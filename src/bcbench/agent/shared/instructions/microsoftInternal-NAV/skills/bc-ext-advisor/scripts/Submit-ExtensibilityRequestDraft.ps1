param(
    [Parameter(Mandatory = $false)]
    [string]$DraftPath,

    [Parameter(Mandatory = $false)]
    [string]$Title,

    [Parameter(Mandatory = $false)]
    [string]$Body,

    [Parameter(Mandatory = $false)]
    [string]$Repo = "microsoft/ALAppExtensions"
)

function Parse-Repo {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoName
    )

    $m = [regex]::Match($RepoName, '^(?<owner>[^/]+)/(?<name>[^/]+)$')
    if (-not $m.Success) {
        throw "Invalid repo format '$RepoName'. Expected 'owner/name'."
    }

    return @{
        Owner = $m.Groups['owner'].Value
        Name = $m.Groups['name'].Value
    }
}

function Get-IssueTypeId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Owner,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$IssueTypeName
    )

    $query = 'query($owner:String!, $name:String!) { repository(owner:$owner, name:$name) { issueTypes(first:100) { nodes { id name } } } }'
    $response = gh api graphql -f query="$query" -f owner="$Owner" -f name="$Name"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($response)) {
        throw "Could not query issue types for repository $Owner/$Name."
    }

    $json = $response | ConvertFrom-Json
    $issueTypeId = $json.data.repository.issueTypes.nodes |
        Where-Object { $_.name -eq $IssueTypeName } |
        Select-Object -First 1 -ExpandProperty id

    if ([string]::IsNullOrWhiteSpace($issueTypeId)) {
        throw "Could not resolve issue type '$IssueTypeName' for repository $Owner/$Name."
    }

    return $issueTypeId
}

function Set-IssueType {
    param(
        [Parameter(Mandatory = $true)]
        [string]$IssueNodeId,

        [Parameter(Mandatory = $true)]
        [string]$IssueTypeId
    )

    $mutation = 'mutation($issueId:ID!, $issueTypeId:ID!) { updateIssue(input:{id:$issueId, issueTypeId:$issueTypeId}) { issue { number } } }'
    gh api graphql -f query="$mutation" -f issueId="$IssueNodeId" -f issueTypeId="$IssueTypeId" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to assign issue type Task."
    }
}

if ($DraftPath) {
    if (-not (Test-Path -LiteralPath $DraftPath)) {
        throw "Draft file not found: $DraftPath"
    }

    $draft = Get-Content -LiteralPath $DraftPath -Raw
    $match = [regex]::Match($draft, '(?ms)^##\s+Title\s*$\s*(?<title>[^\r\n]+)\s*(?<body>.*)$')

    if (-not $match.Success) {
        throw "Draft format error: missing '## Title' section or title value."
    }

    $Title = $match.Groups['title'].Value.Trim()
    $Body = $match.Groups['body'].Value.TrimStart()
}

if ([string]::IsNullOrWhiteSpace($Title)) {
    throw "Title is required. Provide -DraftPath or -Title."
}

if ([string]::IsNullOrWhiteSpace($Body)) {
    throw "Body is required. Provide -DraftPath or -Body."
}

$repoParts = Parse-Repo -RepoName $Repo
$issueTypeId = Get-IssueTypeId -Owner $repoParts.Owner -Name $repoParts.Name -IssueTypeName 'Task'

$createResponse = gh api --method POST "/repos/$($repoParts.Owner)/$($repoParts.Name)/issues" -f title="$Title" -f body="$Body"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($createResponse)) {
    throw "Failed to create issue via gh api."
}

$createdIssue = $createResponse | ConvertFrom-Json
if (-not $createdIssue.node_id -or -not $createdIssue.html_url) {
    throw "Issue was created but response did not contain expected fields."
}

Set-IssueType -IssueNodeId $createdIssue.node_id -IssueTypeId $issueTypeId

Write-Output ("Extensibility request {0} ({1}) is created." -f $createdIssue.number, $createdIssue.html_url)

if ($DraftPath -and (Test-Path -LiteralPath $DraftPath)) {
    Remove-Item -LiteralPath $DraftPath -Force
}
