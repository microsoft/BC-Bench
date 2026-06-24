import os

import pytest

from bcbench.evaluate.codereview_judge import _find_copilot
from bcbench.evaluate.codereview_judge_calibration import (
    CALIBRATION_CASES,
    run_calibration,
    score_calibration,
)


class TestCalibrationDataset:
    def test_has_both_match_and_non_match_cases(self):
        matches = [c for c in CALIBRATION_CASES if c.should_match]
        non_matches = [c for c in CALIBRATION_CASES if not c.should_match]
        assert len(matches) >= 5
        assert len(non_matches) >= 5

    def test_notes_are_unique(self):
        notes = [c.note for c in CALIBRATION_CASES]
        assert len(notes) == len(set(notes))

    def test_gold_labels_score_perfectly_against_themselves(self):
        predicted = [c.should_match for c in CALIBRATION_CASES]
        report = score_calibration(predicted)
        assert report.precision == 1.0
        assert report.recall == 1.0
        assert report.accuracy == 1.0
        assert report.misclassified_notes == []


class TestScoreCalibration:
    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="verdicts"):
            score_calibration([True])

    def test_counts_confusion_matrix(self):
        cases = CALIBRATION_CASES
        # Predict everything as a match: every true match is a TP, every non-match is a FP.
        report = score_calibration([True] * len(cases))
        expected_matches = sum(c.should_match for c in cases)
        assert report.true_positives == expected_matches
        assert report.false_positives == len(cases) - expected_matches
        assert report.false_negatives == 0
        assert report.recall == 1.0

    def test_all_wrong_predictions(self):
        cases = CALIBRATION_CASES
        report = score_calibration([not c.should_match for c in cases])
        assert report.true_positives == 0
        assert report.accuracy == 0.0
        assert len(report.misclassified_notes) == len(cases)


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("BCBENCH_RUN_JUDGE_CALIBRATION") or _find_copilot() is None,
    reason="Live judge calibration is opt-in (set BCBENCH_RUN_JUDGE_CALIBRATION and install the Copilot CLI)",
)
def test_live_judge_meets_accuracy_threshold(tmp_path):
    report = run_calibration(tmp_path)
    assert report.accuracy >= 0.8, f"Judge accuracy {report.accuracy:.3f} below threshold; misclassified: {report.misclassified_notes}"
