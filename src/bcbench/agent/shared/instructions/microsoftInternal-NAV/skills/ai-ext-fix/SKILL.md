---
name: ai-ext-fix
description: >
  Implement a single Business Central extensibility request as an AL code change. The request is
  provided as plain text (a natural-language description of the extension point that is needed,
  usually a new integration event / event publisher). The skill locates the affected AL code in the
  current repository, adds the requested extension point following the repository extensibility
  guidelines, and propagates the change across the W1 base layer and any same-named country/region
  layer files. It edits only `.al` source files and leaves the changes unstaged in the working tree.
  No build, no tests, no commit, and no pull request. TRIGGER when the user asks to implement or add
  an extensibility request / extension point / integration event described in the provided text.
  DO NOT TRIGGER for bug fixes, for building or testing, or for opening pull requests.
allowed-tools: ['view', 'create', 'edit', 'grep', 'glob', 'powershell', 'ask_user']
---

# AI Extension Fix Skill

This skill implements one Business Central extensibility request entirely offline, inside the
current repository. It reads the request text, adds the requested extension point (most often an
integration event) to the standard code following the repository guidelines, and applies the
change W1-first with propagation to same-named country/region layer files. It does **not** build,
test, commit, or open a pull request. The change is left as unstaged edits in the working tree; the
author (or the evaluation harness) reviews the resulting diff.

---

## Critical Rules

- **Text input only**: The extensibility request is provided as plain text in the current
  conversation / prompt. Never fetch anything from an issue tracker or any external system, and never
  depend on labels, tickets, or online metadata.
- **Single request**: This skill implements one request per run. If more than one distinct request is
  provided, implement the first and warn.
- **No writeback, no PR**: Never commit, never push, never open or edit a pull request, and never run
  any `gh` command. The only deliverable is the set of local `.al` edits.
- **No build, no tests**: Never build, publish, or run the app, and never create tests. Produce a
  change that is aligned with the guidelines and, to the best of static reasoning, compilable.
  Correctness is verified by the human reviewer on the resulting diff.
- **Surgical changes**: Make the smallest diff that satisfies the request. Follow the repository's
  code surgery guidelines (see Step 2). Do not reformat, rename, reorder, or refactor unrelated code.
- **W1-first layering**: When the file to change exists in the W1 base layer (`App/Layers/W1/...`),
  make the change in W1 first, then apply the same change to every same-named counterpart file that
  exists in the other layers (Step 5). Only when the file exists solely in a specific country layer do
  you edit that layer directly and skip the propagation step.
- **AL files only**: Only ever create or modify `.al` source files. Never edit, add, or delete any
  other file type (for example `.json`, `.xml`, `.xlf`/translations, `.md`, `.txt`, project or
  settings files, workflows, or build scripts). If a correct change would require touching a
  non-`.al` file, STOP and report that instead of changing it.
- **No ticket-reference comments in code**: Do not add `// issue #<n>`-style comments or any external
  reference into the source.

---

## Step 1: Parse the Request

Review the current conversation and the most recent user message to extract the extensibility
request. Identify:

- **What extension point is asked for** — typically a new integration event / event publisher, but it
  may be an event added to an existing procedure or trigger.
- **Where it should live** — the object (codeunit/table/page/report), and the procedure or trigger and
  the exact placement (before/after a step, in an `else` branch of a `case`, etc.).
- **What data it must expose** — the records and parameters subscribers need.

If the request cannot be found in the provided text and an ask-user capability is available, ask the
user for it. If none is available (unattended), STOP with: `An extensibility request is required.`

If more than one distinct request is present, keep the first, warn that this skill implements a
single request per run, and ignore the rest.

---

## Step 2: Understand and Plan the Change

Build enough understanding to make a correct, minimal change.

1. **Load the guidelines** the change must follow, in this order:

   - The repository code surgery guidelines: read `.github/copilot/code-guidelines.md` if present.
   - The extension guidelines: read `guidelines.md` in this skill folder.
   - General AL best practices (see the checklist at the end of this file).

2. **Locate the affected code**: use `grep` and `glob` to find the AL objects, procedures, tables,
   pages, or codeunits named or implied by the request. Use `view` to read the candidate files and
   confirm relevance. Prefer searching for exact symbol names and object references mentioned in the
   request.

3. **Decide the layer (W1-first)**: this repository is layered under `App/Layers/` with a `W1` base
   layer and country layers (AT, AU, BE, CA, CH, CZ, DE, DK, ES, FI, FR, GB, IN, IS, IT, MX, NL, NO,
   NZ, RU, SE, US). For each file you plan to change, check whether it exists in the W1 layer:

   - **If the file exists under `App/Layers/W1/...`**: make the change there. In Step 5 you will apply
     the same change to every same-named counterpart file that exists in the other layers. Record
     `used_w1 = true`.
   - **If the file exists only in a specific country layer** (not in W1): edit that layer's file
     directly. No propagation applies; the change stays in that layer only.

