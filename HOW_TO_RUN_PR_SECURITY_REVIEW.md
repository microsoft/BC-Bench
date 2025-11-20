# Running PR Security Review

There are several ways to run PR security review with your dataset:

## 1. Using the CLI Command (Easiest)

```powershell
cd C:\depot\BC-Bench

# View the first PR entry and its security review prompt
uv run bcbench run pr-review

# View a specific PR entry (by index)
uv run bcbench run pr-review --entry-index 1

# Save the prompt to a file
uv run bcbench run pr-review --entry-index 0 --output-file prompt.txt

# Run the agent on a specific PR
uv run bcbench run pr-review --entry-index 0 --run-agent
```

### Output
The command will:
1. Load PR from `dataset/prdataset.jsonl`
2. Load instructions from `dataset/instructions.md`
3. Replace placeholders ({prname}, {prdescription}, {diff})
4. Display the complete prompt
5. Show target comments (expected AI output)
6. (Optional) Run Copilot CLI agent to generate security review comments

## 2. Running Full Evaluations (NEW)

Evaluate the agent on **all** PR entries in the dataset using an LLM judge:

```powershell
# Run evaluations on all PRs with default settings
uv run bcbench run pr-review-evals

# Save results to a specific file
uv run bcbench run pr-review-evals --output-file results.jsonl

# Show prompts and judge responses during execution
uv run bcbench run pr-review-evals --show-prompts

# Use a different model
uv run bcbench run pr-review-evals --model=gpt-4o
```

### How it works
1. Loads all PR entries from `dataset/prdataset.jsonl`
2. Runs Copilot CLI on each entry to generate review comments
3. Uses Copilot CLI as an **LLM judge** to evaluate if the actual comments cover the expected comments
4. Writes detailed results to a JSONL file

### Judge Evaluation
The judge prompt (in `dataset/judge_prompt.md`) asks:
> "Does the actual output mention at least the key points from the expected comments?"

The judge returns:
- `passed`: `true` or `false`
- `reason`: Explanation of why it passed or failed

### Output Format
Results are saved as JSONL with each entry containing:
```json
{
  "pr_name": "PR-123",
  "pr_description": "Fix security issue...",
  "output": "The agent's generated comments...",
  "expected_output": [{"line": 10, "comment": "Expected comment"}],
  "passed": true,
  "judge_reason": "All key points about the issue were mentioned",
  "error_message": null
}
```

### Summary Statistics
After evaluation completes, you'll see:
```
EVALUATION SUMMARY (LLM Judge)
================================================================================
Total PRs evaluated: 10
Passed (covers expected comments): 7
Failed (missing expected comments): 3
Success rate: 70.0%
```

## 3. Running with Copilot CLI

After installing Copilot CLI, you can run the agent:

```powershell
# Install Copilot CLI first
npm install -g @github/copilot@latest

# Set up authentication
gh auth login

# Run the demo script to see the prompt
uv run python scripts/run_pr_security_review.py demo

# Run with Copilot CLI (if installed)
uv run python scripts/run_pr_security_review.py run --index 0
```

## 4. Programmatic Usage in Your Code

```python
from bcbench.agent.pr_security_review_helper import (
    load_pr_dataset,
    build_pr_security_review_prompt
)

# Load PR dataset
pr_entries = load_pr_dataset()

# Build prompt for first PR
pr_entry = pr_entries[0]
prompt = build_pr_security_review_prompt(pr_entry)

# Use the prompt with your AI agent
print(prompt)

# Access PR metadata
print(f"PR Name: {pr_entry.name}")
print(f"Description: {pr_entry.description}")
print(f"Target Comments: {len(pr_entry.target_comments)}")

# View expected comments
for target in pr_entry.target_comments:
    print(f"  Line {target['line']}: {target['comment']}")
```

## 5. View PR Dataset

```powershell
# See what PRs are in your dataset
uv run bcbench dataset view  # Once you implement this for PRs

# Or manually check the file
cat dataset/prdataset.jsonl
```

## File Locations

```
dataset/
  ├── prdataset.jsonl          # Your PR data with diffs and expected comments
  ├── instructions.md           # Security review instructions with placeholders
  ├── judge_prompt.md           # LLM judge evaluation prompt (NEW)
  └── bcbench_nav.jsonl         # Existing BC benchmark data

src/bcbench/
  ├── dataset/
  │   └── pr_dataset_entry.py   # PRDatasetEntry class
  ├── agent/
  │   ├── pr_security_review_helper.py  # Helpers for loading/building prompts
  │   └── copilot/
  │       └── prompt.py          # build_pr_review_prompt function
  └── commands/
      └── run.py                 # CLI commands: "pr-review" and "pr-review-evals"

evaluation_results/
  └── pr_review/
      ├── pr_review_results.jsonl  # Evaluation results with judge reasons
      └── prompt_*.txt             # Saved prompts (when using --output-file)
```

## Example Workflow

```powershell
cd C:\depot\BC-Bench

# 1. Install dependencies
uv sync --all-extras

# 2. Install Copilot CLI (required for evaluations)
npm install -g @github/copilot@latest
gh auth login

# 3. View first PR entry
uv run bcbench run pr-review --entry-index 0 --show-prompt

# 4. Run evaluation on all PRs
uv run bcbench run pr-review-evals --output-file results.jsonl

# 5. View results with judge reasons
cat results.jsonl | ConvertFrom-Json | Format-List

# 6. Check detailed output
dir evaluation_results/pr_review/
```

## Troubleshooting

**Issue: "No PR entries found in dataset!"**
- Make sure `dataset/prdataset.jsonl` exists and has content
- Check file is valid JSONL format (one JSON object per line)

**Issue: "Instructions template not found"**
- Make sure `dataset/instructions.md` exists
- Verify the file is readable

**Issue: "Judge prompt template not found"**
- Make sure `dataset/judge_prompt.md` exists
- This file is required for `pr-review-evals` command

**Issue: Copilot CLI not found**
- Install: `npm install -g @github/copilot@latest`
- Authenticate: `gh auth login`
- Verify: `copilot --version`

**Issue: "LLM judge failed, defaulting to false"**
- Check Copilot CLI is authenticated and working
- Try running a simple command: `echo "test" | copilot`
- Check the `--show-prompts` flag to see judge responses

**Issue: Placeholder not replaced**
- Check placeholders in `instructions.md` are exactly: `{prname}`, `{prdescription}`, `{diff}`
- Check PR entry has the correct field names

## Customizing the Judge Prompt

You can customize how the LLM evaluates PR reviews by editing `dataset/judge_prompt.md`:

```markdown
You are evaluating if the actual comments cover the expected comments.

Expected Comments:
{expected_comments}

Actual Comments:
{actual_comments}

Task: Does the actual output mention at least the key points from the expected comments?

Respond in the following JSON format (no additional text):
{"passed": true/false, "reason": "brief explanation of why it passed or failed"}
```

**Tips for customizing:**
- Keep the placeholders `{expected_comments}` and `{actual_comments}`
- Request JSON format for structured parsing
- Be specific about what constitutes a "pass"
- Ask for brief, actionable reasons

## Next Steps

1. ✅ Add evaluation command to evaluate agent output against target comments
2. Integrate with GitHub Actions for automated evaluation
3. Add result collection and metrics aggregation
4. Create leaderboard for PR security review tasks
5. Support additional models beyond Copilot CLI
