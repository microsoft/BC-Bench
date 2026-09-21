from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from bcbench.dataset.dataset_entry import BaseDatasetEntry
from bcbench.types import Checklist, ChecklistAssertion


class BCalSessionConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="forbid")

    publisher: str | None = None
    mode: str | None = None
    audience: str | None = None
    profile: str | None = None
    page: str | None = None
    locale: str | None = None
    publish: bool = False
    review_enabled: bool | None = Field(default=None, alias="review")
    review_deployment: str | None = Field(default=None, alias="reviewDeployment")
    resume: bool | None = None


class BCalUserStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(min_length=1)]
    type: Literal["user"]
    text: Annotated[str, Field(min_length=1)]


class BCalPlanActionStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(min_length=1)]
    type: Literal["plan_action"]
    action: Literal["start", "cancel"]


type BCalScenarioStep = Annotated[BCalUserStep | BCalPlanActionStep, Field(discriminator="type")]


class BCalInteractionMatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question_regex: str | None = Field(default=None, alias="questionRegex")
    choice_regex: str | None = Field(default=None, alias="choiceRegex")
    default: bool = False

    @model_validator(mode="after")
    def require_matcher(self) -> Self:
        if self.default and (self.question_regex or self.choice_regex):
            raise ValueError("The default interaction rule cannot also specify regex matchers")
        if not self.default and not self.question_regex and not self.choice_regex:
            raise ValueError("Interaction match requires questionRegex, choiceRegex, or default=true")
        return self


class BCalInteractionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Literal["accept", "decline", "cancel"]
    value: JsonValue | None = None
    selected_choice: str | None = Field(default=None, alias="selectedChoice")

    @model_validator(mode="after")
    def validate_action_payload(self) -> Self:
        has_value = self.value is not None or self.selected_choice is not None
        if self.action == "accept" and not has_value:
            raise ValueError("An accept response requires value or selectedChoice")
        if self.action != "accept" and has_value:
            raise ValueError("Decline and cancel responses cannot include value or selectedChoice")
        return self


class BCalInteractionRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(min_length=1)]
    match: BCalInteractionMatch
    response: BCalInteractionResponse


class BCalTraceAssertion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(min_length=1)]
    type: Literal[
        "required_tool",
        "forbidden_tool",
        "tool_order",
        "compile_after_final_mutation",
        "interaction_matched",
        "plan_lifecycle",
        "no_mutation_before_step",
        "mutation_after_step",
    ]
    tool: str | None = None
    before: str | None = None
    after: str | None = None
    interaction_id: str | None = None
    step_id: str | None = None
    expected: str | bool | None = None

    @model_validator(mode="after")
    def validate_type_fields(self) -> Self:
        required_fields = {
            "required_tool": ("tool",),
            "forbidden_tool": ("tool",),
            "tool_order": ("before", "after"),
            "interaction_matched": ("interaction_id",),
            "plan_lifecycle": ("step_id", "expected"),
            "no_mutation_before_step": ("step_id",),
            "mutation_after_step": ("step_id",),
        }
        missing = [name for name in required_fields.get(self.type, ()) if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.type} trace assertion requires: {', '.join(missing)}")
        return self


class BCalRuntimeVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    kind: Annotated[str, Field(min_length=1)]
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class BCalEvaluationContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    compile_required: bool = True
    artifact_assertions: Annotated[list[ChecklistAssertion], Field(min_length=1)]
    trace_assertions: list[BCalTraceAssertion] = Field(default_factory=list)
    forbidden_assertions: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    runtime_verification: BCalRuntimeVerification | None = None


class BCalScenarioEntry(BaseDatasetEntry):
    session: BCalSessionConfiguration
    steps: Annotated[list[BCalScenarioStep], Field(min_length=1)]
    interactions: list[BCalInteractionRule] = Field(default_factory=list)
    evaluation: BCalEvaluationContract

    @model_validator(mode="after")
    def validate_interaction_defaults(self) -> Self:
        if not self.interactions:
            return self
        default_indices = [index for index, rule in enumerate(self.interactions) if rule.match.default]
        if default_indices != [len(self.interactions) - 1]:
            raise ValueError("A non-empty interaction list must contain exactly one default rule, and it must be last")
        return self

    @property
    def customization_profile(self) -> str:
        return "bcal"

    def get_task(self) -> str:
        return "\n\n".join(step.text for step in self.steps if isinstance(step, BCalUserStep))

    def get_expected_output(self) -> Checklist:
        forbidden: list[ChecklistAssertion] = [{"text": f"Forbidden behavior is absent: {text}", "level": "critical"} for text in self.evaluation.forbidden_assertions]
        return {"assertions": [*self.evaluation.artifact_assertions, *forbidden]}
