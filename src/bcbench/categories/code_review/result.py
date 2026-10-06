from collections.abc import Sequence
from typing import NamedTuple, Self, override

import numpy as np
from bcbench_core.scoring import f1_score, f_beta_score, precision_recall
from bcbench_core.stats import bootstrap_ci
from pydantic import Field
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from scipy.optimize import linear_sum_assignment

from bcbench.categories.code_review.entry import ReviewComment
from bcbench.dataset import BaseDatasetEntry
from bcbench.results.base import BaseEvaluationResult, JudgeScoredEvaluationResult
from bcbench.results.leaderboard import JudgeBasedLeaderboardAggregate
from bcbench.results.summary import EvaluationResultSummary, JudgeBasedEvaluationResultSummary
from bcbench.types import EvaluationContext

_METRIC_EXPLANATIONS = """\
<details>
<summary>📖 How to read these metrics</summary>

- **Micro** — sums matched, scorable generated (generated minus ignored), and expected across all tasks and computes one score; tasks with many comments dominate.
- **Macro** — computes P/R/F1 per task and averages the scores; every task counts equally regardless of comment volume. Macro precision averages over tasks where the agent commented plus negative tasks (no expected findings), where correct silence scores as perfect precision; silence on a positive task is still not rewarded. Macro recall averages only over positive tasks, since negative tasks have nothing to recall.
- **Matched comment** — a generated comment assigned one-to-one to an expected finding after an LLM judge confirms the same underlying issue. All same-file pairs are candidates; line distance only breaks assignment ties.
- **Ignored comment** — a generated comment that matched the entry's `ignored_comments` set (acceptable-but-not-required findings). Neutral: removed from the scored generated set, so it neither earns recall nor counts against precision. Precision's denominator is scorable generated (generated minus ignored).
- **F1** — harmonic mean of precision and recall; balances both equally. (Special case of Fβ at β=1.)
- **Fβ** — generalized F-score with a tunable precision/recall trade-off:

  ```
  F_β = (1 + β²) · (P · R) / (β² · P + R)
  ```

  where *P* = precision, *R* = recall. β < 1 favors precision; β > 1 favors recall.
- **Fβ (β=0.5)** — precision-leaning; use when false positives are costly (noisy reviews waste reviewer time).
- **Fβ (β=2)** — recall-leaning; use when missing issues is costly.
- **Severity MAE** — mean absolute error between generated and expected severity levels (matched comments only). Lower is better; `0` = exact match.
- **Valid review output rate** — fraction of runs whose output parsed into a structured review. Failures score 0 on every other metric.

</details>
"""


_CONSOLE_METRIC_EXPLANATIONS = (
    "[bold]Micro[/bold] — volume-weighted across all comments; sums matched, scorable generated (generated minus ignored), and expected, so tasks with many comments dominate.\n"
    "[bold]Macro[/bold] — per-task P/R/F1 averaged equally; every task counts the same. Macro precision rewards correct silence on negative tasks but not on positive ones; macro recall averages only over positive tasks.\n"
    "[bold]Matched comment[/bold] — assigned one-to-one after an LLM judge confirms the same underlying issue; all same-file pairs are candidates, with line distance only breaking assignment ties.\n"
    "[bold]Ignored comment[/bold] — matched the entry's ignored_comments set; neutral, so it is removed from the scored generated set (no recall, no precision hit). Precision's denominator is scorable generated (generated minus ignored).\n"
    "[bold]F1[/bold] — harmonic mean of precision and recall (special case of Fβ at β=1).\n"
    "[bold]Fβ[/bold] — F_β = (1 + β²) · (P · R) / (β² · P + R); β<1 favors precision, β>1 favors recall.\n"
    "[bold]Fβ (β=0.5)[/bold] — precision-leaning; use when false positives are costly.\n"
    "[bold]Fβ (β=2)[/bold] — recall-leaning; use when missing issues is costly.\n"
    "[bold]Severity MAE[/bold] — mean absolute error of severity levels for matched comments; lower is better, 0 = exact match.\n"
    "[bold]Valid review output rate[/bold] — fraction of runs whose output parsed into a structured review."
)


