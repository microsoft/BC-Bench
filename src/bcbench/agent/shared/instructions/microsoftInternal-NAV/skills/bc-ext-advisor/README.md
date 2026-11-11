# BC Extensibility Advisor (skill: `bc-ext-advisor`)

A self-contained GitHub Copilot **skill** that helps Business Central users turn an
extensibility need into a well-formed GitHub issue in `microsoft/ALAppExtensions`.

It is **advisory and minimalistic**: pure Markdown knowledge, no MCP server, no Node/TypeScript
build, no external dependencies. The skill reads only the files in this folder and submits the
issue with the `gh` CLI. It never edits, builds, or runs AL source, and it gives no final approval
— a human maintainer decides.

## What it does

1. Classifies the request by type — currently `event-request`, `request-for-external`,
   `enum-request`, or `extensibility-enhancement` (with subtypes where they apply). The types are
   defined in `knowledge/request-types.md` and can be extended there.
2. Loads the mandatory requirements and the blockers/warnings for that type.
3. Gathers the concrete change first, then leads with specific existing-extensibility-point
   suggestions before accepting an alternatives claim.
4. Drafts the issue against the standard two-section template.
5. Submits it to `microsoft/ALAppExtensions` (type `Task`) with `gh` — only after explicit approval.

## Folder layout — everything is local, nothing is referenced from outside

```
BC-Ext-Advisor/
├── SKILL.md                              # the skill: definition + orchestration flow
├── README.md                             # this file
├── templates/
│   └── extensibility-request.md          # the exact issue structure to draft against
└── knowledge/
    ├── general-guidance.md               # communication, eligibility, how to ask
    ├── request-types.md                  # the request types + classification rules
   ├── request_requirements/             # mandatory/optional info per type
    │   ├── general.md
    │   ├── event-request.md
    │   ├── event-request.ishandled.md
    │   ├── enum-request.md
    │   ├── request-for-external.md
    │   └── extensibility-enhancement.md
    ├── rules/                            # blockers, warnings, alternatives, implementation guidance
    │   ├── general-blockers.md
    │   ├── event-request.md
    │   ├── event-request.ishandled.md
    │   ├── enum-request.md
    │   ├── request-for-external.md
    │   └── extensibility-enhancement.md
    └── examples/                         # worked good/bad requests per type
        ├── event-request-good.md
        ├── event-request-bad.md
        ├── event-request.ishandled-good.md
        ├── enum-request-good.md
        ├── request-for-external-good.md
        └── extensibility-enhancement-good.md
```

Filename convention resolved by the flow:
- Requirements: `<type>.md` and, where needed, `<type>.<subtype>.md`.
- Rules: `<type>.md` and `<type>.<subtype>.md`.
- Examples: `<type>-good.md` / `<type>-bad.md` / `<type>.<subtype>-good.md`.
`knowledge/request_requirements/general.md` and `knowledge/rules/general-blockers.md` apply to every type.

## Use in VS Code

1. Copy the whole `BC-Ext-Advisor/` folder into your repository's skills location so Copilot can
   discover it (for example `.github/skills/bc-ext-advisor/`). Keep the folder intact — the skill
   reads its `knowledge/` and `templates/` by relative path.
2. Open the repository in VS Code with the **GitHub Copilot** and **Copilot Chat** extensions and
   Agent Skills enabled.
3. In Copilot Chat (agent mode), describe your extensibility need. Copilot invokes the skill when
   the ask matches its `description` (an event, making a member public/global, adding/extending an
   enum, or a general extensibility enhancement on a Microsoft base-app object).
4. Answer the questions, review the drafted issue, and approve it to submit.

It works the same way from the **Copilot CLI**.

## Requirements

- The authenticated `gh` CLI (run `gh auth login` once) — used only to create the approved issue.
- No other tooling, packages, or build steps.

## Scope

- **In scope:** Microsoft base-application AL objects (`.al`/`.dal`, namespace under `Microsoft`).
- **Out of scope:** custom/non-Microsoft objects, non-AL code, pure bug reports, and any request to
  write or fix AL code.
