# Title: Consumption not posted for multiple ILEs of same Lot No. — only when reservation exists
## Repro Steps:
Same as NAV-178045 base repro, except:
- Component Item has **Reserve = Optional** instead of Reserve = Always
- The bug scenario depends on reservation splitting across ILEs

## Description:
Variant of NAV-178045 (L2: condition-change). The fix only applies the consumption correction when Reserved Quantity is non-zero on the old Item Ledger Entry. Test uses Reserve::Optional instead of Reserve::Always to ensure the scenario explicitly depends on reservation behavior. If no reservation exists, standard application logic applies.
