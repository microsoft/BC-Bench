from pathlib import Path
from unittest.mock import patch

from bcbench.agent.copilot.metrics import parse_metrics, parse_session_log


def test_parse_metrics_full_output_gpt5():
    output_lines = [
        "Some other output\n",
        "Total usage est:        1 Premium request\n",
        "API time spent:         34.5s\n",
        "Total session time:     3m 55.1s\n",
        "Total code changes:     +2 -1\n",
        "Breakdown by AI model:\n",
        "   gpt-5                125.5k in, 3.6k out, 0 cached (Est. 1 Premium request)\n",
    ]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 235.1
    assert result.llm_duration == 34.5
    assert result.prompt_tokens == 125500
    assert result.completion_tokens == 3600


def test_parse_metrics_full_output_haiku45():
    output_lines = [
        "Some other output\n",
        "Total usage est:        0.33 Premium requests\n",
        "API time spent:         1m 37.1s\n",
        "Total session time:     29m 25.4s\n",
        "Total code changes:     +2 -2\n",
        "Breakdown by AI model:\n",
        "   claude-haiku-4.5      1.1m in, 6.6k out, 1.0m cached (Est. 0.33 Premium requests)\n",
    ]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 1765.4
    assert result.llm_duration == 97.1
    assert result.prompt_tokens == 1100000
    assert result.completion_tokens == 6600


def test_parse_metrics_llm_duration_seconds_only():
    output_lines = ["API time spent:  45.7s\n"]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.llm_duration == 45.7


def test_parse_metrics_llm_duration_minutes_and_seconds():
    output_lines = ["API time spent:  5m 12.3s\n"]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.llm_duration == 312.3


def test_parse_metrics_wall_time_seconds_only():
    output_lines = ["Total session time: 45.7s\n"]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 45.7


def test_parse_metrics_wall_time_minutes_and_seconds():
    output_lines = ["Total session time: 5m 12.3s\n"]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 312.3


def test_parse_metrics_token_counts_without_k():
    output_lines = ["Breakdown by AI model:\n", "   model-name    1234 in, 567 out\n"]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.prompt_tokens == 1234
    assert result.completion_tokens == 567


def test_parse_metrics_token_counts_with_k():
    output_lines = ["Breakdown by AI model:\n", "   model-name    12.5k in, 3.2k out\n"]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.prompt_tokens == 12500
    assert result.completion_tokens == 3200


def test_parse_metrics_token_counts_with_m():
    output_lines = [
        "Breakdown by AI model:\n",
        "   claude-haiku-4.5    1.3m in, 11.6k out, 1.2m cached\n",
    ]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.prompt_tokens == 1300000
    assert result.completion_tokens == 11600


def test_parse_metrics_empty_output():
    result = parse_metrics([])

    assert result is None


def test_parse_metrics_no_matching_patterns():
    output_lines = ["Some random output\n", "With no matching patterns\n"]

    result = parse_metrics(output_lines)

    assert result is None


def test_parse_metrics_partial_data():
    output_lines = ["Total session time: 1m 30s\n", "Some other text\n"]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 90.0
    assert result.llm_duration is None
    assert result.prompt_tokens is None
    assert result.completion_tokens is None


def test_parse_metrics_malformed_token_count():
    output_lines = ["Breakdown by AI model:\n", "   model-name    invalid in, 100 out\n"]

    result = parse_metrics(output_lines)

    assert result is None


def test_parse_metrics_with_command_output():
    output_lines = [
        "  ✓ Count AL files\n",
        "     $ Get-ChildItem -Path C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\testbed\\App -Recurse -Filter *.al |\n",
        "     Measure-Object | Select-Object Count\n",
        "  \n",
        "     ↪ 4 lines...\n",
        "  \n",
        "  ✓ Count sustainability AL files\n",
        "     $ Get-ChildItem -Path C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\testbed\\App -Recurse -Filter\n",
        "     *Sustain*.al | Select-Object FullName | Measure-Object | Select-Object Count\n",
        "     ↪ 4 lines...\n",
        "  \n",
        "  ✓ Search for Sustainability Journal text\n",
        "     $ Get-ChildItem -Path C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\testbed\\App -Recurse -Filter\n",
        "     *Sustain*.al | Select-String -Pattern 'Sustainability Journal' -SimpleMatch | Select-Object\n",
        "     Path,LineNumber,Line | Format-Table -AutoSize\n",
        "     ↪ 90 lines...\n",
        "\n",
        "  Total usage est:        1 Premium request\n",
        "  API time spent:         34.5s\n",
        "  Total session time:     3m 55.1s\n",
        "  Total code changes:     +2 -1\n",
        "  Breakdown by AI model:\n",
        "   gpt-5                125.5k in, 3.6k out, 0 cached (Est. 1 Premium request)\n",
    ]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 235.1
    assert result.llm_duration == 34.5
    assert result.prompt_tokens == 125500
    assert result.completion_tokens == 3600


