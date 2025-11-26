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

    def test_transform_image_paths_false_preserves_relative_paths(self, tmp_path: Path):
        content = "# Task\n\n![diagram](./diagram.png)\n\nSome text."
        problem_dir = create_problem_statement_dir(tmp_path, content)
        entry = create_dataset_entry()

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
            result = entry.get_task(transform_image_paths=False)

        assert "![diagram](./diagram.png)" in result

    def test_transform_image_paths_true_converts_to_problem_directory(self, tmp_path: Path):
        content = "# Task\n\n![diagram](./diagram.png)\n\nSome text."
        problem_dir = create_problem_statement_dir(tmp_path, content)
        entry = create_dataset_entry()

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
            result = entry.get_task(transform_image_paths=True)

        assert "![diagram](problem/diagram.png)" in result
        assert "./diagram.png" not in result

    def test_transform_image_paths_handles_multiple_images(self, tmp_path: Path):
        content = "# Task\n\n![first](./img1.png)\n\nText\n\n![second](./img2.png)"
        problem_dir = create_problem_statement_dir(tmp_path, content)
        entry = create_dataset_entry()

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
            result = entry.get_task(transform_image_paths=True)

        assert "![first](problem/img1.png)" in result
        assert "![second](problem/img2.png)" in result

    def test_transform_image_paths_preserves_alt_text(self, tmp_path: Path):
        content = "![Complex Alt Text with spaces](./image.png)"
        problem_dir = create_problem_statement_dir(tmp_path, content)
        entry = create_dataset_entry()

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
            result = entry.get_task(transform_image_paths=True)

        assert "![Complex Alt Text with spaces](problem/image.png)" in result

    def test_transform_image_paths_handles_empty_alt_text(self, tmp_path: Path):
        content = "![](./image.png)"
        problem_dir = create_problem_statement_dir(tmp_path, content)
        entry = create_dataset_entry()

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
            result = entry.get_task(transform_image_paths=True)

        assert "![](problem/image.png)" in result

    def test_transform_image_paths_handles_nested_paths(self, tmp_path: Path):
        content = "![diagram](./images/subdir/diagram.png)"
        problem_dir = create_problem_statement_dir(tmp_path, content)
        entry = create_dataset_entry()

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
            result = entry.get_task(transform_image_paths=True)

        assert "![diagram](problem/images/subdir/diagram.png)" in result

    def test_transform_image_paths_ignores_absolute_urls(self, tmp_path: Path):
        content = "![external](https://example.com/image.png)"
        problem_dir = create_problem_statement_dir(tmp_path, content)
        entry = create_dataset_entry()

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
            result = entry.get_task(transform_image_paths=True)

        assert "![external](https://example.com/image.png)" in result

    def test_transform_image_paths_ignores_non_relative_paths(self, tmp_path: Path):
        content = "![other](images/diagram.png)"
        problem_dir = create_problem_statement_dir(tmp_path, content)
        entry = create_dataset_entry()

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
            result = entry.get_task(transform_image_paths=True)

        # Paths without ./ prefix should not be transformed
        assert "![other](images/diagram.png)" in result

    def test_transform_image_paths_handles_mixed_content(self, tmp_path: Path):
        content = """# Problem

![local](./diagram.png)

Some text with [a link](./doc.md) that is not an image.

![external](https://example.com/img.png)

![another local](./screenshot.jpg)
"""
        problem_dir = create_problem_statement_dir(tmp_path, content)
        entry = create_dataset_entry()

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
            result = entry.get_task(transform_image_paths=True)

        assert "![local](problem/diagram.png)" in result
        assert "![another local](problem/screenshot.jpg)" in result
        assert "![external](https://example.com/img.png)" in result
        # Regular links should be preserved (not images)
        assert "[a link](./doc.md)" in result
