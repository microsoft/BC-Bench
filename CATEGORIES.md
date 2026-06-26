# Adding a New Category

BC-Bench is **category-based**. A category is a distinct evaluation scenario: `bug-fix` asks an agent to patch buggy code, while `test-generation` asks it to write reproduction tests.

Today the benchmark ships several categories: `bug-fix`, `test-generation`, `code-review`, `nl2al`, and `hello-world`. The `bug-fix` and `test-generation` categories happen to share one dataset; every other category has its own. A new category should generally have its own: dataset schema, entry type, result type, pipeline, etc.

`hello-world` is an intentionally tiny, imaginary, self-contained category (no BC container, no symbols) kept as a worked example of every step below. Use it together with the existing categories when adding your own.

This doc is a map; the source files and their comments are the source of truth. To experiment with agent setup on existing categories, see [EXPERIMENT.md](EXPERIMENT.md).

## Architecture

Start with `EvaluationCategory` in [src/bcbench/types.py](src/bcbench/types.py). It is the category registry. Each enum value maps to the pieces the rest of the CLI and workflows consume:

- `dataset_path` — the dataset file for raw tasks.
- `entry_class` — the typed Python model for one dataset row (aka one task).
- `result_class` — the recorded outcome for one evaluated task.
- `summary_class` — the aggregate view for a single run, used by result summaries and leaderboards.
- `aggregate_class` — combines multiple runs of the same combination on the leaderboard.
- `pipeline` — the category-specific setup, agent run, and evaluation behavior.
- `evaluators` / `core_score` — the bc-eval evaluators to run and the headline score.
- `requires_container` / `runner` — whether evaluation builds AL code (needs a BC container) and which GitHub Actions runner to use.
- Prompt template — the category-specific prompt in [src/bcbench/agent/shared/config.yaml](src/bcbench/agent/shared/config.yaml), loaded by [src/bcbench/agent/shared/prompt.py](src/bcbench/agent/shared/prompt.py).

Every `match self` in `EvaluationCategory` is exhaustive and raises on an unhandled value, so adding the enum value forces you to fill in each property above. Categories that score externally (e.g. via an lm_checklist judge) can reuse the `JudgeBased*` result/summary/aggregate classes instead of writing new ones — `nl2al` and `hello-world` do this.

Keep dataset entry classes and result classes focused on typed data. Put category-specific behavior in the pipeline.

## Checklist

`hello-world` is the smallest end-to-end example; `bug-fix` and `test-generation` show a full execution-based category. The `hello-world` commit touches every file below.

1. Add the enum value and all `match` arms in [src/bcbench/types.py](src/bcbench/types.py).
2. Add the entry class in [src/bcbench/dataset/dataset_entry.py](src/bcbench/dataset/dataset_entry.py), export it from [src/bcbench/dataset/__init__.py](src/bcbench/dataset/__init__.py), and add the dataset JSONL under [dataset/](dataset/).
3. Register the category and its dataset file in the `Get-BCBenchDatasetPath` `ValidateSet`/`switch` in [scripts/BCBenchUtils.psm1](scripts/BCBenchUtils.psm1) so the PowerShell setup scripts accept it.
4. Add (or reuse) a result class under [src/bcbench/results/](src/bcbench/results/) and map it from `EvaluationCategory.result_class` (plus `summary_class` and `aggregate_class`).
5. Add a pipeline under [src/bcbench/evaluate/](src/bcbench/evaluate/) and export it from [src/bcbench/evaluate/__init__.py](src/bcbench/evaluate/__init__.py).
6. Add the prompt template to [src/bcbench/agent/shared/config.yaml](src/bcbench/agent/shared/config.yaml).
7. Handle the category in `MockEvaluationPipeline.evaluate` in [src/bcbench/commands/evaluate.py](src/bcbench/commands/evaluate.py) so the CI mock-evaluation job passes.
8. Add the category to workflow choice lists in [.github/workflows/](.github/workflows/), especially evaluation workflows and CI category selection.
9. Add test fixtures/handling (e.g. in [tests/conftest.py](tests/conftest.py), [tests/test_type_exhaustiveness.py](tests/test_type_exhaustiveness.py), [tests/test_evaluate_pipeline.py](tests/test_evaluate_pipeline.py)) and docs, leaderboard data, and notebooks where relevant.

## Validation

At minimum, run the exhaustiveness tests and one local smoke test:

```powershell
uv run pytest tests/test_type_exhaustiveness.py
uv run bcbench run copilot <some-instance-id> --category <new-category> --repo-path /path/to/repo
```

For example, with the `hello-world` sample:

```powershell
uv run bcbench run copilot helloworld__greeting-english-1 --category hello-world --repo-path /tmp/hello-world-repo
```

Then trigger a CI test run before running the full dataset.
