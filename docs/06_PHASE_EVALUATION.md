# Phase 6 — Observability, Test Dataset and PFM Evaluation

## Goal

Generate repeatable evidence for the PFM.

## Evaluation dataset

Prepare approximately 40 cases.

Suggested distribution:

- 10 general/structured information questions;
- 10 room, price and operating-condition questions;
- 10 availability/quote questions;
- 10 ambiguous, unsupported or exception cases.

Include paraphrases and edge cases.

## Test case schema

Use CSV or JSON with fields such as:

```text
id
category
question
expected_route
expected_source
expected_behavior
reference_answer_or_criteria
should_answer
notes
```

## System trace

For each run capture:

- test case id;
- user question;
- selected route;
- tool calls;
- API status/result category;
- RAG document ids;
- final answer;
- end-to-end latency;
- model latency;
- tool latency;
- tokens when available;
- error status.

## Metrics

### Correct resolution

Manual binary or rubric-based evaluation.

### Faithfulness

Suggested manual rubric:

- 2 = fully supported;
- 1 = partially supported;
- 0 = contains unsupported material.

### Answer relevance

- 2 = direct and sufficient;
- 1 = partially relevant;
- 0 = does not answer.

### Hallucination rate

Project operational metric:

```text
responses containing >=1 unsupported factual claim
--------------------------------------------------- x 100
total evaluated responses
```

### Correct abstention

For unsupported or ambiguous cases, count whether the assistant:

- asked for clarification;
- declined to invent;
- escalated.

### Tool correctness

Evaluate:

- correct API tool;
- correct RAG use;
- correct API + RAG combination;
- required parameters obtained correctly.

### Latency

Report:

- mean;
- median;
- p95 if useful.

## User-perception questionnaire

Use 1–5 Likert items for:

- clarity;
- usefulness;
- relevance;
- trust;
- perceived speed;
- ease of interaction;
- satisfaction;
- willingness to use again.

Do not invent participant counts before recruitment.

## Evaluation runner

Create a repeatable command, e.g.:

```bash
python -m app.evaluation.run --dataset evaluation/cases.json
```

Expected outputs:

```text
evaluation/results/
  raw_runs.jsonl
  summary.json
```

## Methodology rule

Freeze before official evaluation:

- code commit;
- prompt version;
- model configuration;
- knowledge-base version.

If changes are made after reviewing errors, label the next run as a new iteration.

Do not mix runs from different versions.

## Definition of done

The 40-case evaluation can be rerun and produces structured evidence for the PFM results chapter.
