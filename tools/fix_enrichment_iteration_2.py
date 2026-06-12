"""Iteration 2 fixes for the 2 remaining probe failures.

privacy-003: Switch to StrSubstNo-Label-then-Error pattern. The previous Label-only design
removed the PII pre-baking that the skill reliably catches. The new design uses a Label
(to avoid the AA0216 style finding from a hardcoded format string) but still pre-bakes
PII into a Text variable via StrSubstNo before Error, which is the privacy violation.

style-002: Keep both expected (PostingHelper 4-space + SelfReferenceStyle missing this.).
Both are real in-domain style violations. Skill surfaces either on any given run.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET = REPO_ROOT / "dataset" / "codereview.jsonl"


def build_new_file_diff(file_path: str, content: str) -> str:
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    n = len(lines)
    out = [
        f"diff --git a/{file_path} b/{file_path}",
        "new file mode 100644",
        "--- /dev/null",
        f"+++ b/{file_path}",
        f"@@ -0,0 +1,{n} @@",
    ]
    out.extend(f"+{ln}" for ln in lines)
    return "\n".join(out) + "\n"


def replace_file_block(patch: str, file_path: str, new_block: str) -> str:
    marker = f"diff --git a/{file_path} b/{file_path}\n"
    start = patch.find(marker)
    if start == -1:
        raise ValueError(f"file block {file_path} not found")
    end = patch.find("\ndiff --git ", start + 1)
    if end == -1:
        return patch[:start] + new_block
    return patch[:start] + new_block + patch[end + 1 :]


PRIVACY_003_CONTENT = """codeunit 50323 "Customer Email Validator"
{
  procedure RejectEmail(CustomerName: Text[100]; EmailAddress: Text[80])
  var
    InvalidEmailErr: Label 'Customer %1 has invalid email %2.';
    ErrorMessage: Text;
  begin
    ErrorMessage := StrSubstNo(InvalidEmailErr, CustomerName, EmailAddress);
    Error(ErrorMessage);
  end;

  procedure Check(CustomerName: Text[100]; EmailAddress: Text[80])
  begin
    this.RejectEmail(CustomerName, EmailAddress);
  end;
}
"""


def fix_privacy_003(entry: dict) -> None:
    entry["patch"] = replace_file_block(
        entry["patch"],
        "src/CustomerEmailValidator.Codeunit.al",
        build_new_file_diff("src/CustomerEmailValidator.Codeunit.al", PRIVACY_003_CONTENT),
    )
    entry["expected_comments"] = [
        {
            "file": "src/CustomerEmailValidator.Codeunit.al",
            "line_start": 8,
            "line_end": 9,
            "severity": "high",
            "domain": "privacy",
            "body": (
                "PII (customer name and email) is pre-built into a Text variable via StrSubstNo "
                "and then passed to Error. The resulting message is logged to telemetry with the "
                "PII inlined. Avoid pre-baking customer data into error messages; surface generic "
                "errors and report PII through a privacy-compliant channel."
            ),
        }
    ]


def fix_style_002(entry: dict) -> None:
    entry["expected_comments"] = [
        {
            "file": "src/PostingHelper.Codeunit.al",
            "line_start": 3,
            "line_end": 33,
            "severity": "low",
            "domain": "style",
            "body": ("The codeunit body uses 4-space indentation for nested AL blocks. Project style requires 2-space indentation consistently throughout."),
        },
        {
            "file": "src/SelfReferenceStyle.Codeunit.al",
            "line_start": 5,
            "line_end": 5,
            "severity": "low",
            "domain": "style",
            "body": ("Self-references inside codeunits should be qualified with this. Use this.IsCustomerNoFilled(CustomerNo) for clarity."),
        },
    ]


FIXES = {
    "synthetic__privacy-003": fix_privacy_003,
    "synthetic__style-002": fix_style_002,
}


def main() -> None:
    out_lines: list[str] = []
    applied = 0
    with DATASET.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip():
                out_lines.append(raw)
                continue
            entry = json.loads(line)
            iid = entry["instance_id"]
            if iid in FIXES:
                FIXES[iid](entry)
                applied += 1
                print(f"  [+] fixed {iid}")
            out_lines.append(json.dumps(entry, ensure_ascii=False) + "\n")

    DATASET.write_text("".join(out_lines), encoding="utf-8")
    print(f"\nApplied {applied} iteration-2 fixes.")


if __name__ == "__main__":
    main()
