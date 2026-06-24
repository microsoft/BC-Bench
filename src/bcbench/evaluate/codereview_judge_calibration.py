"""Calibration set for the code-review LLM judge.

A small, hand-labeled set of (expected, candidate) comment pairs with a human verdict on
whether they describe the same underlying issue. Running the judge over this set yields its
precision/recall against human judgement, so judge drift is caught loudly instead of silently
distorting every code-review score.

The non-match cases deliberately share the same file and line as their pair so the judge cannot
pass on location alone — it must discriminate on the issue itself. The match cases deliberately
differ in wording, severity, or line so semantic equivalence is exercised.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bcbench.dataset.codereview import ReviewComment, Severity
from bcbench.evaluate.codereview_judge import JUDGE_MODEL, judge_verdicts


@dataclass(frozen=True)
class JudgeCalibrationCase:
    expected: ReviewComment
    candidate: ReviewComment
    should_match: bool
    note: str


@dataclass(frozen=True)
class JudgeCalibrationReport:
    total: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    accuracy: float
    misclassified_notes: list[str]


def _c(file: str, line: int, body: str, severity: Severity = Severity.MEDIUM) -> ReviewComment:
    return ReviewComment(file=file, line_start=line, body=body, severity=severity)


CALIBRATION_CASES: list[JudgeCalibrationCase] = [
    # --- Same issue, different wording / line / severity => should match ---
    JudgeCalibrationCase(
        expected=_c("src/Sales/SalesPost.Codeunit.al", 142, "Calling Commit() inside the repeat loop can leave partial data if a later iteration fails."),
        candidate=_c("src/Sales/SalesPost.Codeunit.al", 145, "Move the Commit() out of the loop; committing per iteration breaks atomicity."),
        should_match=True,
        note="commit-in-loop, paraphrased + different line",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Inventory/ItemAvail.Codeunit.al", 58, "Add SetLoadFields before FindSet so the whole record isn't loaded."),
        candidate=_c("src/Inventory/ItemAvail.Codeunit.al", 58, "Use SetLoadFields to limit the columns read for this query."),
        should_match=True,
        note="setloadfields performance, same issue",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Finance/Payment.Codeunit.al", 77, "Currency code 'USD' is hardcoded; read it from setup instead."),
        candidate=_c("src/Finance/Payment.Codeunit.al", 77, "Don't hardcode the currency — pull it from the configuration record."),
        should_match=True,
        note="hardcoded currency, same issue",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Sales/Customer.Codeunit.al", 33, "GET can fail when the customer is missing; handle the not-found case."),
        candidate=_c("src/Sales/Customer.Codeunit.al", 31, "Missing error handling if the GET on Customer returns false."),
        should_match=True,
        note="unchecked GET, same issue",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Sales/SalesLine.Table.al", 210, "You can't SetRange on a FlowField without calling CalcFields first."),
        candidate=_c("src/Sales/SalesLine.Table.al", 210, "Filtering directly on this FlowField won't work as written."),
        should_match=True,
        note="flowfield filter, same issue",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Reports/Statement.Report.al", 90, "Building the filter from a concatenated string risks filter injection; use SetFilter with parameters."),
        candidate=_c("src/Reports/Statement.Report.al", 92, "Use parameterized SetFilter instead of concatenating user input into the filter."),
        should_match=True,
        note="filter injection, same issue",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Inventory/Reorder.Codeunit.al", 120, "This runs a database read per record — an N+1 pattern."),
        candidate=_c("src/Inventory/Reorder.Codeunit.al", 118, "Querying inside the loop causes N+1 queries; batch the lookup."),
        should_match=True,
        note="n+1 query, same issue",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Sales/SalesPost.Codeunit.al", 60, "TestField(Quantity) is missing before posting."),
        candidate=_c("src/Sales/SalesPost.Codeunit.al", 60, "Validate that Quantity is set before posting, e.g. with TestField.", Severity.HIGH),
        should_match=True,
        note="missing testfield, severity differs",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Common/Util.Codeunit.al", 12, "Variable 'i' is declared but never used.", Severity.LOW),
        candidate=_c("src/Common/Util.Codeunit.al", 12, "Remove the unused variable i.", Severity.HIGH),
        should_match=True,
        note="unused variable, severity differs",
    ),
    # --- Different concern at the same location => should NOT match ---
    JudgeCalibrationCase(
        expected=_c("src/Sales/SalesPost.Codeunit.al", 142, "Calling Commit() inside the repeat loop can leave partial data on failure."),
        candidate=_c("src/Sales/SalesPost.Codeunit.al", 142, "The procedure name should be PascalCase to match conventions."),
        should_match=False,
        note="commit-in-loop vs naming style, same line",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Admin/UserSetup.Page.al", 45, "Missing permission/SecurityFiltering check before exposing this data."),
        candidate=_c("src/Admin/UserSetup.Page.al", 45, "Add a tooltip to this field for accessibility."),
        should_match=False,
        note="permission vs tooltip, same line",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Common/Loop.Codeunit.al", 88, "Off-by-one: the range 1..Count skips the last element."),
        candidate=_c("src/Common/Loop.Codeunit.al", 88, "Use a temporary record here to avoid locking the table."),
        should_match=False,
        note="off-by-one vs locking, same line",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Sales/Customer.Codeunit.al", 33, "Possible null/empty reference: 'Customer' may be blank after the failed GET."),
        candidate=_c("src/Sales/Customer.Codeunit.al", 33, "Add a comment explaining what this block does."),
        should_match=False,
        note="null-ref vs missing comment, same line",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Inventory/ItemAvail.Codeunit.al", 58, "Use IsEmpty() instead of Count() = 0 for performance."),
        candidate=_c("src/Inventory/ItemAvail.Codeunit.al", 58, "This label text needs to be translated/localized."),
        should_match=False,
        note="isempty perf vs localization, same line",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Finance/Payment.Codeunit.al", 77, "Currency code 'USD' is hardcoded; read it from setup."),
        candidate=_c("src/Finance/Payment.Codeunit.al", 77, "The magic number 1000 should be extracted into a named constant."),
        should_match=False,
        note="hardcoded currency vs magic number — both 'hardcoding' but different code",
    ),
    JudgeCalibrationCase(
        expected=_c("src/Inventory/Reorder.Codeunit.al", 118, "FindSet(true) should be FindSet(false) since records aren't modified."),
        candidate=_c("src/Inventory/Reorder.Codeunit.al", 118, "Add SetLoadFields before this FindSet to limit columns."),
        should_match=False,
        note="findset write-intent vs setloadfields — both about the same FindSet, different issue",
    ),
]


def score_calibration(predicted: list[bool], cases: list[JudgeCalibrationCase] = CALIBRATION_CASES) -> JudgeCalibrationReport:
    if len(predicted) != len(cases):
        raise ValueError(f"Expected {len(cases)} verdicts, got {len(predicted)}")

    tp = fp = tn = fn = 0
    misclassified: list[str] = []
    for verdict, case in zip(predicted, cases, strict=True):
        if verdict and case.should_match:
            tp += 1
        elif verdict and not case.should_match:
            fp += 1
            misclassified.append(f"FALSE POSITIVE: {case.note}")
        elif not verdict and case.should_match:
            fn += 1
            misclassified.append(f"FALSE NEGATIVE: {case.note}")
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    accuracy = (tp + tn) / len(cases) if cases else 0.0

    return JudgeCalibrationReport(
        total=len(cases),
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        accuracy=accuracy,
        misclassified_notes=misclassified,
    )


def run_calibration(work_dir: Path, model: str = JUDGE_MODEL, cases: list[JudgeCalibrationCase] = CALIBRATION_CASES) -> JudgeCalibrationReport:
    """Run the live judge over the calibration set and score it against the human labels.

    Requires the Copilot CLI (raises LLMJudgeError otherwise).
    """
    pairs = [(case.expected, case.candidate) for case in cases]
    verdicts = judge_verdicts(pairs, work_dir, model=model)
    return score_calibration(verdicts, cases)
