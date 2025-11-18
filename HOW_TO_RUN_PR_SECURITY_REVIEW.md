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
```

### Output
The command will:
1. Load PR from `dataset/prdataset.jsonl`
2. Load instructions from `dataset/instructions.md`
3. Replace placeholders ({prname}, {prdescription}, {diff})
4. Display the complete prompt
5. Show target comments (expected AI output)

## 2. Running with Copilot CLI

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

## 3. Programmatic Usage in Your Code

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

## 4. View PR Dataset

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
  └── bcbench_nav.jsonl         # Existing BC benchmark data

src/bcbench/
  ├── dataset/
  │   └── pr_dataset_entry.py   # PRDatasetEntry class
  ├── agent/
  │   ├── pr_security_review_helper.py  # Helpers for loading/building prompts
  │   └── copilot/
  │       └── prompt.py          # build_pr_review_prompt function
  └── commands/
      └── run.py                 # CLI command "pr-review"
```

## Example Workflow

```powershell
cd C:\depot\BC-Bench

# 1. Install dependencies
uv sync --all-extras

# 2. View first PR entry
uv run bcbench run pr-review --entry-index 0

# 3. Save prompt to file for inspection
uv run bcbench run pr-review --entry-index 0 --output-file pr_prompt.txt

# 4. Install Copilot CLI
npm install -g @github/copilot

# 5. Run with Copilot (requires GH_TOKEN)
$env:GH_TOKEN = "your_github_token"
uv run bcbench run pr-review --entry-index 0

# 6. Check results
dir evaluation_results/
```

## Troubleshooting

**Issue: "No PR entries found in dataset!"**
- Make sure `dataset/prdataset.jsonl` exists and has content
- Check file is valid JSONL format (one JSON object per line)

**Issue: "Instructions template not found"**
- Make sure `dataset/instructions.md` exists
- Verify the file is readable

**Issue: Copilot CLI not found**
- Install: `npm install -g @github/copilot`
- Authenticate: `gh auth login`

**Issue: Placeholder not replaced**
- Check placeholders in `instructions.md` are exactly: `{prname}`, `{prdescription}`, `{diff}`
- Check PR entry has the correct field names

## Next Steps

1. Add evaluation command to evaluate agent output against target comments
2. Integrate with GitHub Actions for automated evaluation
3. Add result collection and metrics
4. Create leaderboard for PR security review tasks
