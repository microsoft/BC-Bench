import json
from typing import override

from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.bcal_evidence import BCalExecutionFacts, compilation_facts
from bcbench.types import HarnessName


class NL2ALResult(JudgeBasedEvaluationResult):
    def _execution_facts(self) -> BCalExecutionFacts | None:
        return compilation_facts(self.transcript) if self.agent_name == HarnessName.BCAL else None

    @property
    @override
    def scorer_output(self) -> str:
        facts: BCalExecutionFacts | None = self._execution_facts()
        if facts is None:
            return self.output
        return json.dumps(
            {
                "authoritative_execution_facts": {**facts.model_dump(mode="json"), "agent_version": self.agent_version},
                "artifact": {"kind": "git_diff", "content": self.output},
            },
            separators=(",", ":"),
        )

    @property
    @override
    def export_metadata(self) -> dict[str, str | int | float | bool | None]:
        facts: BCalExecutionFacts | None = self._execution_facts()
        return {**super().export_metadata, **(facts.export_metadata if facts is not None else {})}
