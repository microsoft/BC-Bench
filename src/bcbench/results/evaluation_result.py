import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from bcbench.evaluate import EvaluationContext
from bcbench.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class EvaluationResult:
    instance_id: str
    project: str
    model: str
    agent_name: str

    resolved: bool
    build: bool

    generated_patch: str = ""
    error_message: str | None = None
    agent_execution_time: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "EvaluationResult":
        return cls(
            instance_id=str(payload["instance_id"]),
            project=str(payload["project"]),
            model=str(payload["model"]),
            agent_name=str(payload["agent_name"]),
            resolved=bool(payload["resolved"]),
            build=bool(payload["build"]),
            generated_patch=payload.get("generated_patch", ""),
            error_message=payload.get("error_message"),
            agent_execution_time=payload.get("agent_execution_time"),
            prompt_tokens=payload.get("prompt_tokens"),
            completion_tokens=payload.get("completion_tokens"),
        )

    @classmethod
    def create_success(cls, context: "EvaluationContext", generated_patch: str) -> "EvaluationResult":
        return cls._create(context, resolved=True, build=True, generated_patch=generated_patch)

    @classmethod
    def create_build_failure(cls, context: "EvaluationContext", generated_patch: str, error_msg: str) -> "EvaluationResult":
        return cls._create(context, resolved=False, build=False, error_message=error_msg, generated_patch=generated_patch)

    @classmethod
    def create_test_failure(cls, context: "EvaluationContext", generated_patch: str, error_msg: str = "Tests failed") -> "EvaluationResult":
        return cls._create(context, resolved=False, build=True, error_message=error_msg, generated_patch=generated_patch)

    @classmethod
    def create_unexpected_error(cls, context: "EvaluationContext", generated_patch: str, error: Exception) -> "EvaluationResult":
        return cls._create(context, resolved=False, build=False, error_message=f"Unexpected error: {error}", generated_patch=generated_patch)

    @classmethod
    def _create(cls, context: "EvaluationContext", resolved: bool, build: bool, error_message: str | None = None, generated_patch: str = "") -> "EvaluationResult":
        metrics = context.agent_metrics or {}
        prompt_tokens = metrics.get("prompt_tokens")
        completion_tokens = metrics.get("completion_tokens")
        agent_execution_time = metrics.get("agent_execution_time")

        # Warn about missing critical metrics that affect result quality
        if context.agent_metrics is None:
            logger.warning(f"Creating result for {context.entry.instance_id} with no agent metrics - performance data will be unavailable")
        else:
            missing_metrics = []
            if agent_execution_time is None:
                missing_metrics.append("agent_execution_time")
            if prompt_tokens is None:
                missing_metrics.append("prompt_tokens")
            if completion_tokens is None:
                missing_metrics.append("completion_tokens")

            if missing_metrics:
                logger.warning(f"Result for {context.entry.instance_id} missing metrics: {', '.join(missing_metrics)}")

        project = context.entry.extract_project_name()
        return cls(
            instance_id=context.entry.instance_id,
            project=project,
            resolved=resolved,
            build=build,
            model=context.model,
            agent_name=context.agent_name,
            generated_patch=generated_patch,
            error_message=error_message,
            agent_execution_time=agent_execution_time,
            prompt_tokens=int(prompt_tokens) if prompt_tokens is not None else None,
            completion_tokens=int(completion_tokens) if completion_tokens is not None else None,
        )

    def save(self, output_dir: Path, result_file: str) -> None:
        output_file = output_dir / result_file
        with open(output_file, "a") as f:
            result_dict = {
                "instance_id": self.instance_id,
                "resolved": self.resolved,
                "model": self.model,
                "agent_name": self.agent_name,
                "build": self.build,
                "error_message": self.error_message,
                "project": self.project,
                "agent_execution_time": self.agent_execution_time,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "generated_patch": self.generated_patch,
            }
            f.write(json.dumps(result_dict) + "\n")

        logger.info(f"Saved evaluation result for {self.instance_id} to {output_file}")


@dataclass(slots=True)
class EvaluationResultSummary:
    total: int
    resolved: int
    failed: int
    build: int

    date: date

    model: str
    agent_name: str

    average_duration: float
    average_prompt_tokens: float
    average_completion_tokens: float

    github_run_id: str | None = None

    @classmethod
    def from_results(cls, results: list[EvaluationResult], run_id: str) -> "EvaluationResultSummary":
        total = len(results)
        resolved = sum(r.resolved for r in results)

        durations = [r.agent_execution_time for r in results if r.agent_execution_time is not None]
        prompt_tokens = [r.prompt_tokens for r in results if r.prompt_tokens is not None]
        completion_tokens = [r.completion_tokens for r in results if r.completion_tokens is not None]

        return cls(
            total=total,
            resolved=resolved,
            failed=total - resolved,
            build=sum(r.build for r in results),
            date=date.today(),
            model=results[0].model,
            agent_name=results[0].agent_name,
            average_duration=sum(durations) / len(durations) if durations else 0.0,
            average_prompt_tokens=sum(prompt_tokens) / len(prompt_tokens) if prompt_tokens else 0.0,
            average_completion_tokens=sum(completion_tokens) / len(completion_tokens) if completion_tokens else 0.0,
            github_run_id=run_id,
        )

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "EvaluationResultSummary":
        return cls(
            total=int(payload["total"]),
            resolved=int(payload["resolved"]),
            failed=int(payload["failed"]),
            build=int(payload["build"]),
            date=date.fromisoformat(payload["date"]),
            model=str(payload["model"]),
            agent_name=str(payload["agent_name"]),
            average_duration=float(payload["average_duration"]),
            average_prompt_tokens=float(payload["average_prompt_tokens"]),
            average_completion_tokens=float(payload["average_completion_tokens"]),
            github_run_id=payload.get("github_run_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "resolved": self.resolved,
            "failed": self.failed,
            "build": self.build,
            "date": self.date.isoformat(),
            "model": self.model,
            "agent_name": self.agent_name,
            "average_duration": round(self.average_duration, 1),
            "average_prompt_tokens": round(self.average_prompt_tokens, 1),
            "average_completion_tokens": round(self.average_completion_tokens, 1),
            "github_run_id": self.github_run_id,
        }

    def save(self, output_dir: Path, summary_file: str) -> None:
        output_file = output_dir / summary_file
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), indent=4))

        logger.info(f"Saved evaluation summary to {output_file}")
