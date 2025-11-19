#!/usr/bin/env python3
"""
Simple PR Data Fetcher
Fetch three essential files for a GitHub Pull Request

Usage:
    python simple_fetch.py <pr_number>
    python simple_fetch.py 5495
"""

import subprocess
import sys
import os


def run_command(command: str, output_file: str = None) -> str:
    """Execute command and return output"""
    print(f"Running: {command}")
    
    try:
        if output_file:
            # Use shell redirection to save to file
            full_command = f"{command} > {output_file}"
            result = subprocess.run(
                full_command,
                shell=True,
                capture_output=True,
                text=True,
                check=True
            )
            print(f"Saved to: {output_file}")
            return f"Saved to {output_file}"
        else:
            # Execute command and return output only
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


def fetch_pr_data(pr_number: int):
    """Fetch three core data files for a PR"""
    
    repo = "microsoft/BCApps"
    
    print(f"\n{'='*60}")
    print(f"Fetching PR #{pr_number} Data")
    print(f"{'='*60}\n")
    
    # 1. Fetch PR complete information
    print("[1/3] Fetching PR info...")
    pr_info_file = f"pr-{pr_number}.json"
    run_command(
        f"gh api repos/{repo}/pulls/{pr_number} --paginate",
        pr_info_file
    )
    
    # 2. Fetch all PR comments
    print("\n[2/3] Fetching PR comments...")
    comments_file = f"pr-{pr_number}-comments.json"
    run_command(
        f"gh api repos/{repo}/pulls/{pr_number}/comments --paginate",
        comments_file
    )
    
    # 3. Fetch PR diff
    print("\n[3/3] Fetching PR diff...")
    diff_file = f"pr-{pr_number}.diff"
    run_command(
        f"gh api repos/{repo}/pulls/{pr_number} -H \"Accept: application/vnd.github.v3.diff\"",
        diff_file
    )
    
    # Summary
    print(f"\n{'='*60}")
    print(f"Successfully fetched PR #{pr_number} data!")
    print(f"{'='*60}\n")
    print("Generated files:")
    print(f"  1. {pr_info_file} - PR complete information")
    print(f"  2. {comments_file} - All PR comments")
    print(f"  3. {diff_file} - PR code diff")
    
    # Display file sizes
    print("\nFile sizes:")
    for file in [pr_info_file, comments_file, diff_file]:
        if os.path.exists(file):
            size = os.path.getsize(file)
            print(f"  {file}: {size:,} bytes")


def main():
    """Main entry point"""
    
    if len(sys.argv) < 2:
        print("Usage: python simple_fetch.py <pr_number>")
        print("Example: python simple_fetch.py 5495")
        sys.exit(1)
    
    try:
        pr_number = int(sys.argv[1])
    except ValueError:
        print(f" Invalid PR number: {sys.argv[1]}")
        sys.exit(1)
    
    fetch_pr_data(pr_number)


if __name__ == "__main__":
    main()
