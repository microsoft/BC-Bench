from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import typer
import yaml
from bcbench_core.registry import CategoryRegistry
from dotenv import load_dotenv

from bcbench.agent.settings import AgentSettings, PRReviewSettings
from bcbench.application import AgentSelection
from bcbench.categories.base import CategoryDefinition
from bcbench.config import Config, PathConfig, find_repository_root
from bcbench.dataset.dataset_entry import BaseDatasetEntry
from bcbench.types import AgentHarness, AgentRuntimeConfig, EvaluationCategory, EvaluationContext

if TYPE_CHECKING:
    from bcbench.categories.code_review.judge import JudgeInvoker


@dataclass(frozen=True)
class CommandContext:
    config: Config
    environment: Mapping[str, str]
    shared_config: Mapping[str, Any]


def load_command_context() -> CommandContext:
    root = find_repository_root()
    load_dotenv(root / ".env")
    environment = MappingProxyType(dict(os.environ))
    paths = PathConfig.from_root(root)
    shared_config = yaml.safe_load((paths.agent_share_dir / "config.yaml").read_text(encoding="utf-8"))
    if not isinstance(shared_config, dict):
        raise TypeError("Agent configuration must be a mapping")
    return CommandContext(Config.from_inputs(root, environment, shared_config), environment, MappingProxyType(shared_config))


def command_context(ctx: typer.Context) -> CommandContext:
    state = ctx.find_object(CommandContext)
    if state is None:
        raise RuntimeError("CLI configuration has not been composed")
    return state


def agent_settings(state: CommandContext) -> AgentSettings:
    paths = state.config.paths
    patterns = state.config.file_patterns
    search_path = state.environment.get("PATH", "")
    return AgentSettings(
        timeout=state.config.timeout.agent_execution,
        shared_config=state.shared_config,
        environment=state.environment,
        instructions_root=paths.agent_share_dir / patterns.instructions_dirname,
        instruction_source_naming=patterns.instruction_source_naming,
        plugin_root=paths.plugin_root,
        plugin_manifest=patterns.plugin_manifest,
        problem_statement_dest_dir=patterns.problem_statement_dest_dir,
        artifact_cache_root=paths.bc_artifacts_cache,
        copilot_executable=shutil.which("copilot.exe", path=search_path) or shutil.which("copilot.cmd", path=search_path) or shutil.which("copilot", path=search_path),
        claude_executable=shutil.which("claude", path=search_path),
        pwsh_executable=shutil.which("pwsh", path=search_path),
        gh_executable=shutil.which("gh", path=search_path),
        git_executable=shutil.which("git", path=search_path),
    )


def judge_invoker(settings: AgentSettings) -> JudgeInvoker:
    from bcbench.agent.copilot.cli import invoke_copilot

    def invoke(*, prompt: str, model: str, work_dir: Path, timeout: int) -> str:
        _, response = invoke_copilot(
            prompt=prompt,
            model=model,
            work_dir=work_dir,
            timeout=timeout,
            executable=settings.copilot_executable,
            env=settings.environment,
            allow_all_tools=True,
        )
        return response

    return invoke


def build_category_registry(state: CommandContext) -> CategoryRegistry[EvaluationCategory, CategoryDefinition]:
    config = state.config

    def bugfix() -> CategoryDefinition:
        from bcbench.categories.bugfix import build_definition

        return build_definition(config)

    def testgeneration() -> CategoryDefinition:
        from bcbench.categories.testgeneration import build_definition

        return build_definition(config)

    def codereview() -> CategoryDefinition:
        from bcbench.categories.code_review import build_definition
        from bcbench.categories.code_review.judge import judge_expected_and_ignored
        from bcbench.categories.code_review.pipeline import CodeReviewPipeline
        from bcbench.categories.code_review.workspace import setup_workspace
        from bcbench.github_actions import github_log_group
        from bcbench.operations.setup_operations import remove_table_scope_onprem

        settings = agent_settings(state)
        workspace = partial(
            setup_workspace,
            env=state.environment,
            remote="origin",
            author_name="bcbench",
            author_email="bcbench@noreply",
            normalize_tables=remove_table_scope_onprem,
        )
        judge = partial(
            judge_expected_and_ignored,
            invoke=judge_invoker(settings),
            model=config.judge.code_review_model,
            timeout=config.timeout.agent_execution,
            result_filename=config.judge.result_file,
        )
        return build_definition(
            dataset_path=config.paths.dataset_dir / "codereview.jsonl",
            judge_model=config.judge.code_review_model,
            pipeline_factory=lambda: CodeReviewPipeline(
                result_suffix=config.file_patterns.result_pattern,
                setup_workspace=workspace,
                judge=judge,
                log_group=partial(github_log_group, in_actions=config.env.github_actions),
            ),
        )

    def nl2al() -> CategoryDefinition:
        from bcbench.categories.nl2al import build_definition

        return build_definition(config)

    def dataquery() -> CategoryDefinition:
        from bcbench.categories.dataquery import build_definition

        return build_definition(config)

    def ext_advisor() -> CategoryDefinition:
        from bcbench.categories.ext_request_advisor import build_definition

        return build_definition(config)

    def ext_implement() -> CategoryDefinition:
        from bcbench.categories.ext_request_implement import build_definition

        return build_definition(config)

    def ext_triage() -> CategoryDefinition:
        from bcbench.categories.ext_request_triage import build_definition

        return build_definition(config)

    return CategoryRegistry(
        (
            (EvaluationCategory.BUG_FIX, bugfix),
            (EvaluationCategory.TEST_GENERATION, testgeneration),
            (EvaluationCategory.CODE_REVIEW, codereview),
            (EvaluationCategory.NL2AL, nl2al),
            (EvaluationCategory.DATA_QUERY, dataquery),
            (EvaluationCategory.EXT_REQUEST_ADVISOR, ext_advisor),
            (EvaluationCategory.EXT_REQUEST_IMPLEMENT, ext_implement),
            (EvaluationCategory.EXT_REQUEST_TRIAGE, ext_triage),
        )
    )


