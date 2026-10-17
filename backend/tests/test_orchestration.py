import asyncio
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.chat import get_orchestrator
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.schemas import RouteSelection
from app.assistant.tools import AssistantTools, ToolOutcome, AssistantEvidence
from app.core.config import Settings
from app.logic_api.errors import LogicApiUnavailable
from app.logic_api.models import (
    Availability,
    AvailabilityRoom,
    AvailabilitySlot,
    OpeningHours,
    Quote,
    Rate,
    Room,
)
from app.main import app
from app.rag.models import KnowledgeSearchResult


class FakeModel:
    def __init__(self, selection, answer="Con base en la información consultada."):
        self.selection = selection
        self.answer = answer
        self.evidence = None
        self.generated = 0

    async def select_route(self, _message, current_date):
        assert current_date
        return self.selection

    async def generate_answer(self, _message, evidence):
        self.generated += 1
        self.evidence = evidence
        return self.answer


class FakeTools:
    def __init__(self, result=None):
        self.result = result
        self.calls = 0

    async def execute(self, _selection, _message):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeLogicClient:
    def __init__(self, *, rooms=None, rates=None, hours=None, quote=None, availability=None, error=None):
        self.rooms = rooms or []
        self.rates = rates or []
        self.hours = hours or []
        self.quote = quote
        self.availability = availability
        self.error = error
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get_rooms(self):
        self.calls.append("get_rooms")
        if self.error:
            raise self.error
        return self.rooms

    async def get_rates(self, day_type=None):
        self.calls.append(("get_rates", day_type))
        return self.rates

    async def get_opening_hours(self):
        self.calls.append("get_opening_hours")
        return self.hours

    async def get_quote(self, requested_date, attendees):
        self.calls.append(("get_quote", requested_date, attendees))
        return self.quote

    async def get_availability(self, requested_date):
        self.calls.append(("get_availability", requested_date))
        return self.availability


def make_tools(client, *, knowledge_results=None):
    return AssistantTools(
        settings=Settings(_env_file=None, logic_api_base_url="https://logic.test"),
        logic_client_factory=lambda _settings: client,
        knowledge_search=lambda *_args, **_kwargs: knowledge_results or [],
    )


def test_api_only_rooms_uses_safe_room_model():
    client = FakeLogicClient(rooms=[Room(name="Portal", min_players=2, max_players=6)])
    tools = make_tools(client)
    model = FakeModel(RouteSelection(route="get_rooms"))
    answer = asyncio.run(AssistantOrchestrator(model, tools).reply("¿Qué salas tienen?"))

    assert answer == model.answer
    assert model.evidence["mode"] == "api_only"
    assert model.evidence["api_facts"] == [{"name": "Portal", "min_players": 2, "max_players": 6}]
    assert "room_id" not in str(model.evidence)


def test_quote_calls_quote_endpoint_with_validated_date_and_attendees():
    quote = Quote(
        date=date(2026, 10, 24), day_type="weekend", is_holiday=False,
        players=5, currency="COP", price_per_person=42000, total=210000,
    )
    client = FakeLogicClient(quote=quote)
    selection = RouteSelection(route="get_quote", date=date(2026, 10, 24), attendees=5)
    model = FakeModel(selection)

    asyncio.run(AssistantOrchestrator(model, make_tools(client)).reply("¿Cuánto cuesta para cinco?"))

    assert client.calls == [("get_quote", date(2026, 10, 24), 5)]
    assert model.evidence["api_facts"][0]["total"] == 210000


def test_missing_quote_date_or_attendees_clarifies_without_calling_tools():
    selection = RouteSelection(route="get_quote", date=None, attendees=4)
    model = FakeModel(selection)
    tools = FakeTools()

    answer = asyncio.run(AssistantOrchestrator(model, tools).reply("¿Cuánto para cuatro?"))

    assert answer == "¿Para qué fecha lo estás consultando?"
    assert tools.calls == 0
    assert model.generated == 0


def test_availability_is_live_and_internal_room_id_is_not_sent_to_model():
    availability = Availability(
        date=date(2026, 10, 24), day_type="weekend", is_holiday=False,
        timezone="America/Bogota", server_now=datetime.fromisoformat("2026-10-17T12:00:00-05:00"),
        min_advance_minutes=0,
        rooms=(AvailabilityRoom(
            room_id="internal-portal-id", name="Portal", slots=(
                AvailabilitySlot(start=datetime.fromisoformat("2026-10-24T16:30:00-05:00"), available=True),
            ),
        ),),
    )
    client = FakeLogicClient(availability=availability)
    selection = RouteSelection(route="get_availability", date=date(2026, 10, 24), room="Portal")
    model = FakeModel(selection)

    asyncio.run(AssistantOrchestrator(model, make_tools(client)).reply("¿Hay espacio en Portal?"))

    assert client.calls == [("get_availability", date(2026, 10, 24))]
    assert model.evidence["api_facts"][0]["rooms"] == [
        {"room_name": "Portal", "slots": [{"start": "16:30", "available": True}]}
    ]
    assert "internal-portal-id" not in str(model.evidence)
    assert "no confirma una reserva" in model.evidence["warnings"][0]


