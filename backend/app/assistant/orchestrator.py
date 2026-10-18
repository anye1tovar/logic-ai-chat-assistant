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
from app.logic_api.errors import LogicApiError

BOGOTA = ZoneInfo("America/Bogota")


def _fill_relative_date(selection: RouteSelection, message: str, today: date) -> RouteSelection:
    """Resolve common Spanish relative dates that the route model may leave blank."""
    normalized = unicodedata.normalize("NFKD", message.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    match = re.search(r"\bpasado\s+manana\b|\bmanana\b|\bhoy\b", normalized)
    if not match or selection.date is not None:
        return selection

    # "En la ma?ana" and "por la ma?ana" refer to a time of day, not tomorrow.
    prefix = normalized[max(0, match.start() - 12):match.start()]
    if match.group() == "manana" and re.search(r"(?:en|por)\s+la\s+$", prefix):
        return selection

    phrase = match.group()
    offset = 2 if phrase.startswith("pasado") else 1 if phrase == "manana" else 0
    resolved = today + timedelta(days=offset)
    missing = [field for field in selection.missing_information if field != "date"]
    return selection.model_copy(update={"date": resolved, "missing_information": missing})


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
        "Esta conversaci\u00f3n ser\u00e1 transferida a una persona del equipo de Logic para verificar "
        "el pago y confirmar la reserva por este chat. "
        "\u00bfQuieres que te aclare algo sobre el proceso?"
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
    )
    for pattern in patterns:
        normalized = unicodedata.normalize("NFKD", content.casefold())
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        matches = list(re.finditer(pattern, normalized))
        if not matches:
            continue
        candidate = matches[-1].group(1).strip(" ,.;:-")
        # The offer may contain a date or attendee phrase; reject those instead of
        # turning them into a room name when wording changes unexpectedly.
        if candidate and len(candidate) <= 80 and not re.search(
            r"\b(?:personas?|jugadores?|\d{1,2}\s+de\s+\w+|\d{4})\b", candidate
        ):
            start, end = matches[-1].span(1)
            original_candidate = content[start:end].strip(" ,.;:-")
            return original_candidate or candidate
    return None


class AssistantOrchestrator:
    """One route selection, one backend execution, and at most one answer call."""

    def __init__(self, model: OpenAIChatModel, tools: AssistantTools) -> None:
        self.model = model
        self.tools = tools

    async def reply(self, user_message: str, history: list[ChatTurn] | None = None) -> str:
        answer = await self._reply(user_message, history)
        if not history:
            answer = self._introduce(answer)
        return self._ensure_follow_up(answer)

    @staticmethod
    def _introduce(answer: str) -> str:
        intro = "\u00a1Hola! Soy Nox, asistente virtual de Logic Escape Room. Con gusto te ayudo \U0001f642."
        if answer.casefold().startswith(("\u00a1hola! soy nox", "hola, soy nox", "hola soy nox")):
            return answer
        return f"{intro} {answer}"

    @staticmethod
    def _ensure_follow_up(answer: str) -> str:
        cleaned = answer.rstrip()
        if cleaned.endswith("?"):
            return cleaned
        return f"{cleaned} \u00bfTe puedo ayudar en algo m\u00e1s?"

    async def _reply(self, user_message: str, history: list[ChatTurn] | None = None) -> str:
        contact_reply = _contact_details_follow_up(
            user_message, history, getattr(self.tools, "settings", None)
        )
        if contact_reply is not None:
            return contact_reply
        try:
            today = datetime.now(BOGOTA).date()
            selection = await self.model.select_route(
                user_message,
                current_date=today.isoformat(),
                history=history,
            )
            selection = _fill_relative_date(selection, user_message, today)
            selection = _recover_time_choice(selection, user_message, history, today)
        except (OpenAIError, ModelProtocolError, ValidationError):
            return "No pude interpretar la consulta en este momento. ¿Puedes reformularla o pedir que el equipo de Logic la revise?"

        missing = selection.missing_required_fields()
        if selection.route == "clarify":
            return clarification_answer(selection.missing_information)
        if missing:
            return clarification_answer(missing)

        try:
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
