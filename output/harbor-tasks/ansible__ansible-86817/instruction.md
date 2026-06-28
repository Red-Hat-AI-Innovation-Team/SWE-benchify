create ansible.github.com


Using --start-at-task no longer gathers facts implicitly
### Summary

Invoking `ansible-playbook` with `--start-at-task $NAME` no longer gathers facts about the hosts. Facts are gathered when `--start-at-task` or by downgrading to ansible-core 2.19.

### Issue Type

Bug Report

### Component Name

core

### Ansible Version

```console
$ ansible --version
ansible [core 2.20.0]
  config file = None
  configured module search path = ['/home/user/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /home/user/.pyenv/versions/3.13.8/envs/ansible/lib/python3.13/site-packages/ansible
  ansible collection location = /home/user/.ansible/collections:/usr/share/ansible/collections
  executable location = /home/user/.pyenv/versions/ansible/bin/ansible
  python version = 3.13.8 (main, Oct  8 2025, 08:15:56) [GCC 15.2.1 20250813] (/home/user/.pyenv/versions/3.13.8/envs/ansible/bin/python)
  jinja version = 3.1.6
  pyyaml version = 6.0.3 (with libyaml v0.2.5)
```

### Configuration

```console
# if using a version older than ansible-core 2.12 you should omit the '-t all'
$ ansible-config dump --only-changed -t all
CONFIG_FILE() = None
EDITOR(env: EDITOR) = nvim

GALAXY_SERVERS:
```

### OS / Environment

- Arch
- Python 3.13.8
- Ansible is installed in a virtual env, using pyenv

### Steps to Reproduce

Playbook:

<!--- Paste example playbooks or commands between quotes below -->
```yaml
- name: testing
  hosts: localhost
  become: false
  tasks:
    - name: Start
      debug:
        msg: hi
    - name: Three
      debug:
        var: ansible_facts
```

Invocation: `ansible-playbook test.yml --start-at-task Start`

### Expected Results

This should print `hi` for the first task and all gathered facts for the second task.

It works as expected if invoked via: `ansible-playbook test.yml` or when invoked with ansible-core 2.19 (downgrade).

### Actual Results

```console
ansible-playbook test.yml --start-at-task Start
[WARNING]: No inventory was parsed, only implicit localhost is available
[WARNING]: provided hosts list is empty, only localhost is available. Note that the implicit localhost does not match 'all'

PLAY [testing] *************************************************************************************************************************************************************************************************************************

TASK [Start] ***************************************************************************************************************************************************************************************************************************
ok: [localhost] => {
    "msg": "hi"
}

TASK [Three] ***************************************************************************************************************************************************************************************************************************
ok: [localhost] => {
    "ansible_facts": {}
}

PLAY RECAP *****************************************************************************************************************************************************************************************************************************
localhost                  : ok=2    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
```

### Code of Conduct

- [x] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `f2a58fd3b24541778c5f9d0780a0a6a42d609a71`

## Hints

done


Files identified in the description:

None

