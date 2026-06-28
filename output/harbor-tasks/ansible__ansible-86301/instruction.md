Using ansible_local triggers INJECT_FACTS_AS_VARS deprecation when using Ansible 13 (core 2.20)
### Summary

After switching to Ansible 13 and using ansible_facts nicely I still got deprecation warnings. I was able to narrow it down to using `ansible_local`. Whenever this variable is used you will also get this deprecation warning which I think is "wrong" as there is not even a `ansible_facts.local`.

### Issue Type

Bug Report

### Component Name

core

### Ansible Version

```console
$ ansible --version
ansible-playbook [core 2.20.0]
  config file = None
  configured module search path = ['./plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = ./python3.13/site-packages/ansible
  ansible collection location = ./collections:/usr/share/ansible/collections
  executable location = .venv/bin/ansible-playbook
  python version = 3.13.5 (main, Jun 12 2025, 12:22:43) [Clang 20.1.4 ] (.venv/bin/python3)
  jinja version = 3.1.6
  pyyaml version = 6.0.2 (with libyaml v0.2.5)
```

### Configuration

```console
# if using a version older than ansible-core 2.12 you should omit the '-t all'
$ ansible-config dump --only-changed -t all
CONFIG_FILE() = None
PAGER(env: PAGER) = less

GALAXY_SERVERS:
```

### OS / Environment

macOS

### Steps to Reproduce

<!--- Paste example playbooks or commands between quotes below -->
```yaml (paste below)
- hosts: all
  remote_user: root
  tasks:
    - debug:
        msg: "{{ ansible_local }}"
```


### Expected Results

```console
➜  infrastructure git:(main) ✗ uv run ansible-playbook -i home, playbook.yml

PLAY [all] **********

TASK [Gathering Facts] **********
ok: [home]

TASK [debug] **********
ok: [home] => {
    "msg": {}
}

PLAY RECAP **********
home                       : ok=2    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0   
```

### Actual Results

```console
➜  infrastructure git:(main) ✗ uv run ansible-playbook -i home, playbook.yml

PLAY [all] **********

TASK [Gathering Facts] **********
ok: [home]

TASK [debug] **********
[WARNING]: Deprecation warnings can be disabled by setting `deprecation_warnings=False` in ansible.cfg.
[DEPRECATION WARNING]: INJECT_FACTS_AS_VARS default to `True` is deprecated, top-level facts will not be auto injected after the change. This feature will be removed from ansible-core version 2.24.
Origin: playbook.yml:5:14

3   tasks:
4     - debug:
5         msg: "{{ ansible_local }}"
               ^ column 14

Use `ansible_facts["fact_name"]` (no `ansible_` prefix) instead.

ok: [home] => {
    "msg": {}
}

PLAY RECAP **********
home                       : ok=2    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
```

### Code of Conduct

- [x] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `85ddbc444448c968d6f159ea150633e7467e30f0`

## Hints

Files identified in the description:

None

If these files are incorrect, please update the `component name` section of the description or use the [component](https://github.com/ansible/ansibotmini#commands) bot command.

<!--- boilerplate: components_banner --->


`ansible_local` is a special case, and is always called `ansible_local`, even when inside of `ansible_facts`.  That variable name is never "de-prefixed".  Although this wouldn't really be easy to document well in the warning.

Although, maybe we can just duplicate the key de-prefixed.

this is still a false positive, since `ansible_local` is always meant to be at the top level.

just need to create a filter when adding the deprecation:
```
diff --git a/lib/ansible/vars/manager.py b/lib/ansible/vars/manager.py
index fb4970cd74..0c8d0f7c60 100644
--- a/lib/ansible/vars/manager.py
+++ b/lib/ansible/vars/manager.py
@@ -299,7 +299,7 @@ class VariableManager:
                 # push facts to main namespace
                 if inject:
                     if origin == 'default':
-                        clean_top = {k: _deprecate_top_level_fact(v) for k, v in clean_facts(facts).items()}
+                        clean_top = {k: _deprecate_top_level_fact(v) for k, v in clean_facts(facts).items() if k != 'ansible_local'}
                     else:
                         clean_top = clean_facts(facts)
                     all_vars = _combine_and_track(all_vars, clean_top, "facts")


```
