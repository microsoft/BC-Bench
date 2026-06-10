import json
from collections import Counter
from pathlib import Path


def parse_tool_usage_from_hooks(hooks_output_path: Path) -> dict[str, int] | None:
    if not hooks_output_path.exists():
        return None

    counts: Counter[str] = Counter()
    for line in hooks_output_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            if name := entry.get("tool_name"):
                counts[name] += 1
        except (json.JSONDecodeError, AttributeError):
            continue

    return dict(counts) or None
