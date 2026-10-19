from datetime import date, datetime, timedelta
import re
import unicodedata
from zoneinfo import ZoneInfo

from openai import OpenAIError
from pydantic import ValidationError

from app.assistant.model import ModelProtocolError, OpenAIChatModel
from app.assistant.response_builder import clarification_answer, logic_error_answer
from app.assistant.schemas import ChatTurn, RouteSelection
from app.assistant.tools import AssistantTools
from app.logic_api.adapter import room_name_matches
from app.logic_api.errors import LogicApiError

BOGOTA = ZoneInfo("America/Bogota")


def _fill_relative_date(
    selection: RouteSelection,
    message: str,
    today: date,
    history: list[ChatTurn] | None = None,
) -> RouteSelection:
    """Resolve Spanish relative dates and weekdays the route model may leave blank."""
    normalized = _normalized_text(message)
    if selection.date is not None:
        return selection

    match = re.search(r"\bpasado\s+manana\b|\banteayer\b|\bmanana\b|\bayer\b|\bhoy\b", normalized)
    if not match:
        if re.search(r"\bfin\s+de\s+semana\b", normalized):
            days_ahead = (5 - today.weekday()) % 7
            if days_ahead == 0 or "proximo" in normalized:
                days_ahead = days_ahead or 7
            resolved = today + timedelta(days=days_ahead)
            missing = [field for field in selection.missing_information if field != "date"]
            return selection.model_copy(update={"date": resolved, "missing_information": missing})
        weekday_match = re.search(
            r"\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b", normalized
        )
        if not weekday_match:
            has_time = bool(re.search(
                r"\ba\s+las?\s+\d{1,2}(?::|\.)?[0-5]?\d?\b|\b\d{1,2}[:.]\d{2}\b",
                normalized,
            ))
            if has_time:
                for turn in reversed(history or []):
                    if turn.role != "assistant":
                        continue
                    prior = _normalized_text(turn.content)
                    if not re.search(r"disponib\w*|horario|reserva", prior):
                        continue
                    requested_date = _history_offer_date(turn.content, today)
                    if requested_date:
                        missing = [field for field in selection.missing_information if field != "date"]
                        return selection.model_copy(update={"date": requested_date, "missing_information": missing})
            return selection
        weekdays = {
            "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
            "viernes": 4, "sabado": 5, "domingo": 6,
        }
        days_ahead = (weekdays[weekday_match.group()] - today.weekday()) % 7
        if days_ahead == 0 and "este " not in normalized[max(0, weekday_match.start() - 8):weekday_match.start()]:
            days_ahead = 7
        resolved = today + timedelta(days=days_ahead)
        missing = [field for field in selection.missing_information if field != "date"]
        return selection.model_copy(update={"date": resolved, "missing_information": missing})

    # "En la ma?ana" and "por la ma?ana" refer to a time of day, not tomorrow.
    prefix = normalized[max(0, match.start() - 12):match.start()]
    if match.group() == "manana" and re.search(r"(?:en|por)\s+la\s+$", prefix):
        return selection

    phrase = match.group()
    offset = (
        2 if phrase.startswith("pasado")
        else -2 if phrase == "anteayer"
        else 1 if phrase == "manana"
        else -1 if phrase == "ayer"
        else 0
    )
    resolved = today + timedelta(days=offset)
    missing = [field for field in selection.missing_information if field != "date"]
    return selection.model_copy(update={"date": resolved, "missing_information": missing})


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _is_greeting_only(message: str) -> bool:
    text = re.sub(r"[^a-z0-9\s]", " ", _normalized_text(message))
    text = " ".join(text.split())
    return bool(re.fullmatch(
        r"(?:hola(?:\s+nox)?(?:\s+(?:buenas(?:\s+(?:dias|tardes|noches))?|buenos\s+dias))?|"
        r"(?:muy\s+)?buenas(?:\s+(?:dias|tardes|noches))?|buenos\s+dias)",
        text,
    ))


def _is_conversation_closing(message: str) -> bool:
    text = re.sub(r"[^a-z0-9\s]", " ", _normalized_text(message))
    text = " ".join(text.split())
    return bool(re.fullmatch(
        r"(?:(?:(?:muchas|mil)\s+)?gracias(?:\s+por\s+(?:todo|la\s+ayuda|tu\s+ayuda|"
        r"la\s+informacion|la\s+atencion|tu\s+tiempo))?|te\s+(?:lo\s+)?agradezco(?:\s+mucho)?|"
        r"no\s+gracias|eso\s+(?:es|seria)\s+todo(?:\s+gracias|\s+por\s+ahora)?|"
        r"por\s+ahora\s+(?:es\s+todo|nada\s+mas)|nada\s+mas(?:\s+gracias)?|"
        r"hasta\s+(?:luego|pronto)|nos\s+vemos|me\s+despido|chao(?:\s+gracias)?|adios|bye)",
        text,
    ))


def _route_thematic_dated_reservation(
    selection: RouteSelection,
    message: str,
    today: date,
) -> RouteSelection:
    """Force a live availability lookup for a dated room-theme reservation request."""
    normalized = _normalized_text(message)
    theme = bool(re.search(r"\b(?:terror|terrorific\w*|miedo|aventura\w*|suspenso|intriga)\b", normalized))
    intent = bool(re.search(
        r"\b(?:reserv\w*|separ\w*|agend\w*|quiero\s+(?:ir|jugar)|"
        r"me\s+gustaria|quisiera|deseo|me\s+interesa)\b",
        normalized,
    ))
    if not theme or not intent:
        return selection

    requested_date = selection.date
    date_match = re.search(
        r"\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)(?:\s+de\s+(\d{4}))?\b",
        normalized,
    )
    if date_match:
        year = int(date_match.group(3)) if date_match.group(3) else today.year
        try:
            requested_date = date(year, SPANISH_MONTHS[date_match.group(2)], int(date_match.group(1)))
        except ValueError:
            return selection
        if not date_match.group(3) and requested_date < today:
            requested_date = requested_date.replace(year=year + 1)
    if requested_date is None:
        requested_date = _fill_relative_date(selection, message, today).date
    if requested_date is None:
        return selection
    return selection.model_copy(update={
        "route": "get_availability",
        "date": requested_date,
        "room": None,
        "missing_information": [],
    })


def _is_thematic_weekend_reservation(message: str) -> bool:
    """Identify a themed reservation whose weekend date still needs a day choice."""
    normalized = _normalized_text(message)
    has_theme = bool(re.search(
        r"\b(?:terror|terrorific\w*|miedo|aventura\w*|suspenso|intriga)\b",
        normalized,
    ))
    has_reservation_intent = bool(re.search(
        r"\b(?:reserv\w*|separ\w*|agend\w*|me\s+gustaria|quisiera|deseo)\b",
        normalized,
    ))
    asks_weekend = bool(re.search(r"\bfin\s+de\s+semana\b", normalized))
    specifies_day = bool(re.search(
        r"\b(?:sabado|domingo)\b|\b\d{1,2}\s+de\s+"
        r"(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\b",
        normalized,
    ))
    return has_theme and has_reservation_intent and asks_weekend and not specifies_day


def _route_specific_time_question(
    selection: RouteSelection,
    message: str,
    today: date,
) -> RouteSelection:
    """Use live availability when an opening-hours route actually asks about a slot."""
    if selection.route not in {"get_opening_hours", "clarify"}:
        return selection
    normalized = _normalized_text(message)
    asks_if_can_attend = bool(re.search(
        r"podemos ir|puedo ir|se puede ir|hay (?:cupo|disponibilidad)|esta libre|estan libres|esta disponible",
        normalized,
    ))
    mentions_time = bool(re.search(
        r"\ba\s+las?\s+\d{1,2}(?::[0-5]\d)?\b|\b\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?\b|\b\d{1,2}\s+de\s+la\s+(?:manana|tarde|noche)\b",
        normalized,
    ))
    if not asks_if_can_attend or not mentions_time:
        return selection

    requested_date = selection.date
    if requested_date is None and selection.day_of_week is not None:
        # Logic API uses Sunday=0; Python date.weekday uses Monday=0.
        weekday = (selection.day_of_week - 1) % 7
        days_ahead = (weekday - today.weekday()) % 7
        requested_date = today + timedelta(days=days_ahead)
    if requested_date is None:
        weekdays = {
            "domingo": 0, "lunes": 1, "martes": 2, "miercoles": 3,
            "jueves": 4, "viernes": 5, "sabado": 6,
        }
        for name, api_weekday in weekdays.items():
            if re.search(rf"\b{name}\b", normalized):
                weekday = (api_weekday - 1) % 7
                days_ahead = (weekday - today.weekday()) % 7
                requested_date = today + timedelta(days=days_ahead)
                break
    if requested_date is None:
        return selection
    missing = [field for field in selection.missing_information if field != "date"]
    return selection.model_copy(update={
        "route": "get_availability",
        "date": requested_date,
        "day_of_week": None,
        "missing_information": missing,
    })


