import asyncio
from datetime import date, datetime, timedelta
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
        self.route_selected = 0
        self.received_history = None

    async def select_route(self, _message, current_date, history=None):
        assert current_date
        self.route_selected += 1
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
    assert "Portal" in answer
    assert "de 2 a 6 personas" in answer
    assert answer.endswith("¿Cuál sala les interesa?")
    assert client.calls == ["get_rooms"]
    assert model.generated == 0


def test_rooms_and_prices_are_fetched_and_returned_as_three_chat_messages():
    client = FakeLogicClient(
        rooms=[
            Room(name="Portal", description="Aventura en otra dimensión", min_players=2, max_players=6, duration_minutes=60),
            Room(name="Manicomio", description="Suspenso en un hospital", min_players=2, max_players=7, duration_minutes=60),
        ],
        rates=[
            Rate(day_type="weekday", day_label="Entre semana", players=2, price_per_person=50000),
            Rate(day_type="weekday", day_label="Entre semana", players=7, price_per_person=33000),
            Rate(day_type="weekend", day_label="Fin de semana", players=2, price_per_person=57000),
            Rate(day_type="weekend", day_label="Fin de semana", players=7, price_per_person=40000),
        ],
    )
    model = FakeModel(RouteSelection(route="get_rates"))
    orchestrator = AssistantOrchestrator(model, make_tools(client))

    messages = asyncio.run(orchestrator.reply_messages("salas y precios"))

    assert client.calls == ["get_rooms", ("get_rates", None)]
    assert len(messages) == 3
    assert "Portal" in messages[0] and "Manicomio" in messages[0]
    assert "$33.000" in messages[1] and "$50.000" in messages[1]
    assert "$40.000" in messages[1] and "$57.000" in messages[1]
    assert "¿Cuántas personas" in messages[2]
    assert model.generated == 0


def test_location_and_prices_are_answered_as_separate_messages():
    client = FakeLogicClient(rates=[
        Rate(day_type="weekday", day_label="Entre semana", players=2, price_per_person=50000),
        Rate(day_type="weekday", day_label="Entre semana", players=7, price_per_person=33000),
        Rate(day_type="weekend", day_label="Fin de semana", players=2, price_per_person=57000),
        Rate(day_type="weekend", day_label="Fin de semana", players=7, price_per_person=40000),
    ])
    location = KnowledgeSearchResult(
        chunk_id="location:v1",
        document_id="experience.location-and-parking",
        category="faq",
        text="La dirección documentada de Logic Escape Room es Calle 32 #5-72, tercer piso, Tunja, Boyacá, Colombia.",
        source_path="experience/location-and-parking.md",
        metadata={"validation_status": "approved_with_open_issue"},
        distance=0.1,
    )
    settings = Settings(
        _env_file=None,
        logic_api_base_url="https://logic.test",
        logic_map_url="https://maps.example/logic",
    )
    tools = AssistantTools(
        settings=settings,
        logic_client_factory=lambda _settings: client,
        knowledge_search=lambda *_args, **_kwargs: [location],
    )
    model = FakeModel(RouteSelection(route="get_rates"))
    orchestrator = AssistantOrchestrator(model, tools)

    messages = asyncio.run(orchestrator.reply_messages("Hola, dónde es y cuánto cuesta"))

    assert client.calls == [("get_rates", None)]
    assert len(messages) == 3
    assert "Calle 32 #5-72, tercer piso" in messages[0]
    assert "https://maps.example/logic" in messages[0]
    assert "$33.000" in messages[1] and "$50.000" in messages[1]
    assert "$40.000" in messages[1] and "$57.000" in messages[1]
    assert "¿Cuántas personas" in messages[2]
    assert "para qué fecha" in messages[2].casefold()
    assert model.generated == 0


@pytest.mark.parametrize("message", [
    "¿Qué salas tienes disponibles?",
    "¿Cuáles son las opciones de salas?",
    "¿Con qué salas cuentan?",
    "¿Qué experiencias ofrecen?",
])
def test_varied_room_catalog_questions_fetch_current_rooms_without_model_answer(message):
    client = FakeLogicClient(rooms=[
        Room(name="Canibal", description="Terror", min_players=4, max_players=7, duration_minutes=60),
        Room(name="Manicomio", description="Suspenso", min_players=2, max_players=7, duration_minutes=60),
    ])
    model = FakeModel(RouteSelection(route="clarify", missing_information=["question"]))
    orchestrator = AssistantOrchestrator(model, make_tools(client))

    answer = asyncio.run(orchestrator.reply(message, history=[
        ChatTurn(role="user", content="Puedo ir con mis hijos de 9 y 11 años?"),
        ChatTurn(role="assistant", content="¿Irá un adulto con ellos?"),
        ChatTurn(role="user", content="Sí, van conmigo"),
        ChatTurn(role="assistant", content="¿Qué sala tienes en mente?"),
    ]))

    assert client.calls == ["get_rooms"]
    assert "Canibal" in answer and "Manicomio" in answer
    assert "60 minutos" in answer
    assert "¿Cuál sala les interesa?" in answer
    assert "horarios concretos" in answer
    assert model.generated == 0


def test_answer_to_short_message_is_not_forced_to_add_a_generic_question():
    result = ToolOutcome(AssistantEvidence("api_only", api_facts=[{"price": 50000}]))
    model = FakeModel(RouteSelection(route="get_rates"), "Estos son los precios disponibles.")

    answer = asyncio.run(
        AssistantOrchestrator(model, FakeTools(result)).reply("precios", [
            ChatTurn(role="user", content="Hola"),
            ChatTurn(role="assistant", content="?Hola! Soy Nox."),
        ])
    )

    assert answer == "Estos son los precios disponibles."


