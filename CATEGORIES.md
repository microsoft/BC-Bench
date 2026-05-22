# Adding a New Category

BC-Bench is **category-based**. A category is a distinct evaluation scenario: `bug-fix` asks an agent to patch buggy code, while `test-generation` asks it to write reproduction tests.

The `bug-fix` and `test-generation` categories happen to share one dataset today. A new category should have its own: dataset schema, entry type, result type, pipeline, etc.

This doc is a map; the source files and their comments are the source of truth. To experiment with agent setup on existing categories, see [EXPERIMENT.md](EXPERIMENT.md).

## Architecture

Start with `EvaluationCategory` in [src/bcbench/types.py](src/bcbench/types.py). It is the category registry. Each enum value maps to the pieces the rest of the CLI and workflows consume:

- `dataset_path` — the dataset file for raw tasks.
- `entry_class` — the typed Python model for one dataset row (aka one task).
- `result_class` — the recorded outcome for one evaluated task.
- `summary_class` — the aggregate view used by result summaries and leaderboards.
- `pipeline` — the category-specific setup, agent run, and evaluation behavior.
- Prompt template — the category-specific prompt in [src/bcbench/agent/shared/config.yaml](src/bcbench/agent/shared/config.yaml), loaded by [src/bcbench/agent/shared/prompt.py](src/bcbench/agent/shared/prompt.py).

Keep dataset entry classes and result classes focused on typed data. Put category-specific behavior in the pipeline.

## Checklist

Use the existing `bug-fix` and `test-generation` implementations as examples.

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
