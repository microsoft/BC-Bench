# BC-Bench application boundaries (goal 2)

**Status: proposal only.** No production changes or further core extraction. This
plan complements the small core PRs #914–#927, not the previous all-at-once
`copilot/extract-bcbench-core-framework` migration. Each numbered step below lands
and passes verification before the next starts.

## 1. Current state

### Ambient configuration

[Config][config] loads dotenv, discovers the git root, reads shared YAML, and
caches paths, timeouts, patterns, judge models and GitHub environment values
(lines 19–32, 148–164, 178–222). Frozen configuration is useful; global discovery
by its consumers is not.

The current checkout has **27 calling modules**: the CLI, six command modules,
and **20 runtime/domain modules**. Of the latter, **17 capture `_config` during
import**; the other three query it during execution:

| Consumers outside CLI/commands | Values and coupling |
| --- | --- |
| [Dataset entries][entries] | Instance-ID schema pattern, problem-statement paths and names; even model construction depends on configuration. |
| [BC operations][bcops], [git operations][gitops], [instruction operations][instructions] | Script/cache paths, build/query/test timeouts, patch suffix, customization and problem-statement locations. |
| [Copilot][copilot], [Claude][claude], [BCal][bcal], [PR Review][prreview] agents | Execution timeouts; BCal output layout; PR Review engine fallback location. |
| [Prompt renderer][prompt], [plugin preparation][plugins] | Image-path rewriting, plugin checkout/manifest locations. |
| [Base pipeline][pipeline], [test-generation pipeline][testgen], [review judge][judge], [judge calibration][calibration] | Result suffix, baseline test-patch location, judge model, timeout and response filename. |
| [GitHub helpers][github], [result display][display], [category enum][types] | Runtime reads: Actions flags/summary destination; dataset paths and judge models. |
| [GitHub collection][collectgh], [patch collection helpers][patchutils], [contamination runner][contamination] | Dataset/problem locations, patch names and identification timeout. |

Additionally, [CLI][cli] initializes configuration at import (line 18); commands
`collect`, `contamination`, `evaluate`, `redteam`, `result`, and `run` capture it
for option defaults. [CLI options][options] already resolve env-backed options
into validated `ContainerConfig`/`AgentRuntimeConfig`: retain this useful seam.

Direct environment access outside the CLI is not limited to `get_config()`:

- [GitHub helpers][github]: `GITHUB_OUTPUT`; the contamination command also
  reads `GITHUB_STEP_SUMMARY`, duplicating `EnvironmentConfig`.
- [Agent environment][agentenv], [PR Review][prreview], [NL2AL pipeline][nl2al]:
  copy/filter the parent environment or add git identity overrides.
- [BCQuality analysis][analysis]: optional `BCQUALITY_ROOT` resolution.
- [BCal CAPI bridge][bridge]: `CAPI_CERT_FILE`, tenant and client values.
  This is a **separate process entry point**, not configuration to move into
  ordinary pipeline code.
- Indirect discovery: [redteam][redteam] constructs `DefaultAzureCredential`
  internally and loads NL2AL entries through the enum; agent YAML is loaded by
  instruction operations. Both should receive already resolved inputs.

### Category service locator

[EvaluationCategory][types] (lines 271–553) contains eight identifiers and
**thirteen properties**. Lazy imports avoid immediate cycles but let domain
objects discover concrete runtime implementations.

| Mapping | Existing consumers |
| --- | --- |
| `dataset_path`, `entry_class`, `pipeline` | [Run][run] and [evaluate][evaluate] commands; [dataset command][datasetcommand]; [redteam][redteam] and [bceval export][export] also load entries. `pipeline` creates a fresh instance per access. |
| `result_class` | [Base pipeline][pipeline]: timeout result; [result models][results]: JSON decoding. |
| `summary_class`, `aggregate_class` | [Summary][summary] and [leaderboard][leaderboard] factories/decoders; [result command][resultcommand] rebuilds aggregates. |
| `judge_model`, `evaluators`, `core_score` | [Category command][categorycommand]: workflow outputs; judged [result models][results] (including [code-review factories][reviewresults]): live result metadata and an ambient-config fallback for old timeout payloads. |
| `requires_container`, `requires_repo`, `runner` | CLI runtime validation and category workflow outputs; repository requirement derives from `RepoGroundedEntry`. |
| `pass_on_bc_container_credentials` | Copilot/Claude child-environment filtering. Only data-query withholds credentials. |

The entry/pipeline/result triples are:

| Category | Entry / pipeline | Result |
| --- | --- | --- |
| bug-fix | `BugFixEntry` / `BugFixPipeline` | `BugFixResult` |
| test-generation | `TestGenEntry` / `TestGenerationPipeline` | `TestGenerationResult` |
| code-review | `CodeReviewEntry` / `CodeReviewPipeline` | `CodeReviewResult` |
| data-query | `DataQueryEntry` / `DataQueryPipeline` | `ExecutionBasedEvaluationResult` |
| nl2al | `NL2ALEntry` / `NL2ALPipeline` | `JudgeBasedEvaluationResult` |
| extensibility-request-advisor | `ExtRequestAdvisorEntry` / `ExtRequestAdvisorPipeline` | `JudgeBasedEvaluationResult` |
| extensibility-request-implement | `ExtRequestImplementEntry` / `ExtRequestImplementPipeline` | `JudgeBasedEvaluationResult` |
| extensibility-request-triage | `ExtRequestTriageEntry` / `ExtRequestTriagePipeline` | `JudgeBasedEvaluationResult` |

Bug-fix/test-generation share `bcbench.jsonl`; other categories have separate
files. Summary/aggregate types follow execution-based, code-review, or
checklist-judged result families. Prompt dispatch is a separate string-key lookup
in [prompt rendering][prompt] (`<category>-template`), with test-generation-only
input-mode logic. Scoring is already partly category-owned: pipelines compute
execution outcomes/review matching, result types expose metrics, and checklist
grading runs **downstream**, not in local pipelines.

## 2. Target design

### Direction and ownership

```text
CLI / commands (configuration loading, category + harness selection)
    -> app category definitions (explicit, statically imported composition)
    -> concrete pipelines / agent adapters / result-processing services
    -> operations and bcbench-core

All of these may depend on pure entry/result/context/identity models.
Models never depend on category composition, pipelines, config loaders or agents.
```

Keep `EvaluationCategory` as a string enum for CLI choices and serialized
identity, **without service properties**. Keep existing entry, pipeline and
result implementations in place. Add a small application composition package at
`/home/runner/work/BC-Bench/BC-Bench/src/bcbench/categories/`, one module per
category, plus a contracts module. It selects existing implementations; it is
not a runtime registry available to domain objects. Sharing result families,
workspace helpers and datasets remains allowed.

### Typed extension points

Proposed signatures below use existing model types. Only `EvaluationPipeline`
gains a result parameter; `AgentRunner[E]` and `EvaluationContext[E]` retain
their existing roles.

```python
@dataclass(frozen=True)
class UnjudgedScore:
    evaluators: tuple[str, ...]
    core_score: str

@dataclass(frozen=True)
class JudgedScore:
    evaluators: tuple[str, ...]
    core_score: str
    kind: Literal["review-matching", "downstream-checklist"]
    model: str

type ScorePolicy = UnjudgedScore | JudgedScore

@dataclass(frozen=True)
class Capabilities:
    container: Literal["required", "optional"]
    agent_credentials: Literal["forward", "withhold"]
    runner: Literal["GitHub-BCBench", "ubuntu-latest", "windows-latest"]

@dataclass(frozen=True)
class CategoryDefinition[E: BaseDatasetEntry, R: BaseEvaluationResult]:
    name: EvaluationCategory
    dataset_file: str
    entry_type: type[E]
    result_type: type[R]
    summary_type: type[EvaluationResultSummary]
    aggregate_type: type[LeaderboardAggregate]
    prepare_workspace: Callable[[E, Path], None]
    make_pipeline: Callable[[], EvaluationPipeline[E, R]]
    render_prompt: Callable[[E, Path, bool], str]
    score: ScorePolicy
    capabilities: Capabilities

# Existing base pipeline, extended rather than replaced:
class EvaluationPipeline[E: BaseDatasetEntry, R: BaseEvaluationResult](ABC):
    def __init__(
        self, *, timeout_result: Callable[[EvaluationContext[E]], R],
        result_suffix: str,
    ) -> None: ...
    def execute(self, context: EvaluationContext[E], runner: AgentRunner[E]) -> None: ...
    def save_result(self, context: EvaluationContext[E], result: R) -> None: ...

def evaluate_one[E: BaseDatasetEntry, R: BaseEvaluationResult](
    definition: CategoryDefinition[E, R], *, dataset_path: Path,
    entry_id: str, runner: AgentRunner[E], repo_path: Path, result_dir: Path,
    agent_name: AgentHarness, model: str, agent_version: str | None,
) -> None: ...
```

