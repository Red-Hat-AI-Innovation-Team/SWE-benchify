merge the repositories
Merge docs, plugins, contrib all together to make it easier to work with and manage pull requests.

There can be only 3.

Be sure to preserve history using appropriate git tree grafting commands.


Rescue block no longer works with handlers
### Summary

We have a playbook that's run fine for many years. We set it up to notify us of failures using a rescue block, but it's stopped working.

### Issue Type

Bug Report

### Component Name

rescue

### Ansible Version

```console
ansible [core 2.16.3]
  config file = None
  configured module search path = ['/home/cesium/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /usr/lib/python3/dist-packages/ansible
  ansible collection location = /home/cesium/.ansible/collections:/usr/share/ansible/collections
  executable location = /usr/bin/ansible
  python version = 3.12.3 (main, Jun 18 2025, 17:59:45) [GCC 13.3.0] (/usr/bin/python3)
  jinja version = 3.1.2
  libyaml = True
```

### Configuration

```console
CONFIG_FILE() = None
EDITOR(env: EDITOR) = vim
```

### OS / Environment

Ubuntu 24.04

### Steps to Reproduce

We have a role with a tasks file like this:
```
[initial tasks]

- block
  - name: Clone code repo
    git: [...]
    notify: [several handlers]

  [additional tasks]

  - meta: flush_handlers

  - name: Notify success
    uri: [webhook]
rescue:
  - name: Notify failure
    uri: [webhook, using ansible_failed_task and ansible_failed_result in the payload]
```

The handlers are defined in a separate file.

### Expected Results

Since we added the rescue block, the behavior has been that if any of the [additional tasks] fails, or any of the handlers fails, then ansible jumps to the rescue block, sends the notification including the failed task information, then exits.

As of recently, the `ansible_failed_*` variables are no longer defined when the rescue block runs. This causes the rescue block to itself fail and not send us a notification. See below for the error message. It seems this doesn't happen when the error came from one of the [additional tasks], so it's a handler-specific issue.

I worked around this by adding a `register:` to every single handler, and reading that instead of `ansible_failed_*`. This fixes the rescue block, but then the behavior I see is that it runs the rescue block and then goes back to running the rest of the handlers before exiting. This seems wrong to me, but I could see it being an intentional change.

### Actual Results

```console
TASK [Clone code repo] ******************************************************************************************************************************
changed: [hostname]

[additional tasks]

TASK [meta] *****************************************************************************************************************************************

RUNNING HANDLER [build client] **********************************************************************************************************************
fatal: [hostname]: FAILED! => {"changed": true, ...}

TASK [Notify failure] ***************************************************************************************************************
fatal: [hostname]: FAILED! => {"msg": "The task includes an option with an undefined variable. The error was: 'ansible_failed_task' is undefine
d. 'ansible_failed_task' is undefined\n\nThe error appears to be in '[filename]': line 140, column 7, but may\nbe elsewhere 
in the file depending on the exact syntax problem.\n\nThe offending line appears to be:\n\n  rescue:\n    - name: Notify failure\n      ^ h
ere\n"}
```

### Code of Conduct

- [x] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `b1fc98c8ad9d56ee65cc43fb46de87f2ee52b18c`

## Hints

Content merged over, still need to update docs references and make sure any pull requests on ansible-plugins and docs are migrated over.


Files identified in the description:

None

If these files are incorrect, please update the `component name` section of the description or use the [component](https://github.com/ansible/ansibotmini#commands) bot command.

<!--- boilerplate: components_banner --->


@cesium12 `ansible-core` 2.16 is not supported and no longer receives bug fixes. Please test against one of [the supported versions](https://docs.ansible.com/ansible/devel/reference_appendices/release_and_maintenance.html#ansible-core-support-matrix) of `ansible-core`, preferably the most recent one, to see whether the bug has been fixed.

[click here for bot help](https://github.com/ansible/ansibotmini#ansibotmini)
<!--- boilerplate: unsupported_version --->


I'm not able to reproduce on 2.16.3 or more recent versions. ~Can you provide a minimal, standalone reproducer?~

<details>
  <summary>Here's what I've tried.</summary>

```console
├── roles
│   └── test
│       └── tasks
│           └── main.yml
└── playbook.yml
```

```yaml
# roles/test/tasks/main.yml 
- block:
  - command: "echo 'notify handler'"
    notify:
      - Handler 1
      - Handler 2

  - meta: flush_handlers

  - name: Notify success
    debug: msg="handlers were successful"
  rescue:
  - assert:
      that: ansible_failed_task is defined
      success_msg: "ansible_failed_task is defined"
```

```yaml
# playbook.yml
- hosts: h1,h2
  connection: local
  gather_facts: no
  handlers:
    - name: Handler 1
      debug: msg="hander 1"
    - name: Handler 2
      command: "{{ (inventory_hostname == 'h1') | ternary('/bin/true', '/bin/false') }}"
  tasks:
    - include_role:
        name: test
```

```console
ansible-playbook -i h1,h2 playbook.yml

PLAY [h1,h2] ************************************************************************************************************************************************************

TASK [include_role : test] **********************************************************************************************************************************************

TASK [test : command] ***************************************************************************************************************************************************
changed: [h1]
changed: [h2]

TASK [test : meta] ******************************************************************************************************************************************************

TASK [test : meta] ******************************************************************************************************************************************************

RUNNING HANDLER [Handler 1] *********************************************************************************************************************************************
ok: [h1] => {
    "msg": "hander 1"
}
ok: [h2] => {
    "msg": "hander 1"
}

RUNNING HANDLER [Handler 2] *********************************************************************************************************************************************
fatal: [h2]: FAILED! => {"changed": true, "cmd": ["/bin/false"], "delta": "0:00:00.001500", "end": "2025-08-18 11:01:55.000177", "msg": "non-zero return code", "rc": 1, "start": "2025-08-18 11:01:54.998677", "stderr": "", "stderr_lines": [], "stdout": "", "stdout_lines": []}
changed: [h1]

TASK [test : Notify success] ********************************************************************************************************************************************
ok: [h1] => {
    "msg": "handlers were successful"
}

TASK [test : assert] ****************************************************************************************************************************************************
ok: [h2] => {
    "changed": false,
    "msg": "ansible_failed_task is defined"
}

PLAY RECAP **************************************************************************************************************************************************************
h1                         : ok=4    changed=2    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0   
h2                         : ok=3    changed=1    unreachable=0    failed=0    skipped=0    rescued=1    ignored=0
```
</details>

@mkrizek devised a reproducer:

```yaml
- hosts: localhost
  gather_facts: false
  tasks:
    - block:
        - debug:
          changed_when: true
          notify: h1
  
        - meta: flush_handlers
      rescue:
        - assert:
            that:
              - ansible_failed_task is defined
  handlers:
    - name: h1
      fail:
```
