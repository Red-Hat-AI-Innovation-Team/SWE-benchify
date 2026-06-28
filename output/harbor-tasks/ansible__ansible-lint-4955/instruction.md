skip_list skips everything
<!--- Verify first that your issue is not already reported on GitHub -->
<!--- Also test if the latest release and main branch are affected too -->

##### Summary

Hi,

I would like to skip a specific tag completely (`var-naming[no-role-prefix]`). I have created the following `.ansible-lint` configuration

```yaml
---
skip_list:
  - var-naming[no-role-prefix]
```

But now no check is executed at all. Everything seems ok.

If i run ansible-lint without a `.ansible-lint` configuration file, i will get the following ouput

```
                       Rule Violation Summary                        
 count tag                        profile rule associated tags       
   307 var-naming[no-role-prefix] basic   idiom                      
     1 yaml[empty-lines]          basic   formatting, yaml           
     3 yaml[indentation]          basic   formatting, yaml           
     1 yaml[key-duplicates]       basic   formatting, yaml           
     1 risky-shell-pipe           safety  command-shell              
     7 no-changed-when            shared  command-shell, idempotency 

Failed: 320 failure(s), 0 warning(s) on 75 files. Last profile that met the validation criteria was 'min'.
```

If I skip one tag now, I would have expected the others to still appear. But with the above config I now get the following

```
Passed: 0 failure(s), 0 warning(s) on 1 files. Last profile that met the validation criteria was 'production'.
```

But I would still like to have the other messages because I would like to fix them. Just not the one which i want to skip.

Background. I have a collection `namespace.zabbix` and in it several roles (agent, server, proxy, ...). Now my variables have the structure `zabbix_ROLE_variable` (e.g. `zabbix_agent_port`), but ansible-lint complains about it. (That's ok, it's defined that way). But surely this one check can be ignored somehow.

##### Issue Type

- Bug Report

##### OS / ENVIRONMENT

<!--- Paste verbatim output between triple backticks -->

```console (paste below)
ansible-lint 6.22.1 using ansible-core:2.16.3 ansible-compat:4.1.11 ruamel-yaml:0.17.40 ruamel-yaml-clib:0.2.8
```

<!--- Provide all relevant information below, e.g. target OS versions, network
 device firmware, etc. -->

- ansible installation method: OS package (Archlinux)
- ansible-lint installation method: OS package (Archlinux)

##### STEPS TO REPRODUCE

<!--- Describe exactly how to reproduce the problem, using a minimal test case -->

Add a simple `.ansible-lint` configuration with `skip_list`

```yaml
---
skip_list:
  - var-naming[no-role-prefix]
```

<!--- Paste example playbooks or commands between triple backticks below -->

<!--- HINT: You can paste gist.github.com links for larger files -->

##### Desired Behavior

<!--- Describe what you expected to happen when running the steps above -->

Only the one check is ignored

##### Actual Behavior

<!--- Describe what happened. If possible run with extra verbosity (-vvvv) -->

Everything is ignored

<!--- Paste verbatim command output between triple backticks -->

[minimum complete verifiable example]: http://stackoverflow.com/help/mcve


yaml checks are skipped
<!--- Verify first that your issue is not already reported on GitHub -->
<!--- Also test if the latest release and main branch are affected too -->

##### Summary
adding any yaml[] in .ansible-list cause all yaml checks to be skipped

##### Issue Type

.ansible-lint parsing issue

##### OS / ENVIRONMENT

<!--- Paste verbatim output between triple backticks -->

```console (paste below)
ansible-lint --version
ansible-lint 26.1.1 using ansible-core:2.20.2 ansible-compat:25.12.0 ruamel-yaml:0.19.1 ruamel-yaml-clib:0.2.15
```

<!--- Provide all relevant information below, e.g. target OS versions, network
 device firmware, etc. -->

- ansible installation method: pip3.12
- ansible-lint installation method: pip

##### STEPS TO REPRODUCE

<!--- Describe exactly how to reproduce the problem, using a minimal test case -->

<!--- Paste example playbooks or commands between triple backticks below -->

