import json
from datetime import date

import pytest

from bcbench.config import get_config
from bcbench.results.evaluation_result import EvaluationResultSummary
from bcbench.types import AgentMetrics, EvaluationCategory, ExperimentConfiguration
from tests.conftest import create_bugfix_result, create_testgen_result

_config = get_config()


class TestEvaluationResultSummary:
    def test_summary_save_creates_json_file(self, tmp_path):
        summary = EvaluationResultSummary(
            total=10,
            resolved=8,
            failed=2,
            build=9,
            percentage=80.0,
            date=date(2025, 1, 15),
            model="gpt-4o",
            category=EvaluationCategory.BUG_FIX,
            agent_name="copilot-cli",
            average_duration=120.5,
            average_prompt_tokens=5000.0,
            average_completion_tokens=1200.0,
            average_llm_duration=80.0,
        )

        summary_file = "test.json"
        summary.save(tmp_path, summary_file)

        output_file = tmp_path / summary_file
        assert output_file.exists()

        with open(output_file) as f:
            data = json.load(f)

        assert data["total"] == 10
        assert data["resolved"] == 8
        assert data["failed"] == 2
        assert data["build"] == 9
        assert data["date"] == "2025-01-15"
        assert data["model"] == "gpt-4o"
        assert data["agent_name"] == "copilot-cli"
        assert data["average_duration"] == 120.5
        assert data["average_prompt_tokens"] == 5000.0
        assert data["average_completion_tokens"] == 1200.0

    def test_summary_save_with_custom_filename(self, tmp_path):
        summary = EvaluationResultSummary(
            total=5,
            resolved=4,
            failed=1,
            build=5,
            percentage=80.0,
            date=date(2025, 1, 20),
            model="gpt-4",
            category=EvaluationCategory.TEST_GENERATION,
            agent_name="mini-bc-agent",
            average_duration=90.0,
            average_prompt_tokens=3000.0,
            average_completion_tokens=800.0,
            average_llm_duration=60.0,
        )

        summary.save(tmp_path, summary_file="custom_summary.json")

        output_file = tmp_path / "custom_summary.json"
        assert output_file.exists()

    def test_loading_existing_results(self):
        from bcbench.results.evaluation_result import Leaderboard

        for category in EvaluationCategory:
            leaderboard_path = _config.paths.leaderboard_dir / f"{category.value}.json"

            with open(leaderboard_path, encoding="utf-8") as f:
                data = json.load(f)
                # New format: {"runs": [...], "aggregate": [...]}
                if "runs" in data and "aggregate" in data:
                    Leaderboard.model_validate(data)
                else:
                    # Old format: array of items
                    for item in data:
                        EvaluationResultSummary.model_validate(item)


