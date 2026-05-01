"""Tests for the metrics module."""

import pytest

from bcbench.results.metrics import bootstrap_ci, pass_at_k, pass_hat_k


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


class TestPassHatK:
    def test_all_successes(self):
        # C(3,3)/C(3,3) = 1.0
        assert pass_hat_k(num_trials=3, success_count=3, k=3) == 1.0

    def test_no_successes(self):
        # C(0,3)/C(3,3) = 0.0
        assert pass_hat_k(num_trials=3, success_count=0, k=3) == 0.0

    def test_partial_success_k1(self):
        # C(2,1)/C(3,1) = 2/3
        result = pass_hat_k(num_trials=3, success_count=2, k=1)
        assert abs(result - 2 / 3) < 1e-9

    def test_partial_success_k2(self):
        # C(2,2)/C(3,2) = 1/3
        result = pass_hat_k(num_trials=3, success_count=2, k=2)
        assert abs(result - 1 / 3) < 1e-9

    def test_insufficient_successes_for_k(self):
        # C(1,3)/C(3,3) = 0 (can't choose 3 from 1)
        assert pass_hat_k(num_trials=3, success_count=1, k=3) == 0.0

    def test_raises_when_trials_less_than_k(self):
        with pytest.raises(ValueError, match="Number of trials 2 is less than k 3"):
            pass_hat_k(num_trials=2, success_count=2, k=3)

    def test_k_equals_1_is_success_rate(self):
        # pass^1 should equal success_count / num_trials
        assert pass_hat_k(num_trials=10, success_count=7, k=1) == 0.7

    def test_large_numbers(self):
        # With 10 trials and 8 successes, k=5
        # C(8,5)/C(10,5) = 56/252 = 2/9
        result = pass_hat_k(num_trials=10, success_count=8, k=5)
        assert abs(result - 56 / 252) < 1e-9


class TestPassAtK:
    def test_all_correct(self):
        # If all samples are correct, pass@k = 1.0
        assert pass_at_k(num_samples=5, num_correct=5, k=1) == 1.0
        assert pass_at_k(num_samples=5, num_correct=5, k=5) == 1.0

    def test_none_correct(self):
        # If no samples are correct, pass@k = 0.0
        assert pass_at_k(num_samples=5, num_correct=0, k=1) == 0.0
        assert pass_at_k(num_samples=5, num_correct=0, k=3) == 0.0

    def test_one_correct_k1(self):
        # With 1 correct out of 5, pass@1 = 1 - C(4,1)/C(5,1) = 1 - 4/5 = 0.2
        result = pass_at_k(num_samples=5, num_correct=1, k=1)
        assert abs(result - 0.2) < 1e-9

    def test_one_correct_k5(self):
        # With 1 correct out of 5, pass@5 = 1 - C(4,5)/C(5,5) = 1 - 0 = 1.0
        result = pass_at_k(num_samples=5, num_correct=1, k=5)
        assert result == 1.0

    def test_half_correct(self):
        # With 3 correct out of 6, pass@1 = 1 - C(3,1)/C(6,1) = 1 - 3/6 = 0.5
        result = pass_at_k(num_samples=6, num_correct=3, k=1)
        assert abs(result - 0.5) < 1e-9

    def test_raises_when_samples_less_than_k(self):
        with pytest.raises(ValueError, match="Number of samples 2 is less than k 3"):
            pass_at_k(num_samples=2, num_correct=1, k=3)

    def test_returns_1_when_enough_correct(self):
        # If n - c < k, return 1.0 (guaranteed success)
        # 5 samples, 4 correct, k=2: n-c=1 < k=2, so return 1.0
        assert pass_at_k(num_samples=5, num_correct=4, k=2) == 1.0

    def test_openai_example(self):
        # Test case from OpenAI's human-eval
        # n=10, c=3, k=1: 1 - C(7,1)/C(10,1) = 1 - 7/10 = 0.3
        result = pass_at_k(num_samples=10, num_correct=3, k=1)
        assert abs(result - 0.3) < 1e-9

    def test_pass_at_k_increases_with_k(self):
        # pass@k should increase (or stay same) as k increases
        results = [pass_at_k(num_samples=10, num_correct=3, k=k) for k in range(1, 11)]
        for i in range(len(results) - 1):
            assert results[i] <= results[i + 1]


class TestMetricsRelationship:
    def test_pass_at_1_equals_pass_hat_1_for_single_trial(self):
        # With k=1, both metrics equal success_count/num_trials
        for n in range(1, 10):
            for c in range(n + 1):
                pass_at = pass_at_k(num_samples=n, num_correct=c, k=1)
                pass_hat = pass_hat_k(num_trials=n, success_count=c, k=1)
                assert abs(pass_at - pass_hat) < 1e-9

    def test_pass_at_k_geq_pass_hat_k(self):
        # pass@k >= pass^k always (optimistic vs pessimistic)
        for n in range(1, 8):
            for c in range(n + 1):
                for k in range(1, n + 1):
                    pass_at = pass_at_k(num_samples=n, num_correct=c, k=k)
                    pass_hat = pass_hat_k(num_trials=n, success_count=c, k=k)
                    assert pass_at >= pass_hat - 1e-9, f"n={n}, c={c}, k={k}: pass@k={pass_at} < pass^k={pass_hat}"
