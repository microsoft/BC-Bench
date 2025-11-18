# PR Dataset and Security Review Integration

This document explains how to use the PR dataset (`prdataset.jsonl`) with the instructions template (`instructions.md`) for AI-driven security review tasks.

## Overview

The new PR dataset integration allows you to:

1. Load PR data (name, description, diff, target comments) from `prdataset.jsonl`
2. Load security review instructions from `instructions.md`
3. Build complete prompts with placeholders replaced with actual PR data
4. Evaluate AI agents on PR security review tasks

## Data Structures

### PRDatasetEntry

Represents a single PR security review task:

```python
from bcbench.dataset import PRDatasetEntry, TargetComment

entry = PRDatasetEntry(
    name="Update EInvoiceSaaSCommunication.Codeunit.al",
    description="Update to use Text instead of SecretText",
    diff="... actual diff content ...",
    target_comments=[
        TargetComment(comment="Procedure calling Azure Key Vault should not be public.", line=114),
        TargetComment(comment="Parameter 'Certificate' should be of type 'SecretText'.", line=114),
        TargetComment(comment="Parameter 'Certificate' should be of type 'SecretText'.", line=133),
    ]
)
```

### Dataset File Format (prdataset.jsonl)

JSONL format with one JSON object per line:

```jsonl
{
    "name": "Update EInvoiceSaaSCommunication.Codeunit.al",
    "description": "Update to use Text instead of SecretText",
    "diff": "diff --git a/App/BCApps...",
    "target_comments": [
        {
            "comment": "Procedure calling Azure Key Vault should not be public.",
            "line": 114
        },
        {
            "comment": "Parameter 'Certificate' should be of type 'SecretText'.",
            "line": 114
        }
    ]
}
```

## Usage Examples

### Loading PR Dataset

```python
from bcbench.agent.pr_security_review_helper import load_pr_dataset

# Load with default path (dataset/prdataset.jsonl)
entries = load_pr_dataset()

# Or specify custom path
entries = load_pr_dataset(path="custom/path/prdataset.jsonl")

for entry in entries:
    print(f"PR: {entry.name}")
    print(f"Description: {entry.description}")
    print(f"Target comments: {len(entry.target_comments)}")
```

### Building Security Review Prompts

The instructions template uses placeholders that get replaced with PR data:

**instructions.md** (excerpt):
```markdown
# AL Security Review

[Review Rules...]

[Input]
PullRequestName:
{prname}

PullRequestDescription:
{prdescription}

PullRequestFilesContentDiff:
{diff}

[Output]
Output in the following format:
[...]
```

Building the complete prompt:

```python
from bcbench.agent.pr_security_review_helper import build_pr_security_review_prompt, load_pr_dataset

# Load PR entry
entries = load_pr_dataset()
pr_entry = entries[0]

# Build complete prompt (replaces {prname}, {prdescription}, {diff})
prompt = build_pr_security_review_prompt(pr_entry)

# Now 'prompt' contains the full instructions with PR data substituted
# Ready to send to AI agent
```

### Manual Prompt Building

If you need more control:

```python
from bcbench.agent.copilot.prompt import build_pr_review_prompt
from bcbench.operations.instruction_operations import load_instructions_template

# Load instructions template
instructions = load_instructions_template()

# Build prompt with specific entry
prompt = build_pr_review_prompt(pr_entry, instructions)
```

## Integration with Copilot Agent

The PR dataset and prompt building is designed to integrate with the GitHub Copilot CLI agent for security review evaluation:

```python
from bcbench.agent.pr_security_review_helper import load_pr_dataset, build_pr_security_review_prompt

# Load PR dataset
entries = load_pr_dataset()

for pr_entry in entries:
    # Build prompt
    prompt = build_pr_security_review_prompt(pr_entry)

    # Send to Copilot CLI for security review
    # ... evaluation logic ...

    # Evaluate against target comments
    for target in pr_entry.target_comments:
        print(f"Target: {target['comment']} (line {target['line']})")
```

## Files Structure

```
dataset/
  prdataset.jsonl         # PR dataset with diff and expected comments
  instructions.md         # Security review instructions with placeholders
  schema.json             # Schema for bcbench_nav.jsonl
  bcbench_nav.jsonl       # Existing BC benchmark dataset

src/bcbench/dataset/
  pr_dataset_entry.py     # PRDatasetEntry and TargetComment classes
  dataset_entry.py        # Existing DatasetEntry class

src/bcbench/agent/
  pr_security_review_helper.py  # Helpers for loading and building prompts
  copilot/
    prompt.py             # Updated with build_pr_review_prompt function

src/bcbench/operations/
  instruction_operations.py    # Updated with load_instructions_template
```

## Key Placeholders in instructions.md

The instructions template should include these placeholders:

- `{prname}` - Pull request name
- `{prdescription}` - Pull request description
- `{diff}` - The diff content/patch

These will be automatically replaced when building the prompt.

## Running Tests

```bash
# Run PR dataset tests
uv run pytest tests/test_pr_dataset_and_security_review.py -v

# Run specific test
uv run pytest tests/test_pr_dataset_and_security_review.py::TestBuildPRReviewPrompt -v
```
