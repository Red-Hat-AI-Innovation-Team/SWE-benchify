'format' option missing from configuration file schema
Running with ansible-lint 26.1.0 which was released on 8-Jan-2026.

```
$ tox -e ansible-lint
ansible-lint: install_deps> python -I -m pip install -r /builds/widget-checker/requirements.txt -r /builds/widget-checker/test-requirements.txt
ansible-lint: freeze> python -m pip freeze --all
ansible-lint: ansible==13.2.0,ansible-compat==25.12.0,ansible-core==2.20.1,ansible-lint==26.1.0,ansible-pylibssh==1.3.0,attrs==25.4.0,black==25.12.0,bracex==2.6,certifi==2026.1.4,cffi==2.0.0,charset-normalizer==3.4.4,click==8.3.1,cryptography==46.0.3,distro==1.9.0,dnspython==2.8.0,filelock==3.20.2,flake8==7.3.0,idna==3.11,isort==7.0.0,Jinja2==3.1.6,jmespath==1.0.1,jsonschema==4.26.0,jsonschema-specifications==2025.9.1,librt==0.7.7,MarkupSafe==3.0.3,mccabe==0.7.0,mypy==1.19.1,mypy_extensions==1.1.0,netaddr==1.3.0,packaging==25.0,pathspec==0.12.1,pip==25.3,platformdirs==4.5.1,pycodestyle==2.14.0,pycparser==2.23,pyflakes==3.4.0,pyspnego==0.12.0,pytokens==0.3.0,pywinrm==0.5.0,PyYAML==6.0.3,referencing==0.37.0,requests==2.32.5,requests_ntlm==1.3.0,resolvelib==1.2.1,rpds-py==0.30.0,ruamel.yaml==0.19.1,subprocess-tee==0.4.2,typing_extensions==4.15.0,urllib3==2.6.3,wcmatch==10.1,xmltodict==1.0.2,yamllint==1.37.1
ansible-lint: commands[0]> ansible-lint -vvv /builds/widget-checker/playbooks/site.yml
[WARNING]: Deprecation warnings can be disabled by setting `deprecation_warnings=False` in ansible.cfg.
[DEPRECATION WARNING]: DEFAULT_MANAGED_STR option. Reason: The `ansible_managed` variable can be set just like any other variable, or a different variable can be used.
Alternatives: Set the `ansible_managed` variable, or use any custom variable in templates. This feature will be removed from ansible-core version 2.23.
ansible-lint: exit 3 (0.47 seconds) /builds/widget-checker> ansible-lint -vvv /builds/widget-checker/playbooks/site.yml pid=132
  ansible-lint: FAIL code 3 (66.99=setup[66.52]+cmd[0.47] seconds)
  evaluation failed :( (67.03 seconds)
```

If I use 25.12.2 it does not fail and completes with success.

Are there some flags I can use to have it show more details on why it failed? If it is because of the deprecation warning I would expect it would say that it failed because of the deprecation warning and say what rule that violated.

Unexpected/inconsistent log redirection behaviour in case of bad/malformed .ansible-lint file
##### Summary

The behaviour of ansible-lint is unexpectedly and inconsistently affected by the presence of the following snippet in the `ansible.cfg`:

```
[defaults]
log_path = /path/to/log-file
```

when `.ansible-lint` file is bad/malformed or otherwise causing errors with ansible-lint execution, for example:

* `.ansible-lint` file contains non-existing (e.g. deprecated and removed) options
* `.ansible-lint` file exists and is empty

And results in the user being unable (or having harder time) understanding/debugging the issue they are dealing with.

##### Issue Type

- Bug Report

##### OS / ENVIRONMENT

<!--- Paste verbatim output between triple backticks -->

```console (paste below)
ansible-lint --version

ansible-lint 26.4.0 using ansible-core:2.20.5 ansible-compat:26.3.0 ruamel-yaml:0.19.1 ruamel-yaml-clib:None
```

<!--- Provide all relevant information below, e.g. target OS versions, network
 device firmware, etc. -->

- ansible installation method: pip
- ansible-lint installation method: pip

##### STEPS TO REPRODUCE

1. in an empty folder, create incorrect `.ansible-lint` file (e.g. empty file, or with contents as below):

```
parseable: true
```

2. create the following `ansible.cfg` file:

```
[defaults]
log_path = /tmp/ansible-bug.log
```

3. run `ansible-lint` with no options or with options such as `-vv` or `--version`.

##### Desired Behavior

1. `ansible-lint --version` should print version and exit regardless of the correctness of `.ansible-lint` file -- if I didn't figure out the nature of issue before reporting it, it would've prevented me from even getting ansible-lint version.
2. `ansible-lint` (with any options) should print errors to console regardless of what's in `ansible.cfg` file.
3. the logs of ansible-lint are not redirected to the log file specified in `ansible.cfg` regardless whether `.ansible-lint` file is correct or not

##### Actual Behavior

