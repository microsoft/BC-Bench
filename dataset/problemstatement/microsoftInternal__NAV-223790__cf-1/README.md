# Title: "Calculate Regenerative Plan" does not plan component — wrong CalcLevels parameter
## Repro Steps:
Same as NAV-223790 base repro.

## Description:
Variant of NAV-223790 where the CalcLevels procedure is called with the wrong first parameter (0 instead of 1). The first parameter controls the calculation type semantic — 0 produces an incorrect LLC value that leaves the planning BOM expansion stale. This is an L1 (API/signature misuse) variant: the code compiles and the trigger fires, but the parameter semantic is wrong, causing the LLC to remain incorrect.
