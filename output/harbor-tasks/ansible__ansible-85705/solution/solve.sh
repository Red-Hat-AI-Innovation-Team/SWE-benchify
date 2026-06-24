#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/85632-setup-logical-volume-name-uniqueness.yml b/changelogs/fragments/85632-setup-logical-volume-name-uniqueness.yml
new file mode 100644
index 00000000000000..275a9db629265e
--- /dev/null
+++ b/changelogs/fragments/85632-setup-logical-volume-name-uniqueness.yml
@@ -0,0 +1,6 @@
+minor_changes:
+- >-
+  setup - added new subkey ``lvs`` within each entry of ``ansible_facts['vgs']``
+  to provide complete logical volume data scoped by volume group.
+  The top level ``lvs`` fact by comparison, deduplicates logical volume names
+  across volume groups and may be incomplete. (https://github.com/ansible/ansible/issues/85632)
diff --git a/lib/ansible/module_utils/facts/hardware/linux.py b/lib/ansible/module_utils/facts/hardware/linux.py
index 88f16945811b1d..a28ea9e48da9dd 100644
--- a/lib/ansible/module_utils/facts/hardware/linux.py
+++ b/lib/ansible/module_utils/facts/hardware/linux.py
@@ -890,7 +890,8 @@ def get_lvm_facts(self):
                     'size_g': items[-2],
                     'free_g': items[-1],
                     'num_lvs': items[2],
-                    'num_pvs': items[1]
+                    'num_pvs': items[1],
+                    'lvs': {},
                 }
 
             lvs_path = self.module.get_bin_path('lvs')
@@ -901,7 +902,18 @@ def get_lvm_facts(self):
                 rc, lv_lines, err = self.module.run_command('%s %s' % (lvs_path, lvm_util_options))
                 for lv_line in lv_lines.splitlines():
                     items = lv_line.strip().split(',')
-                    lvs[items[0]] = {'size_g': items[3], 'vg': items[1]}
+                    vg_name = items[1]
+                    lv_name = items[0]
+                    # The LV name is only unique per VG, so the top level fact lvs can be misleading.
+                    # TODO: deprecate lvs in favor of vgs
+                    lvs[lv_name] = {'size_g': items[3], 'vg': vg_name}
+                    try:
+                        vgs[vg_name]['lvs'][lv_name] = {'size_g': items[3]}
+                    except KeyError:
+                        self.module.warn(
+                            "An LVM volume group was created while gathering LVM facts, "
+                            "and is not included in ansible_facts['vgs']."
+                        )
 
             pvs_path = self.module.get_bin_path('pvs')
             # pvs fields: PV VG #Fmt #Attr PSize PFree
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