1. `ansible-lint --version` prints version and exits only if `.ansible-lint` file is correct; otherwise it prints an error and exits without printing version information
2. `ansible-lint` (with any options) prints errors to console only if there's no log file specified in `ansible.cfg` file.
3.  error logs of ansible-lint are redirected to the log file specified in `ansible.cfg` if `.ansible-lint` file is incorrect, but regular logs are not redirected if `.ansible-lint` file is correct

**example 1**

`.ansible-lint`

```
parseable: true
```

`ansible.cfg`

```
[defaults]
log_path = /tmp/ansible-bug.log
```

Results after executing `ansible-lint` with various options from the directory where the files are:

* `ansible-lint` -> no stdout and no stderr (no output), return code 3
* `ansible-lint -vv` -> no stdout and no stderr (no output), return code 3
* `ansible-lint --version` -> no stdout and no stderr (no output), return code 3
* `ansible-lint --help` -> regular help message

Then, I created an empty subfolder in my example folder, and executed `ansible-lint` (with no options) from there. The output was:

```
Invalid configuration file /path/to/my/example/.ansible-lint. $ Additional properties are not allowed ('parseable' was unexpected). See https://docs.ansible.com/projects/lint/configuring/
```

So ansible-lint correctly used .ansible-lint file from parent folder, but didn't use the ansible.cfg to redirect its error logs.

---

**example 2**

`.ansible-lint` empty

`ansible.cfg`

```
[defaults]
log_path = /tmp/ansible-bug.log
```

Results after executing `ansible-lint` with various options from the directory where the files are:

* `ansible-lint` -> no stdout and no stderr (no output), return code 3
* `ansible-lint -vv` -> no stdout and no stderr (no output), return code 3
* `ansible-lint --version` -> no stdout and no stderr (no output), return code 3
* `ansible-lint --help` -> regular help message

Then, I created an empty subfolder in my example folder, and executed `ansible-lint` (with no options) from there. The output was:

```
Invalid configuration file /path/to/my/example/.ansible-lint. $ None is not of type 'object'. See https://docs.ansible.com/projects/lint/configuring/
```

So ansible-lint correctly used .ansible-lint file from parent folder, but didn't use the ansible.cfg to redirect its error logs.

---

**example 3**

`.ansible-lint`

```
profile: min
```

`ansible.cfg`

```
[defaults]
log_path = /tmp/ansible-bug.log
```

Results after executing `ansible-lint` with various options from the directory where the files are:

* `ansible-lint` -> return code 0, output below

```
Passed: 0 failure(s), 0 warning(s) in 1 files processed of 2 encountered. Profile 'min' was required, but 'production' profile passed.
```

* `ansible-lint -vv` -> return code 0, output looks as expected (but is very long, so not attaching here)
* `ansible-lint --version` -> return code 0, output looks as expected
* `ansible-lint --help` -> regular help message

**Repository:** `ansible/ansible-lint`
**Base commit:** `f1af0edb820b2855fb03025bbf9490a88d7d14e7`

## Hints

Hi @JohnVillalovos, I cannot reproduce this. Can you provide more details about your tox config, playbook contents, and .ansible-lint config files (if any)?
Can you also try running ansible-lint directly with `-vvv` on your playbook without using tox?

Thank you @alisonlhart 

Here is a reproducer. In older versions output would be shown in stdout/stderr.

`playbook.yml`
```
---
- name: Test playbook
  hosts: all
  tasks:
    - name: Debug
      ansible.builtin.debug:
        msg: hello
```

`.ansible-lint`
```
parseable: true
```

`cat ansible.cfg`
```
[defaults]
log_path = /var/log/ansible.log
```


```
$ ansible-lint -vvv playbook.yml
<NO OUTPUT>
```

I didn't realize this was showing up in the log file.
```
$ cat /var/log/ansible.log
2026-01-09 18:06:17,804 p=479 u=root n=ansiblelint.cli ERROR| Invalid configuration file /root/test/.ansible-lint. $ Additional properties are not allowed ('parseable' was unexpected). See https://docs.ansible.com/projects/lint/configuring/
```

Thanks @JohnVillalovos ! This solves it. The parseable option was removed as a config file option in 26.1.0 and deprecated as a CLI option. You can use the `--format=pep8` CLI option (1-1 the same behavior) at runtime to get around this, since 'format' isn't in our configuration file schema as an option. 

Format was not included in configuration by design because we did not want to affect the output format when tool was running from the cli in different directories. Basically the only way to configure output format is via cli args. Parseable was there for historical reasons.

I hope this helps. I will not close the issue yet as I want to allow others to send feedback and see if maybe there is a genuine use case which really requires it inside config.

I'll be honest, my main issue is not about parseable or format. I personally don't care about that. What I care about is that there was no indication of the error sent to STDOUT/STDERR. It made debugging a bit difficult. Thanks.

Hi, I'd like to work on this! I've been contributing to LiteLLM recently and would love to help improve the error reporting in ansible-lint to ensure configuration errors are clearly surfaced to stderr.

The bug #4898 is slightly related in that the user had problem debugging his issue due to the log redirection, specific comment: https://github.com/ansible/ansible-lint/issues/4898#issuecomment-3730030062
