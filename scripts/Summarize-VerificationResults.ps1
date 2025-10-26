using module .\scripts\VerificationResult.psm1

param(
    [Parameter(Mandatory = $true)]
    [string]$ResultsDir
)

$results = Read-VerificationResults -ResultsDir $ResultsDir
Show-VerificationSummary -Results $results
