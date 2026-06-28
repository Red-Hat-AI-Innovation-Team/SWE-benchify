#!/bin/bash
set -euo pipefail

cat > /testbed/solution_patch.diff << '__SOLUTION__'
diff --git a/changelogs/fragments/86957-uniontechos-server-redhat-family.yml b/changelogs/fragments/86957-uniontechos-server-redhat-family.yml
new file mode 100644
index 00000000000000..460a7be7c95468
--- /dev/null
+++ b/changelogs/fragments/86957-uniontechos-server-redhat-family.yml
@@ -0,0 +1,2 @@
+bugfixes:
+  - distribution facts - classify UnionTech OS Server (UOS Server) as ``RedHat`` ``os_family`` instead of ``Debian``. UOS Server is RPM-based and built on top of openAnolis (A version, codename ``kongzi``) or openEuler (E version, codename ``fuyu``), and advertises ``PLATFORM_ID="platform:uel*"`` in ``/etc/os-release``. The Debian-based Desktop edition is unchanged (https://github.com/ansible/ansible/issues/86957).
diff --git a/lib/ansible/module_utils/facts/system/distribution.py b/lib/ansible/module_utils/facts/system/distribution.py
index ee32605e4291e5..aa4852ad0343c5 100644
--- a/lib/ansible/module_utils/facts/system/distribution.py
+++ b/lib/ansible/module_utils/facts/system/distribution.py
@@ -56,6 +56,8 @@ class DistributionFiles:
         {'path': '/etc/oracle-release', 'name': 'OracleLinux'},
         {'path': '/etc/slackware-version', 'name': 'Slackware'},
         {'path': '/etc/centos-release', 'name': 'CentOS'},
+        # Must precede RedHat: A-version UOS Server symlinks redhat-release to uos-release.
+        {'path': '/etc/redhat-release', 'name': 'UnionTech'},
         {'path': '/etc/redhat-release', 'name': 'RedHat'},
         {'path': '/etc/vmware-release', 'name': 'VMwareESX', 'allowempty': True},
         {'path': '/etc/openwrt_release', 'name': 'OpenWrt'},
@@ -67,6 +69,7 @@ class DistributionFiles:
         {'path': '/etc/os-release', 'name': 'SUSE'},
         {'path': '/etc/SuSE-release', 'name': 'SUSE'},
         {'path': '/etc/gentoo-release', 'name': 'Gentoo'},
+        {'path': '/etc/os-release', 'name': 'UnionTech'},
         {'path': '/etc/os-release', 'name': 'Debian'},
         {'path': '/etc/lsb-release', 'name': 'Debian'},
         {'path': '/etc/lsb-release', 'name': 'Mandriva'},
@@ -393,6 +396,11 @@ def parse_distribution_file_Debian(self, name, data, path, collected_facts):
                 debian_facts['distribution_version'] = version.group(1)
                 debian_facts['distribution_major_version'] = version.group(1).split('.')[0]
         elif 'UOS' in data or 'Uos' in data or 'uos' in data:
+            # The RHEL-based UnionTech OS Server variants are handled by
+            # parse_distribution_file_UnionTech via the dedicated OSDIST_LIST entry,
+            # so skip them here to avoid mis-classifying them as the Debian-based Uos.
+            if re.search(r'PLATFORM_ID="?platform:uel', data):
+                return False, debian_facts
             debian_facts['distribution'] = 'Uos'
             release = re.search(r"VERSION_CODENAME=\"?([^\"]+)\"?", data)
             if release:
@@ -513,6 +521,37 @@ def parse_distribution_file_CentOS(self, name, data, path, collected_facts):
 
         return False, centos_facts
 
+    def parse_distribution_file_UnionTech(self, name, data, path, collected_facts):
+        # UOS Server (RHEL-based) is identified by PLATFORM_ID="platform:uel*" in
+        # /etc/os-release, or "UOS Server release" / "UnionTech OS Server release"
+        # in /etc/redhat-release. UOS Desktop (Debian-based, no PLATFORM_ID) is
+        # left to parse_distribution_file_Debian.
+        uniontech_facts = {}
+        is_uos_release_file = bool(re.search(r'(UnionTech OS Server|UOS Server) release', data))
+        has_uel_platform_id = bool(re.search(r'PLATFORM_ID="?platform:uel', data))
+        if not (is_uos_release_file or has_uel_platform_id):
+            return False, uniontech_facts
+
+        uniontech_facts['distribution'] = 'UnionTech'
+        release = re.search(r'VERSION_CODENAME="?([^"\n]+)"?', data)
+        if release:
+            uniontech_facts['distribution_release'] = release.group(1)
+        else:
+            # /etc/redhat-release style: "UnionTech OS Server release 20 (kongzi)"
+            release = re.search(r'release\s+\S+\s+\(([^)]+)\)', data)
+            if release:
+                uniontech_facts['distribution_release'] = release.group(1)
+        version = re.search(r'VERSION_ID="?([^"\n]+)"?', data)
+        if version:
+            uniontech_facts['distribution_version'] = version.group(1)
+            uniontech_facts['distribution_major_version'] = version.group(1).split('.')[0]
+        else:
+            version = re.search(r'release\s+(\S+)', data)
+            if version:
+                uniontech_facts['distribution_version'] = version.group(1)
+                uniontech_facts['distribution_major_version'] = version.group(1).split('.')[0]
+        return True, uniontech_facts
+
 
 class Distribution(object):
     """
@@ -528,7 +567,8 @@ class Distribution(object):
                                 'Ascendos', 'CloudLinux', 'PSBM', 'OracleLinux', 'OVS',
                                 'OEL', 'Amazon', 'Amzn', 'Virtuozzo', 'XenServer', 'Alibaba',
                                 'EulerOS', 'openEuler', 'AlmaLinux', 'Rocky', 'TencentOS',
-                                'EuroLinux', 'Kylin Linux Advanced Server', 'MIRACLE'],
+                                'EuroLinux', 'Kylin Linux Advanced Server', 'MIRACLE',
+                                'UnionTech'],
                      'Debian': ['Debian', 'Ubuntu', 'Raspbian', 'Neon', 'KDE neon',
                                 'Linux Mint', 'SteamOS', 'Devuan', 'Kali', 'Cumulus Linux',
                                 'Pop!_OS', 'Parrot', 'Pardus GNU/Linux', 'Uos', 'Deepin', 'OSMC',
__SOLUTION__

cd /testbed
patch --fuzz=5 -p1 -i /testbed/solution_patch.diff
