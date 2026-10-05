<#
.SYNOPSIS
    BC-Bench benchmark utilities
.DESCRIPTION
    Dataset paths, BC artifact pins, entry versions, repository clone info, and release branches.
    General utilities live in bcbench-core (packages/bcbench-core/src/bcbench_core/powershell/BCBenchUtils.psm1).
#>

<#
.SYNOPSIS
    Gets clone information based on the repository type (GitHub or ADO)
.PARAMETER Entry
    A DatasetEntry object containing the repo field
.OUTPUTS
    Hashtable with Url and Token properties
#>
function Get-RepoCloneInfo {
    [CmdletBinding()]
    [OutputType([hashtable])]
    param(
        [Parameter(Mandatory = $true)]
        [DatasetEntry]$Entry
    )

    [string[]] $repoParts = $Entry.repo -split '/'
    [bool] $isGitHub = $repoParts[0].ToLower() -ne 'microsoftinternal'

    if ($isGitHub) {
        return @{
            Url                 = "https://github.com/$($Entry.repo).git"
            Token               = $env:GITHUB_TOKEN
            SparseCheckoutPaths = @()
        }
    }
    else {
        # ADO internal NAV repository — sparse-checkout to only include application code
        return @{
            Url                 = 'https://dynamicssmb2.visualstudio.com/Dynamics%20SMB/_git/NAV'
            Token               = $env:ADO_TOKEN
            SparseCheckoutPaths = @('App/Apps', 'App/Layers')
        }
    }
}

<#
.SYNOPSIS
    Gets the default dataset path for a given category
.DESCRIPTION
    Get the dataset path based on the provided category, must be maintained when adding new categories.
.PARAMETER Category
    The category for which to get the dataset path
.OUTPUTS
    String representing the dataset path
#>
function Get-BCBenchDatasetPath {
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory = $true)]
        # Category validation lives only here: every caller resolves the dataset path through this function, so there's no need to duplicate ValidateSet on each caller.
        [ValidateSet("bug-fix", "test-generation", "code-review", "nl2al", "data-query", "extensibility-request-advisor", "extensibility-request-implement", "extensibility-request-triage")]
        [string] $Category
    )

    switch ($Category) {
        "bug-fix" { $DatasetName = "bcbench.jsonl" }
        "test-generation" { $DatasetName = "bcbench.jsonl" }
        "code-review" { $DatasetName = "codereview.jsonl" }
        "nl2al" { $DatasetName = "nl2al.jsonl" }
        "data-query" { $DatasetName = "dataquery.jsonl" }
        "extensibility-request-advisor" { $DatasetName = "extensibility_request_advisor.jsonl" }
        "extensibility-request-implement" { $DatasetName = "extensibility_request_implement.jsonl" }
        "extensibility-request-triage" { $DatasetName = "extensibility_request_triage.jsonl" }
    }

    [string] $projectRoot = Split-Path $PSScriptRoot -Parent
    return Join-Path $projectRoot "dataset" $DatasetName
}

function Get-BCBenchArtifactPins {
    [CmdletBinding()]
    [OutputType([hashtable])]
    param(
        [string] $Path = (Join-Path $PSScriptRoot 'BCBenchArtifactPins.json')
    )

    $pinnedUrls = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json -AsHashtable -ErrorAction Stop
    if ($pinnedUrls -isnot [hashtable] -or $pinnedUrls.Count -eq 0) {
        throw "BC artifact pins must be a nonempty version-to-URL map in $Path."
    }

    return $pinnedUrls
}

<#
.SYNOPSIS
    Gets the BC artifact URL and container options for a category and version.
.DESCRIPTION
    Container-backed categories use pinned public artifact URLs, optionally, the latest BC Insider artifact.
.PARAMETER Category
    The evaluation category requesting a BC artifact.
.PARAMETER Version
    The dataset entry's BC sandbox version.
.PARAMETER Country
    BC artifact country (public pins are available only for w1).
.OUTPUTS
    Hashtable with artifactUrl and accept_insiderEula.
