"""Shared types and data structures used across BC-Bench modules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

if TYPE_CHECKING:
    from bcbench.dataset import BaseDatasetEntry
    from bcbench.evaluate.base import EvaluationPipeline
    from bcbench.results.base import BaseEvaluationResult
    from bcbench.results.leaderboard import LeaderboardAggregate
    from bcbench.results.summary import EvaluationResultSummary

__all__ = [
    "AgentHarness",
    "AgentMetrics",
    "BCalLLMBackend",
    "Checklist",
    "ChecklistAssertion",
    "ChecklistLevel",
    "CommitSha",
    "ContainerConfig",
    "EvaluationCategory",
    "EvaluationContext",
    "ExpectedOutput",
    "ExperimentConfiguration",
    "JudgeCalibrationReport",
    "PluginConfig",
    "RepoSlug",
]


type ChecklistLevel = Literal["critical", "expected", "aspirational"]


class ChecklistAssertion(TypedDict):
    text: str
    level: ChecklistLevel


class Checklist(TypedDict):
    assertions: list[ChecklistAssertion]


# Patch-style string for execution-based categories (bug-fix, test-generation),
# or an lm_checklist payload for scorer-driven categories.
type ExpectedOutput = str | Checklist

# A full git commit SHA: branches and tags move, so only a SHA pins content reproducibly
type CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{40}$")]

# A GitHub repository in "owner/repo" form
type RepoSlug = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+$")]


class AgentMetrics(BaseModel):
    """Metrics collected during agent execution.

    Separates runtime execution data from experiment configuration.
    """

    model_config = ConfigDict(frozen=True)

    # Total execution time in seconds
    execution_time: float | None = None
    llm_duration: float | None = None

    turn_count: int | None = None

    # Token usage from LLM calls
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    # Tool usage statistics from agent logs
    tool_usage: dict[str, int] | None = None


class ExperimentConfiguration(BaseModel):
    """Configuration for agent experiment execution.

    This encapsulates experiment-related configuration that agents use,
    making it easier to add new configuration options without changing function signatures.
    """

    model_config = ConfigDict(frozen=True)

    # MCP server names used in experiment (if any)
    mcp_servers: list[str] | None = None

    # Whether the AL LSP server was enabled for this experiment
    al_lsp_enabled: bool = False

    # Custom instructions enabled in experiment
    custom_instructions: bool = False

    # Skills enabled in experiment
    skills_enabled: bool = False

    # Custom agent name used in experiment (if any)
    custom_agent: str | None = None

    # Plugins loaded for this experiment: "<name>@<revision>" (github) or "<name>@local"
    plugins: list[str] | None = None

    def is_empty(self) -> bool:
        """Check if this configuration has all default/empty values.

        An empty configuration means no special experiment settings were used.
        This is useful for comparing with None (no experiment) vs default experiment.
        """
        return self.mcp_servers is None and self.al_lsp_enabled is False and self.custom_instructions is False and self.skills_enabled is False and self.custom_agent is None and self.plugins is None


# Where an agent plugin comes from: local, or cloned from GitHub
type PluginSource = Literal["local", "github"]


class PluginConfig(BaseModel):
    """A single `plugins:` entry in the agent config."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    source: PluginSource
    path: str
    enabled: bool = False
    # Grant the agent filesystem access to this plugin's tree via Copilot `--add-dir`.
    # Off by default so enabling a plugin does not also widen the agent's sandbox access.
    # This is a (hopefully temporary) accommodation for BCQuality, whose skill reads its own
    # knowledge files at runtime; the long-term fix is to serve that content via skills / an MCP server.
    grant_dir_access: bool = False
    # github only
    repo: RepoSlug | None = None
    revision: CommitSha | None = None

    @property
    def record(self) -> str:
        """How the plugin is recorded on a result's `ExperimentConfiguration`."""
        return f"{self.name}@{self.revision or self.source}"

    @model_validator(mode="after")
    def validate_source_fields(self) -> PluginConfig:
        github_fields = {"repo": self.repo, "revision": self.revision}
        match self.source:
            case "github":
                missing = [key for key, value in github_fields.items() if not value]
                if missing:
                    raise ValueError(f"Plugin '{self.name}': source 'github' requires {missing}")
            case "local":
                unexpected = [key for key, value in github_fields.items() if value]
                if unexpected:
                    raise ValueError(f"Plugin '{self.name}': source 'local' does not take {unexpected}")
                if not Path(self.path).expanduser().is_absolute():
                    raise ValueError(f"Plugin '{self.name}': source 'local' requires an absolute 'path', got {self.path!r}")
        return self


