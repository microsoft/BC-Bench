# Adding a New Category

BC-Bench is **category-based**. A category is a distinct evaluation scenario: `bug-fix` asks an agent to patch buggy code, `test-generation` asks it to write reproduction tests, `code-review` asks it to flag issues in a diff, `nl2al` asks it to turn a natural-language spec into AL code, `extensibility-request-advisor` asks it to classify and assess a fully specified extensibility need and draft a GitHub issue, `extensibility-request-implement` asks it to implement an approved extensibility request (e.g. add an integration event) in an existing repo, and `extensibility-request-triage` asks it to triage an extensibility request (emit managed labels, an advisory comment, and an open/closed decision).

Categories also differ in how they're scored and run. `bug-fix` and `test-generation` are execution-based: they build and run AL code, so they need a BC container. `code-review`, `nl2al`, `extensibility-request-advisor`, `extensibility-request-implement`, and `extensibility-request-triage` all leverage LLM-as-a-judge: `code-review` scores precision/recall/F1 of flagged issues against expected findings (an LLM judge only matches comments), and the other judge-based categories have an LLM grade the agent output against an LMChecklist. Advisor entries use an offline, single-shot proxy for the production skill's interactive flow: the prompt supplies the complete scenario, GitHub submission is disabled, and the agent persists classification, feasibility analysis, alternatives, and the final issue draft to `advisor_result.json`. Each category's definition (`requires_container`, `runner`, `evaluators`, `core_score`) captures these differences for the workflows.

Categories may share a dataset (`bug-fix` and `test-generation` do today), but a new category should generally have its own: dataset schema, entry type, result type, pipeline, etc.

This doc is a map; the source files and their comments are the source of truth. To experiment with agent setup on existing categories, see [EXPERIMENT.md](EXPERIMENT.md).

## Architecture

`EvaluationCategory` in [src/bcbench/types.py](src/bcbench/types.py) names the categories. Each category has a package under [src/bcbench/categories/](src/bcbench/categories/) that owns its behaviour; code shared by several categories (base classes, shared result families, shared datasets) stays in the common modules. The CLI looks up a category with `category_definition()` in [src/bcbench/categories/__init__.py](src/bcbench/categories/__init__.py).

A category's `definition.py` declares ([src/bcbench/categories/definition.py](src/bcbench/categories/definition.py)):

- `dataset_file` / `entry_type` — the dataset file for raw tasks and the typed Python model for one dataset row (aka one task). `requires_repo` follows from the entry type.
- `make_pipeline` — builds the category's pipeline (`pipeline.py` in the category package): setup, agent run, and evaluation behavior.
- `evaluators` / `core_score` — the bc-eval evaluator list and headline score, emitted to workflows by [src/bcbench/commands/category.py](src/bcbench/commands/category.py).
- `requires_container` / `runner` — whether the category needs a BC container, and which runner evaluates it.
- `pass_bc_credentials` — whether the agent may see the BC container credentials.

Still mapped from `EvaluationCategory` while the redesign continues:

- `result_class` — the recorded outcome for one evaluated task.
- `summary_class` / `aggregate_class` — the aggregate views used by result summaries and leaderboards.
- `judge_model` — the pinned LLM judge for judge-scored categories.
- Prompt template — the category-specific prompt in [src/bcbench/agent/shared/config.yaml](src/bcbench/agent/shared/config.yaml), loaded by [src/bcbench/agent/shared/prompt.py](src/bcbench/agent/shared/prompt.py).

Keep dataset entry classes and result classes focused on typed data. Put category-specific behavior in the pipeline.

## Checklist

Use the existing implementations as examples: `bug-fix` and `test-generation` for execution-based categories, `code-review` and `nl2al` for judge-based ones.

1. Add the enum value and remaining mappings in [src/bcbench/types.py](src/bcbench/types.py), and a category package with `definition.py` under [src/bcbench/categories/](src/bcbench/categories/), wired into `category_definition()`.
2. Add the category dataset JSONL and entry class in [src/bcbench/dataset/dataset_entry.py](src/bcbench/dataset/dataset_entry.py).
3. Add a result class under [src/bcbench/results/](src/bcbench/results/) and map it from `EvaluationCategory.result_class`.
4. Add a `pipeline.py` to the category package, subclassing `EvaluationPipeline` from [src/bcbench/evaluate/base.py](src/bcbench/evaluate/base.py).
5. Add the prompt template to [src/bcbench/agent/shared/config.yaml](src/bcbench/agent/shared/config.yaml).
6. Add the category to workflow choice lists in [.github/workflows/](.github/workflows/), especially evaluation workflows and CI category selection.
7. Add docs, leaderboard data, notebooks, and tests for the category where relevant.

## Validation

At minimum, run the exhaustiveness tests and one local smoke test:

```powershell
uv run pytest tests/test_type_exhaustiveness.py
uv run bcbench run copilot <some-instance-id> --category <new-category> --repo-path /path/to/repo
```

Then trigger a CI test run before running the full dataset.