def test_parse_metrics_minimal_real_output():
    output_lines = [
        "  Total session time:     2m 15.3s\n",
        "  Breakdown by AI model:\n",
        "   gpt-4o               50.2k in, 1.5k out\n",
    ]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 135.3
    assert result.prompt_tokens == 50200
    assert result.completion_tokens == 1500


def test_parse_metrics_new_format_full():
    output_lines = [
        "Changes   +17 -0\n",
        "Requests  0.33 Premium (1m 45s)\n",
        "Tokens    ↑ 317.5k • ↓ 4.3k • 255.0k (cached)\n",
    ]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 105.0
    assert result.prompt_tokens == 317500
    assert result.completion_tokens == 4300


def test_parse_metrics_new_format_seconds_only():
    output_lines = [
        "Requests  1 Premium (45s)\n",
        "Tokens    ↑ 125.5k • ↓ 3.6k • 0 (cached)\n",
    ]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 45.0
    assert result.prompt_tokens == 125500
    assert result.completion_tokens == 3600


def test_parse_metrics_new_format_tokens_with_m():
    output_lines = [
        "Tokens    ↑ 1.3m • ↓ 11.6k • 1.2m (cached)\n",
    ]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.prompt_tokens == 1300000
    assert result.completion_tokens == 11600


def test_parse_session_log_extracts_turn_count():
    log_content = """
2026-01-20T08:55:10.767Z [INFO] --- Start of group: Sending request to the AI model ---
2026-01-20T08:55:13.898Z [DEBUG] response (Request-ID 00000-1e14d4ab):
2026-01-20T08:55:13.900Z [DEBUG] Tool calls count: 2
2026-01-20T08:55:19.055Z [INFO] --- Start of group: Sending request to the AI model ---
2026-01-20T08:55:21.413Z [DEBUG] response (Request-ID 00000-caa8ae3a):
2026-01-20T08:55:21.460Z [INFO] --- Start of group: Sending request to the AI model ---
2026-01-20T08:55:23.793Z [DEBUG] response (Request-ID 00000-3e8094c5):
"""
    with patch.object(Path, "read_text", return_value=log_content):
        _tool_usage, turn_count = parse_session_log(Path("dummy.log"))

    assert turn_count == 3


def test_parse_session_log_extracts_tool_calls():
    log_content = """
"function": {"name": "view", "arguments": "{}"}
"function": {"name": "view", "arguments": "{}"}
"function": {"name": "grep", "arguments": "{}"}
"function": {"name": "edit", "arguments": "{}"}
"""
    with patch.object(Path, "read_text", return_value=log_content):
        tool_usage, _turn_count = parse_session_log(Path("dummy.log"))

    assert tool_usage == {"view": 2, "grep": 1, "edit": 1}


def test_parse_metrics_with_session_log_includes_turn_count(tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text("""
2026-01-20T08:55:10.767Z [INFO] --- Start of group: Sending request to the AI model ---
2026-01-20T08:55:19.055Z [INFO] --- Start of group: Sending request to the AI model ---
2026-01-20T08:55:21.460Z [INFO] --- Start of group: Sending request to the AI model ---
2026-01-20T08:55:23.840Z [INFO] --- Start of group: Sending request to the AI model ---
2026-01-20T08:55:25.299Z [INFO] --- Start of group: Sending request to the AI model ---
"function": {"name": "view", "arguments": "{}"}
"function": {"name": "grep", "arguments": "{}"}
""")

    output_lines = ["Total session time: 1m 30s\n"]
    result = parse_metrics(output_lines, session_log_path=log_file)

    assert result is not None
    assert result.turn_count == 5
    assert result.tool_usage == {"view": 1, "grep": 1}
    assert result.execution_time == 90.0


def test_parse_metrics_with_session_log_multiple_tools(tmp_path):
    log_file = tmp_path / "session.log"
    log_file.write_text("""
2026-01-20T08:55:10.767Z [INFO] --- Start of group: Sending request to the AI model ---
2026-01-20T08:55:19.055Z [INFO] --- Start of group: Sending request to the AI model ---
2026-01-20T08:55:21.460Z [INFO] --- Start of group: Sending request to the AI model ---
2026-01-20T08:55:23.840Z [INFO] --- Start of group: Sending request to the AI model ---
"function": {"name": "powershell", "arguments": "{}"}
"function": {"name": "view", "arguments": "{}"}
"function": {"name": "grep", "arguments": "{}"}
"function": {"name": "view", "arguments": "{}"}
""")

    output_lines = ["Total session time: 2m 15s\n"]
    result = parse_metrics(output_lines, session_log_path=log_file)

    assert result is not None
    assert result.turn_count == 4
    assert result.tool_usage == {"powershell": 1, "view": 2, "grep": 1}
    assert result.execution_time == 135.0
