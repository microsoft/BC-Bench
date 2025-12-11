"""Tests for patch statistics computation."""

from bcbench.collection.patch_utils import compute_patch_stats


def test_compute_patch_stats_single_file():
    patch = """diff --git a/App/Code.al b/App/Code.al
--- a/App/Code.al
+++ b/App/Code.al
@@ -1,3 +1,5 @@
 procedure OldCode()
 begin
+    // New line 1
+    // New line 2
 end;
"""
    num_files, num_lines = compute_patch_stats(patch)
    assert num_files == 1
    assert num_lines == 2


def test_compute_patch_stats_multiple_files():
    patch = """diff --git a/App/Code1.al b/App/Code1.al
--- a/App/Code1.al
+++ b/App/Code1.al
@@ -1,2 +1,3 @@
 line1
+line2
 line3
diff --git a/App/Code2.al b/App/Code2.al
--- a/App/Code2.al
+++ b/App/Code2.al
@@ -1,1 +1,2 @@
 oldline
+newline
"""
    num_files, num_lines = compute_patch_stats(patch)
    assert num_files == 2
    assert num_lines == 2


def test_compute_patch_stats_empty_patch():
    num_files, num_lines = compute_patch_stats("")
    assert num_files == 0
    assert num_lines == 0


def test_compute_patch_stats_real_patch():
    # Real patch from the dataset
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
    num_files, num_lines = compute_patch_stats(patch)
    assert num_files == 1
    # The patch adds 13 lines total
    assert num_lines == 13


def test_compute_patch_stats_invalid_patch():
    # Invalid patch should return 0s
    num_files, num_lines = compute_patch_stats("not a valid patch")
    assert num_files == 0
    assert num_lines == 0


def test_compute_patch_stats_multiple_files_real_example():
    # Test with a patch that modifies multiple files
    patch = """diff --git a/App/File1.al b/App/File1.al
--- a/App/File1.al
+++ b/App/File1.al
@@ -1,2 +1,4 @@
 line1
+added1
+added2
 line2
diff --git a/App/File2.al b/App/File2.al
--- a/App/File2.al
+++ b/App/File2.al
@@ -1,1 +1,3 @@
 original
+new1
+new2
"""
    num_files, num_lines = compute_patch_stats(patch)
    assert num_files == 2
    assert num_lines == 4
