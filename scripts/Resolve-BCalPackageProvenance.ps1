param(
    [Parameter(Mandatory = $true)]
    [string]$PackageId,

    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [string]$TestFeedUrl
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$expectedRepository = "bic/BC-DeveloperExperience"
$exactVersionPattern = '\A[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\z'

function Normalize-Branch([string]$Value) {
    $branch = $Value.Trim()
    if ($branch.StartsWith("refs/heads/", [System.StringComparison]::Ordinal)) {
        return $branch.Substring("refs/heads/".Length)
    }
    if ($branch -match '\Arefs/pull/([0-9]+)/(?:head|merge)\z') {
        return "pr/$($Matches[1])"
    }
    if ($branch.StartsWith("refs/", [System.StringComparison]::Ordinal)) {
        return $branch.Substring("refs/".Length)
    }
    return $branch
}

if ([string]::IsNullOrWhiteSpace($PackageId)) {
    throw "BCal package ID must not be empty."
}
if ($Version -notmatch $exactVersionPattern) {
    throw "Experimental BCal provenance requires an exact NuGet version."
}
if ([string]::IsNullOrWhiteSpace($TestFeedUrl)) {
    throw "Experimental BCal feed URL must not be empty."
}
$testFeed = [Uri]$TestFeedUrl
$segments = @($testFeed.AbsolutePath.Trim("/") -split "/")
$packagingIndex = -1
for ($index = 0; $index -lt $segments.Count; $index++) {
    if ($segments[$index] -eq "_packaging") {
        $packagingIndex = $index
        break
    }
}
if ($packagingIndex -lt 0 -or $packagingIndex + 1 -ge $segments.Count) {
    throw "Cannot derive the Azure Artifacts feed from the experimental BCal feed URL."
}
$feedView = $segments[$packagingIndex + 1]
if ($feedView -notmatch '\A(?<feed>[^@]+)@Local\z') {
    throw "Experimental BCal feed URL must select an @Local view."
}
$feedName = $Matches.feed

if ($testFeed.Host -match '\A(?<organization>[^.]+)\.pkgs\.visualstudio\.com\z') {
    $organization = $Matches.organization
}
elseif ($testFeed.Host -eq "pkgs.dev.azure.com") {
    if ($segments.Count -lt 1 -or [string]::IsNullOrWhiteSpace($segments[0])) {
        throw "Cannot derive the Azure DevOps organization from the experimental BCal feed URL."
    }
    $organization = $segments[0]
}
else {
    throw "Experimental BCal feed URL is not an Azure Artifacts endpoint."
}
$adoToken = az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($adoToken)) {
    throw "Could not obtain an Azure DevOps access token for BCal package provenance."
}
$headers = @{ Authorization = "Bearer $adoToken" }
$apiVersion = "7.1-preview.1"

$feedsUri = "https://feeds.dev.azure.com/$organization/_apis/packaging/feeds?includeUrls=true&api-version=$apiVersion"
$feeds = Invoke-RestMethod -Uri $feedsUri -Headers $headers -Method Get
$matchingFeeds = @($feeds.value | Where-Object { $_.name -eq $feedName })
if ($matchingFeeds.Count -ne 1) {
    throw "Expected exactly one Azure Artifacts feed named '$feedName'; found $($matchingFeeds.Count)."
}
$feed = $matchingFeeds[0]

$encodedPackageId = [Uri]::EscapeDataString($PackageId)
$packagesUri = "https://feeds.dev.azure.com/$organization/_apis/packaging/feeds/$($feed.id)/packages?protocolType=NuGet&packageNameQuery=$encodedPackageId&includeAllVersions=true&api-version=$apiVersion"
$packages = Invoke-RestMethod -Uri $packagesUri -Headers $headers -Method Get
$matchingPackages = @($packages.value | Where-Object { $_.name -ieq $PackageId })
if ($matchingPackages.Count -ne 1) {
    throw "Expected exactly one '$PackageId' package in '$feedName'; found $($matchingPackages.Count)."
}
$package = $matchingPackages[0]

$versionsUri = "https://feeds.dev.azure.com/$organization/_apis/packaging/feeds/$($feed.id)/packages/$($package.id)/versions?includeUrls=true&isListed=true&api-version=$apiVersion"
$versions = Invoke-RestMethod -Uri $versionsUri -Headers $headers -Method Get
$matchingVersions = @($versions.value | Where-Object { $_.version -ieq $Version })
if ($matchingVersions.Count -ne 1) {
    throw "Expected exact BCal version '$Version' in '$feedName'; found $($matchingVersions.Count)."
}
$packageVersion = $matchingVersions[0]
if (@($packageVersion.sourceChain).Count -ne 0) {
    throw "BCal version '$Version' is upstreamed into '$feedName', not published directly by a branch build."
}

$provenanceUri = "https://feeds.dev.azure.com/$organization/_apis/packaging/Feeds/$($feed.id)/Packages/$($package.id)/Versions/$($packageVersion.id)/provenance?api-version=$apiVersion"
$provenance = Invoke-RestMethod -Uri $provenanceUri -Headers $headers -Method Get
if ($provenance.provenance.provenanceSource -ne "InternalBuild") {
    throw "BCal version '$Version' does not have internal build provenance."
}
$data = $provenance.provenance.data
if ($data.'Build.Repository.Id' -ne $expectedRepository) {
    throw "BCal version '$Version' was built from '$($data.'Build.Repository.Id')', not '$expectedRepository'."
}
$sourceRef = $data.'Build.SourceBranch'
if ([string]::IsNullOrWhiteSpace($sourceRef)) {
    throw "BCal version '$Version' has incomplete Azure build provenance."
}

$actualBranch = Normalize-Branch $sourceRef
if ([string]::IsNullOrWhiteSpace($actualBranch) -or $actualBranch -eq "master" -or $actualBranch.StartsWith("releases/", [System.StringComparison]::Ordinal)) {
    throw "BCal version '$Version' came from official branch '$actualBranch', not an experimental branch."
}
Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value "branch=$actualBranch" -Encoding utf8
Write-Output "Verified experimental BCal package $PackageId $Version from $actualBranch."
