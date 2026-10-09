param(
    [Parameter(Mandatory = $true)]
    [string]$PackageId,

    [Parameter(Mandatory = $true)]
    [string]$FeedUrl,

    [ValidateSet("latest-prerelease", "pinned")]
    [string]$VersionMode = "latest-prerelease",

    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$exactVersionPattern = '\A[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\z'
$hasVersion = -not [string]::IsNullOrWhiteSpace($Version)

if ($VersionMode -eq "latest-prerelease" -and $hasVersion) {
    throw "bcal-version must be empty when bcal-version-mode is latest-prerelease."
}
if ($VersionMode -eq "pinned" -and (-not $hasVersion -or $Version -notmatch $exactVersionPattern)) {
    throw "Pinned mode requires bcal-version to be an exact NuGet version, not a range or floating version."
}

$installArguments = @("tool", "install", "--global", $PackageId)
if ($VersionMode -eq "pinned") {
    $installArguments += @("--version", $Version)
}
else {
    $installArguments += "--prerelease"
}
$installArguments += @("--add-source", $FeedUrl)

# The feed's credential provider can fail transiently before the tool is installed.
for ($attempt = 1; $attempt -le 3; $attempt++) {
    & dotnet @installArguments
    if ($LASTEXITCODE -eq 0) { break }
    if ($attempt -eq 3) { throw "bcal CLI install failed after 3 attempts (exit code $LASTEXITCODE)." }
    Write-Output "::warning::bcal CLI install attempt $attempt failed (exit $LASTEXITCODE); retrying in 20s"
    Start-Sleep -Seconds 20
}

$installedTools = & dotnet tool list $PackageId --global --format json
if ($LASTEXITCODE -ne 0) {
    throw "dotnet tool list failed (exit code $LASTEXITCODE); cannot determine the installed BCal version."
}

try {
    $toolList = ($installedTools -join "`n") | ConvertFrom-Json -AsHashtable -NoEnumerate
}
catch {
    throw "dotnet tool list returned invalid JSON; cannot determine the installed BCal version."
}
if ($toolList -isnot [System.Collections.IDictionary] -or $toolList.version -ne 1 -or $toolList.data -isnot [array]) {
    throw "dotnet tool list returned an unsupported JSON shape."
}

$installedPackages = @(
    $toolList.data | Where-Object {
        $_ -is [System.Collections.IDictionary] -and $_.packageId -is [string] -and $_.packageId -ieq $PackageId
    }
)
if ($installedPackages.Count -ne 1) {
    throw "Expected exactly one installed BCal package '$PackageId'; found $($installedPackages.Count)."
}

$installedVersion = $installedPackages[0].version
if ($installedVersion -isnot [string] -or $installedVersion -notmatch $exactVersionPattern) {
    throw "Invalid installed-version data for BCal package '$PackageId'."
}
if ($VersionMode -eq "pinned" -and $installedVersion -ine $Version) {
    throw "Installed BCal version '$installedVersion' does not match requested version '$Version'."
}

Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "version=$installedVersion" -Encoding utf8
Write-Output "Installed BCal package version: $installedVersion"