Every field has a current consumer: dataset commands need the entry type;
`run` needs workspace preparation without evaluation/container setup; `evaluate`
needs the pipeline factory; agent adapters need the prompt and credential
policy; result processing needs the three model classes; workflow commands
need scoring and capabilities. No new scoring engine or general service
protocol is needed. Factories capture **explicitly supplied** settings, not
`get_config()`. Prompt closures capture validated YAML options and preserve the
sandboxed renderer; test-generation owns its input-mode interpretation.

`E` ties loading, preparation, prompts and runner calls together; `R` ties
pipeline saving and timeout construction together. Composition factories return
concrete specializations, e.g. `CategoryDefinition[BugFixEntry, BugFixResult]`.
Use exhaustive CLI dispatch to these factories and a generic helper inside each
typed branch. Do not erase this relationship into `dict[EvaluationCategory,
CategoryDefinition[BaseDatasetEntry, BaseEvaluationResult]]` or use `Any`/casts
to assemble mismatched components. The selected definition supplies the context's
category identity; it is not separately chosen by the helper.
Derive repository requirements from `issubclass(definition.entry_type,
RepoGroundedEntry)` when emitting workflow metadata; do not introduce an
independent flag that can disagree with the entry schema.

Factor each existing `setup_workspace` implementation into one category-owned
function with its operation settings bound explicitly. Both `prepare_workspace`
and the pipeline delegate to it; do not duplicate workspace logic or construct
an evaluation pipeline requiring a container just to run workspace preparation.

Result-processing services receive projected mappings of category IDs to result,
summary and aggregate **model classes**, supplied by composition. Move
polymorphic decoding/group dispatch out of model classmethods into those
services. They do not receive pipeline factories or look up a global category
catalog. Concrete models keep validation, metric calculations and serialization.
Export receives loaded entries and benchmark version instead of discovering the
dataset. Judged result factories receive a required `judge_model: str`, including
timeouts; validators never consult current configuration.

### Configuration flow

1. A CLI `main()` loads dotenv/configuration, then calls
   `create_app(config: Config) -> typer.Typer`. Command-group factories receive
   that value and **define the decorated command functions inside the factory**,
   so Python binds parameter defaults to that supplied config. Registering the
   existing import-time functions would not change their captured defaults.
   Preserve the same concrete defaults as today.
   Loading, logging setup and optional redteam registration stay at entry points;
   importing model/runtime modules performs no configuration discovery.
2. Commands resolve CLI/env overrides, load the selected harness YAML, snapshot
   the child-process environment, and construct category definitions and agent
   closures. Keep the full `Config` at composition; pass existing slices or
   individual keyword arguments to consumers. Introduce a frozen settings
   record only where a real operation family needs several related values.
3. Execution-category factories require a validated, non-optional
   `ContainerConfig` **for evaluation**; `run` uses `prepare_workspace` without
   this requirement. Judge factories require the selected model and budget.
   Pipelines receive these dependencies through constructors; agents through
   bound `AgentRunner[E]` closures. Context holds task/run state, not a config
   singleton, services bag or callable category registry.
4. Environment transformation becomes pure:
   `agent_subprocess_env(parent: Mapping[str, str], ..., pass_bc_credentials: bool)`.
   PR Review's BCQuality filtering and NL2AL git overrides likewise accept the
   snapshot. GitHub writers receive destination paths/flags. The bridge's
   `main()` resolves certificate inputs and passes them to its helpers; redteam
   receives a credential object created by its command.

Separate schema invariants (instance-ID regex, fixed suffixes) from deployment
settings. Preserve their current values as pure app constants when they are not
actually configurable; inject paths, budgets and customization inputs. Do not
make Pydantic schema creation depend on a run's configuration.

## 3. Landing sequence

Each row is a PR, except explicitly repeated rows, which are **one PR per named
consumer/category**, not a batch migration. Earlier PRs retain working legacy
call paths for untouched consumers; temporary forwarding is removed at the end,
not maintained for backward compatibility. No step changes core files.

Verification for implementation PRs: existing `uv run ruff check`, `uv run ruff
format --check`, `uv run ty check` and focused `uv run pytest` on touched files,
from `/home/runner/work/BC-Bench/BC-Bench`. Add assertions to the existing tests
named below; no new test framework. Run the app suite at the final gate.

