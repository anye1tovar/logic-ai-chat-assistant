"""Explicit backend-owned execution for the small, read-only tool set."""

import asyncio
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

from app.core.config import Settings, get_settings
from app.logic_api.client import LogicApiClient, create_logic_api_client
from app.logic_api.errors import LogicApiError
from app.logic_api.models import Availability, OpeningHours, Quote, Rate, Room
from app.rag.models import KnowledgeSearchResult
from app.rag.retriever import search_business_knowledge
from app.assistant.schemas import RouteSelection

OutcomeMode = Literal["api_only", "rag_only", "api_and_rag"]
DAY_NAMES_ES = ("domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado")
BOGOTA = ZoneInfo("America/Bogota")
KnowledgeSearch = Callable[..., list[KnowledgeSearchResult]]
LogicClientFactory = Callable[[Settings], LogicApiClient]


@dataclass
class AssistantEvidence:
    mode: OutcomeMode
    api_facts: list[dict[str, Any]] = field(default_factory=list)
    rag_facts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_prompt_data(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "api_facts": self.api_facts,
            "rag_facts": self.rag_facts,
            "warnings": self.warnings,
        }


@dataclass
class ToolOutcome:
    evidence: AssistantEvidence
    fallback_answer: str | None = None
    needs_human: bool = False


def _room_fact(room: Room) -> dict[str, Any]:
    return room.model_dump(mode="json", exclude_none=True)


def _rate_fact(rate: Rate) -> dict[str, Any]:
    return rate.model_dump(mode="json", exclude_none=True)


def _opening_hours_fact(item: OpeningHours) -> dict[str, Any]:
    return {
        "day": DAY_NAMES_ES[item.day_of_week],
        "is_open": item.is_open,
        "open_time": item.open_time,
        "close_time": item.close_time,
        "requires_advance_booking": item.requires_advance_booking,
    }


def _quote_fact(quote: Quote) -> dict[str, Any]:
    return quote.model_dump(mode="json", exclude_none=True)


def _availability_facts(
    availability: Availability,
    room_name: str | None,
) -> list[dict[str, Any]]:
    rooms = availability.rooms
    if room_name:
        normalized = room_name.casefold().strip()
        rooms = tuple(room for room in rooms if room.name.casefold().strip() == normalized)
    facts = []
    for room in rooms:
        slots = []
        for slot in room.slots:
            starts_at = slot.start
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=BOGOTA)
            else:
                starts_at = starts_at.astimezone(BOGOTA)
            slots.append({"start": starts_at.strftime("%H:%M"), "available": slot.available})
        facts.append({"room_name": room.name, "slots": slots})
    return facts


def _rag_fact(result: KnowledgeSearchResult) -> dict[str, Any]:
    return {
        "document_id": result.document_id,
        "category": result.category,
        "text": result.text,
        "source_path": result.source_path,
        "validation_status": result.metadata.get("validation_status"),
        "requires_api_data": result.metadata.get("requires_api_data", False),
        "requires_human_for_exceptions": result.metadata.get(
            "requires_human_for_exceptions", False
        ),
        "distance": result.distance,
    }


