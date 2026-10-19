"""Explicit backend-owned execution for the small, read-only tool set."""

import asyncio
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

from app.core.config import Settings, get_settings
from app.logic_api.adapter import room_name_matches
from app.logic_api.client import LogicApiClient, create_logic_api_client
from app.logic_api.errors import LogicApiError
from app.logic_api.models import Availability, OpeningHours, Quote, Rate, Room
from app.rag.models import KnowledgeSearchResult
from app.rag.retriever import search_business_knowledge
from app.assistant.schemas import RouteSelection

OutcomeMode = Literal[
    "api_only",
    "rag_only",
    "api_and_rag",
    "operational_only",
    "rag_and_operational",
]
DAY_NAMES_ES = ("domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado")
BOGOTA = ZoneInfo("America/Bogota")
KnowledgeSearch = Callable[..., list[KnowledgeSearchResult]]
LogicClientFactory = Callable[[Settings], LogicApiClient]


@dataclass
class AssistantEvidence:
    mode: OutcomeMode
    api_facts: list[dict[str, Any]] = field(default_factory=list)
    rag_facts: list[dict[str, Any]] = field(default_factory=list)
    operational_facts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_prompt_data(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "api_facts": self.api_facts,
            "rag_facts": self.rag_facts,
            "operational_facts": self.operational_facts,
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
        rooms = tuple(room for room in rooms if room_name_matches(room_name, room.name))
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


def _payment_operational_facts(
    selection: RouteSelection,
    settings: Settings,
) -> tuple[list[dict[str, Any]], list[str]]:
    if "payments" not in selection.categories:
        return [], []
    if not settings.logic_operational_values_verified:
        return [], ["El importe de abono por sala no está marcado como verificado en la configuración operativa."]
    amount = settings.logic_typical_deposit_per_room_cop
    if amount is None:
        return [], ["El importe de abono por sala no está configurado; no inventar un valor."]
    return [
        {
            "name": "abono_habitual",
            "amount": amount,
            "currency": "COP",
            "scope": "por sala a reservar",
            "source": "configuración operativa verificada",
        }
    ], []


def _business_link_operational_facts(message: str, settings: Settings) -> list[dict[str, Any]]:
    """Expose only configured business links relevant to the customer's request."""
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFD", message.casefold())
        if unicodedata.category(character) != "Mn"
    )
    asks_link = any(term in normalized for term in (
        "link", "enlace", "url", "pagina", "sitio web", "website", "video",
        "maps", "mapas", "ubicacion", "direccion", "menu", "donde queda", "donde es",
        "como llegar", "llegar a logic", "de que se trata la actividad",
        "en que consiste la actividad", "que tipo de actividad",
        "como es el juego", "como es la actividad", "como funciona el juego",
        "como funciona la actividad", "de que se trata el lugar", "que se hace en logic",
    ))
    if not asks_link:
        return []

    requested: list[tuple[str, str | None]] = []
    if "menu" in normalized or (
        any(term in normalized for term in ("cafeteria", "comida", "bebida"))
        and any(term in normalized for term in ("link", "enlace", "url", "pagina"))
    ):
        requested.append(("menu_cafeteria_url", settings.logic_cafeteria_menu_url))
    asks_how_to_arrive = any(term in normalized for term in (
        "donde queda", "donde es", "como llegar", "como puedo llegar", "llegar a logic",
    ))
    if asks_how_to_arrive or any(term in normalized for term in (
        "maps", "mapas", "ubicacion", "direccion", "google",
    )):
        requested.append(("ubicacion_maps_url", settings.logic_map_url))
    asks_for_escape_room_video = (
        any(term in normalized for term in ("instagram", "video explicativo", "que es un escape room", "como funciona un escape room"))
        or (
            any(term in normalized for term in ("video", "reel"))
            and any(term in normalized for term in ("escape room", "actividad", "juego", "logic"))
        )
        or any(term in normalized for term in (
            "de que se trata la actividad", "en que consiste la actividad", "que tipo de actividad",
            "como es el juego", "como es la actividad", "como funciona el juego",
            "como funciona la actividad", "de que se trata el lugar", "que se hace en logic",
        ))
    )
    if asks_for_escape_room_video:
        requested.append(("video_explicativo_escape_room_url", settings.logic_escape_room_explainer_url))
    if any(term in normalized for term in ("pagina", "sitio web", "website", "web oficial")):
        requested.append(("sitio_web_oficial_url", settings.logic_official_website_url))

    return [
        {"name": name, "url": value, "source": "configuracion de entorno de Logic"}
        for name, value in requested
        if value
    ]