```console (paste below)
(ansible_python_env2) mhanafi@ARLWL2024120379:~/GITCHECKOUT/ansible_push$ cat .ansible-lint
---
skip_list:
  - ignore-errors
  - meta-no-info # meta/main.yml should contain relevant info
  - no-handler
  - risky-file-permissions
  - var-naming
  - command-instead-of-module # Using command rather than module
  - command-instead-of-shell # Use shell only when shell functionality is required
  - meta-incorrect # meta/main.yml default values should be changed
  - no-changed-when # Commands should not change things if nothing needs doing
  - no-handler # Tasks that run when changed should likely be handlers
  #- deprecated-command-syntax
  - package-latest # Package installs should not use latest
  - risky-shell-pipe
  - empty-string-compare

warn_list: # or 'skip_list' to silence them completely
  - deprecated-command-syntax # Using command rather than an argument to e.g. file
  - literal-compare # Don't compare to literal True/False
  - no-jinja-when # No Jinja2 in when
  - var-spacing # Variables should have spaces before and after:  {{ var_name }}
  - risky-shell-pipe # Shells that use pipes should set the pipefail option
  - role-name # Role name {0} does not match ``^[a-z][a-z0-9_]+$`` pattern

exclude_paths:
  - ".gitlab-ci.yml"
  - "collections"
(ansible_python_env2) mhanafi@ARLWL2024120379:~/GITCHECKOUT/ansible_push$ ansible-lint --profile production -c .ansible-lint test.yml
WARNING  Listing 1 violation(s) that are fatal
yaml[colons]: Too many spaces before colon
test.yml:6

Read documentation for instructions on how to ignore specific rule violations.

# Rule Violation Summary

  1 yaml profile:basic tags:formatting,yaml

Failed: 1 failure(s), 0 warning(s) in 1 files processed of 1 encountered. Profile 'production' was required, but 'min' profile passed.
(ansible_python_env2) mhanafi@ARLWL2024120379:~/GITCHECKOUT/ansible_push$ cat .ansible-lint
---
skip_list:
  - ignore-errors
  - meta-no-info # meta/main.yml should contain relevant info
  - no-handler
  - risky-file-permissions
  - var-naming
  - command-instead-of-module # Using command rather than module
  - command-instead-of-shell # Use shell only when shell functionality is required
  - meta-incorrect # meta/main.yml default values should be changed
  - no-changed-when # Commands should not change things if nothing needs doing
  - no-handler # Tasks that run when changed should likely be handlers
  #- deprecated-command-syntax
  - package-latest # Package installs should not use latest
  - risky-shell-pipe
  - empty-string-compare
  - yaml[trailing-spaces] #

warn_list: # or 'skip_list' to silence them completely
  - deprecated-command-syntax # Using command rather than an argument to e.g. file
  - literal-compare # Don't compare to literal True/False
  - no-jinja-when # No Jinja2 in when
  - var-spacing # Variables should have spaces before and after:  {{ var_name }}
  - risky-shell-pipe # Shells that use pipes should set the pipefail option
  - role-name # Role name {0} does not match ``^[a-z][a-z0-9_]+$`` pattern

exclude_paths:
  - ".gitlab-ci.yml"
  - "collections"
(ansible_python_env2) mhanafi@ARLWL2024120379:~/GITCHECKOUT/ansible_push$ ansible-lint --profile production -c .ansible-lint test.yml

Passed: 0 failure(s), 0 warning(s) in 1 files processed of 1 encountered. Profile 'production' was required, and it passed.
```



[minimum complete verifiable example]: http://stackoverflow.com/help/mcve

**Repository:** `ansible/ansible-lint`
**Base commit:** `c3df6882119368c8161bffbac279a3a040c5aafd`

## Hints

Please link to a minimal repository that reproduced the bug.

I have same problems
`- yaml[trailing-spaces]`
leave only 
`- yaml[truthy]: Truthy value should be one of`
everything else for yaml is lost


If you specify this rule, then the number of warnings is 93, if you remove it, then more than 1000. Moreover, if you specify not through .ansible-lint, but through .yamllint.yml, then exactly the desired rule is excluded
