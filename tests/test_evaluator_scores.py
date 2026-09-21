import pytest

from evaluator.scores import BuildRate, PostPatchPassedRate, PrePatchFailedRate, ResolutionRate


@pytest.mark.parametrize(
    ("scorer", "score_key"),
    [
        (ResolutionRate(), "resolved"),
        (BuildRate(), "build"),
        (PrePatchFailedRate(), "pre_patch_failed"),
        (PostPatchPassedRate(), "post_patch_passed"),
    ],
)
@pytest.mark.parametrize("score", [False, True])
def test_execution_scorers_omit_infrastructure_failures(scorer, score_key, score):
    assert scorer(metadata={score_key: score, "infrastructure_failure": True}) is None


@pytest.mark.parametrize(
    ("scorer", "score_key"),
    [
        (ResolutionRate(), "resolved"),
        (BuildRate(), "build"),
        (PrePatchFailedRate(), "pre_patch_failed"),
        (PostPatchPassedRate(), "post_patch_passed"),
    ],
)
@pytest.mark.parametrize("infrastructure_failure", [None, False])
@pytest.mark.parametrize("score", [False, True])
def test_execution_scorers_preserve_legacy_scores(scorer, score_key, infrastructure_failure, score):
    metadata = {score_key: score}
    if infrastructure_failure is not None:
        metadata["infrastructure_failure"] = infrastructure_failure

    assert scorer(metadata=metadata) is score