class AgentHarness(StrEnum):
    """Agents that can be evaluated, and the metrics each of them is able to report."""

    COPILOT = "GitHub Copilot"
    CLAUDE = "Claude Code"
    BCAL = "BCal"
    MOCK = "mock-agent"

    @property
    def expected_metrics(self) -> frozenset[str]:
        """Metrics this agent should always report.

        Only these are warned about when missing, so agents that never collect a metric don't emit a warning for every single instance of a run.
        """

        match self:
            case AgentHarness.COPILOT | AgentHarness.CLAUDE | AgentHarness.MOCK:
                expected = AgentMetrics(
                    execution_time=None,
                    llm_duration=None,
                    turn_count=None,
                    prompt_tokens=None,
                    completion_tokens=None,
                    tool_usage=None,
                )
            case AgentHarness.BCAL:
                expected = AgentMetrics(execution_time=None)
            case _:
                raise ValueError(f"Unknown AgentHarness: {self}")

        return frozenset(expected.model_fields_set)

    @property
    def instruction_filename(self) -> str:
        match self:
            case AgentHarness.COPILOT:
                return "copilot-instructions.md"
            case AgentHarness.CLAUDE:
                return "CLAUDE.md"
            case _:
                raise ValueError(f"{self.value} does not support repository instructions")

    def get_target_dir(self, repo_path: Path) -> Path:
        match self:
            case AgentHarness.COPILOT:
                return repo_path / ".github"
            case AgentHarness.CLAUDE:
                return repo_path / ".claude"
            case _:
                raise ValueError(f"{self.value} does not support repository setup")


