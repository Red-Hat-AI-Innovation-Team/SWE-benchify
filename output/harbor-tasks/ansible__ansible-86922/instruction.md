ansible.builtin.command can fail with "can't concat NoneType to bytes" after remote command succeeds
### Summary

ansible.builtin.command can fail with "can't concat NoneType to bytes" after remote command succeeds

### Issue Type

Bug Report

### Component Name

module_utils/basic.py

### Ansible Version

```console
$ ansible --version
ansible [core 2.20.4]
  config file = /home/jpflouret/repos/homelab-workspace/ansible-homelab/ansible.cfg
  configured module search path = ['/home/jpflouret/repos/homelab-workspace/ansible-homelab/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /home/jpflouret/repos/homelab-workspace/ansible-homelab/.venv/lib64/python3.14/site-packages/ansible
  ansible collection location = /home/jpflouret/repos/homelab-workspace/ansible-homelab/.ansible/collections:/usr/share/ansible/collections
  executable location = /home/jpflouret/repos/homelab-workspace/ansible-homelab/.venv/bin/ansible
  python version = 3.14.4 (main, Apr  8 2026, 00:00:00) [GCC 15.2.1 20260123 (Red Hat 15.2.1-7)] (/home/jpflouret/repos/homelab-workspace/ansible-homelab/.venv/bin/python)
  jinja version = 3.1.6
  pyyaml version = 6.0.3 (with libyaml v0.2.5)
```

### Configuration

```console
# if using a version older than ansible-core 2.12 you should omit the '-t all'
$ ansible-config dump --only-changed -t all
ANSIBLE_HOME(/home/jpflouret/repos/homelab-workspace/ansible-homelab/ansible.cfg) = /home/jpflouret/repos/homelab-workspace/ansible-homelab/.ansible
CONFIG_FILE() = /home/jpflouret/repos/homelab-workspace/ansible-homelab/ansible.cfg
DEFAULT_HOST_LIST(/home/jpflouret/repos/homelab-workspace/ansible-homelab/ansible.cfg) = ['/home/jpflouret/repos/homelab-workspace/ansible-homelab/inventory']
DEFAULT_LOCAL_TMP(/home/jpflouret/repos/homelab-workspace/ansible-homelab/ansible.cfg) = /home/jpflouret/repos/homelab-workspace/ansible-homelab/.ansible/tmp/ansible-local-77932al0jkfhz
DEFAULT_STDOUT_CALLBACK(/home/jpflouret/repos/homelab-workspace/ansible-homelab/ansible.cfg) = debug
DEFAULT_VAULT_PASSWORD_FILE(/home/jpflouret/repos/homelab-workspace/ansible-homelab/ansible.cfg) = /home/jpflouret/repos/homelab-workspace/ansible-homelab/.vault_password
EDITOR(env: EDITOR) = /usr/bin/vim
HOST_KEY_CHECKING(/home/jpflouret/repos/homelab-workspace/ansible-homelab/ansible.cfg) = False
INTERPRETER_PYTHON(/home/jpflouret/repos/homelab-workspace/ansible-homelab/ansible.cfg) = auto_silent

GALAXY_SERVERS:


CONNECTION:
==========

paramiko_ssh (DEPRECATED):
_________________________
host_key_checking(/home/jpflouret/repos/homelab-workspace/ansible-homelab/ansible.cfg) = False

paramiko_ssh:
____________
host_key_checking(/home/jpflouret/repos/homelab-workspace/ansible-homelab/ansible.cfg) = False

ssh:
___
host_key_checking(/home/jpflouret/repos/homelab-workspace/ansible-homelab/ansible.cfg) = False
```

### OS / Environment

Host:
Fedora Linux 43 (KDE Plasma Desktop Edition)
Python 3.14.4

Target:
Debian GNU/Linux 13 (trixie)
Python 3.13.5
Raspberry Pi 4 4GB

### Steps to Reproduce

Occurred once with `kubeadm upgrade plan/apply`. The commands succeeded even though ansible reported errors

The upgrade role contains this task:

```yaml
- name: Drain node
  ansible.builtin.command: kubectl drain {{ inventory_hostname }} --kubeconfig /etc/kubernetes/admin.conf --ignore-daemonsets --delete-emptydir-data
  delegate_to: "{{ primary_control_plane }}"
  changed_when: true

- name: Run upgrade commands
  ansible.builtin.command: "{{ item }}"
  loop: "{{ kubernetes_upgrade_commands }}"
  changed_when: true

# ...
```

With:
```yaml
        kubernetes_upgrade_commands:
          - kubeadm upgrade plan {{ kubernetes.version }}
          - kubeadm upgrade apply {{ kubernetes.version }} --yes
```

Command used:

```bash
ansible-playbook upgrade-k8s.yaml -v
```

Important detail: both `kubeadm` commands completed successfully on the remote node despite Ansible reporting failure.

Suspected code path (from Codex):

```python
b_chunk = key.fileobj.read(32768)
if not b_chunk and b_chunk is not None:
    selector.unregister(key.fileobj)
elif key.fileobj == cmd.stdout:
    stdout += b_chunk
elif key.fileobj == cmd.stderr:
    stderr += b_chunk
```

If `read(32768)` returns `None` for a non-blocking pipe, it is not unregistered and falls through to `stdout += b_chunk` / `stderr += b_chunk`, raising `TypeError: can't concat NoneType to bytes`.


### Expected Results

The ansible.builtin.command task should report the actual remote command result.

### Actual Results

```console
TASK [kubernetes_upgrade : Run upgrade commands] ******************************************************************************************************************************************
[ERROR]: Task failed: Module failed: Error executing command: can't concat NoneType to bytes
Origin: /home/jpflouret/repos/homelab-workspace/ansible-homelab/roles/kubernetes_upgrade/tasks/main.yaml:7:3

5   changed_when: true
6
7 - name: Run upgrade commands
    ^ column 3

failed: [rpi-master-1] (item=kubeadm upgrade plan 1.36.0) => {
    "ansible_loop_var": "item",
    "changed": true,
    "cmd": "kubeadm upgrade plan 1.36.0",
    "item": "kubeadm upgrade plan 1.36.0",
    "rc": 257
}

MSG:

Error executing command.

failed: [rpi-master-1] (item=kubeadm upgrade apply 1.36.0 --yes) => {
    "ansible_loop_var": "item",
    "changed": true,
    "cmd": "kubeadm upgrade apply 1.36.0 --yes",
    "item": "kubeadm upgrade apply 1.36.0 --yes",
    "rc": 257
}

MSG:

Error executing command.
```

### Code of Conduct

- [x] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `883360fa0068bfc65b35906909fa1f6388153a17`

## Hints

Files identified in the description:

None

If these files are incorrect, please update the `component name` section of the description or use the [component](https://github.com/ansible/ansibotmini#commands) bot command.

<!--- boilerplate: components_banner --->
