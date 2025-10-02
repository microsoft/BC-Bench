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
        Write-Log "Compiling app in path: $appProjectFolder" -Level Info

        # Set output folder for compiled app
        [string] $outputPath = Join-Path $appProjectFolder "output"

        $compileParams = @{
            containerName = $containerName
            appProjectFolder = $appProjectFolder
            appOutputFolder = $outputPath
            credential = $credential
        }

        if ($env:CI) {
            $compileParams.gitHubActions = $true
        }

        Compile-AppInBcContainer @compileParams

        Write-Log "Publishing and syncing app from: $outputPath" -Level Info

        # Get the compiled result app file
        $appFile = Get-ChildItem -Path $outputPath -Filter "*.app" | Select-Object -First 1 -ExpandProperty FullName

        if (-not $appFile) {
            throw "No compiled app file found in $outputPath"
        }

        # Publish the app with ForceSync
        $publishParams = @{
            containerName = $containerName
            appFile = $appFile
            credential = $credential
            syncMode = 'ForceSync'
            dependencyPublishingOption = 'ignore'
            sync = $true
            install = $true
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

        [Parameter(Mandatory = $true)]
        [object[]] $testEntries,

        [Parameter(Mandatory = $true)]
        [ValidateSet('Pass', 'Fail')]
        [string] $expectation
    )

    if ($testEntries.Count -eq 0) {
        Write-Log "No test entries provided, skipping test execution" -Level Warning
        return
    }

    [bool] $allTestsPassed = $true

    foreach ($testEntry in $testEntries) {
        [int] $codeunitID = $testEntry.codeunitID
        [string] $combinedFunctions = $testEntry.functionName -join '|'

        Write-Log "Running tests for Codeunit $codeunitID with functions: $combinedFunctions" -Level Info

        $testParams = @{
            containerName = $containerName
            credential = $credential
            returnTrueIfAllPassed = $true
            testCodeunitRange = $codeunitID.ToString()
            testFunction = $combinedFunctions
        }

        if ($env:RUNNER_DEBUG -eq '1') {
            $testParams.detailed = $true
        }

        [bool] $testPassed = Run-TestsInBcContainer @testParams

        if ($testPassed) {
            Write-Log "Tests passed for Codeunit $codeunitID" -Level Success
        } else {
            Write-Log "Tests failed for Codeunit $codeunitID" -Level Error
            $allTestsPassed = $false
        }

    }

    # Validate expectation
    if ($expectation -eq 'Pass' -and -not $allTestsPassed) {
        throw "Tests were expected to Pass but some tests failed"
    }
    elseif ($expectation -eq 'Fail' -and $allTestsPassed) {
        throw "Tests were expected to Fail but all tests passed"
    }

    Write-Log "Test expectation '$expectation' met successfully" -Level Success
}