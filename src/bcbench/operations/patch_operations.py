import re
from dataclasses import dataclass

_DIFF_HEADER_PATTERN = re.compile(r"^diff --git ", re.MULTILINE)
_GIT_ESCAPE_BYTES = {
    "a": b"\a",
    "b": b"\b",
    "f": b"\f",
    "n": b"\n",
    "r": b"\r",
    "t": b"\t",
    "v": b"\v",
    "\\": b"\\",
    '"': b'"',
}


@dataclass(frozen=True)
class GitDiffPaths:
    source: str
    target: str


def split_git_diff_blocks(patch: str) -> tuple[str, ...]:
    starts = [match.start() for match in _DIFF_HEADER_PATTERN.finditer(patch)]
    if not starts:
        return ()
    return tuple(patch[start:end] for start, end in zip(starts, [*starts[1:], len(patch)], strict=True))


def _decode_git_quoted_path(path: str) -> str:
    encoded = bytearray()
    index = 1
    while index < len(path) - 1:
        character = path[index]
        if character != "\\":
            encoded.extend(character.encode())
            index += 1
            continue

        index += 1
        if index >= len(path) - 1:
            raise ValueError(f"Invalid Git path quoting: {path}")
        escaped = path[index]
        if escaped in _GIT_ESCAPE_BYTES:
            encoded.extend(_GIT_ESCAPE_BYTES[escaped])
            index += 1
            continue
        if escaped in "01234567":
            octal_end = index + 1
            while octal_end < min(index + 3, len(path) - 1) and path[octal_end] in "01234567":
                octal_end += 1
            encoded.append(int(path[index:octal_end], 8))
            index = octal_end
            continue
        raise ValueError(f"Invalid Git path escape: \\{escaped}")

    return encoded.decode("utf-8")


def decode_git_path(path: str) -> str:
    path_without_timestamp = path.split("\t", maxsplit=1)[0]
    if not path_without_timestamp.startswith('"'):
        return path_without_timestamp
    if not path_without_timestamp.endswith('"'):
        raise ValueError(f"Invalid Git path quoting: {path_without_timestamp}")
    return _decode_git_quoted_path(path_without_timestamp)


def extract_git_diff_paths(diff_block: str) -> GitDiffPaths | None:
    source: str | None = None
    target: str | None = None
    rename_source: str | None = None
    rename_target: str | None = None

    for line in diff_block.splitlines():
        if line.startswith("@@ "):
            break
        if line.startswith("--- "):
            source = decode_git_path(line[4:])
        elif line.startswith("+++ "):
            target = decode_git_path(line[4:])
        elif line.startswith(("rename from ", "copy from ")):
            rename_source = decode_git_path(line.split(" ", maxsplit=2)[2])
        elif line.startswith(("rename to ", "copy to ")):
            rename_target = decode_git_path(line.split(" ", maxsplit=2)[2])

    if source is not None and target is not None:
        return GitDiffPaths(source=source, target=target)
    if rename_source is not None and rename_target is not None:
        return GitDiffPaths(source=rename_source, target=rename_target)
    return None
