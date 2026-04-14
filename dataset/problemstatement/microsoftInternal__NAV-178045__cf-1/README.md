# Title: Consumption not posted for multiple ILEs of same Lot No. — only when multiple entries exist
## Repro Steps:
Same as NAV-178045 base repro, except:
- Only **two** Item Journal Lines are posted with the same Lot No. (5 and 10 qty) instead of three
- Total consumption quantity is 15 instead of 35

## Description:
Variant of NAV-178045 (L2: condition-change). The fix only applies the consumption correction when multiple Item Ledger Entries exist for the same lot (Count > 1 guard). Test uses 2 journal lines instead of 3 to create a tighter scenario while still exercising the multi-ILE path.
