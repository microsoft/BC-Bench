import hashlib
import json
import subprocess

import pytest
from bcbench_core.git import apply_patch

from bcbench.dataset.codereview import CodeReviewEntry
from tools import review_voting_paths as paths
from tools.review_voting_evidence import file_digest, tree_digest
from tools.review_voting_recovery import expected_source_inventory, prove_no_inference


def test_long_path_inventory_hash_and_execution_copy_account_for_every_file(tmp_path):
    root = tmp_path / "source"
    relative = "/".join(["segment" * 12] * 4 + ["fixture.al"])
    leaf = root / relative
    assert len(str(leaf)) > 260
    paths.filesystem_path(leaf.parent).mkdir(parents=True)
    paths.filesystem_path(leaf).write_bytes(b"safe fixture\n")
    (root / "short.al").write_bytes(b"short\n")
    inventory = paths.snapshot_inventory(root)
    assert set(inventory) == {relative, "short.al"}
    assert inventory[relative]["sha256"] == file_digest(leaf) == hashlib.sha256(b"safe fixture\n").hexdigest()
    destination = tmp_path / "execution" / "source"
    paths.copy_tree(root, destination)
    assert paths.snapshot_inventory(destination) == inventory
    assert tree_digest(destination) == tree_digest(root)
    paths.filesystem_path(destination / relative).unlink()
    with pytest.raises(ValueError, match="missing="):
        paths.validate_inventory(paths.snapshot_inventory(destination), {p: r["git_blob"] for p, r in inventory.items()})


@pytest.mark.parametrize("failure", [PermissionError, FileNotFoundError])
def test_unstatable_entry_is_not_silently_omitted(tmp_path, monkeypatch, failure):
    class Entry:
        name = "unstatable.al"

        def stat(self, *, follow_symlinks):
            raise failure("fixture entry cannot be statted")

    class Entries:
        def __enter__(self):
            return iter([Entry()])

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(paths.os, "scandir", lambda *a: Entries())
    with pytest.raises(failure, match="cannot be statted"):
        paths.snapshot_inventory(tmp_path)


def test_disappearing_file_between_enumeration_and_hashing_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "snapshot_files", lambda *a: [("missing.al", tmp_path / "missing.al")])
    with pytest.raises(FileNotFoundError):
        paths.snapshot_inventory(tmp_path)


def test_unreadable_directory_fails(tmp_path, monkeypatch):
    def denied(*args):
        raise PermissionError("fixture enumeration denied")

    monkeypatch.setattr(paths.os, "scandir", denied)
    with pytest.raises(PermissionError, match="enumeration denied"):
        paths.snapshot_files(tmp_path)


def test_altered_or_extra_snapshot_is_not_accepted(tmp_path):
    (tmp_path / "a.al").write_bytes(b"original")
    expected = {p: r["git_blob"] for p, r in paths.snapshot_inventory(tmp_path).items()}
    (tmp_path / "a.al").write_bytes(b"altered")
    with pytest.raises(ValueError, match="differs from pinned"):
        paths.validate_inventory(paths.snapshot_inventory(tmp_path), expected)
    (tmp_path / "extra.al").write_bytes(b"extra")
    with pytest.raises(ValueError, match="extra="):
        paths.validate_inventory(paths.snapshot_inventory(tmp_path), expected)


def test_alternate_git_index_accounts_for_patch_additions_and_deletions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()

    def git(*args, patch=None):
        return subprocess.run(["git", *args], cwd=source, input=patch, capture_output=True, check=True).stdout

    git("init", "--quiet")
    git("config", "core.autocrlf", "false")
    (source / "remove.al").write_bytes(b"old\n")
    (source / "keep.al").write_bytes(b"keep\n")
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Fixture")
    base = git("rev-parse", "HEAD").decode().strip()
    patch = (
        "diff --git a/remove.al b/remove.al\n"
        "deleted file mode 100644\n--- a/remove.al\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n"
        "diff --git a/add.al b/add.al\n"
        "new file mode 100644\n--- /dev/null\n+++ b/add.al\n@@ -0,0 +1 @@\n+new\n"
    )
    entry = CodeReviewEntry.model_validate(
        {
            "instance_id": "synthetic__fixture-01",
            "base_commit": base,
            "created_at": "2026-01-01",
            "environment_setup_version": "27.0",
            "project_paths": [],
            "patch": patch,
            "metadata": {"area": "security"},
            "expected_comments": [],
        }
    )
    before, index_before = tree_digest(source), file_digest(source / ".git" / "index")
    expected = expected_source_inventory(source, entry, tmp_path / "validation")
    assert set(expected) == {"keep.al", "add.al"}
    assert tree_digest(source) == before
    assert file_digest(source / ".git" / "index") == index_before
    apply_patch(source, patch)
    paths.validate_inventory(paths.snapshot_inventory(source), expected)


def test_pre_inference_proof_rejects_any_inference_artifact(tmp_path):
    (tmp_path / "execution").mkdir()
    (tmp_path / "execution" / "started.json").write_text(json.dumps({"started_unix": 1}))
    (tmp_path / "case-01" / "source").mkdir(parents=True)
    proof = prove_no_inference(tmp_path)
    assert proof["baseline_invocations"] == proof["verifier_invocations"] == proof["judge_invocations"] == 0
    (tmp_path / "case-01" / "baseline").mkdir()
    with pytest.raises(ValueError, match="Unexpected inference"):
        prove_no_inference(tmp_path)
