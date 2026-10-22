from collections.abc import Sequence
from typing import Literal, NamedTuple, Self, override

import numpy as np
from bcbench_core.scoring import f1_score, f_beta_score
from pydantic import BaseModel, Field, StrictBool, model_validator
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from scipy.optimize import linear_sum_assignment

from bcbench.dataset import BaseDatasetEntry, ReviewComment
from bcbench.dataset.codereview import Severity
from bcbench.results.base import BaseEvaluationResult, JudgeScoredEvaluationResult
from bcbench.results.summary import JudgeBasedEvaluationResultSummary
from bcbench.types import CodeReviewScoringMode, EvaluationContext

_METRIC_EXPLANATIONS = """\
<details>
<summary>📖 How to read these metrics</summary>

- **Micro** — sums matched comments, scorable generated (generated minus ignored), covered gold, and expected across all tasks and computes one score; tasks with many comments dominate.
- **Macro** — computes P/R/F1 per task and averages the scores; every task counts equally regardless of comment volume. Macro precision averages over tasks where the agent commented plus negative tasks (no expected findings), where correct silence scores as perfect precision; silence on a positive task is still not rewarded. Macro recall averages only over positive tasks, since negative tasks have nothing to recall.
- **Matched comment** — precision TP counts generated comments, not edges. In `any-match`, any concrete positive match credits the comment once, even if other claims are wrong. This optimistic, gold-relative precision is not whole-comment correctness; unmatched output can include missing gold.
- **Covered gold** — recall counts unique required issues covered. One comment may cover several golds; repeated comments add no gold coverage. `one-to-one` retains the legacy assignment algorithm. An LLM judge evaluates all same-file pairs before either policy is applied.
- **Redundant matched comment** — in generated order, a positive comment adds no previously uncovered gold. It still earns comment precision credit in `any-match`; this is a coverage-noise diagnostic, not a factual duplicate verdict.
- **Ignored comment** — a generated comment matched to gold that the recorded scoring policy treats as neutral (optional findings, below-scope severity, or mechanical diagnostics). Removed from the scored generated set, so it neither earns recall nor counts against precision. Precision's denominator is scorable generated (generated minus ignored).
- **F1** — harmonic mean of precision and recall; balances both equally. (Special case of Fβ at β=1.)
- **Fβ** — generalized F-score with a tunable precision/recall trade-off:

  ```
  F_β = (1 + β²) · (P · R) / (β² · P + R)
  ```

  where *P* = precision, *R* = recall. β < 1 favors precision; β > 1 favors recall.
- **Fβ (β=0.5)** — precision-leaning; use when false positives are costly (noisy reviews waste reviewer time).
- **Fβ (β=2)** — recall-leaning; use when missing issues is costly.
- **Severity MAE** — mean absolute error between generated and expected severity levels over confirmed positive edges with known severities. Lower is better; `0` = exact match.
- **Valid review output rate** — fraction of runs whose output parsed into a structured review. Failures score 0 on every other metric.

</details>
"""


