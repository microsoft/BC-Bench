# Running AL Tests

**CRITICAL: Follow these steps strictly in order.**

**IMPORTANT — Environment loss:** Terminal sessions lose their initialized environment when switching between tools or after certain operations. You MUST ALWAYS run `init.ps1` immediately before `Run-NAVALTests` in a SINGLE combined command to ensure the environment is properly initialized.

## STEP 1 — Initialize environment AND run tests in a SINGLE terminal command

**NEVER run `Run-NAVALTests` separately from `init.ps1`** — always combine them to avoid environment loss.

To run a whole test codeunit (without specifying individual test procedures):

```powershell
cd $(git rev-parse --show-toplevel); .\init.ps1 -SkipSetup -SkipNuGetSetup; Run-NAVALTests -ServerInstance <server instance> -CountryCode <country> -TestCodeunitsRange <test codeunit ID> -WebClientUrl (Get-ALTestWebClientUrl -ServerInstanceName <server instance> -CompanyName (Get-NavDefaultCompanyName))
```

To run only specific test procedures:

```powershell
cd $(git rev-parse --show-toplevel); .\init.ps1 -SkipSetup -SkipNuGetSetup; Run-NAVALTests -ServerInstance <server instance> -CountryCode <country> -TestCodeunitsRange <test codeunit ID> -TestMethodRange <test procedure names> -WebClientUrl (Get-ALTestWebClientUrl -ServerInstanceName <server instance> -CompanyName (Get-NavDefaultCompanyName))
```

### How to identify parameter values

- **`<server instance>`**: Read the AL project's `.vscode/launch.json` and use the value of the `serverInstance` property verbatim.
- **`<country>`**: Extract from `serverInstance`. If it follows `SOMETHING_XX` (e.g., `Nav_NO`, `Nav_US`), the suffix after `_` is the country code (`NO`, `US`). If no suffix, use `W1`.
- **`<test codeunit ID>`**: Look at the changed `.Codeunit.al` files containing `Subtype = Test`. Extract the codeunit ID from the declaration (e.g., `codeunit 148102 "SAF-T Unit Tests"` → `148102`).
- **`<test procedure names>`**: From the changed test codeunit, list all procedures with the `[Test]` attribute. Separate multiple names with `|`.

If you cannot read `launch.json` or determine the country code, **ask the user** to specify both `<server instance>` and `<country>`.

## STEP 2 — On failure

If any test fails, investigate and report up to **3** likely causes. **Do NOT** attempt fixes until the user approves.
