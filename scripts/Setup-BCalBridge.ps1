[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [uri] $PythonFeedUrl,
    [string] $EnvironmentPath = '.bcal-llm-api-venv'
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
if ($PythonFeedUrl.Scheme -ne 'https' -or $PythonFeedUrl.UserInfo) {
    throw 'Use an HTTPS feed URL without embedded credentials.'
}
$root = Split-Path $PSScriptRoot
Push-Location $root
try {
    if (Test-Path -LiteralPath $EnvironmentPath) {
        throw "Environment already exists: $EnvironmentPath. Choose a fresh path."
    }
    uv sync --all-packages --extra redteam --locked
    uv venv $EnvironmentPath --python .\.venv\Scripts\python.exe
    # uv's named-index credentials keep the access token out of command arguments and files.
    $previousUsername = $env:UV_INDEX_BC_EVAL_USERNAME
    $previousPassword = $env:UV_INDEX_BC_EVAL_PASSWORD
    try {
        $env:UV_INDEX_BC_EVAL_USERNAME = 'anything'
        $env:UV_INDEX_BC_EVAL_PASSWORD = az account get-access-token `
            --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv
        if (-not $env:UV_INDEX_BC_EVAL_PASSWORD) { throw 'Azure CLI did not return an ADO access token.' }
        uv pip install --python "$EnvironmentPath\Scripts\python.exe" `
            --index "bc-eval=$PythonFeedUrl" `
            --default-index https://packagefeedproxy.microsoft.io/pypi/simple `
            'bc-eval==0.6.1'
    } finally {
        $env:UV_INDEX_BC_EVAL_USERNAME = $previousUsername
        $env:UV_INDEX_BC_EVAL_PASSWORD = $previousPassword
    }
    & "$EnvironmentPath\Scripts\python.exe" -c 'from bc_eval.llm.llm_api import create_llm_api_client; from bc_eval.scorers.autoeval.lmchecklist import LmChecklist; print("BCal bridge and local judge imports ready")'
} finally {
    Pop-Location
}
