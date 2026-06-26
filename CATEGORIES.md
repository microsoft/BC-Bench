# Adding a New Category

BC-Bench is **category-based**. A category is a distinct evaluation scenario: `bug-fix` asks an agent to patch buggy code, `test-generation` asks it to write reproduction tests, `code-review` asks it to flag issues in a diff, and `nl2al` asks it to turn a natural-language spec into AL code.

Categories also differ in how they're scored and run. `bug-fix` and `test-generation` are execution-based: they build and run AL code, so they need a BC container. `code-review` and `nl2al` both leverage LLM-as-a-judge: `code-review` scores precision/recall/F1 of flagged issues against expected findings (an LLM judge only matches comments), and `nl2al` has an LLM grade the output against an LMChecklist. The `EvaluationCategory` properties (`requires_container`, `runner`, `evaluators`, `core_score`) capture these differences for the workflows.

Categories may share a dataset (`bug-fix` and `test-generation` do today), but a new category should generally have its own: dataset schema, entry type, result type, pipeline, etc.

This doc is a map; the source files and their comments are the source of truth. To experiment with agent setup on existing categories, see [EXPERIMENT.md](EXPERIMENT.md).

## Architecture

Start with `EvaluationCategory` in [src/bcbench/types.py](src/bcbench/types.py). It is the category registry. Each enum value maps to the pieces the rest of the CLI and workflows consume:

- `dataset_path` — the dataset file for raw tasks.
- `entry_class` — the typed Python model for one dataset row (aka one task).
- `result_class` — the recorded outcome for one evaluated task.
- `summary_class` / `aggregate_class` — the aggregate views used by result summaries and leaderboards.
- `pipeline` — the category-specific setup, agent run, and evaluation behavior.
- `evaluators` / `core_score` — the bc-eval evaluator list and headline score, emitted to workflows by [src/bcbench/commands/category.py](src/bcbench/commands/category.py).
- `requires_container` / `runner` — whether the category needs a BC container and which runner evaluates it.
- Prompt template — the category-specific prompt in [src/bcbench/agent/shared/config.yaml](src/bcbench/agent/shared/config.yaml), loaded by [src/bcbench/agent/shared/prompt.py](src/bcbench/agent/shared/prompt.py).

Keep dataset entry classes and result classes focused on typed data. Put category-specific behavior in the pipeline.

## Checklist

Use the existing implementations as examples: `bug-fix` and `test-generation` for execution-based categories, `code-review` and `nl2al` for judge-based ones.

1. Add the enum value and mappings in [src/bcbench/types.py](src/bcbench/types.py).
2. Add the category dataset JSONL and entry class in [src/bcbench/dataset/dataset_entry.py](src/bcbench/dataset/dataset_entry.py).
3. Add a result class under [src/bcbench/results/](src/bcbench/results/) and map it from `EvaluationCategory.result_class`.
4. Add a pipeline under [src/bcbench/evaluate/](src/bcbench/evaluate/).
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
