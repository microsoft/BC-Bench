from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from bcbench.agent.bcal.scenario import SCENARIO_EXPORT_DIR, SCENARIO_RESULT, SCENARIO_SYMBOL_DIR, BCalScenarioRunResult, load_scenario_result, resolve_session_chat
from bcbench.dataset import BCalDeterministicArtifactAssertion, BCalScenarioEntry, BCalTraceAssertion
from bcbench.evaluate.base import AgentRunner, EvaluationPipeline
from bcbench.github_actions import github_log_group
from bcbench.logger import get_logger
from bcbench.operations import bootstrap_app_json, copy_symbol_apps
from bcbench.results import BCalScenarioEvaluationResult, IndependentBuildResult, TraceAssertionResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

_MUTATION_TOOLS = frozenset({"write_file", "edit_file", "create_file", "apply_patch", "replace_text", "patch_text"})
_TEXT_EXTENSIONS = frozenset({".al", ".json", ".md", ".txt", ".xml", ".yml", ".yaml", ".ps1", ".toml"})
_CANONICAL_TOOL_TRACE_ASSERTIONS = frozenset({"required_tool", "forbidden_tool", "tool_order"})


def _scenario_app_id(instance_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://github.com/microsoft/BC-Bench/bcal-scenario/{instance_id}"))


def _git_init_and_commit(repo_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial BCal scenario scaffold"],
        cwd=repo_path,
        capture_output=True,
        check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "bcbench", "GIT_AUTHOR_EMAIL": "bcbench@localhost", "GIT_COMMITTER_NAME": "bcbench", "GIT_COMMITTER_EMAIL": "bcbench@localhost"},
    )


