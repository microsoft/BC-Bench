from bcbench.utils import count_files_in_patch, count_lines_in_patch


def test_count_files_single_file():
    patch = """diff --git a/file1.al b/file1.al
index 123..456 789
--- a/file1.al
+++ b/file1.al
@@ -1,3 +1,4 @@
 line1
+new line
 line2
 line3
"""
    assert count_files_in_patch(patch) == 1


def test_count_files_multiple_files():
    patch = """diff --git a/file1.al b/file1.al
index 123..456 789
--- a/file1.al
+++ b/file1.al
@@ -1,3 +1,4 @@
 line1
+new line
 line2
 line3
diff --git a/file2.al b/file2.al
index abc..def 123
--- a/file2.al
+++ b/file2.al
@@ -1,2 +1,3 @@
 line1
+another new line
 line2
"""
    assert count_files_in_patch(patch) == 2


def test_count_files_empty_patch():
    assert count_files_in_patch("") == 0


def test_count_files_whitespace_only():
    assert count_files_in_patch("   \n\n  ") == 0


def test_count_lines_added_only():
    patch = """diff --git a/file1.al b/file1.al
index 123..456 789
--- a/file1.al
+++ b/file1.al
@@ -1,3 +1,4 @@
 line1
+new line
 line2
 line3
"""
    assert count_lines_in_patch(patch) == 1


def test_count_lines_removed_only():
    patch = """diff --git a/file1.al b/file1.al
index 123..456 789
--- a/file1.al
+++ b/file1.al
@@ -1,4 +1,3 @@
 line1
-removed line
 line2
 line3
"""
    assert count_lines_in_patch(patch) == 1


def test_count_lines_added_and_removed():
    patch = """diff --git a/file1.al b/file1.al
index 123..456 789
--- a/file1.al
+++ b/file1.al
@@ -1,4 +1,4 @@
 line1
-old line
+new line
 line2
 line3
"""
    assert count_lines_in_patch(patch) == 2


def test_count_lines_multiple_files():
    patch = """diff --git a/file1.al b/file1.al
index 123..456 789
--- a/file1.al
+++ b/file1.al
@@ -1,3 +1,4 @@
 line1
+new line
 line2
 line3
diff --git a/file2.al b/file2.al
index abc..def 123
--- a/file2.al
+++ b/file2.al
@@ -1,2 +1,3 @@
 line1
+another new line
 line2
"""
    assert count_lines_in_patch(patch) == 2


def test_count_lines_empty_patch():
    assert count_lines_in_patch("") == 0


def test_count_lines_whitespace_only():
    assert count_lines_in_patch("   \n\n  ") == 0


def test_count_files_and_lines_with_real_al_patch():
    patch = """diff --git a/App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al b/App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al
index 335c0099f4a..bf9281c17f7 100644
--- a/App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al
+++ b/App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al
@@ -151,6 +151,8 @@ table 6217 "Sustainability Setup"
                 if Rec."Enable Value Chain Tracking" then
                     if not ConfirmManagement.GetResponseOrDefault(ConfirmEnableValueChainTrackingQst, false) then
                         Error('');
+
+                EnableEmissionsWhenValueChainTrackingIsEnabled();
             end;
         }
     }
@@ -188,6 +190,17 @@ table 6217 "Sustainability Setup"
         exit("Enable Value Chain Tracking");
     end;

+    local procedure EnableEmissionsWhenValueChainTrackingIsEnabled()
+    begin
+        if not Rec."Enable Value Chain Tracking" then
+            exit;
+
+        Rec.Validate("Use Emissions In Purch. Doc.", true);
+        Rec.Validate("Item Emissions", true);
+        Rec.Validate("Resource Emissions", true);
+        Rec.Validate("Work/Machine Center Emissions", true);
+    end;
+
     internal procedure GetFormat(FieldNo: Integer): Text
     begin
         GetSustainabilitySetup();
"""
    assert count_files_in_patch(patch) == 1
    assert count_lines_in_patch(patch) == 13
