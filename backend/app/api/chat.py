from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException

from app.assistant.model import ModelConfigurationError, OpenAIChatModel
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.schemas import ChatRequest, ChatResponse
from app.assistant.tools import AssistantTools
from app.core.config import get_settings

router = APIRouter(prefix="/api", tags=["chat"])


async def get_orchestrator() -> AsyncIterator[AssistantOrchestrator]:
    settings = get_settings()
    try:
        model = OpenAIChatModel(settings)
    except ModelConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail="El asistente no está configurado para responder en este momento.",
        ) from exc
    try:
        yield AssistantOrchestrator(model, AssistantTools(settings=settings))
    finally:
        await model.aclose()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    orchestrator: AssistantOrchestrator = Depends(get_orchestrator),
) -> ChatResponse:
    return ChatResponse(
        answer=await orchestrator.reply(request.message, history=request.history)
    )