| PR | Scope and files touched | Verification / landing gate |
| --- | --- | --- |
| 1 | CLI bootstrap seam: [CLI][cli], [config][config], [project entry point][project]. Add `main`/`create_app`; keep legacy groups working, loading the singleton before importing them until their consumers migrate. | Existing `test_cli_commands.py`, `test_config.py`; explicit config construction, option/env precedence, help and optional-redteam behavior. Do not yet claim all imports are config-free. |
| 2, repeat per group | Convert [command groups][commands] `run`, `evaluate`, `result`, `collect`, `contamination`, `redteam` to factories with injected config; adjust CLI registration and only that group's callers/tests. | CLI tests plus `test_category_command.py`, `test_redteam.py`, or the relevant collection/contamination tests; supplied config controls defaults, rather than import order. |
| 3 | Pure dataset boundary: [entries][entries], its task-reading callers in [prompt][prompt], [instructions][instructions], [export][export]. Make schema regex a constant; pass problem-statement root/names when reading tasks. No pipeline/scoring changes. | `test_dataset_integrity.py`, `test_get_task.py`, `test_copilot_prompt.py`, `test_custom_instructions.py`, `test_result_writer.py`; unchanged task text/image locations and validation errors. |
| 4, repeat per family | Explicit leaf operation settings: [git operations][gitops], then [BC operations][bcops], then [instruction operations][instructions] with [plugins][plugins]. Each PR includes that family's direct callers and corresponding command composition. Temporary adapters may use the singleton only for not-yet-migrated callers; remove each when its last caller migrates. | `test_git_operations.py`; `test_bc_artifacts.py`, `test_ps_templates.py`, `test_setup_operations.py`; then customization/plugin tests. Compare subprocess arguments, script/cache paths, timeouts and copied files. |
| 5 | Explicit reporting inputs: [GitHub helpers][github], [display][display], calling commands and pipeline group-log sites. | `test_category_command.py`, `test_evaluation_summary.py`, `test_pr_review_metrics_reporting.py`, CLI tests; identical output keys, group markers and summary text. Add tests for absent destinations/no-op outside Actions. |
| 6, repeat per harness | [Copilot][copilot], then [Claude][claude], then [BCal][bcal], then [PR Review][prreview], their command composition and [environment helper][agentenv]. Pass timeouts, prepared YAML/customizations and parent env; keep harness selection out of pipelines. | Matching agent tests plus `test_agent_env.py`, plugin/skill tests and `test_agent_versions.py`. Same prompt/argv/output/metrics; data-query cannot regain direct BC access, PR Review excludes BCQuality overrides. |
| 7 | Pipeline common seam: [base][pipeline], concrete [pipelines][evaluatedir], [run][run]/[evaluate][evaluate] composition, [base result factories][results] and [code-review result factories][reviewresults]. Add `R`, timeout factory and result suffix; wire every CLI pipeline-construction site. Judged factories and all their pipeline callers take explicit model for success, invalid output and timeout; remove config-based validator fallback. [Enum][types] pipeline construction/tests need a temporary forwarding path until step 10 replaces them. | `test_evaluate_pipeline.py`, `test_evaluation_factories.py`, `test_result_hierarchy.py`, `test_metrics_to_result_flow.py`; success/failure/timeout retain concrete result type, metrics, experiment and judge provenance. |
| 8, repeat per consumer | [Test-generation][testgen] baseline path, then [judge][judge] model/budget/filename with [calibration][calibration], then [NL2AL][nl2al] child env. Include their concrete pipeline/command callers. | `test_testgeneration_validation.py`; `test_codereview.py`, `test_codereview_judge_calibration.py`; `test_nl2al_pipeline.py`. Preserve baseline-test order and joint expected/ignored review matching. |
| 9 | Model-dispatch seam: [result][results], [summary][summary], [leaderboard][leaderboard], [export][export], [result command][resultcommand]; add app result-processing functions accepting explicit model maps and loaded entries. CLI temporarily projects maps from existing enum properties. | Serialization/hierarchy/summary/writer tests; round-trip every result family, unchanged bceval rows, aggregation keys and leaderboard JSON. Models cease importing a dispatch provider. |
| 10, repeat per category | Add contracts and one concrete module under the proposed categories package; wire [run][run], [evaluate][evaluate], [category command][categorycommand], [dataset command][datasetcommand], [options][options], prompt/credential consumers and result-map projection for that category only. Order: bug-fix, test-generation, code-review, nl2al, data-query, advisor, implement, triage. Factories supply the migrated leaf dependencies. | `test_type_exhaustiveness.py`, `test_category_command.py`, prompt/result tests plus that pipeline's tests. Compare old/new metadata, rendered prompts, workspace preparation and deterministic fake-runner artifacts before deleting that category's legacy arms. Typed helper must reject an entry/runner/result mismatch. |
| 11, repeat per utility | Remove remaining ambient inputs from [collection][collectiondir], [contamination][contamination], [analysis][analysis], and [redteam][redteam], each in its own PR with command wiring. Bridge separately moves certificate reads into [its main][bridge], not the benchmark's Config. | Collection, filepath-identification, article-coverage, redteam and CAPI bridge tests respectively; inject two distinct settings in one process and verify no cross-talk. No live credential requirement for unit tests. |
| 12 | Delete exhausted enum properties/singleton/adapters in [types][types], [config][config] and affected imports/tests; update [category guide][categoryguide]. Add a focused app-boundary test. | App suite, CLI smoke tests, all-eight-category metadata/artifact parity. Boundary test rejects `get_config` and environment discovery outside entry-point loaders and importing composition from models; importing runtime/models must not read YAML, dotenv or run git discovery. |

