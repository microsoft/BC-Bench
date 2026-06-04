import json
from collections import Counter
from pathlib import Path

from bcbench.types import AgentType


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


def parse_skill_read_diagnostics_from_hooks(
    hooks_output_path: Path,
    repo_path: Path,
    agent_type: AgentType,
) -> dict[str, bool] | None:
    if not hooks_output_path.exists():
        return None

    target_dir = agent_type.get_target_dir(repo_path)
    expected_skill_path = (target_dir / "skills" / "al-code-review" / "SKILL.md").resolve()
    domain_files = ["security", "performance", "style", "accessibility", "upgrade", "privacy"]
    expected_instruction_paths = {
        domain: (target_dir / "instructions" / f"{domain}.md").resolve() for domain in domain_files
    }

    normalized_reads: set[str] = set()
    for line in hooks_output_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(entry, dict):
            continue

        path_value = entry.get("tool_path")
        if not isinstance(path_value, str) or not path_value:
            continue

        normalized_reads.add(str(Path(path_value).resolve()).lower())

    diagnostics: dict[str, bool] = {
        "skill_file_read": str(expected_skill_path).lower() in normalized_reads,
    }

    instruction_flags = {
        f"instruction_{domain}_read": str(path).lower() in normalized_reads
        for domain, path in expected_instruction_paths.items()
    }
    diagnostics.update(instruction_flags)
    diagnostics["any_domain_instruction_read"] = any(instruction_flags.values())
    diagnostics["all_domain_instructions_read"] = all(instruction_flags.values())

    return diagnostics


def parse_skill_read_diagnostics_from_session_log(
    session_log_path: Path,
    repo_path: Path,
    agent_type: AgentType,
) -> dict[str, bool] | None:
    if not session_log_path.exists():
        return None

    target_dir = agent_type.get_target_dir(repo_path)
    expected_skill_path = (target_dir / "skills" / "al-code-review" / "SKILL.md").resolve()
    domain_files = ["security", "performance", "style", "accessibility", "upgrade", "privacy"]
    expected_instruction_paths = {
        domain: (target_dir / "instructions" / f"{domain}.md").resolve() for domain in domain_files
    }

    log_text = session_log_path.read_text(encoding="utf-8", errors="replace")
    normalized_log = log_text.replace("\\", "/").lower()

    diagnostics: dict[str, bool] = {
        "skill_file_read": str(expected_skill_path).replace("\\", "/").lower() in normalized_log,
    }

    instruction_flags = {
        f"instruction_{domain}_read": str(path).replace("\\", "/").lower() in normalized_log
        for domain, path in expected_instruction_paths.items()
    }
    diagnostics.update(instruction_flags)
    diagnostics["any_domain_instruction_read"] = any(instruction_flags.values())
    diagnostics["all_domain_instructions_read"] = all(instruction_flags.values())

    return diagnostics
