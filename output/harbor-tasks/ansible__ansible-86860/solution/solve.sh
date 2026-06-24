#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/83367-git-force-local-commits.yml b/changelogs/fragments/83367-git-force-local-commits.yml
new file mode 100644
index 00000000000000..b69f44df3ba1f5
--- /dev/null
+++ b/changelogs/fragments/83367-git-force-local-commits.yml
@@ -0,0 +1,2 @@
+bugfixes:
+  - git - fix ``force`` parameter to properly preserve local commits when set to ``false`` and fail with a clear error message (https://github.com/ansible/ansible/issues/83367)
diff --git a/lib/ansible/modules/git.py b/lib/ansible/modules/git.py
index 5ad0e77b3882d7..0632859b1eca80 100644
--- a/lib/ansible/modules/git.py
+++ b/lib/ansible/modules/git.py
@@ -103,8 +103,8 @@
         version_added: "1.9"
     force:
         description:
-            - If V(true), any modified files in the working
-              repository will be discarded.  Prior to 0.7, this was always
+            - If V(true), any modified files in the working repository and
+              local commits will be discarded.  Prior to 0.7, this was always
               V(true) and could not be disabled.  Prior to 1.9, the default was
               V(true).
         type: bool
@@ -1031,7 +1031,7 @@ def set_remote_branch(git_path, module, dest, remote, version, depth):
         module.fail_json(msg="Failed to fetch branch from remote: %s" % version, stdout=out, stderr=err, rc=rc)
 
 
-def switch_version(git_path, module, dest, remote, version, verify_commit, depth, gpg_allowlist):
+def switch_version(git_path, module, dest, remote, version, verify_commit, depth, gpg_allowlist, force=False):
     cmd = ''
     if version == 'HEAD':
         branch = get_head_branch(git_path, module, dest, remote)
@@ -1054,7 +1054,13 @@ def switch_version(git_path, module, dest, remote, version, verify_commit, depth
                 (rc, out, err) = module.run_command("%s checkout --force %s" % (git_path, version), cwd=dest)
                 if rc != 0:
                     module.fail_json(msg="Failed to checkout branch %s" % version, stdout=out, stderr=err, rc=rc)
-                cmd = "%s reset --hard %s/%s" % (git_path, remote, version)
+                if ('ahead' in out or 'diverged' in out) and not force:
+                    module.fail_json(msg=f"Unable to advance to {remote}/{version} because local commits will be lost. "
+                                     f"Use `force: yes` to overwrite local commits.")
+                if force:
+                    cmd = f"{git_path} reset --hard {remote}/{version}"
+                else:
+                    cmd = f"{git_path} merge --ff-only {remote}/{version}"
         else:
             cmd = "%s checkout --force %s" % (git_path, version)
     (rc, out1, err1) = module.run_command(cmd, cwd=dest)
@@ -1395,7 +1401,7 @@ def main():
     # switch to version specified regardless of whether
     # we got new revisions from the repository
     if not bare:
-        switch_version(git_path, module, dest, remote, version, verify_commit, depth, gpg_allowlist)
+        switch_version(git_path, module, dest, remote, version, verify_commit, depth, gpg_allowlist, force=force)
 
     # Deal with submodules
     submodules_updated = False
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