def _route_room_age_question(selection: RouteSelection, message: str) -> RouteSelection:
    """Prefer structured room data for a named room's minimum age without an adult."""
    normalized = _normalized_text(message)
    asks_room_age = "edad" in normalized and bool(re.search(
        r"sin\s+adulto|adulto\s+responsable|entrar\s+sin|ingresar\s+sin", normalized
    ))
    if asks_room_age and selection.room and selection.route in {
        "search_business_knowledge", "get_opening_hours", "clarify"
    }:
        return selection.model_copy(update={
            "route": "get_rooms",
            "missing_information": [],
        })
    return selection


def _route_child_admission_question(
    selection: RouteSelection,
    message: str,
) -> RouteSelection:
    """Use the age policy and current room catalog for questions about children."""
    normalized = _normalized_text(message)
    mentions_children = bool(re.search(r"\b(?:hijos?|ninos?|menores)\b", normalized))
    asks_admission = bool(re.search(
        r"\b(?:pueden|podrian|puedo|podria|dejan|dejar|entrar|ingresar|jugar|ir|llevar)\b",
        normalized,
    ))
    # Theme requests need the recommendation route so RAG can map themes to rooms.
    if re.search(r"\b(?:terror|miedo|aventura|familiar|suspenso|intriga)\b", normalized):
        return selection
    if mentions_children and asks_admission and selection.route in {
        "clarify", "search_business_knowledge", "get_rooms", "get_opening_hours"
    }:
        has_theme = bool(re.search(r"\b(?:terror|miedo|aventura|familiar|suspenso|intriga)\b", normalized))
        return selection.model_copy(update={
            "route": "get_rooms",
            "query": "__child_admission_policy__",
            "categories": ["faq", "age_policy"] if has_theme else ["age_policy"],
            "room": None,
            "missing_information": [],
        })
    return selection


def _format_child_admission_answer(
    evidence: dict,
    message: str,
    history: list[ChatTurn] | None,
) -> str:
    # Prior assistant messages may mention example rooms or capacity ranges.
    # Only customer messages establish their choice, group size, and plans.
    context = ". ".join(
        _normalized_text(turn.content)
        for turn in [*(history or []), ChatTurn(role="user", content=message)]
        if turn.role == "user"
    )
    policy = " ".join(item.get("text", "") for item in evidence.get("rag_facts", []))
    if not re.search(r"desde\s+los?\s+nueve|desde\s+nueve|9\s+anos", _normalized_text(policy)):
        return "No pude verificar con suficiente certeza la regla de ingreso para menores. El equipo de Logic debe confirmarla. ¿Quieres que consulte otra sala?"

    age_context = context
    age_prefix = re.search(r"(?:hijos?|ninos?|menores)[^.!?]{0,60}", context)
    if age_prefix:
        age_context = age_prefix.group()
    ages = [int(number) for number in re.findall(r"\b\d{1,2}\b", age_context)]
    ages = [age for age in ages if 0 < age < 18]
    if not ages:
        return "Sí, los niños desde los 9 años pueden ingresar acompañados por un adulto responsable. ¿Qué edades tienen para orientarte mejor?"
    if min(ages) < 9:
        return "La regla documentada permite el ingreso desde los 9 años cuando van con un adulto responsable. Para una edad menor, el equipo de Logic debe verificarlo. ¿Quieres que consulte el caso?"

    room_facts = [item for item in evidence.get("api_facts", []) if item.get("name")]
    room = None
    for candidate in room_facts:
        normalized_name = _normalized_text(candidate["name"])
        alias = normalized_name.split(":", 1)[0].strip()
        if re.search(rf"\b{re.escape(alias)}\b", context):
            room = candidate
            break
    room_name = room.get("name") if room else None
    age_limit = room.get("minimum_age_without_adult") if room else None
    adult_is_going = bool(re.search(
        r"\b(?:voy|vamos|iremos|me\s+gustaria\s+ir|ire)\b.{0,35}\bcon\s+mis\s+hijos\b|"
        r"\bcon\s+mis\s+hijos\b.{0,35}\b(?:adulto|padre|madre|3\s+personas)\b",
        context,
    ))
    if not adult_is_going:
        if room_name and age_limit and min(ages) < age_limit:
            return f"Para {room_name}, se requiere un adulto responsable si algún menor tiene menos de {age_limit} años. Los niños desde los 9 años pueden ingresar acompañados. ¿Irá un adulto responsable con ellos?"
        return "La política permite que los niños desde los 9 años ingresen acompañados por un adulto responsable. ¿Irá un adulto con ellos?"

    if not room_name:
        return "Sí 🙂. Los niños desde los 9 años pueden ingresar acompañados por un adulto responsable. ¿Qué sala les interesa para revisar sus condiciones y capacidad?"

    answer = f"Sí 🙂. {room_name} permite el ingreso de niños desde los 9 años cuando van acompañados por un adulto responsable."
    if age_limit and min(ages) < age_limit:
        answer += f" Para ingresar sin adulto se requiere tener {age_limit} años; como irían contigo, cumplen la condición de acompañamiento."

    attendees_match = re.search(r"\b(\d{1,2})\s+personas\b", context)
    attendees = int(attendees_match.group(1)) if attendees_match else None
    minimum, maximum = room.get("min_players"), room.get("max_players")
    if attendees is not None and minimum is not None and maximum is not None:
        if minimum <= attendees <= maximum:
            answer += f" Para {attendees} participantes, también están dentro del rango actual de {minimum} a {maximum} personas."
        else:
            answer += f" El catálogo actual indica un rango de {minimum} a {maximum} participantes; el grupo de {attendees} requiere revisión antes de confirmar que puede jugar."
    elif minimum is not None and maximum is not None:
        answer += f" El rango actual de la sala es de {minimum} a {maximum} participantes."
    return answer + " ¿Quieres que revisemos disponibilidad para una fecha?"


def _past_availability_date(selection: RouteSelection, today: date) -> bool:
    return (
        selection.route == "get_availability"
        and selection.date is not None
        and selection.date < today
    )


def _route_dated_reservation_to_availability(
    selection: RouteSelection,
    message: str,
) -> RouteSelection:
    """Check live availability for a dated reservation even when details are missing."""
    if selection.route not in {
        "clarify", "get_rooms", "get_opening_hours", "get_availability",
        "search_business_knowledge", "check_room_policy", "get_quote",
    } or selection.date is None:
        return selection
    normalized = _normalized_text(message)
    has_time = bool(re.search(
        r"\ba\s+las?\s+\d{1,2}(?::|\.)?[0-5]?\d?\b|\b\d{1,2}[:.]\d{2}\b|"
        r"\b\d{1,2}\s+de\s+(?:la\s+)?(?:manana|tarde|noche)\b",
        normalized,
    ))
    explicit_availability_question = bool(re.search(
        r"\b(?:disponibilidad|disponible|disponibles|hay\s+(?:espacio|horarios?)|"
        r"horarios?\s+(?:libres|disponibles))\b",
        normalized,
    ))
    availability_intent = explicit_availability_question or bool(re.search(
        r"\b(?:reserv\w*|separ\w*|agend\w*|horarios?\s+disponibles|"
        r"quiero\s+(?:ir|jugar|reserv\w*)|me\s+gustaria|quisiera|deseo|"
        r"me\s+interesa\s+(?:ir|jugar|reserv\w*))\b",
        normalized,
    )) or has_time
    if not availability_intent:
        return selection
    return selection.model_copy(update={
        "route": "get_availability",
        "query": None,
        "missing_information": [],
    })


def _route_large_group_split_pricing_to_knowledge(
    selection: RouteSelection,
    message: str,
) -> RouteSelection:
    """Use the documented large-group rule when a price spans multiple rooms."""
    normalized = _normalized_text(message)
    count = re.search(r"\b(\d{1,3})\s*(?:personas?|jugadores?)\b", normalized)
    asks_price = bool(re.search(
        r"\b(?:precio|precios|cobran|cobramos|cuesta|tarifa|pagar)\b", normalized
    ))
    spans_rooms = bool(re.search(
        r"\b(?:dos|varias|multiples)\s+salas\b|\b(?:repart\w*|distribuid\w*)\b.{0,35}\bsalas\b",
        normalized,
    ))
    if (
        selection.route in {"get_rates", "clarify"}
        and count is not None
        and int(count.group(1)) >= 7
        and asks_price
        and spans_rooms
    ):
        return selection.model_copy(update={
            "route": "search_business_knowledge",
            "query": message,
            "categories": ["pricing"],
            "missing_information": [],
        })
    return selection


