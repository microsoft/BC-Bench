# Title: W1 2025 - Bug Bash IV [Sustainability] Value Chain Tracking Enablement
## Repro Steps:
1. Open the **Sustainability Setup** page
2. Keep all fields in the **Procurement** FastTab disabled
3. Enable the **'Enable Value Chain Tracking'** field

===RESULT===
Only the 'Enable Value Chain Tracking' field has been enabled

===EXTECTED RESULT===
Enabling this field, it will also enable the following fields if they are not previously enabled:
* Use Emissions in Purchase Documents
* Item Emissions
* Resource Emissions
* Work/Machine Center Emissions

## Description:
This is small improvement. You cannot use Value Chain tracking enabled if you didn't previously enable the following options:
* Use Emissions in Purchase Documents
* Item Emissions
* Resource Emissions
* Work/Machine Center Emissions

So, just enable them when you enable the **Enable Value Chain Tracking** field if these fields are not previously already enabled.