For step 10, compare deterministic artifacts with fake agents/build/judge
responses, not live-model output. Before accepting execution-category wiring,
also run one existing container-backed benchmark smoke task with unchanged
inputs on the appropriate runner. Keep workflow choices/output names unchanged;
this is boundary work, not a benchmark-methodology change.

## 4. Risks and deferred decisions

- **Large fan-out:** leaf signatures have several callers. Migrate one family
  and its callers together; allow short-lived forwarding adapters, never a
  new global resolver. Rebase onto completed core extraction PRs and adapt to
  their public APIs rather than reopening/moving core code.
- **Cycles/typing:** category definitions sit above models and pipelines.
  A facade that lets `category.get_policy()` remain callable from models merely
  renames the locator. Keep heterogeneous dispatch at composition, concrete
  generic branches, fresh per-run pipelines and exhaustiveness tests.
- **Behavior/security:** preserve dataset selection, sandboxed prompt rendering,
  test-generation gold-patch modes, credential withholding, plugin access grants,
  timeout semantics and judge provenance. Never serialize parent env or secrets
  in result metadata. Validate runtime requirements before workspace mutation.
- **Old artifacts:** backward compatibility is not required. If historical
  timeout records missing `judge_model` must be imported, decide separately on an
  explicit repair adapter with a supplied historical pin, not today's config.
- **Defer:** plugin discovery, DI containers, new categories, unified agent APIs,
  scoring changes, full YAML-schema redesign, splitting every context/model
  into new packages, and additional core extraction. External tools/SDKs may
  inherit environment by their own contract; supply their environment/credentials
  explicitly without attempting to redesign upstream authentication.

[config]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/config.py
[cli]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/cli.py
[types]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/types.py
[options]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/cli_options.py
[entries]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/dataset/dataset_entry.py
[bcops]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/operations/bc_operations.py
[gitops]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/operations/git_operations.py
[instructions]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/operations/instruction_operations.py
[copilot]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/agent/copilot/agent.py
[claude]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/agent/claude/agent.py
[bcal]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/agent/bcal/agent.py
[prreview]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/agent/pr_review/agent.py
[prompt]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/agent/shared/prompt.py
[plugins]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/agent/shared/plugin.py
[pipeline]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/evaluate/base.py
[testgen]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/evaluate/testgeneration.py
[judge]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/evaluate/codereview_judge.py
[calibration]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/evaluate/codereview_judge_calibration.py
[github]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/github_actions.py
[display]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/results/display.py
[collectgh]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/collection/collect_gh.py
[patchutils]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/collection/patch_utils.py
[contamination]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/contamination/runner.py
[agentenv]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/agent/shared/env.py
[nl2al]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/evaluate/nl2al.py
[analysis]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/analysis/bcquality_article_coverage.py
[bridge]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/agent/bcal/bc_eval_capi_bridge.py
[redteam]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/redteam.py
[run]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/commands/run.py
[evaluate]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/commands/evaluate.py
[datasetcommand]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/commands/dataset.py
[resultcommand]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/commands/result.py
[categorycommand]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/commands/category.py
[results]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/results/base.py
[reviewresults]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/results/codereview.py
[summary]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/results/summary.py
[leaderboard]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/results/leaderboard.py
[export]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/results/bceval_export.py
[project]: /home/runner/work/BC-Bench/BC-Bench/pyproject.toml
[commands]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/commands/
[evaluatedir]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/evaluate/
[collectiondir]: /home/runner/work/BC-Bench/BC-Bench/src/bcbench/collection/
[categoryguide]: /home/runner/work/BC-Bench/BC-Bench/CATEGORIES.md