def _build_console_table(title: str, columns: list[str], row: list[str]) -> Table:
    table = Table(title=title, title_justify="left", title_style="bold cyan", show_header=True, header_style="bold")
    for column in columns:
        table.add_column(column, justify="right")
    table.add_row(*row)
    return table


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").lstrip("/")


def _line_distance(line: int, start: int, end: int | None) -> int:
    effective_end = end if end is not None else start
    if start <= line <= effective_end:
        return 0
    if line < start:
        return start - line
    return line - effective_end


def candidate_comment_pairs(
    expected_comments: list[ReviewComment],
    generated_comments: list[ReviewComment],
) -> list[tuple[ReviewComment, ReviewComment]]:
    """All same-file pairs, preserving comment identity and input order without line pruning."""
    return [(expected, generated) for expected in expected_comments for generated in generated_comments if _normalize_path(expected.file) == _normalize_path(generated.file)]


def assign_comment_matches(
    expected_pairs: list[tuple[ReviewComment, ReviewComment]],
    ignored_pairs: list[tuple[ReviewComment, ReviewComment]],
) -> tuple[list[tuple[ReviewComment, ReviewComment]], list[tuple[ReviewComment, ReviewComment]]]:
    """Assign eligible edges by expected count, then ignored count, then total line distance."""
    pairs = expected_pairs + ignored_pairs
    if not pairs:
        return [], []

    # Identity, not value equality: identical-looking findings are still separate comments.
    gold_ids = dict.fromkeys(id(gold) for gold, _ in pairs)
    generated_ids = dict.fromkeys(id(generated) for _, generated in pairs)
    rows = {key: index for index, key in enumerate(gold_ids)}
    columns = {key: index for index, key in enumerate(generated_ids)}
    edges = {(rows[id(gold)], columns[id(generated)]): (gold, generated) for gold, generated in pairs}
    expected_edges = {(rows[id(gold)], columns[id(generated)]) for gold, generated in expected_pairs}
    distances = {key: _line_distance(generated.line_start, gold.line_start, gold.line_end) for key, (gold, generated) in edges.items()}
    num_gold, num_generated = len(rows), len(columns)

    # One ignored match outweighs ALL possible distance savings; one expected match
    # outweighs ALL ignored matches plus distance savings. Ineligible edges stay forbidden.
    ignored_reward = max(distances.values()) * min(num_gold, num_generated) + 1
    expected_reward = (num_gold + 1) * ignored_reward
    cost = np.full((num_gold, num_generated + num_gold), np.inf)
    cost[:, num_generated:] = 0  # Dummy columns let every gold comment remain unmatched.
    for key, distance in distances.items():
        cost[key] = distance - (expected_reward if key in expected_edges else ignored_reward)

    row_indices, column_indices = linear_sum_assignment(cost)
    selected = [(row, column) for row, column in zip(row_indices, column_indices, strict=True) if column < num_generated]
    return (
        [edges[key] for key in selected if key in expected_edges],
        [edges[key] for key in selected if key not in expected_edges],
    )


def _severity_mean_absolute_error(matched_pairs: list[tuple[ReviewComment, ReviewComment]]) -> float:
    """Mean absolute difference between expected and generated severity levels over matched pairs.

    Pairs where either side has no severity are skipped, since prod keeps unknown-severity findings
    rather than defaulting them. Returns 0.0 when there are no scorable pairs.
    """
    errors = [abs(expected.severity.level - generated.severity.level) for expected, generated in matched_pairs if expected.severity is not None and generated.severity is not None]
    if not errors:
        return 0.0
    return sum(errors) / len(errors)


class _ScoreCounts(NamedTuple):
    matched: int
    incorrect: int
    missed: int
    ignored: int
    precision: float
    recall: float


def _score_counts(matched_count: int, generated_count: int, expected_count: int, ignored_count: int) -> _ScoreCounts:
    """Derive the code-review scoring counts and precision/recall from raw match counts.

    Ignored comments are neutral: they leave the scored generated set (``generated - ignored``) so
    they neither earn recall (they are not expected) nor cost precision (they are not false
    positives). Extracted as a pure function so this critical metric math can be unit-tested
    independently of comment matching, the LLM judge, and I/O.
    """
    scored_generated_count = generated_count - ignored_count
    precision, recall = precision_recall(matched_count, scored_generated_count, expected_count)
    return _ScoreCounts(
        matched=matched_count,
        incorrect=scored_generated_count - matched_count,
        missed=expected_count - matched_count,
        ignored=ignored_count,
        precision=precision,
        recall=recall,
    )