_CONSOLE_METRIC_EXPLANATIONS = (
    "[bold]Micro[/bold] — volume-weighted across all comments; sums matched comments, scorable generated (generated minus ignored), covered gold, and expected, so tasks with many comments dominate.\n"
    "[bold]Macro[/bold] — per-task P/R/F1 averaged equally; every task counts the same. Macro precision rewards correct silence on negative tasks but not on positive ones; macro recall averages only over positive tasks.\n"
    "[bold]Matched comment[/bold] — comment-level precision TP; any-match accepts a correct positive part, not necessarily the whole comment. Legacy one-to-one is separately labeled.\n"
    "[bold]Covered gold[/bold] — unique issues confirmed by the LLM judge for recall, independent of comment TP. Duplicate positive comments add no recall.\n"
    "[bold]Ignored comment[/bold] — matched gold treated as neutral by the recorded policy (optional, below-scope severity, or mechanical); removed from the scored generated set (no recall, no precision hit). Precision's denominator is scorable generated (generated minus ignored).\n"
    "[bold]F1[/bold] — harmonic mean of precision and recall (special case of Fβ at β=1).\n"
    "[bold]Fβ[/bold] — F_β = (1 + β²) · (P · R) / (β² · P + R); β<1 favors precision, β>1 favors recall.\n"
    "[bold]Fβ (β=0.5)[/bold] — precision-leaning; use when false positives are costly.\n"
    "[bold]Fβ (β=2)[/bold] — recall-leaning; use when missing issues is costly.\n"
    "[bold]Severity MAE[/bold] — mean absolute error of known severity levels over positive edges; lower is better, 0 = exact match.\n"
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
    *,
    repeatable_ignored_pairs: list[tuple[ReviewComment, ReviewComment]] | None = None,
    scoring_mode: CodeReviewScoringMode = CodeReviewScoringMode.LEGACY,
) -> tuple[list[tuple[ReviewComment, ReviewComment]], list[tuple[ReviewComment, ReviewComment]]]:
    """Apply the explicit positive/neutral policy to confirmed semantic edges."""
    repeatable = repeatable_ignored_pairs or []
    if scoring_mode == CodeReviewScoringMode.ANY_MATCH:
        positives = list({(id(gold), id(generated)): (gold, generated) for gold, generated in expected_pairs}.values())
        positive_outputs = {id(generated) for _, generated in positives}
        # One representative per neutral output; mechanical provenance wins neutral ties.
        neutral = {}
        for gold, generated in repeatable + ignored_pairs:
            if id(generated) not in positive_outputs:
                neutral.setdefault(id(generated), (gold, generated))
        return positives, list(neutral.values())
    pairs = expected_pairs + ignored_pairs + repeatable
    if not pairs:
        return [], []

    # Identity, not value equality: identical-looking findings are still separate comments.
    # Mechanical diagnostics have independent capacity per output, never per positive.
    keyed_pairs: list[tuple[tuple[int, int | None], ReviewComment, ReviewComment]] = [((id(gold), None), gold, generated) for gold, generated in expected_pairs + ignored_pairs]
    keyed_pairs += [((id(gold), id(generated)), gold, generated) for gold, generated in repeatable]
    gold_ids = dict.fromkeys(key for key, _, _ in keyed_pairs)
    generated_ids = dict.fromkeys(id(generated) for _, generated in pairs)
    rows = {key: index for index, key in enumerate(gold_ids)}
    columns = {key: index for index, key in enumerate(generated_ids)}
    edges = {(rows[key], columns[id(generated)]): (gold, generated) for key, gold, generated in keyed_pairs}
    expected_edges = {(rows[(id(gold), None)], columns[id(generated)]) for gold, generated in expected_pairs}
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


def _score_counts(matched_count: int, generated_count: int, expected_count: int, ignored_count: int, covered_gold_count: int | None = None) -> _ScoreCounts:
    """Derive the code-review scoring counts and precision/recall from raw match counts.

    Ignored comments are neutral: they leave the scored generated set (``generated - ignored``) so
    they neither earn recall (they are not expected) nor cost precision (they are not false
    positives). Extracted as a pure function so this critical metric math can be unit-tested
    independently of comment matching, the LLM judge, and I/O.
    """
    scored_generated_count = generated_count - ignored_count
    covered = matched_count if covered_gold_count is None else covered_gold_count
    if not (0 <= ignored_count <= generated_count and 0 <= matched_count <= scored_generated_count and 0 <= covered <= expected_count):
        raise ValueError("Inconsistent code-review comment or gold counts")
    precision = matched_count / scored_generated_count if scored_generated_count else 1.0
    recall = covered / expected_count if expected_count else 1.0
    return _ScoreCounts(
        matched=matched_count,
        incorrect=scored_generated_count - matched_count,
        missed=expected_count - covered,
        ignored=ignored_count,
        precision=precision,
        recall=recall,
    )


class JudgeVerdict(BaseModel):
    pair: int = Field(ge=1, strict=True)
    match: StrictBool
    reasoning: str | None = None


class SemanticMatchEdge(BaseModel):
    gold_bucket: Literal["expected", "ignored"]
    gold_index: int = Field(ge=0)
    generated_index: int = Field(ge=0)
    match: StrictBool
    reasoning: str | None = None


