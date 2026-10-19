from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.logic_api.models import DayType

AssistantRoute = Literal[
    "get_rooms",
    "get_rates",
    "get_opening_hours",
    "get_quote",
    "get_availability",
    "search_business_knowledge",
    "check_room_policy",
    "clarify",
]
MissingField = Literal["date", "attendees", "room", "question"]
CATEGORIES = (
    "age_policy",
    "customer_service_policy",
    "faq",
    "operational_rule",
    "payments",
    "pricing",
    "reservations",
)


class RouteSelection(BaseModel):
    """Strict, bounded route arguments selected by the model and checked by us."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    route: AssistantRoute
    date: Date | None = None
    attendees: int | None = Field(default=None, ge=1, le=100)
    room: str | None = Field(default=None, min_length=1, max_length=80)
    query: str | None = Field(default=None, max_length=2000)
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    day_type: DayType | None = None
    categories: list[str] = Field(default_factory=list, max_length=3)
    missing_information: list[MissingField] = Field(default_factory=list, max_length=3)

    @field_validator("categories")
    @classmethod
    def categories_are_allowlisted(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.casefold().strip() for item in value))
        unknown = set(normalized) - set(CATEGORIES)
        if unknown:
            raise ValueError("categories contains an unsupported value")
        return normalized

    @field_validator("room")
    @classmethod
    def room_is_normalized(cls, value: str | None) -> str | None:
        return value.strip() if value else value

    def missing_required_fields(self) -> list[MissingField]:
        missing: list[MissingField] = []
        if self.route == "get_quote":
            if self.date is None:
                missing.append("date")
            if self.attendees is None:
                missing.append("attendees")
        elif self.route == "get_availability" and self.date is None:
            missing.append("date")
        elif self.route == "check_room_policy" and not self.room:
            missing.append("room")
        return missing


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)


class ChatResponse(BaseModel):
    answer: str
    messages: list[str] | None = None