def _route_room_capacity_question_to_api(
    selection: RouteSelection,
    message: str,
) -> RouteSelection:
    """Use the room catalog for ordinary capacity, not large-group pricing policy."""
    normalized = _normalized_text(message)
    asks_capacity = bool(re.search(
        r"\b(?:caben|cabe|capacidad|admite|acepta|entramos|entran|entrar)\b|"
        r"\ben\s+una\s+sola\s+sala\b|\btodos\s+juntos\b",
        normalized,
    ))
    if asks_capacity and selection.room and selection.route in {
        "search_business_knowledge", "get_rates", "clarify"
    }:
        return selection.model_copy(update={
            "route": "get_rooms",
            "missing_information": [],
        })
    return selection


def _route_price_question_without_exact_date_to_rates(
    selection: RouteSelection,
    message: str,
) -> RouteSelection:
    """Offer published room rates when a total quote lacks an exact date or group size."""
    if selection.route != "clarify" or selection.date is not None:
        return selection
    normalized = _normalized_text(message)
    asks_price = bool(re.search(
        r"\b(?:precio|precios|cuanto\s+(?:vale|cuesta|pagariamos|pagar)|valor)\b",
        normalized,
    ))
    is_cafeteria_price = bool(re.search(r"\b(?:cafeteria|menu|comida|bebida)\b", normalized))
    if asks_price and not is_cafeteria_price:
        return selection.model_copy(update={
            "route": "get_rates",
            "missing_information": [],
        })
    return selection


def _price_follow_up_day_type(
    message: str,
    history: list[ChatTurn] | None,
) -> tuple[str, int] | None:
    """Resolve a weekday/weekend answer in an active price conversation."""
    if not history or history[-1].role != "assistant":
        return None
    normalized = _normalized_text(message)
    weekdays = {
        "lunes": "weekday", "martes": "weekday", "miercoles": "weekday",
        "jueves": "weekday", "viernes": "weekend", "sabado": "weekend",
        "domingo": "weekend",
    }
    selected_day_type = next((
        day_type for day, day_type in weekdays.items()
        if re.search(rf"\b{day}\b", normalized)
    ), None)
    if selected_day_type is None:
        return None

    prior_user_text = [_normalized_text(turn.content) for turn in history if turn.role == "user"]
    prior_assistant_text = [_normalized_text(turn.content) for turn in history if turn.role == "assistant"]
    asked_about_price = any(re.search(
        r"\b(?:precio|precios|tarifa|cuanto\s+(?:vale|cuesta|pagar))\b", text
    ) for text in prior_user_text)
    asked_for_day_to_check_price = any(
        ("tarifa" in text or "precio" in text)
        and re.search(r"\b(?:fecha|dia)\b", text)
        for text in prior_assistant_text
    )
    if not asked_about_price or not asked_for_day_to_check_price:
        return None

    attendees = None
    for text in reversed(prior_user_text):
        match = re.search(
            r"\b(?:seriamos|seremos|somos|vamos\s+a\s+ser|para)\s+(\d{1,3})\b|"
            r"\b(\d{1,3})\s+personas?\b",
            text,
        )
        if match:
            attendees = int(match.group(1) or match.group(2))
            break
    if attendees is None:
        return None
    return selected_day_type, attendees


def _price_follow_up_attendees(message: str, history: list[ChatTurn] | None) -> int | None:
    """Recover a group size when it answers the assistant's question in a price exchange."""
    if not history or history[-1].role != "assistant":
        return None
    current = _normalized_text(message)
    match = re.search(
        r"\b(?:seriamos|seremos|somos|vamos\s+a\s+ser|para|serian)\s+(\d{1,3})\b|"
        r"\b(\d{1,3})\s+(?:personas?|jugadores?)\b",
        current,
    )
    if not match:
        return None
    prior_users = [_normalized_text(turn.content) for turn in history if turn.role == "user"]
    last_assistant = _normalized_text(history[-1].content)
    had_price_question = any(re.search(
        r"\b(?:precio|precios|tarifa|cuanto\s+(?:vale|cuesta|pagar))\b", text
    ) for text in prior_users)
    assistant_asked_group_size = bool(re.search(
        r"cuant[oa]s?\s+(?:personas?|jugadores?)|\bgrupo\b.{0,30}\bcantid", last_assistant
    ))
    if not had_price_question or not assistant_asked_group_size:
        return None
    return int(match.group(1) or match.group(2))


def _format_attendee_price_ranges(evidence: dict, attendees: int) -> str:
    """Report the published per-person price for a group when the date is unknown."""
    rates = [
        fact for fact in evidence.get("api_facts", [])
        if fact.get("day_type") in {"weekday", "weekend"}
        and isinstance(fact.get("players"), int)
        and isinstance(fact.get("price_per_person"), int)
    ]
    if not rates:
        return "No pude verificar los precios para ese grupo. ?Quieres que el equipo de Logic los confirme?"
    day_labels = {
        "weekday": "entre semana (lunes a jueves)",
        "weekend": "en fin de semana o festivo",
    }
    results = []
    for day_type in ("weekday", "weekend"):
        day_rates = [rate for rate in rates if rate["day_type"] == day_type]
        if not day_rates:
            continue
        exact = [rate for rate in day_rates if rate["players"] == attendees]
        if exact:
            amount = exact[-1]["price_per_person"]
            results.append(f"{day_labels[day_type]}: ${amount:,} COP por persona".replace(",", "."))
        else:
            amounts = [rate["price_per_person"] for rate in day_rates]
            low, high = min(amounts), max(amounts)
            if low == high:
                value = f"${low:,} COP".replace(",", ".")
            else:
                value = f"de ${low:,} a ${high:,} COP".replace(",", ".")
            results.append(f"{day_labels[day_type]}: {value} por persona")
    if not results:
        return "No pude verificar los precios para ese grupo. ?Quieres que el equipo de Logic los confirme?"
    return (
        f"Para {attendees} personas, los precios publicados son: "
        + "; ".join(results)
        + ". Si me dices la fecha exacta, consulto el valor total para el grupo."
    )


def _format_day_type_price(evidence: dict, attendees: int, day_type: str) -> str:
    """Answer a weekday/weekend price follow-up from published API rates."""
    rates = [
        fact for fact in evidence.get("api_facts", [])
        if fact.get("day_type") == day_type
        and isinstance(fact.get("players"), int)
        and isinstance(fact.get("price_per_person"), int)
    ]
    if not rates:
        return "No pude verificar la tarifa para ese d?a. ?Quieres que el equipo de Logic la confirme?"
    applicable_attendees = min(attendees, max(rate["players"] for rate in rates))
    exact = [rate for rate in rates if rate["players"] == applicable_attendees]
    if not exact:
        exact = [rate for rate in rates if rate["players"] <= applicable_attendees]
    if not exact:
        return "No encuentro una tarifa publicada para ese grupo. ?Quieres que el equipo de Logic lo revise?"
    price = exact[-1]["price_per_person"]
    day_label = "entre semana" if day_type == "weekday" else "en fin de semana o festivo"
    price_label = f"${price:,}".replace(",", ".")
    return (
        f"Para {attendees} personas, la tarifa {day_label} es de {price_label} COP por persona. "
        "Si me dices la fecha exacta, puedo consultar la disponibilidad."
    )


def _route_location_link_to_knowledge(
    selection: RouteSelection,
    message: str,
) -> RouteSelection:
    """Use the location policy for map links and avoid asking a generic question."""
    normalized = _normalized_text(message)
    asks_location_link = bool(re.search(
        r"\b(?:maps|mapas|google\s+maps|ubicacion|direccion)\b", normalized
    ))
    asks_for_link = bool(re.search(
        r"\b(?:link|enlace|url|mapa)\b|pasame|compart\w*", normalized
    ))
    if selection.route == "clarify" and asks_location_link and asks_for_link:
        return selection.model_copy(update={
            "route": "search_business_knowledge",
            "query": message,
            "categories": ["faq"],
            "missing_information": [],
        })
    return selection


