from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAIError
from pydantic import ValidationError

from app.assistant.model import ModelProtocolError, OpenAIChatModel
from app.assistant.response_builder import clarification_answer, logic_error_answer
from app.assistant.schemas import RouteSelection
from app.assistant.tools import AssistantTools
from app.logic_api.errors import LogicApiError

BOGOTA = ZoneInfo("America/Bogota")


class AssistantOrchestrator:
    """One route selection, one backend execution, and at most one answer call."""

    def __init__(self, model: OpenAIChatModel, tools: AssistantTools) -> None:
        self.model = model
        self.tools = tools

    async def reply(self, user_message: str) -> str:
        try:
            selection = await self.model.select_route(
                user_message,
                current_date=datetime.now(BOGOTA).date().isoformat(),
            )
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
        if not outcome.evidence.api_facts and not outcome.evidence.rag_facts:
            return "No tengo evidencia suficiente para responder con seguridad. Ese caso requiere confirmación del equipo de Logic."
        if outcome.needs_human and not any("revisión humana" in warning.casefold() for warning in outcome.evidence.warnings):
            outcome.evidence.warnings.append(
                "El caso requiere revisión humana; no afirmar que una excepción quedó aprobada."
            )

        try:
            answer = await self.model.generate_answer(
                user_message,
                outcome.evidence.as_prompt_data(),
            )
        except (OpenAIError, ModelProtocolError):
            return "Consulté la información disponible, pero no pude preparar una respuesta ahora. El equipo de Logic debe revisarlo."
        if len(answer) > 3000:
            return "No pude preparar una respuesta breve y segura. El equipo de Logic debe revisar la consulta."
        return answer
