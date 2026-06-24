Parent `tasks` directory anywhere above project_dir prevents kind discovery

##### Summary

Putting an ansible playbook anywhere under a parent directory named `tasks` causes all .yaml files to fail with schema interpretation errors, even when the playbook is using standard file locations.

e.g. `~/Development/tasks/JIRA-1234/my-playbook`

##### Issue Type

- Bug Report

##### OS / ENVIRONMENT

```console
ansible-lint 25.8.2 using ansible-core:2.19.2 ansible-compat:25.8.1 ruamel-yaml:0.18.15 ruamel-yaml-clib:0.2.12
```

macOS 15.6.1; ansible-lint 25.8.2 installed via OS package (brew); ansible not installed.

##### STEPS TO REPRODUCE

Check out or download any ansible playbook containing resources other than tasks. Name your directory `project-dir`.

`cd project-dir; ansible-lint` Verify that ansible-lint runs cleanly.

`cd .. && mkdir -p tasks/foo/bar && mv project-dir tasks/foo/bar/.`

`cd tasks/foo/bar/project-dir ; ansible-lint` will fail with the following error on every .yaml file:

```
schema[tasks]: $ {'dependencies': [{'role': 'sys'}]} is not of type 'array', 'null'
site.yml:1  Returned errors will not include exact line numbers, but they will mention
the schema name being used as a tag, like ``schema[playbook]``,
``schema[tasks]``.

This rule is not skippable and stops further processing of the file.

If incorrect schema was picked, you might want to either:

* move the file to standard location, so its file is detected correctly.
* use ``kinds:`` option in linter config to help it pick correct file type.
[/]
```

##### Desired Behavior

ansible-lint should not fail if a user has a top-level directory named `tasks` containing their source files organized by project.

##### Actual Behavior