def _route_activity_explanation_to_knowledge(
    selection: RouteSelection,
    message: str,
    history: list[ChatTurn] | None = None,
) -> RouteSelection:
    """Recognize varied, including context-dependent, questions about the experience."""
    normalized = _normalized_text(message)
    intent = bool(re.search(
        r"\b(?:que\s+es|que\s+son|de\s+que\s+(?:se\s+)?trata|en\s+que\s+consiste|"
        r"como\s+(?:es|funciona|se\s+juega)|que\s+(?:hacen|se\s+hace|ofrecen|ofrece)|"
        r"que\s+hay\s+que\s+hacer|que\s+toca\s+hacer|que\s+tipo\s+de|"
        r"para\s+que\s+sirve|explicame|cuentame|quiero\s+saber|me\s+(?:explicas|cuentas)|"
        r"nunca\s+he\s+ido|primera\s+vez|que\s+es)\b",
        normalized,
    ))
    mentions_concept = bool(re.search(
        r"\b(?:actividad|juego|escape\s*room|experiencia|lugar|sitio|logic|plan|dinamica)\b|"
        r"\b(?:aqui|alli|aca|alla|este\s+lugar|ese\s+lugar|uno\s+llega)\b",
        normalized,
    ))
    recent_context = " ".join(
        _normalized_text(turn.content)
        for turn in (history or [])[-4:]
    )
    has_experience_context = bool(re.search(
        r"\b(?:actividad|juego|escape\s*room|experiencia|salas?\s+de\s+escape|logic)\b",
        recent_context,
    ))
    asks_for_experience_video = bool(re.search(
        r"\b(?:video|video\s+explicativo|reel)\b|\b(?:tienes|hay|cuentas\s+con)\b.{0,30}\b(?:video|reel)\b",
        normalized,
    )) and has_experience_context
    short_contextual_question = len(normalized.split()) <= 7 and bool(re.search(
        r"\b(?:como\s+es|como\s+funciona|en\s+que\s+consiste|que\s+es|que\s+se\s+hace|y\s+como)\b",
        normalized,
    ))
    asks_activity = (
        intent and (mentions_concept or (short_contextual_question and has_experience_context))
    ) or asks_for_experience_video

    # Questions about a particular named room remain on the room/API path.
    has_specific_room = bool(selection.room)
    if asks_activity and not has_specific_room and selection.route in {"clarify", "search_business_knowledge"}:
        return selection.model_copy(update={
            "route": "search_business_knowledge",
            "query": (
                "video explicativo de que es un escape room"
                if asks_for_experience_video
                else "explicacion general de que es un escape room y actividad de Logic"
            ),
            "categories": ["faq"],
            "missing_information": [],
        })
    return selection


def _route_thematic_room_recommendation(
    selection: RouteSelection,
    message: str,
) -> RouteSelection:
    """Combine the current room catalog and RAG when the customer names a theme."""
    if selection.query and selection.query.startswith("theme:"):
        return selection
    normalized = _normalized_text(message)
    theme = next((name for name, pattern in (
        ("terror", r"\bterror\b|\bterrorific\w*|\bmiedo\b|\basust\w*"),
        ("aventura", r"\baventura\w*|\bfamiliar\b"),
        ("suspenso", r"\bsuspenso\b|\bintriga\b"),
    ) if re.search(pattern, normalized)), None)
    asks_room_advice = bool(re.search(
        r"\b(?:sala|jugar|entrar|recomiend\w*|gustaria|interes\w*|busc\w*|prefer\w*|hij\w*|ninos?|menores?)\b",
        normalized,
    ))
    if theme and asks_room_advice and selection.route in {
        "clarify", "search_business_knowledge", "check_room_policy", "get_rooms"
    }:
        return selection.model_copy(update={
            "route": "get_rooms",
            "query": f"recomendación de sala temática {theme}; verificar edades, acompañamiento y límites con la política vigente",
            "categories": ["faq"],
            "missing_information": [],
        })
    return selection


def _route_ambiguous_information_request(
    selection: RouteSelection,
    message: str,
    history: list[ChatTurn] | None = None,
) -> RouteSelection:
    """Ask what topic the customer means instead of guessing a business fact."""
    normalized = _normalized_text(message)
    asks_for_more = bool(re.search(
        r"\b(?:mas\s+info(?:rmacion)?|mas\s+detalles|saber\s+mas|informacion\s+adicional|"
        r"(?:quiero|quisiera|me\s+gustaria|me\s+interesa)\s+(?:conocer|saber)\s+mas|"
        r"(?:quiero|quisiera|me\s+gustaria|me\s+interesa)\s+(?:mas\s+)?info(?:rmacion)?|"
        r"(?:dame|cuentame|hablame|explicame|explicarme)\s+(?:un\s+poco\s+)?mas|"
        r"(?:me\s+)?(?:puedes|podrias)\s+(?:contar|decir|dar|explicar(?:me)?)\b.{0,24}\b(?:mas|info|detalles?)|"
        r"(?:quisiera|me\s+gustaria)\s+(?:tener|recibir)\s+mas\s+(?:detalles?|info(?:rmacion)?)|"
        r"(?:quiero|quisiera)\s+conocer\s+(?:mejor|un\s+poco\s+mas))\b",
        normalized,
    ))
    if not asks_for_more or selection.room:
        return selection

    topic_terms = re.compile(
        r"\b(?:sala|salas|precio|precios|tarifa|reserva|reservar|fecha|horario|disponibilidad|"
        r"ubicacion|direccion|mapa|maps|cafeteria|menu|cumpleanos|terror|aventura|suspenso|"
        r"escape\s*room|juego|actividad|pago|abono|ninos|hijos)\b"
    )
    if topic_terms.search(normalized):
        return selection
    recent_context = " ".join(
        _normalized_text(turn.content) for turn in (history or [])[-4:]
    )
    if topic_terms.search(recent_context):
        return selection

    return selection.model_copy(update={
        "route": "clarify",
        "query": None,
        "categories": [],
        "missing_information": ["question"],
        "room": None,
        "date": None,
        "attendees": None,
    })


def _is_room_catalog_and_prices_request(message: str) -> bool:
    normalized = _normalized_text(message)
    asks_rooms = bool(re.search(r"\b(?:salas?|habitaciones|tematicas?)\b", normalized))
    asks_prices = bool(re.search(r"\b(?:precios?|tarifas?|cuanto\s+cuesta|cuanto\s+vale)\b", normalized))
    return asks_rooms and asks_prices


def _route_room_catalog_and_prices(
    selection: RouteSelection,
    message: str,
) -> RouteSelection:
    """Fetch room catalog and reference prices together for a combined request."""
    if (
        _is_room_catalog_and_prices_request(message)
        and selection.date is None
        and selection.route in {"clarify", "get_rates", "get_rooms", "search_business_knowledge"}
    ):
        return selection.model_copy(update={
            "route": "get_rooms",
            "query": "__room_catalog_and_reference_prices__",
            "categories": [],
            "room": None,
            "missing_information": [],
        })
    return selection


def _is_room_catalog_question(message: str) -> bool:
    normalized = _normalized_text(message)
    asks_about_rooms = bool(re.search(
        r"\b(?:salas?|habitaciones|tematicas?|experiencias)\b", normalized
    ))
    asks_for_options = bool(re.search(
        r"\b(?:que|cuales?|cu[aá]les?|opciones?|tienen|hay|ofrecen|cuentan|disponibles?|"
        r"puedo\s+(?:elegir|escoger|jugar)|pueden\s+(?:elegir|escoger))\b",
        normalized,
    ))
    return asks_about_rooms and asks_for_options


def _route_room_catalog_question(
    selection: RouteSelection,
    message: str,
) -> RouteSelection:
    if (
        _is_room_catalog_question(message)
        and not _is_room_catalog_and_prices_request(message)
        and selection.date is None
        and selection.route in {
            "clarify", "get_rooms", "get_rates", "get_availability", "search_business_knowledge"
        }
    ):
        return selection.model_copy(update={
            "route": "get_rooms",
            "query": "__room_catalog__",
            "categories": [],
            "room": None,
            "missing_information": [],
        })
    return selection


def _format_room_catalog(evidence: dict) -> str:
    rooms = [fact for fact in evidence.get("api_facts", []) if fact.get("name")]
    if not rooms:
        return "No pude verificar ahora las salas disponibles en Logic. ¿Quieres que el equipo lo revise?"
    room_lines = []
    for room in rooms:
        line = f"• {room['name']}"
        if room.get("description"):
            line += f": {room['description']}"
        details = []
        if room.get("duration_minutes"):
            details.append(f"{room['duration_minutes']} minutos")
        if room.get("min_players") and room.get("max_players"):
            details.append(f"de {room['min_players']} a {room['max_players']} personas")
        if details:
            line += f" ({'; '.join(details)})"
        room_lines.append(line)
    return (
        "Claro que sí 🙂. Estas son las salas que ofrecemos:\n"
        + "\n".join(room_lines)
        + "\n\nSi se refieren a horarios concretos, puedo revisarlos para la fecha que me indiquen. ¿Cuál sala les interesa?"
    )


def _is_location_and_prices_request(message: str) -> bool:
    normalized = _normalized_text(message)
    asks_location = bool(re.search(
        r"\b(?:donde\s+(?:queda|es|esta|estan)|ubicacion|direccion|como\s+llegar)\b",
        normalized,
    ))
    asks_prices = bool(re.search(
        r"\b(?:cuanto\s+(?:cuesta|vale)|precio|precios|tarifa|tarifas)\b",
        normalized,
    ))
    return asks_location and asks_prices


