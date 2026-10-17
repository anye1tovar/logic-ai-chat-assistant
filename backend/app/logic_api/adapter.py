from collections.abc import Mapping
from typing import Any

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
        rooms.append(adapt_room(raw))
    return rooms
