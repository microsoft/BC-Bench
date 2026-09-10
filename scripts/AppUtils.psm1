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
            nowarn               = 'AL0432;AL0523;AL0547;AL0551;AL0602;AL0659;AL0684;AL0685;AL0748;AL0254;AL0667'
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
    .Parameter evidenceDirectory
    The directory where discovery and JUnit evidence will be written.
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
        [string[]] $functionNames,

        [Parameter(Mandatory = $true)]
        [string] $evidenceDirectory
    )

    if ($functionNames -and $functionNames.Count -gt 0) {
        [string] $functionList = [string]::Join(', ', $functionNames)
        [string[]] $functionsToRun = $functionNames
        Write-Log "Running tests for Codeunit $codeunitID with functions: $functionList" -Level Info
    }
    else {
        [string[]] $functionsToRun = @('*')
        Write-Log "Running all tests for Codeunit $codeunitID" -Level Info
    }

    try {
        New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null

        [object[]] $availableCodeunits = @(
            Get-TestsFromBcContainer `
                -containerName $containerName `
                -credential $credential `
                -testCodeunitRange $codeunitID.ToString() `
                -ignoreGroups
        )
        [object] $availableCodeunit = $availableCodeunits |
            Where-Object { [int]$_.Id -eq $codeunitID } |
            Select-Object -First 1
        [string[]] $availableFunctions = if ($availableCodeunit) { @($availableCodeunit.Tests) } else { @() }
        [string[]] $discoveredFunctions = @(
            $functionNames | Where-Object { $availableFunctions -ccontains $_ }
        )

        [string] $discoveryPath = Join-Path $evidenceDirectory "discovery-$codeunitID.json"
        [PSCustomObject]@{
            codeunitID  = $codeunitID
            functionName = $discoveredFunctions
        } | ConvertTo-Json -Depth 5 | Set-Content -Path $discoveryPath -Encoding UTF8

        [string] $resultPath = Join-Path $evidenceDirectory "results-$codeunitID.xml"
        [bool] $allTestsPassed = $true
        [bool] $appendToResult = $false
        foreach ($functionName in $functionsToRun) {
            [hashtable] $testParams = @{
                containerName           = $containerName
                credential              = $credential
                returnTrueIfAllPassed   = $true
                testCodeunitRange       = $codeunitID.ToString()
                testFunction            = $functionName
                detailed                = $true
                JUnitResultFileName     = $resultPath
                AppendToJUnitResultFile = $appendToResult
            }

            [bool] $testPassed = Run-TestsInBcContainer @testParams
            if (-not $testPassed) {
                $allTestsPassed = $false
            }
            $appendToResult = $true
        }

        if ($allTestsPassed) {
            Write-Log "Tests passed for Codeunit $codeunitID" -Level Success
        }
        else {
            Write-Log "Tests failed for Codeunit $codeunitID" -Level Error
        }

        return $allTestsPassed
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
    .Parameter evidenceDirectory
    The directory where discovery and JUnit evidence will be written.
    .Description
    This function runs tests in a Business Central container based on TestEntry objects
    from the dataset. Each TestEntry contains a codeunit ID and array of function names.
    Test expectations are enforced by Python after the evidence is parsed.
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
        [string] $evidenceDirectory
    )
    if ($env:CI) {
        Write-Output "::group::Running Tests for: $($testEntries.CodeunitID)"
    }

    New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null

    if ($testEntries.Count -eq 0) {
        Write-Log "No test entries provided, skipping test execution" -Level Warning

        if ($env:CI) {
            Write-Output "::endgroup::"
        }
        return
    }

    foreach ($testEntry in $testEntries) {
        [int] $codeunitID = $testEntry.codeunitID
        [string[]] $functionNames = $testEntry.functionName

        Invoke-BCTest `
            -containerName $containerName `
            -credential $credential `
            -codeunitID $codeunitID `
            -functionNames $functionNames `
            -evidenceDirectory $evidenceDirectory | Out-Null
    }

    Write-Log "Test execution completed" -Level Success

    if ($env:CI) {
        Write-Output "::endgroup::"
    }
}
