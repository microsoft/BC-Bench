from pydantic import BaseModel, ConfigDict, JsonValue


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

    # Versioned, non-secret execution identity supplied by the harness.
    execution: dict[str, JsonValue] | None = None

    def is_empty(self) -> bool:
        """Check if this configuration has all default/empty values.

        An empty configuration means no special experiment settings were used.
        This is useful for comparing with None (no experiment) vs default experiment.
        """
        return (
            self.mcp_servers is None
            and self.al_lsp_enabled is False
            and self.custom_instructions is False
            and self.skills_enabled is False
            and self.custom_agent is None
            and self.plugins is None
            and self.execution is None
        )
