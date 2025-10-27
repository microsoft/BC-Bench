# DatasetReader.psm1 - Module for reading BC-Bench dataset
# Provides classes and functions to read and parse the bcbench_nav.jsonl dataset

class TestEntry {
    [int]$codeunitID
    [string[]]$functionName

    TestEntry([PSObject]$jsonObject) {
        $this.codeunitID = [int]$jsonObject.codeunitID
        $this.functionName = $jsonObject.functionName
    }
}

class ValidationResult {
    [string]$InstanceId
    [string]$Status
    [string]$Message

    ValidationResult([string]$instanceId, [string]$status, [string]$message) {
        $this.InstanceId = $instanceId
        $this.Status = $status
        $this.Message = $message
    }
}

class DatasetEntry {
    # Properties based on the dataset schema
    [string]$repo
    [string]$instance_id
    [string]$patch
    [string]$base_commit
    [string]$hints_text
    [string]$created_at
    [string]$test_patch
    [string]$problem_statement
    [string]$environment_setup_version
    [TestEntry[]]$FAIL_TO_PASS
    [TestEntry[]]$PASS_TO_PASS
    [string[]]$project_paths

    # Constructor that takes a PSObject (from JSON)
    DatasetEntry([PSObject]$jsonObject) {
        $this.repo = $jsonObject.repo
        $this.instance_id = $jsonObject.instance_id
        $this.patch = $jsonObject.patch
        $this.base_commit = $jsonObject.base_commit
        $this.hints_text = $jsonObject.hints_text
        $this.created_at = $jsonObject.created_at
        $this.test_patch = $jsonObject.test_patch
        $this.problem_statement = $jsonObject.problem_statement
        $this.environment_setup_version = $jsonObject.environment_setup_version
        $this.FAIL_TO_PASS = @()
        foreach ($entry in $jsonObject.FAIL_TO_PASS) {
            $this.FAIL_TO_PASS += [TestEntry]::new($entry)
        }
        $this.PASS_TO_PASS = @()
        foreach ($entry in $jsonObject.PASS_TO_PASS) {
            $this.PASS_TO_PASS += [TestEntry]::new($entry)
        }
        $this.project_paths = $jsonObject.project_paths
    }

    # Helper method to get a summary string
    [string]ToString() {
        return "DatasetEntry: $($this.instance_id) (Repo: $($this.repo), Version: $($this.environment_setup_version))"
    }
}

function Get-DatasetEntries {
    [CmdletBinding()]
    [OutputType([DatasetEntry[]])]

    param(
        [Parameter(Mandatory = $true)]
        [string]$DatasetPath,

        [Parameter(Mandatory = $false)]
        [string]$Version,

        [Parameter(Mandatory = $false)]
        [string]$InstanceId
    )

    if (-not (Test-Path $DatasetPath)) {
        throw "Dataset file not found at: $DatasetPath"
    }

    if ($Version -and $InstanceId) {
        throw "Please provide either Version or InstanceId, not both."
    }

    Write-Verbose "Reading dataset from: $DatasetPath"
    [DatasetEntry[]] $entries = @()

    $content = Get-Content $DatasetPath -Raw
    $jsonObjects = $content -split '(?<=})\s*\n(?=\{)' | Where-Object { $_.Trim().Length -gt 0 }

    foreach ($jsonString in $jsonObjects) {
        try {
            $jsonObject = $jsonString.Trim() | ConvertFrom-Json
            $DatasetEntry = [DatasetEntry]::new($jsonObject)
            $entries += $DatasetEntry
            Write-Verbose "Loaded entry: $($DatasetEntry.instance_id)"
        }
        catch {
            Write-Warning "Failed to parse JSON object: $_"
        }
    }

    if ($Version) {
        $entries = $entries | Where-Object { $_.environment_setup_version -eq $Version }
    } elseif ($InstanceId) {
        $entries = $entries | Where-Object { $_.instance_id -eq $InstanceId }
    }

    Write-Verbose "Successfully loaded $($entries.Count) dataset entries"
    return $entries
}

Export-ModuleMember -Function Get-DatasetEntries
