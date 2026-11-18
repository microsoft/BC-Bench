from __future__ import annotations

import asyncio
import json
import logging
import traceback
from contextlib import ExitStack
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING

from azure.ai.evaluation import IndirectAttackEvaluator
from azure.core.credentials import TokenCredential
from azure.identity import DefaultAzureCredential
from pydantic import JsonValue, TypeAdapter
from pyrit.memory import CentralMemory, SQLiteMemory

from bcbench.harms import Capture, CaptureConfig, Case, EvaluationProject, Trial, capture_case, export_captures, prepare_capture, read_objects, run_capture, write_json
from bcbench.harms_report import write_report
from bcbench.harms_summary import CONTENT_METRICS

if TYPE_CHECKING:
    # The public SDK reexports also include empty Sphinx-only placeholder classes.
    from azure.ai.evaluation.red_team._attack_objective_generator import RiskCategory, SupportedLanguages
    from azure.ai.evaluation.red_team._attack_strategy import AttackStrategy
    from azure.ai.evaluation.red_team._red_team import RedTeam
else:
    from azure.ai.evaluation.red_team import AttackStrategy, RedTeam, RiskCategory, SupportedLanguages


def _ensure_utf8_file_handlers(logger: logging.Logger) -> None:
    for handler in logger.handlers[:]:
        if not isinstance(handler, logging.FileHandler) or handler.encoding == "utf-8":
            continue
        replacement = logging.FileHandler(handler.baseFilename, mode=handler.mode, encoding="utf-8", delay=handler.delay, errors=handler.errors)
        replacement.setLevel(handler.level)
        replacement.setFormatter(handler.formatter)
        for handler_filter in handler.filters:
            replacement.addFilter(handler_filter)
        logger.removeHandler(handler)
        handler.close()
        logger.addHandler(replacement)


