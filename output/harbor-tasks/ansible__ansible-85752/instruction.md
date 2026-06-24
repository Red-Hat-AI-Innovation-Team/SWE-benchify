merge the repositories
Merge docs, plugins, contrib all together to make it easier to work with and manage pull requests.

There can be only 3.

Be sure to preserve history using appropriate git tree grafting commands.


Ansible Core: 2.19: In ternary variable is evaluated in case not triggered
### Summary

When using variable in the true/false case of `ternary` on Ansible Core 2.19, then variable in the case not triggered seems to be evaluated nonetheless. This will lead to an error if a dict is used and the key referenced does not exists.

This behaviour is different from Ansible Core 2.18.

### Issue Type

Bug Report

### Component Name

ansible.builtin.ternary

### Ansible Version

```console
$ ansible --version
ansible [core 2.19.1]
  config file = /home/charly/eclipseprojects/spp_playground/ansible.cfg
  configured module search path = ['/opt/ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /opt/ansible/lib/python3.13/site-packages/ansible
  ansible collection location = /opt/ansible/collections:/usr/share/ansible/collections
  executable location = /usr/bin/ansible
  python version = 3.13.6 (main, Aug  7 2025, 10:53:54) [GCC 14.2.0] (/opt/ansible/bin/python3)
  jinja version = 3.1.6
  pyyaml version = 6.0.2 (with libyaml v0.2.5)
```

### Configuration

```console
# if using a version older than ansible-core 2.12 you should omit the '-t all'
$ ansible-config dump --only-changed -t all
ANSIBLE_HOME(env: ANSIBLE_HOME) = /opt/ansible
CALLBACKS_ENABLED(env: ANSIBLE_CALLBACKS_ENABLED) = ['profile_tasks']
CONFIG_FILE() = /home/charly/eclipseprojects/spp_playground/ansible.cfg
DEFAULT_GATHERING(env: ANSIBLE_GATHERING) = explicit
DEFAULT_LOG_PATH(env: ANSIBLE_LOG_PATH) = /tmp/ansible.log
DEFAULT_ROLES_PATH(env: ANSIBLE_ROLES_PATH) = ['/home/charly/eclipseprojects/spp_playground', '/home/charly/eclipseprojects']
EDITOR(env: EDITOR) = vi
GALAXY_IGNORE_CERTS(/home/charly/eclipseprojects/spp_playground/ansible.cfg) = False
HOST_KEY_CHECKING(/home/charly/eclipseprojects/spp_playground/ansible.cfg) = False
INTERPRETER_PYTHON(env: ANSIBLE_PYTHON_INTERPRETER) = /usr/bin/python3
RETRY_FILES_ENABLED(env: ANSIBLE_RETRY_FILES_ENABLED) = False

GALAXY_SERVERS:


CALLBACK:
========

default:
_______
result_format(env: ANSIBLE_CALLBACK_RESULT_FORMAT) = yaml

minimal:
_______
result_format(env: ANSIBLE_CALLBACK_RESULT_FORMAT) = yaml

CONNECTION:
==========

paramiko_ssh:
____________
host_key_checking(/home/charly/eclipseprojects/spp_playground/ansible.cfg) = False

ssh:
___
control_path(/home/charly/eclipseprojects/spp_playground/ansible.cfg) = %(directory)s/%%h-%%r
host_key_checking(/home/charly/eclipseprojects/spp_playground/ansible.cfg) = False
```

### OS / Environment

- Controller: Debian Testing
```
$ lsb_release -a
No LSB modules are available.
Distributor ID:	Debian
Description:	Debian GNU/Linux forky/sid
Release:	n/a
Codename:	forky
```
- Managed host: Debian 12
```
$ lsb_release -a
No LSB modules are available.
Distributor ID:	Debian
Description:	Debian GNU/Linux 12 (bookworm)
Release:	12
Codename:	bookworm
```

### Steps to Reproduce

<!--- Paste example playbooks or commands between quotes below -->
```yaml (paste below)
$ cat ternary.yml 
---

- hosts: all
  become: true

  tasks:

    - name: get file info for /tmp/does_not_exist
      stat:
        path: /tmp/does_not_exist
      register: rc_stat

    - name: set mtime fact
      set_fact:
        mtime_fact: '{{ rc_stat.stat.exists | ternary(rc_stat.stat.mtime, 0) }}'
```


### Expected Results

Fact `mtime_fact` should have value 0, as it is the case using Ansible Core 2.18.
```
ansible-playbook [core 2.18.8]
  config file = /home/charly/eclipseprojects/spp_playground/ansible.cfg
...
Using /home/charly/eclipseprojects/spp_playground/ansible.cfg as config file
BECOME password: 
redirecting (type: callback) ansible.builtin.profile_tasks to ansible.posix.profile_tasks
Skipping callback 'default', as we already have a stdout callback.
Skipping callback 'minimal', as we already have a stdout callback.
Skipping callback 'oneline', as we already have a stdout callback.

PLAYBOOK: ternary.yml *********************
1 plays in ternary.yml

PLAY [all] **********************

TASK [get file info for /tmp/does_not_exist] *********************
task path: /home/charly/eclipseprojects/spp_playground/ternary.yml:8
Dienstag 26 August 2025  10:55:27 +0200 (0:00:00.008)       0:00:00.008 ******* 
ok: [charly-dev01.server.lan] => 
    changed: false
    stat:
        exists: false

TASK [set mtime fact] ******************
task path: /home/charly/eclipseprojects/spp_playground/ternary.yml:13
Dienstag 26 August 2025  10:55:29 +0200 (0:00:02.007)       0:00:02.015 ******* 
ok: [charly-dev01.server.lan] => 
    ansible_facts:
        mtime_fact: '0'
    changed: false
```

