<#
.SYNOPSIS
    Dataset types for Business Central evaluation scripts
.DESCRIPTION
    Load with `using module` to use the types in a script.
#>

class TestEntry {
    [int]$codeunitID
    [string[]]$functionName

    TestEntry([PSObject]$jsonObject) {
        $this.codeunitID = [int]$jsonObject.codeunitID
        $this.functionName = $jsonObject.functionName
    }
}
