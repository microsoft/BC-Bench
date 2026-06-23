---
bc-version: [all]
domain: style
keywords: [xmldoc, summary, param, returns, public-procedure, documentation]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Add XML documentation to public procedures on library/API codeunits

## Description

XML documentation comments (`/// <summary>…</summary>`, `/// <param>…</param>`, `/// <returns>…</returns>`) are expected on procedures that form the public surface of a library — codeunits intended to be called from outside the current app: System App modules, AppSource library codeunits, `Access = Public` codeunits exposed for extension. The supported tags are `<summary>`, `<param>`, `<returns>`, `<example>`, `<remarks>`, and `<paramref>`. Active wording is preferred — `'Sets…'`, `'Gets…'`, `'Specifies…'` — and the docs should list parameter preconditions and any exceptions the procedure may raise.

XML docs are NOT required on internal procedures, event subscribers, trigger implementations, page-part procedures, test procedures, or the object declarations themselves (tables, pages, codeunits). The reviewer signal is a `procedure` (not `local procedure`, not `internal procedure`) declared inside a codeunit whose role is "library" — those need XML docs; everything else is optional.

## Best Practice

For every public procedure on a library codeunit, write a `<summary>` describing what the procedure does, one `<param>` per parameter naming its role and preconditions, and `<returns>` describing the return when applicable. Avoid placeholder text — `<summary>Validates discount</summary>` is no better than no doc at all.

## Anti Pattern

A public procedure on a library codeunit with no XML doc, or a `<summary>` that restates the procedure name in three words. The first leaves consumers guessing at intent; the second wastes the slot a meaningful description should occupy.
