# Title: "Calculate Regenerative Plan" does not plan component — LLC via event subscriber
## Repro Steps:
Same as NAV-223790 base repro.

## Description:
Variant of NAV-223790 where the Low-Level Code update is implemented through an EventSubscriber on the SKU table's "Production BOM No." OnAfterValidateEvent, rather than a direct OnValidate trigger body in the table extension. This is an L3 (event/trigger paradigm) variant: the same logic executes, but through the publisher-subscriber pattern instead of imperative trigger code. A new codeunit "Mfg. SKU Subscribers" hosts the subscriber procedure.