def _activity_explanation_facts(message: str) -> list[dict[str, Any]]:
    """Provide the basic activity description requested by Logic's owner."""
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFD", message.casefold())
        if unicodedata.category(character) != "Mn"
    )
    asks_activity = any(phrase in normalized for phrase in (
        "de que se trata la actividad", "en que consiste la actividad",
        "que es un escape room", "que es escape room", "que es la actividad", "que tipo de actividad",
        "que actividad es", "que es logic", "como es el juego", "como es la actividad",
        "como funciona el juego", "como funciona la actividad", "como se juega",
        "de que se trata el lugar", "de que trata el lugar", "como es el lugar",
        "como funciona logic", "que se hace en logic", "que se hace en este lugar",
    )) or bool(re.search(
        r"\b(?:de\s+que\s+(?:se\s+)?trata|en\s+que\s+consiste|que\s+es|como\s+(?:es|funciona|se\s+juega))\b.{0,55}\b(?:actividad|logic|escape\s*room|juego|experiencia|lugar)\b",
        normalized,
    )) or (
        bool(re.search(r"\b(?:explicame|cuentame|nunca\s+he\s+ido|primera\s+vez|que\s+toca\s+hacer|que\s+hay\s+que\s+hacer)\b", normalized))
        and bool(re.search(r"\b(?:actividad|logic|escape\s*room|juego|experiencia|lugar|uno\s+llega)\b", normalized))
    )
    if not asks_activity:
        return []
    return [{
        "name": "descripcion_general_actividad",
        "text": "Explicación general del concepto: un escape room es un juego presencial de aventura y lógica que se disfruta en equipo. Los participantes entran a una sala con una temática, buscan pistas y resuelven acertijos para avanzar y cumplir una misión antes de que termine el tiempo. Logic Escape Room ofrece esta clase de experiencia. Esta descripción explica el concepto general y no afirma que todas las salas de Logic tengan las mismas reglas, historia o retos.",
        "source": "descripción general solicitada por Logic",
    }]


def _asks_for_exception_or_payment_review(message: str) -> bool:
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFD", message.casefold())
        if unicodedata.category(character) != "Mn"
    )
    review_phrases = (
        "excepcion",
        "superamos el maximo",
        "somos mas de",
        "abonar menos",
        "pagar menos",
        "abono menor",
        "abono reducido",
        "en efectivo",
        "comprobante",
        "recibo",
        "ya pague",
        "ya transferi",
        "adjunto",
    )
    return any(phrase in normalized for phrase in review_phrases)


def _expand_experience_query(query: str, user_message: str) -> str:
    """Add corpus vocabulary for common paraphrases without adding business claims."""
    normalized = "".join(
        char for char in unicodedata.normalize("NFD", user_message.casefold())
        if unicodedata.category(char) != "Mn"
    )
    has_game_context = any(term in normalized for term in (
        "juego", "sesion", "experiencia", "sala de escape",
    ))
    asks_duration_or_arrival = bool(any(
        term in normalized
        for term in (
            "dura", "duracion", "anticipacion", "llegamos", "llegar temprano",
            "retraso", "a que hora llegar", "cuando llegar",
        )
    ) or ("cuanto tiempo" in normalized and has_game_context))
    asks_about_outside_food_or_drink = bool(any(
        term in normalized
        for term in (
            "bebida", "tomar", "comida", "alimento", "compre afuera",
            "comprado afuera", "llevar afuera", "ingresar a la cafeteria",
            "entrar a la cafeteria",
        )
    ))
    expansions = []
    if asks_duration_or_arrival:
        expansions.append(
            "duracion de la sesion de escape tiempo de juego minutos llegada llegar antes retrasos"
        )
    if asks_about_outside_food_or_drink:
        expansions.append(
            "politica alimentos y bebidas propias bebidas compradas afuera ingreso a salas cafeteria"
        )
    return " ".join([query, *expansions]) if expansions else query