def _route_location_and_prices(
    selection: RouteSelection,
    message: str,
) -> RouteSelection:
    if (
        _is_location_and_prices_request(message)
        and selection.date is None
        and selection.route in {"clarify", "get_rates", "search_business_knowledge"}
    ):
        return selection.model_copy(update={
            "route": "get_rates",
            "query": "__location_and_prices__",
            "categories": [],
            "missing_information": [],
        })
    return selection


def _format_location_and_prices(evidence: dict) -> str:
    rag_facts = evidence.get("rag_facts", [])
    address = None
    for fact in rag_facts:
        match = re.search(
            r"direcci[oó]n documentada de Logic Escape Room es ([^.]+)",
            fact.get("text", ""),
            re.IGNORECASE,
        )
        if match:
            address = match.group(1).strip()
            break
    map_link = next((
        fact.get("url") for fact in evidence.get("operational_facts", [])
        if fact.get("name") == "ubicacion_maps_url" and fact.get("url")
    ), None)
    location_lines = []
    if address:
        location_lines.append(f"Estamos en {address}.")
    if map_link:
        location_lines.append(f"Puedes ver cómo llegar aquí: {map_link}")
    location_message = "Claro que sí 🙂. " + " ".join(location_lines) if location_lines else (
        "Claro que sí 🙂. No pude verificar ahora la dirección de Logic; el equipo puede confirmártela."
    )

    grouped: dict[str, list[int]] = {"weekday": [], "weekend": []}
    for rate in evidence.get("api_facts", []):
        day_type = rate.get("day_type")
        amount = rate.get("price_per_person")
        if day_type in grouped and isinstance(amount, int):
            grouped[day_type].append(amount)

    def describe(label: str, amounts: list[int]) -> str | None:
        if not amounts:
            return None
        low, high = min(amounts), max(amounts)
        if low == high:
            return f"{label}: ${low:,} COP por persona".replace(",", ".")
        return f"{label}: de ${low:,} a ${high:,} COP por persona".replace(",", ".")

    price_lines = [line for line in (
        describe("Entre semana (lunes a jueves)", grouped["weekday"]),
        describe("Fines de semana y festivos", grouped["weekend"]),
    ) if line]
    price_message = (
        "Estos son los precios de referencia por persona:\n" + "\n".join(price_lines)
        if price_lines else "No pude verificar ahora los precios; el equipo de Logic debe confirmarlos."
    )
    follow_up = "¿Cuántas personas serían y para qué fecha quieres consultar?"
    return "\n\n".join((location_message, price_message, follow_up))


def _format_thematic_room_availability(evidence: dict, query: str) -> str:
    """Present live options for a theme that maps to several active rooms."""
    room_names = [name.strip() for name in query.partition(":")[2].split("|") if name.strip()]
    availability = next((
        fact for fact in evidence.get("api_facts", [])
        if isinstance(fact, dict) and fact.get("date") and isinstance(fact.get("rooms"), list)
    ), {})
    try:
        requested_date = date.fromisoformat(availability.get("date", ""))
    except ValueError:
        requested_date = None
    months = (
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    )
    date_label = (
        f"el {requested_date.day} de {months[requested_date.month - 1]}"
        if requested_date else "la fecha consultada"
    )
    live_rooms = availability.get("rooms", [])
    lines = []
    for name in room_names:
        room = next((
            item for item in live_rooms
            if _normalized_text(item.get("room_name", "")) == _normalized_text(name)
        ), None)
        available_slots = [slot.get("start") for slot in (room or {}).get("slots", []) if slot.get("available")]
        if available_slots:
            labels = []
            for value in available_slots:
                try:
                    hour, minute = (int(part) for part in value.split(":", 1))
                    period = "a. m." if hour < 12 else "p. m."
                    shown_hour = hour % 12 or 12
                    labels.append(f"{shown_hour}:{minute:02d} {period}")
                except (AttributeError, TypeError, ValueError):
                    continue
            details = ", ".join(labels) if labels else "horarios disponibles"
            lines.append(f"• {name}: {details}")
        else:
            lines.append(f"• {name}: no aparecen horarios disponibles")
    if not lines:
        return f"No pude verificar horarios para {date_label}. ¿Quieres que el equipo de Logic lo revise?"
    next_question = (
        "\u00bfCu\u00e1l sala prefieres para continuar con la reserva?"
        if len(room_names) > 1
        else "\u00bfQu\u00e9 horario te sirve para continuar con la reserva?"
    )
    return (
        f"Claro que s\u00ed \U0001f642. Para {date_label}, estas son las opciones de esa tem\u00e1tica:\n"
        + "\n".join(lines)
        + "\n\n"
        + next_question
    )


def _format_room_catalog_and_prices(evidence: dict) -> str:
    facts = evidence.get("api_facts", [])
    rooms = [fact for fact in facts if "name" in fact]
    rates = [fact for fact in facts if "day_type" in fact and "price_per_person" in fact]
    if not rooms or not rates:
        return "No pude verificar ahora mismo las salas y sus precios en el sistema de Logic. ¿Quieres que el equipo lo revise?"

    room_lines = []
    for room in rooms:
        line = f"• {room['name']}"
        if room.get("description"):
            line += f": {room['description']}"
        details = []
        if room.get("duration_minutes"):
            details.append(f"{room['duration_minutes']} minutos")
        if room.get("min_players") and room.get("max_players"):
            details.append(f"{room['min_players']} a {room['max_players']} personas")
        if details:
            line += f" ({'; '.join(details)})"
        room_lines.append(line)

    grouped: dict[str, list[int]] = {"weekday": [], "weekend": []}
    for rate in rates:
        day_type = rate.get("day_type")
        amount = rate.get("price_per_person")
        if day_type in grouped and isinstance(amount, int):
            grouped[day_type].append(amount)

    def describe(label: str, amounts: list[int]) -> str | None:
        if not amounts:
            return None
        low, high = min(amounts), max(amounts)
        if low == high:
            return f"{label}: ${low:,} COP por persona".replace(",", ".")
        return f"{label}: de ${low:,} a ${high:,} COP por persona".replace(",", ".")

    price_lines = [line for line in (
        describe("Entre semana (lunes a jueves)", grouped["weekday"]),
        describe("Fines de semana y festivos", grouped["weekend"]),
    ) if line]
    return "\n\n".join((
        "Claro que sí 🙂. Estas son las salas del catálogo actual:\n" + "\n".join(room_lines),
        "Estos son los precios de referencia por persona:\n" + "\n".join(price_lines),
        "El valor por persona depende del día y la cantidad de jugadores. ¿Cuántas personas serían para orientarte con el rango adecuado?",
    ))


SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _contact_details_follow_up(
    message: str,
    history: list[ChatTurn] | None,
    settings=None,
) -> str | None:
    """Continue a staged request for the customer's name and phone number."""
    if not history or history[-1].role != "assistant":
        return None
    prompt = unicodedata.normalize("NFKD", history[-1].content.casefold())
    prompt = "".join(char for char in prompt if not unicodedata.combining(char))
    asked_for_name = bool(re.search(
        r"a\s+nombre\s+de\s+quien|(?:me\s+)?compart\w*[^?]*nombre|nombre[^?]*(?:compart\w*|seria\s+la\s+solicitud)",
        prompt,
    ))
    asked_for_phone = bool(re.search(
        r"(?:compart\w*|me\s+das)[^?]*(?:celular|telefono|numero)|(?:celular|telefono)[^?]*(?:compart\w*|para\s+continuar)",
        prompt,
    ))
    if not asked_for_name and not asked_for_phone:
        return None

    phone_pattern = re.compile(r"(?<!\w)\+?\d[\d\s().-]{5,}\d(?!\w)")
    current_phone = phone_pattern.search(message)
    phone = current_phone.group().strip() if current_phone and 7 <= len(re.sub(r"\D", "", current_phone.group())) <= 15 else None

    name = None
    if current_phone:
        name = (message[:current_phone.start()] + " " + message[current_phone.end():]).strip()
        name = re.sub(r"^[\s,:;-]+|[\s,:;-]+$", "", name)
        name = re.sub(r"^(?:mi nombre es|soy)\s+", "", name, flags=re.IGNORECASE).strip()
    elif asked_for_name:
        name = message.strip()

    if not name:
        for index, turn in enumerate(history[:-1]):
            if turn.role != "assistant":
                continue
            prior_prompt = unicodedata.normalize("NFKD", turn.content.casefold())
            prior_prompt = "".join(char for char in prior_prompt if not unicodedata.combining(char))
            if "nombre" not in prior_prompt:
                continue
            candidate_turn = history[index + 1]
            if candidate_turn.role != "user" or phone_pattern.search(candidate_turn.content):
                continue
            candidate = candidate_turn.content.strip()
            if any(char.isalpha() for char in candidate):
                name = candidate

    if not phone:
        for index, turn in enumerate(history[:-1]):
            if turn.role != "assistant":
                continue
            prior_prompt = unicodedata.normalize("NFKD", turn.content.casefold())
            prior_prompt = "".join(char for char in prior_prompt if not unicodedata.combining(char))
            if not re.search(r"celular|telefono", prior_prompt):
                continue
            candidate_turn = history[index + 1]
            if candidate_turn.role != "user":
                continue
            candidate_phone = phone_pattern.search(candidate_turn.content)
            if candidate_phone and 7 <= len(re.sub(r"\D", "", candidate_phone.group())) <= 15:
                phone = candidate_phone.group().strip()

    if not name:
        return "Gracias. \u00bfMe compartes el nombre de quien realizar\u00e1 la solicitud?"
    if not phone:
        return f"Gracias, {name}. \u00bfMe compartes tambi\u00e9n tu n\u00famero de celular para continuar?"

    completed = _completed_reservation_message(message, history, settings, name, phone)
    if completed:
        return completed

    user_context = " ".join(turn.content.casefold() for turn in [*(history or []), ChatTurn(role="user", content=message)] if turn.role == "user")
    normalized_context = unicodedata.normalize("NFKD", user_context)
    normalized_context = "".join(char for char in normalized_context if not unicodedata.combining(char))
    has_deposit = bool(re.search(r"\b(abono|abonar|anticipo)\b", normalized_context))
    has_full_payment = bool(re.search(r"\b(total|completo|completa|todo|toda)\b", normalized_context))
    if has_full_payment and not has_deposit:
        return (
            f"Gracias, {name}. Una persona del equipo de Logic verificar\u00e1 el pago total y "
            "confirmar\u00e1 la reserva por este chat. \u00bfQuieres consultar algo m\u00e1s?"
        )
    if has_deposit and not has_full_payment:
        return (
            f"Gracias, {name}. Una persona del equipo de Logic revisar\u00e1 el pago del abono y "
            "confirmar\u00e1 la reserva por este chat. \u00bfQuieres consultar algo m\u00e1s?"
        )
    return (
        f"Gracias, {name}. Una persona del equipo de Logic revisar\u00e1 el pago y confirmar\u00e1 "
        "la reserva por este chat. \u00bfQuieres consultar algo m\u00e1s?"
    )


def _completed_reservation_message(message: str, history, settings, contact_name: str, contact_phone: str) -> str | None:
    if settings is None or not getattr(settings, "logic_operational_values_verified", False):
        return None
    method = getattr(settings, "logic_payment_method_for_deposits", None)
    payment_key = getattr(settings, "logic_bre_b_key", None)
    deposit = getattr(settings, "logic_typical_deposit_per_room_cop", None)
    if not method or not payment_key or deposit is None:
        return None

    phone = contact_phone
    name = contact_name

    turns = [*(history or []), ChatTurn(role="user", content=message)]
    room = None
    for index, turn in enumerate(turns[:-1]):
        if turn.role != "assistant":
            continue
        prompt = unicodedata.normalize("NFKD", turn.content.casefold())
        prompt = "".join(char for char in prompt if not unicodedata.combining(char))
        if "sala" in prompt and re.search(r"tienes en mente|cual.*sala|que sala", prompt):
            next_turn = turns[index + 1]
            if next_turn.role == "user" and len(next_turn.content.strip()) <= 80:
                room = next_turn.content.strip()
    if not room:
        for turn in reversed(turns):
            if turn.role == "assistant":
                room = _room_from_availability_offer(turn.content)
                if room:
                    break

    today = datetime.now(BOGOTA).date()
    requested_date = None
    for turn in reversed(turns):
        if turn.role == "assistant":
            parsed = _history_offer_date(turn.content, today)
            if parsed:
                requested_date = parsed
                break
    if requested_date is None:
        for turn in reversed(turns):
            if turn.role == "user":
                parsed = _fill_relative_date(RouteSelection(route="get_availability"), turn.content, today).date
                if parsed:
                    requested_date = parsed
                    break

    context = " ".join(turn.content for turn in turns)
    normalized_context = unicodedata.normalize("NFKD", context.casefold())
    normalized_context = "".join(char for char in normalized_context if not unicodedata.combining(char))
    numbers = {"uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
               "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
    attendee_matches = list(re.finditer(
        r"\b(?:para\s+(?:las?\s+)?|somos\s+)(\d+|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+personas?\b",
        normalized_context,
    ))
    attendees = None
    if attendee_matches:
        value = attendee_matches[-1].group(1)
        attendees = int(value) if value.isdigit() else numbers[value]

    selected_time = None
    for turn in reversed(turns):
        if turn.role != "assistant":
            continue
        text = unicodedata.normalize("NFKD", turn.content.casefold())
        text = "".join(char for char in text if not unicodedata.combining(char))
        if re.search(r"disponib\w*", text) and (
            "nombre" in text or re.search(r"sigue[n]?\s+disponib", text)
        ):
            time_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
            if time_match:
                selected_time = f"{int(time_match.group(1)):02d}:{time_match.group(2)}"
                break
    if selected_time is None:
        for turn in reversed(turns):
            if turn.role != "user":
                continue
            text = unicodedata.normalize("NFKD", turn.content.casefold())
            text = "".join(char for char in text if not unicodedata.combining(char))
            time_match = re.search(
                r"\b(?:a\s+las?\s+)?(\d{1,2})(?::([0-5]\d))?\s*(a\.?\s*m\.?|p\.?\s*m\.?)\b",
                text,
            )
            if time_match:
                hour = int(time_match.group(1))
                minute = time_match.group(2) or "00"
                meridiem = time_match.group(3).startswith("p")
                if meridiem and hour < 12:
                    hour += 12
                elif not meridiem and hour == 12:
                    hour = 0
                selected_time = f"{hour:02d}:{minute}"
                break

    if not all((room, requested_date, selected_time, attendees, name, phone)):
        return None

    month_names = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                   "agosto", "septiembre", "octubre", "noviembre", "diciembre")
    date_label = f"{requested_date.day} de {month_names[requested_date.month - 1]} de {requested_date.year}"
    deposit_label = f"${deposit:,.0f}".replace(",", ".")
    return (
        "\u2728 Perfecto, revisa los datos de tu solicitud:\n"
        f"\U0001f465 N\u00famero de personas: {attendees}\n"
        f"\U0001f575 Sala / tem\u00e1tica: {room}\n"
        f"\U0001f4c5 Fecha: {date_label}\n"
        f"\u23f0 Hora: {selected_time}\n"
        f"\U0001f9d1 Nombre de quien solicita: {name}\n"
        f"\U0001f44d N\u00famero de contacto: {phone}\n\n"
        f"Para continuar, puedes enviar el abono de {deposit_label} COP por sala mediante {method}, "
        f"a la llave {payment_key}. Cuando realices el pago, env\u00edanos el comprobante por este chat.\n\n"
        "Una persona del equipo de Logic revisar\u00e1 el pago y confirmar\u00e1 la reserva por este chat."
    )


def _history_offer_date(text: str, today: date) -> date | None:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    match = re.search(
        r"\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)(?:\s+de\s+(\d{4}))?\b",
        normalized,
    )
    if match:
        year = int(match.group(3)) if match.group(3) else today.year
        try:
            resolved = date(year, SPANISH_MONTHS[match.group(2)], int(match.group(1)))
        except ValueError:
            return None
        if not match.group(3) and resolved < today:
            try:
                resolved = resolved.replace(year=year + 1)
            except ValueError:
                return None
        return resolved

    relative = RouteSelection(route="get_availability")
    return _fill_relative_date(relative, text, today).date