4. **Form a concrete plan in memory** (do not write it to a tracked file): the specific edits, file by
   file, and the layer each edit lands in. There is no approval gate. Proceed directly to Step 3.

---

## Step 3: Implement the Change

Apply the planned edits with the `edit` and `create` tools.

- Make the **smallest diff** that satisfies the request. Add rather than change where reasonable.
- **Match the existing code style** in each file: indentation, casing, naming, and object layout.
- Follow the AL best-practice checklist below and the extension guidelines from Step 2.
- **Guidelines override the request**: If the request text contains a proposed solution (event names,
  parameter names, code snippets, or any other implementation detail) that does not comply with the
  guidelines, do **not** implement it as-is. Correct it to comply. The guidelines are the source of
  truth; the request's suggestion is a hint, not a specification. In particular, event names must
  follow the placement-based naming convention (for example `OnBeforePostSalesLine`,
  `OnPostSalesLineOnAfterCalculateAmounts`), and record parameters use full table names with spaces
  removed.
- Do **not** reformat, rename, reorder, or refactor code unrelated to the change.
- Edit **only `.al` files**. If the change seems to need a non-`.al` file, STOP and report it.
- Aim for code that compiles: keep object IDs, procedure signatures, and variable declarations
  consistent; ensure every referenced symbol exists; balance `begin`/`end`; and respect AL syntax.
  You will not build it here, so reason carefully about correctness.

Make **all** the W1-layer edits now, before propagating, so the W1 layer is in its final state
before Step 5.

---

## Step 4: (reserved)

There is no separate branch/commit step. The change stays as unstaged edits in the working tree.

---

## Step 5: Propagate W1 Changes to Same-Named Files in Other Layers

Run this step **only if** you changed at least one file under `App/Layers/W1/...` (`used_w1 == true`).
If every edit was in a country-only layer, skip this step.

A country layer overrides only a subset of files; the ones it does **not** contain are inherited from
W1 automatically. So propagation means: for each W1 file you changed, find the **same-named
counterpart files that already exist in the other layers** and apply the equivalent change to each of
them yourself with the `edit` tool.

For **each** W1 file you edited in Step 3:

1. **List the existing counterparts** in the other layers (same relative path under each layer root):

   ```powershell
   $w1File = "<the W1 file you changed, e.g. App/Layers/W1/BaseApp/.../Foo.Codeunit.al>"
   $rel = $w1File -replace '^App/Layers/W1/', ''
   Get-ChildItem "App/Layers" -Directory | Where-Object { $_.Name -ne 'W1' } | ForEach-Object {
     $candidate = Join-Path $_.FullName $rel
     if (Test-Path $candidate) { $candidate }
   }
   ```

   Each path returned is a layer that has its own copy of this file and therefore needs the change.
   Layers with no such file inherit W1 and are left untouched.

2. **Apply the equivalent change to each counterpart** with the `edit` tool:

   - Read the counterpart file first. It may already differ from W1 because that layer customized it.
   - Make the **same logical change** you made in W1 — locate the same object, procedure, or lines and
     apply it there.
   - **Adapt, do not overwrite**: preserve that layer's existing customizations, local naming, values,
     and any country-specific behavior. If the layer's code differs from W1's, apply the intent of the
     change to the layer's variant rather than pasting the W1 text verbatim.
   - Keep the same surgical, style-matching discipline as Step 3.

3. If a counterpart's code has genuinely diverged so the change does not map cleanly, apply the safest
   equivalent change (preserve the layer's behavior) and continue.

---

## Step 6: Summary

Report to the user, concisely:

- The extensibility request implemented, in one or two sentences.
- The extension point added (object, procedure/trigger, event name and signature).
- The exact list of `.al` files changed, including any propagated layer counterparts.

If no file changes were produced, STOP and report that the request did not lead to any code change,
explaining why.

---

## AL Best-Practice Checklist

Apply these when editing AL code, unless the surrounding code clearly follows a different local
convention (match the file):

- Follow standard event conventions: `[IntegrationEvent(false, false)]`, `local procedure`, empty
  body, and placement-accurate `OnBefore`/`OnAfter`/`On<Procedure>On<Timing>` naming.
- Use full table names with spaces removed for record parameters (e.g. `SalesHeader`, `Jobs Setup`
  → `JobsSetup`); do not abbreviate. Use descriptive names for simple-type parameters.
- Append new parameters to the end of an existing event signature; do not insert in the middle.
- When adding `IsHandled`, initialize it to `false` before the event call.
- Use meaningful PascalCase names for objects, procedures, and variables; match existing naming.
- Respect existing object IDs and app structure; do not renumber or move objects.
- Preserve `begin`/`end`, `case`, and `if/then/else` structure and existing indentation.
- Avoid breaking public/extensible signatures; add optional parameters or overloads instead.
- Keep changes backward compatible for existing callers and subscribers.
