"""
Convert the result into a format that bceval can consume and upload to Braintrust.
"""

import json
import logging
from pathlib import Path
from typing import Any

from bcbench.bcal_evidence import normalize_bcal_execution_facts
from bcbench.dataset import BaseDatasetEntry
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.summary import get_benchmark_version
from bcbench.types import AgentHarness, BCalExecutionFacts, EvaluationCategory, ExpectedOutput, ExperimentConfiguration

logger = logging.getLogger(__name__)


def _resolve_bcal_execution_facts(result: BaseEvaluationResult) -> BCalExecutionFacts | None:
    if result.category != EvaluationCategory.NL2AL or result.agent_name != AgentHarness.BCAL:
        return None
    if result.execution_facts is not None:
        if result.execution_identity != result.execution_facts.execution_identity:
            raise ValueError(f"Result {result.instance_id} execution facts do not match its execution identity")
        return result.execution_facts
    if result.execution_identity is None or result.evidence is None:
        return None
    return normalize_bcal_execution_facts(
        execution_identity=result.execution_identity,
        evidence=result.evidence,
    )


def _scorer_output(result: BaseEvaluationResult, execution_facts: BCalExecutionFacts | None) -> str:
    if execution_facts is None:
        return result.output

    authoritative_facts: dict[str, Any] = execution_facts.model_dump(mode="json")
    authoritative_facts["agent_version"] = result.agent_version
    return json.dumps(
        {
            "authoritative_execution_facts": authoritative_facts,
            "artifact": {
                "kind": "git_diff",
                "content": result.output,
            },
        },
        separators=(",", ":"),
    )


def _execution_facts_metadata(execution_facts: BCalExecutionFacts | None) -> dict[str, str | bool | None]:
    if execution_facts is None:
        return {}
    return {
        "execution_provider": execution_facts.provider,
        "execution_product_version": execution_facts.execution_identity.product_version,
        "execution_source_commit_sha": execution_facts.execution_identity.source_commit_sha,
        "execution_build_configuration": execution_facts.execution_identity.build_configuration,
        "scenario_completed": execution_facts.scenario_completed,
        "scenario_step_status": execution_facts.scenario_step_status,
        "compile_succeeded": execution_facts.compile_succeeded,
        "compile_evidence_source": execution_facts.compile_evidence_source,
        "evidence_status": execution_facts.evidence_status,
        "trace_truncated": execution_facts.trace_truncated,
    }


def _experiment_metadata(experiment: ExperimentConfiguration | None, git_ref: str | None, benchmark_version: str) -> dict[str, Any]:
    """Metadata identifying whether a run is a baseline or an experiment, and its configuration.

    bc-eval promotes the ``EvalRunType`` key to the Kusto ``EvalRunType``/``testJobType`` fields
    unless the summarize workflow overrides it with ``--eval-run-type experiment``.
    """
    is_experiment: bool = experiment is not None and not experiment.is_empty()
    return {
        "EvalRunType": "experiment" if is_experiment else "baseline",
        "experiment": experiment.model_dump(mode="json") if is_experiment and experiment else None,
        "git_branch": git_ref,
        "benchmark_version": benchmark_version,
    }


def write_bceval_results(
    results: list[BaseEvaluationResult],
    out_dir: Path,
    run_id: str,
    output_filename: str,
    category: EvaluationCategory,
    git_ref: str | None = None,
) -> None:
    """Write results into a JSONL file for bceval consumption."""
    dataset_entries: list[BaseDatasetEntry] = category.entry_class.load(category.dataset_path(results[0].tier))
    benchmark_version = get_benchmark_version()

    output_file = out_dir / output_filename
    with output_file.open("w") as f:
        for result in results:
            matching_entries = [e for e in dataset_entries if e.instance_id == result.instance_id]

            if not matching_entries:
                logger.error(f"No matching dataset entry found for instance_id: {result.instance_id}")
                continue

            matched_entry = matching_entries[0]
            execution_facts = _resolve_bcal_execution_facts(result)
            task_input: str = matched_entry.get_task()
            expected: ExpectedOutput = matched_entry.get_expected_output()

            metadata: dict[str, Any] = {
                "model": result.model,
                "tier": result.tier,
                **matched_entry.metadata.model_dump(mode="json"),
                "agent_version": result.agent_version,
                **result.export_metadata,
                "prompt_tokens": (result.metrics.prompt_tokens if result.metrics else None) or 0,
                "completion_tokens": (result.metrics.completion_tokens if result.metrics else None) or 0,
                "llm_duration": (result.metrics.llm_duration if result.metrics else None) or 0,
                "ai_credits": result.metrics.ai_credits if result.metrics else None,
                "latency": (result.metrics.execution_time if result.metrics else None) or 0,
                "turn_count": (result.metrics.turn_count if result.metrics else None) or 0,
                **result.category_metrics,
                "run_id": run_id,
                "project": result.project,
                "error_message": result.error_message,
                "bcal_failure_code": result.bcal_failure.code if result.bcal_failure else None,
                "bcal_failure_message": result.bcal_failure.message if result.bcal_failure else None,
                "bcal_failure_step_id": result.bcal_failure.step_id if result.bcal_failure else None,
                "bcal_failure_retryable": result.bcal_failure.retryable if result.bcal_failure else None,
                "bcal_terminal_reason": result.bcal_failure.message if result.bcal_failure and result.bcal_failure.code == "incomplete_execution" else None,
                "tool_usage": (result.metrics.tool_usage if result.metrics and result.metrics.tool_usage else None) or 0,
                **_execution_facts_metadata(execution_facts),
                **_experiment_metadata(result.experiment, git_ref, benchmark_version),
            }

            bceval_result = {
                "id": result.instance_id,
                "input": task_input,
                "expected": expected,
                "output": _scorer_output(result, execution_facts),
                "context": result.evidence if result.evidence is not None else "",
                "metadata": metadata,
                "tags": [],
            }
            f.write(json.dumps(bceval_result) + "\n")

    logger.info(f"Wrote bceval results to: {output_file}")