def _recover_time_choice(
    selection: RouteSelection,
    message: str,
    history: list[ChatTurn] | None,
    today: date,
) -> RouteSelection:
    """Continue an offered-slot exchange when the customer answers with a time."""
    if not history:
        return selection
    normalized_message = unicodedata.normalize("NFKD", message.casefold())
    normalized_message = "".join(char for char in normalized_message if not unicodedata.combining(char))
    if selection.route == "get_availability" and selection.date is not None and re.search(
        r"\b(?:sala|salas|habitacion|terror|aventura|suspenso|canibal|secta|jumanji|manicomio)\b",
        normalized_message,
    ):
        # This is a new or revised room request, not just a short answer selecting
        # one of the previously offered times. Keep the current turn's intent.
        return selection
    has_time = re.search(
        r"\b(?:a\s+las?\s+)?\d{1,2}(?::\d{2})?\s*(?:a\.?\s*m\.?|p\.?\s*m\.?)?\b|\b\d{1,2}\s+de\s+(?:la\s+)?(?:manana|tarde|noche)\b",
        normalized_message,
    )
    if not has_time:
        return selection

    offer_index = None
    for index in range(len(history) - 1, -1, -1):
        turn = history[index]
        if turn.role != "assistant":
            continue
        offer = unicodedata.normalize("NFKD", turn.content.casefold())
        offer = "".join(char for char in offer if not unicodedata.combining(char))
        offered_availability = bool(re.search(r"disponib\w*", offer))
        asks_for_choice = bool(re.search(r"prefier\w*|cual.*sirve|cual.*prefier\w*|que horario", offer))
        if offered_availability and asks_for_choice:
            offer_index = index
            break
    if offer_index is None:
        return selection

    offer_turn = history[offer_index]
    requested_date = _history_offer_date(offer_turn.content, today)
    room = _room_from_availability_offer(offer_turn.content)
    if offer_index >= 2 and history[offer_index - 1].role == "user":
        preceding_question = history[offer_index - 2]
        if not room and preceding_question.role == "assistant" and "sala" in preceding_question.content.casefold():
            room = history[offer_index - 1].content.strip()

    if requested_date and room and len(room) <= 80:
        return RouteSelection(
            route="get_availability",
            date=requested_date,
            room=room,
            query=message,
        )

    missing = []
    if requested_date is None:
        missing.append("date")
    if not room:
        missing.append("room")
    return RouteSelection(route="clarify", missing_information=missing)


def _room_from_availability_offer(content: str) -> str | None:
    """Recover the room echoed in the assistant's prior live availability offer."""
    patterns = (
        r"[,;]\s*(?:la\s+sala\s+)?([^,.;!?]+?)\s+tiene\s+(?:disponibilidad|disponibles)\b",
        r"\bpara\s+(?:la\s+sala\s+)?(.+?)\s+(?:manana|hoy|pasado\s+manana)\b",
        r"\bpara\s+(.+?)\s*,\s*(?:el\s+)?(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b",
        r"\bpara\s+(.+?)\s*,\s*(?:el\s+)?\**\s*\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\b",
        r"\bpara\s+(.+?)\s+(?:el\s+)?\**\s*\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\b",
        r"\ben\s+(?:la\s+sala\s+)?(.+?)\s+(?:el\s+)?(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b",
    )
    for pattern in patterns:
        normalized = unicodedata.normalize("NFKD", content.casefold())
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        matches = list(re.finditer(pattern, normalized))
        if not matches:
            continue
        candidate = matches[-1].group(1).strip(" ,.;:-*_")
        # The offer may contain a date or attendee phrase; reject those instead of
        # turning them into a room name when wording changes unexpectedly.
        if candidate and len(candidate) <= 80 and not re.search(
            r"\b(?:personas?|jugadores?|\d{1,2}\s+de\s+\w+|\d{4})\b", candidate
        ):
            start, end = matches[-1].span(1)
            original_candidate = content[start:end].strip(" ,.;:-*_")
            return original_candidate or candidate
    return None


