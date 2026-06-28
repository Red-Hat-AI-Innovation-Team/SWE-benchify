templates: lookup errors while accessing missing key in dict
### Summary

When trying to use templates that access a key in a dict that does not exist, even when `| default` is specified in the expression it errors out. This seems to be a regression issue, as this did not happen in the previous ansible versions.

### Issue Type

Bug Report

### Component Name

ansible, ansible-core

### Ansible Version

```console
$ ansible --version
ansible [core 2.19.0]
  config file = None
  configured module search path = ['/home/user/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /usr/lib/python3.13/site-packages/ansible
  ansible collection location = /home/user/.ansible/collections:/usr/share/ansible/collections
  executable location = /usr/bin/ansible
  python version = 3.13.5 (main, Jun 21 2025, 09:35:00) [GCC 15.1.1 20250425] (/usr/bin/python)
  jinja version = 3.1.6
  pyyaml version = 6.0.2 (with libyaml v0.2.5)
```

### Configuration

```console
# if using a version older than ansible-core 2.12 you should omit the '-t all'
$ ansible-config dump --only-changed -t all
CONFIG_FILE() = None
EDITOR(env: EDITOR) = nvim
PAGER(env: PAGER) = less

GALAXY_SERVERS:
```

### OS / Environment

Arch Linux (original repro)
Debian Trixie (for poc bellow)

### Steps to Reproduce

Sample playbook.yaml:
```yaml
- name: Sample playbook
  hosts: localhost
  tasks:
    - name: Debug print success
      ansible.builtin.debug:
        msg: "{{ template_data }}"
      vars:
        template_data: "{{ lookup('template', 'template.txt') }}"
        template_opts: "{{ sample_var['sample_key'] | default('sample_default') }}"
        sample_var:
          sample_key: "sample_value"

    - name: Debug print failure
      ansible.builtin.debug:
        msg: "{{ template_data }}"
      vars:
        template_data: "{{ lookup('template', 'template.txt') }}"
        template_opts: "{{ sample_var['sample_key2'] | default('sample_default') }}"
        sample_var:
          sample_key: "sample_value"
```

Sample template.txt:
```
# Sample template
{{ template_opts }}
```

### Expected Results

```
> podman run --name debian-bookworm -it --rm debian:bookworm
root@5f208e7062e4:/# apt update
Get:1 http://deb.debian.org/debian bookworm InRelease [151 kB]
Get:2 http://deb.debian.org/debian bookworm-updates InRelease [55.4 kB]
Get:3 http://deb.debian.org/debian-security bookworm-security InRelease [48.0 kB]
Get:4 http://deb.debian.org/debian bookworm/main amd64 Packages [8793 kB]
Get:5 http://deb.debian.org/debian bookworm-updates/main amd64 Packages [6924 B]
Get:6 http://deb.debian.org/debian-security bookworm-security/main amd64 Packages [274 kB]
Fetched 9329 kB in 1s (9260 kB/s)
Reading package lists... Done
Building dependency tree... Done
Reading state information... Done
All packages are up to date.
root@5f208e7062e4:/# apt install ansible
Reading package lists... Done
Building dependency tree... Done
Reading state information... Done
The following additional packages will be installed:
  ansible-core ca-certificates ieee-data krb5-locales libbsd0 libcbor0.8 libedit2 libexpat1
...
Setting up ansible (7.7.0+dfsg-3+deb12u1) ...
Processing triggers for libc-bin (2.36-9+deb12u10) ...
Processing triggers for ca-certificates (20230311+deb12u1) ...
Updating certificates in /etc/ssl/certs...
0 added, 0 removed; done.
Running hooks in /etc/ca-certificates/update.d...
done.
root@5f208e7062e4:/# cd $(mktemp -d)
root@5f208e7062e4:/tmp/tmp.hdaDLZqsNa# cat >playbook.yaml <<EOF
> - name: Sample playbook
  hosts: localhost
  tasks:
    - name: Debug print success
      ansible.builtin.debug:
        msg: "{{ template_data }}"
      vars:
        template_data: "{{ lookup('template', 'template.txt') }}"
        template_opts: "{{ sample_var['sample_key'] | default('sample_default') }}"
        sample_var:
          sample_key: "sample_value"

    - name: Debug print failure
      ansible.builtin.debug:
        msg: "{{ template_data }}"
      vars:
        template_data: "{{ lookup('template', 'template.txt') }}"
        template_opts: "{{ sample_var['sample_key2'] | default('sample_default') }}"
        sample_var:
          sample_key: "sample_value"
> EOF
root@5f208e7062e4:/tmp/tmp.hdaDLZqsNa# cat >template.txt <<EOF
> # Sample template
{{ template_opts }}
> EOF
root@5f208e7062e4:/tmp/tmp.hdaDLZqsNa# ansible-playbook playbook.yaml
[WARNING]: No inventory was parsed, only implicit localhost is available
[WARNING]: provided hosts list is empty, only localhost is available. Note that the implicit localhost does not match 'all'

PLAY [Sample playbook] ***********************************************************************************************************************************************************************************

TASK [Gathering Facts] ***********************************************************************************************************************************************************************************
ok: [localhost]

TASK [Debug print success] *******************************************************************************************************************************************************************************
ok: [localhost] => {
    "msg": "# Sample template\nsample_value\n"
}

TASK [Debug print failure] *******************************************************************************************************************************************************************************
ok: [localhost] => {
    "msg": "# Sample template\nsample_default\n"
}

PLAY RECAP ***********************************************************************************************************************************************************************************************
localhost                  : ok=3    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
```

### Actual Results