def _normalize_tool(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def _normalize_state(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _result_tool_events(result: BCalScenarioRunResult) -> list[tuple[float, str, str]]:
    events: list[tuple[float, str, str]] = []
    for step_index, step in enumerate(result.steps):
        for tool_index, usage in enumerate(step.tool_usage):
            if usage.started:
                events.append((step_index * 1000 + tool_index, _normalize_tool(usage.name), step.id))
    events.extend((float(interaction.sequence), "ask_user", interaction.rule_id or "") for interaction in result.interactions if interaction.matched)
    return events


def _canonical_trace_events(result: BCalScenarioRunResult) -> list[tuple[float, str, str]]:
    if not result.evidence:
        return []
    trace = result.evidence.get("trace")
    if not isinstance(trace, dict):
        return []
    raw_events = cast(dict[str, object], trace).get("events")
    if not isinstance(raw_events, list):
        return []

    events: list[tuple[float, str, str]] = []

    def tool_name(record: dict[str, object]) -> str | None:
        direct = record.get("toolName") or record.get("tool_name")
        if isinstance(direct, str):
            return direct
        if "tool" in str(record.get("type", "")).lower():
            name = record.get("name") or record.get("tool")
            if isinstance(name, str):
                return name
        for child in record.values():
            if isinstance(child, dict):
                nested = tool_name(cast(dict[str, object], child))
                if nested:
                    return nested
        return None

    for index, value in enumerate(raw_events):
        if not isinstance(value, dict):
            continue
        record = cast(dict[str, object], value)
        name = tool_name(record)
        if not name:
            continue
        raw_sequence = record.get("sequence", record.get("index", index))
        position = float(raw_sequence) if isinstance(raw_sequence, int | float) else float(index)
        events.append((position, _normalize_tool(name), str(record.get("stepId", ""))))
    return events


def _canonical_trace_is_incomplete(result: BCalScenarioRunResult) -> bool:
    trace = result.canonical_trace
    if trace is None:
        return False
    omitted_event_count = trace.get("omittedEventCount")
    return trace.get("truncated") is True or (isinstance(omitted_event_count, int) and omitted_event_count > 0)


def _chat_tool_events(chat_path: Path | None) -> list[tuple[float, str, str]]:
    if chat_path is None:
        return []
    try:
        payload = json.loads(chat_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []

    events: list[tuple[float, str, str]] = []
    sequence = 0

    def visit(value: object) -> None:
        nonlocal sequence
        if isinstance(value, dict):
            record = cast(dict[str, object], value)
            tool_name = record.get("toolName") or record.get("tool_name")
            if tool_name is None and str(record.get("type", "")).lower() in {"tool", "tool_call", "tool_use"}:
                tool_name = record.get("name")
            if isinstance(tool_name, str):
                raw_sequence = record.get("sequence", record.get("index", sequence))
                position = float(raw_sequence) if isinstance(raw_sequence, int | float) else float(sequence)
                events.append((position, _normalize_tool(tool_name), str(record.get("stepId", ""))))
                sequence += 1
            for child in record.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return events


def evaluate_trace_assertion(
    assertion: BCalTraceAssertion,
    result: BCalScenarioRunResult,
    chat_path: Path | None,
    changed_paths: list[str],
) -> TraceAssertionResult:
    if assertion.type in _CANONICAL_TOOL_TRACE_ASSERTIONS and _canonical_trace_is_incomplete(result):
        return TraceAssertionResult(
            assertion_id=assertion.id,
            passed=False,
            message="Canonical trace is truncated or reports omitted events; tool-event compliance cannot be established",
        )

    events = _canonical_trace_events(result) or _chat_tool_events(chat_path) or _result_tool_events(result)
    tool_positions: dict[str, list[float]] = {}
    for position, tool, _step_id in events:
        tool_positions.setdefault(tool, []).append(position)

    passed = False
    message: str
    match assertion.type:
        case "required_tool":
            tool = _normalize_tool(assertion.tool or "")
            passed = bool(tool_positions.get(tool))
            message = f"Required tool {tool!r} {'was observed' if passed else 'was not observed'}"
        case "forbidden_tool":
            tool = _normalize_tool(assertion.tool or "")
            passed = not tool_positions.get(tool)
            message = f"Forbidden tool {tool!r} {'was not observed' if passed else 'was observed'}"
        case "tool_order":
            before = _normalize_tool(assertion.before or "")
            after = _normalize_tool(assertion.after or "")
            before_positions = tool_positions.get(before, [])
            after_positions = [position for tool in _MUTATION_TOOLS for position in tool_positions.get(tool, [])] if after in _MUTATION_TOOLS else tool_positions.get(after, [])
            after_description = "workspace mutation" if after in _MUTATION_TOOLS else repr(after)
            passed = bool(before_positions and after_positions and min(before_positions) < min(after_positions))
            if not before_positions:
                message = f"Expected {before!r} before {after_description}, but {before!r} was not observed"
            elif not after_positions:
                message = f"Observed {before!r}, but {after_description} was not observed"
            else:
                message = f"Expected {before!r} before {after_description}"
        case "compile_after_final_mutation":
            mutation_steps = [index for index, step in enumerate(result.steps) if any(_normalize_tool(usage.name) in _MUTATION_TOOLS and usage.started for usage in step.tool_usage)]
            compile_steps = [index for index, step in enumerate(result.steps) if step.compile_succeeded is True]
            passed = bool(compile_steps) and (not mutation_steps or max(compile_steps) >= max(mutation_steps))
            message = "Expected a successful compile after the final workspace mutation"
        case "interaction_matched":
            records = [record for record in result.interactions if record.rule_id == assertion.interaction_id]
            passed = bool(records and records[-1].matched and records[-1].failure is None)
            if passed and assertion.expected is not None:
                response = records[-1].response or {}
                passed = assertion.expected in (response.get("selectedChoice"), response.get("value"))
            if not records and result.interactions:
                matched_rules = [record.rule_id for record in result.interactions if record.matched]
                message = f"ask_user was observed, but scripted interaction {assertion.interaction_id!r} did not match; matched rules: {matched_rules!r}"
            elif records and records[-1].failure:
                message = f"Interaction {assertion.interaction_id!r} matched but acceptance failed: {records[-1].failure.message}"
            elif records and assertion.expected is not None and not passed:
                message = f"Interaction {assertion.interaction_id!r} did not accept expected value {assertion.expected!r}"
            else:
                message = f"Expected interaction {assertion.interaction_id!r} to match"
        case "interaction_rejected":
            records = [record for record in result.interactions if record.rule_id == assertion.interaction_id]
            response = records[-1].response if records else None
            action = response.get("action") if response else None
            passed = bool(records and records[-1].matched and records[-1].failure is None and action in {"decline", "cancel"})
            message = f"Expected interaction {assertion.interaction_id!r} to be declined or cancelled, got {action!r}"
        case "plan_lifecycle":
            steps = [step for step in result.steps if step.id == assertion.step_id]
            actual = steps[-1].plan.lifecycle if steps and steps[-1].plan else None
            passed = actual is not None and _normalize_state(actual) == _normalize_state(assertion.expected)
            message = f"Expected plan lifecycle {assertion.expected!r}, got {actual!r}"
        case "no_mutation_before_step" | "mutation_after_step":
            step_indices = {step.id: index for index, step in enumerate(result.steps)}
            boundary = step_indices.get(assertion.step_id or "")
            mutation_indices = [index for index, step in enumerate(result.steps) if any(_normalize_tool(usage.name) in _MUTATION_TOOLS and usage.started for usage in step.tool_usage)]
            if assertion.type == "no_mutation_before_step":
                passed = boundary is not None and all(index >= boundary for index in mutation_indices)
                message = f"Expected no workspace mutations before step {assertion.step_id!r}"
            else:
                passed = boundary is not None and any(index >= boundary for index in mutation_indices)
                message = f"Expected workspace mutation after step {assertion.step_id!r}"
        case "changed_paths":
            expected_paths = sorted(assertion.paths or [])
            passed = sorted(changed_paths) == expected_paths
            message = f"Expected changed paths {expected_paths!r}, got {sorted(changed_paths)!r}"
        case _:
            message = f"Unsupported trace assertion type: {assertion.type}"

    return TraceAssertionResult(assertion_id=assertion.id, passed=passed, message=message)


def evaluate_trace(entry: BCalScenarioEntry, result: BCalScenarioRunResult, chat_path: Path | None, changed_paths: list[str] | None = None) -> list[TraceAssertionResult]:
    return [evaluate_trace_assertion(assertion, result, chat_path, changed_paths or []) for assertion in entry.evaluation.trace_assertions]


def evaluate_artifact_assertion(
    assertion: BCalDeterministicArtifactAssertion,
    workspace: dict[str, str],
) -> TraceAssertionResult:
    actual = workspace.get(assertion.path)
    if assertion.type == "file_exists":
        passed = actual is not None
    elif assertion.type == "file_contains":
        passed = actual is not None and assertion.expected is not None and assertion.expected in actual
    elif assertion.type == "file_not_contains":
        passed = actual is not None and assertion.expected is not None and assertion.expected not in actual
    else:
        passed = actual == assertion.expected
    if actual is None:
        message = f"Expected artifact {assertion.path!r} was not exported"
    elif passed:
        message = f"Artifact {assertion.path!r} satisfied hidden assertion {assertion.type!r}"
    else:
        message = f"Artifact {assertion.path!r} failed hidden assertion {assertion.type!r}"
    return TraceAssertionResult(assertion_id=assertion.id, passed=passed, message=message)


def _skill_delivery_events(result: BCalScenarioRunResult) -> list[tuple[float, str, str]]:
    trace = result.canonical_trace or {}
    raw_events = trace.get("events")
    if not isinstance(raw_events, list):
        return []
    events: list[tuple[float, str, str]] = []

    def find_scalar(value: object, names: set[str]) -> str:
        if not isinstance(value, dict):
            return ""
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in names and isinstance(child, str):
                return child
        for child in value.values():
            found = find_scalar(child, names)
            if found:
                return found
        return ""

    for index, value in enumerate(raw_events):
        if not isinstance(value, dict):
            continue
        record = cast(dict[str, object], value)
        text = json.dumps(value, sort_keys=True).lower()
        if "skill" not in text or not any(marker in text for marker in ("deliver", "activat", "inject")):
            continue
        sequence = record.get("sequence", record.get("index", index))
        position = float(sequence) if isinstance(sequence, int | float) else float(index)
        skill = find_scalar(record, {"skillid", "skill_id", "skill"})
        source = find_scalar(record, {"source", "activationsource", "activation_source"})
        events.append((position, skill.lower(), source.lower()))
    return events


def _trace_records(result: BCalScenarioRunResult) -> list[dict[str, object]]:
    trace = result.canonical_trace or {}
    events = trace.get("events")
    if not isinstance(events, list):
        return []
    return [cast(dict[str, object], event) for event in events if isinstance(event, dict)]


def _record_sequence(record: dict[str, object], fallback: int = 0) -> int | float | None:
    value = record.get("sequence", record.get("index", fallback))
    return value if isinstance(value, int | float) else None


def _skill_catalog(result: BCalScenarioRunResult) -> tuple[list[dict[str, object]], bool]:
    evidence = result.evidence or {}
    skill_evidence = evidence.get("skillEvidence")
    if not isinstance(skill_evidence, dict):
        return [], False
    skill_evidence_record = cast(dict[str, object], skill_evidence)
    catalog = skill_evidence_record.get("catalog")
    complete = skill_evidence_record.get("catalogTruncated") is False and skill_evidence_record.get("omittedCatalogEntryCount") == 0
    if not isinstance(catalog, list):
        return [], False
    return [cast(dict[str, object], entry) for entry in catalog if isinstance(entry, dict)], complete


def _first_delivery_model_request(records: list[dict[str, object]]) -> dict[str, object] | None:
    return next(
        (record for record in records if record.get("type") == "model_request" and record.get("operation") == "delivery"),
        None,
    )


def _offered_tool_assertions(records: list[dict[str, object]]) -> list[TraceAssertionResult]:
    if os.getenv("BCBENCH_BCAL_REQUIRE_OFFERED_TOOL_EVIDENCE", "").lower() != "true":
        return []
    request = _first_delivery_model_request(records)
    names = request.get("offeredToolNames") if request else None
    count = request.get("offeredToolCount") if request else None
    schema_hash = request.get("offeredToolSchemaHash") if request else None
    truncated = request.get("offeredToolsTruncated") if request else None
    omitted = request.get("omittedOfferedToolCount") if request else None
    activate_skill_offered = request.get("activateSkillToolOffered") if request else None
    normalized_names = {_normalize_tool(name) for name in names if isinstance(name, str)} if isinstance(names, list) else set()
    complete = request is not None and truncated is False and omitted == 0
    count_valid = isinstance(names, list) and isinstance(count, int) and count == len(names)
    schema_hash_valid = isinstance(schema_hash, str) and len(schema_hash) == 64 and all(character in "0123456789abcdef" for character in schema_hash)
    return [
        TraceAssertionResult(
            assertion_id="variant-offered-tools-complete",
            passed=complete,
            message="Expected complete, nontruncated offered-tool evidence on the first delivery model request",
        ),
        TraceAssertionResult(
            assertion_id="variant-activate-skill-offered",
            passed=complete and activate_skill_offered is True and "activate_skill" in normalized_names,
            message="Expected activateSkillToolOffered=true and activate_skill in the first delivery model request offered-tool names",
        ),
        TraceAssertionResult(
            assertion_id="variant-offered-tool-count",
            passed=complete and count_valid,
            message="Expected offeredToolCount to equal the number of offeredToolNames",
        ),
        TraceAssertionResult(
            assertion_id="variant-offered-tool-schema-hash",
            passed=complete and schema_hash_valid,
            message="Expected a lowercase SHA-256 offeredToolSchemaHash without raw tool schemas",
        ),
    ]


def _variant_skill_assertions(result: BCalScenarioRunResult) -> list[TraceAssertionResult]:
    policy = os.getenv("BCBENCH_BCAL_SKILL_ACTIVATION_POLICY")
    if not policy:
        return []
    expected_skill = os.environ.get("BCBENCH_BCAL_REPORT_SKILL_ID", "report").lower()
    expected_mode = os.getenv("BCBENCH_BCAL_EXPECTED_ACTIVATION_MODE", "").lower()
    expected_contract = os.getenv("BCBENCH_BCAL_SKILL_CONTRACT_VERSION", "").lower()
    expected_content_sha = os.getenv("BCBENCH_BCAL_SKILL_CONTENT_SHA256", "").lower()
    expected_revision = os.getenv("BCBENCH_BCAL_SKILL_REVISION", "").lower()
    expected_catalog = os.getenv("BCBENCH_BCAL_SKILL_CATALOG_SEGMENT", "").lower()
    expected_segment = os.getenv("BCBENCH_BCAL_SKILL_ACTIVATED_SEGMENT", "").lower()
    expected_request_id = os.getenv("BCBENCH_BCAL_REQUESTED_TOOL_CALL_ID", "").lower()
    canonical_trace = result.canonical_trace
    trace_complete = canonical_trace is not None and not _canonical_trace_is_incomplete(result)
    assertions = [
        TraceAssertionResult(
            assertion_id="variant-canonical-trace-complete",
            passed=trace_complete,
            message="Expected a present, nontruncated canonical trace for report-study evidence",
        )
    ]
    deliveries = _skill_delivery_events(result)
    matching = [event for event in deliveries if expected_skill in event[1] or expected_skill in json.dumps(event)]
    evidence_text = json.dumps(result.evidence or {}, sort_keys=True).lower()
    if policy == "forbidden":
        return [
            *assertions,
            *_offered_tool_assertions(_trace_records(result)),
            TraceAssertionResult(
                assertion_id="variant-skill-not-delivered",
                passed=not matching and (not expected_segment or expected_segment not in evidence_text),
                message=f"Expected no {expected_skill!r} skill delivery in the permanent-guidance variant",
            ),
        ]
    trace_events = _trace_records(result)
    catalog, catalog_complete = _skill_catalog(result)
    matching_catalog = [entry for entry in catalog if str(entry.get("name", "")).lower() == expected_skill and str(entry.get("revisionId", "")).lower() == expected_revision]
    identity_valid = catalog_complete and any(
        str(entry.get("semanticContractVersion", "")).lower() == expected_contract and str(entry.get("contentHash", "")).lower() == expected_content_sha for entry in matching_catalog
    )
    lifecycle_types = (
        "skill_activation_requested",
        "skill_activation_pending",
        "skill_instructions_delivered",
        "skill_activation_ready",
    )
    lifecycle = {
        event_type: [record for record in trace_events if record.get("type") == event_type and str(record.get("skillRevisionId", "")).lower() == expected_revision] for event_type in lifecycle_types
    }
    lifecycle_records = [record for event_type in lifecycle_types for record in lifecycle[event_type]]
    mode_valid = (
        bool(matching_catalog)
        and all(str(entry.get("activationMode", "")).lower() == expected_mode for entry in matching_catalog)
        and bool(lifecycle_records)
        and all(str(record.get("skillActivationMode", "")).lower() == expected_mode for record in lifecycle_records)
    )
    prompt_delivery_valid = all(expected and expected in evidence_text for expected in (expected_catalog, expected_segment))
    requested_records = lifecycle["skill_activation_requested"]
    request_keys = ("activateSkillToolCallId", "requestedToolCallId", "requested_tool_call_id")
    requested_values = [record[key] for record in requested_records for key in request_keys if key in record]
    if expected_request_id == "non_null":
        requested_tool_call_valid = any(isinstance(value, str) and bool(value.strip()) for value in requested_values)
    elif expected_request_id == "null":
        requested_tool_call_valid = bool(requested_values) and all(value is None for value in requested_values)
    else:
        requested_tool_call_valid = not requested_values
    requested = requested_records[0] if len(requested_records) == 1 else None
    pending = lifecycle["skill_activation_pending"][0] if len(lifecycle["skill_activation_pending"]) == 1 else None
    delivered = lifecycle["skill_instructions_delivered"][0] if len(lifecycle["skill_instructions_delivered"]) == 1 else None
    ready = lifecycle["skill_activation_ready"][0] if len(lifecycle["skill_activation_ready"]) == 1 else None
    lifecycle_chain = [requested, pending, delivered, ready]
    activation_ids = {str(record.get("activationId")) for record in lifecycle_chain if record is not None and record.get("activationId") is not None}
    sequences = [_record_sequence(record) for record in lifecycle_chain if record is not None]
    ready_sequence = _record_sequence(ready) if ready else None
    delivered_sequence = _record_sequence(delivered) if delivered else None

    def is_workspace_mutation(record: dict[str, object]) -> bool:
        classifications = record.get("toolClassifications")
        return record.get("type") == "tool_started" and isinstance(classifications, list) and "workspace_mutation" in classifications

    first_mutation = next(
        (record for record in trace_events if is_workspace_mutation(record)),
        None,
    )
    first_mutation_sequence = _record_sequence(first_mutation) if first_mutation else None
    receipts = first_mutation.get("skillDependencyReceipts") if first_mutation else None
    receipt_records = [cast(dict[str, object], receipt) for receipt in receipts if isinstance(receipt, dict)] if isinstance(receipts, list) else []
    receipt_valid = any(str(receipt.get("revisionId", "")).lower() == expected_revision and receipt.get("priorReadyEventSequence") == ready_sequence for receipt in receipt_records)
    lifecycle_order_valid = (
        all(record is not None for record in lifecycle_chain)
        and len(activation_ids) == 1
        and len(sequences) == 4
        and all(isinstance(sequence, int | float) for sequence in sequences)
        and sequences == sorted(sequences)
        and len(set(sequences)) == 4
        and ready is not None
        and ready.get("deliveryEventSequence") == delivered_sequence
    )
    delivered_before_mutation = lifecycle_order_valid and (
        first_mutation is None or (isinstance(first_mutation_sequence, int | float) and isinstance(ready_sequence, int | float) and ready_sequence < first_mutation_sequence and receipt_valid)
    )
    return [
        *assertions,
        *_offered_tool_assertions(trace_events),
        TraceAssertionResult(
            assertion_id="variant-skill-identity",
            passed=identity_valid,
            message=f"Expected exact contract/content/revision identity for skill {expected_skill!r}",
        ),
        TraceAssertionResult(
            assertion_id="variant-skill-prompt-delivery",
            passed=prompt_delivery_valid,
            message=f"Expected catalog {expected_catalog!r} and activated segment {expected_segment!r}",
        ),
        TraceAssertionResult(
            assertion_id="variant-activation-mode",
            passed=mode_valid,
            message=f"Expected activationMode {expected_mode!r}",
        ),
        TraceAssertionResult(
            assertion_id="variant-requested-tool-call",
            passed=requested_tool_call_valid,
            message=f"Expected requestedToolCallId state {expected_request_id!r}",
        ),
        TraceAssertionResult(
            assertion_id="variant-skill-before-first-mutation",
            passed=delivered_before_mutation,
            message=f"Expected skill {expected_skill!r} delivery before the first report workspace mutation",
        ),
    ]


def _compile_exported_project(app_folder: Path, package_cache: Path) -> IndependentBuildResult:
    al_files = list(app_folder.rglob("*.al"))
    if not al_files:
        return IndependentBuildResult(status="failed", message="BCal exported no AL source files")

    compiler = shutil.which("al")
    if compiler is None:
        return IndependentBuildResult(
            status="not_attempted",
            message="The standalone 'al' compiler is not installed on PATH. Symbols alone are insufficient for independent compilation.",
        )

    output_folder = app_folder / ".bcbench-build"
    completed = subprocess.run(
        [
            compiler,
            "compile",
            str(app_folder),
            "--packagecachepath",
            str(package_cache),
            "--outputfolder",
            str(output_folder),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = "\n".join(filter(None, (completed.stdout.strip(), completed.stderr.strip())))
    if completed.returncode == 0:
        return IndependentBuildResult(status="passed", message=output or "Standalone AL compilation succeeded")
    return IndependentBuildResult(status="failed", message=output or f"Standalone AL compiler exited with status {completed.returncode}")


def _textual_workspace(app_folder: Path) -> dict[str, str]:
    workspace: dict[str, str] = {}
    for path in sorted(app_folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT_EXTENSIONS or ".alpackages" in path.parts or ".bcbench-build" in path.parts:
            continue
        workspace[path.relative_to(app_folder).as_posix()] = path.read_text(encoding="utf-8", errors="replace")
    return workspace


def _export_diff(repo_path: Path, app_folder: Path) -> tuple[str, list[str]]:
    relative_app = app_folder.relative_to(repo_path)
    subprocess.run(["git", "add", "--", str(relative_app)], cwd=repo_path, capture_output=True, check=True)
    completed = subprocess.run(
        ["git", "--no-pager", "diff", "--cached", "--binary", "--", str(relative_app)],
        cwd=repo_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    changed = subprocess.run(
        ["git", "--no-pager", "diff", "--cached", "--name-only", "--", str(relative_app)],
        cwd=repo_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return completed.stdout, [path for path in changed.stdout.splitlines() if path]


def _confirmed_decisions(result: BCalScenarioRunResult) -> list[dict[str, object]]:
    return [
        {
            "ruleId": record.rule_id,
            "question": record.request.question,
            "response": record.response,
            "usedDefault": record.used_default,
        }
        for record in result.interactions
        if record.matched
    ]


def _create_scoring_packet(
    entry: BCalScenarioEntry,
    result: BCalScenarioRunResult,
    build: IndependentBuildResult,
    trace: list[TraceAssertionResult],
    workspace: dict[str, str],
    diff: str,
    changed_paths: list[str],
) -> str:
    evidence = result.evidence or {}
    prompt_evidence = evidence.get("promptEvidence")
    trace_evidence = evidence.get("trace")
    packet = {
        "task": entry.get_task(),
        "confirmedScriptedDecisions": _confirmed_decisions(result),
        "executionIdentity": result.execution_identity,
        "workspaceSeed": (result.workspace_seed.model_dump(mode="json", by_alias=True) if result.workspace_seed else None),
        "promptEvidence": prompt_evidence if isinstance(prompt_evidence, dict) else None,
        "deterministicResult": {
            "scenarioCompleted": result.completed,
            "independentBuild": build.model_dump(mode="json"),
            "traceCompliance": all(assertion.passed for assertion in trace),
            "runtimeStatus": "not_run" if entry.evaluation.runtime_verification is not None else None,
            "runnerFailure": result.failure.model_dump(mode="json", by_alias=True) if result.failure else None,
        },
        "traceSummary": [assertion.model_dump(mode="json") for assertion in trace],
        "canonicalTrace": trace_evidence if isinstance(trace_evidence, dict) else None,
        "forbiddenAssertions": entry.evaluation.forbidden_assertions,
        "changedPaths": changed_paths,
        "workspaceDiff": diff,
        "exportedWorkspace": workspace,
    }
    return json.dumps(packet, indent=2, ensure_ascii=False)


def _archive_workspace(entry: BCalScenarioEntry, app_folder: Path, result_dir: Path) -> None:
    artifact_path = result_dir / "artifacts" / f"{entry.instance_id}-workspace.zip"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(artifact_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app_folder.rglob("*")):
            if path.is_file() and ".git" not in path.parts:
                archive.write(path, path.relative_to(app_folder))


class BCalScenarioPipeline(EvaluationPipeline[BCalScenarioEntry]):
    def setup_workspace(self, entry: BCalScenarioEntry, repo_path: Path) -> None:
        if repo_path.exists():
            shutil.rmtree(repo_path)
        app_folder = repo_path / SCENARIO_EXPORT_DIR
        app_folder.mkdir(parents=True)
        bootstrap_app_json(
            app_folder,
            entry.instance_id,
            entry.environment_setup_version,
            app_id=_scenario_app_id(entry.instance_id),
        )
        for relative_path, content in entry.workspace_files.items():
            path = app_folder / Path(relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        vscode_folder = app_folder / ".vscode"
        vscode_folder.mkdir()
        for file_name in ("launch.json", "settings.json"):
            (vscode_folder / file_name).write_bytes(b"{}\n")
        copy_symbol_apps(repo_path / SCENARIO_SYMBOL_DIR, entry.environment_setup_version)
        (repo_path / ".gitignore").write_text(".bcal-symbols/\n**/.alpackages/\n**/.bcbench-build/\n", encoding="utf-8")
        _git_init_and_commit(repo_path)

    def setup(self, context: EvaluationContext[BCalScenarioEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext[BCalScenarioEntry], agent_runner: AgentRunner[BCalScenarioEntry]) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[BCalScenarioEntry]) -> None:
        result = load_scenario_result(context.repo_path / SCENARIO_RESULT)
        chat_path = resolve_session_chat(result, context.repo_path)
        app_folder = context.repo_path / SCENARIO_EXPORT_DIR
        package_cache = context.repo_path / SCENARIO_SYMBOL_DIR / ".alpackages"
        build = (
            _compile_exported_project(app_folder, package_cache)
            if context.entry.evaluation.compile_required
            else IndependentBuildResult(status="not_attempted", message="Compilation is not required by this entry")
        )
        workspace = _textual_workspace(app_folder)
        diff, changed_paths = _export_diff(context.repo_path, app_folder)
        trace = [
            *evaluate_trace(context.entry, result, chat_path, changed_paths),
            *(evaluate_artifact_assertion(assertion, workspace) for assertion in context.entry.evaluation.deterministic_artifact_assertions),
            *_variant_skill_assertions(result),
        ]
        _archive_workspace(context.entry, app_folder, context.result_dir)
        output = _create_scoring_packet(context.entry, result, build, trace, workspace, diff, changed_paths)
        runtime_status = "not_run" if context.entry.evaluation.runtime_verification is not None else None
        error_message = result.failure.message if result.failure else None
        evaluation_result = BCalScenarioEvaluationResult.create(
            context,
            output=output,
            scenario_completed=result.completed,
            independent_build=build,
            trace_assertions=trace,
            runtime_status=runtime_status,
            execution_identity=result.execution_identity,
            workspace_seed=(result.workspace_seed.model_dump(mode="json", by_alias=True) if result.workspace_seed else None),
            prompt_evidence=result.prompt_evidence,
            canonical_trace=result.canonical_trace,
            semantic_metrics_eligible=any(step.assistant_text for step in result.steps) or result.totals.output_tokens > 0,
            error_message=error_message,
        )
        self.save_result(context, evaluation_result)
