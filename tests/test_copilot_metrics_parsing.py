from bcbench.agent.copilot.metrics import parse_metrics


def test_parse_metrics_full_output_gpt5():
    output_lines = [
        "Some other output\n",
        "Total usage est:       1 Premium request\n",
        "Total duration (API):  34.5s\n",
        "Total duration (wall): 3m 55.1s\n",
        "Total code changes:    2 lines added, 1 lines removed\n",
        "Usage by model:\n",
        "    gpt-5                125.5k input, 3.6k output, 0 cache read, 0 cache write (Est. 1 Premium request)\n",
    ]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 235.1
    assert result.prompt_tokens == 125500
    assert result.completion_tokens == 3600


def test_parse_metrics_full_output_haiku45():
    output_lines = [
        "Some other output\n",
        "Total usage est:       0.33 Premium requests\n",
        "Total duration (API):  1m 37.1s\n",
        "Total duration (wall): 29m 25.4s\n",
        "Total code changes:    2 lines added, 2 lines removed\n",
        "Usage by model:\n",
        "    claude-haiku-4.5     1.1m input, 6.6k output, 0 cache read, 0 cache write (Est. 0.33 Premium requests)\n",
    ]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 1765.4
    assert result.prompt_tokens == 1100000
    assert result.completion_tokens == 6600


def test_parse_metrics_wall_time_seconds_only():
    output_lines = ["Total duration (wall): 45.7s\n"]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 45.7


def test_parse_metrics_wall_time_minutes_and_seconds():
    output_lines = ["Total duration (wall): 5m 12.3s\n"]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 312.3


def test_parse_metrics_token_counts_without_k():
    output_lines = ["Usage by model:\n", "    model-name    1234 input, 567 output\n"]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.prompt_tokens == 1234
    assert result.completion_tokens == 567


def test_parse_metrics_token_counts_with_k():
    output_lines = ["Usage by model:\n", "    model-name    12.5k input, 3.2k output\n"]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.prompt_tokens == 12500
    assert result.completion_tokens == 3200


def test_parse_metrics_empty_output():
    result = parse_metrics([])

    assert result is None


def test_parse_metrics_no_matching_patterns():
    output_lines = ["Some random output\n", "With no matching patterns\n"]

    result = parse_metrics(output_lines)

    assert result is None


def test_parse_metrics_partial_data():
    output_lines = ["Total duration (wall): 1m 30s\n", "Some other text\n"]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 90.0
    assert result.prompt_tokens is None
    assert result.completion_tokens is None


def test_parse_metrics_malformed_token_count():
    output_lines = ["Usage by model:\n", "    model-name    invalid input, 100 output\n"]

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
        "  Total usage est:       1 Premium request\n",
        "  Total duration (API):  34.5s\n",
        "  Total duration (wall): 3m 55.1s\n",
        "  Total code changes:    2 lines added, 1 lines removed\n",
        "  Usage by model:\n",
        "      gpt-5                125.5k input, 3.6k output, 0 cache read, 0 cache write (Est. 1 Premium request)\n",
    ]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 235.1
    assert result.prompt_tokens == 125500
    assert result.completion_tokens == 3600


def test_parse_metrics_minimal_real_output():
    output_lines = [
        "  Total duration (wall): 2m 15.3s\n",
        "  Usage by model:\n",
        "      gpt-4o               50.2k input, 1.5k output\n",
    ]

    result = parse_metrics(output_lines)

    assert result is not None
    assert result.execution_time == 135.3
    assert result.prompt_tokens == 50200
    assert result.completion_tokens == 1500
