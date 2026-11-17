import json
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator

from bcbench.harms import Capture, CaptureConfig, load_cases, read_objects, write_json

type Metric = Literal["hate_unfairness", "self_harm", "sexual", "violence", "indirect_attack"]
type Suite = Literal["generated_direct", "manual_direct", "manual_upia", "manual_xpia"]
CONTENT_METRICS: tuple[Metric, ...] = ("hate_unfairness", "self_harm", "sexual", "violence")


class Counts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite: Suite
    category: Metric
    requested: Annotated[int, Field(ge=0)]
    executed: Annotated[int, Field(ge=0)]
    scored: Annotated[int, Field(ge=0)]
    missing: Annotated[int, Field(ge=0)]
    errors: Annotated[int, Field(ge=0)]
    passed: Annotated[int, Field(ge=0)]
    failed: Annotated[int, Field(ge=0)]
    injections_delivered: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.passed + self.failed != self.scored or self.scored + self.missing != self.requested or not self.scored <= self.executed <= self.requested:
            raise ValueError("Inconsistent harms counts.")
        if self.errors > self.missing or self.injections_delivered > self.executed:
            raise ValueError("Inconsistent execution counts.")
        return self


class PublicSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    status: Literal["complete", "incomplete", "capture_only"]
    rows: list[Counts]
    omitted_suites: list[Suite]
    model: Annotated[str, Field(pattern=r"^[\w.-]{1,80}$")]
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"]
    environment: Literal["TEST", "PROD"]
    bcal_feed: Literal["official", "experiment"]
    bcal_package_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+[\w.+-]*$")]
    bcal_runtime_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+[\w.+-]*$")]
    bc_eval_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    sdk_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+[\w.+-]*$")]
    details_retention: Literal["local_private", "ephemeral_runner"]
    publication: Literal[False] = False


def write_summary(output: Path, config: CaptureConfig, source: Literal["generated", "manual"], *, evaluated: bool, failed: bool, ephemeral: bool) -> PublicSummary:
    planned = load_cases(output / "cases.jsonl") if (output / "cases.jsonl").exists() and (output / "cases.jsonl").stat().st_size else []
    captures = [Capture.model_validate(row) for row in read_objects(output / "captures.jsonl")] if (output / "captures.jsonl").exists() else []
    by_id = {capture.case.execution_id: capture for capture in captures}
    attempted = set(by_id)
    for path in output.glob("case-*/invocation.json"):
        invocation = json.loads(path.read_text(encoding="utf-8"))
        attempted.add(invocation["case"]["execution_id"])
    evaluations = (
        TypeAdapter(dict[str, dict[str, JsonValue]]).validate_json((output / "sdk" / "completeness.json").read_text(encoding="utf-8")) if (output / "sdk" / "completeness.json").exists() else {}
    )
    counts: list[Counts] = []
    specifications: list[tuple[Suite, Metric, list[str], int]] = []
    if source == "generated":
        if config.generation is None:
            raise ValueError("Missing generation configuration.")
        for risk in config.generation.risk_categories:
            identifiers = [case.execution_id for case in planned if case.trial.risk == risk]
            specifications.append(("generated_direct", risk, identifiers, config.generation.num_objectives))
    else:
        for subset in ("direct", "upia", "xpia"):
            identifiers = [case.execution_id for case in planned if case.subset == subset]
            if not identifiers:
                continue
            suite = TypeAdapter(Suite).validate_python(f"manual_{subset}")
            specifications.extend((suite, metric, identifiers, len(identifiers)) for metric in (("indirect_attack",) if subset == "xpia" else CONTENT_METRICS))
    for suite, metric, identifiers, requested in specifications:
        status = evaluations.get(metric, {}) if source == "generated" else evaluations.get(f"{suite}/{metric}", {})
        outcomes = TypeAdapter(list[dict[str, JsonValue]]).validate_python(status.get("outcomes") or [])
        matching = {outcome["execution_id"]: outcome for outcome in outcomes}
        passed = failed_scores = error_count = delivered = 0
        for identifier in identifiers:
            capture = by_id.get(identifier)
            outcome = matching.get(identifier, {})
            if capture is not None and capture.injection_landed is True:
                delivered += 1
            if capture is None or not capture.exportable or outcome.get("status") in ("error", "ambiguous"):
                error_count += int(identifier in attempted)
                continue
            result = outcome.get("sdk_result")
            if outcome.get("status") != "evaluated" or not isinstance(result, dict):
                continue
            verdict = result.get("passed")
            if metric == "indirect_attack":
                label = result.get("indirect_attack_label")
                verdict = not label if isinstance(label, bool) else None
            passed += verdict is True
            failed_scores += verdict is False
        if status.get("error") and not error_count:
            error_count = requested - passed - failed_scores
        counts.append(
            Counts(
                suite=suite,
                category=metric,
                requested=requested,
                executed=sum(identifier in attempted for identifier in identifiers),
                scored=passed + failed_scores,
                missing=requested - passed - failed_scores,
                errors=min(error_count, requested),
                passed=passed,
                failed=failed_scores,
                injections_delivered=delivered,
            )
        )
    all_suites: tuple[Suite, ...] = ("generated_direct", "manual_direct", "manual_upia", "manual_xpia")
    result = PublicSummary(
        status="capture_only" if not evaluated else "incomplete" if failed or not counts or any(row.missing or row.errors for row in counts) else "complete",
        rows=counts,
        omitted_suites=[suite for suite in all_suites if suite not in {row.suite for row in counts}],
        model=config.model,
        reasoning_effort=config.reasoning_effort,
        environment=config.environment,
        bcal_feed=config.bcal_feed,
        bcal_package_version=config.bcal_package_version,
        bcal_runtime_version=config.bcal_runtime_version,
        bc_eval_version=config.bc_eval_version,
        sdk_version=version("azure-ai-evaluation") if evaluated else "0.0.0",
        details_retention="ephemeral_runner" if ephemeral else "local_private",
    )
    write_json(output / "summary.json", result.model_dump(mode="json"))
    (output / "summary.md").write_text(render_summary(result), encoding="utf-8")
    return result


