import asyncio
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.chat import get_orchestrator
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.model import OpenAIChatModel
from app.assistant.schemas import ChatTurn, RouteSelection
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
        self.received_history = None

    async def select_route(self, _message, current_date, history=None):
        assert current_date
        self.received_history = history
        return self.selection

    async def generate_answer(self, _message, evidence, history=None):
        self.generated += 1
        self.evidence = evidence
        self.received_history = history
        return self.answer


class FakeTools:
    def __init__(self, result=None):
        self.result = result
        self.calls = 0
        self.last_selection = None

    async def execute(self, selection, _message):
        self.calls += 1
        self.last_selection = selection
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


def test_route_selection_passes_configured_reasoning_effort_to_openai():
    class FakeCompletions:
        request = None

        async def create(self, **request):
            self.request = request
            arguments = (
                '{"route":"clarify","date":null,"attendees":null,"room":null,'
                '"query":null,"day_of_week":null,"day_type":null,"categories":[],'
                '"missing_information":["question"]}'
            )
            tool_call = SimpleNamespace(
                function=SimpleNamespace(name="select_route", arguments=arguments)
            )
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(tool_calls=[tool_call])
            )])

    completions = FakeCompletions()
    model = object.__new__(OpenAIChatModel)
    model.settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        openai_model="gpt-6-luna",
        openai_reasoning_effort="none",
    )
    model.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = asyncio.run(model.select_route("Hola", "2026-10-18"))

    assert result.route == "clarify"
    assert completions.request["reasoning_effort"] == "none"


def test_api_only_rooms_uses_safe_room_model():
    client = FakeLogicClient(rooms=[Room(name="Portal", min_players=2, max_players=6)])
    tools = make_tools(client)
    model = FakeModel(RouteSelection(route="get_rooms"))
    answer = asyncio.run(AssistantOrchestrator(model, tools).reply("¿Qué salas tienen?"))

    assert answer.startswith("¡Hola! Soy Nox, asistente virtual de Logic Escape Room.")
    assert model.answer in answer
    assert answer.endswith("\u00bfTe puedo ayudar en algo m\u00e1s?")
    assert model.evidence["mode"] == "api_only"
    assert model.evidence["api_facts"] == [{"name": "Portal", "min_players": 2, "max_players": 6}]
    assert "room_id" not in str(model.evidence)


def test_answer_to_short_message_ends_with_an_inviting_question():
    result = ToolOutcome(AssistantEvidence("api_only", api_facts=[{"price": 50000}]))
    model = FakeModel(RouteSelection(route="get_rates"), "Estos son los precios disponibles.")

    answer = asyncio.run(
        AssistantOrchestrator(model, FakeTools(result)).reply("precios", [
            ChatTurn(role="user", content="Hola"),
            ChatTurn(role="assistant", content="?Hola! Soy Nox."),
        ])
    )

    assert answer == "Estos son los precios disponibles. \u00bfTe puedo ayudar en algo m\u00e1s?"


def test_relative_tomorrow_fills_missing_date_and_only_asks_for_room():
    model = FakeModel(RouteSelection(
        route="clarify", missing_information=["date", "room"]
    ))

    answer = asyncio.run(AssistantOrchestrator(model, FakeTools()).reply(
        "Hola, me gustar?a reservar una sala para dos personas para ma\u00f1ana"
    ))

    assert "fecha" not in answer.casefold()
    assert "sala" in answer.casefold()
    from app.assistant.orchestrator import _fill_relative_date
    expected_date = date(2026, 10, 18)
    resolved = _fill_relative_date(
        RouteSelection(route="clarify", missing_information=["date", "room"]),
        "para ma\u00f1ana",
        date(2026, 10, 17),
    )
    assert resolved.date == expected_date
    assert resolved.missing_information == ["room"]


