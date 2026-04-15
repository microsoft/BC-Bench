from pathlib import Path
from unittest.mock import patch

from tests.conftest import create_dataset_entry, create_problem_statement_dir


class TestGetTask:
    def test_returns_readme_content(self, tmp_path: Path):
        content = "# Problem Statement\n\nThis is the task description."
        problem_dir = create_problem_statement_dir(tmp_path, content)
        entry = create_dataset_entry()

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
            result = entry.get_task()

        assert result == content
