from bcbench.collection.patch_utils import split_patch_by_projects

TEST_PROJECTS = ["App\\Apps\\W1\\Shopify\\test"]

APP_FILE_DIFF = """diff --git a/App/Apps/W1/Shopify/app/Order.Codeunit.al b/App/Apps/W1/Shopify/app/Order.Codeunit.al
--- a/App/Apps/W1/Shopify/app/Order.Codeunit.al
+++ b/App/Apps/W1/Shopify/app/Order.Codeunit.al
@@ -1,3 +1,3 @@
-    if Quantity < 0 then
+    if Quantity <= 0 then
"""

TEST_FILE_DIFF = """diff --git a/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al b/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al
--- a/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al
+++ b/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al
@@ -1,3 +1,6 @@
+    [Test]
+    procedure TestNegativeQuantity()
"""


def test_app_only_patch_returns_empty_test_half():
    app_patch, test_patch = split_patch_by_projects(APP_FILE_DIFF, TEST_PROJECTS)

    assert app_patch == APP_FILE_DIFF
    assert test_patch == ""


def test_test_only_patch_returns_empty_app_half():
    app_patch, test_patch = split_patch_by_projects(TEST_FILE_DIFF, TEST_PROJECTS)

    assert app_patch == ""
    assert test_patch == TEST_FILE_DIFF


def test_mixed_patch_is_split_by_project():
    app_patch, test_patch = split_patch_by_projects(APP_FILE_DIFF + TEST_FILE_DIFF, TEST_PROJECTS)

    assert app_patch == APP_FILE_DIFF
    assert test_patch == TEST_FILE_DIFF


def test_each_half_keeps_its_diff_git_header():
    app_patch, test_patch = split_patch_by_projects(APP_FILE_DIFF + TEST_FILE_DIFF, TEST_PROJECTS)

    assert app_patch.startswith("diff --git a/App/Apps/W1/Shopify/app/Order.Codeunit.al")
    assert test_patch.startswith("diff --git a/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al")


def test_backslash_project_paths_match_forward_slash_diff_paths():
    _app_patch, test_patch = split_patch_by_projects(TEST_FILE_DIFF, ["App\\Apps\\W1\\Shopify\\test"])

    assert test_patch == TEST_FILE_DIFF


def test_empty_patch_returns_two_empty_strings():
    assert split_patch_by_projects("", TEST_PROJECTS) == ("", "")
    assert split_patch_by_projects("   \n", TEST_PROJECTS) == ("", "")