def test_relative_tomorrow_reservation_checks_availability_before_missing_room():
    model = FakeModel(RouteSelection(
        route="clarify", missing_information=["date", "room"]
    ))
    tools = FakeTools(ToolOutcome(AssistantEvidence(
        "api_only", api_facts=[{"date": "2026-10-19", "rooms": []}]
    )))

    answer = asyncio.run(AssistantOrchestrator(model, tools).reply(
        "Hola, me gustar?a reservar una sala para dos personas para ma\u00f1ana"
    ))

    assert tools.last_selection.route == "get_availability"
    assert tools.last_selection.date == date.today() + timedelta(days=1)
    assert model.generated == 1
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
        ChatTurn(role="user", content="Quiero una sala para manana para dos personas"),
        ChatTurn(role="assistant", content="Que sala tienes en mente?"),
        ChatTurn(role="user", content="Manicomio"),
        ChatTurn(role="assistant", content=(
            "Para Manicomio manana, 19 de octubre, hay horarios disponibles a las 17:00, "
            "18:30 y 20:00. Cual prefieres para las dos personas?"
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


def test_time_choice_recovers_room_from_offer_with_numeric_calendar_date():
    from app.assistant.orchestrator import _recover_time_choice

    history = [
        ChatTurn(role="assistant", content=(
            "Para **Cannibal**, el **31 de octubre de 2026** hay horarios disponibles a "
            "las **15:00, 16:30, 18:00 y 19:30**. Cual prefieres?"
        )),
    ]

    selection = _recover_time_choice(
        RouteSelection(route="clarify", missing_information=["question"]),
        "a las 4:30 de la tarde",
        history,
        date(2026, 10, 18),
    )

    assert selection.route == "get_availability"
    assert selection.date == date(2026, 10, 31)
    assert selection.room == "Cannibal"


def test_time_choice_continues_with_live_availability_route():
    history = [
        ChatTurn(role="user", content="Quiero ir manana para dos personas"),
        ChatTurn(role="assistant", content="Que sala tienes en mente?"),
        ChatTurn(role="user", content="Manicomio"),
        ChatTurn(role="assistant", content=(
            "Para Manicomio manana, 19 de octubre, hay horarios disponibles a las 17:00. "
            "Cual prefieres para las dos personas?"
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


def test_time_choice_recovers_markdown_room_name_from_weekday_offer():
    from app.assistant.orchestrator import _recover_time_choice

    history = [
        ChatTurn(role="user", content="Jumanji"),
        ChatTurn(role="assistant", content=(
            "Claro que sí 🙂. Para **Portal: Jumanji**, el sábado 24 de octubre están "
            "disponibles estos horarios: **3:00 p. m., 6:00 p. m. y 7:30 p. m.** "
            "¿Cuál prefieres?"
        )),
    ]

    result = _recover_time_choice(
        RouteSelection(route="clarify", missing_information=["question"]),
        "A las 3 pm por favor",
        history,
        date(2026, 10, 18),
    )

    assert result.route == "get_availability"
    assert result.date == date(2026, 10, 24)
    assert result.room == "Portal: Jumanji"


@pytest.mark.parametrize("date_phrase", [
    "para el sábado",
    "este sábado",
    "el próximo sábado",
    "el fin de semana",
    "el próximo fin de semana",
])
def test_reservation_intent_with_room_date_and_time_routes_to_live_availability(date_phrase):
    from app.assistant.orchestrator import (
        _fill_relative_date,
        _route_dated_reservation_to_availability,
    )

    today = date(2026, 10, 18)  # Sunday
    message = f"Me gustaría Canibal {date_phrase} a las 4:30"
    selection = RouteSelection(
        route="clarify", room="Canibal", missing_information=["date", "attendees"]
    )

    selection = _fill_relative_date(selection, message, today)
    selection = _route_dated_reservation_to_availability(selection, message)

    assert selection.route == "get_availability"
    assert selection.date == date(2026, 10, 24)
    assert selection.room == "Canibal"
    assert selection.missing_information == []


def test_combined_room_weekday_and_time_resolves_room_from_catalog_and_checks_availability():
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("America/Bogota")).date()
    days_until_saturday = (5 - today.weekday()) % 7 or 7
    saturday = today + timedelta(days=days_until_saturday)
    client = FakeLogicClient(
        rooms=[Room(name="Canibal", min_players=4, max_players=7)],
        availability=Availability(
            date=saturday,
            day_type="weekend",
            is_holiday=False,
            timezone="America/Bogota",
            server_now=datetime.fromisoformat(f"{today.isoformat()}T12:00:00-05:00"),
            min_advance_minutes=0,
            rooms=(AvailabilityRoom(
                room_id="internal-id",
                name="Canibal",
                slots=(AvailabilitySlot(
                    start=datetime.fromisoformat(f"{saturday.isoformat()}T16:30:00-05:00"),
                    available=True,
                ),),
            ),),
        ),
    )
    model = FakeModel(RouteSelection(route="clarify", missing_information=["room"]))

    asyncio.run(AssistantOrchestrator(model, make_tools(client)).reply(
        "Me gustaría Canibal para el sábado a las 4:30"
    ))

    assert client.calls == ["get_rooms", ("get_availability", saturday)]
    assert model.evidence["api_facts"][0]["rooms"][0]["room_name"] == "Canibal"
    assert model.evidence["api_facts"][0]["rooms"][0]["slots"][0]["available"] is True


def test_thematic_room_and_dot_time_use_rag_catalog_and_prior_date_context():
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("America/Bogota")).date()
    days_until_saturday = (5 - today.weekday()) % 7 or 7
    saturday = today + timedelta(days=days_until_saturday)
    months = (
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    )
    client = FakeLogicClient(
        rooms=[Room(name="Portal: Jumanji", min_players=2, max_players=6)],
        availability=Availability(
            date=saturday,
            day_type="weekend",
            is_holiday=False,
            timezone="America/Bogota",
            server_now=datetime.fromisoformat(f"{today.isoformat()}T12:00:00-05:00"),
            min_advance_minutes=0,
            rooms=(AvailabilityRoom(
                room_id="internal-id",
                name="Portal: Jumanji",
                slots=(AvailabilitySlot(
                    start=datetime.fromisoformat(f"{saturday.isoformat()}T15:00:00-05:00"),
                    available=True,
                ),),
            ),),
        ),
    )
    recommendation = KnowledgeSearchResult(
        chunk_id="themes:v1",
        document_id="recommendations.room-difficulty-and-intensity",
        category="faq",
        text="Canibal: terror con sustos. Portal: aventura, publico familiar. Manicomio: suspenso y misterio. La Secta: terror paranormal.",
        source_path="recommendations/room-difficulty-and-intensity.md",
        metadata={"validation_status": "approved_with_open_issue", "requires_api_data": True},
        distance=0.1,
    )
    tools = AssistantTools(
        settings=Settings(_env_file=None, logic_api_base_url="https://logic.test"),
        logic_client_factory=lambda _settings: client,
        knowledge_search=lambda *_args, **_kwargs: [recommendation],
    )
    model = FakeModel(RouteSelection(route="clarify", missing_information=["room", "date"]))
    history = [ChatTurn(
        role="assistant",
        content=(f"Para el sábado {saturday.day} de {months[saturday.month - 1]} de {saturday.year}, "
                 "hay horarios disponibles. ¿Cuál prefieres?"),
    )]

    answer = asyncio.run(AssistantOrchestrator(model, tools).reply(
        "La sala de aventura a las 3.00", history
    ))

    assert client.calls == ["get_rooms", ("get_availability", saturday)]
    assert "Portal: Jumanji: 3:00 p. m." in answer
    assert "horario te sirve" in answer
    assert model.generated == 0


def test_terror_theme_matches_only_api_rooms_with_terror_in_their_rag_description():
    requested_date = date(2026, 10, 31)
    client = FakeLogicClient(
        rooms=[
            Room(name="Canibal", min_players=4, max_players=7),
            Room(name="Manicomio", min_players=2, max_players=7),
            Room(name="Portal: Jumanji", min_players=2, max_players=6),
        ],
        availability=Availability(
            date=requested_date,
            day_type="weekend",
            is_holiday=False,
            timezone="America/Bogota",
            server_now=datetime.fromisoformat("2026-10-18T12:00:00-05:00"),
            min_advance_minutes=0,
            rooms=(
                AvailabilityRoom(
                    room_id="canibal-id", name="Canibal", slots=(
                        AvailabilitySlot(start=datetime.fromisoformat("2026-10-31T15:00:00-05:00"), available=True),
                        AvailabilitySlot(start=datetime.fromisoformat("2026-10-31T18:00:00-05:00"), available=False),
                    ),
                ),
                AvailabilityRoom(
                    room_id="manicomio-id", name="Manicomio", slots=(
                        AvailabilitySlot(start=datetime.fromisoformat("2026-10-31T16:00:00-05:00"), available=True),
                    ),
                ),
                AvailabilityRoom(
                    room_id="portal-id", name="Portal: Jumanji", slots=(
                        AvailabilitySlot(start=datetime.fromisoformat("2026-10-31T17:00:00-05:00"), available=True),
                    ),
                ),
            ),
        ),
    )
    recommendation = KnowledgeSearchResult(
        chunk_id="themes:v1",
        document_id="recommendations.room-difficulty-and-intensity",
        category="faq",
        text="Canibal: terror con sustos. Portal: aventura, publico familiar. Manicomio: suspenso y misterio. La Secta: terror paranormal.",
        source_path="recommendations/room-difficulty-and-intensity.md",
        metadata={"validation_status": "approved_with_open_issue", "requires_api_data": True},
        distance=0.1,
    )
    knowledge_queries = []

    def search_theme_knowledge(query, **_kwargs):
        knowledge_queries.append(query)
        return [] if len(knowledge_queries) == 1 else [recommendation]

    tools = AssistantTools(
        settings=Settings(_env_file=None, logic_api_base_url="https://logic.test"),
        logic_client_factory=lambda _settings: client,
        knowledge_search=search_theme_knowledge,
    )
    model = FakeModel(RouteSelection(
        route="clarify", date=requested_date, missing_information=["room"]
    ))

    answer = asyncio.run(AssistantOrchestrator(model, tools).reply(
        "Me gustaría reservar una sala de terror para el 31 de octubre por favor"
    ))

    assert client.calls == ["get_rooms", ("get_availability", requested_date)]
    assert "Canibal: 3:00 p. m." in answer
    assert "Manicomio" not in answer
    assert "Portal" not in answer
    assert "18:00" not in answer  # unavailable slot is not presented as an option
    assert "horario te sirve" in answer
    assert knowledge_queries == ["terror", "recomendacion tematica sala terror"]
    assert model.generated == 0


def test_thematic_dated_reservation_routes_without_model_extracting_date():
    from app.assistant.orchestrator import _route_thematic_dated_reservation

    result = _route_thematic_dated_reservation(
        RouteSelection(route="clarify", missing_information=["room", "date"]),
        "Me gustaria resrvar una sala de terror para el 31 de octubre por favor",
        date(2026, 10, 18),
    )

    assert result.route == "get_availability"
    assert result.date == date(2026, 10, 31)
    assert result.room is None
    assert result.missing_information == []


def test_themed_next_weekend_checks_room_then_asks_saturday_or_sunday():
    client = FakeLogicClient(rooms=[Room(name="Canibal", min_players=4, max_players=7)])
    recommendation = KnowledgeSearchResult(
        chunk_id="themes:v1",
        document_id="recommendations.room-difficulty-and-intensity",
        category="faq",
        text="Canibal: terror con sustos. Portal: aventura. Manicomio: suspenso.",
        source_path="recommendations/room-difficulty-and-intensity.md",
        metadata={"validation_status": "approved_with_open_issue", "requires_api_data": True},
        distance=0.1,
    )
    knowledge_queries = []

    def search_theme_knowledge(query, **_kwargs):
        knowledge_queries.append(query)
        return [recommendation]

    tools = AssistantTools(
        settings=Settings(_env_file=None, logic_api_base_url="https://logic.test"),
        logic_client_factory=lambda _settings: client,
        knowledge_search=search_theme_knowledge,
    )
    model = FakeModel(RouteSelection(route="clarify", missing_information=["date", "room"]))

    answer = asyncio.run(AssistantOrchestrator(model, tools).reply(
        "Me gustarÃ­a reservar la sala de terror para el prÃ³ximo fin de semana"
    ))

    assert client.calls == ["get_rooms"]
    assert knowledge_queries == ["terror"]
    assert "Canibal" in answer
    assert "s\u00e1bado o el domingo" in answer
    assert model.route_selected == 0
    assert model.generated == 0

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


def test_opening_hours_question_with_specific_day_and_time_uses_live_availability():
    from app.assistant.orchestrator import _route_specific_time_question

    selection = RouteSelection(route="get_opening_hours", day_of_week=1)

    result = _route_specific_time_question(
        selection,
        "\u00bfPodemos ir el lunes a las 8 de la noche?",
        date(2026, 10, 18),
    )

    assert result.route == "get_availability"
    assert result.date == date(2026, 10, 19)
    assert result.day_of_week is None


def test_clarify_with_named_weekday_and_specific_time_uses_live_availability():
    from app.assistant.orchestrator import _route_specific_time_question

    result = _route_specific_time_question(
        RouteSelection(route="clarify", missing_information=["date"]),
        "¿Podemos ir el lunes a las 8 de la noche?",
        date(2026, 10, 18),
    )

    assert result.route == "get_availability"
    assert result.date == date(2026, 10, 19)


def test_room_age_without_adult_uses_structured_room_route():
    from app.assistant.orchestrator import _route_room_age_question

    selection = RouteSelection(
        route="search_business_knowledge", room="Manicomio", categories=["age_policy"]
    )

    result = _route_room_age_question(
        selection, "\u00bfQu\u00e9 edad m\u00ednima tiene Manicomio para entrar sin adulto?"
    )

    assert result.route == "get_rooms"
    assert result.room == "Manicomio"


def test_named_room_age_question_executes_structured_room_route():
    model = FakeModel(RouteSelection(
        route="search_business_knowledge", room="Manicomio", categories=["age_policy"]
    ))
    tools = FakeTools(ToolOutcome(AssistantEvidence(
        "api_only", api_facts=[{"name": "Manicomio", "minimum_age_without_adult": 14}]
    )))

    asyncio.run(AssistantOrchestrator(model, tools).reply(
        "\u00bfQu\u00e9 edad m\u00ednima tiene Manicomio para entrar sin adulto?"
    ))

    assert tools.last_selection.route == "get_rooms"


def test_past_availability_date_is_detected_before_calling_api():
    from app.assistant.orchestrator import _fill_relative_date, _past_availability_date

    selection = _fill_relative_date(
        RouteSelection(route="get_availability"),
        "Quiero disponibilidad para ayer en Manicomio",
        date(2026, 10, 18),
    )

    assert selection.date == date(2026, 10, 17)
    assert _past_availability_date(selection, date(2026, 10, 18))


def test_past_availability_request_is_answered_without_upstream_call():
    model = FakeModel(RouteSelection(route="get_availability", date=date(2020, 1, 1)))
    tools = FakeTools()

    answer = asyncio.run(AssistantOrchestrator(model, tools).reply(
        "Quiero disponibilidad para ayer en Manicomio"
    ))

    assert "Esa fecha ya pasó" in answer
    assert tools.calls == 0


def test_dated_reservation_checks_live_availability_before_asking_for_missing_details():
    model = FakeModel(RouteSelection(
        route="clarify", missing_information=["room", "attendees"]
    ))
    tools = FakeTools(ToolOutcome(AssistantEvidence(
        "api_only",
        api_facts=[{"date": "2026-10-19", "rooms": [{
            "room_name": "Manicomio",
            "slots": [{"start": "17:00", "available": True}],
        }]}],
    )))

    asyncio.run(AssistantOrchestrator(model, tools).reply(
        "Quiero reservar Manicomio para mañana, somos dos."
    ))

    assert tools.calls == 2  # read the safe room catalog, then check live availability
    assert tools.last_selection.route == "get_availability"
    assert tools.last_selection.date == date.today() + timedelta(days=1)


def test_clarification_without_dated_reservation_intent_stays_clarification():
    from app.assistant.orchestrator import _route_dated_reservation_to_availability

    selection = RouteSelection(
        route="clarify", date=date(2026, 10, 19), missing_information=["question"]
    )

    assert _route_dated_reservation_to_availability(
        selection, "¿Qué salas tienen?"
    ) == selection


def test_past_availability_request_from_clarify_route_asks_for_future_date():
    model = FakeModel(RouteSelection(
        route="clarify", missing_information=["question"]
    ))
    tools = FakeTools()

    answer = asyncio.run(AssistantOrchestrator(model, tools).reply(
        "Quiero disponibilidad para ayer en Manicomio."
    ))

    assert "fecha futura" in answer.casefold()
    assert tools.calls == 0


def test_split_large_group_price_question_routes_to_pricing_knowledge():
    from app.assistant.orchestrator import _route_large_group_split_pricing_to_knowledge

    selection = _route_large_group_split_pricing_to_knowledge(
        RouteSelection(route="get_rates"),
        "Para 8 personas en dos salas, ¿nos cobran más por persona que si fuéramos 7?",
    )

    assert selection.route == "search_business_knowledge"
    assert selection.categories == ["pricing"]


def test_room_capacity_question_uses_api_even_if_model_selected_rag():
    from app.assistant.orchestrator import _route_room_capacity_question_to_api

    selection = _route_room_capacity_question_to_api(
        RouteSelection(
            route="search_business_knowledge", room="Manicomio", attendees=8,
            categories=["pricing"],
        ),
        "¿Se puede reservar Manicomio para 8 personas en una sola sala?",
    )

    assert selection.route == "get_rooms"
    assert selection.room == "Manicomio"


def test_group_price_without_exact_date_uses_reference_rates():
    from app.assistant.orchestrator import _route_price_question_without_exact_date_to_rates

    selection = _route_price_question_without_exact_date_to_rates(
        RouteSelection(route="clarify", attendees=4, missing_information=["date"]),
        "Somos 4, ¿cuánto pagaríamos el sábado?",
    )

    assert selection.route == "get_rates"
    assert selection.attendees == 4


def test_price_follow_up_weekday_uses_attendee_context_and_reference_rates():
    client = FakeLogicClient(rates=[
        Rate(day_type="weekday", day_label="Entre semana", players=2, price_per_person=50000),
        Rate(day_type="weekday", day_label="Entre semana", players=7, price_per_person=33000),
        Rate(day_type="weekend", day_label="Fin de semana", players=2, price_per_person=57000),
        Rate(day_type="weekend", day_label="Fin de semana", players=7, price_per_person=40000),
    ])
    model = FakeModel(RouteSelection(route="clarify"))
    history = [
        ChatTurn(role="user", content="salas y precios"),
        ChatTurn(role="assistant", content="¿Cuántas personas serían?"),
        ChatTurn(role="user", content="Seríamos 7"),
        ChatTurn(
            role="assistant",
            content="Para 7 personas necesito la fecha para verificar la tarifa vigente. ¿Qué día tienen pensado venir?",
        ),
    ]

    answer = asyncio.run(AssistantOrchestrator(model, make_tools(client)).reply("El jueves", history))

    assert "7 personas" in answer
    assert "$33.000 COP por persona" in answer
    assert "entre semana" in answer
    assert "fecha exacta" in answer
    assert client.calls == [("get_rates", "weekday")]
    assert model.generated == 0


def test_price_follow_up_exact_date_uses_quote_endpoint_and_remembers_group_size():
    requested_date = date(2026, 10, 22)
    quote = Quote(
        date=requested_date,
        day_type="weekday",
        is_holiday=False,
        players=7,
        currency="COP",
        price_per_person=33000,
        total=231000,
    )
    client = FakeLogicClient(quote=quote)
    model = FakeModel(RouteSelection(route="clarify"))
    history = [
        ChatTurn(role="user", content="Salas y precios"),
        ChatTurn(role="assistant", content="¿Cuántas personas serían?"),
        ChatTurn(role="user", content="Seríamos 7"),
        ChatTurn(
            role="assistant",
            content="Para 7 personas necesito la fecha para verificar la tarifa vigente. ¿Qué día tienen pensado venir?",
        ),
        ChatTurn(role="user", content="El jueves"),
        ChatTurn(
            role="assistant",
            content="Para 7 personas, la tarifa entre semana es de $33.000 COP por persona. Si me dices la fecha exacta, puedo consultar la disponibilidad.",
        ),
    ]

    answer = asyncio.run(AssistantOrchestrator(model, make_tools(client)).reply(
        "El jueves 22 de octubre", history
    ))

    assert "7 personas" in answer
    assert "$231.000 COP" in answer
    assert "$33.000 COP por persona" in answer
    assert client.calls == [("get_quote", requested_date, 7)]
    assert model.generated == 0


def test_price_follow_up_attendee_answer_keeps_price_intent_and_uses_group_rates():
    client = FakeLogicClient(rates=[
        Rate(day_type="weekday", day_label="Entre semana", players=2, price_per_person=50000),
        Rate(day_type="weekday", day_label="Entre semana", players=4, price_per_person=40000),
        Rate(day_type="weekday", day_label="Entre semana", players=7, price_per_person=33000),
        Rate(day_type="weekend", day_label="Fin de semana", players=2, price_per_person=57000),
        Rate(day_type="weekend", day_label="Fin de semana", players=4, price_per_person=48000),
        Rate(day_type="weekend", day_label="Fin de semana", players=7, price_per_person=40000),
    ])
    model = FakeModel(RouteSelection(route="clarify"))
    history = [
        ChatTurn(role="user", content="¿Qué precio tienen?"),
        ChatTurn(
            role="assistant",
            content="Entre semana el precio va de $33.000 a $50.000 COP por persona; fines de semana, de $40.000 a $57.000 COP por persona. ¿Cuántas personas serían?",
        ),
    ]

    answer = asyncio.run(AssistantOrchestrator(model, make_tools(client)).reply(
        "Seríamos 4", history
    ))

    assert "4 personas" in answer
    assert "entre semana (lunes a jueves): $40.000 COP por persona" in answer
    assert "fin de semana o festivo: $48.000 COP por persona" in answer
    assert "fecha exacta" in answer
    assert client.calls == [("get_rates", None)]
    assert model.generated == 0


def test_explicit_availability_question_overrides_previous_price_context():
    requested_date = date(2026, 10, 31)
    availability = Availability(
        date=requested_date,
        day_type="weekend",
        is_holiday=False,
        timezone="America/Bogota",
        server_now=datetime.fromisoformat("2026-10-18T12:00:00-05:00"),
        min_advance_minutes=0,
        rooms=(AvailabilityRoom(
            room_id="cannibal",
            name="Cannibal",
            slots=(AvailabilitySlot(
                start=datetime.fromisoformat("2026-10-31T15:00:00-05:00"),
                available=True,
            ),),
        ),),
    )
    client = FakeLogicClient(
        rooms=[Room(name="Cannibal", min_players=4, max_players=7)],
        availability=availability,
    )
    model = FakeModel(RouteSelection(
        route="get_quote",
        date=requested_date,
        attendees=4,
    ))
    history = [
        ChatTurn(role="user", content="¿Qué precio tienen?"),
        ChatTurn(role="assistant", content="¿Cuántas personas serían?"),
        ChatTurn(role="user", content="Seríamos 4"),
        ChatTurn(
            role="assistant",
            content="Para 4 personas, la tarifa de fin de semana es $46.000 COP por persona. Si me dices la fecha exacta, consulto el valor total para el grupo.",
        ),
        ChatTurn(
            role="user",
            content="¿Qué disponibilidad tienes para la sala Caníbal para el sábado 31 de octubre?",
        ),
        ChatTurn(
            role="assistant",
            content="Para 4 personas el 31/10/2026, el total es $184.000 COP. ¿Te puedo ayudar en algo más?",
        ),
    ]

    asyncio.run(AssistantOrchestrator(model, make_tools(client)).reply(
        "¿Qué disponibilidad hay en la fecha del sábado 31 de octubre?",
        history,
    ))

    assert client.calls == ["get_rooms", ("get_availability", requested_date)]
    assert model.evidence["api_facts"][0]["rooms"][0]["room_name"] == "Cannibal"
    assert model.generated == 1


def test_price_question_without_group_size_uses_reference_rates():
    from app.assistant.orchestrator import _route_price_question_without_exact_date_to_rates

    selection = RouteSelection(route="clarify", missing_information=["attendees"])

    assert _route_price_question_without_exact_date_to_rates(
        selection, "¿Cuánto cuesta?"
    ).route == "get_rates"


def test_cafeteria_price_question_does_not_use_escape_room_rates():
    from app.assistant.orchestrator import _route_price_question_without_exact_date_to_rates

    selection = RouteSelection(route="clarify", missing_information=["question"])

    assert _route_price_question_without_exact_date_to_rates(
        selection, "¿Qué precio tiene el menú de la cafetería?"
    ) == selection


def test_map_link_question_routes_to_location_knowledge_when_model_clarifies():
    from app.assistant.orchestrator import _route_location_link_to_knowledge

    selection = _route_location_link_to_knowledge(
        RouteSelection(route="clarify", missing_information=["question"]),
        "Pásame el link de Google Maps, por favor.",
    )

    assert selection.route == "search_business_knowledge"
    assert selection.categories == ["faq"]


def test_ambiguous_more_information_request_asks_for_topic_instead_of_guessing_location():
    from app.assistant.orchestrator import _route_ambiguous_information_request

    for message in (
        "Hola, quiero más información",
        "Hola quiero mas info",
        "Quiero más info, por favor",
        "Cuéntame un poco más",
        "Quisiera conocer más",
        "¿Me puedes dar más detalles?",
        "Me interesa saber más",
        "¿Podrías explicarme un poco más?",
    ):
        selection = _route_ambiguous_information_request(
            RouteSelection(
                route="search_business_knowledge",
                query="ubicación de Logic",
                categories=["faq"],
            ),
            message,
        )

        assert selection.route == "clarify"
        assert selection.missing_information == ["question"]
        assert selection.query is None


def test_more_information_request_keeps_a_topic_or_selected_room():
    from app.assistant.orchestrator import _route_ambiguous_information_request

    selection = RouteSelection(
        route="get_rooms", room="Manicomio", query="información de Manicomio"
    )
    assert _route_ambiguous_information_request(
        selection, "Cuéntame más de Manicomio"
    ) == selection

    specific_topic = RouteSelection(route="get_rates", query="precios")
    assert _route_ambiguous_information_request(
        specific_topic, "Quiero más información sobre precios"
    ) == specific_topic


def test_vague_information_clarification_offers_customer_topic_options():
    from app.assistant.response_builder import clarification_answer

    answer = clarification_answer(["question"])

    assert "salas" in answer
    assert "precios" in answer
    assert "eventos" in answer
    assert "cafetería" in answer
    assert "¿Cuál de esos temas" in answer


def test_theme_and_children_question_uses_room_catalog_and_rag():
    from app.assistant.orchestrator import _route_thematic_room_recommendation

    message = "Me gustaría ir con mis hijos de 9 y 11 años; quieren entrar a una sala de terror"
    selection = _route_thematic_room_recommendation(
        RouteSelection(route="clarify", missing_information=["room"]), message
    )
    assert selection.route == "get_rooms"
    assert selection.categories == ["faq"]
    assert "terror" in selection.query

    rooms = [
        Room(name="Canibal", min_players=4, max_players=7, minimum_age_without_adult=14),
        Room(name="La Secta", min_players=2, max_players=6, minimum_age_without_adult=14),
        Room(name="Portal: Jumanji", min_players=2, max_players=6, minimum_age_without_adult=12),
        Room(name="Manicomio", min_players=2, max_players=7, minimum_age_without_adult=14),
    ]
    theme_policy = KnowledgeSearchResult(
        chunk_id="themes:v1",
        document_id="recommendations.room-difficulty-and-intensity",
        category="faq",
        text="Canibal: terror con sustos. Portal: aventura, publico familiar. Manicomio: suspenso y misterio. La Secta: terror paranormal.",
        source_path="recommendations/room-difficulty-and-intensity.md",
        metadata={"validation_status": "approved_with_open_issue", "requires_api_data": True},
        distance=0.2,
    )
    client = FakeLogicClient(rooms=rooms)
    model = FakeModel(selection)
    tools = AssistantTools(
        settings=Settings(_env_file=None, logic_api_base_url="https://logic.test"),
        logic_client_factory=lambda _settings: client,
        knowledge_search=lambda *_args, **_kwargs: [theme_policy],
    )

    asyncio.run(AssistantOrchestrator(model, tools).reply(message))

    assert client.calls == ["get_rooms"]
    assert model.evidence["mode"] == "api_and_rag"
    assert {item["name"] for item in model.evidence["api_facts"]} == {
        "Canibal", "La Secta", "Portal: Jumanji", "Manicomio"
    }
    assert model.evidence["rag_facts"][0]["document_id"] == "recommendations.room-difficulty-and-intensity"
    assert "minimum_age_without_adult" in str(model.evidence["api_facts"])


def test_children_from_nine_with_parent_are_approved_for_selected_room():
    from app.assistant.orchestrator import _route_child_admission_question

    message = "Aún no lo sé, solo estoy cotizando. ¿Podría ir con mis hijos de 9 y 11 años?"
    history = [
        ChatTurn(role="user", content="Me gustaría ir con mis hijos de 9 y 11 años"),
        ChatTurn(role="assistant", content="¿Qué sala tienes en mente?"),
        ChatTurn(role="user", content="Me gustaría Manicomio, para 3 personas"),
        ChatTurn(role="assistant", content="¿Para qué fecha lo estás consultando?"),
    ]
    selection = _route_child_admission_question(
        RouteSelection(route="clarify", missing_information=["date"]), message
    )
    assert selection.route == "get_rooms"
    assert selection.query == "__child_admission_policy__"

    policy = KnowledgeSearchResult(
        chunk_id="minors:v1",
        document_id="policies.minors-and-room-limits",
        category="age_policy",
        text="La política permite el ingreso de niños desde los nueve años con un adulto responsable.",
        source_path="policies/minors-and-room-limits.md",
        metadata={"validation_status": "approved", "requires_api_data": True},
        distance=0.2,
    )
    client = FakeLogicClient(rooms=[
        Room(name="Manicomio", min_players=2, max_players=7, minimum_age_without_adult=14)
    ])
    model = FakeModel(selection)
    tools = AssistantTools(
        settings=Settings(_env_file=None, logic_api_base_url="https://logic.test"),
        logic_client_factory=lambda _settings: client,
        knowledge_search=lambda *_args, **_kwargs: [policy],
    )

    answer = asyncio.run(AssistantOrchestrator(model, tools).reply(message, history=history))

    assert answer.startswith("Sí")
    assert "Manicomio" in answer
    assert "adulto responsable" in answer
    assert "3 participantes" in answer
    assert "2 a 7 personas" in answer
    assert "disponibilidad" in answer


def test_child_admission_ignores_rooms_and_capacity_mentioned_by_assistant():
    from app.assistant.orchestrator import _format_child_admission_answer

    history = [
        ChatTurn(
            role="assistant",
            content="Canibal y Manicomio admiten de 4 a 7 personas; ¿cuál prefieres?",
        ),
    ]
    evidence = {
        "rag_facts": [{"text": "Los niños desde los 9 años pueden ingresar con un adulto responsable."}],
        "api_facts": [
            {"name": "Canibal", "min_players": 4, "max_players": 7, "minimum_age_without_adult": 14},
            {"name": "Manicomio", "min_players": 2, "max_players": 7, "minimum_age_without_adult": 14},
        ],
    }

    answer = _format_child_admission_answer(
        evidence,
        "Me gustaría ir con mis hijos de 9 y 11 años",
        history,
    )

    assert "desde los 9 años" in answer
    assert "adulto responsable" in answer
    assert "sala les interesa" in answer
    assert "Canibal" not in answer
    assert "Manicomio" not in answer
    assert "7 personas" not in answer
    assert "API" not in answer


def test_activity_explanation_question_routes_to_faq_when_model_clarifies():
    from app.assistant.orchestrator import _route_activity_explanation_to_knowledge

    selection = _route_activity_explanation_to_knowledge(
        RouteSelection(route="clarify", missing_information=["question"]),
        "¿De qué se trata la actividad?",
    )

    assert selection.route == "search_business_knowledge"
    assert selection.categories == ["faq"]
    assert "escape room" in selection.query


@pytest.mark.parametrize("question", [
    "¿Cómo es el juego?",
    "¿Cómo funciona la actividad?",
    "¿De qué se trata el lugar?",
    "¿Qué se hace en Logic?",
    "¿En qué consiste la experiencia?",
    "¿Qué toca hacer cuando uno llega?",
    "Explícame qué ofrece Logic",
    "Nunca he ido a un escape room, ¿qué es?",
])
def test_general_experience_questions_use_escape_room_explanation(question):
    from app.assistant.orchestrator import _route_activity_explanation_to_knowledge
    from app.assistant.tools import _activity_explanation_facts

    selection = _route_activity_explanation_to_knowledge(
        RouteSelection(route="clarify", missing_information=["question"]), question
    )

    assert selection.route == "search_business_knowledge"
    assert _activity_explanation_facts(question)


def test_short_experience_question_uses_recent_chat_context():
    from app.assistant.orchestrator import _route_activity_explanation_to_knowledge

    selection = _route_activity_explanation_to_knowledge(
        RouteSelection(route="clarify", missing_information=["question"]),
        "¿Y cómo es?",
        history=[
            ChatTurn(role="user", content="Nunca he probado un escape room"),
            ChatTurn(role="assistant", content="Con gusto te explico la actividad de Logic."),
        ],
    )

    assert selection.route == "search_business_knowledge"


def test_video_follow_up_uses_escape_room_context_and_configured_link():
    from app.assistant.orchestrator import _route_activity_explanation_to_knowledge

    selection = _route_activity_explanation_to_knowledge(
        RouteSelection(route="clarify", missing_information=["question"]),
        "¿Tienes un video?",
        history=[
            ChatTurn(role="user", content="¿De qué se trata el juego?"),
            ChatTurn(role="assistant", content="Es un juego presencial de escape room."),
        ],
    )
    model = FakeModel(selection)
    tools = AssistantTools(
        settings=Settings(
            _env_file=None,
            logic_escape_room_explainer_url="https://example.test/escape-room",
        ),
        knowledge_search=lambda *_args, **_kwargs: [],
    )

    asyncio.run(AssistantOrchestrator(model, tools).reply(
        "¿Tienes un video?",
        history=[
            ChatTurn(role="user", content="¿De qué se trata el juego?"),
            ChatTurn(role="assistant", content="Es un juego presencial de escape room."),
        ],
    ))

    assert selection.query == "video explicativo de que es un escape room"
    assert any(
        fact["name"] == "video_explicativo_escape_room_url"
        and fact["url"] == "https://example.test/escape-room"
        for fact in model.evidence["operational_facts"]
    )


def test_activity_explanation_includes_authorized_description_and_video_link():
    from app.core.prompts import FINAL_ANSWER_PROMPT

    model = FakeModel(RouteSelection(
        route="clarify", missing_information=["question"]
    ))
    tools = AssistantTools(
        settings=Settings(
            _env_file=None,
            logic_escape_room_explainer_url="https://example.test/escape-room",
        ),
        knowledge_search=lambda *_args, **_kwargs: [],
    )

    answer = asyncio.run(AssistantOrchestrator(model, tools).reply(
        "¿De qué se trata la actividad?"
    ))

    facts = model.evidence["operational_facts"]
    description = next(
        fact["text"] for fact in facts if fact["name"] == "descripcion_general_actividad"
    )
    assert all(term in description for term in (
        "en equipo", "sala", "pistas", "acertijos", "misión", "tiempo"
    ))
    assert any(
        fact["name"] == "video_explicativo_escape_room_url"
        and fact["url"] == "https://example.test/escape-room"
        for fact in facts
    )
    assert "video_explicativo_escape_room_url" in FINAL_ANSWER_PROMPT
    assert "salas de escape" in FINAL_ANSWER_PROMPT
    assert answer.endswith(model.answer)


def test_portal_alias_matches_canonical_api_room_name():
    from app.logic_api.adapter import room_name_matches

    assert room_name_matches("Portal", "Portal: Jumanji")
    assert room_name_matches("Portal: Jumanji", "Portal: Jumanji")
    assert not room_name_matches("Portal", "Portal 2")
    assert room_name_matches("Canibal", "Cannibal")


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

    assert answer.startswith("\u00a1Hola! Soy Nox, asistente virtual de Logic Escape Room.")
    assert "\u00bfEn qu\u00e9 puedo ayudarte?" in answer
    assert model.route_selected == 0


@pytest.mark.parametrize("message", ["Hola", "Hola Nox, buenas tardes", "Muy buenas"])
def test_greeting_variants_open_the_conversation_without_a_topic_menu(message):
    model = FakeModel(RouteSelection(route="clarify", missing_information=["question"]))

    answer = asyncio.run(AssistantOrchestrator(model, FakeTools()).reply(message))

    assert answer.startswith("\u00a1Hola! Soy Nox, asistente virtual de Logic Escape Room.")
    assert answer.endswith("\u00bfEn qu\u00e9 puedo ayudarte?")
    assert "precios, reservas" not in answer
    assert model.route_selected == 0


@pytest.mark.parametrize("message", [
    "Gracias",
    "Muchas gracias por la ayuda",
    "Mil gracias",
    "Te lo agradezco mucho",
    "No, gracias",
    "Hasta luego",
    "Hasta pronto",
    "Eso es todo, gracias",
    "Por ahora es todo",
])
def test_short_thanks_or_goodbye_closes_without_another_question(message):
    model = FakeModel(RouteSelection(route="clarify", missing_information=["question"]))

    answer = asyncio.run(AssistantOrchestrator(model, FakeTools()).reply(
        message,
        [ChatTurn(role="assistant", content="\u00bfQuieres que te ayude con algo m\u00e1s?")],
    ))

    assert answer == "\u00a1Con gusto! Gracias por escribirnos. Aqu\u00ed estar\u00e9 cuando quieras volver."
    assert "?" not in answer
    assert model.route_selected == 0


def test_follow_up_question_that_starts_with_thanks_does_not_close_conversation():
    model = FakeModel(
        RouteSelection(route="clarify", missing_information=["question"]),
        "\u00bfQu\u00e9 salas tienen?",
    )
    tools = FakeTools(ToolOutcome(
        AssistantEvidence("api_only", api_facts=[{"name": "Portal"}])
    ))

    answer = asyncio.run(AssistantOrchestrator(model, tools).reply(
        "Gracias, \u00bfqu\u00e9 salas tienen?",
        [ChatTurn(role="assistant", content="\u00bfTe puedo ayudar con algo m\u00e1s?")],
    ))

    assert model.route_selected == 1
    assert "salas" in answer

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
    assert "Una persona del equipo de Logic revisará el pago y confirmará la reserva por este chat." in answer


def test_combined_name_and_phone_complete_reservation_summary_and_payment_instructions():
    history = [
        ChatTurn(
            role="user",
            content="Me gustaría la sala Canibal, ¿qué horarios tienes disponibles para el sábado 31 de octubre?",
        ),
        ChatTurn(
            role="assistant",
            content="Para el sábado 31 de octubre, Cannibal tiene disponibles las 17:00 y 18:00. ¿Cuál prefieres?",
        ),
        ChatTurn(role="user", content="para las 6 de la tarde por favor"),
        ChatTurn(
            role="assistant",
            content="Claro que sí, las 18:00 sigue disponible para Cannibal el sábado 31 de octubre. ¿Cuántas personas asistirán?",
        ),
        ChatTurn(role="user", content="5"),
        ChatTurn(
            role="assistant",
            content="Claro que sí, para 5 personas a las 18:00 en Cannibal el sábado 31 de octubre. ¿Me compartes tu nombre y número de celular para continuar?",
        ),
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
    ).reply("Gloria 3121231234", history))

    assert "Número de personas: 5" in answer
    assert "Sala / temática: Cannibal" in answer
    assert "Hora: 18:00" in answer
    assert "Nombre de quien solicita: Gloria" in answer
    assert "Número de contacto: 3121231234" in answer
    assert "abono de $50.000 COP" in answer
    assert "Bre-B" in answer and "0091786913" in answer
    assert answer.endswith(
        "Una persona del equipo de Logic revisará el pago y confirmará la reserva por este chat."
    )


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

    assert answer == model.answer
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


def test_availability_resolves_short_room_alias_to_canonical_catalog_name():
    availability = Availability(
        date=date(2026, 10, 24), day_type="weekend", is_holiday=False,
        timezone="America/Bogota", server_now=datetime.fromisoformat("2026-10-17T12:00:00-05:00"),
        min_advance_minutes=0,
        rooms=(AvailabilityRoom(
            room_id="portal-jumanji", name="Portal: Jumanji", slots=(
                AvailabilitySlot(start=datetime.fromisoformat("2026-10-24T16:30:00-05:00"), available=True),
            ),
        ),),
    )
    client = FakeLogicClient(availability=availability)
    model = FakeModel(RouteSelection(
        route="get_availability", date=date(2026, 10, 24), room="Portal"
    ))

    asyncio.run(AssistantOrchestrator(model, make_tools(client)).reply("\u00bfHay espacio en Portal?"))

    assert model.evidence["api_facts"][0]["rooms"] == [{
        "room_name": "Portal: Jumanji",
        "slots": [{"start": "16:30", "available": True}],
    }]


def test_availability_canonicalizes_room_spelling_even_when_model_selected_room():
    requested_date = date(2026, 10, 31)
    availability = Availability(
        date=requested_date,
        day_type="weekend",
        is_holiday=False,
        timezone="America/Bogota",
        server_now=datetime.fromisoformat("2026-10-18T12:00:00-05:00"),
        min_advance_minutes=0,
        rooms=(AvailabilityRoom(
            room_id="cannibal",
            name="Cannibal",
            slots=(AvailabilitySlot(
                start=datetime.fromisoformat("2026-10-31T17:00:00-05:00"),
                available=True,
            ),),
        ),),
    )
    client = FakeLogicClient(
        rooms=[Room(name="Cannibal", min_players=4, max_players=7)],
        availability=availability,
    )
    model = FakeModel(RouteSelection(
        route="get_availability", date=requested_date, room="Canibal"
    ))

    asyncio.run(AssistantOrchestrator(model, make_tools(client)).reply(
        "¿Qué horarios tiene la sala Canibal para el sábado 31 de octubre?"
    ))

    assert client.calls == [("get_availability", requested_date)]
    assert model.evidence["api_facts"][0]["rooms"] == [{
        "room_name": "Cannibal",
        "slots": [{"start": "17:00", "available": True}],
    }]


def test_room_policy_resolves_alias_before_combining_api_and_rag():
    room = Room(name="Portal: Jumanji", min_players=2, max_players=6)
    policy = KnowledgeSearchResult(
        chunk_id="portal-policy:v1", document_id="policies.minors-and-room-limits",
        category="age_policy", text="La excepci\u00f3n de Portal exige confirmaci\u00f3n humana.",
        source_path="policies/minors-and-room-limits.md",
        metadata={"requires_human_for_exceptions": True, "validation_status": "approved"},
        distance=0.2,
    )
    client = FakeLogicClient(rooms=[room])
    tools = make_tools(client, knowledge_results=[policy])
    model = FakeModel(RouteSelection(
        route="check_room_policy", room="Portal", attendees=7,
        query="Somos siete en Portal, \u00bfpodemos jugar?", categories=["age_policy"],
    ))

    asyncio.run(AssistantOrchestrator(model, tools).reply("Somos siete en Portal, \u00bfpodemos jugar?"))

    assert model.evidence["mode"] == "api_and_rag"
    assert model.evidence["api_facts"][0]["name"] == "Portal: Jumanji"
    assert model.evidence["rag_facts"][0]["document_id"] == "policies.minors-and-room-limits"


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


@pytest.mark.parametrize(("message", "expected_name", "url_field"), [
    ("Pásame el link de Google Maps", "ubicacion_maps_url", "logic_map_url"),
    ("¿Me compartes el menú de la cafetería?", "menu_cafeteria_url", "logic_cafeteria_menu_url"),
    ("¿Cuál es la página web oficial?", "sitio_web_oficial_url", "logic_official_website_url"),
    ("Envíame el video de qué es un escape room", "video_explicativo_escape_room_url", "logic_escape_room_explainer_url"),
])
def test_configured_business_links_are_added_as_operational_evidence(message, expected_name, url_field):
    from app.assistant.tools import _business_link_operational_facts

    settings = Settings(_env_file=None, **{url_field: "https://example.test/link"})

    facts = _business_link_operational_facts(message, settings)

    assert facts == [{
        "name": expected_name,
        "url": "https://example.test/link",
        "source": "configuracion de entorno de Logic",
    }]


def test_unconfigured_business_link_is_not_included_in_evidence():
    from app.assistant.tools import _business_link_operational_facts

    assert _business_link_operational_facts(
        "Pásame el link de Google Maps", Settings(_env_file=None)
    ) == []


def test_cafeteria_usage_question_does_not_attach_menu_link():
    from app.assistant.tools import _business_link_operational_facts

    settings = Settings(_env_file=None, logic_cafeteria_menu_url="https://example.test/menu")

    assert _business_link_operational_facts(
        "¿Cuánto tiempo podemos quedarnos en la cafetería?", settings
    ) == []


def test_duration_and_arrival_paraphrases_expand_rag_search_terms():
    from app.assistant.tools import _expand_experience_query

    expanded = _expand_experience_query(
        "cuanto dura el juego y con cuanta anticipacion llegamos",
        "\u00bfCu\u00e1nto dura el juego y con cu\u00e1nta anticipaci\u00f3n llegamos?",
    )

    assert "duracion de la sesion de escape" in expanded
    assert "llegar antes" in expanded


def test_outside_drink_paraphrases_expand_rag_search_terms():
    from app.assistant.tools import _expand_experience_query

    expanded = _expand_experience_query(
        "¿Puedo entrar con bebidas que compré afuera?",
        "¿Puedo entrar con bebidas que compré afuera?",
    )

    assert "bebidas propias" in expanded
    assert "cafeteria" in expanded


def test_rag_query_retains_original_user_wording_with_model_query():
    captured = {}

    def knowledge_search(query, **kwargs):
        captured["query"] = query
        captured["categories"] = kwargs.get("categories")
        return []

    tools = AssistantTools(
        settings=Settings(_env_file=None),
        knowledge_search=knowledge_search,
    )
    asyncio.run(tools._search_knowledge(
        RouteSelection(route="search_business_knowledge", query="reglas de llegada"),
        "¿Cuánto dura el juego y con cuánta anticipación llegamos?",
    ))

    assert "¿Cuánto dura el juego" in captured["query"]
    assert "duracion de la sesion de escape" in captured["query"]
    assert captured["categories"] == ["operational_rule"]


def test_experience_question_overrides_incompatible_model_category():
    from app.assistant.tools import _knowledge_categories_for_message

    assert _knowledge_categories_for_message(
        ["faq"], "¿Cuánto dura el juego y con cuánta anticipación llegamos?"
    ) == ["operational_rule"]
    assert _knowledge_categories_for_message(
        ["faq"], "¿Cuál es el menú de la cafetería?"
    ) == ["faq"]
    assert _knowledge_categories_for_message(
        ["operational_rule"], "¿Cuánto tiempo podemos quedarnos en la cafetería?"
    ) == ["faq"]


def test_cafeteria_stay_question_does_not_expand_to_game_duration():
    from app.assistant.tools import _expand_experience_query

    expanded = _expand_experience_query(
        "¿Cuánto tiempo podemos quedarnos en la cafetería?",
        "¿Cuánto tiempo podemos quedarnos en la cafetería?",
    )

    assert "duracion de la sesion de escape" not in expanded


def test_empty_model_answer_is_retried_once():
    class FakeCompletions:
        calls = 0

        async def create(self, **_kwargs):
            self.calls += 1
            content = "" if self.calls == 1 else "Respuesta respaldada."
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=content)
            )])

    completions = FakeCompletions()
    model = object.__new__(OpenAIChatModel)
    model.settings = Settings(
        _env_file=None, openai_api_key="test-key", openai_model="gpt-6-luna"
    )
    model.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    answer = asyncio.run(model.generate_answer("pregunta", {}))

    assert answer == "Respuesta respaldada."
    assert completions.calls == 2


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
    assert answer.endswith(model.answer)
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