class ReviewJudgeEvidence(BaseModel):
    protocol: str
    prompt_template_sha256: str
    source_patch_sha256: str
    expected_comments: list[ReviewComment]
    ignored_comments: list[ReviewComment]
    edges: list[SemanticMatchEdge]


class CommentMatch(BaseModel):
    gold_index: int = Field(ge=0)
    generated_index: int = Field(ge=0)


class CodeReviewResult(JudgeScoredEvaluationResult):
    """Result for the code-review category."""

    generated_comments: list[ReviewComment] = Field(default_factory=list)
    expected_comments: list[ReviewComment] = Field(default_factory=list)
    ignored_comments: list[ReviewComment] = Field(default_factory=list)
    valid_review_output: bool = False
    minimum_severity: Severity | None = None
    out_of_scope_comments: list[ReviewComment] = Field(default_factory=list)
    out_of_scope_matched_comment_count: int = Field(default=0, ge=0)
    mechanical_diagnostics_neutral: bool = False
    mechanical_comments: list[ReviewComment] = Field(default_factory=list)
    mechanical_matched_comment_count: int = Field(default=0, ge=0)
    unscoped_result: "CodeReviewResult | None" = None
    legacy_result: "CodeReviewResult | None" = None
    scoring_mode: CodeReviewScoringMode = CodeReviewScoringMode.LEGACY
    judge_protocol: str = "same-issue-v1"
    judge_evidence: ReviewJudgeEvidence | None = None
    positive_matches: list[CommentMatch] = Field(default_factory=list)
    neutral_matches: list[CommentMatch] = Field(default_factory=list)
    covered_gold_count: int = Field(default=0, ge=0)
    redundant_matched_comment_count: int = Field(default=0, ge=0)
    severity_pair_count: int = Field(default=0, ge=0)

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

    @model_validator(mode="before")
    @classmethod
    def restore_legacy_counts(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("scoring_mode", CodeReviewScoringMode.LEGACY) == CodeReviewScoringMode.LEGACY:
            return {
                **value,
                "covered_gold_count": value.get("covered_gold_count", value.get("matched_comment_count", 0)),
                "severity_pair_count": value.get("severity_pair_count", value.get("matched_comment_count", 0)),
            }
        return value

    @model_validator(mode="after")
    def validate_matching_contract(self) -> Self:
        if self.scoring_mode == CodeReviewScoringMode.ANY_MATCH and self.valid_review_output:
            positive = {(match.gold_index, match.generated_index) for match in self.positive_matches}
            neutral = {(match.gold_index, match.generated_index) for match in self.neutral_matches}
            for matches, golds in ((positive, self.expected_comments), (neutral, self.ignored_comments)):
                for gold_index, generated_index in matches:
                    if gold_index >= len(golds) or generated_index >= len(self.generated_comments):
                        raise ValueError("Match index is outside its comment array")
                    if _normalize_path(golds[gold_index].file) != _normalize_path(self.generated_comments[generated_index].file):
                        raise ValueError("A match must be in the same normalized file")
            matched_outputs = {generated for _, generated in positive}
            neutral_outputs = {generated for _, generated in neutral}
            covered = {gold for gold, _ in positive}
            if len(positive) != len(self.positive_matches) or len(neutral_outputs) != len(self.neutral_matches) or matched_outputs & neutral_outputs:
                raise ValueError("Duplicate edges or overlapping positive/neutral comments")
            counts = _score_counts(len(matched_outputs), len(self.generated_comments), len(self.expected_comments), len(neutral_outputs), len(covered))
            if (self.matched_comment_count, self.covered_gold_count, self.incorrect_comment_count, self.missed_comment_count, self.ignored_matched_comment_count) != (
                counts.matched,
                len(covered),
                counts.incorrect,
                counts.missed,
                counts.ignored,
            ):
                raise ValueError("Stored counts disagree with comment matches or gold coverage")
            if abs(self.precision - counts.precision) > 1e-9 or abs(self.recall - counts.recall) > 1e-9:
                raise ValueError("Stored precision/recall disagree with their separate denominators")
        if self.judge_evidence is not None:
            evidence = self.judge_evidence
            eligible = {
                (bucket, gold_index, generated_index)
                for bucket, golds in (("expected", evidence.expected_comments), ("ignored", evidence.ignored_comments))
                for gold_index, gold in enumerate(golds)
                for generated_index, generated in enumerate(self.generated_comments)
                if _normalize_path(gold.file) == _normalize_path(generated.file)
            }
            actual = {(edge.gold_bucket, edge.gold_index, edge.generated_index) for edge in evidence.edges}
            if len(actual) != len(evidence.edges) or actual != eligible:
                raise ValueError("Judge evidence must contain every eligible same-file pair exactly once")
            if evidence.protocol != self.judge_protocol:
                raise ValueError("Judge evidence protocol differs from result identity")
        return self

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
        scoring_mode: CodeReviewScoringMode = CodeReviewScoringMode.LEGACY,
        judge_protocol: str = "same-issue-v1",
    ) -> Self:
        expected_indices = {id(comment): index for index, comment in enumerate(expected_comments)}
        ignored_indices = {id(comment): index for index, comment in enumerate(ignored_comments)}
        generated_indices = {id(comment): index for index, comment in enumerate(generated_comments)}
        positive_matches = [CommentMatch(gold_index=expected_indices[id(gold)], generated_index=generated_indices[id(generated)]) for gold, generated in matched_pairs]
        neutral_matches = [CommentMatch(gold_index=ignored_indices[id(gold)], generated_index=generated_indices[id(generated)]) for gold, generated in ignored_matched_pairs]
        matched_outputs = {match.generated_index for match in positive_matches}
        covered = {match.gold_index for match in positive_matches}
        neutral_outputs = {match.generated_index for match in neutral_matches}
        if matched_outputs & neutral_outputs or len(neutral_outputs) != len(neutral_matches):
            raise ValueError("A generated comment cannot be both positive and neutral or neutralized twice")
        if scoring_mode == CodeReviewScoringMode.LEGACY and (len(matched_outputs) != len(matched_pairs) or len(covered) != len(matched_pairs)):
            raise ValueError("Legacy matches must be one-to-one")
        seen_gold: set[int] = set()
        redundant = 0
        for index in sorted(matched_outputs):
            coverage = {match.gold_index for match in positive_matches if match.generated_index == index}
            redundant += int(not (coverage - seen_gold))
            seen_gold.update(coverage)
        scores = _score_counts(
            matched_count=len(matched_outputs),
            generated_count=len(generated_comments),
            expected_count=len(expected_comments),
            ignored_count=len(neutral_outputs),
            covered_gold_count=len(covered),
        )

        return cls(
            **cls._base_fields(context),
            output=output,
            expected_comments=expected_comments,
            generated_comments=generated_comments,
            ignored_comments=ignored_comments,
            valid_review_output=True,
            scoring_mode=scoring_mode,
            judge_protocol=judge_protocol,
            positive_matches=positive_matches,
            neutral_matches=neutral_matches,
            covered_gold_count=len(covered),
            redundant_matched_comment_count=redundant,
            severity_pair_count=sum(gold.severity is not None and generated.severity is not None for gold, generated in matched_pairs),
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
            "covered_gold_count": self.covered_gold_count,
            "redundant_matched_comment_count": self.redundant_matched_comment_count,
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
            "mechanical_diagnostics_neutral": self.mechanical_diagnostics_neutral,
            "mechanical_comment_count": len(self.mechanical_comments),
            "mechanical_matched_comment_count": self.mechanical_matched_comment_count,
            **(
                {
                    "minimum_severity_level": self.minimum_severity.level,
                    "out_of_scope_comment_count": len(self.out_of_scope_comments),
                    "out_of_scope_matched_comment_count": self.out_of_scope_matched_comment_count,
                }
                if self.minimum_severity is not None
                else {}
            ),
            **({f"unscoped_{key}": value for key, value in self.unscoped_result.category_metrics.items()} if self.unscoped_result is not None else {}),
            **({f"legacy_{key}": value for key, value in self.legacy_result.category_metrics.items()} if self.legacy_result is not None else {}),
        }

    @property
    @override
    def export_metadata(self) -> dict[str, str | int | float | bool | None]:
        return {
            **super().export_metadata,
            "scoring_scope": f"gold>={self.minimum_severity.value}" if self.minimum_severity is not None else "all-severity",
            "mechanical_diagnostics_neutral": self.mechanical_diagnostics_neutral,
            "scoring_mode": self.scoring_mode.value,
            "judge_protocol": self.judge_protocol,
        }

    @property
    @override
    def display_row(self) -> dict[str, str]:
        return {
            "Generated": str(len(self.generated_comments)),
            "Matched": str(self.matched_comment_count),
            "Covered gold": str(self.covered_gold_count),
            "Scoring": self.scoring_mode.value,
            "Expected": str(len(self.expected_comments)),
            "Precision": f"{self.precision:.2f}",
            "Recall": f"{self.recall:.2f}",
            "F1": f"{self.f1:.2f}",
            **({"Mechanical gold": str(len(self.mechanical_comments)), "Mechanical neutral": str(self.mechanical_matched_comment_count)} if self.mechanical_diagnostics_neutral else {}),
            **(
                {
                    "Gold scope": f">={self.minimum_severity}",
                    "Excluded gold": str(len(self.out_of_scope_comments)),
                    "Scope neutral": str(self.out_of_scope_matched_comment_count),
                    "Unscoped P/R/F1": f"{self.unscoped_result.precision:.2f}/{self.unscoped_result.recall:.2f}/{self.unscoped_result.f1:.2f}",
                }
                if self.unscoped_result is not None
                else {}
            ),
        }


