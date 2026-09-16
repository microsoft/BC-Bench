import pytest

from bcbench.operations.patch_operations import GitDiffPaths, extract_git_diff_paths


def test_strips_synthetic_prefixes_from_file_headers():
    diff_block = """\
diff --git a/a/Main/Feature.Codeunit.al b/b/Main/Feature.Codeunit.al
--- a/a/Main/Feature.Codeunit.al
+++ b/b/Main/Feature.Codeunit.al
@@ -1 +1 @@
-codeunit 1 Old {}
+codeunit 1 New {}
"""

    assert extract_git_diff_paths(diff_block) == GitDiffPaths(
        source="a/Main/Feature.Codeunit.al",
        target="b/Main/Feature.Codeunit.al",
    )


@pytest.mark.parametrize("operation", ["rename", "copy"])
def test_preserves_repository_relative_metadata_prefixes(operation: str):
    diff_block = f"""\
diff --git a/a/Main/Old.Codeunit.al b/b/Main/New.Codeunit.al
similarity index 100%
{operation} from a/Main/Old.Codeunit.al
{operation} to b/Main/New.Codeunit.al
"""

    assert extract_git_diff_paths(diff_block) == GitDiffPaths(
        source="a/Main/Old.Codeunit.al",
        target="b/Main/New.Codeunit.al",
    )