If these files are incorrect, please update the `component name` section of the description or use the [component](https://github.com/ansible/ansibotmini#commands) bot command.

<!--- boilerplate: components_banner --->


I'm not sure this should have ever worked, I would expect `--start-at-task`  to do what it says and 'start at the task' and not run any other tasks, implicit or otherwise. 

Fact gathering can be slow and expensive, if I'm going to run a task that does not use facts, I would not expect it to run, the same goes for `meta: flush_handlers` (another implicit task).

I bisected this to 27a56a34df7c7d879c2c0473aef5c58490024319. This wasn't a change I intended to make. I think we should restore the behavior, because `vars_prompt` and `vars_files` run regardless of `--start-at-task`.

I'm not sure what the fix is, but the problem is that the SETUP block contains multiple tasks, and after matching `--start-at-task`, the run_state is set to SETUP, without modifying the cur_block or cur_regular_task: https://github.com/ansible/ansible/blob/devel/lib/ansible/executor/play_iterator.py#L237-L240. Prior to the commit causing the issue, there was only a single SETUP task, so the cur_block/cur_regular_task were never referenced.

vars prompt and vars files do make sense as a play level import, i'm still on the fence about fact gathering, but if it is the 'implicit' one, it could be seen as 'play level' vs a normal task.

It was expected behavior as of 2.0: https://github.com/ansible/ansible/issues/15010. https://github.com/ansible/ansible/commit/27a56a34df7c7d879c2c0473aef5c58490024319 also broke the reproducer in that issue.

<details><summary>Before:</summary>

```console
PLAY [localhost] ************************************************************************************************************************************************

TASK [Gathering Facts] ******************************************************************************************************************************************
ok: [localhost]

TASK [start here] ***********************************************************************************************************************************************
ok: [localhost] => {
    "msg": "should start here"
}

TASK [run also] *************************************************************************************************************************************************
ok: [localhost] => {
    "msg": "run me too"
}

PLAY [second play] **********************************************************************************************************************************************

TASK [Gathering Facts] ******************************************************************************************************************************************
ok: [localhost]

TASK [this should run] ******************************************************************************************************************************************
ok: [localhost] => {
    "msg": "first task new play"
}

PLAY RECAP ******************************************************************************************************************************************************
localhost                  : ok=5    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0  
```
</details>

<details><summary>After:</summary>

```console
PLAY [localhost] ************************************************************************************************************************************************

PLAY [second play] **********************************************************************************************************************************************

TASK [Gathering Facts] ******************************************************************************************************************************************
ok: [localhost]

TASK [this should run] ******************************************************************************************************************************************
ok: [localhost] => {
    "msg": "first task new play"
}

PLAY RECAP ******************************************************************************************************************************************************
localhost                  : ok=2    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0  
```
</details>

Some input as an unsophisticated Ansible user (sorry if this is just noise / piling on!):
It seems like `--start-at-task` is totally broken in 2.20.2. Here's a MRE:
```
echo > test.yml '---
- name: Test
  hosts: localhost
  connection: local
  gather_facts: false
  tasks:
  - name: Task A
    ansible.builtin.debug:
      msg: A
  - name: Task B
    ansible.builtin.debug:
      msg: B'
uvx --from 'ansible-core==2.19.6' ansible-playbook test.yml --start-at-task 'Task B'
uvx --from 'ansible-core==2.20.2' ansible-playbook test.yml --start-at-task 'Task B'
```
The first command runs Task B, the second doesn't. I don't quite understand how this is related to `gather_facts` here since I have it disabled here anyway (maybe this should be a different bug)?

We see the same issue here @mattclay

Observing similar behaviour
- Running the playbook without `--start-at-task=...` performs as expected
- Supplying an invalid (i.e. non-existent) parameter to `--start-at-task=...` throws an error, as expected, that there is no matching task
- Supplying a valid (both fully-qualified with `role : task-name` or implicit with `task-name`) parameter to `--start-at-task=...` often leads to nothing being executed at all.

The behaviour is quite weird, however. Sometimes it helps to supply an earlier task to `--start-at-task`. Other times that doesn't work either. Whether a task can be 'targeted' with `--start-at-task` seems to depend on the task at hand. 
In one example I'm looking at now, an `ansible.builtin.get_url` task works as a starting point, whereas an `ansible.posix.firewalld` or `ansible.builtin.file` do not work.

Ansible core version `2.20.3`, atm.

Not sure if that is related with the originally reported issue of it not gathering facts - should potentially open a new issue, instead.

These do stem from the same underlying issue. The SETUP stage iterates through the block ansible should start at, so the host never starts at the right task, and if there is no following block the host is marked as complete for the play. This was caused by using the current `block` and `cur_regular_task` attribute [here](https://github.com/ansible/ansible/commit/27a56a34df7c7d879c2c0473aef5c58490024319#diff-5b550455cfef2fb28d42806f6495e67c1801173f06929263e3de6eadb788679cR299) and [here](https://github.com/ansible/ansible/commit/27a56a34df7c7d879c2c0473aef5c58490024319#diff-5b550455cfef2fb28d42806f6495e67c1801173f06929263e3de6eadb788679cR320). Those attributes are responsible for preserving the `--start-at-task`, so by overloading their meaning `--start-at-task` is just generally broken. I have a general fix here: https://github.com/ansible/ansible/pull/86345/changes?w=1, I've tried to make the subject and changelog clearer about the scope of the bug.