def test_contact_details_reply_continues_reservation_instead_of_generic_clarification():
    model = FakeModel(RouteSelection(route="clarify", missing_information=["question"]))
    history = [
        ChatTurn(role="user", content="Quiero reservar ma\u00f1ana para dos personas"),
        ChatTurn(role="assistant", content="\u00bfQu\u00e9 sala tienes en mente?"),
        ChatTurn(role="user", content="Manicomio"),
        ChatTurn(role="assistant", content=(
            "El horario de las 17:00 sigue disponible. \u00bfMe compartes tu nombre y n\u00famero de celular para continuar?"
        )),
    ]
    settings = Settings(
        _env_file=None,
        logic_payment_method_for_deposits="Bre-B",
        logic_bre_b_key="0091786913",
        logic_typical_deposit_per_room_cop=50000,
        logic_operational_values_verified=True,
    )
    tools = FakeTools()
    tools.settings = settings

    answer = asyncio.run(AssistantOrchestrator(model, tools).reply(
        "Ernesto Garc\u00eda 3121231234", history
    ))

    assert "Perfecto, revisa los datos de tu solicitud" in answer
    assert "Manicomio" in answer and "personas: 2" in answer
    assert "Ernesto Garc\u00eda" in answer and "17:00" in answer
    assert "Bre-B" in answer and "0091786913" in answer
    assert "$50.000 COP" in answer
    assert "comprobante" in answer
    assert model.generated == 0


def test_name_only_reply_prompts_for_cellphone_and_keeps_the_name():
    history = [ChatTurn(role="assistant", content="\u00bfA nombre de qui\u00e9n ser\u00eda la solicitud?")]
    answer = asyncio.run(AssistantOrchestrator(
        FakeModel(RouteSelection(route="clarify", missing_information=["question"])),
        FakeTools(),
    ).reply("Daniela Vivas", history))

    assert "Daniela Vivas" in answer
    assert "celular" in answer


def test_phone_after_name_is_collected_completes_the_reservation_summary():
    model = FakeModel(RouteSelection(route="clarify", missing_information=["question"]))
    history = [
        ChatTurn(role="user", content="Quiero reservar ma?ana para dos personas"),
        ChatTurn(role="assistant", content="?Qu? sala tienes en mente?"),
        ChatTurn(role="user", content="Manicomio"),
        ChatTurn(role="assistant", content=(
            "El horario de las 17:00 sigue disponible para ma?ana, 19 de octubre, "
            "para dos personas. ?A nombre de qui?n ser?a la solicitud?"
        )),
        ChatTurn(role="user", content="Daniela Vivas"),
        ChatTurn(role="assistant", content="?Me compartes tu n?mero de celular para continuar?"),
    ]
    tools = FakeTools()
    tools.settings = Settings(
        _env_file=None,
        logic_payment_method_for_deposits="Bre-B",
        logic_bre_b_key="0091786913",
        logic_typical_deposit_per_room_cop=50000,
        logic_operational_values_verified=True,
    )

    answer = asyncio.run(AssistantOrchestrator(model, tools).reply("3121231234", history))

    assert "Daniela Vivas" in answer
    assert "3121231234" in answer
    assert "0091786913" in answer
    assert "17:00" in answer


def test_contact_reply_uses_full_payment_confirmation_when_customer_already_chose_total():
    history = [
        ChatTurn(role="user", content="Pagar? el total de la reserva"),
        ChatTurn(role="assistant", content="?Me compartes tu nombre y celular?"),
    ]
    answer = asyncio.run(AssistantOrchestrator(
        FakeModel(RouteSelection(route="clarify", missing_information=["question"])),
        FakeTools(),
    ).reply("Ernesto Garc?a 3121231234", history))

    assert "pago total" in answer and "reserva por este chat" in answer
    assert "pago del abono" not in answer


