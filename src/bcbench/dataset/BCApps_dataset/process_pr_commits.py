#!/usr/bin/env python3
"""
Process PR JSON file and create one dataset entry per commit

Usage:
    python process_pr_commits.py <pr_number>
    python process_pr_commits.py 5495
"""

import json
import subprocess
import sys
import os


def run_gh_command(command: str) -> str:
    """Execute GitHub CLI command and return output"""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error: {e.stderr}")
        sys.exit(1)


def get_commits_for_pr(pr_number: int) -> list:
    """Fetch all commits for a PR, sorted by date"""
    print(f"Fetching commits for PR #{pr_number}...")
    
    repo = "microsoft/BCApps"
    command = f"gh api repos/{repo}/pulls/{pr_number}/commits --paginate"
    
    output = run_gh_command(command)
    commits = json.loads(output)
    
    # Extract commit SHAs and dates
    commit_list = []
    for commit in commits:
        commit_list.append({
            "sha": commit["sha"],
            "date": commit["commit"]["author"]["date"]
        })
    
    # Sort by date
    commit_list.sort(key=lambda x: x["date"])
    
    print(f"Found {len(commit_list)} commits")
    return commit_list


def process_pr_file(pr_number: int):
    """Process PR JSON file and create one entry per commit"""
    
    pr_file = f"pr-{pr_number}.json"
    diff_file = f"pr-{pr_number}.diff"
        # Output file (temporary, will be overwritten by process_comments.py)
    output_file = f"pr-{pr_number}-dataset-temp.json"
    
    print(f"\n{'='*60}")
    print(f"Processing PR #{pr_number}")
    print(f"{'='*60}\n")
    
    # 1. Read PR JSON file
    print(f"Reading: {pr_file}")
    if not os.path.exists(pr_file):
        print(f"Error: File not found: {pr_file}")
        sys.exit(1)
    
    with open(pr_file, 'r', encoding='utf-8') as f:
        pr_data = json.load(f)
    
    # 2. Read diff file
    print(f"Reading: {diff_file}")
    if not os.path.exists(diff_file):
        print(f"Error: File not found: {diff_file}")
        sys.exit(1)
    
    with open(diff_file, 'r', encoding='utf-8') as f:
        diff_content = f.read()
    
    # 3. Get all commits
    commits = get_commits_for_pr(pr_number)
    
    # 4. Create one entry per commit
    print(f"\n Creating dataset entries...")
    
    dataset = []
    for commit in commits:
        entry = {
            "name": pr_data["title"],                    # PR title
            "diff": diff_content,                        # Same diff for all
            "pr_id": pr_data["number"],                  # PR number
            "body": pr_data.get("body", ""),            # PR description
            "commit_id": commit["sha"],                  # Single commit SHA
            "target_comments": []                        # Will be filled later
        }
        dataset.append(entry)
    
    # 5. Save dataset
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(dataset, f, indent=4, ensure_ascii=False)
    
    print(f"Saved to: {output_file}")
    
    # 6. Print summary
    print(f"\n{'='*60}")
    print(f"Summary")
    print(f"{'='*60}")
    print(f"  Title: {pr_data['title']}")
    print(f"  PR ID: {pr_data['number']}")
    print(f"  Body length: {len(pr_data.get('body', ''))} characters")
    print(f"  Diff length: {len(diff_content)} characters")
    print(f"  Total entries created: {len(dataset)}")
    print(f"\n  Commit IDs (chronological):")
    for i, commit in enumerate(commits, 1):
        print(f"    {i}. {commit['sha'][:8]}... ({commit['date']})")
    print(f"\nDataset ready with {len(dataset)} entries (one per commit)")


def main():
    """Main entry point"""
    
    if len(sys.argv) < 2:
        print("Usage: python process_pr_commits.py <pr_number>")
        print("Example: python process_pr_commits.py 5495")
        sys.exit(1)
    
    try:
        pr_number = int(sys.argv[1])
    except ValueError:
        print(f" Invalid PR number: {sys.argv[1]}")
        sys.exit(1)
    
    process_pr_file(pr_number)


if __name__ == "__main__":
    main()
