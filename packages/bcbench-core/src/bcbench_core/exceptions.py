from bcbench_core.types import AgentExecution


class CoreError(Exception):
    pass


class AgentError(CoreError):
    pass


class AgentTimeoutError(CoreError):
    def __init__(self, message: str, execution: AgentExecution) -> None:
        self.execution = execution
        super().__init__(message)


class PatchApplicationError(CoreError):
    def __init__(self, patch_name: str, stderr: str = "") -> None:
        self.patch_name = patch_name
        self.stderr = stderr
        super().__init__(f"Failed to apply {patch_name}" + (f": {stderr}" if stderr else ""))


class EmptyDiffError(CoreError):
    pass


def _extract_compiler_errors(output: str, max_lines: int = 30) -> str:
    if not output:
        return ""
    lines = output.splitlines()
    error_lines = [line for line in lines if ": error " in line or ": warning " in line]
    return "\n".join(error_lines[:max_lines] if error_lines else lines[-max_lines:])


def _extract_test_errors(output: str, max_lines: int = 20) -> str:
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
    filtered = [line for line in output.splitlines() if not any(skip in line for skip in skip_patterns)]
    return "\n".join(filtered[:max_lines] if filtered else output.splitlines()[-max_lines:])


class BuildError(CoreError):
    def __init__(self, project_path: str, output: str = "") -> None:
        self.project_path = project_path
        self.output = output
        self.errors = _extract_compiler_errors(output)
        super().__init__(f"Build or publish failed for {project_path}:\n{self.errors}")


class BuildTimeoutExpired(CoreError):
    def __init__(self, project_path: str, timeout: int) -> None:
        self.project_path = project_path
        self.timeout = timeout
        super().__init__(f"Build and publish timed out for {project_path} after {timeout} seconds")


class TestExecutionError(CoreError):
    def __init__(self, expectation: str, stderr: str = "", stdout: str = "") -> None:
        self.expectation = expectation
        self.stderr = stderr
        self.stdout = stdout
        self.errors = _extract_test_errors(stdout)
        message = f"Test result did not meet expectation (expected: {expectation})"
        if self.errors:
            message += f"\n{self.errors}"
        super().__init__(message)


class TestExecutionTimeoutExpired(CoreError):
    def __init__(self, tests: str, timeout: int) -> None:
        self.tests = tests
        self.timeout = timeout
        super().__init__(f"Test execution timed out (tests: {tests}) after {timeout} seconds")