#>
function Get-BCBenchArtifactConfig {
    [CmdletBinding()]
    [OutputType([hashtable])]
    param(
        [Parameter(Mandatory = $true)]
        [string] $Category,

        [Parameter(Mandatory = $true)]
        [string] $Version,

        [string] $Country = 'w1'
    )

    if ($Category -eq 'data-query') {
        $url = Get-BCArtifactUrl -Version $Version -Country $Country -StorageAccount 'bcinsider' -Select 'Latest' -accept_insiderEula
        if (-not $url) { throw "No BC Insider artifact URL resolved for version $Version ($Country)." }
        return @{ artifactUrl = $url; accept_insiderEula = $true }
    }

    if ($Country -ne 'w1') { throw "Approved BC artifacts are only configured for w1, not $Country." }

    [hashtable] $pinnedUrls = Get-BCBenchArtifactPins

    if (-not $pinnedUrls.ContainsKey($Version) -or $pinnedUrls[$Version] -isnot [string] -or [string]::IsNullOrWhiteSpace($pinnedUrls[$Version])) {
        throw "No pinned BC artifact URL for bcartifacts version $Version in Get-BCBenchArtifactConfig."
    }

    return @{ artifactUrl = $pinnedUrls[$Version]; accept_insiderEula = $false }
}

function Get-BCBenchLatestArtifactUrls {
    [CmdletBinding()]
    [OutputType([hashtable])]
    param(
        [string] $Path = (Join-Path $PSScriptRoot 'BCBenchArtifactPins.json')
    )

    $pins = Get-BCBenchArtifactPins -Path $Path
    foreach ($version in @($pins.Keys)) {
        if ($version -notmatch '^\d+\.\d+$') {
            throw "Invalid pinned BC artifact version: $version."
        }

        $url = Get-BCArtifactUrl -Version $version -Country 'w1' -Select 'Latest' -ErrorAction Stop
        if ($url -isnot [string]) {
            throw "No valid public BC artifact URL resolved for version $version (w1): $url."
        }

        $pins[$version] = $url
    }

    return $pins
}

<#
.SYNOPSIS
    Resolves the BC sandbox version (environment_setup_version) for a dataset entry.
.DESCRIPTION
    Centralizes the category -> dataset -> version lookup used by container setup, symbol download,
    and the CI artifact cache key. Resolves the dataset file via Get-BCBenchDatasetPath.
.PARAMETER InstanceId
    The dataset instance_id to resolve.
.PARAMETER Category
    The dataset category, used to locate the dataset file.
.PARAMETER DatasetPath
    Optional override for the dataset (.jsonl) path. Defaults to the category-specific path via Get-BCBenchDatasetPath.
.OUTPUTS
    The environment_setup_version string, e.g. "26.5".
.EXAMPLE
    Get-BCBenchEntryVersion -InstanceId "bug-fix__job-budget-report-1" -Category "bug-fix"
#>
function Get-BCBenchEntryVersion {
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory = $true)]
        [string] $InstanceId,

        [Parameter(Mandatory = $true)]
        [string] $Category,

        [Parameter(Mandatory = $false)]
        [string] $DatasetPath = (Get-BCBenchDatasetPath -Category $Category)
    )

    if (-not (Test-Path $DatasetPath)) {
        throw "Dataset file not found at: $DatasetPath"
    }

    foreach ($line in Get-Content -Path $DatasetPath) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $entry = $line | ConvertFrom-Json
        if ($entry.instance_id -eq $InstanceId) {
            return $entry.environment_setup_version
        }
    }

    throw "Entry '$InstanceId' not found in $DatasetPath"
}

<#
.SYNOPSIS
    Returns the latest BCApps release branch name (e.g. "releases/28.5").
.DESCRIPTION
    Lists all refs under refs/heads/releases/ via the GitHub API and returns
    the branch with the highest <major>.<minor> version. Branches whose name
    after "releases/" does not parse as a version are ignored.
.PARAMETER Repo
    OWNER/REPO. Defaults to microsoft/BCApps.
.OUTPUTS
    String like "releases/28.5", or $null if no release branch is found.
#>
function Get-LatestReleaseBranch {
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [string]$Repo = 'microsoft/BCApps'
    )

    $refsJson = & gh api "repos/$Repo/git/matching-refs/heads/releases/" --jq '[.[].ref]'
    if ($LASTEXITCODE -ne 0) { throw "gh api matching-refs failed for $Repo" }

    $latest = $refsJson | ConvertFrom-Json |
    ForEach-Object { $_ -replace '^refs/heads/', '' } |
    ForEach-Object {
        $name = $_
        $suffix = $name -replace '^releases/', ''
        $version = $null
        if ([Version]::TryParse($suffix, [ref]$version)) {
            [pscustomobject]@{ Name = $name; Version = $version }
        }
    } |
    Sort-Object Version -Descending |
    Select-Object -First 1

    return $latest.Name
}

Export-ModuleMember -Function Get-RepoCloneInfo, Get-BCBenchDatasetPath, Get-BCBenchArtifactPins, Get-BCBenchArtifactConfig, Get-BCBenchLatestArtifactUrls, Get-BCBenchEntryVersion, Get-LatestReleaseBranch