class TestFromResults:
    @pytest.fixture
    def sample_results(self):
        return [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=5000, completion_tokens=1000),
            ),
            create_bugfix_result(
                instance_id="test__2",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=150.0, prompt_tokens=6000, completion_tokens=1500),
            ),
            create_bugfix_result(
                instance_id="test__3",
                project="app",
                resolved=False,
                build=False,
                error_message="Build failed",
                metrics=AgentMetrics(execution_time=80.0, prompt_tokens=4000, completion_tokens=800),
            ),
        ]

    def test_from_results_creates_correct_summary(self, sample_results):
        summary = EvaluationResultSummary.from_results(sample_results, run_id="test_run_123")

        assert summary.total == 3
        assert summary.resolved == 2
        assert summary.failed == 1
        assert summary.build == 2
        assert summary.model == "gpt-4o"
        assert summary.agent_name == "copilot-cli"
        assert summary.github_run_id == "test_run_123"
        assert summary.date == date.today()

    def test_from_results_calculates_averages_correctly(self, sample_results):
        summary = EvaluationResultSummary.from_results(sample_results, run_id="test_run_123")

        # Average duration: (100 + 150 + 80) / 3 = 110
        assert summary.average_duration == pytest.approx(110.0)
        # Average prompt tokens: (5000 + 6000 + 4000) / 3 = 5000
        assert summary.average_prompt_tokens == pytest.approx(5000.0)
        # Average completion tokens: (1000 + 1500 + 800) / 3 = 1100
        assert summary.average_completion_tokens == pytest.approx(1100.0)

    def test_from_results_handles_none_values_in_metrics(self):
        results = [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=5000, completion_tokens=1000),
            ),
            create_bugfix_result(
                instance_id="test__2",
                project="app",
                resolved=False,
                build=False,
                error_message="Error",
                metrics=None,
            ),
        ]

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        # Should only average non-None values
        assert summary.average_duration == pytest.approx(100.0)
        assert summary.average_prompt_tokens == pytest.approx(5000.0)
        assert summary.average_completion_tokens == pytest.approx(1000.0)

    def test_from_results_with_all_none_metrics_returns_zero(self):
        results = [
            create_testgen_result(
                instance_id="test__1",
                project="app",
                resolved=False,
                build=False,
                error_message="Error",
                metrics=None,
            ),
        ]

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        assert summary.average_duration == 0.0
        assert summary.average_prompt_tokens == 0.0
        assert summary.average_completion_tokens == 0.0

    def test_from_results_calculates_average_tool_usage(self):
        results = [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(
                    execution_time=100.0,
                    tool_usage={"bash": 10, "view": 5},
                ),
            ),
            create_bugfix_result(
                instance_id="test__2",
                project="app",
                resolved=True,
                metrics=AgentMetrics(
                    execution_time=100.0,
                    tool_usage={"bash": 6, "view": 3, "edit": 2},
                ),
            ),
        ]

        summary = EvaluationResultSummary.from_results(results, run_id="test_run")

        assert summary.average_tool_usage is not None
        # bash: (10 + 6) / 2 = 8
        assert summary.average_tool_usage["bash"] == 8
        # view: (5 + 3) / 2 = 4
        assert summary.average_tool_usage["view"] == 4
        # edit: (0 + 2) / 2 = 1
        assert summary.average_tool_usage["edit"] == 1

    def test_from_results_handles_no_tool_usage(self):
        results = [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0),
            ),
        ]

        summary = EvaluationResultSummary.from_results(results, run_id="test_run")

        assert summary.average_tool_usage is None


