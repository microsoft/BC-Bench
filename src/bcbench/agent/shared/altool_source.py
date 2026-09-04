import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from bcbench.logger import get_logger

logger = get_logger(__name__)

_SCOPE_ONPREM = re.compile(
    rb"^(?P<indent>[ \t]*)Scope[ \t]*=[ \t]*OnPrem;[ \t]*(?P<newline>\r?\n|$)",
    re.IGNORECASE | re.MULTILINE,
)
_MARKER_PREFIX = b"// BC-Bench AL tool compatibility: hidden Scope = OnPrem"


@dataclass(frozen=True)
class _ScopeRewrite:
    path: Path
    marker: bytes
    original: bytes


@dataclass
class AlToolSourceCompatibility:
    repo_path: Path
    original_head: str | None = None
    rewrites: tuple[_ScopeRewrite, ...] = ()
    restored: bool = False

    def restore(self) -> None:
        if self.restored or not self.rewrites:
            self.restored = True
            return

        for rewrite in reversed(self.rewrites):
            if not rewrite.path.is_file():
                logger.warning(f"AL tool compatibility source was deleted or moved by the agent: {rewrite.path}")
                continue

            content = rewrite.path.read_bytes()
            marker_count = content.count(rewrite.marker)
            if marker_count == 0:
                logger.warning(f"AL tool compatibility marker was changed by the agent: {rewrite.path}")
                continue
            if marker_count > 1:
                logger.warning(f"AL tool compatibility marker was duplicated by the agent: {rewrite.path}")
            rewrite.path.write_bytes(content.replace(rewrite.marker, rewrite.original, 1))

        if self.original_head is None:
            raise RuntimeError("Original Git HEAD is unavailable for AL tool source restoration")

        subprocess.run(
            ["git", "reset", "--mixed", self.original_head],
            cwd=self.repo_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )
        self.restored = True
        logger.info(f"Restored {len(self.rewrites)} temporary Scope = OnPrem declaration(s)")


def prepare_altool_source_compatibility(
    repo_path: Path,
    project_paths: list[str],
    *,
    enabled: bool,
) -> AlToolSourceCompatibility:
    state = AlToolSourceCompatibility(repo_path=repo_path)
    if not enabled:
        return state

    original_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    ).stdout.strip()

    rewrites: list[_ScopeRewrite] = []
    changed_paths: set[Path] = set()
    try:
        for project_path in dict.fromkeys(project_paths):
            project_root = Path(project_path)
            if not project_root.is_absolute():
                project_root = repo_path / project_root
            if not project_root.is_dir():
                continue

            for path in project_root.rglob("*.al"):
                if not path.name.casefold().endswith(".table.al") or _is_under_symlink(path, project_root):
                    continue

                content = path.read_bytes()
                updated = _hide_scope_onprem(path, content, rewrites)
                if updated != content:
                    path.write_bytes(updated)
                    changed_paths.add(path)

        if not rewrites:
            return state

        relative_paths = [str(path.relative_to(repo_path)) for path in sorted(changed_paths)]
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=bcbench",
                "-c",
                "user.email=bcbench@noreply",
                "commit",
                "--no-verify",
                "--only",
                "-m",
                "Prepare source for public AL tooling",
                "--",
                *relative_paths,
            ],
            cwd=repo_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )
    except Exception:
        for rewrite in reversed(rewrites):
            content = rewrite.path.read_bytes()
            if rewrite.marker in content:
                rewrite.path.write_bytes(content.replace(rewrite.marker, rewrite.original, 1))
        reset = subprocess.run(
            ["git", "reset", "--mixed", original_head],
            cwd=repo_path,
            stdout=subprocess.DEVNULL,
            encoding="utf-8",
            text=True,
            stderr=subprocess.PIPE,
            check=False,
        )
        if reset.returncode:
            logger.warning(f"Failed to reset temporary AL tool compatibility commit: {reset.stderr}")
        raise

    logger.info(f"Temporarily hid {len(rewrites)} Scope = OnPrem declaration(s) from public AL tooling")
    return AlToolSourceCompatibility(repo_path=repo_path, original_head=original_head, rewrites=tuple(rewrites))


def _is_under_symlink(path: Path, root: Path) -> bool:
    current = path
    while current != root and current != current.parent:
        if current.is_symlink():
            return True
        current = current.parent
    return False


def _hide_scope_onprem(path: Path, content: bytes, rewrites: list[_ScopeRewrite]) -> bytes:
    if _MARKER_PREFIX in content:
        raise RuntimeError(f"Stale AL tool compatibility marker found in {path}")

    def hide_scope(match: re.Match[bytes]) -> bytes:
        marker = match.group("indent") + _MARKER_PREFIX + f" {len(rewrites)}".encode() + match.group("newline")
        rewrites.append(_ScopeRewrite(path=path, marker=marker, original=match.group(0)))
        return marker

    return _SCOPE_ONPREM.sub(hide_scope, content)
