ansible.builtin.copy reports changed=False even when it copies something for a specific dir structure
### Summary

When I used ansible.builtin.copy to copy directories, it reported changed=False even when it did copy the files.

This problem seems to only happen with a following directory structure, where it has a single subdirectory and a single file inside that subdirectory:
```
src/
└── dir1/
    └── file
```

This issue doesn't happen if there are more files / more directories.

I've verified that it happens with ssh and local connections. It also happens inside Ansible playbooks, and `ansible` command.

### Issue Type

Bug Report

### Component Name

ansible.builtin.copy

### Ansible Version

```console
$ ansible --version
ansible [core 2.18.9]
  config file = None
  configured module search path = ['/home/yuxiao.zeng/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /home/yuxiao.zeng/ansible-copy-issue/.venv/lib/python3.13/site-packages/ansible
  ansible collection location = /home/yuxiao.zeng/.ansible/collections:/usr/share/ansible/collections
  executable location = .venv/bin/ansible
  python version = 3.13.3 (main, Apr  9 2025, 04:03:52) [Clang 20.1.0 ] (/home/yuxiao.zeng/ansible-copy-issue/.venv/bin/python)
  jinja version = 3.1.6
  libyaml = True
```

### Configuration

```console
# if using a version older than ansible-core 2.12 you should omit the '-t all'
$ ansible-config dump --only-changed -t all
CONFIG_FILE() = None

GALAXY_SERVERS:
```

### OS / Environment

Control node: Ubuntu 22.04
Target node: Ubuntu 22.04 (same as control node)

### Steps to Reproduce

1. Inside a test directory, use the following command to create the source directory.
    ```bash
    mkdir -p src/dir1
    touch src/dir1/file
    ```
    It should result in the following directory structure with the command `tree -F .`.
    ```
    ./
    └── src/
        └── dir1/
            └── file
    ```

2. Execute the following ansible command to copy `src` to `dest`:
    ```bash
    ansible -m ansible.builtin.copy -a "src=src/ dest=$PWD/dest" -vvvv localhost
    ```

3. Check if files are copied using `tree -F .` command.

### Expected Results

I expected 2 to return "changed=True", and 3 to show the `dest/dir1/file1` to be copied with all directories created.

### Actual Results

The result of 3 is correct:

```console
./
├── dest/
│   └── dir1/
│       └── file
└── src/
    └── dir1/
        └── file
```


However, 2 returned changed=False. The following is the logs.

