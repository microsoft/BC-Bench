$ErrorActionPreference = "Stop"

try {
    $inputJson = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $toolName = if ($inputJson.tool_name) { $inputJson.tool_name } else { $inputJson.toolName }
    $timestamp = $inputJson.timestamp

    if ($toolName -and $env:BCBENCH_TOOL_LOG) {
        $entry = @{ tool_name = $toolName; timestamp = $timestamp } | ConvertTo-Json -Compress
        Add-Content -Path $env:BCBENCH_TOOL_LOG -Value $entry -Encoding UTF8
    }

    exit 0
}
catch {
    # Never block tool execution — silently fail
    exit 0
}
