from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import cast

from bcbench.agent.bcal.scenario import SCENARIO_EXPORT_DIR, SCENARIO_RESULT, SCENARIO_SYMBOL_DIR, BCalScenarioRunResult, load_scenario_result, resolve_session_chat
from bcbench.dataset import BCalScenarioEntry, BCalTraceAssertion
from bcbench.evaluate.base import AgentRunner, EvaluationPipeline
from bcbench.github_actions import github_log_group
from bcbench.logger import get_logger
from bcbench.operations import bootstrap_app_json, copy_symbol_apps
from bcbench.results import BCalScenarioEvaluationResult, IndependentBuildResult, TraceAssertionResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

_MUTATION_TOOLS = frozenset({"write_file", "edit_file", "create_file", "apply_patch", "replace_text", "patch_text"})
_TEXT_EXTENSIONS = frozenset({".al", ".json", ".md", ".txt", ".xml", ".yml", ".yaml", ".ps1", ".toml"})


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
) -> TraceAssertionResult:
    events = _chat_tool_events(chat_path) or _result_tool_events(result)
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
            after_positions = tool_positions.get(after, [])
            passed = bool(before_positions and after_positions and min(before_positions) < min(after_positions))
            message = f"Expected {before!r} before {after!r}"
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
            message = f"Expected interaction {assertion.interaction_id!r} to match"
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
        case _:
            message = f"Unsupported trace assertion type: {assertion.type}"

    return TraceAssertionResult(assertion_id=assertion.id, passed=passed, message=message)


def evaluate_trace(entry: BCalScenarioEntry, result: BCalScenarioRunResult, chat_path: Path | None) -> list[TraceAssertionResult]:
    return [evaluate_trace_assertion(assertion, result, chat_path) for assertion in entry.evaluation.trace_assertions]


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


def _export_diff(repo_path: Path, app_folder: Path) -> str:
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
    return completed.stdout


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
) -> str:
    packet = {
        "task": entry.get_task(),
        "confirmedScriptedDecisions": _confirmed_decisions(result),
        "deterministicResult": {
            "scenarioCompleted": result.completed,
            "independentBuild": build.model_dump(mode="json"),
            "traceCompliance": all(assertion.passed for assertion in trace),
            "runtimeStatus": "not_run" if entry.evaluation.runtime_verification is not None else None,
            "runnerFailure": result.failure.model_dump(mode="json", by_alias=True) if result.failure else None,
        },
        "traceSummary": [assertion.model_dump(mode="json") for assertion in trace],
        "forbiddenAssertions": entry.evaluation.forbidden_assertions,
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
        bootstrap_app_json(app_folder, entry.instance_id, entry.environment_setup_version)
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
        trace = evaluate_trace(context.entry, result, chat_path)
        app_folder = context.repo_path / SCENARIO_EXPORT_DIR
        package_cache = context.repo_path / SCENARIO_SYMBOL_DIR / ".alpackages"
        build = (
            _compile_exported_project(app_folder, package_cache)
            if context.entry.evaluation.compile_required
            else IndependentBuildResult(status="not_attempted", message="Compilation is not required by this entry")
        )
        workspace = _textual_workspace(app_folder)
        diff = _export_diff(context.repo_path, app_folder)
        _archive_workspace(context.entry, app_folder, context.result_dir)
        output = _create_scoring_packet(context.entry, result, build, trace, workspace, diff)
        runtime_status = "not_run" if context.entry.evaluation.runtime_verification is not None else None
        error_message = result.failure.message if result.failure else None
        evaluation_result = BCalScenarioEvaluationResult.create(
            context,
            output=output,
            scenario_completed=result.completed,
            independent_build=build,
            trace_assertions=trace,
            runtime_status=runtime_status,
            error_message=error_message,
        )
        self.save_result(context, evaluation_result)
