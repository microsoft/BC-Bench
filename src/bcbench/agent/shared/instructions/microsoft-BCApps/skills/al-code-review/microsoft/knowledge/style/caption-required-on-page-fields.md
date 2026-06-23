---
bc-version: [all]
domain: style
keywords: [caption, page-field, aa0225, aa0226, codecop, captionclass]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Every page field needs a `Caption` (CodeCop AA0225/AA0226)

## Description

CodeCop AA0225 and AA0226 require every field control to expose a `Caption` property, separately from the field's source name. The caption is what the user sees as the column header or label; the source name is what the code uses to reference the field. Without an explicit `Caption`, AL falls back to the source field's caption — which may be wrong for the page's context — or to the field name itself in code casing, which surfaces internal naming to users and to translators.

Acceptable exceptions: a field whose caption is inherited via `CaptionClass = '3,5,' + CurrencyCode` (or another CaptionClass formula) does not need a literal `Caption`; the formula provides it. API pages and test pages may omit captions because their consumers are not human users. Boolean fields whose name already reads as a sentence — `Enabled`, `Posted`, `Released` — do not need a redundant Caption that repeats the name.

## Best Practice

`Caption = 'Customer No.';` paired with `ToolTip = 'Specifies …';`. Captions are short, noun-phrase, title-case for primary labels; sentence-case is allowed for descriptive labels that read as a sentence fragment.

See sample: `caption-required-on-page-fields.good.al`.

## Anti Pattern

A field control with no `Caption` and no `CaptionClass`, or `Caption = '';`. The user sees the internal identifier as the column header and the translation pipeline has nothing to translate.

See sample: `caption-required-on-page-fields.bad.al`.
