"""Errors raised by bcbench-core operations."""


class GitOperationError(Exception):
    """Base class for git operation failures."""


class PatchApplicationError(GitOperationError):
    """Failed to apply a patch."""

    def __init__(self, patch_name: str, stderr: str = "") -> None:
        self.patch_name = patch_name
        self.stderr = stderr
        message = f"Failed to apply {patch_name}"
        if stderr:
            message += f": {stderr}"
        super().__init__(message)


class EmptyDiffError(GitOperationError):
    """Generated diff is empty."""

    def __init__(self) -> None:
        message = "Generated diff is empty. Agent did not make any changes."
        super().__init__(message)


def _extract_compiler_errors(output: str, max_lines: int = 30) -> str:
    """Extract AL compiler error/warning lines from build output."""
    if not output:
        return ""

    lines = output.splitlines()
    # Match lines like: path.al(line,col): error AL0185: ...
    error_lines = [line for line in lines if ": error " in line or ": warning " in line]

    if error_lines:
        return "\n".join(error_lines[:max_lines])

    # Fallback: return last N lines if no error pattern found
    return "\n".join(lines[-max_lines:])


def _extract_test_errors(output: str, max_lines: int = 20) -> str:
    """Extract test failure information from test output, filtering verbose lines."""
    if not output:
        return ""

    skip_patterns = (
        "BcContainerHelper",
        "BC.HelperFunctions",
        "Running on Windows",
        "Using Container",
        "WARNING: TaskScheduler",
        "Connecting to http://",
        "Tests failed for",
        "::group::",
        "::endgroup::",
        "::error",
        "::warning",
        "Running tests for Codeunit",
    )

    def is_relevant(line: str) -> bool:
        return not any(skip in line for skip in skip_patterns)

    lines = output.splitlines()
    filtered = list(filter(is_relevant, lines))

    if filtered:
        return "\n".join(filtered[:max_lines])

    # Fallback: return last N lines if no pattern found
    return "\n".join(lines[-max_lines:])


class BuildError(Exception):
    """Build or publish operation failures."""

    def __init__(self, project_path: str, output: str = "") -> None:
        self.project_path = project_path
        self.output = output
        self.errors = _extract_compiler_errors(output)
        message = f"Build or publish failed for {project_path}:\n{self.errors}"

        super().__init__(message)


class BuildTimeoutExpired(Exception):
    """Build and publish operation timed out."""

    def __init__(self, project_path: str, timeout: int) -> None:
        self.project_path = project_path
        self.timeout = timeout
        message = f"Build and publish timed out for {project_path} after {timeout} seconds"
        super().__init__(message)


class TestExecutionError(Exception):
    """Test execution failures."""

    def __init__(self, expectation: str, stderr: str = "", stdout: str = "") -> None:
        self.expectation = expectation
        self.stderr = stderr
        self.stdout = stdout
        self.errors = _extract_test_errors(stdout)
        message = f"Test result did not meet expectation (expected: {expectation})"
        if self.errors:
            message += f"\n{self.errors}"
        super().__init__(message)


class TestExecutionTimeoutExpired(Exception):
    """Test execution timed out."""

    def __init__(self, tests: str, timeout: int) -> None:
        self.tests = tests
        self.timeout = timeout
        message = f"Test execution timed out (tests: {tests}) after {timeout} seconds"
        super().__init__(message)