class CodeReviewResult(JudgeScoredEvaluationResult):
    """Result for the code-review category."""

    generated_comments: list[ReviewComment] = Field(default_factory=list)
    expected_comments: list[ReviewComment] = Field(default_factory=list)
    ignored_comments: list[ReviewComment] = Field(default_factory=list)
    valid_review_output: bool = False

    matched_comment_count: int = Field(default=0, ge=0)
    missed_comment_count: int = Field(default=0, ge=0)
    incorrect_comment_count: int = Field(default=0, ge=0)
    ignored_matched_comment_count: int = Field(default=0, ge=0)

    precision: float = Field(default=0.0, ge=0.0, le=1.0)
    recall: float = Field(default=0.0, ge=0.0, le=1.0)
    f1: float = Field(default=0.0, ge=0.0, le=1.0)
    f_beta_05: float = Field(default=0.0, ge=0.0, le=1.0)
    f_beta_2: float = Field(default=0.0, ge=0.0, le=1.0)
    severity_mae: float = 0.0

    @classmethod
    def create[E: BaseDatasetEntry](
        cls,
        context: EvaluationContext[E],
        output: str,
        expected_comments: list[ReviewComment],
        generated_comments: list[ReviewComment],
        *,
        matched_pairs: list[tuple[ReviewComment, ReviewComment]],
        ignored_comments: list[ReviewComment],
        ignored_matched_pairs: list[tuple[ReviewComment, ReviewComment]],
    ) -> Self:
        scores = _score_counts(
            matched_count=len(matched_pairs),
            generated_count=len(generated_comments),
            expected_count=len(expected_comments),
            ignored_count=len(ignored_matched_pairs),
        )

        return cls(
            **cls._base_fields(context),
            output=output,
            expected_comments=expected_comments,
            generated_comments=generated_comments,
            ignored_comments=ignored_comments,
            valid_review_output=True,
            matched_comment_count=scores.matched,
            incorrect_comment_count=scores.incorrect,
            missed_comment_count=scores.missed,
            ignored_matched_comment_count=scores.ignored,
            precision=scores.precision,
            recall=scores.recall,
            f1=f1_score(scores.precision, scores.recall),
            f_beta_05=f_beta_score(scores.precision, scores.recall, beta=0.5),
            f_beta_2=f_beta_score(scores.precision, scores.recall, beta=2.0),
            severity_mae=_severity_mean_absolute_error(matched_pairs),
        )

    @classmethod
    def create_invalid[E: BaseDatasetEntry](
        cls,
        context: EvaluationContext[E],
        output: str,
        expected_comments: list[ReviewComment],
    ) -> Self:
        """Result for output that could not be parsed into a review — scored zero."""
        return cls(
            **cls._base_fields(context),
            output=output,
            expected_comments=expected_comments,
            valid_review_output=False,
        )

    @property
    @override
    def category_metrics(self) -> dict[str, int | float | bool]:
        return {
            "generated_comment_count": len(self.generated_comments),
            "expected_comment_count": len(self.expected_comments),
            "matched_comment_count": self.matched_comment_count,
            "incorrect_comment_count": self.incorrect_comment_count,
            "missed_comment_count": self.missed_comment_count,
            "ignored_matched_comment_count": self.ignored_matched_comment_count,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
            "f_beta_05": round(self.f_beta_05, 3),
            "f_beta_2": round(self.f_beta_2, 3),
            "severity_mae": round(self.severity_mae, 3),
            "valid_review_output": self.valid_review_output,
        }

    @property
    @override
    def display_row(self) -> dict[str, str]:
        return {
            "Generated": str(len(self.generated_comments)),
            "Matched": str(self.matched_comment_count),
            "Expected": str(len(self.expected_comments)),
            "Precision": f"{self.precision:.2f}",
            "Recall": f"{self.recall:.2f}",
            "F1": f"{self.f1:.2f}",
        }