def test_time_choice_after_availability_offer_keeps_room_and_date_context():
    from app.assistant.orchestrator import _recover_time_choice

    history = [
        ChatTurn(role="user", content="Quiero una sala para ma?ana para dos personas"),
        ChatTurn(role="assistant", content="?Qu? sala tienes en mente?"),
        ChatTurn(role="user", content="Manicomio"),
        ChatTurn(role="assistant", content=(
            "Para Manicomio ma?ana, 19 de octubre, hay horarios disponibles a las 17:00, "
            "18:30 y 20:00. ?Cu?l prefieres para las dos personas?"
        )),
    ]

    selection = _recover_time_choice(
        RouteSelection(route="clarify", missing_information=["question"]),
        "a las 5 pm por favor",
        history,
        date(2026, 10, 18),
    )

    assert selection.route == "get_availability"
    assert selection.date == date(2026, 10, 19)
    assert selection.room == "Manicomio"


def test_time_choice_continues_with_live_availability_route():
    history = [
        ChatTurn(role="user", content="Quiero ir ma?ana para dos personas"),
        ChatTurn(role="assistant", content="?Qu? sala tienes en mente?"),
        ChatTurn(role="user", content="Manicomio"),
        ChatTurn(role="assistant", content=(
            "Para Manicomio ma?ana, 19 de octubre, hay horarios disponibles a las 17:00. "
            "?Cu?l prefieres para las dos personas?"
        )),
    ]
    model = FakeModel(RouteSelection(route="clarify", missing_information=["question"]))
    tools = FakeTools(ToolOutcome(AssistantEvidence(
        "api_only", api_facts=[{"date": "2026-10-19", "rooms": [{"room_name": "Manicomio", "slots": [
            {"start": "17:00", "available": True},
        ]}]}],
    )))

    asyncio.run(AssistantOrchestrator(model, tools).reply("a las 5 pm por favor", history))

    assert tools.calls == 1
    assert tools.last_selection.route == "get_availability"
    assert tools.last_selection.date == date(2026, 10, 19)
    assert tools.last_selection.room == "Manicomio"


def test_time_choice_recognizes_alternate_availability_wording():
    from app.assistant.orchestrator import _recover_time_choice

    history = [
        ChatTurn(role="user", content="Quiero reservar ma?ana para dos personas"),
        ChatTurn(role="assistant", content="?Qu? sala tienes en mente?"),
        ChatTurn(role="user", content="Manicomio"),
        ChatTurn(role="assistant", content=(
            "Para ma?ana, 19 de octubre, la sala Manicomio tiene disponibles las 17:00 y 18:30. "
            "?Cu?l horario prefieres?"
        )),
    ]

    result = _recover_time_choice(
        RouteSelection(route="clarify", missing_information=["question"]),
        "5 pm",
        history,
        date(2026, 10, 18),
    )

    assert result.route == "get_availability"
    assert result.date == date(2026, 10, 19)
    assert result.room == "Manicomio"


def test_time_choice_keeps_room_echoed_in_offer_when_client_named_it_up_front():
    from app.assistant.orchestrator import _recover_time_choice

    history = [
        ChatTurn(role="user", content="Quiero reservar para manana Manicomio para dos personas"),
        ChatTurn(role="assistant", content=(
            "Para manana, 19 de octubre, Manicomio tiene disponibilidad para dos personas "
            "a las 17:00, 18:30 y 20:00. ?Cual horario prefieren?"
        )),
    ]

    result = _recover_time_choice(
        RouteSelection(route="clarify", missing_information=["room"]),
        "5 pm",
        history,
        date(2026, 10, 18),
    )

    assert result.route == "get_availability"
    assert result.date == date(2026, 10, 19)
    assert result.room == "Manicomio"


def test_time_choice_without_slot_offer_does_not_override_route():
    from app.assistant.orchestrator import _recover_time_choice

    selection = RouteSelection(route="clarify", missing_information=["question"])
    result = _recover_time_choice(
        selection,
        "a las 5 pm por favor",
        [ChatTurn(role="assistant", content="?Qu? informaci?n quieres consultar?")],
        date(2026, 10, 18),
    )

    assert result == selection


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