```console
ansible [core 2.18.9]
  config file = None
  configured module search path = ['/home/yuxiao.zeng/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /home/yuxiao.zeng/ansible-copy-issue/.venv/lib/python3.13/site-packages/ansible
  ansible collection location = /home/yuxiao.zeng/.ansible/collections:/usr/share/ansible/collections
  executable location = .venv/bin/ansible
  python version = 3.13.3 (main, Apr  9 2025, 04:03:52) [Clang 20.1.0 ] (/home/yuxiao.zeng/ansible-copy-issue/.venv/bin/python)
  jinja version = 3.1.6
  libyaml = True
No config file found; using defaults
setting up inventory plugins
Loading collection ansible.builtin from 
host_list declined parsing /etc/ansible/hosts as it did not pass its verify_file() method
Skipping due to inventory source not existing or not being readable by the current user
script declined parsing /etc/ansible/hosts as it did not pass its verify_file() method
auto declined parsing /etc/ansible/hosts as it did not pass its verify_file() method
Skipping due to inventory source not existing or not being readable by the current user
yaml declined parsing /etc/ansible/hosts as it did not pass its verify_file() method
Skipping due to inventory source not existing or not being readable by the current user
ini declined parsing /etc/ansible/hosts as it did not pass its verify_file() method
Skipping due to inventory source not existing or not being readable by the current user
toml declined parsing /etc/ansible/hosts as it did not pass its verify_file() method
[WARNING]: No inventory was parsed, only implicit localhost is available
Loading callback plugin minimal of type stdout, v2.0 from /home/yuxiao.zeng/ansible-copy-issue/.venv/lib/python3.13/site-packages/ansible/plugins/callback/minimal.py
Skipping callback 'default', as we already have a stdout callback.
Skipping callback 'minimal', as we already have a stdout callback.
Skipping callback 'oneline', as we already have a stdout callback.
<127.0.0.1> ESTABLISH LOCAL CONNECTION FOR USER: yuxiao.zeng
<127.0.0.1> EXEC /bin/sh -c 'echo ~yuxiao.zeng && sleep 0'
<127.0.0.1> EXEC /bin/sh -c '( umask 77 && mkdir -p "` echo /home/yuxiao.zeng/.ansible/tmp `"&& mkdir "` echo /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827 `" && echo ansible-tmp-1757383155.4423716-4134632-110586824360827="` echo /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827 `" ) && sleep 0'
Using module file /home/yuxiao.zeng/ansible-copy-issue/.venv/lib/python3.13/site-packages/ansible/modules/stat.py
<127.0.0.1> PUT /home/yuxiao.zeng/.ansible/tmp/ansible-local-41346299cvx9__j/tmp9iyt4lub TO /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/AnsiballZ_stat.py
<127.0.0.1> EXEC /bin/sh -c 'chmod u+rwx /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/ /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/AnsiballZ_stat.py && sleep 0'
<127.0.0.1> EXEC /bin/sh -c '/home/yuxiao.zeng/ansible-copy-issue/.venv/bin/python /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/AnsiballZ_stat.py && sleep 0'
<127.0.0.1> PUT /home/yuxiao.zeng/ansible-copy-issue/src/dir1/file TO /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/.source
<127.0.0.1> EXEC /bin/sh -c 'chmod u+rwx /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/ /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/.source && sleep 0'
Using module file /home/yuxiao.zeng/ansible-copy-issue/.venv/lib/python3.13/site-packages/ansible/modules/copy.py
<127.0.0.1> PUT /home/yuxiao.zeng/.ansible/tmp/ansible-local-41346299cvx9__j/tmpybs13ydr TO /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/AnsiballZ_copy.py
<127.0.0.1> EXEC /bin/sh -c 'chmod u+rwx /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/ /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/AnsiballZ_copy.py && sleep 0'
<127.0.0.1> EXEC /bin/sh -c '/home/yuxiao.zeng/ansible-copy-issue/.venv/bin/python /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/AnsiballZ_copy.py && sleep 0'
Using module file /home/yuxiao.zeng/ansible-copy-issue/.venv/lib/python3.13/site-packages/ansible/modules/file.py
<127.0.0.1> PUT /home/yuxiao.zeng/.ansible/tmp/ansible-local-41346299cvx9__j/tmpkxx9a2nv TO /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/AnsiballZ_file.py
<127.0.0.1> EXEC /bin/sh -c 'chmod u+rwx /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/ /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/AnsiballZ_file.py && sleep 0'
<127.0.0.1> EXEC /bin/sh -c '/home/yuxiao.zeng/ansible-copy-issue/.venv/bin/python /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/AnsiballZ_file.py && sleep 0'
<127.0.0.1> EXEC /bin/sh -c 'rm -f -r /home/yuxiao.zeng/.ansible/tmp/ansible-tmp-1757383155.4423716-4134632-110586824360827/ > /dev/null 2>&1 && sleep 0'
localhost | SUCCESS => {
    "changed": false,
    "dest": "/home/yuxiao.zeng/ansible-copy-issue/dest/dir1",
    "diff": {
        "after": {
            "path": "/home/yuxiao.zeng/ansible-copy-issue/dest/dir1"
        },
        "before": {
            "path": "/home/yuxiao.zeng/ansible-copy-issue/dest/dir1"
        }
    },
    "gid": 1000,
    "group": "yuxiao.zeng",
    "invocation": {
        "module_args": {
            "_diff_peek": null,
            "_original_basename": null,
            "access_time": null,
            "access_time_format": "%Y%m%d%H%M.%S",
            "attributes": null,
            "follow": true,
            "force": false,
            "group": null,
            "mode": null,
            "modification_time": null,
            "modification_time_format": "%Y%m%d%H%M.%S",
            "owner": null,
            "path": "/home/yuxiao.zeng/ansible-copy-issue/dest/dir1",
            "recurse": false,
            "selevel": null,
            "serole": null,
            "setype": null,
            "seuser": null,
            "src": null,
            "state": "directory",
            "unsafe_writes": false
        }
    },
    "mode": "0775",
    "owner": "yuxiao.zeng",
    "path": "/home/yuxiao.zeng/ansible-copy-issue/dest/dir1",
    "size": 4096,
    "state": "directory",
    "uid": 1000
}
```

### Code of Conduct

- [x] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `f13785e859408d15178392a60f4189b95acb2ffc`

## Hints

Files identified in the description:

* [`lib/ansible/modules/copy.py`](https://github.com/ansible/ansible/blob/devel/lib/ansible/modules/copy.py)
* [`lib/ansible/plugins/action/copy.py`](https://github.com/ansible/ansible/blob/devel/lib/ansible/plugins/action/copy.py)

If these files are incorrect, please update the `component name` section of the description or use the [component](https://github.com/ansible/ansibotmini#commands) bot command.

<!--- boilerplate: components_banner --->


Hi Ansible team, I would appreciate if you can have a look and prioritize this issue.

In our playbook, we have a step which copies files and triggers a command only when a change occurs. We have found that the command fails to execute when only one file is being copied, which unfortunately interrupts our automation workflow and necessitates a manual command execution. This issue has become quite a frequent annoyance and can be a significant blocker for us.

I see that @webknjaz has already been kind enough to spend some time reviewing PR #85834, which addresses this specific problem.

We would be extremely grateful if you could review and prioritize the merging of PR #85834 so that this fix can be included in the next release. Resolving this would greatly improve the reliability of our automation.

Please let me know if there's any change needed for the PR.

Here is an issue about this problem dating back to 2018 - #38938

@asg7443 Thanks for pointing out that!

@s-hertel it looks like you worked on a fix previously as well, so I guess you have some context. Could you have a look at my PR #85834?
