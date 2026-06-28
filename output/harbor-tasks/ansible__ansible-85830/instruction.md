Resolve 2.20 deprecations
The following deprecations are scheduled for removal in 2.20 and need to be resolved:

- [x] lib/ansible/cli/doc.py pylint:ansible-deprecated-version
- [x] lib/ansible/galaxy/api.py pylint:ansible-deprecated-version
- [x] lib/ansible/plugins/filter/encryption.py pylint:ansible-deprecated-version
- [x] lib/ansible/utils/encrypt.py pylint:ansible-deprecated-version
- [x] lib/ansible/utils/py3compat.py pylint:ansible-deprecated-version
- [x] lib/ansible/utils/ssh_functions.py pylint:ansible-deprecated-version
- [x] lib/ansible/vars/manager.py pylint:ansible-deprecated-version-comment
- [x] lib/ansible/vars/plugins.py pylint:ansible-deprecated-version
- [x] lib/ansible/modules/dnf.py validate-modules:ansible-deprecated-version
- [x] lib/ansible/modules/dnf5.py validate-modules:ansible-deprecated-version

@ansibot bot_skip

**Repository:** `ansible/ansible`
**Base commit:** `e30da5173160887ad88d8f066fb2d4f783c7fa10`
