$ErrorActionPreference = "Stop"

try {
    $inputJson = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $toolName = if ($inputJson.tool_name) { $inputJson.tool_name } else { $inputJson.toolName }
    $timestamp = $inputJson.timestamp
    $toolPath = $null

    # LSP calls share the tool name "lsp"; the specific operation (findReferences, goToDefinition, hover, ...) lives in the tool arguments.
    # Capture it as an "lsp:<operation>" sub-label so usage stats stay meaningful.
    $toolArgs = if ($null -ne $inputJson.toolArgs) { $inputJson.toolArgs } else { $inputJson.tool_input }

    if ($toolName -eq "lsp") {
        if ($toolArgs -is [string]) {
            try { $toolArgs = $toolArgs | ConvertFrom-Json } catch { $toolArgs = $null }
        }
        if ($toolArgs -and $toolArgs.operation) {
            $toolName = "lsp:$($toolArgs.operation)"
        }
    }

    # Capture target file path for read-like tools so diagnostics can verify
    # whether skills/instructions were actually opened.
    if ($toolName -in @("Read", "read", "read_file", "functions.read_file", "view")) {
        if ($toolArgs -is [string]) {
            try { $toolArgs = $toolArgs | ConvertFrom-Json } catch { $toolArgs = $null }
        }

        if ($toolArgs) {
            if ($toolArgs.filePath) {
                $toolPath = [string]$toolArgs.filePath
            }
            elseif ($toolArgs.path) {
                $toolPath = [string]$toolArgs.path
            }
        }
    }

    if ($toolName -and $env:BCBENCH_TOOL_LOG) {
        $entryPayload = @{ tool_name = $toolName; timestamp = $timestamp }
        if ($toolPath) {
            $entryPayload["tool_path"] = $toolPath
        }
        $entry = $entryPayload | ConvertTo-Json -Compress
        Add-Content -Path $env:BCBENCH_TOOL_LOG -Value $entry -Encoding UTF8
    }

    exit 0
}
catch {
    # Never block tool execution — silently fail
    exit 0
}
