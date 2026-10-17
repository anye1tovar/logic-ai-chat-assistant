# 00 — Project Context

## Business

Logic Escape Room is an escape-room business in Tunja, Colombia.

Customers commonly ask about:

- rooms;
- prices;
- minimum/maximum players;
- minimum age to enter without an adult;
- opening hours;
- availability;
- special cases and exceptions.

## Project objective

Build and evaluate a conversational assistant that answers customer questions using trustworthy business information.

## Information sources

### Structured source: Logic API

The current Logic system manages:

- prices;
- rooms;
- general room description;
- YouTube room video link;
- minimum/maximum players;
- minimum age to enter without a responsible adult;
- opening hours / advance-booking rules;
- availability by date.

This data remains owned by Logic's system.

### Contextual source: RAG

RAG exists for knowledge that is not naturally represented as structured fields.

Examples:

- operational exceptions;
- age/accompaniment exceptions;
- capacity exceptions;
- business policies;
- staff criteria;
- special FAQs.

## Architectural principles

1. One source of truth per fact.
2. Do not duplicate API-owned facts in RAG.
3. RAG complements the API.
4. Availability is live.
5. Concrete price quotations use the quote endpoint.
6. The LLM is the language layer, not the database.
7. If evidence is insufficient, ask or escalate.
8. Every answer must be auditable during evaluation.

## Example

User:

> Somos 7 niños de 12 años. ¿Podemos entrar a Portal?

Possible evidence:

- API: Portal standard maxPlayers = 6.
- RAG: documented child-group exception under exact conditions.

The answer must combine both.

If the RAG exception does not clearly match, do not infer that it applies.

## Non-goals

The PFM is not intended to:

- replace all human service;
- create a general autonomous agent;
- rebuild the booking system;
- automate payment;
- create bookings in the first MVP;
- deploy WhatsApp production integration in the first MVP.
