"""
Get dataset entries for a specific version
Returns JSON array of instance_ids for use in GitHub Actions matrix
"""
import argparse
import json
import sys
from pathlib import Path
from dataset_entry import DatasetEntry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=str,
        default="../../dataset/bcbench_nav.jsonl",
        help="Path to dataset file"
    )
    parser.add_argument(
        "--version",
        type=str,
        required=True,
        help="Environment setup version to filter by"
    )
    args = parser.parse_args()

    dataset_path = Path(__file__).parent / args.dataset

    instance_ids = []

    with open(dataset_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
                entry = DatasetEntry.from_json(data)
                if entry.environment_setup_version == args.version:
                    instance_ids.append(entry.instance_id)
            except Exception:
                continue

    # Output as JSON array for GitHub Actions matrix
    print(json.dumps(instance_ids))


if __name__ == "__main__":
    main()
