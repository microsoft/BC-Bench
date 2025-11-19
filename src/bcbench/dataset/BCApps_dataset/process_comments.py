"""
Process PR comments and map them to commits in the dataset.
Matches comments to dataset entries based on commit_id.
"""

import json
import sys
from pathlib import Path


def extract_comment_fields(comment):
    """
    Extract required fields from a GitHub review comment.
    
    Args:
        comment: Raw comment object from GitHub API
        
    Returns:
        Dictionary with filtered fields, or None if commit_id is missing
    """
    # GitHub API may not always have commit_id (e.g., for outdated comments)
    commit_id = comment.get('commit_id', comment.get('original_commit_id', ''))
    
    if not commit_id:
        return None
    
    return {
        'diff_hunk': comment.get('diff_hunk', ''),
        'path': comment.get('path', ''),
        'commit_id': commit_id,
        'author': comment.get('user', {}).get('login', ''),
        'body': comment.get('body', ''),
        'line': comment.get('line'),
        'original_line': comment.get('original_line')
    }


def map_comments_to_dataset(dataset_file, comments_file, output_file):
    """
    Map comments to dataset entries based on commit_id.
    
    Args:
        dataset_file: Path to pr-{number}-dataset.json
        comments_file: Path to pr-{number}-comments.json
        output_file: Path to output file with comments mapped
    """
    # Load dataset
    with open(dataset_file, 'r', encoding='utf-8') as f:
        dataset = json.load(f)
    
    # Load comments
    with open(comments_file, 'r', encoding='utf-8') as f:
        raw_comments = json.load(f)
    
    # Extract and filter comment fields
    comments = []
    for comment in raw_comments:
        extracted = extract_comment_fields(comment)
        if extracted:
            comments.append(extracted)
    
    print(f"Loaded {len(dataset)} dataset entries")
    print(f"Loaded {len(comments)} valid comments (with commit_id)")
    
    # Create mapping: commit_id -> list of comments
    comment_map = {}
    for comment in comments:
        commit_id = comment['commit_id']
        if commit_id not in comment_map:
            comment_map[commit_id] = []
        comment_map[commit_id].append(comment)
    
    # Map comments to dataset entries
    matched_count = 0
    for entry in dataset:
        entry_commit_id = entry['commit_id']
        if entry_commit_id in comment_map:
            entry['target_comments'] = comment_map[entry_commit_id]
            matched_count += len(comment_map[entry_commit_id])
            print(f"  Commit {entry_commit_id[:8]}: {len(comment_map[entry_commit_id])} comments")
        else:
            entry['target_comments'] = []
    
    # Save result
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(dataset, f, indent=4, ensure_ascii=False)
    
    print(f"\nSummary:")
    print(f"  Total comments matched: {matched_count}")
    print(f"  Commits with comments: {len([e for e in dataset if e['target_comments']])}")
    print(f"  Commits without comments: {len([e for e in dataset if not e['target_comments']])}")
    print(f"  Output saved to: {output_file}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python process_comments.py <pr_number>")
        print("Example: python process_comments.py 5495")
        sys.exit(1)
    
    pr_number = sys.argv[1]
    
    # Define file paths
    dataset_file = f"pr-{pr_number}-dataset-temp.json"
    comments_file = f"pr-{pr_number}-comments.json"
    output_file = f"pr-{pr_number}-dataset.json"
    
    # Check if files exist
    if not Path(dataset_file).exists():
        print(f"Error: {dataset_file} not found")
        print(f"Please run process_pr_commits.py first to generate the dataset")
        sys.exit(1)
    
    if not Path(comments_file).exists():
        print(f"Error: {comments_file} not found")
        print(f"Please run simple_fetch.py first to fetch comments")
        sys.exit(1)
    
    # Process
    map_comments_to_dataset(dataset_file, comments_file, output_file)
