$ErrorActionPreference = "Stop"

try {
    $inputJson = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $toolName = if ($inputJson.tool_name) { $inputJson.tool_name } else { $inputJson.toolName }
    $timestamp = $inputJson.timestamp

    # LSP calls share the tool name "lsp"; the specific operation (findReferences, goToDefinition, hover, ...) lives in the tool arguments.
    # Capture it as an "lsp:<operation>" sub-label so usage stats stay meaningful.
    if ($toolName -eq "lsp") {
        $toolArgs = if ($null -ne $inputJson.toolArgs) { $inputJson.toolArgs } else { $inputJson.tool_input }
        if ($toolArgs -is [string]) {
            try { $toolArgs = $toolArgs | ConvertFrom-Json } catch { $toolArgs = $null }
        }
        if ($toolArgs -and $toolArgs.operation) {
            $toolName = "lsp:$($toolArgs.operation)"
        }
    }

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
