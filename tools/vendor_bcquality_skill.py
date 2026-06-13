"""Vendor the BCQuality composed-review skill framework into the BC-Bench skill folder.

Copies the meta-skill contracts, the AL review super-skill, its five in-scope leaf
skills (performance, privacy, security, style, upgrade), and the matching knowledge
files (plus .good.al / .bad.al samples) into the al-code-review skill directory, then
regenerates knowledge-index.json over the vendored corpus.

Source: a local clone of github.com/microsoft/BCQuality (default: %TEMP%/BCQuality).
Target: src/bcbench/agent/shared/instructions/microsoft-BCApps/skills/al-code-review/
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

DOMAINS = ["performance", "privacy", "security", "style", "upgrade"]
LEAVES = [f"al-{d}-review.md" for d in DOMAINS]

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = (
    REPO_ROOT
    / "src/bcbench/agent/shared/instructions/microsoft-BCApps/skills/al-code-review"
)


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.index("\n---", 3)
    raw = text[3:end].strip()
    body = text[end + 4 :]
    fm: dict[str, object] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            fm[key] = [v.strip() for v in inner.split(",")] if inner else []
        else:
            fm[key] = value
    return fm, body


def _title(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _description(body: str) -> str:
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower() == "## description":
            for follow in lines[i + 1 :]:
                if follow.strip():
                    sentence = re.split(r"(?<=[.!?])\s", follow.strip())[0]
                    return sentence.strip()
            break
    return ""


def vendor(source: Path) -> None:
    if not source.exists():
        sys.exit(f"BCQuality clone not found at {source}")

    if TARGET.exists():
        # Preserve the hand-authored Copilot entry point if present.
        skill_md = TARGET / "SKILL.md"
        backup = skill_md.read_text(encoding="utf-8") if skill_md.exists() else None
        shutil.rmtree(TARGET)
        TARGET.mkdir(parents=True)
        if backup is not None:
            skill_md.write_text(backup, encoding="utf-8")
    else:
        TARGET.mkdir(parents=True)

    # 1. Meta-skill contracts.
    contracts_dir = TARGET / "skills"
    contracts_dir.mkdir(exist_ok=True)
    for name in ("read.md", "do.md"):
        shutil.copy2(source / "skills" / name, contracts_dir / name)

    # 2. Super-skill + leaves (drop the UI leaf).
    review_dir = TARGET / "microsoft/skills/review"
    review_dir.mkdir(parents=True, exist_ok=True)
    super_src = (source / "microsoft/skills/review/al-code-review.md").read_text(
        encoding="utf-8"
    )
    super_src = super_src.replace(
        "  - microsoft/skills/review/al-ui-review.md\n", ""
    )
    super_src = super_src.replace(
        "(performance, security, privacy, upgrade, style, UI)",
        "(performance, security, privacy, upgrade, style)",
    )
    super_src = super_src.replace(
        "- `microsoft/skills/review/al-ui-review.md`\n", ""
    )
    (review_dir / "al-code-review.md").write_text(super_src, encoding="utf-8")
    for leaf in LEAVES:
        shutil.copy2(source / "microsoft/skills/review" / leaf, review_dir / leaf)

    # 3. Knowledge files (md + AL samples) for the in-scope domains.
    index: list[dict[str, object]] = []
    for domain in DOMAINS:
        src_dir = source / "microsoft/knowledge" / domain
        dst_dir = TARGET / "microsoft/knowledge" / domain
        dst_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(src_dir.iterdir()):
            if f.suffix not in (".md", ".al"):
                continue
            shutil.copy2(f, dst_dir / f.name)
            if f.suffix == ".md":
                fm, body = _split_frontmatter(f.read_text(encoding="utf-8"))
                index.append(
                    {
                        "path": f"microsoft/knowledge/{domain}/{f.name}",
                        "layer": "microsoft",
                        "domain": fm.get("domain", domain),
                        "bc-version": fm.get("bc-version", []),
                        "technologies": fm.get("technologies", []),
                        "countries": fm.get("countries", []),
                        "application-area": fm.get("application-area", []),
                        "keywords": fm.get("keywords", []),
                        "title": _title(body),
                        "description": _description(body),
                    }
                )

    # 4. Knowledge index over the vendored corpus.
    index.sort(key=lambda e: e["path"])
    (TARGET / "knowledge-index.json").write_text(
        json.dumps({"articles": index}, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Vendored {len(index)} knowledge articles across {len(DOMAINS)} domains.")
    print(f"Target: {TARGET.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ["TEMP"]) / "BCQuality"
    vendor(src)