```console
> podman run --name debian-trixie -it --rm debian:trixie
root@6e69c6fab585:/# apt update
Get:1 http://deb.debian.org/debian trixie InRelease [138 kB]
Get:2 http://deb.debian.org/debian trixie-updates InRelease [47.1 kB]
Get:3 http://deb.debian.org/debian-security trixie-security InRelease [43.4 kB]
Get:4 http://deb.debian.org/debian trixie/main amd64 Packages [9668 kB]
Get:5 http://deb.debian.org/debian trixie-updates/main amd64 Packages [2432 B]
Get:6 http://deb.debian.org/debian-security trixie-security/main amd64 Packages [8780 B]
Fetched 9907 kB in 1s (10.3 MB/s)
All packages are up to date.
root@6e69c6fab585:/# apt install ansible
Installing:
  ansible
...
Setting up ansible (12.0.0~a6+dfsg-1) ...
Processing triggers for libc-bin (2.41-12) ...
Processing triggers for ca-certificates (20250419) ...
Updating certificates in /etc/ssl/certs...
0 added, 0 removed; done.
Running hooks in /etc/ca-certificates/update.d...
done.
root@6e69c6fab585:/# cd $(mktemp -d)
root@6e69c6fab585:/tmp/tmp.i1gsojt4Qs# cat >playbook.yaml <<EOF
> - name: Sample playbook
  hosts: localhost
  tasks:
    - name: Debug print success
      ansible.builtin.debug:
        msg: "{{ template_data }}"
      vars:
        template_data: "{{ lookup('template', 'template.txt') }}"
        template_opts: "{{ sample_var['sample_key'] | default('sample_default') }}"
        sample_var:
          sample_key: "sample_value"

    - name: Debug print failure
      ansible.builtin.debug:
        msg: "{{ template_data }}"
      vars:
        template_data: "{{ lookup('template', 'template.txt') }}"
        template_opts: "{{ sample_var['sample_key2'] | default('sample_default') }}"
        sample_var:
          sample_key: "sample_value"
> EOF
root@6e69c6fab585:/tmp/tmp.i1gsojt4Qs# cat >template.txt <<EOF
> # Sample template
{{ template_opts }}
> EOF
root@6e69c6fab585:/tmp/tmp.i1gsojt4Qs# ansible-playbook playbook.yaml
[WARNING]: No inventory was parsed, only implicit localhost is available
[WARNING]: provided hosts list is empty, only localhost is available. Note that the implicit localhost does not match 'all'

PLAY [Sample playbook] ***********************************************************************************************************************************************************************************

TASK [Gathering Facts] ***********************************************************************************************************************************************************************************
ok: [localhost]

TASK [Debug print success] *******************************************************************************************************************************************************************************
ok: [localhost] => {
    "msg": "# Sample template\nsample_value\n"
}

TASK [Debug print failure] *******************************************************************************************************************************************************************************
[ERROR]: Task failed: Finalization of task args for 'ansible.builtin.debug' failed: Error while resolving value for 'msg': The lookup plugin 'template' failed: object of type 'dict' has no attribute 'sample_key2'

Task failed.
Origin: /tmp/tmp.i1gsojt4Qs/playbook.yaml:13:7

11           sample_key: "sample_value"
12
13     - name: Debug print failure
         ^ column 7

<<< caused by >>>

Finalization of task args for 'ansible.builtin.debug' failed.
Origin: /tmp/tmp.i1gsojt4Qs/playbook.yaml:14:7

12
13     - name: Debug print failure
14       ansible.builtin.debug:
         ^ column 7

<<< caused by >>>

Error while resolving value for 'msg'.
Origin: /tmp/tmp.i1gsojt4Qs/playbook.yaml:15:14

13     - name: Debug print failure
14       ansible.builtin.debug:
15         msg: "{{ template_data }}"
                ^ column 14

<<< caused by >>>

The lookup plugin 'template' failed.
Origin: /tmp/tmp.i1gsojt4Qs/playbook.yaml:17:24

15         msg: "{{ template_data }}"
16       vars:
17         template_data: "{{ lookup('template', 'template.txt') }}"
                          ^ column 24

<<< caused by >>>

object of type 'dict' has no attribute 'sample_key2'
Origin: /tmp/tmp.i1gsojt4Qs/playbook.yaml:18:24

16       vars:
17         template_data: "{{ lookup('template', 'template.txt') }}"
18         template_opts: "{{ sample_var['sample_key2'] | default('sample_default') }}"
                          ^ column 24

fatal: [localhost]: FAILED! => {"msg": "Task failed: Finalization of task args for 'ansible.builtin.debug' failed: Error while resolving value for 'msg': The lookup plugin 'template' failed: object of type 'dict' has no attribute 'sample_key2'"}

PLAY RECAP ***********************************************************************************************************************************************************************************************
localhost                  : ok=2    changed=0    unreachable=0    failed=1    skipped=0    rescued=0    ignored=0
```

### Code of Conduct

- [x] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `3518d48146b3ecda6f8cfc6c33922aa9d492ad4f`

## Hints

Files identified in the description:

* [`bin/ansible`](https://github.com/ansible/ansible/blob/devel/bin/ansible)

If these files are incorrect, please update the `component name` section of the description or use the [component](https://github.com/ansible/ansibotmini#commands) bot command.

<!--- boilerplate: components_banner --->


This also happens with current `devel`. And changing `sample_var['sample_key2']` to `sample_var.sample_key2` makes the problem go away.

As an additional note, the above workaround does not work for the cases you need a non-static / dynamic key (that cannot be used with the dot notation).

A workaround for dynamic keys - tested on 2.19 locally - is:
```yaml
        template_opts: "{{ sample_var.get('sample_key2', 'sample_default') }}"
```
Which is certainly an undesirable deviation from the conventional Ansible idiom, but it might help as a short-term measure.