class TestExperimentConfiguration:
    def test_is_empty_with_all_defaults(self):
        experiment = ExperimentConfiguration()
        assert experiment.is_empty() is True

    def test_is_empty_with_explicit_defaults(self):
        experiment = ExperimentConfiguration(mcp_servers=None, custom_instructions=False, custom_agent=None)
        assert experiment.is_empty() is True

    def test_is_empty_with_mcp_servers(self):
        experiment = ExperimentConfiguration(mcp_servers=["pylance"])
        assert experiment.is_empty() is False

    def test_is_empty_with_custom_instructions(self):
        experiment = ExperimentConfiguration(custom_instructions=True)
        assert experiment.is_empty() is False

    def test_is_empty_with_custom_agent(self):
        experiment = ExperimentConfiguration(custom_agent="my-agent")
        assert experiment.is_empty() is False

    def test_summary_with_experiment_configuration(self):
        experiment = ExperimentConfiguration(
            mcp_servers=["pylance", "filesystem"],
            custom_instructions=True,
            custom_agent="custom-bc-agent",
        )
        summary = EvaluationResultSummary(
            total=5,
            resolved=3,
            failed=2,
            build=4,
            percentage=60.0,
            date=date(2025, 1, 15),
            model="gpt-4o",
            category=EvaluationCategory.BUG_FIX,
            agent_name="copilot-cli",
            average_duration=100.0,
            average_prompt_tokens=4000.0,
            average_completion_tokens=1000.0,
            average_llm_duration=70.0,
            experiment=experiment,
        )

        assert summary.experiment is not None
        assert summary.experiment.mcp_servers == ["pylance", "filesystem"]
        assert summary.experiment.custom_instructions is True
        assert summary.experiment.custom_agent == "custom-bc-agent"

    def test_summary_without_experiment_configuration(self):
        summary = EvaluationResultSummary(
            total=5,
            resolved=3,
            failed=2,
            build=4,
            percentage=60.0,
            date=date(2025, 1, 15),
            model="gpt-4o",
            category=EvaluationCategory.BUG_FIX,
            agent_name="copilot-cli",
            average_duration=100.0,
            average_prompt_tokens=4000.0,
            average_completion_tokens=1000.0,
            average_llm_duration=70.0,
        )

        assert summary.experiment is None

    def test_summary_save_includes_experiment_in_json(self, tmp_path):
        experiment = ExperimentConfiguration(
            mcp_servers=["pylance"],
            custom_instructions=True,
        )
        summary = EvaluationResultSummary(
            total=10,
            resolved=8,
            failed=2,
            build=9,
            percentage=80.0,
            date=date(2025, 1, 15),
            model="gpt-4o",
            category=EvaluationCategory.BUG_FIX,
            agent_name="copilot-cli",
            average_duration=120.5,
            average_prompt_tokens=5000.0,
            average_completion_tokens=1200.0,
            average_llm_duration=80.0,
            experiment=experiment,
        )

        summary.save(tmp_path, "summary_with_experiment.json")

        with open(tmp_path / "summary_with_experiment.json") as f:
            data = json.load(f)

        assert "experiment" in data
        assert data["experiment"]["mcp_servers"] == ["pylance"]
        assert data["experiment"]["custom_instructions"] is True
        assert data["experiment"]["custom_agent"] is None

    def test_summary_save_with_none_experiment(self, tmp_path):
        summary = EvaluationResultSummary(
            total=5,
            resolved=3,
            failed=2,
            build=4,
            percentage=60.0,
            date=date(2025, 1, 15),
            model="gpt-4o",
            category=EvaluationCategory.BUG_FIX,
            agent_name="copilot-cli",
            average_duration=100.0,
            average_prompt_tokens=4000.0,
            average_completion_tokens=1000.0,
            average_llm_duration=70.0,
            experiment=None,
        )

        summary.save(tmp_path, "summary_no_experiment.json")

        with open(tmp_path / "summary_no_experiment.json") as f:
            data = json.load(f)

        assert data["experiment"] is None

    def test_from_results_extracts_experiment_from_first_result(self):
        experiment = ExperimentConfiguration(
            mcp_servers=["pylance", "filesystem"],
            custom_instructions=True,
            custom_agent="custom-bc-agent",
        )
        results = [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=5000, completion_tokens=1000),
            ),
            create_bugfix_result(
                instance_id="test__2",
                project="app",
                resolved=False,
                metrics=AgentMetrics(execution_time=150.0, prompt_tokens=6000, completion_tokens=1500),
            ),
        ]
        # Set experiment on the first result
        results[0].experiment = experiment

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        assert summary.experiment is not None
        assert summary.experiment.mcp_servers == ["pylance", "filesystem"]
        assert summary.experiment.custom_instructions is True
        assert summary.experiment.custom_agent == "custom-bc-agent"

    def test_from_results_with_no_experiment_returns_none(self):
        results = [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=5000, completion_tokens=1000),
            ),
        ]

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        assert summary.experiment is None

    def test_from_results_normalizes_empty_experiment_to_none(self):
        results = [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=5000, completion_tokens=1000),
            ),
        ]
        # Set an empty experiment config (all defaults)
        results[0].experiment = ExperimentConfiguration()

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        # Should be normalized to None
        assert summary.experiment is None

    def test_from_results_normalizes_explicit_empty_experiment_to_none(self):
        results = [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=5000, completion_tokens=1000),
            ),
        ]
        # Set an explicitly empty experiment config
        results[0].experiment = ExperimentConfiguration(mcp_servers=None, custom_instructions=False, custom_agent=None)

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        # Should be normalized to None
        assert summary.experiment is None

    def test_from_results_preserves_non_empty_experiment(self):
        experiment = ExperimentConfiguration(mcp_servers=["pylance"], custom_instructions=True)
        results = [
            create_bugfix_result(
                instance_id="test__1",
                project="app",
                resolved=True,
                metrics=AgentMetrics(execution_time=100.0, prompt_tokens=5000, completion_tokens=1000),
            ),
        ]
        results[0].experiment = experiment

        summary = EvaluationResultSummary.from_results(results, run_id="test_run_123")

        # Should preserve non-empty experiment
        assert summary.experiment is not None
        assert summary.experiment.mcp_servers == ["pylance"]
        assert summary.experiment.custom_instructions is True


class TestInstanceResults:
    def test_from_results_creates_instance_results(self):
        results = [
            create_bugfix_result(instance_id="test__1", resolved=True),
            create_bugfix_result(instance_id="test__2", resolved=False),
            create_bugfix_result(instance_id="test__3", resolved=True),
        ]

        summary = EvaluationResultSummary.from_results(results, run_id="test_run")

        assert summary.instance_results is not None
        assert len(summary.instance_results) == 3
        assert summary.instance_results["test__1"] is True
        assert summary.instance_results["test__2"] is False
        assert summary.instance_results["test__3"] is True


