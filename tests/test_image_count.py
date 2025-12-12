from pathlib import Path
from unittest.mock import patch

from bcbench.dataset.dataset_entry import IMAGE_EXTENSIONS, count_images_in_directory
from tests.conftest import create_dataset_entry, create_problem_statement_dir


class TestCountImagesInDirectory:
    def test_returns_none_for_nonexistent_directory(self, tmp_path: Path):
        nonexistent = tmp_path / "does_not_exist"
        result = count_images_in_directory(nonexistent)
        assert result is None

    def test_returns_zero_for_empty_directory(self, tmp_path: Path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = count_images_in_directory(empty_dir)
        assert result == 0

    def test_returns_zero_for_directory_with_no_images(self, tmp_path: Path):
        dir_with_files = tmp_path / "files"
        dir_with_files.mkdir()
        (dir_with_files / "README.md").write_text("# Test")
        (dir_with_files / "data.json").write_text("{}")
        result = count_images_in_directory(dir_with_files)
        assert result == 0

    def test_counts_png_files(self, tmp_path: Path):
        dir_with_images = tmp_path / "images"
        dir_with_images.mkdir()
        (dir_with_images / "image1.png").write_bytes(b"fake png")
        (dir_with_images / "image2.png").write_bytes(b"fake png")
        result = count_images_in_directory(dir_with_images)
        assert result == 2

    def test_counts_various_image_extensions(self, tmp_path: Path):
        dir_with_images = tmp_path / "images"
        dir_with_images.mkdir()
        (dir_with_images / "photo.jpg").write_bytes(b"fake jpg")
        (dir_with_images / "screenshot.jpeg").write_bytes(b"fake jpeg")
        (dir_with_images / "diagram.png").write_bytes(b"fake png")
        (dir_with_images / "animation.gif").write_bytes(b"fake gif")
        (dir_with_images / "icon.webp").write_bytes(b"fake webp")
        result = count_images_in_directory(dir_with_images)
        assert result == 5

    def test_ignores_non_image_files(self, tmp_path: Path):
        dir_with_mixed = tmp_path / "mixed"
        dir_with_mixed.mkdir()
        (dir_with_mixed / "image.png").write_bytes(b"fake png")
        (dir_with_mixed / "README.md").write_text("# Test")
        (dir_with_mixed / "data.txt").write_text("data")
        result = count_images_in_directory(dir_with_mixed)
        assert result == 1

    def test_case_insensitive_extensions(self, tmp_path: Path):
        dir_with_images = tmp_path / "images"
        dir_with_images.mkdir()
        (dir_with_images / "image1.PNG").write_bytes(b"fake png")
        (dir_with_images / "image2.Jpg").write_bytes(b"fake jpg")
        (dir_with_images / "image3.JPEG").write_bytes(b"fake jpeg")
        result = count_images_in_directory(dir_with_images)
        assert result == 3


class TestDatasetEntryCountImages:
    def test_count_images_returns_count_from_problem_statement_dir(self, tmp_path: Path):
        problem_dir = create_problem_statement_dir(tmp_path)
        (problem_dir / "screenshot.png").write_bytes(b"fake png")
        (problem_dir / "diagram.jpg").write_bytes(b"fake jpg")

        entry = create_dataset_entry()

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
            result = entry.count_images()

        assert result == 2

    def test_count_images_returns_none_for_missing_directory(self, tmp_path: Path):
        nonexistent_dir = tmp_path / "nonexistent"
        entry = create_dataset_entry()

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: nonexistent_dir)):
            result = entry.count_images()

        assert result is None

    def test_count_images_returns_zero_for_directory_with_no_images(self, tmp_path: Path):
        problem_dir = create_problem_statement_dir(tmp_path)
        entry = create_dataset_entry()

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
            result = entry.count_images()

        # problem_statement_dir has README.md by default
        assert result == 0


class TestImageExtensionsConstant:
    def test_contains_common_image_extensions(self):
        assert ".png" in IMAGE_EXTENSIONS
        assert ".jpg" in IMAGE_EXTENSIONS
        assert ".jpeg" in IMAGE_EXTENSIONS
        assert ".gif" in IMAGE_EXTENSIONS
        assert ".webp" in IMAGE_EXTENSIONS
        assert ".bmp" in IMAGE_EXTENSIONS
        assert ".svg" in IMAGE_EXTENSIONS
