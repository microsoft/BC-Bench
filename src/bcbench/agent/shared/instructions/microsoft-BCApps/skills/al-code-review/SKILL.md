---
name: al-code-review
description: 'Review AL code for Dynamics 365 Business Central by composing specialized review sub-skills (performance, security, privacy, upgrade, style), each backed by curated BCQuality knowledge files. Use when reviewing AL code changes or pull requests and producing structured findings.'
allowed-tools: Read, Glob, Grep, LSP
argument-hint: 'leave empty to run the full composed review across all domains'
---

# AL Code Review (composed super-skill / sub-skill review)

Reviews AL code for Dynamics 365 Business Central using a **composition** pattern: a single
super-skill invokes five domain leaf sub-skills one at a time, each evaluating the diff against
its own curated **knowledge files**, then performs a cross-cutting self-review pass. The result
is mapped into this repository's `review.json` schema.

## When to Use

- Reviewing AL code changes or pull requests
- User asks for "code review", "review this AL code", or domain-specific analysis

## Vendored layout — all paths are relative to THIS skill folder

This skill is self-contained. The evaluator copies it to `.github/skills/al-code-review/`.
Every path referenced by the vendored framework files below resolves **relative to this skill
folder** (the directory containing this `SKILL.md`), not the repository root:

```
.github/skills/al-code-review/
  SKILL.md                                  <- this entry point (you are here)
  skills/
    read.md                                 <- READ contract: how to read a knowledge file
    do.md                                   <- DO contract: the action-skill template + output schema
  microsoft/
    skills/review/
      al-code-review.md                     <- the super-skill (composition orchestrator)
      al-performance-review.md              <- leaf sub-skill
      al-privacy-review.md                  <- leaf sub-skill
      al-security-review.md                 <- leaf sub-skill
      al-style-review.md                    <- leaf sub-skill
      al-upgrade-review.md                  <- leaf sub-skill
    knowledge/
      performance/  privacy/  security/  style/  upgrade/   <- knowledge files (*.md) + samples (*.al)
  knowledge-index.json                      <- discovery metadata for the knowledge corpus
```

This `SKILL.md` is the entry point. The BCQuality framework's own `entry.md` routing/dispatch
step is **not** vendored — its job is fulfilled here: you always dispatch the single super-skill
`microsoft/skills/review/al-code-review.md`. Ignore any reference to `entry.md` inside the
vendored contracts; wherever a contract says "the knowledge index BCQuality builds at the root of
the knowledge checkout", read the already-built `knowledge-index.json` in this skill folder.

## Review Process

1. **Read the contracts first.** Read `skills/read.md` (knowledge-file schema + frontmatter
   matching) and `skills/do.md` (action-skill template, severity taxonomy, output contract,
   agent-finding precision bar).
2. **Invoke the super-skill.** Read `microsoft/skills/review/al-code-review.md` and execute it.
   It composes the five leaf sub-skills listed in its frontmatter `sub-skills`.
3. **Run each leaf one at a time (mandatory execution discipline).** For each of
   `al-performance-review`, `al-security-review`, `al-privacy-review`, `al-upgrade-review`,
   `al-style-review`: read the leaf file, read `knowledge-index.json`, select the candidate
   articles for that leaf's `domain`, open only the worklisted knowledge files in full, and
   evaluate the diff against their `## Best Practice` / `## Anti Pattern` sections. Do NOT
   collapse multiple leaves into one shared scan — each leaf re-walks the diff independently.
4. **Cross-cutting self-review pass.** After all five leaves finish, perform the super-skill's
   own self-review for defects that span domain boundaries. Hold agent findings to the precision
   bar in `skills/do.md` (concrete, demonstrable, material; steelman first; when in doubt, omit).
5. **Map and write output.** Convert the rolled-up findings into this repository's `review.json`
   schema (below) and save to a file named `review.json` in the repository root.

## Scope of the diff

Review ONLY the current working-tree AL file changes for this evaluation entry. Do NOT compare
commits (do NOT use `HEAD~1..HEAD` or `origin/main`). Use working-tree diff only (`git diff HEAD`)
and focus on changed `*.al` files.

## Strict domain discipline

Each leaf sub-skill owns exactly one domain and emits findings only within that domain. When a
leaf is active, judge every candidate by its **root cause**, not by surrounding names: a
non-translatable string in a method called `GenerateComplianceReport` is a `style` issue, not
`privacy`. If a candidate's root cause is outside the active leaf's domain, the active leaf stays
silent — the owning leaf (or the cross-cutting pass) will surface it. When in doubt, drop it.

## Output mapping — BCQuality findings-report -> review.json

The composed run produces a BCQuality findings-report (see `skills/do.md`). Map it into the
`review.json` schema this repository expects. The output file MUST contain valid JSON with a
top-level object named `findings`; each finding is an object with exactly these fields:

| review.json field | Source in the BCQuality finding | Notes |
|-------------------|---------------------------------|-------|
| `filePath`        | `location.file`                 | Repo-relative path of the changed `*.al` file. |
| `lineNumber`      | `location.line`                 | 1-based line in the changed file. |
| `severity`        | `severity`                      | Map: `blocker`->`critical`, `major`->`high`, `minor`->`medium`, `info`->`low`. |
| `issue`           | `message`                       | Describe the concern. |
| `recommendation`  | `message` / knowledge guidance  | The concrete fix; draw from the knowledge file's `## Best Practice` when present. |
| `domain`          | `from-sub-skill`                | Map leaf id to domain (below). |
| `suggestedCode`   | `suggested-code`                | Literal replacement for the located lines; empty string if none. |

Domain mapping for `from-sub-skill`:

- `al-performance-review` -> `performance`
- `al-security-review` -> `security`
- `al-privacy-review` -> `privacy`
- `al-upgrade-review` -> `upgrade`
- `al-style-review` -> `style`
- `agent` (cross-cutting self-review finding) or a leaf's own agent finding -> map to the single
  closest of the five domains above by the finding's root cause.

Allowed `severity` values in `review.json` are exactly: `critical`, `high`, `medium`, `low`.
Drop the BCQuality-only fields (`id`, `references`, `confidence`, `from-sub-skill`, `sub-results`,
etc.) — they are not part of `review.json`. If there are no findings, write an empty `findings`
list.

Example `review.json`:

```json
{
  "findings": [
    {
      "filePath": "src/Sales/PostingRoutines.Codeunit.al",
      "lineNumber": 140,
      "severity": "high",
      "issue": "FindSet is called without a prior SetRange/SetFilter, forcing a full-table scan.",
      "recommendation": "Apply SetRange/SetFilter to narrow the record set before FindSet, per the filter-before-find guidance.",
      "domain": "performance",
      "suggestedCode": ""
    }
  ]
}
```
