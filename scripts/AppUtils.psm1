using module .\BCBenchUtils.psm1
using module .\DatasetEntry.psm1

<#
    .Synopsis
    Compiles and publishes an app to a Business Central container with force sync.
    .Parameter containerName
    The name of the container to publish the app to.
    .Parameter appProjectFolder
    The full path to the app project folder.
    .Parameter credential
    The credential to use when publishing the app.
    .Parameter skipVerification
    If specified, app verification will be skipped during publishing.
    .Parameter useDevEndpoint
    If specified, the dev endpoint will be used for publishing.
    .Description
    This function compiles an AL app project and publishes it to a Business Central container.
    The app is published with ForceSync to ensure schema changes are applied.
    Based on the implementation in BCApps/build/scripts/DevEnv/NewDevEnv.psm1
#>
function Invoke-AppBuildAndPublish {
    param(
        [Parameter(Mandatory = $true)]
        [string] $containerName,

        [Parameter(Mandatory = $true)]
        [string] $appProjectFolder,

        [Parameter(Mandatory = $true)]
        [PSCredential] $credential,

        [Parameter(Mandatory = $false)]
        [switch] $skipVerification,

        [Parameter(Mandatory = $false)]
        [switch] $useDevEndpoint
    )

    try {
        if ($env:CI) {
            Write-Output "::group::Compiling app: $appProjectFolder"
        }

        [string] $outputPath = Join-Path $appProjectFolder "output"
        Remove-Item -Path "$outputPath\*" -Force -Recurse -ErrorAction SilentlyContinue
        [string] $appSymbolsFolder = Join-Path $appProjectFolder ".alpackages"
        Remove-Item -Path "$appSymbolsFolder\*" -Force -Recurse -ErrorAction SilentlyContinue

        $compileParams = @{
            containerName        = $containerName
            appProjectFolder     = $appProjectFolder
            appOutputFolder      = $outputPath
            credential           = $credential
            appSymbolsFolder     = $appSymbolsFolder
            GenerateReportLayout = 'No'
            gitHubActions        = $false
            nowarn               = 'AL0432;AL0523;AL0547;AL0551;AL0602;AL0659;AL0684;AL0685;AL0748'
        }

        if ($env:RUNNER_DEBUG -eq '1') {
            # debug mode
            Compile-AppInBcContainer @compileParams
        }
        else {
            $compileOutput = Compile-AppInBcContainer @compileParams 2>&1
        }

        if ($env:CI) {
            Write-Output "::endgroup::"
        }
        Write-Log "Publishing and syncing app from: $outputPath" -Level Info

        # Get the compiled result app file
        $appFile = Get-ChildItem -Path $outputPath -Filter "*.app" | Select-Object -First 1 -ExpandProperty FullName

        if (-not $appFile) {
            throw "No compiled app file found in $outputPath"
        }

        # Publish the app with ForceSync
        $publishParams = @{
            containerName              = $containerName
            appFile                    = $appFile
            credential                 = $credential
            syncMode                   = 'ForceSync'
            dependencyPublishingOption = 'ignore'
            sync                       = $true
            install                    = $true
        }

        if ($skipVerification) {
            $publishParams.skipVerification = $true
        }

        if ($useDevEndpoint) {
            $publishParams.useDevEndpoint = $true
        }

        Publish-BcContainerApp @publishParams

        Write-Log "Successfully compiled and published app from: $appProjectFolder" -Level Success
    }
    catch {
        Write-Log "Failed to compile and publish app from ${appProjectFolder}: $($_.Exception.Message)" -Level Error

        if ($env:RUNNER_DEBUG -ne '1') {
            if ($compileOutput) {
                Write-Log "Compilation output:" -Level Error
                Write-Log $compileOutput -Level Error
            }
        }
        throw
    }
}

