# Phase 5 — Minimal Chat Frontend

## Goal

Create a simple interface to test the assistant and support user evaluation.

This is not a production customer portal.

## Stack

- React
- Vite
- TypeScript

## Required UI

At minimum:

- conversation area;
- text input;
- send button;
- loading state;
- error state;
- reset/new conversation action.

Optional:

- example questions;
- a small notice that special cases may require staff verification.

## Do not expose internals

Do not show normal users:

- raw tool calls;
- API URLs;
- raw JSON;
- RAG chunks;
- prompt;
- internal IDs;
- API keys.

A debug mode may exist locally, off by default.

## Backend contract

Prefer one frontend-facing endpoint:

`POST /api/chat`

Conceptual request:

```json
{
  "conversationId": "optional",
  "message": "¿Hay Portal disponible el sábado?"
}
```

Conceptual response:

```json
{
  "conversationId": "...",
  "message": "...",
  "status": "answered"
}
```

Possible statuses:

- `answered`
- `needs_clarification`
- `human_review`
- `temporarily_unavailable`

Do not return internal evidence by default.

## UX behavior

- preserve multi-turn context within the session;
- allow Enter to send;
- disable duplicate sends while pending;
- preserve user message if server errors;
- clearly display retryable errors.

## Evaluation mode

Optionally support a local/test flag to capture:

- interaction id;
- latency;
- scenario/test case id.

Do not expose sensitive traces to normal users.

## Tests

At minimum:

- renders;
- sends a message;
- loading state;
- response display;
- backend error;
- duplicate send prevention;
- conversation state.

## Definition of done

A non-technical evaluator can use the browser interface to run the planned PFM scenarios.
