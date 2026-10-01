"""Shared types and data structures used across BC-Bench modules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, TypedDict

from bcbench_core.types import AgentMetrics, AgentMetricsContract
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

if TYPE_CHECKING:
    from bcbench.categories.base import CategoryDefinition
    from bcbench.dataset import BaseDatasetEntry
    from bcbench.evaluate.base import EvaluationPipeline
    from bcbench.results.base import BaseEvaluationResult
    from bcbench.results.leaderboard import LeaderboardAggregate
    from bcbench.results.summary import EvaluationResultSummary

__all__ = [
    "AgentHarness",
    "AgentMetrics",
    "AgentMetricsContract",
    "AnyAgentMetrics",
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
    "PRReviewMetrics",
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
# Reproducible only when fetchable from the recorded remote
type CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{40}$")]

# A GitHub repository in "owner/repo" form
type RepoSlug = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+$")]


class PRReviewMetrics(AgentMetrics):
    kind: Literal["pr-review"] = "pr-review"

    cached_tokens: int | None = Field(default=None, ge=0)
    cache_creation_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    api_calls: int | None = Field(default=None, ge=0)
    failed_api_calls: int | None = Field(default=None, ge=0)
    usage_api_calls: int | None = Field(default=None, ge=0)
    usage_complete: bool | None = None
    malformed_records: int | None = Field(default=None, ge=0)
    copilot_cli_version: str | None = None


type AnyAgentMetrics = Annotated[AgentMetrics | PRReviewMetrics, Field(discriminator="kind")]


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
    PR_REVIEW = "BC PR Review"

    @property
    def metrics_contract(self) -> AgentMetricsContract:
        """Metrics schema and fields this harness must populate.

        The model defines which fields may be reported. The required subset
        controls which missing values produce warnings.
        """

        match self:
            case AgentHarness.COPILOT:
                metrics = AgentMetrics(
                    execution_time=None,
                    llm_duration=None,
                    ai_credits=None,
                    turn_count=None,
                    tool_usage=None,
                )
            case AgentHarness.CLAUDE | AgentHarness.MOCK:
                metrics = AgentMetrics(
                    execution_time=None,
                    llm_duration=None,
                    turn_count=None,
                    prompt_tokens=None,
                    completion_tokens=None,
                    tool_usage=None,
                )
            case AgentHarness.BCAL:
                metrics = AgentMetrics(execution_time=None)
            case AgentHarness.PR_REVIEW:
                metrics = PRReviewMetrics(
                    execution_time=None,
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    ai_credits=None,
                )
            case _:
                raise ValueError(f"Unknown AgentHarness: {self}")

        return AgentMetricsContract(type(metrics), frozenset(metrics.model_fields_set))

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
    DATA_QUERY = "data-query"
    # Single-shot proxy for the interactive advisor: classify, assess feasibility, and draft an issue.
    EXT_REQUEST_ADVISOR = "extensibility-request-advisor"
    # Implement an approved extensibility request (add an event/extension point) as an AL code change.
    EXT_REQUEST_IMPLEMENT = "extensibility-request-implement"
    # Triage a single extensibility request: emit managed labels, an advisory comment, and open/closed state.
    EXT_REQUEST_TRIAGE = "extensibility-request-triage"

    @property
    def definition(self) -> CategoryDefinition:
        from bcbench.categories import categories

        if self.value not in categories:
            raise ValueError(f"Evaluation category is not registered: {self.value}")
        return categories[self.value]

    @property
    def dataset_path(self) -> Path:
        from bcbench.config import get_config

        return get_config().paths.dataset_dir / self.definition.dataset_filename

    @property
    def entry_class(self) -> type[BaseDatasetEntry]:
        return self.definition.entry_class

    @property
    def result_class(self) -> type[BaseEvaluationResult]:
        return self.definition.result_class

    @property
    def summary_class(self) -> type[EvaluationResultSummary]:
        return self.definition.summary_class

    @property
    def aggregate_class(self) -> type[LeaderboardAggregate]:
        return self.definition.aggregate_class

    @property
    def pipeline(self) -> EvaluationPipeline:
        return self.definition.pipeline_factory()

    @property
    def judge_model(self) -> str | None:
        from bcbench.config import get_config

        return self.definition.judge_model(get_config().judge)

    @property
    def evaluators(self) -> list[str]:
        return list(self.definition.evaluators)

    @property
    def core_score(self) -> str:
        return self.definition.core_score

    @property
    def requires_container(self) -> bool:
        return self.definition.requires_container

    @property
    def pass_on_bc_container_credentials(self) -> bool:
        return self.definition.pass_on_bc_container_credentials

    @property
    def requires_repo(self) -> bool:
        """Whether evaluating this category works on a cloned dataset repository."""
        from bcbench.dataset import RepoGroundedEntry

        return issubclass(self.entry_class, RepoGroundedEntry)

    @property
    def runner(self) -> str:
        return self.definition.runner


@dataclass(frozen=True)
class ContainerConfig:
    name: str
    username: str
    password: str
    company: str
    server_url: str = ""
    server_instance: str = ""
    mcp_url: str | None = None

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("Container name must not be empty")
        company = self.company.strip()
        if not company:
            raise ValueError("Company must not be empty")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "company", company)


@dataclass(frozen=True)
class AgentRuntimeConfig:
    container: ContainerConfig
    al_mcp: bool = False
    al_lsp: bool = False
    bc_mcp: bool = False

    def __post_init__(self) -> None:
        if self.bc_mcp and not self.container.mcp_url:
            raise ValueError("An MCP URL is required when BC MCP is enabled")


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

    agent_version: str | None = None

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