def select_agent[E: BaseDatasetEntry](
    state: CommandContext,
    definition: CategoryDefinition[E],
    *,
    name: AgentHarness,
    model: str,
    runtime: AgentRuntimeConfig | None,
    evaluate: bool,
    engine_path: Path | None = None,
    min_severity: str | None = None,
) -> AgentSelection[E]:
    settings = agent_settings(state)
    pass_credentials = definition.capabilities.pass_on_bc_container_credentials

    if name is AgentHarness.PR_REVIEW:
        from bcbench.agent.pr_review import get_pr_review_version, run_pr_review_agent

        engine = PRReviewSettings(
            engine_path=engine_path,
            min_severity=min_severity or str(state.shared_config["pr_review"]["min_severity"]),
            prepare_script=state.config.paths.agent_share_dir.parent / "pr_review" / "scripts" / "Prepare-BCQualityRoot.ps1",
        )
        return AgentSelection(
            name=name,
            model=model,
            version=get_pr_review_version(engine_path, settings=settings) if evaluate else None,
            runner=lambda context: run_pr_review_agent(
                entry=context.entry,
                model=context.model,
                category=definition.name,
                repo_path=context.repo_path,
                output_dir=context.result_dir,
                settings=settings,
                engine=engine,
                pass_bc_credentials=pass_credentials,
            ),
        )

    from bcbench.agent.shared.prompt import build_prompt

    prompt_config = state.shared_config["prompt"]
    template = prompt_config[f"{definition.name.value}-template"]
    context_values = definition.prompt_context(prompt_config)

    def prompt(context: EvaluationContext[E]) -> str:
        return build_prompt(
            template=template,
            task=context.entry.get_task(state.config.paths.problem_statement_dir),
            repo_path=context.repo_path,
            project_paths=context.entry.project_paths,
            problem_statement_dest_dir=settings.problem_statement_dest_dir,
            include_project_paths=bool(prompt_config.get("include_project_paths")),
            context=context_values,
            al_mcp=bool(runtime and runtime.al_mcp),
        )

    match name:
        case AgentHarness.COPILOT:
            from bcbench.agent.copilot import get_copilot_version, run_copilot_agent

            return AgentSelection(
                name=name,
                model=model,
                version=get_copilot_version(settings) if evaluate else None,
                runner=lambda context: run_copilot_agent(
                    entry=context.entry,
                    model=context.model,
                    category=definition.name,
                    repo_path=context.repo_path,
                    output_dir=context.result_dir,
                    runtime=runtime,
                    settings=settings,
                    prompt=prompt(context),
                    pass_bc_credentials=pass_credentials,
                ),
            )
        case AgentHarness.CLAUDE:
            from bcbench.agent.claude import get_claude_version, run_claude_code

            return AgentSelection(
                name=name,
                model=model,
                version=get_claude_version(settings) if evaluate else None,
                runner=lambda context: run_claude_code(
                    entry=context.entry,
                    model=context.model,
                    category=definition.name,
                    repo_path=context.repo_path,
                    output_dir=context.result_dir,
                    runtime=runtime,
                    settings=settings,
                    prompt=prompt(context),
                    pass_bc_credentials=pass_credentials,
                ),
            )
        case _:
            raise ValueError(f"Unsupported agent: {name}")
