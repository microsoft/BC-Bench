#!/usr/bin/env python3
"""
Convert diff file to JSON-compatible single line format

Usage:
    python convert_diff.py <pr_number>
    python convert_diff.py 5495
"""

import json
import sys
import os


def convert_diff_to_json_string(diff_file: str) -> str:
    """Read diff file and convert to JSON-compatible escaped string"""
    
    if not os.path.exists(diff_file):
        print(f"Error: File not found: {diff_file}")
        sys.exit(1)
    
    # Read the diff content
    with open(diff_file, 'r', encoding='utf-8') as f:
        diff_content = f.read()
    
    # Convert to JSON string (automatically escapes newlines and special chars)
    json_string = json.dumps(diff_content)
    
    return json_string


def main():
    """Main entry point"""
    
    if len(sys.argv) < 2:
        print("Usage: python convert_diff.py <pr_number>")
        print("Example: python convert_diff.py 5495")
        sys.exit(1)
    
    try:
        pr_number = int(sys.argv[1])
    except ValueError:
        print(f"Invalid PR number: {sys.argv[1]}")
        sys.exit(1)
    
    diff_file = f"pr-{pr_number}.diff"
    output_file = f"pr-{pr_number}-diff.json"
    
    # Convert diff to JSON string
    json_string = convert_diff_to_json_string(diff_file)
    
    # Create JSON object with diff
    result = {
        "pr_id": pr_number,
        "diff": json.loads(json_string)  # Load back to get the actual string
    }
    
if __name__ == "__main__":
    main()