class TestLeaderboardAggregate:
    def test_from_single_run_calculates_pass_hat_1(self):
        from bcbench.results.evaluation_result import LeaderboardAggregate

        summary = EvaluationResultSummary.from_results(
            [
                create_bugfix_result(instance_id="test__1", resolved=True),
                create_bugfix_result(instance_id="test__2", resolved=False),
                create_bugfix_result(instance_id="test__3", resolved=True),
            ],
            run_id="run_1",
        )

        agg = LeaderboardAggregate.from_runs([summary])

        assert agg.num_runs == 1
        assert agg.total == 3
        # With 1 run: pass^1 = avg of C(s,1)/C(1,1) = (1 + 0 + 1)/3 = 0.667
        assert agg.pass_hat_1 == 0.667
        assert agg.pass_hat_3 is None  # Not enough runs
        assert agg.pass_hat_5 is None

    def test_from_multiple_runs_calculates_pass_k(self):
        from bcbench.results.evaluation_result import LeaderboardAggregate

        run1 = EvaluationResultSummary.from_results(
            [
                create_bugfix_result(instance_id="test__1", resolved=True),
                create_bugfix_result(instance_id="test__2", resolved=False),
                create_bugfix_result(instance_id="test__3", resolved=False),
            ],
            run_id="run_1",
        )
        run2 = EvaluationResultSummary.from_results(
            [
                create_bugfix_result(instance_id="test__1", resolved=False),
                create_bugfix_result(instance_id="test__2", resolved=True),
                create_bugfix_result(instance_id="test__3", resolved=False),
            ],
            run_id="run_2",
        )
        run3 = EvaluationResultSummary.from_results(
            [
                create_bugfix_result(instance_id="test__1", resolved=False),
                create_bugfix_result(instance_id="test__2", resolved=False),
                create_bugfix_result(instance_id="test__3", resolved=True),
            ],
            run_id="run_3",
        )

        agg = LeaderboardAggregate.from_runs([run1, run2, run3])

        assert agg.num_runs == 3
        assert agg.total == 3
        # pass^1: average of individual pass^1 values
        # test__1: 1/3 successes -> C(1,1)/C(3,1) = 1/3
        # test__2: 1/3 successes -> C(1,1)/C(3,1) = 1/3
        # test__3: 1/3 successes -> C(1,1)/C(3,1) = 1/3
        # Average = 1/3 = 0.333
        assert agg.pass_hat_1 == 0.333
        # pass^3: C(1,3)/C(3,3) = 0 for each (can't pick 3 successes from 1)
        assert agg.pass_hat_3 == 0.0
        # pass^5: not enough runs
        assert agg.pass_hat_5 is None

    def test_pass_hat_k_calculation(self):
        from bcbench.results.evaluation_result import LeaderboardAggregate

        # Create 3 runs where:
        # - test__1: resolved in runs 1,2,3 (3/3 successes)
        # - test__2: resolved in runs 1,2 only (2/3 successes)
        # - test__3: resolved in run 1 only (1/3 successes)
        run1 = EvaluationResultSummary.from_results(
            [
                create_bugfix_result(instance_id="test__1", resolved=True),
                create_bugfix_result(instance_id="test__2", resolved=True),
                create_bugfix_result(instance_id="test__3", resolved=True),
            ],
            run_id="run_1",
        )
        run2 = EvaluationResultSummary.from_results(
            [
                create_bugfix_result(instance_id="test__1", resolved=True),
                create_bugfix_result(instance_id="test__2", resolved=True),
                create_bugfix_result(instance_id="test__3", resolved=False),
            ],
            run_id="run_2",
        )
        run3 = EvaluationResultSummary.from_results(
            [
                create_bugfix_result(instance_id="test__1", resolved=True),
                create_bugfix_result(instance_id="test__2", resolved=False),
                create_bugfix_result(instance_id="test__3", resolved=False),
            ],
            run_id="run_3",
        )

        agg = LeaderboardAggregate.from_runs([run1, run2, run3])

        # pass^1: Average of C(s,1)/C(3,1) for each instance
        # test__1: C(3,1)/C(3,1) = 1.0
        # test__2: C(2,1)/C(3,1) = 2/3
        # test__3: C(1,1)/C(3,1) = 1/3
        # Average = (1 + 2/3 + 1/3) / 3 = 2/3 = 0.667
        assert agg.pass_hat_1 == 0.667
        # pass^3: C(s,3)/C(3,3) for each instance
        # test__1: C(3,3)/C(3,3) = 1.0
        # test__2: C(2,3)/C(3,3) = 0 (can't choose 3 from 2)
        # test__3: C(1,3)/C(3,3) = 0
        # Average = 1/3 = 0.333
        assert agg.pass_hat_3 == 0.333

    def test_pass_hat_k_with_consistent_results(self):
        """When an instance passes all runs, pass^k = 1.0 for all k."""
        from bcbench.results.evaluation_result import LeaderboardAggregate

        # All instances pass all runs
        run1 = EvaluationResultSummary.from_results(
            [
                create_bugfix_result(instance_id="test__1", resolved=True),
                create_bugfix_result(instance_id="test__2", resolved=True),
            ],
            run_id="run_1",
        )
        run2 = EvaluationResultSummary.from_results(
            [
                create_bugfix_result(instance_id="test__1", resolved=True),
                create_bugfix_result(instance_id="test__2", resolved=True),
            ],
            run_id="run_2",
        )
        run3 = EvaluationResultSummary.from_results(
            [
                create_bugfix_result(instance_id="test__1", resolved=True),
                create_bugfix_result(instance_id="test__2", resolved=True),
            ],
            run_id="run_3",
        )

        agg = LeaderboardAggregate.from_runs([run1, run2, run3])

        # All instances pass all runs: C(3,k)/C(3,k) = 1.0 for each
        assert agg.pass_hat_1 == 1.0
        assert agg.pass_hat_3 == 1.0
        assert agg.pass_hat_1 == agg.pass_hat_3


