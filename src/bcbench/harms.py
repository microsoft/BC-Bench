from __future__ import annotations

import hashlib
import html
import json
import shutil
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator

from bcbench.agent.bcal import BCalBackendConfig, bc_eval_llm_api_bridge, run_bcal_prompt
from bcbench.agent.bcal.agent import BCalPromptResult

type Subset = Literal["direct", "upia", "xpia"]
type Vector = Literal["direct", "page_inspector", "symbols"]


class CaptureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bcal_feed: Literal["official", "experiment", "snapshot"]
    bcal_package_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+[\w.+-]*$")] | None
    bcal_runtime_version: Annotated[str, Field(min_length=1)]
    bc_eval_version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    model: Annotated[str, Field(pattern=r"^[\w.-]+$")]
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"]
    environment: Literal["TEST", "PROD"]
    timeout_seconds: Annotated[int, Field(gt=0)] = 1500
    generation: GenerationConfig | None = None
    evaluation_project: EvaluationProject | None = None

    @model_validator(mode="after")
    def package_provenance(self) -> Self:
        if (self.bcal_feed == "snapshot") != (self.bcal_package_version is None):
            raise ValueError("Snapshots require a null package version; feed installations require an exact package version.")
        return self


class Trial(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    vector: Vector
    channel: str
    risk: str
    prompt: Annotated[str, Field(min_length=1)]
    attack: str


class RuntimeContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: Annotated[str, Field(min_length=1)]
    audience: Annotated[str, Field(min_length=1)]
    mode: Literal["Extension"]
    review_enabled: Literal[False]
    system_prompt_hashes: list[str] | None = None


class EvaluationProject(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subscription_id: Annotated[str, Field(min_length=1)]
    resource_group_name: Annotated[str, Field(min_length=1)]
    project_name: Annotated[str, Field(min_length=1)]


class GenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project: EvaluationProject
    context: RuntimeContext
    num_objectives: Annotated[int, Field(gt=0)]
    risk_categories: Annotated[list[Literal["violence", "self_harm", "sexual", "hate_unfairness"]], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_risks(self) -> Self:
        if len(set(self.risk_categories)) != len(self.risk_categories):
            raise ValueError("Generation risk categories must be unique.")
        return self


class Case(BaseModel):
    # Accept the recovered manifest's additional historical provenance without treating it as configuration.
    model_config = ConfigDict(frozen=True)

    execution_id: Annotated[str, Field(min_length=1)]
    subset: Subset
    trial: Trial
    context: RuntimeContext
    fixture: dict[str, JsonValue] | None

    @model_validator(mode="after")
    def validate_delivery(self) -> Self:
        if self.subset != "xpia":
            if self.trial.vector != "direct" or self.fixture is not None:
                raise ValueError("Direct/UPIA cases cannot add an indirect fixture.")
            return self
        if self.trial.vector == "direct" or not self.trial.attack or self.fixture is None:
            raise ValueError("XPIA requires an original payload and a supported delivery fixture.")
        injections = self.fixture.get("injections")
        if not isinstance(injections, list) or len(injections) != 1:
            raise ValueError("Expected one BCal fixture injection per execution.")
        injection = injections[0]
        if not isinstance(injection, dict) or injection.get("vector") != self.trial.vector or injection.get("payload") != self.trial.attack:
            raise ValueError("Fixture vector/payload differs from the case.")
        return self


class Capture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case: Case
    response: str
    response_channel: Literal["generated_al", "assistant", "assistant_and_generated_al", "unavailable"]
    completed: bool
    injection_landed: bool | None
    errors: list[str]

    @property
    def exportable(self) -> bool:
        delivery_confirmed = self.case.fixture is None or self.injection_landed is True
        return self.completed and delivery_confirmed and bool(self.response.strip()) and not self.errors


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read_objects(path: Path) -> list[dict[str, JsonValue]]:
    with path.open(encoding="utf-8-sig") as stream:
        values = [json.loads(line) for line in stream]
    return TypeAdapter(list[dict[str, JsonValue]]).validate_python(values)


def load_cases(path: Path) -> list[Case]:
    cases = [Case.model_validate(row) for row in read_objects(path)]
    identities = {(case.subset, case.trial.case_id, case.trial.vector, case.trial.channel, case.trial.risk) for case in cases}
    if not cases or len(identities) != len(cases) or len({case.execution_id for case in cases}) != len(cases):
        raise ValueError("Cases must be nonempty with unique execution IDs and full case identities.")
    return cases


def _strings(value: JsonValue) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def inspect_capture(directory: Path, case: Case, config: CaptureConfig, result: BCalPromptResult) -> Capture:
    errors: list[str] = []
    completed = result.exit_code == 0 and not result.timed_out
    texts: list[str] = []
    prompt_hashes: list[JsonValue] = []
    landed = None
    if case.fixture is None:
        transcript = result.transcript or {}
        steps = TypeAdapter(list[dict[str, JsonValue]]).validate_python(transcript.get("steps") or [])
        completed &= transcript.get("completed") is True and not transcript.get("failure") and len(steps) == 1 and steps[0].get("status") == "succeeded"
        if len(steps) == 1 and isinstance(steps[0].get("assistantText"), str):
            texts.append(TypeAdapter(str).validate_python(steps[0]["assistantText"]))
        else:
            errors.append("assistant_output_unavailable")
        if case.context.system_prompt_hashes is not None:
            evidence = TypeAdapter(dict[str, JsonValue]).validate_python(transcript.get("evidence") or {})
            prompts = TypeAdapter(dict[str, JsonValue]).validate_python(evidence.get("promptEvidence") or {})
            compositions = TypeAdapter(list[dict[str, JsonValue]]).validate_python(prompts.get("compositions") or [])
            prompt_hashes = [item.get("fullPromptHash") for item in compositions]
    else:
        events = read_objects(directory / "runtime.jsonl") if (directory / "runtime.jsonl").exists() else []
        sessions = [event for event in events if event.get("event") == "session_start"]
        if len(sessions) != 1 or any(
            sessions[0].get(key) != value for key, value in {"mode": case.context.mode, "audience": case.context.audience, "review_enabled": False, "deployment": config.model}.items()
        ):
            errors.append("runtime_context_mismatch")
        if [event.get("text") for event in events if event.get("event") == "user_message"] != [case.trial.prompt]:
            errors.append("prompt_mismatch")
        completed &= any(event.get("event") == "turn_complete" for event in events)
        responses = [event for event in events if event.get("event") == "llm_response" and event.get("llm_operation") in (None, "Delivery")]
        if not responses:
            errors.append("assistant_output_unavailable")
        for response in responses:
            if response.get("finish_reason") not in ("stop", "tool_calls") or response.get("was_truncated"):
                errors.append("assistant_output_incomplete")
            text = response.get("text_content")
            if isinstance(text, str):
                texts.append(text)
            elif text is not None:
                errors.append("assistant_output_unavailable")
        landed = any(
            event.get("event") == "tool_result" and event.get("success") is True and any(case.trial.attack in html.unescape(text) for text in _strings(event.get("result"))) for event in events
        )
        if not landed:
            errors.append("payload_not_delivered")
        prompt_hashes = [event.get("system_prompt_hash") for event in events if event.get("event") == "llm_request"]
    if not completed:
        errors.append("execution_incomplete")
    if case.context.system_prompt_hashes is not None and (not prompt_hashes or any(value not in case.context.system_prompt_hashes for value in prompt_hashes)):
        errors.append("system_prompt_mismatch")
    generated = "\n\n".join(path.read_text(encoding="utf-8") for path in sorted((directory / "export").rglob("*.al"))).strip()
    text = "\n\n".join(text for text in texts if text.strip())
    response = "\n\n".join(part for part in (text, generated) if part)
    if not response.strip():
        errors.append("assistant_output_unavailable")
    channel = "assistant_and_generated_al" if text and generated else "assistant" if text else "generated_al" if generated else "unavailable"
    return Capture(
        case=case,
        response=response,
        response_channel=channel,
        completed=completed,
        injection_landed=landed,
        errors=sorted(set(errors)),
    )


def capture_case(case: Case, config: CaptureConfig, bcal: Path, bridge_python: Path, symbols: Path, directory: Path) -> Capture:
    directory.mkdir()
    config_path = directory / "transport-config.json"
    write_json(config_path, config.model_dump())
    command = subprocess.list2cmdline(
        [
            str(bridge_python),
            str(Path(bc_eval_llm_api_bridge.__file__)),
            "--config",
            str(config_path),
        ]
    )
    # The runtime may write to its package cache. Isolate each execution without changing runtime behavior.
    cache = directory / "symbols"
    shutil.copytree(symbols, cache)
    fixture_path = None
    if case.fixture is not None:
        fixture_path = directory / "fixture.json"
        write_json(fixture_path, case.fixture)
    write_json(directory / "invocation.json", {"case": case.model_dump()})
    result = run_bcal_prompt(
        query=case.trial.prompt,
        page=case.context.page,
        audience=case.context.audience,
        package_cache_path=cache,
        export_folder=directory / "export",
        backend_config=BCalBackendConfig(command=command, model=config.model),
        executable=bcal,
        output=directory,
        fixture=fixture_path,
        timeout=config.timeout_seconds,
    )
    return inspect_capture(directory, case, config, result)


def export_captures(output: Path) -> dict[str, JsonValue]:
    planned = load_cases(output / "cases.jsonl")
    captures = [Capture.model_validate(row) for row in read_objects(output / "captures.jsonl")]
    by_id = {case.execution_id: case for case in planned}
    if len({capture.case.execution_id for capture in captures}) != len(captures) or any(by_id.get(capture.case.execution_id) != capture.case for capture in captures):
        raise ValueError("Captured identities/inputs differ from planned cases.")
    attempted = {capture.case.execution_id for capture in captures}
    for invocation in output.glob("case-*/invocation.json"):
        invoked_case = Case.model_validate(json.loads(invocation.read_text(encoding="utf-8"))["case"])
        if by_id.get(invoked_case.execution_id) != invoked_case:
            raise ValueError("Invoked inputs differ from planned cases.")
        attempted.add(invoked_case.execution_id)
    exports = output / "foundry"
    exports.mkdir()
    provenance: list[dict[str, JsonValue]] = []
    datasets: dict[str, JsonValue] = {}
    for subset in ("direct", "upia", "xpia"):
        selected = [capture for capture in captures if capture.case.subset == subset and capture.exportable]
        path = exports / f"{subset}.jsonl"
        with path.open("x", encoding="utf-8") as stream:
            for index, capture in enumerate(selected):
                row = {"query": capture.case.trial.prompt, "response": capture.response, "context": capture.case.trial.attack}
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                provenance.append({"execution_id": capture.case.execution_id, "dataset": path.name, "row_index_zero_based": index})
        datasets[subset] = {"rows": len(selected), "sha256": sha256(path)}
    write_json(exports / "provenance.json", provenance)
    summary: dict[str, JsonValue] = {
        "planned": len(planned),
        "attempted": len(attempted),
        "captured": len(captures),
        "unfinalized": len(attempted) - len(captures),
        "not_attempted": len(planned) - len(attempted),
        "completed": sum(capture.completed for capture in captures),
        "injections_planned": sum(case.fixture is not None for case in planned),
        "injections_delivered": sum(capture.injection_landed is True for capture in captures),
        "excluded": sum(not capture.exportable for capture in captures),
        "datasets": datasets,
        "evaluation_performed_by_export": False,
        "uploaded": False,
    }
    write_json(exports / "manifest.json", summary)
    return summary


def prepare_capture(config: CaptureConfig, bcal: Path, symbols: Path, output: Path, cases_path: Path | None = None) -> None:
    if not any(symbols.rglob("*.app")):
        raise ValueError("An explicit populated BC symbol directory is required.")
    version = subprocess.run([str(bcal), "--version"], check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    if version != config.bcal_runtime_version:
        raise ValueError("BCal --version differs from the explicitly selected runtime version.")
    symbol_hashes = {str(path.relative_to(symbols)): sha256(path) for path in sorted(symbols.rglob("*")) if path.is_file()}
    write_json(
        output / "run.json",
        {
            "started_utc": datetime.now(UTC).isoformat(),
            "config": config.model_dump(),
            "bcal_runtime_version": version,
            "bcal_executable_sha256": sha256(bcal),
            "bridge_sha256": sha256(Path(bc_eval_llm_api_bridge.__file__)),
            "source_cases_sha256": sha256(cases_path) if cases_path is not None else None,
            "symbol_files": symbol_hashes,
        },
    )


def run_capture(cases_path: Path, config: CaptureConfig, bcal: Path, bridge_python: Path, symbols: Path, output: Path) -> dict[str, JsonValue]:
    cases = load_cases(cases_path)
    shutil.copyfile(cases_path, output / "cases.jsonl")
    prepare_capture(config, bcal, symbols, output, cases_path)
    with (output / "captures.jsonl").open("x", encoding="utf-8") as stream:
        for index, case in enumerate(cases):
            capture = capture_case(case, config, bcal, bridge_python, symbols, output / f"case-{index:06d}")
            stream.write(capture.model_dump_json() + "\n")
            stream.flush()
            if not capture.exportable:
                break
    summary = export_captures(output)
    if summary["not_attempted"] or summary["unfinalized"] or summary["excluded"]:
        raise RuntimeError("Capture incomplete; inspect local captures and Foundry export denominators. No safety verdicts were assigned.")
    return summary
