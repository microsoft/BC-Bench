from pydantic import BaseModel, ConfigDict, Field

from bcbench.agent.pr_review.run_manifest import RunManifest
from bcbench.exceptions import AgentError

UNCLASSIFIED_PR_REVIEW_DEFINITION_ID = "unclassified"


class PRReviewDefinition(BaseModel):
    """A release-owned, fully validated BC PR Review configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    display_name: str
    root_model: str
    leaf_model: str
    leaf_execution: str
    max_leaf_concurrency: int = Field(ge=1)
    engine_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    copilot_cli_version: str
    bcquality_repository: str
    bcquality_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    bcquality_source_snapshot: str = Field(pattern=r"^[0-9a-f]{64}$")
    cli_timeout_minutes: int = Field(ge=0)
    minimum_severity: str
    agent_minimum_severity: str
    review_source: str

    def runtime_mismatches(
        self,
        *,
        engine_commit: str,
        copilot_cli_version: str,
        root_model: str,
        leaf_model: str,
        leaf_execution: str,
        max_leaf_concurrency: int,
        bcquality_repository: str | None = None,
        bcquality_commit: str | None = None,
        bcquality_source_snapshot: str | None = None,
        cli_timeout_minutes: int | None = None,
        minimum_severity: str | None = None,
        agent_minimum_severity: str | None = None,
        review_source: str | None = None,
    ) -> list[str]:
        expected_values = {
            "engine_commit": self.engine_commit,
            "copilot_cli_version": self.copilot_cli_version,
            "root_model": self.root_model,
            "leaf_model": self.leaf_model,
            "leaf_execution": self.leaf_execution,
            "max_leaf_concurrency": self.max_leaf_concurrency,
        }
        actual_values = {
            "engine_commit": engine_commit,
            "copilot_cli_version": copilot_cli_version,
            "root_model": root_model,
            "leaf_model": leaf_model,
            "leaf_execution": leaf_execution,
            "max_leaf_concurrency": max_leaf_concurrency,
        }
        optional_values = {
            "bcquality_repository": (bcquality_repository, self.bcquality_repository),
            "bcquality_commit": (bcquality_commit, self.bcquality_commit),
            "bcquality_source_snapshot": (bcquality_source_snapshot, self.bcquality_source_snapshot),
            "cli_timeout_minutes": (cli_timeout_minutes, self.cli_timeout_minutes),
            "minimum_severity": (minimum_severity, self.minimum_severity),
            "agent_minimum_severity": (agent_minimum_severity, self.agent_minimum_severity),
            "review_source": (review_source, self.review_source),
        }
        mismatches = [f"{name}={actual_values[name]!r} (expected {expected!r})" for name, expected in expected_values.items() if actual_values[name] != expected]
        mismatches.extend(f"{name}={actual!r} (expected {expected!r})" for name, (actual, expected) in optional_values.items() if actual is not None and actual != expected)
        return mismatches

    def mismatches_for_manifest(self, manifest: RunManifest, *, bcquality_repository: str | None) -> list[str]:
        configuration = manifest.configuration
        return self.runtime_mismatches(
            engine_commit=manifest.engine.commit or "",
            copilot_cli_version=configuration.copilot_cli_version,
            root_model=configuration.root_model,
            leaf_model=configuration.leaf_model,
            leaf_execution=configuration.leaf_execution,
            max_leaf_concurrency=configuration.max_leaf_concurrency,
            bcquality_repository=bcquality_repository,
            bcquality_commit=manifest.bcquality.commit,
            bcquality_source_snapshot=manifest.bcquality.source_snapshot,
            cli_timeout_minutes=configuration.cli_timeout_minutes,
            minimum_severity=configuration.minimum_severity,
            agent_minimum_severity=configuration.agent_minimum_severity,
            review_source=configuration.review_source,
        )


PR_REVIEW_DEFINITIONS: tuple[PRReviewDefinition, ...] = (
    PRReviewDefinition(
        id="pr-review-production-sol-luna-serial-v1",
        display_name="BC PR Review — Production / Sol / Luna / Serial v1",
        root_model="gpt-5.6-sol",
        leaf_model="gpt-5.6-luna",
        leaf_execution="serial",
        max_leaf_concurrency=4,
        engine_commit="03239afe611a3eff490002eba0e4098b48099ba3",
        copilot_cli_version="1.0.83",
        bcquality_repository="microsoft/BCQuality",
        bcquality_commit="b74967bc5b7a454eae19d6a1250199afd869f064",
        bcquality_source_snapshot="096dca9a79cc20bb42bfd0d42d317672f39270e03532c119ac7c47084323d903",
        cli_timeout_minutes=30,
        minimum_severity="Medium",
        agent_minimum_severity="Medium",
        review_source="local",
    ),
)
DEFAULT_PR_REVIEW_DEFINITION_ID = PR_REVIEW_DEFINITIONS[0].id


def get_pr_review_definition(definition_id: str) -> PRReviewDefinition:
    for definition in PR_REVIEW_DEFINITIONS:
        if definition.id == definition_id:
            return definition
    raise AgentError(f"Unknown BC PR Review definition {definition_id!r}. Register its complete immutable configuration before using it.")


def resolve_requested_pr_review_definition(definition_id: str | None) -> PRReviewDefinition | None:
    if definition_id is None or definition_id == UNCLASSIFIED_PR_REVIEW_DEFINITION_ID:
        return None
    return get_pr_review_definition(definition_id)


def validate_requested_pr_review_definition(
    definition_id: str | None,
    *,
    engine_commit: str,
    copilot_cli_version: str,
    root_model: str,
    leaf_model: str,
    leaf_execution: str,
    max_leaf_concurrency: int,
) -> PRReviewDefinition | None:
    definition = resolve_requested_pr_review_definition(definition_id)
    if definition is None:
        return None

    mismatches = definition.runtime_mismatches(
        engine_commit=engine_commit,
        copilot_cli_version=copilot_cli_version,
        root_model=root_model,
        leaf_model=leaf_model,
        leaf_execution=leaf_execution,
        max_leaf_concurrency=max_leaf_concurrency,
    )
    if mismatches:
        raise AgentError(f"Requested BC PR Review definition {definition.id!r} does not match configured inputs: {'; '.join(mismatches)}")
    return definition


def resolve_pr_review_definition(manifest: RunManifest, *, bcquality_repository: str | None) -> PRReviewDefinition | None:
    for definition in PR_REVIEW_DEFINITIONS:
        if not definition.mismatches_for_manifest(manifest, bcquality_repository=bcquality_repository):
            return definition
    return None


def validate_pr_review_definition_metadata(definition_id: str | None, definition_name: str | None) -> None:
    if definition_id is None and definition_name is None:
        return
    if definition_id is None or definition_name is None:
        raise ValueError("PR Review definition_id and definition_name must be set together.")
    definition = next((item for item in PR_REVIEW_DEFINITIONS if item.id == definition_id), None)
    if definition is None:
        raise ValueError(f"Unknown BC PR Review definition {definition_id!r}.")
    if definition_name != definition.display_name:
        raise ValueError(f"PR Review definition_name does not match registered definition {definition_id!r}.")
