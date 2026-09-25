import stat

from bcbench_core.filesystem import clear_directory, prepare_run_dir, remove_tree


def test_remove_tree_removes_read_only_files(tmp_path):
    tree = tmp_path / "tree"
    (tree / "nested").mkdir(parents=True)
    read_only_file = tree / "nested" / "read-only.txt"
    read_only_file.write_text("content", encoding="utf-8")
    read_only_file.chmod(stat.S_IREAD)

    remove_tree(tree)

    assert not tree.exists()


def test_prepare_run_dir_replaces_existing_run(tmp_path):
    stale_file = tmp_path / "run-1" / "stale.jsonl"
    stale_file.parent.mkdir()
    stale_file.write_text("{}", encoding="utf-8")

    run_dir = prepare_run_dir(tmp_path, "run-1")

    assert run_dir == tmp_path / "run-1"
    assert run_dir.is_dir()
    assert list(run_dir.iterdir()) == []


def test_prepare_run_dir_creates_missing_parents(tmp_path):
    run_dir = prepare_run_dir(tmp_path / "results", "run-2")

    assert run_dir.is_dir()


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
