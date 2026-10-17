# Phase 4 — LLM Orchestration and Conversational Behavior

## Goal

Combine Logic API and RAG into a bounded, auditable conversational flow.

## Architecture decision

Do not build a general autonomous agent.

The MVP has a small known set of tools.

The LLM can help choose a tool, but the backend owns:

- argument validation;
- execution;
- error handling;
- source boundaries;
- evidence construction.

## Tools

Conceptually:

```text
get_rooms
get_rates
get_opening_hours
get_quote
get_availability
search_business_knowledge
```

No booking creation tool in the first MVP.

## Four answer modes

### API-only

Examples:

- What rooms do you have?
- What time do you open Thursday?
- How much is it for 4 people on October 20?
- Is Portal available Saturday?

### RAG-only

Contextual policy or exception that is not stored as structured data.

### API + RAG

Standard structured fact plus a documented exception/policy.

### Clarification / escalation

- missing date;
- missing attendee count;
- ambiguous room;
- no matching policy;
- API unavailable;
- undocumented exception.

## Conversation policy

The assistant must:

- speak Spanish by default;
- be concise but helpful;
- ask only for information needed to continue;
- never invent missing values;
- never imply a booking is confirmed;
- never expose raw tool calls or JSON;
- distinguish availability from reservation;
- explain uncertainty clearly.

## Availability flow

Example:

> ¿Hay espacio mañana?

Behavior:

1. Resolve "tomorrow" to an exact date in `America/Bogota`.
2. Query live availability.
3. If room is missing, summarize or ask according to UX.
4. Do not use cached availability.

## Quote flow

Example:

> ¿Cuánto pagamos 5 personas el sábado?

Need:

- exact date;
- attendees.

Then call quote.

Do not calculate from cached rates.

## API + RAG flow

Example:

> Portal dice máximo 6, pero somos 7 niños de 12. ¿Podemos?

Steps:

1. identify room;
2. fetch/cache structured room data;
3. retrieve contextual exception;
4. verify exception conditions explicitly match;
5. build evidence;
6. generate answer;
7. if conditions do not match exactly, escalate.

## Evidence object

Before final generation, assemble an internal object such as:

```json
{
  "api_facts": [],
  "rag_facts": [],
  "missing_information": [],
  "warnings": []
}
```

The final generation uses this evidence, not raw API responses.

## Prompt requirements

The system prompt must include:

- Logic-specific facts come only from supplied evidence;
- do not rely on model memory for business facts;
- do not invent exceptions;
- no reservation confirmation without a booking result;
- ask for missing data;
- if evidence conflicts, do not choose silently;
- request human verification when needed.

## OpenAI integration

Use the OpenAI SDK directly.

Keep model configurable:

`OPENAI_MODEL`

Avoid coupling orchestration logic to one model name.

Use structured tool/function schemas.

## Conversation state

For MVP, keep only the minimum state needed:

- selected room;
- requested date;
- attendee count.

Do not store long-term customer profiles.

## Error behavior

### API 400

Explain mapped functional issues safely.

### DAY_CLOSED

Tell the user the selected date is closed/unavailable.

### OPENING_HOURS_MISSING

Do not invent slots; offer manual verification.

### API 5xx / timeout

Say the information could not be verified.

Do not turn a technical failure into "not available".

### No RAG evidence

Do not improvise a policy.

Escalate.

## Tests

Create service tests for:

- API-only room question;
- quote;
- availability;
- missing date;
- RAG-only policy;
- API + RAG exception;
- exception that must not be generalized;
- API timeout;
- no knowledge;
- conflicting evidence.

## Definition of done

A backend chat endpoint can answer MVP scenarios with explicit evidence routing and controlled error boundaries.