class AssistantTools:
    """Executes one validated route; it never lets the model call tools in a loop."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        logic_client_factory: LogicClientFactory | None = None,
        knowledge_search: KnowledgeSearch | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.logic_client_factory = logic_client_factory or create_logic_api_client
        self.knowledge_search = knowledge_search or search_business_knowledge

    async def execute(self, selection: RouteSelection, user_message: str) -> ToolOutcome:
        route = selection.route
        if route == "clarify":
            raise ValueError("Clarification routes are handled before tool execution.")
        if route == "search_business_knowledge":
            return await self._search_knowledge(selection, user_message)
        if route == "check_room_policy":
            return await self._check_room_policy(selection, user_message)

        if not self.settings.logic_api_base_url:
            return ToolOutcome(
                AssistantEvidence("api_only"),
                fallback_answer="No puedo verificar esa información porque la conexión con la API de Logic no está configurada.",
                needs_human=True,
            )

        async with self.logic_client_factory(self.settings) as client:
            if route == "get_rooms":
                rooms = await client.get_rooms()
                return ToolOutcome(
                    AssistantEvidence("api_only", api_facts=[_room_fact(room) for room in rooms])
                )
            if route == "get_rates":
                rates = await client.get_rates(selection.day_type)
                return ToolOutcome(
                    AssistantEvidence("api_only", api_facts=[_rate_fact(rate) for rate in rates])
                )
            if route == "get_opening_hours":
                hours = await client.get_opening_hours()
                if selection.day_of_week is not None:
                    hours = [item for item in hours if item.day_of_week == selection.day_of_week]
                if not hours:
                    return ToolOutcome(
                        AssistantEvidence("api_only"),
                        fallback_answer="No encuentro un horario configurado para ese día. El equipo de Logic debe verificarlo.",
                        needs_human=True,
                    )
                return ToolOutcome(
                    AssistantEvidence(
                        "api_only", api_facts=[_opening_hours_fact(item) for item in hours]
                    )
                )
            if route == "get_quote":
                missing = selection.missing_required_fields()
                if missing:
                    raise ValueError("Quote route is missing required arguments.")
                quote = await client.get_quote(selection.date, selection.attendees)
                return ToolOutcome(AssistantEvidence("api_only", api_facts=[_quote_fact(quote)]))
            if route == "get_availability":
                if selection.date is None:
                    raise ValueError("Availability route is missing a date.")
                availability = await client.get_availability(selection.date)
                facts = _availability_facts(availability, selection.room)
                if selection.room and not facts:
                    return ToolOutcome(
                        AssistantEvidence("api_only"),
                        fallback_answer="No pude verificar esa sala para la fecha consultada. ¿Me confirmas el nombre de la sala?",
                    )
                return ToolOutcome(
                    AssistantEvidence(
                        "api_only",
                        api_facts=[{"date": availability.date.isoformat(), "rooms": facts}],
                        warnings=["La disponibilidad es una consulta en tiempo real y no confirma una reserva."],
                    )
                )
        raise ValueError("Unsupported assistant route.")

    async def _search_knowledge(
        self,
        selection: RouteSelection,
        user_message: str,
    ) -> ToolOutcome:
        query = (selection.query or user_message).strip()
        try:
            results = await asyncio.to_thread(
                self.knowledge_search,
                query,
                room=selection.room,
                categories=selection.categories or None,
                top_k=4,
                settings=self.settings,
            )
        except Exception:
            return ToolOutcome(
                AssistantEvidence("rag_only"),
                fallback_answer="No pude consultar las políticas de Logic en este momento. El equipo debe verificar el caso.",
                needs_human=True,
            )
        if not results:
            return ToolOutcome(
                AssistantEvidence("rag_only"),
                fallback_answer="No encuentro una política documentada que responda con suficiente certeza. Ese caso requiere confirmación del equipo de Logic.",
                needs_human=True,
            )
        return ToolOutcome(
            AssistantEvidence("rag_only", rag_facts=[_rag_fact(item) for item in results]),
            needs_human=any(
                bool(item.metadata.get("requires_human_for_exceptions")) for item in results
            ),
        )

    async def _check_room_policy(
        self,
        selection: RouteSelection,
        user_message: str,
    ) -> ToolOutcome:
        if not selection.room:
            raise ValueError("Room policy route is missing a room.")
        if not self.settings.logic_api_base_url:
            return ToolOutcome(
                AssistantEvidence("api_and_rag"),
                fallback_answer="No puedo verificar la sala en la API de Logic en este momento; el equipo debe revisar el caso.",
                needs_human=True,
            )
        async with self.logic_client_factory(self.settings) as client:
            rooms = await client.get_rooms()
        normalized = selection.room.casefold().strip()
        matching_rooms = [room for room in rooms if room.name.casefold().strip() == normalized]
        if not matching_rooms:
            return ToolOutcome(
                AssistantEvidence("api_and_rag"),
                fallback_answer="No pude verificar esa sala en el catálogo actual de Logic. ¿Me confirmas el nombre de la sala?",
            )
        query = (selection.query or user_message).strip()
        try:
            results = await asyncio.to_thread(
                self.knowledge_search,
                query,
                room=selection.room,
                categories=selection.categories or None,
                top_k=4,
                settings=self.settings,
            )
        except Exception:
            return ToolOutcome(
                AssistantEvidence("api_and_rag", api_facts=[_room_fact(matching_rooms[0])]),
                fallback_answer="Puedo verificar los datos actuales de la sala, pero no pude consultar la política que aplica. El equipo de Logic debe revisarlo.",
                needs_human=True,
            )
        if not results:
            return ToolOutcome(
                AssistantEvidence(
                    "api_and_rag",
                    api_facts=[_room_fact(matching_rooms[0])],
                ),
                fallback_answer="Puedo consultar los datos actuales de la sala, pero no encuentro una política documentada que confirme esa excepción. El equipo de Logic debe revisarla.",
                needs_human=True,
            )

        attendee_count = selection.attendees
        room = matching_rooms[0]
        warnings = [
            "La política recuperada es evidencia contextual; sus condiciones deben cumplirse y las excepciones requieren confirmación humana.",
        ]
        if attendee_count and room.max_players and attendee_count > room.max_players:
            warnings.append(
                "El grupo supera el máximo ordinario de la API; no confirmar el cupo y solicitar revisión humana."
            )
        evidence = AssistantEvidence(
            "api_and_rag",
            api_facts=[_room_fact(room)],
            rag_facts=[_rag_fact(item) for item in results],
            warnings=warnings,
        )
        return ToolOutcome(evidence, needs_human=True)
