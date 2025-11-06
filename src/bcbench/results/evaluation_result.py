import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from bcbench.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class EvaluationResult:
    instance_id: str
    version: str
    model: str
    agent_name: str

    resolved: bool
    build: bool

    error_message: str | None = None
    agent_execution_time: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "EvaluationResult":
        return cls(
            instance_id=str(payload["instance_id"]),
            version=str(payload["environment_setup_version"]),
            model=str(payload["model"]),
            agent_name=str(payload["agent_name"]),
            resolved=bool(payload["resolved"]),
            build=bool(payload["build"]),
            error_message=payload.get("error_message"),
            agent_execution_time=payload.get("agent_execution_time"),
            prompt_tokens=payload.get("prompt_tokens"),
            completion_tokens=payload.get("completion_tokens"),
        )

    def save(self, output_dir: Path, result_file: str = "instance_results.jsonl") -> None:
        output_file = output_dir / result_file
        with open(output_file, "a") as f:
            result_dict = {
                "instance_id": self.instance_id,
                "resolved": self.resolved,
                "model": self.model,
                "agent_name": self.agent_name,
                "build": self.build,
                "error_message": self.error_message,
                "environment_setup_version": self.version,
                "agent_execution_time": self.agent_execution_time,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
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

    def save(self, output_dir: Path, summary_file: str = "evaluation_summary.json") -> None:
        output_file = output_dir / summary_file
        with open(output_file, "w", encoding="utf-8") as f:
            summary_dict = {
                "total": self.total,
                "resolved": self.resolved,
                "failed": self.failed,
                "build": self.build,
                "date": self.date.isoformat(),
                "model": self.model,
                "agent_name": self.agent_name,
                "average_duration": self.average_duration,
                "average_prompt_tokens": self.average_prompt_tokens,
                "average_completion_tokens": self.average_completion_tokens,
                "github_run_id": self.github_run_id,
            }
            f.write(json.dumps(summary_dict, indent=4))

        logger.info(f"Saved evaluation summary to {output_file}")