Minimal reproducible playbook as base64 .tar.gz file:
```
H4sICMOkwGgAA21pbmltYWwudGFyAO2bS2/bOBCAffavGLh7SLCQo7cAA7lsUaB7KBps9lYUAi1R
NjeU6BWpNE7R/15Ssgw/krqOZXWxmQ9BbD0oDTmc4XBI56xgOeFXgzNia6IgaD7DqP60Xb/5bBg4
gR3ajquvhwPbcTzfG0BwTqFaKqlICTD4JxPLH92nb8uyPgTql3ylf8kUHS9zfo53GAWHvv+s/h3f
3dG/Z7vRAOxzCLPLK9e/ZVlDCwqS0wl8aPoCTKsZpDQXhVQlUUwUQ4C5kEpOgIuEcPNdnyoFp3Ki
vwBY9cEE5FLWxwCKzGRz/KtriPyI1v5rZZ5pFPh5/+9EYWBr+3f9MED/3wfb+tf2eoY+8JP6Dzyt
fDeo/b/nOKj/PtjXvyLyrttecET85wSeo/Xv+y7qvxee07+kypJzyrmViCJjs1NiwwPxn+uEbfxn
h17kDmzX9pwQ478+2Iz/bqmCWufQ6Lxqoj/IGKdwT0pGprqT6ABvqsPAuzbyO6YsXEyJnF+uYkRS
SKbPjqcV44oVY93n4owkarK6DiZ+jBelMA+ZwOjr17ZITIv78fuPH97Bt29X49Udo61iZRIfKGZE
KZO21Jc5LSbrGytJy7ipD5N7gpZ0Rh8uRuPfr8wzfhtdDl/UFo/dN8XjC9vi8fSmeDyhJTLWfVOk
VZ4v4xe2R1P41CYx1dprk5tGoqYN6APT86pnal7LuBY8pVI1Em/UXwu7UTVFlH6BElUyX5/MRWoq
ahzwaFuQv5ITZVg145Ey/GqPh2zy3PivTysrmdPk7vSs0KH8j+sGO/Ff5IQOjv99sDn+vzXqhqWo
Svjj3VvjCi9klYpLWBApv4gyHe77h0TkOSnSCdBkLmD0dDnt/cuSJmps/MSU6jLGRZQV1YfJnBQz
msaNh80IlxRdRH88Z/850crtKB98yP69jfyPH+l5ohPq+SLafx9s2v/oz3whSgXG9zPCzRivaA46
AKsWUI8FcvSEC2B1qbjuNxPYHjj2nv1UNFiXPPzkp6ak6CpOpLX/8artLc4K1fE7Dtm/DgDW6z9+
6Jn8X+Tg+N8Lxv7lHVvEnJnQ/tNntKhXRWv/retNslnn7zi8/hvu5v99H/N/vfAppRmpuJKfh6y4
p4US5fJ6fLX+Xg+yJpqPM05m8tp6D9btMCGcT4mOB2JamBROCtfrwXshJHtoc3LN2I0+5T/L7vh/
jiXgI9Z/bLeO/z3bw/WfXtjTv0ntd/yOg/Hfvv7DyEX/3wd7+j/DRpBj7N8Ojf59J3DR/vtgT/+5
SKuOe8Bx+g/r9f8oQv33wZ7+E8E5TUxeprM+cLz9B3oCgPrvg3X+l/5bsZLmOuqXXe8DPjj+h8E6
/+u4tf8Pbcz/9oLJ/2yYvFnqtdZTuUoxLrfO1JM7nM79f2jtf2vC3/E7Dtm/50Z1/ieIHMdv9v85
+jLafw8Y+38DN5wSSSEVUAhltmuwbAlqzmS9Q2RIOJ+sfwNQ7+pY/w5gsr1vJE5EUTS+ZPVjgZ3r
i6WaiyJmhaLloqT6//YunAUny6kQd6sbzd4SeAN/G1H0X0FpSlPIRAk5ST7ewk1z1z0tpVlJIqke
xkiyRA+FIAiCIAiCIAiCIAiCIAiCIAiCvE6+A+K3x5YAUAAA
```
Output of `ansible-lint -vvvv --offline --nocolor 2>&1`:
```
DEBUG    Logging initialized to level 10
INFO     Identified / as project root due file system root.
DEBUG    Options: Options(_skip_ansible_syntax_check=False, cache_dir=PosixPath('/var/folders/22/9fk7dmyx52l2tzr0ssrnyrhh0000gq/T/.ansible-0aaa'), colored=False, configured=True, cwd=PosixPath('/Users/jfoy/src/coretech/tasks/foo/bar'), display_relative_path=True, exclude_paths=['.cache', '.git', '.hg', '.svn', '.tox'], format=None, lintables=[], list_rules=False, list_tags=False, write_list=[], write_exclude_list=[], parseable=False, quiet=0, rulesdirs=[PosixPath('/opt/homebrew/Cellar/ansible-lint/25.8.2_1/libexec/lib/python3.13/site-packages/ansiblelint/rules')], skip_list=[], tags=[], verbosity=4, warn_list=['experimental', 'jinja[spacing]', 'fqcn[deep]'], mock_filters=[], mock_modules=[], mock_roles=[], loop_var_prefix=None, only_builtins_allow_collections=[], only_builtins_allow_modules=[], var_naming_pattern=None, offline=True, project_dir='/', extra_vars=None, enable_list=[], skip_action_validation=True, strict=False, rules={}, profile=None, task_name_prefix='{stem} | ', sarif_file=None, config_file=None, generate_ignore=False, rulesdir=[], use_default_rules=False, version=False, list_profiles=False, ignore_file=None, yamllint_file=None, max_tasks=100, max_block_depth=20, supported_ansible_also=[])[/]
DEBUG    CWD: /Users/jfoy/src/coretech/tasks/foo/bar
WARNING  Project directory /.ansible cannot be used for caching as it is not writable.
WARNING  Using unique temporary directory /var/folders/22/9fk7dmyx52l2tzr0ssrnyrhh0000gq/T/.ansible-0aaa for caching.
DEBUG    Logging initialized to level 10
INFO     Collection paths was patched to include extra directories /Users/jfoy/.ansible/collections,/usr/share/ansible/collections,/opt/homebrew/opt/python@3.13/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages,/opt/homebrew/lib/python3.13/site-packages,/opt/homebrew/Cellar/ansible-lint/25.8.2_1/libexec/lib/python3.13/site-packages
DEBUG    Effective yamllint rules used: {'anchors': {'level': 'error', 'forbid-undeclared-aliases': True, 'forbid-duplicated-anchors': False, 'forbid-unused-anchors': False}, 'braces': {'level': 'error', 'forbid': False, 'min-spaces-inside': 0, 'max-spaces-inside': 1, 'min-spaces-inside-empty': -1, 'max-spaces-inside-empty': -1}, 'brackets': {'level': 'error', 'forbid': False, 'min-spaces-inside': 0, 'max-spaces-inside': 0, 'min-spaces-inside-empty': -1, 'max-spaces-inside-empty': -1}, 'colons': {'level': 'error', 'max-spaces-before': 0, 'max-spaces-after': 1}, 'commas': {'level': 'error', 'max-spaces-before': 0, 'min-spaces-after': 1, 'max-spaces-after': 1}, 'comments': {'level': 'warning', 'require-starting-space': True, 'ignore-shebangs': True, 'min-spaces-from-content': 1}, 'comments-indentation': False, 'document-end': False, 'document-start': False, 'empty-lines': {'level': 'error', 'max': 2, 'max-start': 0, 'max-end': 0}, 'empty-values': False, 'float-values': False, 'hyphens': {'level': 'error', 'max-spaces-after': 1}, 'indentation': {'level': 'error', 'spaces': 'consistent', 'indent-sequences': True, 'check-multi-line-strings': False}, 'key-duplicates': {'level': 'error', 'forbid-duplicated-merge-keys': False}, 'key-ordering': False, 'line-length': {'level': 'error', 'max': 160, 'allow-non-breakable-words': True, 'allow-non-breakable-inline-mappings': False}, 'new-line-at-end-of-file': {'level': 'error'}, 'new-lines': {'level': 'error', 'type': 'unix'}, 'octal-values': {'forbid-implicit-octal': True, 'forbid-explicit-octal': True, 'level': 'error'}, 'quoted-strings': False, 'trailing-spaces': {'level': 'error'}, 'truthy': {'level': 'warning', 'allowed-values': ['true', 'false'], 'check-keys': True}}
INFO     Set ANSIBLE_LIBRARY=/Users/jfoy/src/coretech/tasks/foo/bar/.ansible/modules:/Users/jfoy/.ansible/plugins/modules:/usr/share/ansible/plugins/modules
INFO     Set ANSIBLE_COLLECTIONS_PATH=/Users/jfoy/src/coretech/tasks/foo/bar/.ansible/collections:/Users/jfoy/.ansible/collections:/usr/share/ansible/collections:/opt/homebrew/opt/python@3.13/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages:/opt/homebrew/lib/python3.13/site-packages:/opt/homebrew/Cellar/ansible-lint/25.8.2_1/libexec/lib/python3.13/site-packages
INFO     Set ANSIBLE_ROLES_PATH=/Users/jfoy/src/coretech/tasks/foo/bar/.ansible/roles:/Users/jfoy/.ansible/roles:/usr/share/ansible/roles:/etc/ansible/roles
DEBUG    Effective yamllint rules used: {'anchors': {'level': 'error', 'forbid-undeclared-aliases': True, 'forbid-duplicated-anchors': False, 'forbid-unused-anchors': False}, 'braces': {'level': 'error', 'forbid': False, 'min-spaces-inside': 0, 'max-spaces-inside': 1, 'min-spaces-inside-empty': -1, 'max-spaces-inside-empty': -1}, 'brackets': {'level': 'error', 'forbid': False, 'min-spaces-inside': 0, 'max-spaces-inside': 0, 'min-spaces-inside-empty': -1, 'max-spaces-inside-empty': -1}, 'colons': {'level': 'error', 'max-spaces-before': 0, 'max-spaces-after': 1}, 'commas': {'level': 'error', 'max-spaces-before': 0, 'min-spaces-after': 1, 'max-spaces-after': 1}, 'comments': {'level': 'warning', 'require-starting-space': True, 'ignore-shebangs': True, 'min-spaces-from-content': 1}, 'comments-indentation': False, 'document-end': False, 'document-start': False, 'empty-lines': {'level': 'error', 'max': 2, 'max-start': 0, 'max-end': 0}, 'empty-values': False, 'float-values': False, 'hyphens': {'level': 'error', 'max-spaces-after': 1}, 'indentation': {'level': 'error', 'spaces': 'consistent', 'indent-sequences': True, 'check-multi-line-strings': False}, 'key-duplicates': {'level': 'error', 'forbid-duplicated-merge-keys': False}, 'key-ordering': False, 'line-length': {'level': 'error', 'max': 160, 'allow-non-breakable-words': True, 'allow-non-breakable-inline-mappings': False}, 'new-line-at-end-of-file': {'level': 'error'}, 'new-lines': {'level': 'error', 'type': 'unix'}, 'octal-values': {'forbid-implicit-octal': True, 'forbid-explicit-octal': True, 'level': 'error'}, 'quoted-strings': False, 'trailing-spaces': {'level': 'error'}, 'truthy': {'level': 'warning', 'allowed-values': ['true', 'false'], 'check-keys': True}}
DEBUG    Excluded: .ansible
DEBUG    Excluded: minimal/.ansible
DEBUG    Added role: minimal/roles/sys (role)
DEBUG    Excluded: .ansible
DEBUG    Excluded: minimal/.ansible
DEBUG    data set to None for minimal/ansible.cfg due to being '' (unknown) kind.
INFO     Executing syntax check on role minimal/roles/sys (0.38s)
DEBUG    Examining minimal/roles/sys/tasks/main.yml of type tasks
DEBUG    Running rule internal-error
DEBUG    Running rule load-failure
DEBUG    Running rule parser-error
DEBUG    Running rule warning
DEBUG    Running rule yaml
DEBUG    Running rule args
DEBUG    Running rule avoid-implicit
DEBUG    Running rule command-instead-of-module
DEBUG    Running rule command-instead-of-shell
DEBUG    Running rule complexity
DEBUG    Running rule deprecated-bare-vars
DEBUG    Running rule deprecated-local-action
DEBUG    Running rule deprecated-module
DEBUG    Running rule fqcn
DEBUG    Running rule galaxy
DEBUG    Running rule ignore-errors
DEBUG    Running rule inline-env-var
DEBUG    Running rule jinja
DEBUG    Running rule key-order
DEBUG    Running rule latest
DEBUG    Running rule literal-compare
DEBUG    Running rule loop-var-prefix
DEBUG    Running rule meta-incorrect
DEBUG    Running rule meta-no-tags
DEBUG    Running rule meta-runtime
DEBUG    Running rule meta-video-links
DEBUG    Running rule name
DEBUG    Running rule no-changed-when
DEBUG    Running rule no-free-form
DEBUG    Running rule no-handler
DEBUG    Running rule no-jinja-when
DEBUG    Running rule no-relative-paths
DEBUG    Running rule no-tabs
DEBUG    Running rule package-latest
DEBUG    Running rule partial-become
DEBUG    Running rule pattern
DEBUG    Running rule playbook-extension
DEBUG    Running rule risky-file-permissions
DEBUG    Running rule risky-octal
DEBUG    Running rule risky-shell-pipe
DEBUG    Running rule role-name
DEBUG    Running rule run-once
DEBUG    Running rule sanity
DEBUG    Running rule schema
DEBUG    Running rule var-naming
DEBUG    Examining minimal/roles/sys/tasks/set-shell-config.yml of type tasks
DEBUG    Running rule internal-error
DEBUG    Running rule load-failure
DEBUG    Running rule parser-error
DEBUG    Running rule warning
DEBUG    Running rule yaml
DEBUG    Running rule args
DEBUG    Running rule avoid-implicit
DEBUG    Running rule command-instead-of-module
DEBUG    Running rule command-instead-of-shell
DEBUG    Running rule complexity
DEBUG    Running rule deprecated-bare-vars
DEBUG    Running rule deprecated-local-action
DEBUG    Running rule deprecated-module
DEBUG    Running rule fqcn
DEBUG    Running rule galaxy
DEBUG    Running rule ignore-errors
DEBUG    Running rule inline-env-var
DEBUG    Running rule jinja
DEBUG    NAME 'ansible_env' (prefix='')
DEBUG    DOT '.' (prefix='')
DEBUG    NAME 'HOME' (prefix='')
DEBUG    NEWLINE '\n' (prefix=' ')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'ansible_env' (prefix='')
DEBUG    DOT '.' (prefix='')
DEBUG    NAME 'HOME' (prefix='')
DEBUG    NEWLINE '\n' (prefix='')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'ansible_env' (prefix='')
DEBUG    DOT '.' (prefix='')
DEBUG    NAME 'HOME' (prefix='')
DEBUG    NEWLINE '\n' (prefix=' ')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'ansible_env' (prefix='')
DEBUG    DOT '.' (prefix='')
DEBUG    NAME 'HOME' (prefix='')
DEBUG    NEWLINE '\n' (prefix='')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'ansible_env' (prefix='')
DEBUG    DOT '.' (prefix='')
DEBUG    NAME 'HOME' (prefix='')
DEBUG    NEWLINE '\n' (prefix=' ')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'ansible_env' (prefix='')
DEBUG    DOT '.' (prefix='')
DEBUG    NAME 'HOME' (prefix='')
DEBUG    NEWLINE '\n' (prefix='')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'ansible_env' (prefix='')
DEBUG    DOT '.' (prefix='')
DEBUG    NAME 'HOME' (prefix='')
DEBUG    NEWLINE '\n' (prefix=' ')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'ansible_env' (prefix='')
DEBUG    DOT '.' (prefix='')
DEBUG    NAME 'HOME' (prefix='')
DEBUG    NEWLINE '\n' (prefix='')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'ansible_env' (prefix='')
DEBUG    DOT '.' (prefix='')
DEBUG    NAME 'HOME' (prefix='')
DEBUG    NEWLINE '\n' (prefix=' ')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'ansible_env' (prefix='')
DEBUG    DOT '.' (prefix='')
DEBUG    NAME 'HOME' (prefix='')
DEBUG    NEWLINE '\n' (prefix='')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'ansible_env' (prefix='')
DEBUG    DOT '.' (prefix='')
DEBUG    NAME 'HOME' (prefix='')
DEBUG    NEWLINE '\n' (prefix=' ')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'ansible_env' (prefix='')
DEBUG    DOT '.' (prefix='')
DEBUG    NAME 'HOME' (prefix='')
DEBUG    NEWLINE '\n' (prefix='')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'sys_profile' (prefix='')
DEBUG    NEWLINE '\n' (prefix=' ')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'sys_profile' (prefix='')
DEBUG    NEWLINE '\n' (prefix='')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'sys_rc_file' (prefix='')
DEBUG    NEWLINE '\n' (prefix=' ')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    NAME 'sys_rc_file' (prefix='')
DEBUG    NEWLINE '\n' (prefix='')
DEBUG    ENDMARKER '' (prefix='')
DEBUG    Stop.
DEBUG    Running rule key-order
DEBUG    Running rule latest
DEBUG    Running rule literal-compare
DEBUG    Running rule loop-var-prefix
DEBUG    Running rule meta-incorrect
DEBUG    Running rule meta-no-tags
DEBUG    Running rule meta-runtime
DEBUG    Running rule meta-video-links
DEBUG    Running rule name
DEBUG    Running rule no-changed-when
DEBUG    Running rule no-free-form
DEBUG    Running rule no-handler
DEBUG    Running rule no-jinja-when
DEBUG    Running rule no-relative-paths
DEBUG    Running rule no-tabs
DEBUG    Running rule package-latest
DEBUG    Running rule partial-become
DEBUG    Running rule pattern
DEBUG    Running rule playbook-extension
DEBUG    Running rule risky-file-permissions
DEBUG    Running rule risky-octal
DEBUG    Running rule risky-shell-pipe
DEBUG    Running rule role-name
DEBUG    Running rule run-once
DEBUG    Running rule sanity
DEBUG    Running rule schema
DEBUG    Running rule var-naming
DEBUG    Examining minimal/roles/sys/tasks/init-check.yml of type tasks
DEBUG    Running rule internal-error
DEBUG    Running rule load-failure
DEBUG    Running rule parser-error
DEBUG    Running rule warning
DEBUG    Running rule yaml
DEBUG    Running rule args
DEBUG    Running rule avoid-implicit
DEBUG    Running rule command-instead-of-module
DEBUG    Running rule command-instead-of-shell
DEBUG    Running rule complexity
DEBUG    Running rule deprecated-bare-vars
DEBUG    Running rule deprecated-local-action
DEBUG    Running rule deprecated-module
DEBUG    Running rule fqcn
DEBUG    Running rule galaxy
DEBUG    Running rule ignore-errors
DEBUG    Running rule inline-env-var
DEBUG    Running rule jinja
DEBUG    Running rule key-order
DEBUG    Running rule latest
DEBUG    Running rule literal-compare
DEBUG    Running rule loop-var-prefix
DEBUG    Running rule meta-incorrect
DEBUG    Running rule meta-no-tags
DEBUG    Running rule meta-runtime
DEBUG    Running rule meta-video-links
DEBUG    Running rule name
DEBUG    Running rule no-changed-when
DEBUG    Running rule no-free-form
DEBUG    Running rule no-handler
DEBUG    Running rule no-jinja-when
DEBUG    Running rule no-relative-paths
DEBUG    Running rule no-tabs
DEBUG    Running rule package-latest
DEBUG    Running rule partial-become
DEBUG    Running rule pattern
DEBUG    Running rule playbook-extension
DEBUG    Running rule risky-file-permissions
DEBUG    Running rule risky-octal
DEBUG    Running rule risky-shell-pipe
DEBUG    Running rule role-name
DEBUG    Running rule run-once
DEBUG    Running rule sanity
DEBUG    Running rule schema
DEBUG    Running rule var-naming
DEBUG    Examining minimal/requirements.yml of type tasks
DEBUG    Running rule internal-error
DEBUG    Running rule load-failure
DEBUG    Running rule parser-error
DEBUG    Running rule warning
DEBUG    Running rule yaml
DEBUG    Running rule args
DEBUG    Running rule avoid-implicit
DEBUG    Running rule command-instead-of-module
DEBUG    Running rule command-instead-of-shell
DEBUG    Running rule complexity
DEBUG    Running rule deprecated-bare-vars
DEBUG    Running rule deprecated-local-action
DEBUG    Running rule deprecated-module
DEBUG    Running rule fqcn
DEBUG    Running rule galaxy
DEBUG    Running rule ignore-errors
DEBUG    Running rule inline-env-var
DEBUG    Running rule jinja
DEBUG    Running rule key-order
DEBUG    Running rule latest
DEBUG    Running rule literal-compare
DEBUG    Running rule loop-var-prefix
DEBUG    Running rule meta-incorrect
DEBUG    Running rule meta-no-tags
DEBUG    Running rule meta-runtime
DEBUG    Running rule meta-video-links
DEBUG    Running rule name
DEBUG    Running rule no-changed-when
DEBUG    Running rule no-free-form
DEBUG    Running rule no-handler
DEBUG    Running rule no-jinja-when
DEBUG    Running rule no-relative-paths
DEBUG    Running rule no-tabs
DEBUG    Running rule package-latest
DEBUG    Running rule partial-become
DEBUG    Running rule pattern
DEBUG    Running rule playbook-extension
DEBUG    Running rule risky-file-permissions
DEBUG    Running rule risky-octal
DEBUG    Running rule risky-shell-pipe
DEBUG    Running rule role-name
DEBUG    Running rule run-once
DEBUG    Running rule sanity
DEBUG    Running rule schema
DEBUG    Running rule var-naming
DEBUG    Examining minimal/.ansible-lint of type ansible-lint-config
DEBUG    Running rule internal-error
DEBUG    Running rule load-failure
DEBUG    Running rule parser-error
DEBUG    Running rule warning
DEBUG    Running rule yaml
DEBUG    Running rule args
DEBUG    Running rule avoid-implicit
DEBUG    Running rule command-instead-of-module
DEBUG    Running rule command-instead-of-shell
DEBUG    Running rule complexity
DEBUG    Running rule deprecated-bare-vars
DEBUG    Running rule deprecated-local-action
DEBUG    Running rule deprecated-module
DEBUG    Running rule fqcn
DEBUG    Running rule galaxy
DEBUG    Running rule ignore-errors
DEBUG    Running rule inline-env-var
DEBUG    Running rule jinja
DEBUG    Running rule key-order
DEBUG    Running rule latest
DEBUG    Running rule literal-compare
DEBUG    Running rule loop-var-prefix
DEBUG    Running rule meta-incorrect
DEBUG    Running rule meta-no-tags
DEBUG    Running rule meta-runtime
DEBUG    Running rule meta-video-links
DEBUG    Running rule name
DEBUG    Running rule no-changed-when
DEBUG    Running rule no-free-form
DEBUG    Running rule no-handler
DEBUG    Running rule no-jinja-when
DEBUG    Running rule no-relative-paths
DEBUG    Running rule no-tabs
DEBUG    Running rule package-latest
DEBUG    Running rule partial-become
DEBUG    Running rule pattern
DEBUG    Running rule playbook-extension
DEBUG    Running rule risky-file-permissions
DEBUG    Running rule risky-octal
DEBUG    Running rule risky-shell-pipe
DEBUG    Running rule role-name
DEBUG    Running rule run-once
DEBUG    Running rule sanity
DEBUG    Running rule schema
DEBUG    Running rule var-naming
DEBUG    Examining minimal/inventory.yml of type tasks
DEBUG    Running rule internal-error
DEBUG    Running rule load-failure
DEBUG    Running rule parser-error
DEBUG    Running rule warning
DEBUG    Running rule yaml
DEBUG    Running rule args
DEBUG    Running rule avoid-implicit
DEBUG    Running rule command-instead-of-module
DEBUG    Running rule command-instead-of-shell
DEBUG    Running rule complexity
DEBUG    Running rule deprecated-bare-vars
DEBUG    Running rule deprecated-local-action
DEBUG    Running rule deprecated-module
DEBUG    Running rule fqcn
DEBUG    Running rule galaxy
DEBUG    Running rule ignore-errors
DEBUG    Running rule inline-env-var
DEBUG    Running rule jinja
DEBUG    Running rule key-order
DEBUG    Running rule latest
DEBUG    Running rule literal-compare
DEBUG    Running rule loop-var-prefix
DEBUG    Running rule meta-incorrect
DEBUG    Running rule meta-no-tags
DEBUG    Running rule meta-runtime
DEBUG    Running rule meta-video-links
DEBUG    Running rule name
DEBUG    Running rule no-changed-when
DEBUG    Running rule no-free-form
DEBUG    Running rule no-handler
DEBUG    Running rule no-jinja-when
DEBUG    Running rule no-relative-paths
DEBUG    Running rule no-tabs
DEBUG    Running rule package-latest
DEBUG    Running rule partial-become
DEBUG    Running rule pattern
DEBUG    Running rule playbook-extension
DEBUG    Running rule risky-file-permissions
DEBUG    Running rule risky-octal
DEBUG    Running rule risky-shell-pipe
DEBUG    Running rule role-name
DEBUG    Running rule run-once
DEBUG    Running rule sanity
DEBUG    Running rule schema
DEBUG    Running rule var-naming
DEBUG    Examining minimal/roles/sys of type role
DEBUG    Running rule internal-error
DEBUG    Running rule load-failure
DEBUG    Running rule parser-error
DEBUG    Running rule warning
DEBUG    Running rule yaml
DEBUG    Running rule args
DEBUG    Running rule avoid-implicit
DEBUG    Running rule command-instead-of-module
DEBUG    Running rule command-instead-of-shell
DEBUG    Running rule complexity
DEBUG    Running rule deprecated-bare-vars
DEBUG    Running rule deprecated-local-action
DEBUG    Running rule deprecated-module
DEBUG    Running rule fqcn
DEBUG    Running rule galaxy
DEBUG    Running rule ignore-errors
DEBUG    Running rule inline-env-var
DEBUG    Running rule jinja
DEBUG    Running rule key-order
DEBUG    Running rule latest
DEBUG    Running rule literal-compare
DEBUG    Running rule loop-var-prefix
DEBUG    Running rule meta-incorrect
DEBUG    Running rule meta-no-tags
DEBUG    Running rule meta-runtime
DEBUG    Running rule meta-video-links
DEBUG    Running rule name
DEBUG    Running rule no-changed-when
DEBUG    Running rule no-free-form
DEBUG    Running rule no-handler
DEBUG    Running rule no-jinja-when
DEBUG    Running rule no-relative-paths
DEBUG    Running rule no-tabs
DEBUG    Running rule package-latest
DEBUG    Running rule partial-become
DEBUG    Running rule pattern
DEBUG    Running rule playbook-extension
DEBUG    Running rule risky-file-permissions
DEBUG    Running rule risky-octal
DEBUG    Running rule risky-shell-pipe
DEBUG    Running rule role-name
DEBUG    Running rule run-once
DEBUG    Running rule sanity
DEBUG    Running rule schema
DEBUG    Running rule var-naming
DEBUG    Examining minimal/site.yml of type tasks
DEBUG    Running rule internal-error
DEBUG    Running rule load-failure
DEBUG    Running rule parser-error
DEBUG    Running rule warning
DEBUG    Running rule yaml
DEBUG    Running rule args
DEBUG    Running rule avoid-implicit
DEBUG    Running rule command-instead-of-module
DEBUG    Running rule command-instead-of-shell
DEBUG    Running rule complexity
DEBUG    Running rule deprecated-bare-vars
DEBUG    Running rule deprecated-local-action
DEBUG    Running rule deprecated-module
DEBUG    Running rule fqcn
DEBUG    Running rule galaxy
DEBUG    Running rule ignore-errors
DEBUG    Running rule inline-env-var
DEBUG    Running rule jinja
DEBUG    Running rule key-order
DEBUG    Running rule latest
DEBUG    Running rule literal-compare
DEBUG    Running rule loop-var-prefix
DEBUG    Running rule meta-incorrect
DEBUG    Running rule meta-no-tags
DEBUG    Running rule meta-runtime
DEBUG    Running rule meta-video-links
DEBUG    Running rule name
DEBUG    Running rule no-changed-when
DEBUG    Running rule no-free-form
DEBUG    Running rule no-handler
DEBUG    Running rule no-jinja-when
DEBUG    Running rule no-relative-paths
DEBUG    Running rule no-tabs
DEBUG    Running rule package-latest
DEBUG    Running rule partial-become
DEBUG    Running rule pattern
DEBUG    Running rule playbook-extension
DEBUG    Running rule risky-file-permissions
DEBUG    Running rule risky-octal
DEBUG    Running rule risky-shell-pipe
DEBUG    Running rule role-name
DEBUG    Running rule run-once
DEBUG    Running rule sanity
DEBUG    Running rule schema
DEBUG    Running rule var-naming
WARNING  Listing 4 violation(s) that are fatal
Read documentation for instructions on how to ignore specific rule violations.

DEBUG    Determined rule-profile order: {'internal-error': (0, 'min'), 'load-failure': (1, 'min'), 'parser-error': (2, 'min'), 'syntax-check': (3, 'min'), 'command-instead-of-module': (4, 'basic'), 'command-instead-of-shell': (5, 'basic'), 'deprecated-bare-vars': (6, 'basic'), 'deprecated-local-action': (7, 'basic'), 'deprecated-module': (8, 'basic'), 'inline-env-var': (9, 'basic'), 'key-order': (10, 'basic'), 'literal-compare': (11, 'basic'), 'jinja': (12, 'basic'), 'no-free-form': (13, 'basic'), 'no-jinja-when': (14, 'basic'), 'no-tabs': (15, 'basic'), 'partial-become': (16, 'basic'), 'playbook-extension': (17, 'basic'), 'role-name': (18, 'basic'), 'schema': (19, 'basic'), 'name': (20, 'basic'), 'var-naming': (21, 'basic'), 'yaml': (22, 'basic'), 'name[template]': (23, 'moderate'), 'name[imperative]': (24, 'moderate'), 'name[casing]': (25, 'moderate'), 'spell-var-name': (26, 'moderate'), 'avoid-implicit': (27, 'safety'), 'latest': (28, 'safety'), 'package-latest': (29, 'safety'), 'risky-file-permissions': (30, 'safety'), 'risky-octal': (31, 'safety'), 'risky-shell-pipe': (32, 'safety'), 'galaxy': (33, 'shared'), 'ignore-errors': (34, 'shared'), 'layout': (35, 'shared'), 'meta-incorrect': (36, 'shared'), 'meta-no-tags': (37, 'shared'), 'meta-video-links': (38, 'shared'), 'meta-version': (39, 'shared'), 'meta-runtime': (40, 'shared'), 'no-changed-when': (41, 'shared'), 'no-changelog': (42, 'shared'), 'no-handler': (43, 'shared'), 'no-relative-paths': (44, 'shared'), 'max-block-depth': (45, 'shared'), 'max-tasks': (46, 'shared'), 'unsafe-loop': (47, 'shared'), 'pattern': (48, 'production'), 'avoid-dot-notation': (49, 'production'), 'sanity': (50, 'production'), 'fqcn': (51, 'production'), 'import-task-no-when': (52, 'production'), 'meta-no-dependencies': (53, 'production'), 'single-entry-point': (54, 'production'), 'use-loop': (55, 'production')}[/]
# Rule Violation Summary

  1 parser-error profile:min tags:core
  3 schema profile:min tags:core

Failed: 4 failure(s), 0 warning(s) on 9 files.
schema[tasks]: $ {'all': {'hosts': {'localhost': {'ansible_connection': 'local', 'ansible_python_interpreter': '{{ ansible_playbook_python }}'}}}} is not of type 'array', 'null'
minimal/inventory.yml:1  Returned errors will not include exact line numbers, but they will mention
the schema name being used as a tag, like ``schema[playbook]``,
``schema[tasks]``.

This rule is not skippable and stops further processing of the file.

If incorrect schema was picked, you might want to either:

* move the file to standard location, so its file is detected correctly.
* use ``kinds:`` option in linter config to help it pick correct file type.
[/]

schema[tasks]: $ {'collections': ['ansible.utils', 'ansible.posix']} is not of type 'array', 'null'
minimal/requirements.yml:1  Returned errors will not include exact line numbers, but they will mention
the schema name being used as a tag, like ``schema[playbook]``,
``schema[tasks]``.

This rule is not skippable and stops further processing of the file.

If incorrect schema was picked, you might want to either:

* move the file to standard location, so its file is detected correctly.
* use ``kinds:`` option in linter config to help it pick correct file type.
[/]

schema[tasks]: $[0] 'block' is a required property[/]
minimal/site.yml:1  Returned errors will not include exact line numbers, but they will mention
the schema name being used as a tag, like ``schema[playbook]``,
``schema[tasks]``.

This rule is not skippable and stops further processing of the file.

If incorrect schema was picked, you might want to either:

* move the file to standard location, so its file is detected correctly.
* use ``kinds:`` option in linter config to help it pick correct file type.
[/]

parser-error: conflicting action statements: hosts, roles (warning)
minimal/site.yml:2:3
```

This line appears to be the culprit:
https://github.com/ansible/ansible-lint/blob/7ef0ba81bf84dc4493261025c03e593336fa61ae/src/ansiblelint/config.py#L54

**Repository:** `ansible/ansible-lint`
**Base commit:** `cfd927fe8a92d28082d3b10234a28968074cec27`
