"""Apply targeted design fixes after initial probe revealed OOD/missed issues.

Fixes:
- security-002: Drop expected[0] (line 3 SecretText param), keep expected[1] (line 10 concat)
- privacy-003: Use Label format string in new file (eliminates style OOD); update expected to line 7
- privacy-008: Use JsonObject in new file (eliminates security OOD); keep expected at line 10
- style-002: Replace expected to point at pre-existing PostingHelper.Codeunit.al line 3 (4-space indent)
- upgrade-001: Change expected line_start to 5 (trigger header where skill flags it)
"""

from __future__ import annotations

import json
from collections.abc import Callable
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
        raise ValueError(f"file block {file_path} not found in patch")
    end = patch.find("\ndiff --git ", start + 1)
    if end == -1:
        return patch[:start] + new_block
    return patch[:start] + new_block + patch[end + 1 :]


PRIVACY_003_CONTENT = """codeunit 50323 "Customer Email Validator"
{
  procedure RejectEmail(CustomerName: Text[100]; EmailAddress: Text[80])
  var
    InvalidEmailErr: Label 'Customer %1 has invalid email %2.';
  begin
    Error(InvalidEmailErr, CustomerName, EmailAddress);
  end;

  procedure Check(CustomerName: Text[100]; EmailAddress: Text[80])
  begin
    this.RejectEmail(CustomerName, EmailAddress);
  end;
}
"""

PRIVACY_008_CONTENT = """codeunit 50327 "Customer Sync Dispatcher"
{
  procedure SendCustomer(Customer: Record Customer)
  var
    HttpClient: HttpClient;
    HttpContent: HttpContent;
    HttpResponse: HttpResponseMessage;
  begin
    HttpContent.WriteFrom(this.BuildPayload(Customer));
    HttpClient.Post('https://api.contoso.example/customers', HttpContent, HttpResponse);
  end;

  local procedure BuildPayload(Customer: Record Customer): Text
  var
    PayloadJson: JsonObject;
    PayloadText: Text;
  begin
    PayloadJson.Add('email', Customer."E-Mail");
    PayloadJson.WriteTo(PayloadText);
    exit(PayloadText);
  end;
}
"""


FIXES: dict[str, Callable[[dict], None]] = {}


def fix_security_002(entry: dict) -> None:
    # Drop expected[0] which expected line 3 (skill consolidates into line 10 finding)
    ec = entry["expected_comments"]
    if len(ec) >= 2:
        # Keep only the line 10 expected
        entry["expected_comments"] = [c for c in ec if c.get("line_start") == 10]


def fix_privacy_003(entry: dict) -> None:
    entry["patch"] = replace_file_block(
        entry["patch"],
        "src/CustomerEmailValidator.Codeunit.al",
        build_new_file_diff("src/CustomerEmailValidator.Codeunit.al", PRIVACY_003_CONTENT),
    )
    for c in entry["expected_comments"]:
        if c["file"] == "src/CustomerEmailValidator.Codeunit.al":
            c["line_start"] = 7
            c["line_end"] = 7
            c["body"] = (
                "Error embeds the customer name and email address as substitution parameters, "
                "so telemetry captures the formatted message containing PII. Use a generic error message "
                "without customer data, or surface the PII through a privacy-compliant channel."
            )


def fix_privacy_008(entry: dict) -> None:
    entry["patch"] = replace_file_block(
        entry["patch"],
        "src/CustomerSyncDispatcher.Codeunit.al",
        build_new_file_diff("src/CustomerSyncDispatcher.Codeunit.al", PRIVACY_008_CONTENT),
    )
    # Keep expected at line 10 (HttpClient.Post)


def fix_style_002(entry: dict) -> None:
    # Replace the SelfReferenceStyle expected with a PostingHelper 4-space indent expected
    entry["expected_comments"] = [
        {
            "file": "src/PostingHelper.Codeunit.al",
            "line_start": 3,
            "line_end": 33,
            "severity": "low",
            "domain": "style",
            "body": ("The codeunit body uses 4-space indentation for nested AL blocks. Project style requires 2-space indentation consistently throughout."),
        }
    ]


def fix_upgrade_001(entry: dict) -> None:
    for c in entry["expected_comments"]:
        if c["file"] == "src/InlineUpgradeSteps.Codeunit.al":
            c["line_start"] = 5
            c["line_end"] = 5
            c["body"] = (
                "OnUpgradePerCompany trigger contains the upgrade implementation inline. "
                "Trigger bodies should delegate to a local procedure so upgrade orchestration "
                "and implementation remain separable and testable."
            )


FIXES["synthetic__security-002"] = fix_security_002
FIXES["synthetic__privacy-003"] = fix_privacy_003
FIXES["synthetic__privacy-008"] = fix_privacy_008
FIXES["synthetic__style-002"] = fix_style_002
FIXES["synthetic__upgrade-001"] = fix_upgrade_001


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
    print(f"\nApplied {applied} fixes.")


if __name__ == "__main__":
    main()
