from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

type CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{40}$")]
type RepoSlug = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+$")]
type PluginSource = Literal["local", "github"]


class DatasetEntry(Protocol):
    instance_id: str
    project_paths: list[str]
    environment_setup_version: str

    def get_task(self) -> str: ...

    def extract_project_name(self) -> str: ...


class AgentMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["generic"] = "generic"
    execution_time: float | None = None
    llm_duration: float | None = None
    ai_credits: float | None = None
    turn_count: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    tool_usage: dict[str, int] | None = None


@dataclass(frozen=True)
class AgentMetricsContract:
    metrics_type: type[AgentMetrics]
    required_fields: frozenset[str] = frozenset()

    def validate(self, metrics: AgentMetrics | None) -> tuple[str, ...]:
        if metrics is None:
            return tuple(sorted(self.required_fields))
        if not isinstance(metrics, self.metrics_type):
            raise TypeError(f"Expected {self.metrics_type.__name__}, got {type(metrics).__name__}")
        return tuple(sorted(name for name in self.required_fields if getattr(metrics, name) is None))


class ExperimentConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    mcp_servers: list[str] | None = None
    al_lsp_enabled: bool = False
    custom_instructions: bool = False
    skills_enabled: bool = False
    custom_agent: str | None = None
    plugins: list[str] | None = None

    def is_empty(self) -> bool:
        return self.mcp_servers is None and not self.al_lsp_enabled and not self.custom_instructions and not self.skills_enabled and self.custom_agent is None and self.plugins is None


@dataclass(frozen=True)
class AgentExecution:
    metrics: AgentMetrics | None
    experiment: ExperimentConfiguration
    timed_out: bool = False


class PluginConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    source: PluginSource
    path: str
    enabled: bool = False
    grant_dir_access: bool = False
    repo: RepoSlug | None = None
    revision: CommitSha | None = None

    @property
    def record(self) -> str:
        return f"{self.name}@{self.revision or self.source}"

    @model_validator(mode="after")
    def validate_source_fields(self) -> PluginConfig:
        github_fields = {"repo": self.repo, "revision": self.revision}
        match self.source:
            case "github":
                if missing := [key for key, value in github_fields.items() if not value]:
                    raise ValueError(f"Plugin '{self.name}': source 'github' requires {missing}")
            case "local":
                if unexpected := [key for key, value in github_fields.items() if value]:
                    raise ValueError(f"Plugin '{self.name}': source 'local' does not take {unexpected}")
                if not Path(self.path).expanduser().is_absolute():
                    raise ValueError(f"Plugin '{self.name}': source 'local' requires an absolute 'path', got {self.path!r}")
        return self


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
        company = self.company.strip()
        if not name:
            raise ValueError("Container name must not be empty")
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