<#
    .Synopsis
    Runs tests for a single codeunit in a Business Central container.
    .Parameter containerName
    The name of the container to run tests in.
    .Parameter credential
    The credential to use when running tests.
    .Parameter codeunitID
    The ID of the test codeunit to run.
    .Parameter functionNames
    Optional array of function names to run. If not specified, all tests in the codeunit will run.
    .Description
    This function runs tests for a single codeunit in a Business Central container.
    Returns $true if all tests pass, $false otherwise.
#>
function Invoke-BCTest {
    param(
        [Parameter(Mandatory = $true)]
        [string] $containerName,

        [Parameter(Mandatory = $true)]
        [PSCredential] $credential,

        [Parameter(Mandatory = $true)]
        [int] $codeunitID,

        [Parameter(Mandatory = $false)]
        [string[]] $functionNames
    )

    if ($functionNames -and $functionNames.Count -gt 0) {
        [string] $combinedFunctions = $functionNames -join '|'
        Write-Log "Running tests for Codeunit $codeunitID with functions: $combinedFunctions" -Level Info
    }
    else {
        [string] $combinedFunctions = '*'
        Write-Log "Running all tests for Codeunit $codeunitID" -Level Info
    }

    $testParams = @{
        containerName         = $containerName
        credential            = $credential
        returnTrueIfAllPassed = $true
        testCodeunitRange     = $codeunitID.ToString()
        testFunction          = $combinedFunctions
        detailed              = $true
    }

    try {
        [bool] $testPassed = Run-TestsInBcContainer @testParams

        if ($testPassed) {
            Write-Log "Tests passed for Codeunit $codeunitID" -Level Success
        }
        else {
            Write-Log "Tests failed for Codeunit $codeunitID" -Level Error
        }

        return $testPassed
    }
    catch {
        Write-Log "Test execution error for Codeunit ${codeunitID}: $($_.Exception.Message)" -Level Error
        throw
    }
}

<#
    .Synopsis
    Runs tests in a Business Central container based on TestEntry objects.
    .Parameter containerName
    The name of the container to run tests in.
    .Parameter credential
    The credential to use when running tests.
    .Parameter testEntries
    An array of TestEntry objects containing codeunitID and functionName arrays.
    .Parameter expectation
    Expected test outcome: 'Pass' or 'Fail'. Throws an error if the actual result doesn't match.
    .Description
    This function runs tests in a Business Central container based on TestEntry objects
    from the dataset. Each TestEntry contains a codeunit ID and array of function names.
    Throws an error if the test results don't match the expectation.
#>
function Invoke-DatasetTests {
    param(
        [Parameter(Mandatory = $true)]
        [string] $containerName,

        [Parameter(Mandatory = $true)]
        [PSCredential] $credential,

        [Parameter(Mandatory = $false)]
        [TestEntry[]] $testEntries,

        [Parameter(Mandatory = $true)]
        [ValidateSet('Pass', 'Fail')]
        [string] $expectation
    )
    if ($env:CI) {
        Write-Output "::group::Running Tests for: $($testEntries.CodeunitID), expectation: $expectation"
    }

    if ($testEntries.Count -eq 0) {
        Write-Log "No test entries provided, skipping test execution" -Level Warning

        if ($env:CI) {
            Write-Output "::endgroup::"
        }
        return
    }

    [bool] $allTestsPassed = $true

    foreach ($testEntry in $testEntries) {
        [int] $codeunitID = $testEntry.codeunitID
        [string[]] $functionNames = $testEntry.functionName

        [bool] $testPassed = Invoke-BCTest -containerName $containerName -credential $credential -codeunitID $codeunitID -functionNames $functionNames

        if (-not $testPassed) {
            $allTestsPassed = $false
        }
    }

    if ($expectation -eq 'Pass' -and -not $allTestsPassed) {
        throw "Tests were expected to Pass but some tests failed"
    }
    elseif ($expectation -eq 'Fail' -and $allTestsPassed) {
        throw "Tests were expected to Fail but all tests passed"
    }

    Write-Log "Test expectation '$expectation' met successfully" -Level Success

    if ($env:CI) {
        Write-Output "::endgroup::"
    }
}
