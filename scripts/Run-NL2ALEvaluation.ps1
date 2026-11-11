[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('accuracy', 'harms')]
    [string] $Category,
    [Parameter(Mandatory)]
    [string] $BcalExecutable,
    [Parameter(Mandatory)]
    [string] $ArtifactVersion,
    [Parameter(Mandatory)]
    [string] $ResultsDirectory,
    [string] $BridgePython = '.bcal-llm-api-venv\Scripts\python.exe',
    [string] $Model = 'gpt-56-ceres',
    [ValidateSet('gold', 'challenge')]
    [string] $Tier = 'gold',
    [ValidateRange(1, 2147483647)]
    [int] $Limit = 1,
    [switch] $Full
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$root = Split-Path $PSScriptRoot
Push-Location $root
try {
    $python = (Resolve-Path .\.venv\Scripts\python.exe).Path
    $bridgePythonPath = (Resolve-Path -LiteralPath $BridgePython).Path
    $bridge = Join-Path $root 'src\bcbench\agent\bcal\bc_eval_llm_api_bridge.py'
    if ($bridgePythonPath -match '\s' -or $bridge -match '\s') {
        throw 'BCal external-command transport requires a checkout and bridge environment path without spaces.'
    }
    $env:BCAL_EXECUTABLE = (Resolve-Path -LiteralPath $BcalExecutable).Path
    $env:BCAL_LLM_COMMAND = "$bridgePythonPath $bridge"
    $env:BCAL_LLM_MODEL = $Model
    if (Test-Path -LiteralPath $ResultsDirectory) {
        throw "Results directory already exists: $ResultsDirectory"
    }
    $artifactRoot = & $python -c 'import sys; from bcbench_core.artifacts import resolve_artifact_version_root; p=resolve_artifact_version_root("28.0"); assert p is not None and p.name == sys.argv[1], p; print(p)' $ArtifactVersion
    $datasetPath = & $python -c 'import sys; from bcbench.types import EvaluationCategory as C, DatasetTier as T; print(C.NL2AL.dataset_path(T(sys.argv[1])))' $Tier
    $commit = git rev-parse HEAD
    if (git status --porcelain --untracked-files=no) { throw 'Commit tracked changes before recording an evaluation revision.' }
    $out = (New-Item -ItemType Directory -Path $ResultsDirectory).FullName
    @{
        source_commit = $commit
        category = $Category
        model = $Model
        completion_review_model = $env:BCAL_COMPLETION_REVIEW_MODEL
        tier = $Tier
        full = [bool]$Full
        limit = if ($Full) { $null } else { $Limit }
        executable = $env:BCAL_EXECUTABLE
        runtime_version = (& $env:BCAL_EXECUTABLE --version)
        runtime_files = @(Get-ChildItem (Split-Path $env:BCAL_EXECUTABLE) -File -Recurse |
            Get-FileHash -Algorithm SHA256 | Select-Object Path, Hash)
        bridge_hash = (Get-FileHash $bridge).Hash
        bridge_packages = @(& $bridgePythonPath -c 'from importlib.metadata import distributions; print("\n".join(sorted(f"{d.metadata[''Name'']}=={d.version}" for d in distributions())))')
        artifact_version = $ArtifactVersion
        package_hashes = @(Get-ChildItem -LiteralPath $artifactRoot -Recurse -File -Filter *.app |
            Get-FileHash -Algorithm SHA256 | Select-Object Path, Hash)
        input_hashes = @(Get-FileHash $datasetPath, .\dataset\harms\comprehensive.harms.yaml |
            Select-Object Path, Hash)
    } | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 "$out\protocol.json"

    $failures = [System.Collections.Generic.List[string]]::new()
    if ($Category -eq 'accuracy') {
        $ids = @(& $python -c 'import sys; from bcbench.types import EvaluationCategory as C, DatasetTier as T; print("\n".join(e.instance_id for e in C.NL2AL.entry_class.load(C.NL2AL.dataset_path(T(sys.argv[1])))))' $Tier)
        if (-not $Full) { $ids = @($ids | Select-Object -First $Limit) }
        $ids | ConvertTo-Json -AsArray | Set-Content -Encoding utf8 "$out\entries.json"
        foreach ($id in $ids) {
            # The CLI resets its run directory: every case must own a distinct one.
            $PSNativeCommandUseErrorActionPreference = $false
            & $python -m bcbench evaluate bcal $id --tier $Tier `
                --repo-path "$out\workspaces\$id" --output-dir "$out\accuracy" --run-id $id `
                *> "$out\$id.console.txt"
            $code = $LASTEXITCODE
            $PSNativeCommandUseErrorActionPreference = $true
            if ($code) { $failures.Add($id) }
        }
        & $python -m bcbench result summarize --run-id accuracy --category nl2al `
            --result-dir $out --result-pattern '*.jsonl' --git-ref $commit
    } else {
        $limitArgs = if ($Full) { @() } else { @('--limit', "$Limit") }
        $PSNativeCommandUseErrorActionPreference = $false
        & $python -m bcbench harms run --suite .\dataset\harms\comprehensive.harms.yaml `
            @limitArgs --llm-model $Model --skip-evaluation --results-dir "$out\harms" `
            *> "$out\harms.console.txt"
        $code = $LASTEXITCODE
        $PSNativeCommandUseErrorActionPreference = $true
        if ($code) { $failures.Add('harms') }
    }
    @{ execution_failures = @($failures); scoring = 'Not run; score saved captures separately' } |
        ConvertTo-Json | Set-Content -Encoding utf8 "$out\execution-summary.json"
    if ($failures.Count) { throw "Execution failures: $($failures -join ', '). Captures retained at $out" }
    Write-Output "Captured $Category at $out. Inspect delivery coverage and score the saved results separately."
} finally {
    Pop-Location
}