class CodeReviewResultSummary(JudgeBasedEvaluationResultSummary):
    """
    Summary for the code-review category.

    Micro metrics aggregate matched/expected/generated comment counts across all results (volume-weighted).
    Macro metrics average per-task scores (each task weighted equally).
    """

    average_prompt_tokens: float | None = None
    average_completion_tokens: float | None = None
    minimum_severity: Severity | None = None
    out_of_scope_comment_count: int = Field(default=0, ge=0)
    out_of_scope_matched_comment_count: int = Field(default=0, ge=0)
    mechanical_diagnostics_neutral: bool = False
    mechanical_comment_count: int = Field(default=0, ge=0)
    mechanical_matched_comment_count: int = Field(default=0, ge=0)
    unscoped_summary: "CodeReviewResultSummary | None" = None
    legacy_summary: "CodeReviewResultSummary | None" = None
    scoring_mode: CodeReviewScoringMode = CodeReviewScoringMode.LEGACY
    judge_protocol: str = "same-issue-v1"
    covered_gold_count: int = Field(default=0, ge=0)
    redundant_matched_comment_count: int = Field(default=0, ge=0)

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

    @model_validator(mode="before")
    @classmethod
    def restore_legacy_coverage(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("scoring_mode", CodeReviewScoringMode.LEGACY) == CodeReviewScoringMode.LEGACY:
            return {**value, "covered_gold_count": value.get("covered_gold_count", value.get("matched_comment_count", 0))}
        return value

    @override
    def combination_key(self) -> tuple[str | None, ...]:
        return (*super().combination_key(), self.scoring_mode.value, self.judge_protocol)

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
        scope_markdown = ""
        if self.unscoped_summary is not None:
            original = self.unscoped_summary
            scope_markdown = (
                f"## Scoring scope: gold >= {self.minimum_severity}\n\n"
                f"Excluded gold: {self.out_of_scope_comment_count}; generated comments neutralized by scope: {self.out_of_scope_matched_comment_count}. "
                "The metrics below are scope-aligned. Generated comments are not filtered by their own severity or kind. Both scopes use the same judge verdicts and the recorded scoring mode.\n\n"
                f"Mechanical diagnostics are neutral in both views: {self.mechanical_comment_count} gold records, {self.mechanical_matched_comment_count} matched outputs. "
                "Mechanical outputs remain neutral, including duplicates. In any-match, all neutral-only outputs are excluded; in legacy, ordinary ignored and Low-only matches retain one-to-one capacity.\n\n"
                "| View | Expected | Matched comments | Covered gold | Incorrect | Ignored | Micro P | Micro R | Micro F1 |\n"
                "|------|---------:|-----------------:|-------------:|----------:|--------:|--------:|--------:|---------:|\n"
                f"| Unscoped (all-severity review findings) | {original.expected_comment_count} | {original.matched_comment_count} | {original.covered_gold_count} | {original.incorrect_comment_count} | {original.ignored_matched_comment_count} | "
                f"{original.precision:.1%} | {original.recall:.1%} | {original.f1:.1%} |\n"
                f"| Gold >= {self.minimum_severity} | {self.expected_comment_count} | {self.matched_comment_count} | {self.covered_gold_count} | {self.incorrect_comment_count} | {self.ignored_matched_comment_count} | "
                f"{self.precision:.1%} | {self.recall:.1%} | {self.f1:.1%} |\n\n"
            )
        legacy_markdown = ""
        if self.legacy_summary is not None:
            legacy = self.legacy_summary
            legacy_markdown = (
                "## Legacy assignment sensitivity (same new judge edges, not historical scores)\n\n"
                f"Comment TP: {legacy.matched_comment_count}; covered gold: {legacy.covered_gold_count}; "
                f"FP: {legacy.incorrect_comment_count}; FN: {legacy.missed_comment_count}; neutral: {legacy.ignored_matched_comment_count}; "
                f"micro P/R/F1: {legacy.precision:.1%}/{legacy.recall:.1%}/{legacy.f1:.1%}. "
                "The serialized legacy summary also retains its all-severity view.\n\n"
            )
        return (
            f"## Scoring mode: {self.scoring_mode.value}; judge protocol: {self.judge_protocol}\n\n"
            + scope_markdown
            + legacy_markdown
            + (
                "## Comment counts\n"
                "\n"
                "| Generated | Expected | Matched comments | Covered gold | Incorrect | Missed | Ignored | Redundant matched |\n"
                "|----------:|---------:|-----------------:|-------------:|----------:|-------:|--------:|------------------:|\n"
                f"| {self.generated_comment_count} | {self.expected_comment_count} | {self.matched_comment_count} | {self.covered_gold_count} | {self.incorrect_comment_count} | {self.missed_comment_count} | {self.ignored_matched_comment_count} | {self.redundant_matched_comment_count} |\n"
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
        )

    @override
    def render_console_metrics(self) -> RenderableType:
        metric_columns = ["Precision", "Recall", "F1", "Fβ (β=0.5)", "Fβ (β=2)"]

        scope_tables: list[RenderableType] = []
        if self.unscoped_summary is not None:
            original = self.unscoped_summary
            scope_tables = [
                _build_console_table(
                    f"Gold scope >= {self.minimum_severity} (following tables); all-severity review findings",
                    ["Unscoped P", "Unscoped R", "Unscoped F1", "Excluded gold", "Scope neutral"],
                    [f"{original.precision:.1%}", f"{original.recall:.1%}", f"{original.f1:.1%}", str(self.out_of_scope_comment_count), str(self.out_of_scope_matched_comment_count)],
                )
            ]
        if self.mechanical_diagnostics_neutral:
            scope_tables.append(
                _build_console_table(
                    "Mechanical diagnostics (neutral in both views; duplicate matches also neutral)",
                    ["Gold records", "Matched outputs"],
                    [str(self.mechanical_comment_count), str(self.mechanical_matched_comment_count)],
                )
            )
        return Group(
            f"Scoring mode: {self.scoring_mode.value}; judge protocol: {self.judge_protocol}",
            *(
                [f"Legacy same-edge P/R/F1: {self.legacy_summary.precision:.1%}/{self.legacy_summary.recall:.1%}/{self.legacy_summary.f1:.1%} (not historical scores)"]
                if self.legacy_summary is not None
                else []
            ),
            *scope_tables,
            _build_console_table(
                "Comment counts",
                ["Generated", "Expected", "Matched", "Covered gold", "Incorrect", "Missed", "Ignored", "Redundant"],
                [
                    str(self.generated_comment_count),
                    str(self.expected_comment_count),
                    str(self.matched_comment_count),
                    str(self.covered_gold_count),
                    str(self.incorrect_comment_count),
                    str(self.missed_comment_count),
                    str(self.ignored_matched_comment_count),
                    str(self.redundant_matched_comment_count),
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
        identities = {(r.scoring_mode, r.judge_protocol) for r in code_review_results}
        if len(identities) != 1:
            raise ValueError("Cannot summarize code-review results with different scoring modes or judge protocols")
        scoring_mode, judge_protocol = next(iter(identities))
        legacy_results = [r.legacy_result for r in code_review_results if r.legacy_result is not None]
        if legacy_results and len(legacy_results) != total_results:
            raise ValueError("Legacy comparison must be present for every result or none")
        legacy_summary = cls.from_results(legacy_results, run_id) if legacy_results else None
        scopes = {(r.minimum_severity, r.mechanical_diagnostics_neutral) for r in code_review_results if not r.timeout or r.mechanical_diagnostics_neutral or r.minimum_severity is not None}
        if len(scopes) > 1:
            raise ValueError("Cannot summarize code-review results with different severity scopes or mechanical policies")
        minimum_severity, mechanical_neutral = next(iter(scopes), (None, False))
        unscoped_summary = None
        if minimum_severity is not None:
            if any(r.unscoped_result is None and not r.timeout for r in code_review_results):
                raise ValueError("Scoped code-review results must preserve their unscoped result")
            unscoped_summary = cls.from_results([r.unscoped_result if r.unscoped_result is not None else r for r in code_review_results], run_id)

        generated_total: int = sum(len(r.generated_comments) for r in code_review_results)
        expected_total: int = sum(len(r.expected_comments) for r in code_review_results)
        matched_total: int = sum(r.matched_comment_count for r in code_review_results)
        covered_total = sum(r.covered_gold_count for r in code_review_results)
        incorrect_total: int = sum(r.incorrect_comment_count for r in code_review_results)
        missed_total: int = sum(r.missed_comment_count for r in code_review_results)
        ignored_total: int = sum(r.ignored_matched_comment_count for r in code_review_results)

        # Ignored comments are neutral, so they leave the scored generated set exactly as each
        # per-task precision already does -- keeping micro precision consistent with macro.
        scored_generated_total: int = generated_total - ignored_total
        precision = matched_total / scored_generated_total if scored_generated_total else 1.0
        recall = covered_total / expected_total if expected_total else 1.0
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

        weighted_mae_numerator: float = sum(r.severity_mae * r.severity_pair_count for r in code_review_results)
        weighted_mae_denominator: int = sum(r.severity_pair_count for r in code_review_results)
        severity_mae: float = weighted_mae_numerator / weighted_mae_denominator if weighted_mae_denominator > 0 else 0.0

        valid_output_count: int = sum(1 for r in code_review_results if r.valid_review_output)
        valid_output_rate: float = valid_output_count / total_results
        if valid_output_count == 0:
            precision = recall = f1 = f_beta_05 = f_beta_2 = 0.0
            macro_precision = macro_recall = macro_f1 = macro_f_beta_05 = macro_f_beta_2 = 0.0

        def average_metric(values: Sequence[int | float | None]) -> float | None:
            available = [value for value in values if value is not None]
            return sum(available) / len(available) if available else None

        return summary.model_copy(
            update={
                "minimum_severity": minimum_severity,
                "scoring_mode": scoring_mode,
                "judge_protocol": judge_protocol,
                "legacy_summary": legacy_summary,
                "covered_gold_count": covered_total,
                "redundant_matched_comment_count": sum(r.redundant_matched_comment_count for r in code_review_results),
                "mechanical_diagnostics_neutral": mechanical_neutral,
                "mechanical_comment_count": sum(len(r.mechanical_comments) for r in code_review_results),
                "mechanical_matched_comment_count": sum(r.mechanical_matched_comment_count for r in code_review_results),
                "unscoped_summary": unscoped_summary,
                "out_of_scope_comment_count": sum(len(r.out_of_scope_comments) for r in code_review_results),
                "out_of_scope_matched_comment_count": sum(r.out_of_scope_matched_comment_count for r in code_review_results),
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