class EvaluationCategory(StrEnum):
    BUG_FIX = "bug-fix"
    TEST_GENERATION = "test-generation"
    CODE_REVIEW = "code-review"
    NL2AL = "nl2al"
    # Implement an approved extensibility request (add an event/extension point) as an AL code change.
    # The sibling ext-advisor category is planned but not yet implemented.
    EXT_REQUEST_IMPLEMENT = "extensibility-request-implement"
    # Triage a single extensibility request: emit managed labels, an advisory comment, and open/closed state.
    EXT_REQUEST_TRIAGE = "extensibility-request-triage"

    @property
    def dataset_path(self) -> Path:
        from bcbench.config import get_config

        match self:
            case EvaluationCategory.BUG_FIX:
                return get_config().paths.dataset_dir / "bcbench.jsonl"
            case EvaluationCategory.TEST_GENERATION:
                return get_config().paths.dataset_dir / "bcbench.jsonl"
            case EvaluationCategory.CODE_REVIEW:
                return get_config().paths.dataset_dir / "codereview.jsonl"
            case EvaluationCategory.NL2AL:
                return get_config().paths.dataset_dir / "nl2al.jsonl"
            case EvaluationCategory.EXT_REQUEST_IMPLEMENT:
                return get_config().paths.dataset_dir / "extensibility_request_implement.jsonl"
            case EvaluationCategory.EXT_REQUEST_TRIAGE:
                return get_config().paths.dataset_dir / "extensibility_request_triage.jsonl"

        raise ValueError(f"Unknown evaluation category: {self}")

    @property
    def entry_class(self) -> type[BaseDatasetEntry]:
        from bcbench.dataset import BugFixEntry, CodeReviewEntry, ExtRequestImplementEntry, ExtRequestTriageEntry, NL2ALEntry, TestGenEntry

        match self:
            case EvaluationCategory.BUG_FIX:
                return BugFixEntry
            case EvaluationCategory.TEST_GENERATION:
                return TestGenEntry
            case EvaluationCategory.CODE_REVIEW:
                return CodeReviewEntry
            case EvaluationCategory.NL2AL:
                return NL2ALEntry
            case EvaluationCategory.EXT_REQUEST_IMPLEMENT:
                return ExtRequestImplementEntry
            case EvaluationCategory.EXT_REQUEST_TRIAGE:
                return ExtRequestTriageEntry

        raise ValueError(f"Unknown evaluation category: {self}")

    @property
    def result_class(self) -> type[BaseEvaluationResult]:
        from bcbench.results.base import JudgeBasedEvaluationResult
        from bcbench.results.bugfix import BugFixResult
        from bcbench.results.codereview import CodeReviewResult
        from bcbench.results.testgeneration import TestGenerationResult

        match self:
            case EvaluationCategory.BUG_FIX:
                return BugFixResult
            case EvaluationCategory.TEST_GENERATION:
                return TestGenerationResult
            case EvaluationCategory.CODE_REVIEW:
                return CodeReviewResult
            case EvaluationCategory.NL2AL:
                return JudgeBasedEvaluationResult
            case EvaluationCategory.EXT_REQUEST_IMPLEMENT:
                return JudgeBasedEvaluationResult
            case EvaluationCategory.EXT_REQUEST_TRIAGE:
                return JudgeBasedEvaluationResult

        raise ValueError(f"Unknown evaluation category: {self}")

    @property
    def summary_class(self) -> type[EvaluationResultSummary]:
        """Returns the EvaluationResultSummary subclass for this category."""
        from bcbench.results.codereview import CodeReviewResultSummary
        from bcbench.results.summary import ExecutionBasedEvaluationResultSummary, JudgeBasedEvaluationResultSummary

        match self:
            case EvaluationCategory.BUG_FIX:
                return ExecutionBasedEvaluationResultSummary
            case EvaluationCategory.TEST_GENERATION:
                return ExecutionBasedEvaluationResultSummary
            case EvaluationCategory.CODE_REVIEW:
                return CodeReviewResultSummary
            case EvaluationCategory.NL2AL:
                return JudgeBasedEvaluationResultSummary
            case EvaluationCategory.EXT_REQUEST_IMPLEMENT:
                return JudgeBasedEvaluationResultSummary
            case EvaluationCategory.EXT_REQUEST_TRIAGE:
                return JudgeBasedEvaluationResultSummary

        raise ValueError(f"Unknown evaluation category: {self}")

    @property
    def aggregate_class(self) -> type[LeaderboardAggregate]:
        """Returns the LeaderboardAggregate subclass for this category, used for aggregating multiple runs on the same benchmark/model/agent combination."""
        from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate, ExecutionBasedLeaderboardAggregate, JudgeBasedLeaderboardAggregate

        match self:
            case EvaluationCategory.BUG_FIX:
                return ExecutionBasedLeaderboardAggregate
            case EvaluationCategory.TEST_GENERATION:
                return ExecutionBasedLeaderboardAggregate
            case EvaluationCategory.CODE_REVIEW:
                return CodeReviewLeaderboardAggregate
            case EvaluationCategory.NL2AL:
                return JudgeBasedLeaderboardAggregate
            case EvaluationCategory.EXT_REQUEST_IMPLEMENT:
                return JudgeBasedLeaderboardAggregate
            case EvaluationCategory.EXT_REQUEST_TRIAGE:
                return JudgeBasedLeaderboardAggregate

        raise ValueError(f"Unknown evaluation category: {self}")

    @property
    def pipeline(self) -> EvaluationPipeline:
        from bcbench.evaluate import BugFixPipeline, CodeReviewPipeline, ExtRequestImplementPipeline, ExtRequestTriagePipeline, NL2ALPipeline, TestGenerationPipeline

        match self:
            case EvaluationCategory.BUG_FIX:
                return BugFixPipeline()
            case EvaluationCategory.TEST_GENERATION:
                return TestGenerationPipeline()
            case EvaluationCategory.CODE_REVIEW:
                return CodeReviewPipeline()
            case EvaluationCategory.NL2AL:
                return NL2ALPipeline()
            case EvaluationCategory.EXT_REQUEST_IMPLEMENT:
                return ExtRequestImplementPipeline()
            case EvaluationCategory.EXT_REQUEST_TRIAGE:
                return ExtRequestTriagePipeline()

        raise ValueError(f"Unknown evaluation category: {self}")

    @property
    def evaluators(self) -> list[str]:
        """
        Names of bc-eval evaluators (from evaluator/scores.py) to run for this category.

        Used for uploading evaluation results to long term storage.
        """
        match self:
            case EvaluationCategory.BUG_FIX:
                return ["resolution_rate", "build_rate"]
            case EvaluationCategory.TEST_GENERATION:
                return ["resolution_rate", "build_rate", "pre_patch_failed_rate", "post_patch_passed_rate"]
            case EvaluationCategory.CODE_REVIEW:
                return ["precision_score", "recall_score", "f1_score", "valid_review_output"]
            case EvaluationCategory.NL2AL:
                return ["lm_checklist"]
            case EvaluationCategory.EXT_REQUEST_IMPLEMENT:
                return ["lm_checklist"]
            case EvaluationCategory.EXT_REQUEST_TRIAGE:
                return ["lm_checklist"]

        raise ValueError(f"Unknown evaluation category: {self}")

    @property
    def core_score(self) -> str:
        """Name of the evaluator whose value is considered as CoreScore, required by bc-eval."""
        match self:
            case EvaluationCategory.BUG_FIX | EvaluationCategory.TEST_GENERATION:
                return "ResolutionRate"
            case EvaluationCategory.CODE_REVIEW:
                return "F1Score"
            case EvaluationCategory.NL2AL | EvaluationCategory.EXT_REQUEST_IMPLEMENT | EvaluationCategory.EXT_REQUEST_TRIAGE:
                return "test_passed"

        raise ValueError(f"Unknown evaluation category: {self}")

    @property
    def requires_container(self) -> bool:
        """Whether evaluating this category builds/runs AL code and therefore needs a BC container."""
        match self:
            case EvaluationCategory.BUG_FIX | EvaluationCategory.TEST_GENERATION:
                return True
            case EvaluationCategory.CODE_REVIEW | EvaluationCategory.NL2AL | EvaluationCategory.EXT_REQUEST_IMPLEMENT | EvaluationCategory.EXT_REQUEST_TRIAGE:
                return False

        raise ValueError(f"Unknown evaluation category: {self}")

    @property
    def requires_repo(self) -> bool:
        """Whether evaluating this category works on a cloned dataset repository."""
        from bcbench.dataset import RepoGroundedEntry

        return issubclass(self.entry_class, RepoGroundedEntry)

    @property
    def runner(self) -> str:
        """GitHub Actions runner label for evaluating this category.

        Only categories that require building BaseApp needs self-hosted runners.
        """
        match self:
            case EvaluationCategory.BUG_FIX | EvaluationCategory.TEST_GENERATION:
                return "GitHub-BCBench"
            case EvaluationCategory.CODE_REVIEW | EvaluationCategory.EXT_REQUEST_IMPLEMENT | EvaluationCategory.EXT_REQUEST_TRIAGE:
                return "ubuntu-latest"
            case EvaluationCategory.NL2AL:
                return "windows-latest"

        raise ValueError(f"Unknown evaluation category: {self}")


