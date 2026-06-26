# Conditional LSP Instruction in Benchmark Prompts

Date: 2026-06-26
Status: Approved

## Problem

When a benchmark run is started with `--al-lsp`, the agent gets an AL Language
Server (via the `al-lsp-plugin` written by `build_al_lsp_plugin`) that exposes
diagnostics, go-to-definition, hover, and completion over `.al` files. However,
nothing in the prompt tells the agent that this capability exists or that it
should be preferred over text search (grep/ripgrep) for symbol-level work. As a
result the agent tends to grep, which produces false positives and undermines the
existing "BUILD MUST SUCCEED / no invented procedures or fields" goals.

We want a prompt instruction that **forces the agent to prioritize the AL Language
Server over grep** for verifying symbols, reading signatures, and checking compile
errors. The instruction must appear **only when `--al-lsp` is enabled**, and must
not appear otherwise.

## Goals

- Inject an LSP-first instruction into the rendered prompt when, and only when,
  `--al-lsp` is enabled.
- Apply to all three prompt categories: `bug-fix`, `test-generation`, and
  `code-review`.
- Keep the instruction text defined once (DRY) while letting each template control
  placement.
- No change in behavior when `--al-lsp` is off (instruction absent).

## Non-Goals

- No change to how the LSP server itself is launched or configured
  (`build_al_lsp_plugin` is untouched).
- No interaction with `--al-mcp`. The two are complementary: MCP governs
  build/run, LSP governs navigation/verification.
- `find-references` is intentionally excluded (less certain to be exposed by
  `al launchlspserver`); only definition, hover, completion, and diagnostics are
  referenced.

## Design

### 1. Shared instruction text in config

Add a single key under `prompt:` in
`src/bcbench/agent/shared/config.yaml` so the wording lives in one place:

```yaml
prompt:
  lsp-instruction: |-
    - An AL Language Server is available for .al files and is the authoritative source of truth for code
      navigation. Use it — not grep/ripgrep — to confirm a procedure, object, table, or field exists and to
      read its exact signature (go-to-definition, hover, completion), and check its diagnostics to catch
      compile errors before finalizing. Do NOT use text search to verify symbols: grep matches raw text and
      returns false positives from comments, string literals, and similarly named identifiers in other objects.
      Fall back to grep only for non-symbol patterns (comments, literals, config values) or if the server is unavailable.
```

Wording follows the "explicit prohibition + rationale + escape hatch" pattern that
research showed is the most effective at changing agent behavior (vs. a soft
"prefer" verb).

### 2. Template conditionals

The instruction is gated behind an `{% if al_lsp %}` block in each of the three
templates, rendering the shared variable:

```jinja2
{% if al_lsp %}
{{ lsp_instruction }}
{% endif %}
```

Placement:
- `bug-fix-template` and `test-generation-template`: as a bullet within the
  "Important constraints" list, alongside the existing `al_mcp` conditional line.
- `code-review-template`: **before** the "write only valid JSON to review.json"
  closing directive, so the final, strongest command is not diluted.

### 3. Threading `al_lsp` into `build_prompt`

`src/bcbench/agent/shared/prompt.py`:

- Add parameter `al_lsp: bool = False`.
- Read `lsp_instruction = prompt_config.get("lsp-instruction", "")`.
- Pass `al_lsp=al_lsp` and `lsp_instruction=lsp_instruction` to
  `template.render(...)`.

Jinja does not auto-resolve one config key from another; the value is read in
Python and passed as a normal render variable.

### 4. Callers

`al_lsp` is already in scope in both agent entrypoints. Update the existing calls:

- `src/bcbench/agent/copilot/agent.py`: `build_prompt(..., al_mcp=al_mcp)` →
  `build_prompt(..., al_mcp=al_mcp, al_lsp=al_lsp)`.
- `src/bcbench/agent/claude/agent.py`: same change.

### 5. Tests

`tests/test_copilot_prompt.py`: add assertions that a distinctive substring of the
LSP instruction (e.g. "AL Language Server") is **present** when `al_lsp=True` and
**absent** when `al_lsp=False`, covering all three categories.

## Alternatives Considered

- **Inline `{% if al_lsp %}` block with the full text duplicated in each
  template (A):** consistent with the `al_mcp` pattern and most discoverable, but
  duplicates the wording 3× so it drifts and is easy to miss a template.
- **Append the instruction in `build_prompt()` after render (C):** most DRY, but
  moves prompt prose into Python (wrong layer), is invisible to anyone editing
  prompts in config, and lands the text in a blunt position (after the task /
  after code-review's final JSON directive).

Approach B (shared config key + render variable) was chosen: DRY, keeps prose in
config, and lets each template control placement.

## Risks / Notes

- Whitespace: use YAML `|-` for the config block and keep the template conditional
  tight to avoid stray blank lines in the rendered prompt.
- The instruction is purely additive and off by default; runs without `--al-lsp`
  are unaffected.
