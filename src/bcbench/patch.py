from unidiff import PatchSet


def extract_file_paths_from_patch(patch: str) -> list[str]:
    if not patch:
        return []
    return [patched_file.path for patched_file in PatchSet(patch) if patched_file.path]
