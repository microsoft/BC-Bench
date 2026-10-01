class CoreError(Exception):
    """Base exception for benchmark framework operations."""


class DatasetError(CoreError):
    """Base exception for dataset operations."""


class EntryNotFoundError(DatasetError):
    def __init__(self, entry_id: str) -> None:
        self.entry_id = entry_id
        super().__init__(f"Entry with instance_id '{entry_id}' not found in dataset")


class GitOperationError(CoreError):
    """Base exception for workspace Git operations."""


class PatchApplicationError(GitOperationError):
    def __init__(self, patch_name: str, stderr: str = "") -> None:
        self.patch_name = patch_name
        self.stderr = stderr
        message = f"Failed to apply {patch_name}"
        if stderr:
            message += f": {stderr}"
        super().__init__(message)


class EmptyDiffError(GitOperationError):
    def __init__(self) -> None:
        super().__init__("Generated diff is empty. Agent did not make any changes.")
