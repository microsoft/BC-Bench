$ErrorActionPreference = "Stop"

# Claude Code Stop hook: block the agent from finishing until it has written the required output file.
# The agent's natural completion is a prose answer, so it often skips the answer.json the evaluation
# reads. When the file is missing we return {"decision":"block"} to force one more turn, bounded by a
# retry counter so a stubborn agent can't loop forever.

# Consume the Stop-hook payload on stdin (we don't need any of its fields).
[void][Console]::In.ReadToEnd()

$answerPath = $env:BCBENCH_ANSWER_PATH
if ([string]::IsNullOrEmpty($answerPath) -or (Test-Path $answerPath)) {
    exit 0  # nothing required, or the file is already there -> allow the agent to stop
}

$maxRetries = if ($env:BCBENCH_STOP_MAX) { [int]$env:BCBENCH_STOP_MAX } else { 3 }
$counterFile = $env:BCBENCH_STOP_COUNTER
$count = if ($counterFile -and (Test-Path $counterFile)) { [int](Get-Content $counterFile -Raw) } else { 0 }
if ($count -ge $maxRetries) {
    exit 0  # gave up after enough nudges -> allow the agent to stop
}
if ($counterFile) {
    ($count + 1) | Set-Content -Path $counterFile -NoNewline
}

$reason = "You have not written '$answerPath' yet. Before finishing, write the result rows that answer the question there as a JSON array (one JSON object per row), using the data returned by the bc_data_query tool. This file is the ONLY output that is evaluated - a chat answer does not count."
@{ decision = "block"; reason = $reason } | ConvertTo-Json -Compress
exit 0