@dataclass(frozen=True)
class ContainerConfig:
    name: str
    username: str
    password: str


@dataclass(frozen=True)
class JudgeCalibrationReport:
    total: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    accuracy: float  # (TP + TN) / total: share of judge verdicts that match the human label, not F1
    misclassified_notes: list[str]


@dataclass
class EvaluationContext[E: BaseDatasetEntry]:
    """Context object containing all configuration for evaluation pipeline.

    This bundles related configuration together to avoid long parameter lists
    and makes it easier to add new configuration options in the future.
    """

    # Core configuration
    entry: E
    repo_path: Path
    result_dir: Path

    # Agent metadata
    agent_name: AgentHarness
    model: str

    # Evaluation category
    category: EvaluationCategory

    # BC Container configuration (optional — not all categories require a container)
    container: ContainerConfig | None = None

    # Agent execution metrics
    metrics: AgentMetrics | None = None

    # Experiment configuration
    experiment: ExperimentConfiguration | None = None

    def get_container(self) -> ContainerConfig:
        if self.container is None:
            raise ValueError(f"Container configuration is required for {self.category.value} evaluation")
        return self.container


class BCalLLMBackend(StrEnum):
    AZURE_OPENAI = "azure-openai"
    EXTERNAL_COMMAND = "external-command"
