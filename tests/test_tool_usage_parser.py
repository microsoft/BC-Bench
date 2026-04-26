from pathlib import Path

from bcbench.agent.copilot.metrics import parse_turn_count_from_log


class TestParseTurnCountFromLog:
    def test_counts_turn_markers(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_content = """
2025-01-01T00:00:00.000Z [INFO] --- Start of group: Sending request to the AI model ---
2025-01-01T00:00:01.000Z [DEBUG] response
2025-01-01T00:00:02.000Z [INFO] --- Start of group: Sending request to the AI model ---
2025-01-01T00:00:03.000Z [INFO] --- Start of group: Sending request to the AI model ---
"""
        log_file.write_text(log_content)

        turn_count = parse_turn_count_from_log(log_file)

        assert turn_count == 3

    def test_returns_zero_for_empty_log(self, tmp_path: Path):
        log_file = tmp_path / "empty.log"
        log_file.write_text("")

        turn_count = parse_turn_count_from_log(log_file)

        assert turn_count == 0

    def test_returns_zero_for_no_turn_markers(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_content = """
2025-01-01T00:00:00.000Z [DEBUG] Some debug output
2025-01-01T00:00:01.000Z [INFO] Some info output
"""
        log_file.write_text(log_content)

        turn_count = parse_turn_count_from_log(log_file)

        assert turn_count == 0