### Actual Results

```console
On Ansible 2.19.1 an error is raised:

ansible-playbook [core 2.19.1]
  config file = /home/charly/eclipseprojects/spp_playground/ansible.cfg
  configured module search path = ['/opt/ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /opt/ansible/lib/python3.13/site-packages/ansible
  ansible collection location = /opt/ansible/collections:/usr/share/ansible/collections
  executable location = /usr/bin/ansible-playbook
  python version = 3.13.6 (main, Aug  7 2025, 10:53:54) [GCC 14.2.0] (/opt/ansible/bin/python3)
  jinja version = 3.1.6
  pyyaml version = 6.0.2 (with libyaml v0.2.5)
Using /home/charly/eclipseprojects/spp_playground/ansible.cfg as config file
BECOME password: 
redirecting (type: callback) ansible.builtin.profile_tasks to ansible.posix.profile_tasks
Skipping callback 'minimal', as we already have a stdout callback.
Skipping callback 'oneline', as we already have a stdout callback.

PLAYBOOK: ternary.yml *********************
1 plays in ternary.yml

PLAY [all] *********************

TASK [get file info for /tmp/does_not_exist] *********************
task path: /home/charly/eclipseprojects/spp_playground/ternary.yml:8
Dienstag 26 August 2025  11:12:26 +0200 (0:00:00.008)       0:00:00.008 ******* 
ok: [charly-dev01.server.lan] => 
    changed: false
    stat:
        exists: false

TASK [set mtime fact] **********************
task path: /home/charly/eclipseprojects/spp_playground/ternary.yml:13
Dienstag 26 August 2025  11:12:28 +0200 (0:00:01.936)       0:00:01.945 ******* 
[ERROR]: Task failed: Finalization of task args for 'ansible.builtin.set_fact' failed: Error while resolving value for 'mtime_fact': object of type 'dict' has no attribute 'mtime'

Task failed.
Origin: /home/charly/eclipseprojects/spp_playground/ternary.yml:13:7

11       register: rc_stat
12
13     - name: set mtime fact
         ^ column 7

<<< caused by >>>

Finalization of task args for 'ansible.builtin.set_fact' failed.
Origin: /home/charly/eclipseprojects/spp_playground/ternary.yml:14:7

12
13     - name: set mtime fact
14       set_fact:
         ^ column 7

<<< caused by >>>

Error while resolving value for 'mtime_fact': object of type 'dict' has no attribute 'mtime'
Origin: /home/charly/eclipseprojects/spp_playground/ternary.yml:15:21

13     - name: set mtime fact
14       set_fact:
15         mtime_fact: '{{ rc_stat.stat.exists | ternary(rc_stat.stat.mtime, 0) }}'
                       ^ column 21

fatal: [charly-dev01.server.lan]: FAILED! => 
    changed: false
    msg: 'Task failed: Finalization of task args for ''ansible.builtin.set_fact'' failed:
        Error while resolving value for ''mtime_fact'': object of type ''dict'' has no
        attribute ''mtime'''

PLAY RECAP ******************************
charly-dev01.server.lan    : ok=1    changed=0    unreachable=0    failed=1    skipped=0    rescued=0    ignore
```

### Code of Conduct

- [x] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `b3ef4f767195e3597cf2f38d694055cb1442c572`

## Hints

Content merged over, still need to update docs references and make sure any pull requests on ansible-plugins and docs are migrated over.


Files identified in the description:

None

If these files are incorrect, please update the `component name` section of the description or use the [component](https://github.com/ansible/ansibotmini#commands) bot command.

<!--- boilerplate: components_banner --->


As a workaround [inline if expression](https://jinja.palletsprojects.com/en/stable/templates/#if-expression) works in both versions:

```yaml
- set_fact:
    mtime_fact: "{{ rc_stat.stat.mtime if rc_stat.stat.exists else 0 }}"
```

According to the [documentation](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/ternary_filter.html#notes) this appears to be expected behavior:

> Vars as values are evaluated even when not returned. This is due to them being evaluated before being passed into the filter.

However I understand this is a breaking change. This needs further investigation.

@mkrizek This looks like it should be an easy fix. The `ternary` filter just needs the `@accept_args_markers` decorator:

https://github.com/ansible/ansible/blob/3ec07418aa0dd295aa4d607ea5190c32c25125ff/lib/ansible/plugins/filter/core.py#L223

We should add some tests to cover this use case.