def test_rag_only_policy_includes_traceable_source_metadata():
    result = KnowledgeSearchResult(
        chunk_id="faq:v1", document_id="experience.birthdays-and-cafeteria",
        category="faq", text="El uso de la cafetería es libre.",
        source_path="experience/birthdays-and-cafeteria.md",
        metadata={"validation_status": "approved", "requires_api_data": False},
        distance=0.31,
    )
    selection = RouteSelection(route="search_business_knowledge", query="uso de cafetería")
    model = FakeModel(selection)
    tools = make_tools(FakeLogicClient(), knowledge_results=[result])

    asyncio.run(AssistantOrchestrator(model, tools).reply("¿Cuánto tiempo puedo estar en la cafetería?"))

    assert model.evidence["mode"] == "rag_only"
    assert model.evidence["rag_facts"][0]["source_path"] == "experience/birthdays-and-cafeteria.md"
    assert model.evidence["rag_facts"][0]["validation_status"] == "approved"


def test_rag_without_evidence_escalates_without_generating_an_answer():
    selection = RouteSelection(route="search_business_knowledge", query="política de mascotas")
    model = FakeModel(selection)
    tools = make_tools(FakeLogicClient())

    answer = asyncio.run(
        AssistantOrchestrator(model, tools).reply("¿Puedo llevar una mascota?")
    )

    assert "no encuentro una política documentada" in answer.casefold()
    assert "confirmación del equipo" in answer.casefold()
    assert model.generated == 0


def test_api_and_rag_exception_keeps_api_limit_and_requires_human_review():
    room = Room(name="Portal", min_players=2, max_players=6)
    policy = KnowledgeSearchResult(
        chunk_id="minors:v1", document_id="policies.minors-and-room-limits",
        category="age_policy", text="La excepción de Portal permite hasta siete en total, contando al adulto.",
        source_path="policies/minors-and-room-limits.md",
        metadata={"requires_human_for_exceptions": True, "validation_status": "approved"},
        distance=0.22,
    )
    client = FakeLogicClient(rooms=[room])
    selection = RouteSelection(
        route="check_room_policy", room="Portal", attendees=7,
        query="Somos siete, ¿podemos jugar?", categories=["age_policy"],
    )
    model = FakeModel(selection, "La capacidad ordinaria es seis; la excepción requiere confirmación humana.")

    answer = asyncio.run(AssistantOrchestrator(
        model, make_tools(client, knowledge_results=[policy])
    ).reply("Somos siete en Portal, ¿podemos jugar?"))

    assert answer == model.answer
    assert model.evidence["mode"] == "api_and_rag"
    assert model.evidence["api_facts"][0]["max_players"] == 6
    assert "supera el máximo ordinario" in model.evidence["warnings"][1]
    assert model.evidence["rag_facts"][0]["source_path"] == "policies/minors-and-room-limits.md"


def test_room_exception_is_not_generalized_when_no_policy_matches():
    client = FakeLogicClient(rooms=[Room(name="Caníbal", max_players=6)])
    selection = RouteSelection(route="check_room_policy", room="Caníbal", query="somos siete")
    model = FakeModel(selection)

    answer = asyncio.run(AssistantOrchestrator(model, make_tools(client)).reply("Somos siete en Caníbal"))

    assert "no encuentro una política documentada" in answer
    assert model.generated == 0


def test_api_timeout_is_mapped_safely_and_not_treated_as_unavailable_slot():
    client = FakeLogicClient(error=LogicApiUnavailable("private upstream details"))
    model = FakeModel(RouteSelection(route="get_rooms"))

    answer = asyncio.run(AssistantOrchestrator(model, make_tools(client)).reply("¿Qué salas hay?"))

    assert "no puedo verificar" in answer
    assert "private upstream details" not in answer
    assert model.generated == 0


def test_chat_endpoint_returns_answer_without_route_or_raw_evidence():
    class StubOrchestrator:
        async def reply(self, _message):
            return "¡Hola! ¿Qué te gustaría saber?"

    async def override_orchestrator():
        yield StubOrchestrator()

    app.dependency_overrides[get_orchestrator] = override_orchestrator
    try:
        response = TestClient(app).post("/api/chat", json={"message": "Hola"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"answer": "¡Hola! ¿Qué te gustaría saber?"}

