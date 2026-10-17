import json

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.assistant.schemas import CATEGORIES, RouteSelection
from app.assistant.response_builder import evidence_messages
from app.core.config import Settings, get_settings
from app.core.prompts import ROUTE_SELECTION_PROMPT

ROUTE_NAMES = (
    "get_rooms",
    "get_rates",
    "get_opening_hours",
    "get_quote",
    "get_availability",
    "search_business_knowledge",
    "check_room_policy",
    "clarify",
)
MISSING_FIELDS = ("date", "attendees", "room", "question")
ROUTE_SELECTION_TOOL = {
    "type": "function",
    "function": {
        "name": "select_route",
        "description": "Select exactly one approved read-only assistant route and validated arguments.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "route": {"type": "string", "enum": list(ROUTE_NAMES)},
                "date": {"type": ["string", "null"]},
                "attendees": {"type": ["integer", "null"]},
                "room": {"type": ["string", "null"]},
                "query": {"type": ["string", "null"]},
                "day_of_week": {"type": ["integer", "null"]},
                "day_type": {"type": ["string", "null"], "enum": ["weekday", "weekend", None]},
                "categories": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(CATEGORIES)},
                },
                "missing_information": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(MISSING_FIELDS)},
                },
            },
            "required": [
                "route",
                "date",
                "attendees",
                "room",
                "query",
                "day_of_week",
                "day_type",
                "categories",
                "missing_information",
            ],
            "additionalProperties": False,
        },
    },
}


class ModelConfigurationError(RuntimeError):
    pass


class ModelProtocolError(RuntimeError):
    pass


class OpenAIChatModel:
    """Two bounded model calls: one route selection and one evidence-grounded answer."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.openai_api_key:
            raise ModelConfigurationError("OpenAI credentials are not configured.")
        if not self.settings.openai_model:
            raise ModelConfigurationError("OPENAI_MODEL is not configured.")
        self.client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            timeout=self.settings.openai_timeout_seconds,
            max_retries=2,
        )

    async def select_route(self, user_message: str, current_date: str) -> RouteSelection:
        response = await self.client.chat.completions.create(
            model=self.settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": f"{ROUTE_SELECTION_PROMPT}\nFecha actual en America/Bogota: {current_date}.",
                },
                {"role": "user", "content": user_message},
            ],
            tools=[ROUTE_SELECTION_TOOL],
            tool_choice={"type": "function", "function": {"name": "select_route"}},
            parallel_tool_calls=False,
        )
        choices = response.choices
        tool_calls = choices[0].message.tool_calls if choices else None
        if not tool_calls or len(tool_calls) != 1 or tool_calls[0].function.name != "select_route":
            raise ModelProtocolError("The model did not return exactly one approved route.")
        try:
            arguments = json.loads(tool_calls[0].function.arguments)
            return RouteSelection.model_validate(arguments)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise ModelProtocolError("The model returned invalid route arguments.") from exc

    async def generate_answer(self, user_message: str, evidence: dict) -> str:
        response = await self.client.chat.completions.create(
            model=self.settings.openai_model,
            messages=evidence_messages(user_message, evidence),
            max_completion_tokens=self.settings.openai_chat_max_output_tokens,
        )
        choices = response.choices
        content = choices[0].message.content if choices else None
        if not content or not content.strip():
            raise ModelProtocolError("The model returned an empty answer.")
        return content.strip()

    async def aclose(self) -> None:
        await self.client.close()
