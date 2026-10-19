from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.assistant.schemas import ChatTurn


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=40)
    category: Literal[
        "general_structured",
        "room_price_conditions",
        "availability_quote",
        "ambiguous_unsupported_exception",
    ]
    question: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)
    expected_route: str = Field(min_length=1)
    expected_source: list[Literal["api", "rag"]] = Field(default_factory=list)
    expected_behavior: str = Field(min_length=1)
    reference_answer_or_criteria: list[str] = Field(min_length=1)
    should_answer: bool
    notes: str = ""


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str = Field(min_length=1)
    description: str
    cases: list[EvaluationCase] = Field(min_length=1)

    def validate_unique_ids(self) -> None:
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Evaluation case ids must be unique.")


class ManualReview(BaseModel):
    """Human scores are intentionally left empty by the automated runner."""

    faithfulness: Literal[0, 1, 2] | None = None
    relevance: Literal[0, 1, 2] | None = None
    unsupported_factual_claim: bool | None = None
    correct_abstention: bool | None = None
    notes: str | None = None