class CodeReviewResultSummary(JudgeBasedEvaluationResultSummary):
    """
    Summary for the code-review category.

    Micro metrics aggregate matched/expected/generated comment counts across all results (volume-weighted).
    Macro metrics average per-task scores (each task weighted equally).
    """

    average_prompt_tokens: float | None = None
    average_completion_tokens: float | None = None

    generated_comment_count: int = Field(default=0, ge=0)
    expected_comment_count: int = Field(default=0, ge=0)
    matched_comment_count: int = Field(default=0, ge=0)
    incorrect_comment_count: int = Field(default=0, ge=0)
    missed_comment_count: int = Field(default=0, ge=0)
    ignored_matched_comment_count: int = Field(default=0, ge=0)

    precision: float = Field(default=0.0, ge=0.0, le=1.0)
    recall: float = Field(default=0.0, ge=0.0, le=1.0)
    f1: float = Field(default=0.0, ge=0.0, le=1.0)
    f_beta_05: float = Field(default=0.0, ge=0.0, le=1.0)
    f_beta_2: float = Field(default=0.0, ge=0.0, le=1.0)

    macro_precision: float = Field(default=0.0, ge=0.0, le=1.0)
    macro_recall: float = Field(default=0.0, ge=0.0, le=1.0)
    macro_f1: float = Field(default=0.0, ge=0.0, le=1.0)
    macro_f_beta_05: float = Field(default=0.0, ge=0.0, le=1.0)
    macro_f_beta_2: float = Field(default=0.0, ge=0.0, le=1.0)

    severity_mae: float = 0.0
    valid_review_output_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    average_total_tokens: float | None = None

    # Per-task F1 keyed by instance_id, retained so the leaderboard can bootstrap a confidence
    # interval over tasks (meaningful even for a single run) instead of only over runs.
    instance_results: dict[str, float] = Field(default_factory=dict)

    def _performance_markdown(self) -> str:
        def metric(value: float | None, digits: int = 1) -> str:
            return f"{value:.{digits}f}" if value is not None else "n/a"

        return (
            "## Performance\n"
            "\n"
            "| Avg duration (s) | Avg prompt tokens | Avg completion tokens | Avg total tokens | Avg AI credits |\n"
            "|-----------------:|------------------:|----------------------:|-----------------:|---------------:|\n"
            f"| {self.average_duration:.1f} | {metric(self.average_prompt_tokens)} | {metric(self.average_completion_tokens)} | "
            f"{metric(self.average_total_tokens)} | {metric(self.average_ai_credits, 4)} |\n"
            "\n"
        )

    @override
    def render_github_metrics_markdown(self) -> str:
        micro_p = self.precision * 100
        micro_r = self.recall * 100
        micro_f1 = self.f1 * 100
        micro_f05 = self.f_beta_05 * 100
        micro_f2 = self.f_beta_2 * 100
        macro_p = self.macro_precision * 100
        macro_r = self.macro_recall * 100
        macro_f1 = self.macro_f1 * 100
        macro_f05 = self.macro_f_beta_05 * 100
        macro_f2 = self.macro_f_beta_2 * 100
        valid_rate = self.valid_review_output_rate * 100
        return (
            "## Comment counts\n"
            "\n"
            "| Generated | Expected | Matched | Incorrect | Missed | Ignored |\n"
            "|----------:|---------:|--------:|----------:|-------:|--------:|\n"
            f"| {self.generated_comment_count} | {self.expected_comment_count} | {self.matched_comment_count} | {self.incorrect_comment_count} | {self.missed_comment_count} | {self.ignored_matched_comment_count} |\n"
            "\n"
            "## Micro metrics (volume-weighted across all comments)\n"
            "\n"
            "| Precision | Recall | F1 | Fβ (β=0.5) | Fβ (β=2) |\n"
            "|----------:|-------:|---:|-----------:|---------:|\n"
            f"| {micro_p:.1f}% | {micro_r:.1f}% | {micro_f1:.1f}% | {micro_f05:.1f}% | {micro_f2:.1f}% |\n"
            "\n"
            "## Macro metrics (averaged per task)\n"
            "\n"
            "| Precision | Recall | F1 | Fβ (β=0.5) | Fβ (β=2) |\n"
            "|----------:|-------:|---:|-----------:|---------:|\n"
            f"| {macro_p:.1f}% | {macro_r:.1f}% | {macro_f1:.1f}% | {macro_f05:.1f}% | {macro_f2:.1f}% |\n"
            "\n"
            "## Quality\n"
            "\n"
            "| Severity MAE | Valid review output rate |\n"
            "|-------------:|-------------------------:|\n"
            f"| {self.severity_mae:.3f} | {valid_rate:.1f}% |\n"
            "\n"
            f"{self._performance_markdown()}"
            f"{_METRIC_EXPLANATIONS}"
        )

    @override
    def render_console_metrics(self) -> RenderableType:
        metric_columns = ["Precision", "Recall", "F1", "Fβ (β=0.5)", "Fβ (β=2)"]

        return Group(
            _build_console_table(
                "Comment counts",
                ["Generated", "Expected", "Matched", "Incorrect", "Missed", "Ignored"],
                [
                    str(self.generated_comment_count),
                    str(self.expected_comment_count),
                    str(self.matched_comment_count),
                    str(self.incorrect_comment_count),
                    str(self.missed_comment_count),
                    str(self.ignored_matched_comment_count),
                ],
            ),
            _build_console_table(
                "Micro metrics (volume-weighted across all comments)",
                metric_columns,
                [
                    f"{self.precision * 100:.1f}%",
                    f"{self.recall * 100:.1f}%",
                    f"{self.f1 * 100:.1f}%",
                    f"{self.f_beta_05 * 100:.1f}%",
                    f"{self.f_beta_2 * 100:.1f}%",
                ],
            ),
            _build_console_table(
                "Macro metrics (averaged per task)",
                metric_columns,
                [
                    f"{self.macro_precision * 100:.1f}%",
                    f"{self.macro_recall * 100:.1f}%",
                    f"{self.macro_f1 * 100:.1f}%",
                    f"{self.macro_f_beta_05 * 100:.1f}%",
                    f"{self.macro_f_beta_2 * 100:.1f}%",
                ],
            ),
            _build_console_table(
                "Quality",
                ["Severity MAE", "Valid review output rate"],
                [f"{self.severity_mae:.3f}", f"{self.valid_review_output_rate * 100:.1f}%"],
            ),
            _build_console_table(
                "Performance",
                ["Avg duration (s)", "Prompt", "Completion", "Total", "AI credits"],
                [
                    f"{self.average_duration:.1f}",
                    f"{self.average_prompt_tokens:.1f}" if self.average_prompt_tokens is not None else "n/a",
                    f"{self.average_completion_tokens:.1f}" if self.average_completion_tokens is not None else "n/a",
                    f"{self.average_total_tokens:.1f}" if self.average_total_tokens is not None else "n/a",
                    f"{self.average_ai_credits:.4f}" if self.average_ai_credits is not None else "n/a",
                ],
            ),
            Panel(
                _CONSOLE_METRIC_EXPLANATIONS,
                title="📖 How to read these metrics",
                title_align="left",
                border_style="dim",
                padding=(1, 2),
            ),
        )

    @classmethod
    @override
    def from_results(cls, results: Sequence[BaseEvaluationResult], run_id: str) -> "CodeReviewResultSummary":
        summary = super().from_results(results, run_id)
        assert isinstance(summary, CodeReviewResultSummary)

        code_review_results: list[CodeReviewResult] = [r for r in results if isinstance(r, CodeReviewResult)]
        total_results: int = len(code_review_results)

        generated_total: int = sum(len(r.generated_comments) for r in code_review_results)
        expected_total: int = sum(len(r.expected_comments) for r in code_review_results)
        matched_total: int = sum(r.matched_comment_count for r in code_review_results)
        incorrect_total: int = sum(r.incorrect_comment_count for r in code_review_results)
        missed_total: int = sum(r.missed_comment_count for r in code_review_results)
        ignored_total: int = sum(r.ignored_matched_comment_count for r in code_review_results)

        # Ignored comments are neutral, so they leave the scored generated set exactly as each
        # per-task precision already does -- keeping micro precision consistent with macro.
        scored_generated_total: int = generated_total - ignored_total
        precision, recall = precision_recall(matched_total, scored_generated_total, expected_total)
        f1: float = f1_score(precision, recall)
        f_beta_05: float = f_beta_score(precision, recall, beta=0.5)
        f_beta_2: float = f_beta_score(precision, recall, beta=2.0)

        # Precision is only defined where the agent actually commented, so silent tasks are normally
        # excluded from macro precision (rewarding silence would inflate precision on positive tasks).
        # "Commented" means scorable comments (matched + incorrect); a positive task whose only output
        # was neutralized as ignored is treated like silence, not rewarded. Exception: negative tasks
        # (no expected findings) ARE scored when silent -- staying quiet earns precision=1.0, while any
        # scorable comment is a false positive (precision=0).
        results_for_macro_precision = [r for r in code_review_results if (r.matched_comment_count + r.incorrect_comment_count) > 0 or not r.expected_comments]
        macro_precision: float = sum(r.precision for r in results_for_macro_precision) / len(results_for_macro_precision) if results_for_macro_precision else 0.0
        # Recall measures the ability to find planted issues, so it only averages over positive tasks.
        # Negative tasks (no expected findings) have a vacuous recall of 1.0 that would otherwise inflate
        # the metric; when a run is all-negative there is nothing to recall, so recall defaults to 1.0.
        positive_results = [r for r in code_review_results if r.expected_comments]
        macro_recall: float = sum(r.recall for r in positive_results) / len(positive_results) if positive_results else 1.0
        macro_f1: float = sum(r.f1 for r in code_review_results) / total_results
        macro_f_beta_05: float = sum(r.f_beta_05 for r in code_review_results) / total_results
        macro_f_beta_2: float = sum(r.f_beta_2 for r in code_review_results) / total_results

        weighted_mae_numerator: float = sum(r.severity_mae * r.matched_comment_count for r in code_review_results)
        weighted_mae_denominator: int = sum(r.matched_comment_count for r in code_review_results)
        severity_mae: float = weighted_mae_numerator / weighted_mae_denominator if weighted_mae_denominator > 0 else 0.0

        valid_output_count: int = sum(1 for r in code_review_results if r.valid_review_output)
        valid_output_rate: float = valid_output_count / total_results

        def average_metric(values: Sequence[int | float | None]) -> float | None:
            available = [value for value in values if value is not None]
            return sum(available) / len(available) if available else None

        return summary.model_copy(
            update={
                "generated_comment_count": generated_total,
                "expected_comment_count": expected_total,
                "matched_comment_count": matched_total,
                "incorrect_comment_count": incorrect_total,
                "missed_comment_count": missed_total,
                "ignored_matched_comment_count": ignored_total,
                "precision": round(precision, 3),
                "recall": round(recall, 3),
                "f1": round(f1, 3),
                "f_beta_05": round(f_beta_05, 3),
                "f_beta_2": round(f_beta_2, 3),
                "macro_precision": round(macro_precision, 3),
                "macro_recall": round(macro_recall, 3),
                "macro_f1": round(macro_f1, 3),
                "macro_f_beta_05": round(macro_f_beta_05, 3),
                "macro_f_beta_2": round(macro_f_beta_2, 3),
                "severity_mae": round(severity_mae, 3),
                "valid_review_output_rate": round(valid_output_rate, 3),
                "instance_results": {r.instance_id: round(r.f1, 6) for r in code_review_results},
                "average_prompt_tokens": average_metric([result.metrics.prompt_tokens if result.metrics else None for result in code_review_results]),
                "average_completion_tokens": average_metric([result.metrics.completion_tokens if result.metrics else None for result in code_review_results]),
                "average_total_tokens": average_metric([result.metrics.total_tokens if result.metrics else None for result in code_review_results]),
                "average_ai_credits": average_metric([result.metrics.ai_credits if result.metrics else None for result in code_review_results]),
            }
        )


