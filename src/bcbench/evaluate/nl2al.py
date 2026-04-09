import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from bcbench.dataset import NL2ALEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import BuildError
from bcbench.logger import get_logger, github_log_group
from bcbench.operations import build_and_publish_projects, stage_and_get_diff
from bcbench.results.nl2al import NL2ALResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["NL2ALPipeline"]

_APP_JSON_TEMPLATE = {
    "id": "00000000-0000-0000-0000-000000000001",
    "name": "",
    "publisher": "BCBench",
    "version": "1.0.0.0",
    "brief": "",
    "description": "",
    "privacyStatement": "",
    "EULA": "",
    "help": "",
    "url": "",
    "logo": "",
    "dependencies": [],
    "screenshots": [],
    "platform": "",
    "application": "",
    "idRanges": [{"from": 80000, "to": 80099}],
    "resourceExposurePolicy": {"allowDebugging": True, "allowDownloadingSource": True, "includeSourceInSymbolFile": True},
    "runtime": "",
    "target": "Cloud",
}


def _create_al_project_scaffold(project_dir: Path, entry: NL2ALEntry) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    src_dir = project_dir / "src"
    src_dir.mkdir(exist_ok=True)

    app_json = _APP_JSON_TEMPLATE.copy()
    app_name = entry.project_paths[0] if entry.project_paths else "NL2ALApp"
    app_json["name"] = app_name
    app_json["brief"] = f"Generated AL extension: {app_name}"
    app_json["platform"] = f"{entry.environment_setup_version}.0.0"
    app_json["application"] = f"{entry.environment_setup_version}.0.0"
    app_json["runtime"] = f"{entry.environment_setup_version.split('.')[0]}.0"

    app_json_path = project_dir / "app.json"
    app_json_path.write_text(json.dumps(app_json, indent=2), encoding="utf-8")


def _git_init_and_commit(repo_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial AL project scaffold"],
        cwd=repo_path,
        capture_output=True,
        check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "bcbench", "GIT_AUTHOR_EMAIL": "bcbench@localhost", "GIT_COMMITTER_NAME": "bcbench", "GIT_COMMITTER_EMAIL": "bcbench@localhost"},
    )


class NL2ALPipeline(EvaluationPipeline[NL2ALEntry]):
    """Pipeline for NL2AL evaluation category — generate AL code from natural language."""

    def setup_workspace(self, entry: NL2ALEntry, repo_path: Path) -> None:
        project_path = entry.project_paths[0] if entry.project_paths else "App"
        project_dir = repo_path / project_path

        _create_al_project_scaffold(project_dir, entry)
        _git_init_and_commit(repo_path)

    def setup(self, context: EvaluationContext[NL2ALEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext[NL2ALEntry], agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[NL2ALEntry]) -> None:
        generated_patch = stage_and_get_diff(context.repo_path)
        result: NL2ALResult | None = None

        try:
            build_and_publish_projects(
                context.repo_path,
                context.entry.project_paths,
                context.get_container(),
                context.entry.environment_setup_version,
            )

            # TODO: LLM-as-judge evaluation
            # Compare generated_patch against context.entry.get_expected_output()
            # to assess functional correctness beyond just "it builds"

            result = NL2ALResult.create_success(context, generated_patch)
            logger.info(f"Successfully completed {context.entry.instance_id}")

        except BuildError as e:
            result = NL2ALResult.create_build_failure(context, generated_patch, str(e))
            logger.error(f"Build failed during evaluation of {context.entry.instance_id}: {e}")

        finally:
            if result is not None:
                self.save_result(context, result)
            else:
                logger.error(f"No result generated for {context.entry.instance_id}")
                raise RuntimeError(f"No result generated for {context.entry.instance_id}")
