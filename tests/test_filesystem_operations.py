import stat

from bcbench.operations import clear_directory


def test_clear_directory_removes_contents_and_preserves_directory(tmp_path):
    nested_directory = tmp_path / "nested"
    nested_directory.mkdir()
    (nested_directory / "nested.txt").write_text("nested", encoding="utf-8")
    read_only_file = tmp_path / "read-only.txt"
    read_only_file.write_text("content", encoding="utf-8")
    read_only_file.chmod(stat.S_IREAD)

    clear_directory(tmp_path)

    assert tmp_path.is_dir()
    assert list(tmp_path.iterdir()) == []


def test_clear_directory_creates_missing_directory(tmp_path):
    missing_directory = tmp_path / "missing"

    clear_directory(missing_directory)

    assert missing_directory.is_dir()