class CodeReviewLeaderboardAggregate(JudgeBasedLeaderboardAggregate):
    """Aggregate for the code-review category: mean F1 across runs with bootstrap CI."""

    f1: float = 0.0
    f1_ci_low: float | None = None
    f1_ci_high: float | None = None
    f_beta_05: float = 0.0
    f_beta_2: float = 0.0
    precision: float = 0.0
    recall: float = 0.0

    macro_f1: float = 0.0
    macro_f1_ci_low: float | None = None
    macro_f1_ci_high: float | None = None
    macro_f_beta_05: float = 0.0
    macro_f_beta_2: float = 0.0
    macro_precision: float = 0.0
    macro_recall: float = 0.0

    valid_review_output_rate: float = 0.0
    average_prompt_tokens: float | None = None
    average_completion_tokens: float | None = None
    average_total_tokens: float | None = None
    average_ai_credits: float | None = None

    @classmethod
    @override
    def from_runs(cls, runs: Sequence[EvaluationResultSummary]) -> "CodeReviewLeaderboardAggregate":
        base = super().from_runs(runs)
        assert isinstance(base, CodeReviewLeaderboardAggregate)

        cr_runs: list[CodeReviewResultSummary] = [run for run in runs if isinstance(run, CodeReviewResultSummary)]
        n = len(cr_runs)

        def mean_metric(values: Sequence[float | None]) -> float | None:
            available = [value for value in values if value is not None]
            return sum(available) / len(available) if available else None

        # The micro headline pools every comment across the dataset, so there is no per-task
        # decomposition to resample; its CI is intentionally over run-level means and captures
        # run-to-run reproducibility (None unless >=2 runs with variance).
        f1_ci = bootstrap_ci([r.f1 for r in cr_runs])
        # The macro headline weights tasks equally, so we bootstrap the equal-weight headline over the
        # pooled per-task F1 scores across runs: the CI reflects task-level variance (resampling tasks),
        # which is the dominant sampling uncertainty for our small task set and is meaningful even for a
        # single run. This deliberately differs from the per-run micro CI above.
        pooled_task_f1 = [score for r in cr_runs for score in r.instance_results.values()]
        macro_f1_ci = bootstrap_ci(pooled_task_f1)

        return base.model_copy(
            update={
                "f1": round(f1_ci["mean"], 3) if f1_ci["mean"] is not None else 0.0,
                "f1_ci_low": round(f1_ci["ci_low"], 3) if f1_ci["ci_low"] is not None else None,
                "f1_ci_high": round(f1_ci["ci_high"], 3) if f1_ci["ci_high"] is not None else None,
                "f_beta_05": sum(r.f_beta_05 for r in cr_runs) / n,
                "f_beta_2": sum(r.f_beta_2 for r in cr_runs) / n,
                "precision": sum(r.precision for r in cr_runs) / n,
                "recall": sum(r.recall for r in cr_runs) / n,
                "macro_f1": round(macro_f1_ci["mean"], 3) if macro_f1_ci["mean"] is not None else 0.0,
                "macro_f1_ci_low": round(macro_f1_ci["ci_low"], 3) if macro_f1_ci["ci_low"] is not None else None,
                "macro_f1_ci_high": round(macro_f1_ci["ci_high"], 3) if macro_f1_ci["ci_high"] is not None else None,
                "macro_f_beta_05": sum(r.macro_f_beta_05 for r in cr_runs) / n,
                "macro_f_beta_2": sum(r.macro_f_beta_2 for r in cr_runs) / n,
                "macro_precision": sum(r.macro_precision for r in cr_runs) / n,
                "macro_recall": sum(r.macro_recall for r in cr_runs) / n,
                "valid_review_output_rate": sum(r.valid_review_output_rate for r in cr_runs) / n,
                "average_prompt_tokens": mean_metric([run.average_prompt_tokens for run in cr_runs]),
                "average_completion_tokens": mean_metric([run.average_completion_tokens for run in cr_runs]),
                "average_total_tokens": mean_metric([run.average_total_tokens for run in cr_runs]),
                "average_ai_credits": mean_metric([run.average_ai_credits for run in cr_runs]),
            }
        )
