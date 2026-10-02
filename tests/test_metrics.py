"""Tests for the metrics module."""

import pytest

from bcbench.results.metrics import bootstrap_ci


class TestBootstrapCI:
    def test_returns_none_ci_for_single_value(self):
        result = bootstrap_ci([0.5])
        assert result["ci_low"] is None
        assert result["ci_high"] is None
        assert result["mean"] == 0.5

    def test_returns_none_ci_for_empty_list(self):
        result = bootstrap_ci([])
        assert result["ci_low"] is None
        assert result["ci_high"] is None
        assert result["mean"] == 0.0

    def test_returns_none_ci_for_identical_values(self):
        result = bootstrap_ci([0.5, 0.5, 0.5])
        assert result["ci_low"] is None
        assert result["ci_high"] is None

    def test_returns_positive_width_for_varying_values(self):
        result = bootstrap_ci([0.4, 0.5, 0.6])
        assert result["ci_low"] is not None
        assert result["ci_high"] is not None
        assert result["ci_high"] > result["ci_low"]

    def test_wider_ci_for_more_variance(self):
        low_var = bootstrap_ci([0.49, 0.50, 0.51])
        high_var = bootstrap_ci([0.3, 0.5, 0.7])
        assert low_var["ci_high"] is not None
        assert low_var["ci_low"] is not None
        assert high_var["ci_high"] is not None
        assert high_var["ci_low"] is not None
        low_width = low_var["ci_high"] - low_var["ci_low"]
        high_width = high_var["ci_high"] - high_var["ci_low"]
        assert high_width > low_width

    def test_narrower_ci_for_more_samples(self):
        few = bootstrap_ci([0.4, 0.6])
        many = bootstrap_ci([0.4, 0.5, 0.5, 0.5, 0.6])
        assert few["ci_high"] is not None
        assert few["ci_low"] is not None
        assert many["ci_high"] is not None
        assert many["ci_low"] is not None
        few_width = few["ci_high"] - few["ci_low"]
        many_width = many["ci_high"] - many["ci_low"]
        assert many_width < few_width

    def test_deterministic_with_seed(self):
        result1 = bootstrap_ci([0.3, 0.5, 0.7, 0.4, 0.6])
        result2 = bootstrap_ci([0.3, 0.5, 0.7, 0.4, 0.6])
        assert result1["ci_low"] == result2["ci_low"]
        assert result1["ci_high"] == result2["ci_high"]

    def test_returns_mean(self):
        result = bootstrap_ci([0.4, 0.6])
        assert result["mean"] == pytest.approx(0.5)

    def test_returns_ci_bounds(self):
        result = bootstrap_ci([0.3, 0.5, 0.7])
        assert result["ci_low"] is not None
        assert result["ci_high"] is not None
        assert result["ci_low"] < result["ci_high"]

    def test_does_not_return_bootstrap_means(self):
        result = bootstrap_ci([0.3, 0.5, 0.7])
        assert "bootstrap_means" not in result

    def test_ci_contains_mean(self):
        result = bootstrap_ci([0.3, 0.5, 0.7])
        ci_low = result["ci_low"]
        ci_high = result["ci_high"]
        mean = result["mean"]
        assert ci_low is not None
        assert ci_high is not None
        assert mean is not None
        assert ci_low <= mean <= ci_high
