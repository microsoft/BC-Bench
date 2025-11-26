from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from bcbench.config import get_config

_config = get_config()

__all__ = ["DatasetEntry", "TestEntry"]


class TestEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    codeunitID: int
    functionName: Annotated[set[str], Field(min_length=1)]


class DatasetEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    repo: str = Field(default="microsoftInternal/NAV", pattern=r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+$")
    instance_id: str = Field(pattern=_config.file_patterns.instance_pattern)
    base_commit: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    created_at: Annotated[str, Field(min_length=1)]
    environment_setup_version: str = Field(pattern=r"^[0-9]{2}\.[0-9]{1}$")
    project_paths: Annotated[list[str], Field(min_length=2)]
    fail_to_pass: Annotated[list[TestEntry], Field(alias="FAIL_TO_PASS", min_length=1)]
    pass_to_pass: Annotated[list[TestEntry], Field(alias="PASS_TO_PASS")] = []
    test_patch: Annotated[str, Field(min_length=1)]
    patch: Annotated[str, Field(min_length=1)]

    @property
    def problem_statement_dir(self) -> Path:
        return _config.paths.problem_statement_dir / self.instance_id

    def save_to_file(self, filepath: Path | str) -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            # For JSONL format, always write compact JSON without indentation
            json.dump(self.model_dump(by_alias=True, mode="json"), handle, ensure_ascii=False)
            handle.write("\n")

    def get_task(self, transform_image_paths: bool = False) -> str:
        """Get the task description.

        problem_statment and hints_text stored in the README.md file under the problem statement directory.

        Args:
            transform_image_paths: Whether to transform relative image paths to include the problem statement directory. Needed when passing to Agents.
        """
        readme_path = self.problem_statement_dir / _config.file_patterns.problem_statement_readme

        content: str = readme_path.read_text(encoding="utf-8")

        if not transform_image_paths:
            return content

        # Transform relative image paths: ![alt text](./diagram.png) -> ![alt text](problem/diagram.png)
        dest_dir = _config.file_patterns.problem_statement_dest_dir
        return re.sub(r"!\[([^\]]*)\]\(\./([^)]+)\)", rf"![\1]({dest_dir}/\2)", content)

    def extract_project_name(self) -> str:
        """Extract the project name from the first project path.

        Examples:
            App\\Apps\\W1\\Sustainability\\app -> Sustainability
            App\\Layers\\W1\\BaseApp -> BaseApp
            App\\Apps\\W1\\Shopify\\test -> Shopify

        Returns:
            The extracted project name, or empty string if no project paths.
        """
        if not self.project_paths:
            return ""

        # Take the first project path
        path = self.project_paths[0]

        # Split by backslash or forward slash
        parts = path.replace("\\", "/").split("/")

        # Look for the meaningful project name
        # Pattern: App\Apps\W1\<ProjectName>\app or App\Layers\W1\<ProjectName>
        if len(parts) >= 4:
            # For paths like App\Apps\W1\Sustainability\app, return "Sustainability"
            # For paths like App\Layers\W1\BaseApp, return "BaseApp"
            return parts[-2] if parts[-1] in ("app", "test") else parts[-1]

        # Fallback to the last meaningful part
        return parts[-1] if parts else ""
