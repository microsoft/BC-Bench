---
name: create-release
description: "Prepare BC-Bench release notes for review. Use when creating a release, screening merged PRs since the previous version tag for changes that may affect evaluation results, matching recent GitHub release notes, or reporting the agent harness and development tool versions shipped by a release."
---

# Create Release

Prepare release notes for maintainer review. Do not change versions, commit, tag, push, or create a GitHub release unless explicitly asked.

## Workflow

1. **Establish the range:** Read the version from `pyproject.toml` and use `v<version>` as the target tag. If that tag exists, use it as the target ref and select the preceding semantic-version tag. Otherwise, use `HEAD` as the target ref and select the latest reachable semantic-version tag. Ignore non-version tags such as evaluation-run tags. Exclude uncommitted changes and stop if the range is empty, ambiguous, or not fully available locally.
2. **Study the format:** Fetch and read the bodies of the three most recently published releases from `microsoft/BC-Bench`. Match their concise paragraph style, spacing, and `# Versions` section; do not use GitHub's automatically generated notes as the draft.
3. **Screen merged PRs:** Treat each commit in the complete `<previous-tag>..<target-ref>` range as a merged PR. Review its title, changed files, and PR description, inspecting the diff only as needed to determine whether it may affect evaluation results. Classify every PR as included or omitted, but do not produce a PR-by-PR summary.
4. **Select release-note content:** Include only changes that may affect evaluation results or their comparability, such as dataset and gold-answer changes, evaluation logic, prompts, models, agent harnesses, tools, result schemas, and execution behavior. Combine related PRs into outcome-focused paragraphs. Omit formatting, linting, tests, documentation, refactoring, dependency maintenance, and CI housekeeping unless they change benchmark behavior or reproducibility. Call out compatibility boundaries explicitly.
5. **Collect shipped versions:** Read the target ref, not the uncommitted worktree, and locate the exact pins for `@github/copilot`, `@anthropic-ai/claude-code`, and `Microsoft.Dynamics.BusinessCentral.Development.Tools`. Confirm duplicate pins agree. Never copy versions from an older release or infer them from commit messages.
6. **Validate the draft:** Ensure every claim is supported by an included PR, every PR in the range was classified, omitted PRs have no plausible evaluation impact, the target version is correct, and the three shipped versions are exact. Stop and report conflicting pins, missing history, or uncertain evaluation impact instead of guessing.

## Output

Return one fenced `markdown` block containing the release body for review. Do not include the tag or release title in the body, a commit-by-commit list, PR links, a comparison link, or commentary outside the block.

Use this shape, replacing the placeholders and adding only as many short paragraphs as the changes require:

```markdown
<Concise summary of evaluation-affecting changes.>

<Optional compatibility or additional impact paragraph.>

# Versions
• GitHub Copilot CLI <version>
• Claude Code <version>
• Microsoft.Dynamics.BusinessCentral.Development.Tools <version>
```
