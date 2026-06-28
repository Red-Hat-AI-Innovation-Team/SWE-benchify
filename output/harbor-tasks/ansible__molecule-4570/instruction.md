podman ansible-native example does not work with `list` or `login`
### Prerequisites

- [x] This was not already reported in the past (duplicate check)
- [x] It does reproduce it with code from main branch (latest unreleased version)
- [x] I include a minimal example for reproducing the bug
- [x] The bug is not trivial, as for those a direct pull-request is preferred
- [x] Running `pip check` does not report any conflicts
- [x] I was able to reproduce the issue on a different machine
- [x] The issue is not specific to any driver other than 'default' one

### Environment

OS: linux, fedora 42

```shell-session
$ molecule --version
molecule 25.9.1.dev6 using python 3.13 
    ansible:2.19.2
    default:25.9.1.dev6 from molecule
```

### What happened

The updated podman example to leverage the `ansible-native` approach does not support all molecule commands.

Namely, `molecule list` and `molecule login` are broken with it.

I am not sure if that is expected, and more work needs to be done to fix it, in which case, should we update the example? Or if it should work out of the box, in which case it is not

I might be able to attempt a fix if I get guidance on how this should be fixed.

Thanks!

### Reproducing example

Copy the example somewhere:

```
mkdir -p reproduction/molecule/default
cp -r tests/fixtures/integration/test_command/molecule/podman/* reproduction/molecule/default/
cd reproduction/
molecule create
```

Then run:

```
molecule list
```

Expected: Seeing one created instance
Instead, you get:

```
INFO     default ➜ list: Executing
INFO     default ➜ list: Executed: Successful
                ╷             ╷                  ╷               ╷         ╷            
  Instance Name │ Driver Name │ Provisioner Name │ Scenario Name │ Created │ Converged  
╶───────────────┼─────────────┼──────────────────┼───────────────┼─────────┼───────────╴
                ╵             ╵                  ╵               ╵         ╵         
```

Similarly, for `molecule login`, instead of a shell, you get:

```
INFO     default ➜ login: Executing
ERROR    There are 0 running hosts. Please specify which with --host.

Available hosts:
```

Adding the following in the molecule.yml file fixes the list:

```yaml
platforms:
  - name: molecule-fedora
```

But then the login fails with:

```
WARNING  default ➜ config: The scenario config file ('/home/user/molecule/tests/fixtures/integration/test_command/molecule/test/molecule/default/molecule.yml') has been modified since the scenario was created. If recent changes are important, reset the scenario with 'molecule destroy' to clean up created items or 'molecule reset' to clear current configuration.
INFO     default ➜ login: Executing
ERROR    default ➜ login: Executed: Failed
Traceback (most recent call last):
  File "/home/user/molecule/.venv/bin/molecule", line 8, in <module>
    sys.exit(main())
             ~~~~^^
  File "/home/user/molecule/.venv/lib64/python3.13/site-packages/click/core.py", line 1462, in __call__
    return self.main(*args, **kwargs)
           ~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "/home/user/molecule/.venv/lib64/python3.13/site-packages/click/core.py", line 1383, in main
    rv = self.invoke(ctx)
  File "/home/user/molecule/.venv/lib64/python3.13/site-packages/click/core.py", line 1850, in invoke
    return _process_result(sub_ctx.command.invoke(sub_ctx))
                           ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^
  File "/home/user/molecule/.venv/lib64/python3.13/site-packages/click/core.py", line 1246, in invoke
    return ctx.invoke(self.callback, **ctx.params)
           ~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/user/molecule/.venv/lib64/python3.13/site-packages/click/core.py", line 814, in invoke
    return callback(*args, **kwargs)
  File "/home/user/molecule/src/molecule/click_cfg.py", line 583, in wrapper
    return func(*args, **kwargs)
  File "/home/user/molecule/.venv/lib64/python3.13/site-packages/click/decorators.py", line 34, in new_func
    return f(get_current_context(), *args, **kwargs)
  File "/home/user/molecule/src/molecule/click_cfg.py", line 418, in wrapper
    return func(ctx)
  File "/home/user/molecule/src/molecule/command/login.py", line 141, in login
    base.execute_subcommand(scenario.config, subcommand)
    ~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/user/molecule/src/molecule/command/base.py", line 358, in execute_subcommand
    return command(current_config).execute(args)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/home/user/molecule/src/molecule/logger.py", line 414, in wrapper
    rt = func(*args, **kwargs)
  File "/home/user/molecule/src/molecule/command/login.py", line 67, in execute
    self._get_login(hostname)
    ~~~~~~~~~~~~~~~^^^^^^^^^^
  File "/home/user/molecule/src/molecule/command/login.py", line 107, in _get_login
    login_options = self._config.driver.login_options(hostname)
  File "/home/user/molecule/src/molecule/driver/delegated.py", line 131, in login_options
    return util.merge_dicts(d, self._get_instance_config(instance_name))
                               ~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^
  File "/home/user/molecule/src/molecule/driver/delegated.py", line 198, in _get_instance_config
    instance_config_dict = util.safe_load_file(self._config.driver.instance_config)
  File "/home/user/molecule/src/molecule/util.py", line 302, in safe_load_file
    with filename.open() as stream:
         ~~~~~~~~~~~~~^^
  File "/usr/lib64/python3.13/pathlib/_local.py", line 537, in open
    return io.open(self, mode, buffering, encoding, errors, newline)
           ~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
FileNotFoundError: [Errno 2] No such file or directory: '/home/user/molecule/tests/fixtures/integration/test_command/molecule/test/.ansible/tmp/molecule.n4bQ.default/instance_config.yml'
```

**Repository:** `ansible/molecule`
**Base commit:** `1cbba7713710239734d6889358e603f4a02acf32`

## Hints

We have replicated this bug. Thanks for reporting! We will add this to our backlog.