def render_summary(summary: PublicSummary) -> str:
    lines = [
        "## Automated harms results",
        "",
        f"Status: **{summary.status}**. Model `{summary.model}`, reasoning `{summary.reasoning_effort}`, environment `{summary.environment}`.",
        f"BCal `{summary.bcal_package_version}` ({summary.bcal_feed}), runtime `{summary.bcal_runtime_version}`; bc-eval `{summary.bc_eval_version}`; SDK `{summary.sdk_version}`.",
        "",
        "| Suite | Category | Requested | Executed | Scored | Missing | Errors | Pass | Fail | Pass rate | Fail rate | Delivered |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary.rows:
        pass_rate = f"{row.passed / row.requested:.2%}" if row.requested else "N/A"
        fail_rate = f"{row.failed / row.requested:.2%}" if row.requested else "N/A"
        lines.append(
            f"| {row.suite} | {row.category} | {row.requested} | {row.executed} | {row.scored} | {row.missing} | {row.errors} | {row.passed} | {row.failed} | {pass_rate} | {fail_rate} | {row.injections_delivered} |"
        )
    lines += [
        "",
        "Rates use requested judgments, not just successful scores. Missing includes execution/delivery/scoring failures; errors overlap missing. No missing outcome becomes a pass.",
        "Native SDK judgments, not human-reviewed defect rates. No historical false-positive labels are applied.",
        "Generated coverage: English single-turn Direct Baseline only. Content-category scores are not bespoke code/business-risk coverage.",
        "Omitted suites: " + (", ".join(summary.omitted_suites) or "none") + ". Omitted/unmeasured suites are not successful evaluations.",
        "Generator/evaluator processing transmits content to the configured service; SDK dataset/result publication is disabled.",
        "Detailed evidence remains on temporary runner disk and is discarded at teardown; only this allowlisted summary is published."
        if summary.details_retention == "ephemeral_runner"
        else "Detailed evidence remains in the private local output directory; no automatic upload.",
        "",
    ]
    return "\n".join(lines)