class AssistantOrchestrator:
    """One route selection, one backend execution, and at most one answer call."""

    def __init__(self, model: OpenAIChatModel, tools: AssistantTools) -> None:
        self.model = model
        self.tools = tools

    async def _resolve_room_from_customer_context(
        self,
        selection: RouteSelection,
        user_message: str,
        history: list[ChatTurn] | None,
    ) -> RouteSelection:
        """Resolve a room named in customer messages against the current safe catalog."""
        thematic_weekend = (
            selection.route == "get_rooms"
            and bool(selection.query)
            and selection.query.startswith("theme:")
            and _is_thematic_weekend_reservation(user_message)
        )
        if not thematic_weekend and (
            selection.route != "get_availability" or selection.date is None
        ):
            return selection
        current_text = _normalized_text(user_message)
        theme = next((name for name in ("terror", "aventura", "suspenso") if name in current_text), None)
        if selection.room and not theme:
            return selection
        try:
            catalog = await self.tools.execute(
                RouteSelection(
                    route="get_rooms",
                    query=f"theme:{theme}" if theme else None,
                    categories=["faq"] if theme else [],
                ),
                user_message,
            )
        except (LogicApiError, ValueError):
            if theme:
                return selection.model_copy(update={
                    "query": f"__thematic_room_lookup_failed__:{theme}",
                    "room": None,
                })
            return selection
        catalog_aliases = {}
        for room in catalog.evidence.api_facts:
            name = room.get("name")
            if not name:
                continue
            aliases = [name]
            aliases.extend(part.strip() for part in name.split(":") if part.strip())
            catalog_aliases[name] = [
                re.sub(r"(.)\1+", r"\1", _normalized_text(alias))
                for alias in aliases
            ]
        normalized_customer = re.sub(r"(.)\1+", r"\1", current_text)
        room_context_texts = [normalized_customer]
        if not any(
            re.search(rf"\b{re.escape(alias)}\b", normalized_customer)
            for aliases in catalog_aliases.values()
            for alias in aliases
        ):
            for turn in reversed(history or []):
                if turn.role != "user":
                    continue
                prior_text = re.sub(r"(.)\1+", r"\1", _normalized_text(turn.content))
                if any(
                    re.search(rf"\b{re.escape(alias)}\b", prior_text)
                    for aliases in catalog_aliases.values()
                    for alias in aliases
                ):
                    room_context_texts.append(prior_text)
                    break
        matches = []
        for name, aliases in catalog_aliases.items():
            if any(
                re.search(rf"\b{re.escape(alias)}\b", text)
                for alias in aliases
                for text in room_context_texts
            ):
                matches.append(name)
        if theme and not matches:
            active_rooms = []
            ignored_name_parts = {"sala", "escape", "room", "de", "del", "la", "el", "los", "las"}
            for room in catalog.evidence.api_facts:
                name = room.get("name")
                if not name:
                    continue
                prefix = name.split(":", 1)[0].strip()
                aliases = [prefix]
                aliases.extend(
                    token for token in re.findall(r"[a-z0-9]+", _normalized_text(prefix))
                    if token not in ignored_name_parts
                )
                active_rooms.extend((room, alias) for alias in dict.fromkeys(aliases))
            for room, alias in active_rooms:
                room_pattern = re.compile(rf"\b{re.escape(_normalized_text(alias))}\b")
                for fact in catalog.evidence.rag_facts:
                    text = _normalized_text(fact.get("text", ""))
                    mentions = list(room_pattern.finditer(text))
                    if not mentions:
                        continue
                    labeled_sections = list(re.finditer(r"\b[a-z][a-z ]{0,30}:", text))
                    for mention in mentions:
                        next_room_start = next((
                            label.start()
                            for label in labeled_sections
                            if label.start() >= mention.end()
                            and _normalized_text(alias) not in label.group().rstrip(":")
                        ), len(text))
                        room_description = text[mention.end():next_room_start]
                        if re.search(rf"\b{theme}\b", room_description):
                            matches.append(room["name"])
                            break
                    if room["name"] in matches:
                        break
        unique_matches = list(dict.fromkeys(matches))
        if theme and unique_matches:
            if thematic_weekend:
                return selection.model_copy(update={
                    "query": "__thematic_weekend_choice__:" + "|".join(unique_matches),
                    "categories": [],
                    "missing_information": [],
                })
            return selection.model_copy(update={
                "route": "get_availability",
                "date": selection.date,
                "room": None,
                "query": "__thematic_room_availability__:" + "|".join(unique_matches),
                "categories": [],
                "missing_information": [],
            })
        if len(unique_matches) == 1:
            return selection.model_copy(update={"room": unique_matches[0]})
        if selection.room:
            return selection.model_copy(update={"room": None})
        if theme:
            return selection.model_copy(update={
                "query": f"__thematic_room_unresolved__:{theme}",
                "room": None,
            })
        return selection

    async def reply(self, user_message: str, history: list[ChatTurn] | None = None) -> str:
        if _is_conversation_closing(user_message):
            return "\u00a1Con gusto! Gracias por escribirnos. Aqu\u00ed estar\u00e9 cuando quieras volver."
        if _is_greeting_only(user_message):
            if history:
                return "\u00a1Hola de nuevo! \u00bfEn qu\u00e9 puedo ayudarte?"
            return "\u00a1Hola! Soy Nox, asistente virtual de Logic Escape Room. \u00bfEn qu\u00e9 puedo ayudarte?"
        answer = await self._reply(user_message, history)
        if not history:
            answer = self._introduce(answer)
        return self._ensure_follow_up(answer)

    async def reply_messages(
        self, user_message: str, history: list[ChatTurn] | None = None
    ) -> list[str]:
        answer = await self.reply(user_message, history=history)
        if _is_room_catalog_and_prices_request(user_message) or _is_location_and_prices_request(user_message):
            parts = [part.strip() for part in answer.split("\n\n") if part.strip()]
            if len(parts) > 1:
                return parts
        return [answer]

    @staticmethod
    def _introduce(answer: str) -> str:
        intro = "\u00a1Hola! Soy Nox, asistente virtual de Logic Escape Room. Con gusto te ayudo \U0001f642."
        if answer.casefold().startswith(("\u00a1hola! soy nox", "hola, soy nox", "hola soy nox")):
            return answer
        return f"{intro} {answer}"

    @staticmethod
    def _ensure_follow_up(answer: str) -> str:
        """Trim the answer without forcing a generic continuation question."""
        return answer.rstrip()

    async def _reply(self, user_message: str, history: list[ChatTurn] | None = None) -> str:
        contact_reply = _contact_details_follow_up(
            user_message, history, getattr(self.tools, "settings", None)
        )
        if contact_reply is not None:
            return contact_reply
        try:
            today = datetime.now(BOGOTA).date()
            if _is_thematic_weekend_reservation(user_message):
                theme = next(
                    name for name in ("terror", "aventura", "suspenso", "miedo", "intriga")
                    if name in _normalized_text(user_message)
                )
                selection = RouteSelection(
                    route="get_rooms",
                    query=f"theme:{theme}",
                    categories=["faq"],
                )
            else:
                selection = await self.model.select_route(
                    user_message,
                    current_date=today.isoformat(),
                    history=history,
                )
                selection = _fill_relative_date(selection, user_message, today, history=history)
                if re.search(
                    r"\b\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\b",
                    _normalized_text(user_message),
                ):
                    explicit_date = _history_offer_date(user_message, today)
                    if explicit_date is not None:
                        selection = selection.model_copy(update={"date": explicit_date})
                selection = _route_thematic_dated_reservation(selection, user_message, today)
            price_attendees = _price_follow_up_attendees(user_message, history)
            price_follow_up = _price_follow_up_day_type(user_message, history)
            if price_attendees is not None:
                selection = RouteSelection(
                    route="get_rates",
                    attendees=price_attendees,
                    query="__price_attendees_followup__",
                )
            elif price_follow_up is not None:
                day_type, attendees = price_follow_up
                has_calendar_date = bool(re.search(
                    r"\b\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\b",
                    _normalized_text(user_message),
                ))
                requested_date = _history_offer_date(user_message, today) if has_calendar_date else None
                if requested_date is not None:
                    selection = RouteSelection(
                        route="get_quote",
                        date=requested_date,
                        attendees=attendees,
                        query="__price_date_followup__",
                    )
                else:
                    selection = RouteSelection(
                        route="get_rates",
                        attendees=attendees,
                        day_type=day_type,
                        query="__price_day_followup__",
                    )
            selection = _route_ambiguous_information_request(selection, user_message, history)
            selection = _route_dated_reservation_to_availability(selection, user_message)
            selection = _route_large_group_split_pricing_to_knowledge(selection, user_message)
            selection = _route_room_capacity_question_to_api(selection, user_message)
            selection = _route_location_and_prices(selection, user_message)
            selection = _route_price_question_without_exact_date_to_rates(selection, user_message)
            selection = _route_location_link_to_knowledge(selection, user_message)
            selection = _route_thematic_room_recommendation(selection, user_message)
            selection = _route_child_admission_question(selection, user_message)
            selection = _route_activity_explanation_to_knowledge(selection, user_message, history)
            selection = _route_room_catalog_and_prices(selection, user_message)
            selection = _route_room_catalog_question(selection, user_message)
            selection = _recover_time_choice(selection, user_message, history, today)
            selection = _route_specific_time_question(selection, user_message, today)
            selection = _route_room_age_question(selection, user_message)
        except (OpenAIError, ModelProtocolError, ValidationError):
            return "No pude interpretar la consulta en este momento. ¿Puedes reformularla o pedir que el equipo de Logic la revise?"

        if _past_availability_date(selection, today):
            return "Esa fecha ya pas\u00f3. \u00bfQu\u00e9 fecha futura quieres consultar?"

        missing = selection.missing_required_fields()
        if selection.route == "clarify":
            return clarification_answer(selection.missing_information)
        if missing:
            return clarification_answer(missing)

        try:
            selection = await self._resolve_room_from_customer_context(
                selection, user_message, history
            )
            if selection.query and selection.query.startswith("__thematic_weekend_choice__:"):
                room_names = [
                    name.strip()
                    for name in selection.query.partition(":")[2].split("|")
                    if name.strip()
                ]
                if not room_names:
                    return "No pude identificar una sala para esa tem\u00e1tica. \u00bfQuieres que el equipo de Logic lo revise?"
                if len(room_names) == 1:
                    room_summary = f"La sala que corresponde a esa tem\u00e1tica es {room_names[0]}."
                else:
                    room_summary = "Las salas que corresponden a esa tem\u00e1tica son: " + ", ".join(room_names) + "."
                return f"Claro que s\u00ed \U0001f642. {room_summary} Para el pr\u00f3ximo fin de semana, \u00bfprefieres el s\u00e1bado o el domingo?"
            if selection.query and selection.query.startswith("__thematic_room_unresolved__:"):
                return (
                    "No pude relacionar esa temática con una sala activa del catálogo en este momento. "
                    "Una persona del equipo de Logic puede confirmarte las opciones. ¿Quieres que le pase tu consulta?"
                )
            if selection.query and selection.query.startswith("__thematic_room_lookup_failed__:"):
                return (
                    "No pude consultar el catálogo de salas en este momento. "
                    "Una persona del equipo de Logic puede confirmar las opciones y horarios. "
                    "¿Quieres que le pase tu consulta?"
                )
            outcome = await self.tools.execute(selection, user_message)
        except LogicApiError as exc:
            return logic_error_answer(exc)
        except ValueError:
            return "Me falta un dato para hacer esa consulta. ¿Me das un poco más de detalle?"

        if outcome.fallback_answer:
            return outcome.fallback_answer
        if (
            not outcome.evidence.api_facts
            and not outcome.evidence.rag_facts
            and not outcome.evidence.operational_facts
        ):
            return "No tengo evidencia suficiente para responder con seguridad. Ese caso requiere confirmación del equipo de Logic."
        if outcome.needs_human and not any("revisión humana" in warning.casefold() for warning in outcome.evidence.warnings):
            outcome.evidence.warnings.append(
                "El caso requiere revisión humana; no afirmar que una excepción quedó aprobada."
            )

        if selection.query == "__child_admission_policy__":
            return _format_child_admission_answer(
                outcome.evidence.as_prompt_data(), user_message, history
            )
        if selection.query == "__room_catalog_and_reference_prices__":
            return _format_room_catalog_and_prices(outcome.evidence.as_prompt_data())
        if selection.query == "__room_catalog__":
            return _format_room_catalog(outcome.evidence.as_prompt_data())
        if selection.query == "__location_and_prices__":
            return _format_location_and_prices(outcome.evidence.as_prompt_data())
        if selection.query == "__price_day_followup__":
            return _format_day_type_price(
                outcome.evidence.as_prompt_data(), selection.attendees, selection.day_type
            )
        if selection.query == "__price_attendees_followup__":
            return _format_attendee_price_ranges(
                outcome.evidence.as_prompt_data(), selection.attendees
            )
        if selection.query == "__price_date_followup__":
            quote = outcome.evidence.as_prompt_data().get("api_facts", [{}])[0]
            total = quote.get("total")
            per_person = quote.get("price_per_person")
            if not isinstance(total, int) or not isinstance(per_person, int):
                return "No pude verificar el precio total para esa fecha. ?Quieres que el equipo de Logic lo confirme?"
            return (
                f"Para {selection.attendees} personas el {selection.date.strftime('%d/%m/%Y')}, "
                f"el total es ${total:,} COP (${per_person:,} COP por persona)."
            ).replace(",", ".")
        if selection.query and selection.query.startswith("__thematic_room_availability__:"):
            return _format_thematic_room_availability(
                outcome.evidence.as_prompt_data(), selection.query
            )

        try:
            answer = await self.model.generate_answer(
                user_message,
                outcome.evidence.as_prompt_data(),
                history=history,
            )
        except (OpenAIError, ModelProtocolError):
            return "Consulté la información disponible, pero no pude preparar una respuesta ahora. El equipo de Logic debe revisarlo."
        if len(answer) > 3000:
            return "No pude preparar una respuesta breve y segura. El equipo de Logic debe revisar la consulta."
        return answer
