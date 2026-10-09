"""Native BCAL scenario input and execution-result validation."""

import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, NonNegativeInt, ValidationError
from pydantic.alias_generators import to_camel

from bcbench.dataset import NL2ALEntry
from bcbench.exceptions import AgentError
from bcbench.types import AgentMetrics, ExperimentConfiguration


class BCalScenarioError(AgentError):
    def __init__(self, message: str, metrics: AgentMetrics) -> None:
        self.metrics = metrics
        self.config = ExperimentConfiguration()
        super().__init__(message)


class _ScenarioModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, alias_generator=to_camel)


class _ScenarioFailure(_ScenarioModel):
    code: str
    message: str
    step_id: str | None = None

    def describe(self) -> str:
        location = f" ({self.step_id})" if self.step_id else ""
        return f"{self.code}{location}: {self.message}"


class _ScenarioStepResult(_ScenarioModel):
    id: str
    type: str
    status: str
    compile_succeeded: bool | None
    failure: _ScenarioFailure | None


class _ScenarioInteractionResult(_ScenarioModel):
    sequence: NonNegativeInt
    rule_id: str | None
    matched: bool
    used_default: bool
    failure: _ScenarioFailure | None


class _ScenarioToolUsage(_ScenarioModel):
    name: str
    started: NonNegativeInt
    completed: NonNegativeInt
    succeeded: NonNegativeInt
    failed: NonNegativeInt


class _ScenarioTotals(_ScenarioModel):
    steps: NonNegativeInt
    successful_steps: NonNegativeInt
    failed_steps: NonNegativeInt
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    tool_calls_started: NonNegativeInt
    tool_calls_completed: NonNegativeInt
    duration_ms: NonNegativeInt


class _ScenarioExportResult(_ScenarioModel):
    attempted: bool
    success: bool
    message: str | None = None


class _ScenarioRunResult(_ScenarioModel):
    schema_version: Literal["1.0"]
    completed: bool
    steps: list[_ScenarioStepResult]
    interactions: list[_ScenarioInteractionResult]
    tool_usage: list[_ScenarioToolUsage]
    totals: _ScenarioTotals
    export: _ScenarioExportResult
    session_archive: _ScenarioExportResult
    failure: _ScenarioFailure | None

    def metrics(self, execution_time: float) -> AgentMetrics:
        return AgentMetrics(
            execution_time=execution_time,
            turn_count=sum(step.status in ("succeeded", "failed") for step in self.steps),
            prompt_tokens=self.totals.input_tokens,
            completion_tokens=self.totals.output_tokens,
            total_tokens=self.totals.input_tokens + self.totals.output_tokens,
            tool_usage={tool.name: tool.started for tool in self.tool_usage},
        )

    def errors(self, expected_steps: int) -> list[str]:
        errors: list[str] = []
        if self.failure:
            errors.append(self.failure.describe())
        if not self.completed:
            errors.append("Scenario did not complete")

        expected_ids = [f"turn-{index}" for index in range(1, expected_steps + 1)]
        actual_ids = [step.id for step in self.steps]
        if actual_ids != expected_ids:
            errors.append(f"Scenario steps do not match the scripted turn order: expected {expected_ids}, got {actual_ids}")
        for step in self.steps:
            if step.type != "user" or step.status != "succeeded":
                errors.append(f"Step {step.id}: type={step.type}, status={step.status}")
            if step.failure:
                errors.append(step.failure.describe())
            if step.status == "succeeded" and step.compile_succeeded is not True:
                errors.append(f"Step {step.id} did not report successful compilation")

        counts = (len(self.steps), sum(step.status == "succeeded" for step in self.steps), sum(step.status == "failed" for step in self.steps))
        if (self.totals.steps, self.totals.successful_steps, self.totals.failed_steps) != counts:
            errors.append("Scenario totals do not match the reported steps")

        if self.interactions:
            errors.append("Unexpected clarification interaction; scripted scenarios do not supply answers")
            errors.extend(interaction.failure.describe() for interaction in self.interactions if interaction.failure)
        if not self.export.attempted or not self.export.success:
            errors.append(f"Scenario export failed or was not attempted: {self.export.message or 'no details'}")
        if not self.session_archive.attempted or not self.session_archive.success:
            errors.append(f"Scenario session archive failed or was not attempted: {self.session_archive.message or 'no details'}")
        return errors


def prepare_scenario(entry: NL2ALEntry, repo_path: Path, result_dir: Path | None) -> tuple[Path, Path]:
    workspace = repo_path.resolve()
    artifact_root = (result_dir / "bcal-scenario" / entry.instance_id if result_dir is not None else workspace.with_name(f"{workspace.name}-bcal-artifacts")).resolve()
    if artifact_root.is_relative_to(workspace):
        raise AgentError(f"BCAL scenario artifacts must be outside the generated-source workspace: {artifact_root}")

    # A new directory per invocation prevents a previous result from making a failed rerun succeed.
    artifact_dir = artifact_root / uuid4().hex
    artifact_dir.mkdir(parents=True)
    scenario_path = artifact_dir / "scenario.json"
    result_path = artifact_dir / "result.json"
    scenario = {
        "schemaVersion": "1.0",
        "session": {
            "publisher": "bcal",
            "mode": "extension",
            "audience": entry.audience.lower(),
            "page": entry.page,
            "locale": entry.language,
            "publish": "never",
            "review": True,
        },
        "steps": [{"id": f"turn-{index}", "type": "user", "text": turn.prompt} for index, turn in enumerate(entry.turns, 1)],
        "interactions": [{"id": "unexpected-clarification", "match": {"default": True}, "response": {"action": "cancel"}}],
    }
    scenario_path.write_text(json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8")
    return scenario_path, result_path


def inspect_scenario_result(result_path: Path, expected_steps: int, execution_time: float) -> tuple[AgentMetrics, str | None]:
    try:
        result = _ScenarioRunResult.model_validate_json(result_path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        return AgentMetrics(execution_time=execution_time), f"BCAL scenario result is missing or unreadable at {result_path}: {exc}"
    except (ValidationError, UnicodeError) as exc:
        return AgentMetrics(execution_time=execution_time), f"BCAL scenario result is malformed at {result_path}: {exc}"

    return result.metrics(execution_time), "; ".join(result.errors(expected_steps)) or None
