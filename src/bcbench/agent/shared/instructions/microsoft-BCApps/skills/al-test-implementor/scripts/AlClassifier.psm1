# AlClassifier.psm1
# Heuristic taxonomy classifier for AL test corpus rows.
# See openspec/changes/improve-al-test-implementor-skill/design.md (D5).
#
# Two-axis labels:
#   subject     : posting | pages | reports | xml-integration | calculation
#                 | setup | permissions | other
#   interaction : direct-call | confirm-dialog | modal-page | report-request
#                 | notification | asserterror | none

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Rule tables
# ---------------------------------------------------------------------------
# Order matters: first match wins. Each rule has a label and one or more
# regex patterns. Patterns are matched case-insensitively.

$script:SubjectPathRules = @(
    @{ label = 'permissions';     pattern = '(?i)/permission|permission\.codeunit\.al$' }
    @{ label = 'reports';         pattern = '(?i)/reports?/|report\.codeunit\.al$|reportdataset' }
    @{ label = 'xml-integration'; pattern = '(?i)/(xml|edoc|integration|electronic|edi)/|xmlport|xmlnode' }
    @{ label = 'pages';           pattern = '(?i)/pages?/' }
    @{ label = 'posting';         pattern = '(?i)/(posting|post)/' }
    @{ label = 'setup';           pattern = '(?i)/setup/|setup\.codeunit\.al$' }
)

$script:SubjectBodyRules = @(
    @{ label = 'reports';         pattern = '(?i)\bLibraryReportDataset\b|\bReport\.Run\b|\bRequestPageHandler\b|\bLoadDataSetFile\b' }
    @{ label = 'xml-integration'; pattern = '(?i)\bXMLPort\b|\bXmlDoc\b|\bXmlNode\b|\bElectronicDocument\b|\bEDocument\b' }
    @{ label = 'pages';           pattern = '(?i)\bTestPage\b' }
    @{ label = 'posting';         pattern = '(?i)\bLibrary(ERM|Sales|Purchase|Inventory|Job|Manufacturing|Service|Warehouse)\.Post|\bPostSalesDocument\b|\bPostPurchaseDocument\b|\bPostJournalLines?\b|::Post\b' }
    @{ label = 'permissions';     pattern = '(?i)\bLibraryLowerPermissions\b\.SetO365' }
    @{ label = 'setup';           pattern = '(?i)\bRecord\s+"[^"]*Setup"' }
    @{ label = 'calculation';     pattern = '(?i)\bCalc(ulate)?\w*\(|\bCalcFields\b|\bCalcSums\b|\bRoundAmount\b' }
)

$script:InteractionRules = @(
    # Order: most-specific first.
    @{ label = 'asserterror';    pattern = '(?im)^\s*asserterror\b' }
    @{ label = 'confirm-dialog'; pattern = '(?i)\bConfirmHandler\b|HandlerFunctions\([^)]*Confirm|\bLibraryVariableStorage\.Enqueue\b.*\bConfirm\b' }
    @{ label = 'report-request'; pattern = '(?i)\bRequestPageHandler\b|\bReport\.RunModal\b|\bReport\.Run\b' }
    @{ label = 'modal-page';     pattern = '(?i)\bModalPageHandler\b|\bRunModal\b' }
    @{ label = 'notification';   pattern = '(?i)\bSendNotificationHandler\b|RecallNotificationHandler\b|\bNotification\b\s*:|\.SendNotification\b' }
    @{ label = 'direct-call';    pattern = '(?i)\bTestPage\b|\.OpenEdit\b|\.OpenView\b|::Run\b' }
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

function Get-AlSubjectLabel {
    <#
    .SYNOPSIS
        Returns one of the eight subject labels for a corpus row.
    .PARAMETER Path
        The repo-relative file path (e.g. corpus row's `file`).
    .PARAMETER Body
        The procedure body text.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [string] $Path,
        [string] $Body
    )

    if ($Path) {
        foreach ($r in $script:SubjectPathRules) {
            if ($Path -match $r.pattern) { return $r.label }
        }
    }
    if ($Body) {
        foreach ($r in $script:SubjectBodyRules) {
            if ($Body -match $r.pattern) { return $r.label }
        }
    }
    return 'other'
}

function Get-AlInteractionLabel {
    <#
    .SYNOPSIS
        Returns one of the seven interaction labels for a corpus row.
    .PARAMETER Body
        The procedure body text.
    .PARAMETER Attributes
        Optional list of AL attributes attached to the procedure
        (e.g. `Test`, `ConfirmHandler`, `ModalPageHandler`).
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [string]   $Body,
        [string[]] $Attributes
    )

    if ($Attributes) {
        $attrText = ($Attributes -join ' ')
        if ($attrText -match '(?i)ConfirmHandler')           { return 'confirm-dialog' }
        if ($attrText -match '(?i)ModalPageHandler')         { return 'modal-page' }
        if ($attrText -match '(?i)RequestPageHandler')       { return 'report-request' }
        if ($attrText -match '(?i)NotificationHandler')      { return 'notification' }
    }
    if ($Body) {
        foreach ($r in $script:InteractionRules) {
            if ($Body -match $r.pattern) { return $r.label }
        }
    }
    return 'none'
}

function Get-AlClassification {
    <#
    .SYNOPSIS
        Convenience wrapper: returns @{ subject = ...; interaction = ... }.
    #>
    [CmdletBinding()]
    [OutputType([hashtable])]
    param(
        [string]   $Path,
        [string]   $Body,
        [string[]] $Attributes
    )

    return @{
        subject     = Get-AlSubjectLabel     -Path $Path -Body $Body
        interaction = Get-AlInteractionLabel -Body $Body -Attributes $Attributes
    }
}

Export-ModuleMember -Function Get-AlSubjectLabel, Get-AlInteractionLabel, Get-AlClassification
