git module can "lose" local commits
### Summary

ansible.builtin.git (with default force: false and update: true) carefully doesn't clobber uncommitted local modifications in the destination directory, but it does run `cmd = "%s reset --hard %s/%s" % (git_path, remote, version)` which can result in losing track of local **commits** not yet pushed to origin.

Note: my environment happens to be 2.13.3, but I can still see the problem in https://github.com/ansible/ansible/blob/devel/lib/ansible/modules/git.py#L1044

### Issue Type

Bug Report

### Component Name

git

### Ansible Version

```console
$ ansible --version
ansible [core 2.13.3]
  config file = /etc/ansible/ansible.cfg
  configured module search path = ['/home/dmrz/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /home/dmrz/.local/lib/python3.10/site-packages/ansible
  ansible collection location = /home/dmrz/.ansible/collections:/usr/share/ansible/collections
  executable location = /home/dmrz/.local/bin/ansible
  python version = 3.10.12 (main, Nov 20 2023, 15:14:05) [GCC 11.4.0]
  jinja version = 3.1.2
  libyaml = True
```


### Configuration

```console
$ ansible-config dump --only-changed -t all
```


### OS / Environment

Ubuntu 22.04.4 LTS

### Steps to Reproduce

<!--- Paste example playbooks or commands between quotes below -->
test-git.yml:
```yaml
- hosts: localhost
  tasks:
  - git:
      dest: mygitdir
      repo: https://github.com/ansible/ansible.git
      version: devel
```
1. Initial run
```
dmrz@golbez:~$ ansible-playbook test-git.yml 
[WARNING]: provided hosts list is empty, only localhost is available. Note that the implicit localhost does not match 'all'

PLAY [localhost] ***********************************************************************************************************************************************************

TASK [Gathering Facts] *****************************************************************************************************************************************************
ok: [localhost]

TASK [git] *****************************************************************************************************************************************************************
changed: [localhost]

PLAY RECAP *****************************************************************************************************************************************************************
localhost                  : ok=2    changed=1    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0   
```
2. Make a new git commit
```
dmrz@golbez:~$ echo "DUMMY CHANGE" >> mygitdir/README.md; git -C mygitdir commit -m "DUMMY CHANGE" README.md
[devel a1c34a79cd] DUMMY CHANGE
 1 file changed, 1 insertion(+)

dmrz@golbez:~$ git -C mygitdir log -2
commit a1c34a79cd43d49dcb8689951be08ea82c24e604 (HEAD -> devel)
Author: David Zych <dmrz@REDACTED>
Date:   Tue Jun 4 11:43:29 2024 -0500

    DUMMY CHANGE

commit c77ed376c4f2df1ce619690ddf1fd02b33d328aa (origin/devel, origin/HEAD)
Author: Brian Coca <bcoca@users.noreply.github.com>
Date:   Tue Jun 4 11:42:15 2024 -0400

    timeout give extra info (#83206)
    
    the new field shows the python code in execution when it timed out, 99% of the time it will be on a selector waiting for output from ssh to remote.
```
3. Rerun the playbook
```
dmrz@golbez:~$ ansible-playbook test-git.yml
[WARNING]: provided hosts list is empty, only localhost is available. Note that the implicit localhost does not match 'all'

PLAY [localhost] ***********************************************************************************************************************************************************

TASK [Gathering Facts] *****************************************************************************************************************************************************
ok: [localhost]

TASK [git] *****************************************************************************************************************************************************************
changed: [localhost]

PLAY RECAP *****************************************************************************************************************************************************************
localhost                  : ok=2    changed=1    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0   
```
4. Observe that branch `devel` has been reset to match `origin/devel` and our commit a1c34a79cd is gone!
```
dmrz@golbez:~$ git -C mygitdir log -2
commit c77ed376c4f2df1ce619690ddf1fd02b33d328aa (HEAD -> devel, origin/devel, origin/HEAD)
Author: Brian Coca <bcoca@users.noreply.github.com>
Date:   Tue Jun 4 11:42:15 2024 -0400

    timeout give extra info (#83206)
    
    the new field shows the python code in execution when it timed out, 99% of the time it will be on a selector waiting for output from ssh to remote.

commit e07b4edc547e2a5bd429d1027c0102235616db6c
Author: MajesticMagikarpKing <69774548+yctomwang@users.noreply.github.com>
Date:   Mon Jun 3 23:51:32 2024 +1000

    Fix Test failure with cowsay installed/present (#83347)
```

Okay, it's not _completely_ gone, I can find it again with `git reflog`, but only if I realize that something is amiss (which is not at all obvious).

### Expected Results

The current behavior (make local branch head match remote no matter what) would be completely reasonable/expected if I had set `force: true`.

In the absence of `force: true`, I would expect `update: true` to update my local branch head (and working tree) with ["new revisions from the origin repository"](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/git_module.html#parameter-update) only if it can do so **without endangering my work in the destination directory**.

I think perhaps `git merge --ff-only origin/devel` would provide the right behavior here:
- if I had no local commits, it would have the same result as status quo
- if I have local commits but origin/devel has not advanced since then, it would succeed ("Already up to date.") **without** modifying my local branch head, i.e. no-op
- if I have local commits and origin/devel _has_ advanced, it would fail with "fatal: Not possible to fast-forward, aborting.", resulting in an Ansible task failure (similar to the failure that occurs now if I have uncommitted local modifications)


### Actual Results

Branch `devel` has been reset to match `origin/devel` and our commit a1c34a79cd is gone (see Steps to Reproduce)


### Code of Conduct

- [X] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `3adecacccf408960128d7cc122e8212a88ae4e9b`

## Hints

Files identified in the description:

* [`lib/ansible/modules/git.py`](https://github.com/ansible/ansible/blob/devel/lib/ansible/modules/git.py)

If these files are incorrect, please update the `component name` section of the description or use the [component](https://github.com/ansible/ansibotmini#commands) bot command.

<!--- boilerplate: components_banner --->


@dmrzzz `ansible-core` 2.13 is not supported and no longer receives bug fixes. Please test against one of [the supported versions](https://docs.ansible.com/ansible/devel/reference_appendices/release_and_maintenance.html#ansible-core-support-matrix) of `ansible-core`, preferably the most recent one, to see whether the bug has been fixed.

[click here for bot help](https://github.com/ansible/ansibotmini#ansibotmini)
<!--- boilerplate: unsupported_version --->


OK fine ansibot, retested same steps on AlmaLinux 9.4 with
```
$ ansible --version
ansible [core 2.15.12]
  config file = None
  configured module search path = ['/home/dmrz/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /home/dmrz/.local/lib/python3.9/site-packages/ansible
  ansible collection location = /home/dmrz/.ansible/collections:/usr/share/ansible/collections
  executable location = /home/dmrz/.local/bin/ansible
  python version = 3.9.18 (main, Jan 24 2024, 00:00:00) [GCC 11.4.1 20231218 (Red Hat 11.4.1-3)] (/usr/bin/python3)
  jinja version = 3.1.4
  libyaml = True
```
with the same result.

`git reflog` to the rescue
