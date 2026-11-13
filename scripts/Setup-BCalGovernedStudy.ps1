$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$work = $env:BCAL_STUDY_WORK
New-Item -ItemType Directory -Force -Path $work | Out-Null
$token = az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv
if (-not $token) { throw 'ADO token unavailable.' }
Write-Output "::add-mask::$token"

uv venv "$work\inference" --python .\.venv\Scripts\python.exe *> "$work\venv-inference.log"
uv venv "$work\judge" --python .\.venv\Scripts\python.exe *> "$work\venv-judge.log"
foreach ($name in @('inference', 'judge')) {
    uv pip install --python "$work\$name\Scripts\python.exe" --no-deps -r ".\experiments\bcal-sdk-policy\$name-requirements.txt" *> "$work\deps-$name.log"
    uv pip install --no-cache --python "$work\$name\Scripts\python.exe" --no-deps 'bc-eval==0.6.1' --index "https://anything:$token@dynamicssmb2.pkgs.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_packaging/BC_PythonFeed/pypi/simple/" *> "$work\private-package-$name.log"
}

$env:BCAL_STUDY_INFERENCE_PYTHON = "$work\inference\Scripts\python.exe"
$env:BCAL_STUDY_JUDGE_PYTHON = "$work\judge\Scripts\python.exe"
$study = Get-Content "experiments\$env:BCAL_STUDY_PROFILE\study.json" -Raw | ConvertFrom-Json
$installedRoot = "$HOME\.dotnet\tools\.store\microsoft.businesscentral.bcal.cli\$($study.package.version)"
$installed = @(Get-ChildItem $installedRoot -Filter bcal.exe -File -Recurse | Where-Object { $_.FullName -match '\\net10\.0\\any\\bcal\.exe$' })
if ($installed.Count -ne 1) { throw 'Expected exactly one installed net10 BCAL.' }
$env:BCAL_STUDY_INSTALLED_BINARY = $installed[0].FullName
$env:PYTHONPATH = "$env:GITHUB_WORKSPACE\src"
$env:LLM_API_ENVIRONMENT = 'TEST'
$env:LLM_API_CERTIFICATE_FILE = "$work\llm-api-cert.pfx"
$b64 = az keyvault secret show --vault-name $env:STUDY_CERT_VAULT --name $env:STUDY_CERT_NAME --query value -o tsv
if (-not $b64) { throw 'Study certificate unavailable.' }
Write-Output "::add-mask::$b64"
[IO.File]::WriteAllBytes($env:LLM_API_CERTIFICATE_FILE, [Convert]::FromBase64String($b64))
$b64 = $null

& $env:BCAL_STUDY_INFERENCE_PYTHON -c "import hashlib,importlib.metadata,pathlib; p=pathlib.Path(importlib.metadata.distribution('bc-eval').locate_file('bc_eval/llm/llm_api.py')); assert hashlib.sha256(p.read_bytes()).hexdigest() == 'f4dfdd0148debfc2de8a3cabfa49b00c9f8b01bfcbfa4a78708c7d0459cfe815'"
& $env:BCAL_STUDY_INFERENCE_PYTHON -c "import sys; sys.path.insert(0, 'scripts'); from bcal_study_transport import load_proxy; from bc_eval.llm.llm_api import LlmApiSettings,LlmApiTransport; assert load_proxy()._handler"
& $env:BCAL_STUDY_JUDGE_PYTHON -c "import hashlib,importlib.metadata,pathlib; p=pathlib.Path(importlib.metadata.distribution('bc-eval').locate_file('bc_eval/scorers/autoeval/lmchecklist.py')); assert hashlib.sha256(p.read_bytes()).hexdigest() == 'c563e569520b202e725d46ac58497868fefd8d48662fb8a305c9a397e14c398d'"

$symbolRoot = 'C:\bcartifacts.cache\sandbox\28.0.46665.57479'
if (-not (Test-Path $symbolRoot)) {
    Install-Module -Name BcContainerHelper -Force -AllowClobber -AllowPrerelease *> "$work\symbol-helper.log"
    Import-Module BcContainerHelper -Force -DisableNameChecking
    $url = Get-BCArtifactUrl -type Sandbox -version '28.0.46665.57479' -country w1 -select Latest
    if (-not $url -or ([uri]$url).Segments[-2].Trim('/') -ne '28.0.46665.57479') { throw 'Exact approved symbol artifact unavailable.' }
    Download-Artifacts -artifactUrl $url -includePlatform *> "$work\symbol-download.log"
}
.\.venv\Scripts\python.exe .\scripts\bcal_governed_study.py fixtures --work $work
& $env:BCAL_STUDY_INFERENCE_PYTHON .\scripts\bcal_governed_study.py preflight --work $work --output study-sanitized

foreach ($name in @('BCAL_STUDY_INFERENCE_PYTHON', 'BCAL_STUDY_JUDGE_PYTHON', 'BCAL_STUDY_INSTALLED_BINARY', 'PYTHONPATH', 'LLM_API_ENVIRONMENT', 'LLM_API_CERTIFICATE_FILE')) {
    "$name=$([Environment]::GetEnvironmentVariable($name))" >> $env:GITHUB_ENV
}
$token = $null