def _objects(value: JsonValue) -> list[dict[str, JsonValue]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("Expected a list of SDK objects.")
    return [item for item in value if isinstance(item, dict)]


def summarize_sdk_results(raw: dict[str, JsonValue], captures: list[Capture], risk: str, requested: int) -> dict[str, JsonValue]:
    summary = TypeAdapter(dict[str, JsonValue]).validate_python(raw.get("AOAI_Compatible_Summary") or {})
    output_items = TypeAdapter(dict[str, JsonValue]).validate_python(summary.get("output_items") or {})
    items = _objects(output_items.get("data") or [])
    outcomes: list[dict[str, JsonValue]] = []
    returned = 0
    for item in items:
        returned += sum(result.get("name") == risk for result in _objects(item.get("results") or []))
    for capture in captures:
        expected_input = [{"role": "user", "content": capture.case.trial.prompt}]
        expected_output = [{"role": "assistant", "content": capture.response}]
        matches = [item for item in items if isinstance(sample := item.get("sample"), dict) and sample.get("input") == expected_input and sample.get("output") == expected_output]
        outcome: dict[str, JsonValue] = {"execution_id": capture.case.execution_id, "status": "missing", "reason": "No matching SDK output item."}
        duplicate_capture = sum(other.case.trial.prompt == capture.case.trial.prompt and other.response == capture.response for other in captures) > 1
        if len(matches) > 1 or duplicate_capture:
            outcome.update(status="ambiguous", reason="Multiple SDK items match this query/response; no positional pairing.")
        elif matches:
            item = matches[0]
            sample = TypeAdapter(dict[str, JsonValue]).validate_python(item["sample"])
            results = [result for result in _objects(item.get("results") or []) if result.get("name") == risk]
            outcome["sdk_output_item_id"] = item.get("id")
            if item.get("status") not in (None, "completed") or sample.get("error"):
                outcome.update(status="error", reason=sample.get("error") or "SDK output item failed.")
            elif len(results) != 1:
                outcome["reason"] = "Expected exactly one SDK result for the requested risk category."
            else:
                result = results[0]
                outcome["sdk_result"] = result
                outcome["reason"] = result.get("reason")
                properties = result.get("properties")
                returned_error = isinstance(properties, dict) and properties.get("outcome") == "error"
                if result.get("status") not in (None, "completed") or result.get("error") or returned_error:
                    outcome.update(status="error", reason=result.get("error") or result.get("reason") or result.get("status"))
                elif isinstance(result.get("passed"), bool):
                    outcome["status"] = "evaluated"
                else:
                    outcome["reason"] = result.get("reason") or "SDK returned no judgment."
        outcomes.append(outcome)
    evaluated = sum(outcome["status"] == "evaluated" for outcome in outcomes)
    return {
        "requested": requested,
        "target_executions": len(captures),
        "returned_output_items": len(items),
        "returned_evaluator_results": returned,
        "evaluated": evaluated,
        "missing_or_error": max(requested, len(captures)) - evaluated,
        "complete": len(captures) == requested == len(items) == returned == evaluated and all(capture.exportable for capture in captures),
        "outcomes": list(outcomes),
    }


def export_sdk_report(output: Path) -> None:
    captures = [Capture.model_validate(row) for row in read_objects(output / "captures.jsonl")]
    evaluations = TypeAdapter(dict[str, dict[str, JsonValue]]).validate_json((output / "sdk" / "completeness.json").read_text(encoding="utf-8"))
    by_id = {capture.case.execution_id: capture for capture in captures}
    rows: list[dict[str, JsonValue]] = []
    for risk, evaluation in evaluations.items():
        for outcome in _objects(evaluation["outcomes"]):
            capture = by_id[TypeAdapter(str).validate_python(outcome["execution_id"])]
            result = TypeAdapter(dict[str, JsonValue]).validate_python(outcome.get("sdk_result") or {})
            rows.append(
                {
                    "Execution ID": capture.case.execution_id,
                    "Case ID": capture.case.trial.case_id,
                    "Subset": capture.case.subset,
                    "Vector": capture.case.trial.vector,
                    "Input prompt": capture.case.trial.prompt,
                    "Output": capture.response,
                    "Injection context": capture.case.trial.attack,
                    "BC context": capture.case.context.model_dump(mode="json"),
                    "Evaluator": risk,
                    "Evaluation status": outcome["status"],
                    "Passed (SDK)": result.get("passed"),
                    "Score (SDK, optional)": result.get("indirect_attack", result.get("score")),
                    "Label (SDK)": result.get("indirect_attack_label", result.get("label")),
                    "Reason (SDK)": result.get("indirect_attack_reason", result.get("reason")),
                    "SDK result": result,
                    "Capture complete": capture.exportable,
                }
            )
    summary = [{"Evaluator": risk, **{key: value for key, value in evaluation.items() if key != "outcomes"}} for risk, evaluation in evaluations.items()]
    provenance: list[dict[str, JsonValue]] = []
    for source in (output / "run.json", output / "sdk" / "identity.json"):
        if source.exists():
            values = TypeAdapter(dict[str, JsonValue]).validate_json(source.read_text(encoding="utf-8"))
            provenance.extend({"Source": source.name, "Field": key, "Value": value} for key, value in values.items())
    provenance.append(
        {
            "Source": "Report",
            "Field": "Assessment ownership",
            "Value": "SDK judgments, not manually confirmed defects. No local safety thresholds; missing judgments are not passes. Optional numeric scores may be absent in RedTeam summaries.",
        }
    )
    write_report(output / "report.xlsx", {"Results": rows, "Summary": summary, "Provenance": provenance})


def run_generation(config: CaptureConfig, bcal: Path, bridge_python: Path, symbols: Path, output: Path) -> dict[str, JsonValue]:
    generation = config.generation
    if generation is None:
        raise ValueError("Generated runs require explicit generation project, context, risks and objective count.")
    prepare_capture(config, bcal, symbols, output)
    sdk_root = output / "sdk"
    sdk_root.mkdir()
    write_json(
        sdk_root / "identity.json",
        {
            "azure_ai_evaluation": version("azure-ai-evaluation"),
            "pyrit": version("pyrit"),
            "generation": generation.model_dump(),
            "attack_strategies": [AttackStrategy.Baseline.value],
            "language": SupportedLanguages.English.value,
            "skip_evals": False,
            "skip_upload": True,
            "evaluation_content_sent_to_service": True,
        },
    )
    evaluations = {risk: summarize_sdk_results({}, [], risk, generation.num_objectives) for risk in generation.risk_categories}
    write_json(sdk_root / "completeness.json", evaluations)
    captured: list[Capture] = []
    # SQLiteMemory is a singleton: select and verify its path before RedTeam initializes memory.
    memory = SQLiteMemory(db_path=sdk_root / "memory.db")
    if not isinstance(memory, SQLiteMemory) or Path(memory.db_path).resolve() != (sdk_root / "memory.db").resolve():
        raise RuntimeError("PyRIT memory was already initialized elsewhere. Use a fresh process to keep content in this run directory.")
    CentralMemory.set_memory_instance(memory)
    with (
        ExitStack() as cleanup,
        (output / "cases.jsonl").open("x", encoding="utf-8") as cases_file,
        (output / "captures.jsonl").open("x", encoding="utf-8") as captures_file,
        DefaultAzureCredential() as credential,
    ):
        cleanup.callback(memory.dispose_engine)

        async def scan_risk(risk: str) -> dict[str, JsonValue]:
            risk_output = sdk_root / risk
            risk_output.mkdir()
            current: list[Capture] = []
            target_error: Exception | None = None
            lock = asyncio.Lock()

            async def capture_target(
                messages: list[dict[str, JsonValue]],
                stream: bool = False,
                session_state: str | None = None,
                context: dict[str, JsonValue] | None = None,
            ) -> dict[str, object]:
                if len(current) >= generation.num_objectives:
                    raise RuntimeError("SDK requested more target executions than the explicitly configured objective count.")
                # This adapter is single-turn/direct only. Do not silently discard SDK context or history.
                if len(messages) != 1 or messages[0].get("role") != "user" or not isinstance(messages[0].get("content"), str):
                    raise ValueError("Generated baseline requires one string user message.")
                if stream or context not in (None, {}, {"contexts": []}):
                    raise ValueError("Generated baseline cannot deliver streaming or additional SDK context.")
                prompt = TypeAdapter(str).validate_python(messages[0]["content"])
                case_id = f"generated-{risk}-{len(current):06d}"
                case = Case(
                    execution_id=case_id,
                    subset="direct",
                    trial=Trial(case_id=case_id, vector="direct", channel="redteam_baseline", risk=risk, prompt=prompt, attack=""),
                    context=generation.context,
                    fixture=None,
                )
                cases_file.write(case.model_dump_json() + "\n")
                cases_file.flush()
                write_json(risk_output / f"{case_id}.request.json", {"messages": messages, "context": context, "session_state": session_state, "risk": risk})
                directory = output / f"case-{len(captured):06d}"
                capture = await asyncio.to_thread(capture_case, case, config, bcal, bridge_python, symbols, directory)
                captures_file.write(capture.model_dump_json() + "\n")
                captures_file.flush()
                current.append(capture)
                captured.append(capture)
                if not capture.exportable:
                    raise RuntimeError("Target capture is incomplete or non-exportable.")
                return {"messages": [{"role": "assistant", "content": capture.response}], "stream": False, "session_state": session_state, "context": context or {}}

            async def target(
                messages: list[dict[str, JsonValue]],
                stream: bool = False,
                session_state: str | None = None,
                context: dict[str, JsonValue] | None = None,
            ) -> dict[str, object]:
                nonlocal target_error
                async with lock:
                    if target_error is not None:
                        raise RuntimeError("A previous capture failed; no further target execution is allowed.") from target_error
                    _ensure_utf8_file_handlers(logging.getLogger("RedTeamLogger"))
                    try:
                        response = await capture_target(messages, stream, session_state, context)
                    except Exception as exc:
                        target_error = exc
                        raise
                    else:
                        return response

            raw: dict[str, JsonValue] = {}
            scan_error: str | None = None
            try:
                red_team = RedTeam(
                    azure_ai_project=generation.project.model_dump(),
                    credential=credential,
                    risk_categories=[RiskCategory(risk)],
                    num_objectives=generation.num_objectives,
                    language=SupportedLanguages.English,
                    output_dir=str(risk_output),
                )
                result = await red_team.scan(
                    target=target,
                    attack_strategies=[AttackStrategy.Baseline],
                    skip_evals=False,
                    skip_upload=True,
                    parallel_execution=False,
                    max_parallel_tasks=1,
                    timeout=config.timeout_seconds,
                    output_path=str(risk_output / "results"),
                )
                raw_json = result.to_json()
                (risk_output / "sdk-result.json").write_text(raw_json, encoding="utf-8")
                (risk_output / "attack-details.json").write_text(json.dumps(result.attack_details), encoding="utf-8")
                raw = TypeAdapter(dict[str, JsonValue]).validate_json(raw_json) if raw_json else {}
            except Exception as exc:  # noqa: BLE001 - preserve partial captures, record the SDK failure, then fail the run below.
                scan_error = type(exc).__name__
                (risk_output / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            status = summarize_sdk_results(raw, current, risk, generation.num_objectives)
            if scan_error or target_error or status["missing_or_error"]:
                status.update(complete=False, error=scan_error or ("target_error" if target_error else "missing_sdk_judgment"))
            return status

        for risk in generation.risk_categories:
            evaluations[risk] = asyncio.run(scan_risk(risk))
            write_json(sdk_root / "completeness.json", evaluations)
            if not evaluations[risk]["complete"]:
                break
    summary = export_captures(output) if (output / "cases.jsonl").stat().st_size else {"captured": 0}
    if any(not value["complete"] for value in evaluations.values()):
        raise RuntimeError("SDK generation/evaluation incomplete. Inspect private SDK results and completeness; saved captures remain independently exportable.")
    return summary


async def score_saved_content(capture: Capture, metric: str, project: EvaluationProject, credential: TokenCredential, directory: Path, timeout_seconds: int) -> dict[str, JsonValue]:
    messages = [{"role": "user", "content": capture.case.trial.prompt}]
    seeds = [{"id": capture.case.execution_id, "metadata": {"target_harms": [{"risk-type": metric}]}, "messages": messages}]
    write_json(directory / "seeds.json", seeds)
    calls = 0

    async def target(
        messages: list[dict[str, JsonValue]],
        stream: bool = False,
        session_state: str | None = None,
        context: dict[str, JsonValue] | None = None,
    ) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls != 1 or stream or context not in (None, {}, {"contexts": []}) or messages != seeds[0]["messages"]:
            raise ValueError("SDK changed supplied input or requested additional execution.")
        return {"messages": [{"role": "assistant", "content": capture.response}], "stream": False, "context": context or {}, "session_state": session_state}

    scanner = RedTeam(
        azure_ai_project=project.model_dump(),
        credential=credential,
        custom_attack_seed_prompts=str(directory / "seeds.json"),
        risk_categories=[RiskCategory(metric)],
        num_objectives=1,
        language=SupportedLanguages.English,
        output_dir=str(directory / "sdk"),
    )
    sdk_result = await scanner.scan(
        target=target,
        attack_strategies=[AttackStrategy.Baseline],
        skip_evals=False,
        skip_upload=True,
        parallel_execution=False,
        max_parallel_tasks=1,
        timeout=timeout_seconds,
        output_path=str(directory / "results"),
    )
    raw = TypeAdapter(dict[str, JsonValue]).validate_json(sdk_result.to_json())
    write_json(directory / "sdk-result.json", raw)
    status = summarize_sdk_results(raw, [capture], metric, 1)
    outcome = _objects(status["outcomes"])[0]
    if calls != 1 or not status["complete"]:
        outcome["status"] = "error"
    return outcome


def run_manual_evaluation(cases_path: Path, config: CaptureConfig, bcal: Path, bridge_python: Path, symbols: Path, output: Path) -> dict[str, JsonValue]:
    project = config.evaluation_project
    if project is None:
        raise ValueError("Manual scoring requires an explicit existing evaluation_project.")
    summary = run_capture(cases_path, config, bcal, bridge_python, symbols, output)
    captures = [Capture.model_validate(row) for row in read_objects(output / "captures.jsonl")]
    sdk_root = output / "sdk"
    sdk_root.mkdir()
    write_json(
        sdk_root / "identity.json",
        {
            "azure_ai_evaluation": version("azure-ai-evaluation"),
            "pyrit": version("pyrit"),
            "project": project.model_dump(),
            "skip_upload": True,
            "evaluation_content_sent_to_service": True,
            "content_path": "RedTeam custom seeds / Baseline",
            "xpia_path": "IndirectAttackEvaluator",
        },
    )
    evaluations: dict[str, dict[str, JsonValue]] = {}
    for capture in captures:
        for metric in ("indirect_attack",) if capture.case.subset == "xpia" else CONTENT_METRICS:
            key = f"manual_{capture.case.subset}/{metric}"
            entry = evaluations.setdefault(key, {"outcomes": []})
            outcomes = _objects(entry["outcomes"])
            outcomes.append({"execution_id": capture.case.execution_id, "status": "missing"})
            entry["outcomes"] = list(outcomes)
    write_json(sdk_root / "completeness.json", evaluations)
    memory = SQLiteMemory(db_path=sdk_root / "memory.db")
    if not isinstance(memory, SQLiteMemory) or Path(memory.db_path).resolve() != (sdk_root / "memory.db").resolve():
        raise RuntimeError("PyRIT memory already initialized elsewhere; use a fresh process.")
    CentralMemory.set_memory_instance(memory)
    with ExitStack() as cleanup, DefaultAzureCredential() as credential:
        cleanup.callback(memory.dispose_engine)
        for index, capture in enumerate(captures):
            for metric in ("indirect_attack",) if capture.case.subset == "xpia" else CONTENT_METRICS:
                key = f"manual_{capture.case.subset}/{metric}"
                outcome = next(value for value in _objects(evaluations[key]["outcomes"]) if value["execution_id"] == capture.case.execution_id)
                directory = sdk_root / f"{index:06d}-{metric}"
                directory.mkdir()
                try:
                    if metric == "indirect_attack":
                        evaluator = IndirectAttackEvaluator(credential=credential, azure_ai_project=project.model_dump())
                        result = TypeAdapter(dict[str, JsonValue]).validate_python(evaluator(query=capture.case.trial.prompt, response=capture.response))
                        write_json(directory / "sdk-result.json", result)
                        outcome.update(sdk_result=result, status="evaluated" if isinstance(result.get("indirect_attack_label"), bool) else "missing")
                        if result.get("error") or result.get("status") not in (None, "completed"):
                            outcome.update(status="error")
                    else:
                        outcome.update(asyncio.run(score_saved_content(capture, metric, project, credential, directory, config.timeout_seconds)))
                except Exception as exc:  # noqa: BLE001 - retain private SDK errors, then stop the run below.
                    outcome.update(status="error", error=type(exc).__name__)
                    (directory / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
                write_json(sdk_root / "completeness.json", evaluations)
                if outcome["status"] != "evaluated":
                    raise RuntimeError("Manual SDK scoring incomplete; private captures and attempts retained.")
    return summary
