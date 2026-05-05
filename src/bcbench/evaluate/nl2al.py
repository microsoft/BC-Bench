import json
import os
import shutil
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


def _reset_repo_path(repo_path: Path) -> None:
    if repo_path.exists():
        shutil.rmtree(repo_path)
    repo_path.mkdir(parents=True, exist_ok=True)


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

        _reset_repo_path(repo_path)
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
        except BuildError as e:
            result = NL2ALResult.create_build_failure(context, output=generated_patch, error_message=str(e))
            logger.exception(f"Build failed for {context.entry.instance_id}")
        else:
            # TODO: LLM-as-judge evaluation against context.entry.get_expected_output()
            llm_judge_score = None

            result = NL2ALResult.create_build_success(context, output=generated_patch, llm_judge_score=llm_judge_score)
            logger.info(f"Build succeeded for {context.entry.instance_id}")

        self.save_result(context, result)
