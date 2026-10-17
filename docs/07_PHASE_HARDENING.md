# Phase 7 — Hardening, Security Review and Delivery

## Goal

Prepare the prototype for a defensible PFM delivery and document the gap between prototype and production.

## Security review

Verify:

- no secret committed to git;
- no OpenAI key in frontend;
- no Logic credential in frontend;
- no raw environment dump in logs;
- no unrestricted raw Logic room records sent to LLM;
- no forbidden booking-list routes used;
- outbound timeout configured;
- logs minimize personal data.

## Current Logic API security limitation

Assistant-facing routes currently have no server-to-server authentication.

CORS does not solve this.

Document as a production gap:

- assistant-specific credential;
- least privilege;
- revocation/rotation;
- rate limiting;
- monitoring;
- versioned assistant API contract.

## API contract hardening

Prefer a future family such as:

```text
/api/v1/assistant/...
```

with explicit public DTOs.

This avoids coupling the assistant to database schemas returned by current room/rate endpoints.

## Deployment

Production deployment is optional unless required by the tutor.

If deployed, conceptually keep:

- frontend;
- assistant backend;
- Logic API as external dependency.

Do not add cloud infrastructure only for complexity.

## Performance

Measure actual latency before optimizing.

Do not introduce Redis, queues, autoscaling or CDN logic without evidence.

## Final documentation

Before delivery update:

- README;
- architecture diagram;
- environment variables;
- API dependency list;
- knowledge inventory;
- evaluation instructions;
- limitations;
- production recommendations.

## Final PFM evidence

Preserve:

- repository commit hash used for evaluation;
- final prompt version;
- final knowledge-base version;
- model configuration;
- evaluation result files.

## Future booking phase

Only after the informational assistant is validated should the team consider:

`POST /api/bookings`

Before enabling it, address:

- API authentication;
- consent for personal data;
- data retention;
- `409` handling;
- idempotency;
- timeout uncertainty;
- booking-confirmation UX;
- reservation-code handling.

## Definition of done

The prototype is reproducible, testable, documented and its production limitations are explicit.
