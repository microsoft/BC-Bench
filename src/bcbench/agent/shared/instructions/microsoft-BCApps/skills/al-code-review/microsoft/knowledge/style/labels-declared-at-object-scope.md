---
bc-version: [all]
domain: style
keywords: [label, scope, procedure, translation, localization, xliff]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Declare Labels at object scope, not inside procedure `var` blocks

## Description

`Label` is the AL declaration that participates in the translation pipeline: the build extracts every Label declared in an object into the `.xlf` file shipped to translators, and the runtime substitutes the localized value when the object is loaded. Translation tooling discovers Labels by walking the object's top-level declarations.

Labels declared inside a procedure-local `var` block are still **compiled** as Label values, but their participation in localization is fragile: depending on the BC version, the build pipeline, and the translation toolchain in use, procedure-local Labels may be missed during XLIFF extraction, may be re-emitted with auto-generated keys that change between builds, or may not be addressable by reviewers triaging translations. The reliable, supported pattern is to declare every Label in the object's top-level `var` block.

The same rule applies to all object types that own behavior: codeunits, pages, tables, reports, queries, and their extensions. For shared messages used by multiple objects, declare the Label in the most appropriate owning object and reference it — do not duplicate the literal across procedure-scoped declarations in several places.

## Best Practice

Move every `Label` to the object's top-level `var` block. Use the appropriate suffix (`Msg`, `Err`, `Qst`, `Lbl`, `Tok`, `Txt`) on the variable name so reviewers and the translation team can see at a glance what role the string plays. Pair non-translatable strings (URLs, JSON/XML fragments, integration tokens) with `Locked = true`, as covered by `label-locked-for-non-translatable.md`.

See sample: `labels-declared-at-object-scope.good.al`.

## Anti Pattern

Declaring `Label` inside a procedure-local `var` block — `procedure Lookup() var GreetingMsg: Label 'Hello %1';` — couples the translatable string to one procedure, hides it from object-level review, and depends on a translation pipeline behavior that is not part of the AL language contract.

See sample: `labels-declared-at-object-scope.bad.al`.
