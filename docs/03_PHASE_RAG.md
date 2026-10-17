# Phase 3 — RAG Knowledge Base

## Goal

Build a small RAG layer for contextual operational knowledge that is not represented reliably as structured Logic API data.

## Critical rule

Do not duplicate API-owned structured facts in RAG.

Do not create RAG documents whose primary purpose is to store:

- current prices;
- current room list;
- standard min/max players;
- standard minimum age without an adult;
- general opening hours;
- live availability.

Those facts belong to the Logic API.

## What belongs in RAG

Examples:

- operational exceptions;
- special admission criteria;
- capacity exceptions;
- age-related exceptions;
- policies requiring contextual explanation;
- staff decision guidelines that have been explicitly documented;
- FAQs whose answer is not present in the API;
- escalation rules.

## Knowledge file format

Use Markdown.

Prefer one policy/exception per file or clearly delimited unit.

Suggested front matter:

```yaml
---
id: portal-child-capacity-exception
category: capacity_exception
room: portal
status: active
updated_at: 2026-10-09
owner: Logic Escape Room
---
```

Suggested body:

```md
# Rule

State the normal business rule.

# Exception

State the exception precisely.

# Conditions

- condition 1
- condition 2

# Does not apply when

- case 1
- case 2

# Escalation

If the case does not match exactly, consult Logic staff.
```

## Avoid vague knowledge

Bad:

> Sometimes more children can fit.

Good:

> A documented exception applies only when X, Y and Z are true. Otherwise the standard API capacity remains authoritative.

## Repository location

Use:

```text
knowledge/
  policies/
  exceptions/
  faq/
```

## Ingestion

Ingestion should:

1. read Markdown files;
2. parse front matter;
3. create semantic chunks;
4. keep source metadata;
5. generate embeddings;
6. persist vectors in Chroma.

## Embeddings

Default proposal:

`text-embedding-3-small`

Keep configurable:

`OPENAI_EMBEDDING_MODEL`

## Vector database

Use local persistent Chroma for the MVP.

No hosted vector DB account is required.

## Chunking

Prefer semantic sections rather than blind fixed-size chunking.

A single business exception should remain understandable as one retrieval unit whenever possible.

Keep enough context so the model sees:

- rule;
- exception;
- conditions;
- exclusions;
- escalation.

## Retrieval result

Each retrieved chunk should return:

- chunk id;
- document id;
- category;
- text;
- source path;
- metadata;
- similarity/retrieval score if available.

## Retrieval API

Recommended internal function:

```python
search_business_knowledge(
    query: str,
    room: str | None = None,
    categories: list[str] | None = None,
    top_k: int = 4,
)
```

Do not expose Chroma directly to orchestration code.

## Confidence behavior

Do not convert a similarity score into a universal truth probability.

If retrieval is weak or evidence does not clearly apply:

- do not generalize;
- let orchestration clarify or escalate.

## Initial knowledge to collect

Before evaluation, document at least:

- special capacity exceptions;
- age/accompaniment policies;
- room-specific exceptions;
- reservation/customer-service clarifications not represented in API;
- situations where staff always prefer manual review.

## Tests

Create fixtures that test:

1. exception applies exactly;
2. similar query but exception does not apply;
3. unrelated query does not retrieve an exception as sufficient evidence;
4. room filter works;
5. source metadata is preserved.

## Definition of done

A plain-text query can retrieve the correct Logic operational policy or exception with traceable source metadata.