def _knowledge_categories_for_message(
    categories: list[str],
    user_message: str,
) -> list[str] | None:
    """Prefer corpus categories implied by clear experience questions over model guesses."""
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFD", user_message.casefold())
        if unicodedata.category(character) != "Mn"
    )
    has_game_context = any(term in normalized for term in (
        "juego", "sesion", "experiencia", "sala de escape",
    ))
    food_or_drink_question = any(term in normalized for term in (
        "bebida", "tomar", "comida", "alimento", "compre afuera",
        "comprado afuera",
    ))
    if "cafeteria" in normalized and not food_or_drink_question:
        return ["faq"]
    experience_question = any(term in normalized for term in (
        "dura", "duracion", "anticipacion", "llegamos", "llegar temprano",
        "retraso",
    )) or food_or_drink_question or ("cuanto tiempo" in normalized and has_game_context)
    if experience_question:
        return ["operational_rule"]
    return categories or None


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
                fallback_answer="No puedo verificar esa información en este momento. El equipo de Logic debe revisarla.",
                needs_human=True,
            )

        async with self.logic_client_factory(self.settings) as client:
            if route == "get_rooms":
                rooms = await client.get_rooms()
                if selection.room:
                    rooms = [room for room in rooms if room_name_matches(selection.room, room.name)]
                    if not rooms:
                        return ToolOutcome(
                            AssistantEvidence("api_only"),
                            fallback_answer="No pude encontrar esa sala en el catálogo vigente. ¿Me confirmas su nombre?",
                        )
                api_facts = [_room_fact(room) for room in rooms]
                if selection.query == "__room_catalog_and_reference_prices__":
                    rates = await client.get_rates()
                    api_facts.extend(_rate_fact(rate) for rate in rates)
                    return ToolOutcome(AssistantEvidence("api_only", api_facts=api_facts))
                if selection.query == "__child_admission_policy__":
                    try:
                        results = await asyncio.to_thread(
                            self.knowledge_search,
                            "regla general ingreso niños desde nueve años con adulto responsable " + user_message,
                            room=None,
                            categories=selection.categories,
                            top_k=4,
                            settings=self.settings,
                        )
                    except Exception:
                        results = []
                    if not results:
                        return ToolOutcome(
                            AssistantEvidence("api_and_rag", api_facts=api_facts),
                            fallback_answer="No pude verificar la política de ingreso para menores. El equipo de Logic debe confirmarla.",
                            needs_human=True,
                        )
                    return ToolOutcome(AssistantEvidence(
                        "api_and_rag",
                        api_facts=api_facts,
                        rag_facts=[_rag_fact(item) for item in results],
                    ))
                if selection.categories and selection.query:
                    if selection.query.startswith("theme:"):
                        theme = selection.query.partition(":")[2].strip()
                        # Keep the embedding query focused on the exact thematic term.
                        # Appending the booking date and phrasing can rank unrelated FAQ chunks higher.
                        query = theme
                        top_k = 20
                    else:
                        query = " ".join(
                            part.strip() for part in (selection.query, user_message) if part and part.strip()
                        )
                        top_k = 4
                    try:
                        results = await asyncio.to_thread(
                            self.knowledge_search,
                            query,
                            room=selection.room,
                            categories=selection.categories,
                            top_k=top_k,
                            settings=self.settings,
                        )
                    except Exception:
                        results = []
                    if not results and selection.query.startswith("theme:"):
                        theme = selection.query.partition(":")[2].strip()
                        try:
                            results = await asyncio.to_thread(
                                self.knowledge_search,
                                f"recomendacion tematica sala {theme}",
                                room=None,
                                categories=selection.categories,
                                top_k=20,
                                settings=self.settings,
                            )
                        except Exception:
                            results = []
                    if not results:
                        return ToolOutcome(AssistantEvidence(
                            "api_and_rag",
                            api_facts=api_facts,
                            warnings=["No se pudo verificar la correspondencia entre la temática solicitada y las salas; no recomendar una sala por tema ni inferir condiciones para menores."],
                        ), needs_human=True)
                    return ToolOutcome(AssistantEvidence(
                        "api_and_rag",
                        api_facts=api_facts,
                        rag_facts=[_rag_fact(item) for item in results],
                        warnings=["Usa las temáticas solo como recomendación; confirma edades y límites con los datos actuales de cada sala."],
                    ))
                return ToolOutcome(AssistantEvidence("api_only", api_facts=api_facts))
            if route == "get_rates":
                rates = await client.get_rates(selection.day_type)
                api_facts = [_rate_fact(rate) for rate in rates]
                if selection.query == "__location_and_prices__":
                    try:
                        location_results = await asyncio.to_thread(
                            self.knowledge_search,
                            "dirección física ubicación de Logic Escape Room Tunja",
                            room=None,
                            categories=["faq"],
                            top_k=2,
                            settings=self.settings,
                        )
                    except Exception:
                        location_results = []
                    return ToolOutcome(AssistantEvidence(
                        "api_and_rag",
                        api_facts=api_facts,
                        rag_facts=[_rag_fact(item) for item in location_results],
                        operational_facts=_business_link_operational_facts(
                            user_message, self.settings
                        ),
                    ))
                return ToolOutcome(
                    AssistantEvidence("api_only", api_facts=api_facts)
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
                        warnings=[],
                    )
                )
        raise ValueError("Unsupported assistant route.")

    async def _search_knowledge(
        self,
        selection: RouteSelection,
        user_message: str,
    ) -> ToolOutcome:
        query = _expand_experience_query(
            " ".join(
                part.strip()
                for part in (selection.query, user_message)
                if part and part.strip()
            ),
            user_message,
        )
        operational_facts, operational_warnings = _payment_operational_facts(
            selection, self.settings
        )
        link_facts = _business_link_operational_facts(
            " ".join(part for part in (selection.query, user_message) if part),
            self.settings,
        )
        activity_facts = _activity_explanation_facts(
            " ".join(part for part in (selection.query, user_message) if part)
        )
        operational_facts.extend([*link_facts, *activity_facts])
        try:
            results = await asyncio.to_thread(
                self.knowledge_search,
                query,
                room=selection.room,
                categories=_knowledge_categories_for_message(
                    selection.categories, user_message
                ),
                top_k=4,
                settings=self.settings,
            )
        except Exception:
            if operational_facts:
                return ToolOutcome(
                    AssistantEvidence(
                        "operational_only",
                        operational_facts=operational_facts,
                        warnings=operational_warnings + [
                            "No se pudo consultar la política de pagos; limita la respuesta al importe habitual y no afirmes otras condiciones."
                        ],
                    )
                )
            return ToolOutcome(
                AssistantEvidence("rag_only"),
                fallback_answer="No pude consultar las políticas de Logic en este momento. El equipo debe verificar el caso.",
                needs_human=True,
            )
        if not results:
            if operational_facts:
                return ToolOutcome(
                    AssistantEvidence(
                        "operational_only",
                        operational_facts=operational_facts,
                        warnings=operational_warnings,
                    )
                )
            return ToolOutcome(
                AssistantEvidence("rag_only"),
                fallback_answer="No encuentro una política documentada que responda con suficiente certeza. Ese caso requiere confirmación del equipo de Logic.",
                needs_human=True,
            )
        return ToolOutcome(
            AssistantEvidence(
                "rag_and_operational" if operational_facts else "rag_only",
                rag_facts=[_rag_fact(item) for item in results],
                operational_facts=operational_facts,
                warnings=operational_warnings,
            ),
            needs_human=(
                _asks_for_exception_or_payment_review(user_message)
                and any(
                    bool(item.metadata.get("requires_human_for_exceptions"))
                    for item in results
                )
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
                fallback_answer="No puedo verificar la sala en este momento; el equipo de Logic debe revisar el caso.",
                needs_human=True,
            )
        async with self.logic_client_factory(self.settings) as client:
            rooms = await client.get_rooms()
        matching_rooms = [room for room in rooms if room_name_matches(selection.room, room.name)]
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
                "El grupo supera el máximo ordinario de la sala; no confirmar el cupo y solicitar revisión humana."
            )
        evidence = AssistantEvidence(
            "api_and_rag",
            api_facts=[_room_fact(room)],
            rag_facts=[_rag_fact(item) for item in results],
            warnings=warnings,
        )
        return ToolOutcome(evidence, needs_human=True)