class TestLeaderboard:
    def test_aggregate_from_runs(self):
        from bcbench.results.evaluation_result import LeaderboardAggregate

        run1 = EvaluationResultSummary.from_results(
            [
                create_bugfix_result(instance_id="test__1", resolved=True),
                create_bugfix_result(instance_id="test__2", resolved=False),
            ],
            run_id="run_1",
        )

        agg = LeaderboardAggregate.from_runs([run1])

        assert agg.num_runs == 1
        # With 1 run: pass^1 = avg of C(s,1)/C(1,1) = (1 + 0)/2 = 0.5
        assert agg.pass_hat_1 == 0.5

    def test_leaderboard_to_dict(self):
        from bcbench.results.evaluation_result import Leaderboard, LeaderboardAggregate

        run1 = EvaluationResultSummary.from_results(
            [create_bugfix_result(instance_id="test__1", resolved=True)],
            run_id="run_1",
        )

        agg = LeaderboardAggregate.from_runs([run1])
        leaderboard = Leaderboard(runs=[run1], aggregate=[agg])
        data = leaderboard.to_dict()

        assert "runs" in data
        assert "aggregate" in data
        assert len(data["runs"]) == 1
        assert data["aggregate"][0]["pass_hat_1"] == 1.0

    def test_aggregate_from_legacy_runs_without_instance_results(self):
        """Test that a single legacy run without instance_results uses pass rate ratio."""
        from bcbench.results.evaluation_result import LeaderboardAggregate

        # Create a summary without instance_results (simulates legacy data)
        legacy_run = EvaluationResultSummary(
            total=10,
            resolved=6,
            failed=4,
            build=8,
            percentage=60.0,
            date=date.today(),
            model="gpt-4",
            agent_name="test-agent",
            category=EvaluationCategory.BUG_FIX,
            average_duration=100.0,
            average_prompt_tokens=1000.0,
            average_completion_tokens=500.0,
            instance_results=None,  # Legacy: no instance_results
        )

        agg = LeaderboardAggregate.from_runs([legacy_run])

        assert agg.num_runs == 1
        assert agg.total == 10
        # Should fall back to pass rate (resolved/total) from the run
        assert agg.pass_hat_1 == 0.6  # 6/10 = 0.6
        assert agg.pass_hat_3 is None
        assert agg.pass_hat_5 is None
        assert agg.pass_hat_3 is None  # Only 1 run has instance_results

    def test_load_empty_leaderboard_file(self, tmp_path):
        """Test loading a leaderboard file that contains an empty array."""
        from bcbench.results.evaluation_result import Leaderboard

        empty_file = tmp_path / "empty.json"
        empty_file.write_text("[]")

        leaderboard = Leaderboard.load(empty_file)

        assert leaderboard.runs == []
        assert leaderboard.aggregate == []
