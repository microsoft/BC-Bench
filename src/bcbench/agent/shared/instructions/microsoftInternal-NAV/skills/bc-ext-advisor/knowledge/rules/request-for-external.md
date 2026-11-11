# Request-for-External Rules

Apply to `request-for-external`, in addition to the general rules.

## Implementation guidance
- **Widening visibility.** *Apply directly.* Make a member externally accessible by removing the `local` modifier or the `[Scope('OnPrem')]` attribute, as appropriate.
- **`var` → `protected var`.** *Apply directly.* If no `protected var` section exists, add one after all `var` declarations. Keep the order `var` → `protected var` → procedures; never interleave `var` and `protected var`.