def test_first_response_greets_and_introduces_even_when_clarifying():
    model = FakeModel(RouteSelection(
        route="clarify", missing_information=["question"]
    ))

    answer = asyncio.run(AssistantOrchestrator(model, FakeTools()).reply("Hola buenos d\u00edas"))

    assert answer.startswith("\u00a1Hola! Soy Nox, asistente virtual de Logic Escape Room. Con gusto te ayudo")
    assert "¿Qué informaci\u00f3n de Logic quieres consultar?" in answer


def test_missing_quote_date_or_attendees_clarifies_without_calling_tools():
    selection = RouteSelection(route="get_quote", date=None, attendees=4)
    model = FakeModel(selection)
    tools = FakeTools()

    answer = asyncio.run(AssistantOrchestrator(model, tools).reply("¿Cuánto para cuatro?"))

    assert answer == "\u00a1Hola! Soy Nox, asistente virtual de Logic Escape Room. Con gusto te ayudo \U0001f642. \u00bfPara qu\u00e9 fecha lo est\u00e1s consultando?"
    assert tools.calls == 0
    assert model.generated == 0


def test_phone_after_initial_room_choice_completes_payment_summary():
    history = [
        ChatTurn(role="user", content="Quiero reservar para ma\u00f1ana Manicomio para dos personas"),
        ChatTurn(role="assistant", content=(
            "Para ma\u00f1ana, 19 de octubre, Manicomio tiene disponibilidad para dos personas "
            "a las 17:00, 18:30 y 20:00. \u00bfCu\u00e1l horario prefieren?"
        )),
        ChatTurn(role="user", content="para las 5 por favor"),
        ChatTurn(role="assistant", content=(
            "Claro que s\u00ed, las 17:00 para ma\u00f1ana siguen disponibles para dos personas. "
            "\u00bfA nombre de qui\u00e9n ser\u00eda la solicitud?"
        )),
        ChatTurn(role="user", content="Daniela Rodriguez"),
        ChatTurn(role="assistant", content="\u00bfMe compartes tu n\u00famero de celular para continuar?"),
    ]
    tools = FakeTools()
    tools.settings = Settings(
        _env_file=None,
        logic_payment_method_for_deposits="Bre-B",
        logic_bre_b_key="0091786913",
        logic_typical_deposit_per_room_cop=50000,
        logic_operational_values_verified=True,
    )

    answer = asyncio.run(AssistantOrchestrator(
        FakeModel(RouteSelection(route="clarify", missing_information=["question"])), tools
    ).reply("3121231234", history))

    assert "Perfecto, revisa los datos de tu solicitud" in answer
    assert "Manicomio" in answer and "personas: 2" in answer
    assert "17:00" in answer and "Daniela Rodriguez" in answer
    assert "3121231234" in answer
    assert "Bre-B" in answer and "0091786913" in answer
    assert "$50.000 COP" in answer
    assert "transferida" in answer and "confirmar la reserva" in answer


def test_price_question_after_reservation_summary_is_not_mistaken_for_contact_details():
    summary = (
        "\u2728 Perfecto, revisa los datos de tu solicitud:\n"
        "\U0001f465 N\u00famero de personas: 2\n"
        "\U0001f575 Sala / tem\u00e1tica: Manicomio\n"
        "\U0001f4c5 Fecha: 19 de octubre de 2026\n"
        "\u23f0 Hora: 17:00\n"
        "\U0001f9d1 Nombre de quien solicita: Fernanda Rojas\n"
        "\U0001f44d N\u00famero de contacto: 3121231234\n\n"
        "Para continuar, puedes enviar el abono. \u00bfQuieres que te aclare algo sobre el proceso?"
    )
    history = [
        ChatTurn(role="user", content="Quiero reservar para ma\u00f1ana Manicomio para dos personas"),
        ChatTurn(role="assistant", content=summary),
    ]
    result = ToolOutcome(AssistantEvidence("api_only", api_facts=[{"price_per_person": 50000}]))
    model = FakeModel(RouteSelection(route="get_rates"), "Para dos personas, el precio entre semana es 100.000 COP.")

    answer = asyncio.run(AssistantOrchestrator(model, FakeTools(result)).reply(
        "cual es el precio por los dos?", history
    ))

    assert "precio entre semana" in answer
    assert "Fernanda Rojas" not in answer
    assert "Perfecto, revisa los datos" not in answer
    assert model.generated == 1


