from collections.abc import Mapping
import re
from typing import Any
import unicodedata

from pydantic import ValidationError

from app.logic_api.errors import LogicApiProtocolError
from app.logic_api.models import Room


def _difficulty(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized if normalized in {"easy", "medium", "hard"} else None
    try:
        level = int(value)
    except (TypeError, ValueError):
        return None
    if level <= 1:
        return "easy"
    if level == 2:
        return "medium"
    return "hard"


def room_name_matches(requested: str, canonical: str) -> bool:
    """Match exact room names and unambiguous prefixes before a subtitle separator."""
    def normalize(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.casefold())
        without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
        normalized = re.sub(r"\s+", " ", without_marks).strip()
        # Accept harmless spelling variants such as Canibal/Cannibal.
        return re.sub(r"(.)\1+", r"\1", normalized)

    query = normalize(requested)
    name = normalize(canonical)
    if not query or not name:
        return False
    if query == name:
        return True
    return bool(re.fullmatch(re.escape(query) + r"\s*[:\-–—]\s*.+", name))


def adapt_room(raw: Mapping[str, Any]) -> Room:
    """Map the current rooms table response to the allow-listed assistant DTO."""
    allowed = {
        "name": raw.get("name"),
        "description": raw.get("description"),
        "video_url": raw.get("video_url"),
        "min_players": raw.get("min_players"),
        "max_players": raw.get("max_players"),
        "minimum_age_without_adult": raw.get("min_age"),
        "duration_minutes": raw.get("duration_minutes"),
        "difficulty": _difficulty(raw.get("difficulty")),
    }
    try:
        return Room.model_validate(allowed)
    except ValidationError as exc:
        raise LogicApiProtocolError(
            "The Logic API returned a room that does not match the supported contract."
        ) from exc


def adapt_rooms(payload: Any) -> list[Room]:
    if not isinstance(payload, list):
        raise LogicApiProtocolError("The Logic API rooms response must be an array.")
    rooms: list[Room] = []
    for raw in payload:
        if not isinstance(raw, Mapping):
            raise LogicApiProtocolError("The Logic API returned an invalid room record.")
        if raw.get("active") is False:
            continue
        rooms.append(adapt_room(raw))
    return rooms
