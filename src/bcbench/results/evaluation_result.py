import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from bcbench.logger import get_logger
from bcbench.results.base import BaseEvaluationResult
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)


@dataclass(slots=True)
class EvaluationResultSummary:
    total: int
    resolved: int
    failed: int
    build: int

    date: date

    model: str
    agent_name: str
    category: EvaluationCategory

    average_duration: float
    average_prompt_tokens: float
    average_completion_tokens: float

    github_run_id: str | None = None
    mcp_servers: str | None = None
    custom_instructions: bool | None = None
    custom_agent: str | None = None

    @classmethod
    def from_results(cls, results: list[BaseEvaluationResult], run_id: str) -> "EvaluationResultSummary":
        total = len(results)
        resolved = sum(r.resolved for r in results)

        durations = [r.agent_execution_time for r in results if r.agent_execution_time is not None]
        prompt_tokens = [r.prompt_tokens for r in results if r.prompt_tokens is not None]
        completion_tokens = [r.completion_tokens for r in results if r.completion_tokens is not None]

        # Extract MCP servers and custom instructions from first result (all should be same in a run)
        first_result = results[0]
        mcp_servers_list = first_result.mcp_servers if first_result and first_result.mcp_servers else None
        mcp_servers_str = ", ".join(mcp_servers_list) if mcp_servers_list else None

        return cls(
            total=total,
            resolved=resolved,
            failed=total - resolved,
            build=sum(r.build for r in results),
            date=date.today(),
            category=first_result.category,
            model=first_result.model,
            agent_name=first_result.agent_name,
            average_duration=sum(durations) / len(durations) if durations else 0.0,
            average_prompt_tokens=sum(prompt_tokens) / len(prompt_tokens) if prompt_tokens else 0.0,
            average_completion_tokens=sum(completion_tokens) / len(completion_tokens) if completion_tokens else 0.0,
            github_run_id=run_id,
            mcp_servers=mcp_servers_str,
            custom_instructions=first_result.custom_instructions,
            custom_agent=first_result.custom_agent,
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
            category=EvaluationCategory(payload["category"]),
            agent_name=str(payload["agent_name"]),
            average_duration=float(payload["average_duration"]),
            average_prompt_tokens=float(payload["average_prompt_tokens"]),
            average_completion_tokens=float(payload["average_completion_tokens"]),
            github_run_id=payload.get("github_run_id"),
            mcp_servers=payload.get("mcp_servers"),
            custom_instructions=payload.get("custom_instructions"),
            custom_agent=payload.get("custom_agent"),
        )

    # TODO: handle test-generation category
    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "resolved": self.resolved,
            "failed": self.failed,
            "build": self.build,
            "date": self.date.isoformat(),
            "model": self.model,
            "category": self.category.value,
            "agent_name": self.agent_name,
            "average_duration": round(self.average_duration, 1),
            "average_prompt_tokens": round(self.average_prompt_tokens, 1),
            "average_completion_tokens": round(self.average_completion_tokens, 1),
            "github_run_id": self.github_run_id,
            "mcp_servers": self.mcp_servers,
            "custom_instructions": self.custom_instructions,
            "custom_agent": self.custom_agent,
        }

    def save(self, output_dir: Path, summary_file: str) -> None:
        output_file = output_dir / summary_file
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), indent=4))

        logger.info(f"Saved evaluation summary to {output_file}")
