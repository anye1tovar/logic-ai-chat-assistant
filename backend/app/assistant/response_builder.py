import json
from typing import Any

from app.assistant.schemas import ChatTurn, MissingField
from app.core.prompts import FINAL_ANSWER_PROMPT
from app.logic_api.errors import (
    LogicApiError,
    LogicApiUnavailable,
    LogicConflict,
    LogicDayClosed,
    LogicInvalidRequest,
    LogicOpeningHoursMissing,
)


def clarification_answer(fields: list[MissingField]) -> str:
    questions = {
        "date": "¿Para qué fecha lo estás consultando?",
        "attendees": "¿Cuántas personas participarían?",
        "room": "¿Qué sala tienes en mente?",
        "question": (
            "¡Claro! Puedo contarte sobre nuestras salas y temáticas, precios, reservas y horarios, "
            "eventos, cafetería o ubicación. ¿Cuál de esos temas te interesa más?"
        ),
    }
    selected = list(dict.fromkeys(fields))
    if not selected:
        return "¿Me das un poco más de detalle para orientarte?"
    if len(selected) == 1:
        return questions[selected[0]]
    prompts = [questions[field][1:-1].lower() for field in selected]
    return "Para continuar, dime " + " y ".join(prompts) + "."


def logic_error_answer(error: LogicApiError) -> str:
    if isinstance(error, LogicDayClosed):
        return "Ese día Logic está cerrado. Si quieres, dime otra fecha y la consulto."
    if isinstance(error, LogicOpeningHoursMissing):
        return "No hay un horario configurado para esa fecha; el equipo de Logic debe verificarlo."
    if isinstance(error, LogicConflict):
        return "El sistema reportó un conflicto al consultar esa opción. No puedo confirmar disponibilidad; debe revisarlo el equipo de Logic."
    if isinstance(error, LogicInvalidRequest):
        return "El sistema no pudo procesar esa consulta. Revisa los datos o pide al equipo de Logic que los verifique."
    if isinstance(error, LogicApiUnavailable):
        return "En este momento no puedo verificar esa información en el sistema de Logic. El equipo debe revisarla."
    return "No pude verificar esa información en el sistema de Logic. El equipo debe revisarla."


def evidence_messages(
    question: str,
    evidence: dict[str, Any],
    history: list[ChatTurn] | None = None,
) -> list[dict[str, str]]:
    payload = json.dumps(
        {"pregunta": question, "evidencia": evidence},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return [
        {"role": "system", "content": FINAL_ANSWER_PROMPT},
        *(
            {"role": turn.role, "content": turn.content}
            for turn in (history or [])[-8:]
        ),
        {"role": "user", "content": payload},
    ]