def test_conversation_history_is_available_for_reference_resolution():
    history = [ChatTurn(role="user", content="Me interesa Portal para este sábado.")]
    result = ToolOutcome(
        AssistantEvidence("api_only", api_facts=[{"name": "Portal"}])
    )
    model = FakeModel(RouteSelection(route="get_rooms"))

    answer = asyncio.run(
        AssistantOrchestrator(model, FakeTools(result)).reply("¿Y cuánto cuesta?", history)
    )

    assert answer == model.answer + " \u00bfTe puedo ayudar en algo m\u00e1s?"
    assert model.received_history == history


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
    assert not any("no confirma una reserva" in warning.casefold() for warning in model.evidence["warnings"])


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


def test_verified_deposit_configuration_is_included_for_payment_questions():
    policy = KnowledgeSearchResult(
        chunk_id="deposit:v1",
        document_id="policies.deposits-and-payments",
        category="payments",
        text="El abono habitual se consulta en la configuración operativa verificada y se entiende por sala.",
        source_path="policies/deposits-and-payments.md",
        metadata={"requires_human_for_exceptions": True, "validation_status": "approved"},
        distance=0.2,
    )
    settings = Settings(
        _env_file=None,
        logic_typical_deposit_per_room_cop=50000,
        logic_operational_values_verified=True,
    )
    tools = AssistantTools(
        settings=settings,
        knowledge_search=lambda *_args, **_kwargs: [policy],
    )
    model = FakeModel(RouteSelection(
        route="search_business_knowledge",
        query="abono por sala para reservar",
        categories=["payments"],
    ))

    asyncio.run(
        AssistantOrchestrator(model, tools).reply("¿Tengo que pagar para reservar?")
    )

    assert model.evidence["operational_facts"] == [{
        "name": "abono_habitual",
        "amount": 50000,
        "currency": "COP",
        "scope": "por sala a reservar",
        "source": "configuración operativa verificada",
    }]
    assert model.evidence["mode"] == "rag_and_operational"
    assert not any("revisión humana" in warning.casefold() for warning in model.evidence["warnings"])


def test_unverified_deposit_is_not_added_to_operational_evidence():
    settings = Settings(
        _env_file=None,
        logic_typical_deposit_per_room_cop=50000,
        logic_operational_values_verified=False,
    )
    result = KnowledgeSearchResult(
        chunk_id="deposit:v1",
        document_id="policies.deposits-and-payments",
        category="payments",
        text="El importe se consulta en configuración verificada.",
        source_path="policies/deposits-and-payments.md",
        metadata={},
        distance=0.2,
    )
    tools = AssistantTools(
        settings=settings,
        knowledge_search=lambda *_args, **_kwargs: [result],
    )
    model = FakeModel(RouteSelection(
        route="search_business_knowledge", categories=["payments"]
    ))

    asyncio.run(AssistantOrchestrator(model, tools).reply("¿Cuánto es el abono?"))

    assert model.evidence["operational_facts"] == []
    assert "no está marcado como verificado" in model.evidence["warnings"][0].casefold()


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

    assert answer.startswith("¡Hola! Soy Nox, asistente virtual de Logic Escape Room.")
    assert model.answer in answer
    assert answer.endswith("\u00bfTe puedo ayudar en algo m\u00e1s?")
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
        async def reply(self, _message, history=None):
            assert history is not None and len(history) == 1
            return "¡Hola! ¿Qué te gustaría saber?"

    async def override_orchestrator():
        yield StubOrchestrator()

    app.dependency_overrides[get_orchestrator] = override_orchestrator
    try:
        response = TestClient(app).post("/api/chat", json={
            "message": "¿cuánto cuesta?",
            "history": [{"role": "user", "content": "Quiero ir el sábado"}],
        })
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"answer": "¡Hola! ¿Qué te gustaría saber?"}

