from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


DayType = Literal["weekday", "weekend"]


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="ignore",
        frozen=True,
    )


class Room(ApiModel):
    """Explicit assistant-safe room data; database fields are discarded."""

    name: str = Field(min_length=1)
    description: str | None = None
    video_url: str | None = None
    min_players: int | None = Field(default=None, ge=1)
    max_players: int | None = Field(default=None, ge=1)
    minimum_age_without_adult: int | None = Field(default=None, ge=0)
    duration_minutes: int | None = Field(default=None, ge=1)
    difficulty: str | None = None


class Rate(ApiModel):
    day_type: DayType
    day_label: str | None = None
    day_range: str | None = None
    players: int = Field(ge=1)
    price_per_person: int = Field(ge=0)
    currency: str = "COP"


class Quote(ApiModel):
    date: date
    day_type: DayType
    is_holiday: bool
    players: int = Field(ge=1)
    currency: str
    price_per_person: int = Field(ge=0)
    total: int = Field(ge=0)


class OpeningHours(ApiModel):
    day_of_week: int = Field(ge=0, le=6)
    open_time: str | None = None
    close_time: str | None = None
    is_open: bool
    requires_advance_booking: bool


class AvailabilitySlot(ApiModel):
    start: datetime
    available: bool
    reason: str | None = None


class AvailabilityRoom(ApiModel):
    room_id: str | int
    name: str
    min_players: int | None = None
    max_players: int | None = None
    duration_minutes: int | None = None
    difficulty: str | None = None
    slots: tuple[AvailabilitySlot, ...]


class Availability(ApiModel):
    date: date
    day_type: DayType
    is_holiday: bool
    rates: tuple[Rate, ...] = ()
    timezone: str
    server_now: datetime
    min_advance_minutes: int = Field(ge=0)
    rooms: tuple[AvailabilityRoom, ...]
