molecule.exception when trying to login in to a non-existing host
### Prerequisites

- [x] This was not already reported in the past (duplicate check)
- [x] It does reproduce it with code from main branch (latest unreleased version)
- [x] I include a minimal example for reproducing the bug
- [x] The bug is not trivial, as for those a direct pull-request is preferred
- [x] Running `pip check` does not report any conflicts
- [x] I was able to reproduce the issue on a different machine
- [x] The issue is not specific to any driver other than 'default' one

### Environment

```sh
$ molecule --version
[WARNING]: You are running the development version of Ansible. You should only run Ansible from "devel" if you are modifying the Ansible engine, or trying out features under development. This is a rapidly changing source of code and can become unstable at any point.
molecule 25.7.1.dev39 using python 3.13
    ansible:2.20.0.dev0
    openstack:25.8.12 from molecule_plugins requiring collections: openstack.cloud>=2.1.0
    default:25.7.1.dev39 from molecule
    ec2:25.8.12 from molecule_plugins
    vagrant:25.8.12 from molecule_plugins
    gce:25.8.12 from molecule_plugins requiring collections: google.cloud>=1.0.2 community.crypto>=1.8.0
    containers:25.8.12 from molecule_plugins requiring collections: ansible.posix>=1.3.0 community.docker>=1.9.1 containers.podman>=1.8.1
    podman:25.8.12 from molecule_plugins requiring collections: containers.podman>=1.7.0 ansible.posix>=1.3.0
    azure:25.8.12 from molecule_plugins
    docker:25.8.12 from molecule_plugins requiring collections: community.docker>=3.10.2 ansible.posix>=1.4.0
```

### What happened

```sh
$ molecule login --host almalinux9
[WARNING]: You are running the development version of Ansible. You should only run Ansible from "devel" if you are modifying the Ansible engine, or trying out features under development. This is a rapidly changing source of code and can become unstable at any point.
WARNING  Driver vagrant does not provide a schema.
WARNING  Driver docker does not provide a schema.
WARNING  Driver vagrant does not provide a schema.
WARNING  Driver vagrant does not provide a schema.
WARNING  Driver vagrant does not provide a schema.
WARNING  Driver vagrant does not provide a schema.
WARNING  Driver vagrant does not provide a schema.
INFO     default ➜ login: Executing
CRITICAL There are no hosts that match 'almalinux9'.  You can only login to valid hosts.
ERROR    default ➜ login: Executed: Failed
Traceback (most recent call last):
  File "[...]/venvs/ansible-upstream/bin/molecule", line 10, in <module>
    sys.exit(main())
             ~~~~^^
  File "[...]/venvs/ansible-upstream/lib/python3.13/site-packages/click/core.py", line 1442, in __call__
    return self.main(*args, **kwargs)
           ~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "[...]/venvs/ansible-upstream/lib/python3.13/site-packages/click/core.py", line 1363, in main
    rv = self.invoke(ctx)
  File "[...]/venvs/ansible-upstream/lib/python3.13/site-packages/click/core.py", line 1830, in invoke
    return _process_result(sub_ctx.command.invoke(sub_ctx))
                           ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^
  File "[...]/venvs/ansible-upstream/lib/python3.13/site-packages/click/core.py", line 1226, in invoke
    return ctx.invoke(self.callback, **ctx.params)
           ~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "[...]/venvs/ansible-upstream/lib/python3.13/site-packages/click/core.py", line 794, in invoke
    return callback(*args, **kwargs)
  File "[...]/venvs/ansible-upstream/lib/python3.13/site-packages/molecule/click_cfg.py", line 583, in wrapper
    return func(*args, **kwargs)
  File "[...]/venvs/ansible-upstream/lib/python3.13/site-packages/click/decorators.py", line 34, in new_func
    return f(get_current_context(), *args, **kwargs)
  File "[...]/venvs/ansible-upstream/lib/python3.13/site-packages/molecule/click_cfg.py", line 418, in wrapper
    return func(ctx)
  File "[...]/venvs/ansible-upstream/lib/python3.13/site-packages/molecule/command/login.py", line 138, in login
    base.execute_subcommand(scenario.config, subcommand)
    ~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "[...]/venvs/ansible-upstream/lib/python3.13/site-packages/molecule/command/base.py", line 363, in execute_subcommand
    return command(current_config).execute(args)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "[...]/venvs/ansible-upstream/lib/python3.13/site-packages/molecule/logger.py", line 414, in wrapper
    rt = func(*args, **kwargs)
  File "[...]/venvs/ansible-upstream/lib/python3.13/site-packages/molecule/command/login.py", line 66, in execute
    hostname = self._get_hostname(hosts)
  File "[...]/venvs/ansible-upstream/lib/python3.13/site-packages/molecule/command/login.py", line 85, in _get_hostname
    raise MoleculeError(msg)
molecule.exceptions.MoleculeError
```


### Reproducing example

```yml
Molecule configuration https://github.com/konstruktoid/ansible-role-hardening/tree/master/molecule/default using https://github.com/konstruktoid/ansible-role-hardening/blob/master/requirements-upstream.txt
```

**Repository:** `ansible/molecule`
**Base commit:** `e5e165a6c94d58433d76282dee7df25a118b922f`

## Hints

TY.  I think we can move the exception details into debug only.
