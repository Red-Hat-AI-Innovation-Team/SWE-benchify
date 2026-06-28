merge the repositories
Merge docs, plugins, contrib all together to make it easier to work with and manage pull requests.

There can be only 3.

Be sure to preserve history using appropriate git tree grafting commands.


Play tags prevents executing role handlers in ansible-core 2.19
### Summary

In ansible 2.19, defining a play tag prevents role handlers from executing. If you run the playbook with the role tag, notified handler is not executed.

This works well in ansible 2.18 (and before) and also when there are no *play* tags defined.

### Issue Type

Bug Report

### Component Name

core

### Ansible Version

```console
$ ansible --version
ansible [core 2.19.0rc2]
  config file = ~/projects/ansible-handlers-error/ansible.cfg
  configured module search path = ['~/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = ~/.virtualenvs/ansible2.19/lib/python3.13/site-packages/ansible
  ansible collection location = ~/.ansible/collections:/usr/share/ansible/collections
  executable location = ~/.virtualenvs/ansible2.19/bin/ansible
  python version = 3.13.5 (main, Jun 25 2025, 18:55:22) [GCC 14.2.0] (~/.virtualenvs/ansible2.19/bin/python)
  jinja version = 3.1.6
  pyyaml version = 6.0.2 (with libyaml v0.2.5)
```

### Configuration

```console
# if using a version older than ansible-core 2.12 you should omit the '-t all'
$ ansible-config dump --only-changed -t all
ANSIBLE_NOCOWS(~/projects/ansible-handlers-error/ansible.cfg) = True
CONFIG_FILE() = ~/projects/ansible-handlers-error/ansible.cfg
EDITOR(env: EDITOR) = vim
PAGER(env: PAGER) = less

GALAXY_SERVERS:
```

### OS / Environment

Debian 13 (testing)

### Steps to Reproduce

1. Use this `playbook.yml`:
    ```yaml
    - name: Test handler
      hosts: localhost
      roles:
        - name: foo
          tags:
            - foo
      tags:
        - broken
    ```
2. Use this role `foo`:
    `tasks.yml`:
    ```yaml
    - name: Ping
      ansible.builtin.ping:
      changed_when: true
      notify: Handle this
    ```
    `handler.yml`:
    ```yaml
    - name: Handle this
      ansible.builtin.debug:
        msg: "Handler fired"
    ```
3. Run the playbook with the role tag:
    ```
    ansible-playbook -C -t foo playbook.yml
    ```
4. Handlers are not executed

### Expected Results

```console
PLAY [Test handler] ************************************************************************************

TASK [broken : meta] ***********************************************************************************

TASK [broken : Ping] ***********************************************************************************
changed: [localhost]

RUNNING HANDLER [broken : Handle this] *****************************************************************
ok: [localhost] => {
    "msg": "Handler fired"
}

PLAY RECAP *********************************************************************************************
localhost                  : ok=3    changed=1    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0   
```

### Actual Results

```console
PLAY [Test handler] ************************************************************************************

TASK [broken : meta] ***********************************************************************************

TASK [broken : Ping] ***********************************************************************************
changed: [localhost]

PLAY RECAP *********************************************************************************************
localhost                  : ok=1    changed=1    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
```

### Code of Conduct

- [x] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `6bee84318d681c5d582d7baf9f3bdee37b49b2e9`

## Hints

Content merged over, still need to update docs references and make sure any pull requests on ansible-plugins and docs are migrated over.


Files identified in the description:

None

If these files are incorrect, please update the `component name` section of the description or use the [component](https://github.com/ansible/ansibotmini#commands) bot command.

<!--- boilerplate: components_banner --->


example project to reproduce: 
```console
ansible-handlers-error/
├── ansible.cfg
├── playbook-broken.yml
├── playbook-working.yml
├── roles
│   └── foo
│       ├── handlers
│       │   └── main.yml
│       └── tasks
│           └── main.yml
└── test.sh

5 directories, 6 files
```

[ansible-handlers-error.zip](https://github.com/user-attachments/files/21199770/ansible-handlers-error.zip)

This is an expected change and was introduced in https://github.com/ansible/ansible/commit/0f4f05ebe4545297d870433d8f46abe62b1f728f

The implicit flush_handlers tasks now inherit play tags, and if the tags applied to the play are not selected, the implicit flush_handlers will not run.

But the handlers run if there are no play tags and some "other" tags are selected on the command line.

In that case, "implicit flush_handlers", should not have any tags assigned and thus not run.

I don't agree that this is an expected change. In the discussion in #83968 it was explicitly stated:
> This PR just fixes what is expected that when play is tagged and it is skipped on its tags then nothing from that play runs. Which isn't true in devel where we still run flush_handlers needlessly since nothing could possibly notify any handler. So all this is transparent to the user and they shouldn't have to know about any of this

The play in this reproducer is not being skipped, a handler is notified but not run, and so the change in behaviour is visible to the user and is an unintended bug.

cc @mkrizek 

all 'automatically genreated' tasks in a play should default to the 'always' tag, but if the play itself is tagged, they should inherit that tag, this is how gather_facts and role_specs work and I thought we had updated `meta` tasks to do same (x2 checking).

In general, sure. I think handler flushing has to be special, though, both because play tags allowing handlers to be lost would be incredibly surprising and because handlers themselves are special.

```yaml
- hosts: localhost
  become: false
  handlers:
    - name: tagged handler
      debug:
        msg: hello
      tags: bar
  tasks:
    - debug:
        msg: goodbye
      changed_when: true
      notify: tagged handler
      tags: foo
```
```text
$ ansible-playbook test.yml --tags foo

PLAY [localhost] ***************************************************************

TASK [debug] *******************************************************************
changed: [localhost] => 
    msg: goodbye

RUNNING HANDLER [tagged handler] ***********************************************
ok: [localhost] => 
    msg: hello
```

I can see this both ways, you are tagging the play, which includes it's handlers, but if the handlers come from a role, they should also be able to trigger with the role's tags. 

The problem comes when trying to make an exception for handlers when triggered by a task that does not share the role tag and the role tag is excluded. 

I'm not sure if handlers and 'flush_handlers' should obey tags at all at this point.
