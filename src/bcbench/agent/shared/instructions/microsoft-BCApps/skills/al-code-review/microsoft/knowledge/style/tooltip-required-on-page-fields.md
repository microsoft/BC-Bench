---
bc-version: [all]
domain: style
keywords: [tooltip, page-field, aa0218, codecop, accessibility, specifies]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Every page field needs a `ToolTip` (CodeCop AA0218)

## Description

CodeCop AA0218 requires a non-empty `ToolTip` property on every field control on a page. The tooltip is what users see on hover and is what screen readers announce; an empty or missing tooltip removes a piece of UI affordance that is part of BC's accessibility baseline. AppSource technical validation rejects pages with missing tooltips. The companion rules AA0219 and AA0220 push the wording further — tooltips should describe what the field shows, conventionally starting with `'Specifies …'`, though `'Shows …'` and similar variants are acceptable when they clearly describe the field's purpose.

Acceptable exceptions: table fields inside `Upgrade`, `Migration`, `HybridBC14`, `HybridSL`, and `HybridGP` codeunits and tables are allowed to omit the tooltip — those types are not surfaced to users.

## Best Practice

Every field control on a regular page carries `ToolTip = 'Specifies …';` (or a clear alternative phrasing). Compose the text in the form "what this value shows" rather than "what the user does with it".

See sample: `tooltip-required-on-page-fields.good.al`.

## Anti Pattern

A field control with no `ToolTip` property at all, or `ToolTip = '';`. AA0218 flags both; the hover state is blank and the screen reader has nothing to announce.

See sample: `tooltip-required-on-page-fields.bad.al`.
