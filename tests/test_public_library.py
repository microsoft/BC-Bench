import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
from bcbench_core import EvaluationContext, EvaluationResult, ProviderUnavailableError, RunIdentity, aggregate_summaries, core_version, execute, load_results, run_command, score_results, summarize
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]


class Entry(BaseModel):
    instance_id: str
    value: str


class Result(EvaluationResult):
    output: str


class Pipeline:
    def evaluate(self, context: EvaluationContext[Entry], agent) -> Result:
        return Result(instance_id=context.instance_id, identity=context.identity, agent="static", model="test", output=agent(context))


class Scorer:
    scorer_id = "exact/v1"

    def __call__(self, result: Result) -> float:
        return float(result.output == "OK")


def identity(consumer: str = "consumer-a", scorer: str = "exact/v1") -> RunIdentity:
    return RunIdentity(core_version=core_version(), consumer_revision=consumer, benchmark_id="fixture/v1", data_revision="dataset-a", scorer_id=scorer, experiment={"seed": 1})


def test_consumer_configuration_is_isolated_and_results_round_trip(tmp_path):
    left, right = (tmp_path / "left", tmp_path / "right")
    for output_dir, consumer in ((left, "consumer-a"), (right, "consumer-b")):
        context = EvaluationContext(
            entry=Entry(instance_id="case", value="OK"), instance_id="case", workspace=output_dir / "workspace", output_file=output_dir / "results.jsonl", identity=identity(consumer)
        )
        execute(context, lambda ctx: ctx.entry.value, Pipeline())
        results = load_results([context.output_file], Result, identity=context.identity)
        summary = summarize(score_results(results, Scorer()))
        assert summary.count == 1
        aggregate = aggregate_summaries([summary, summary])
        assert aggregate.mean_score == 1.0
        assert len(aggregate.runs) == 2
    assert load_results([left / "results.jsonl"], Result)[0].identity.consumer_revision == "consumer-a"
    with pytest.raises(ValueError, match="Incompatible result identity"):
        load_results([left / "results.jsonl"], Result, identity=identity("consumer-b"))


def test_mismatched_scorer_and_aggregation_are_rejected():
    result = Result(instance_id="case", identity=identity(scorer="other/v1"), agent="static", model="test", output="OK")
    with pytest.raises(ValueError, match="requires scorer"):
        score_results([result], Scorer())
    left = summarize(score_results([result.model_copy(update={"identity": identity()})], Scorer()))
    right = left.model_copy(update={"identity": identity("consumer-b")})
    with pytest.raises(ValueError, match="incompatible"):
        aggregate_summaries([left, right])


def test_unavailable_agent_does_not_fall_back(tmp_path):
    with pytest.raises(ProviderUnavailableError, match="unavailable"):
        run_command(["bcbench-nonexistent-agent-123"], workspace=tmp_path, env={}, timeout=5)


def test_command_agent_receives_only_scoped_environment(tmp_path):
    result = run_command(
        [sys.executable, "-c", "import os; print(os.getenv('SECRET', 'missing'))"],
        workspace=tmp_path,
        env={"PATH": os.environ.get("PATH", "")},
        timeout=5,
    )
    assert result.stdout.strip() == "missing"


def test_distribution_contents_and_external_consumer(tmp_path):
    dist = Path(os.environ["BCBENCH_CORE_DIST"]) if "BCBENCH_CORE_DIST" in os.environ else tmp_path / "dist"
    if "BCBENCH_CORE_DIST" not in os.environ:
        subprocess.run(["uv", "build", str(ROOT / "library"), "--out-dir", str(dist)], check=True, capture_output=True, text=True)
    wheel = next(dist.glob("bcbench_core-*.whl"))
    sdist = next(dist.glob("bcbench-core-*.tar.gz"))
    with zipfile.ZipFile(wheel) as archive:
        wheel_files = archive.namelist()
        assert all(name.startswith(("bcbench_core/", "bcbench_core-0.1.0.dist-info/")) for name in wheel_files)
        texts = [archive.read(name) for name in wheel_files if name.endswith((".py", "METADATA"))]
    with tarfile.open(sdist, "r:gz") as archive:
        sdist_files = [member.name for member in archive.getmembers() if member.isfile()]
        assert all(
            name.startswith(("bcbench-core-0.1.0/src/bcbench_core/", "bcbench-core-0.1.0/src/bcbench_core.egg-info/"))
            or name
            in {
                "bcbench-core-0.1.0/README.md",
                "bcbench-core-0.1.0/PKG-INFO",
                "bcbench-core-0.1.0/pyproject.toml",
                "bcbench-core-0.1.0/setup.cfg",
            }
            for name in sdist_files
        )
        texts.extend(
            stream.read() for member in archive.getmembers() if member.isfile() and member.name.endswith((".py", ".toml", ".md", "PKG-INFO")) if (stream := archive.extractfile(member)) is not None
        )
    assert not any(marker in text for marker in (b"microsoftInternal", b"packagefeedproxy", b"CAPI_CLIENT_ID", b"bcbench.jsonl") for text in texts)

    site = tmp_path / "site"
    subprocess.run(["uv", "pip", "install", "--target", str(site), "--no-deps", str(wheel)], check=True, capture_output=True, text=True)
    output = tmp_path / "output"
    process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "examples/synthetic-consumer/consumer.py"),
            "--dataset",
            str(ROOT / "examples/synthetic-consumer/dataset.jsonl"),
            "--workspace",
            str(tmp_path / "workspace"),
            "--output-dir",
            str(output),
            "--consumer-revision",
            "external-consumer-1",
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(site)},
        check=True,
        capture_output=True,
        text=True,
    )
    assert "2 answers round-tripped; mean score 1.0" in process.stdout
    assert json.loads((output / "summary.jsonl").read_text(encoding="utf-8"))["identity"]["consumer_revision"] == "external-consumer-1"
