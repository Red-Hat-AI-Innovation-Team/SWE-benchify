--fix does not fix yaml[comments] errors (Python 3.12, ansible-lint 25.9.2 and 25.9.3.dev9)
##### Summary

Given this input:
```yaml
---
#comment
arr:
  - 42
```
I expect ansible-lint to change the comment line:
```diff
-#comment
+# comment
```

However, it does not.  Instead, I get:
```
$ ansible-lint --fix foo.yaml
ERROR    Rule specific fix not applied for: yaml[comments]/yaml foo.yaml:2[/]
WARNING  Listing 1 violation(s) that are fatal
yaml[comments]: Missing starting space in comment
foo.yaml:2

Read documentation for instructions on how to ignore specific rule violations.

# Rule Violation Summary

  1 yaml profile:basic tags:formatting,yaml

Failed: 1 failure(s), 0 warning(s) in 1 files processed of 1 encountered. Last profile that met the validation criteria was 'min'.
```

I have checked for related issues but not found any.  Issues like #3890 relate to spaces _before_ the `#`, whereas this ticket is for spaces _after_ the `#`.

##### Issue Type

- Bug Report

##### OS / ENVIRONMENT

<!--- Paste verbatim output between triple backticks -->

```console (paste below)
ansible-lint --version
ansible-lint 25.9.2 using ansible-core:2.19.3 ansible-compat:25.8.2 ruamel-yaml:0.18.16 ruamel-yaml-clib:0.2.14

```

<!--- Provide all relevant information below, e.g. target OS versions, network
 device firmware, etc. -->

* Linux x86_64
* Ubuntu 22.04.5 LTS
* Python 3.12.12.
* Both ansible-lint 25.9.2 and 25.9.3.dev9 exhibit the same behaviour.

- ansible installation method: not installed separately --- `pip` installed `ansible-compat-25.8.2 ansible-core-2.19.3` along with `ansible-lint`.
- ansible-lint installation method: tested with `pip` (25.9.2) and `pip -e .` (25.9.3.dev9 @ 35e396c75)

##### STEPS TO REPRODUCE

Repro script is attached (`repro.sh` in https://github.com/user-attachments/files/23239068/repro.zip).  Run with no args in an empty directory.

Run `ansible-lint --fix` on the yaml file in the "Summary" above

##### Desired Behavior

`#comment` -> `# comment` (details above)

##### Actual Behavior


```paste below
DEBUG    Applying rule specific fix for: yaml[comments]/yaml foo.yaml:2[/]
ERROR    Rule specific fix not applied for: yaml[comments]/yaml foo.yaml:2[/]
DEBUG    Rewriting yaml file: foo.yaml (yaml), version=None
DEBUG    Fixing: (1 of 1) [yaml] (Missing starting space in comment) matched foo.yaml:2 [/]
DEBUG    Rerunning: [yaml] (Missing starting space in comment) matched foo.yaml:2 [/]
```

Full log is attached (`repro.ansi` in https://github.com/user-attachments/files/23239068/repro.zip)

**Repository:** `ansible/ansible-lint`
**Base commit:** `444be15e3b7a37b66957cd9687cada9772552300`

## Hints

[repro.zip](https://github.com/user-attachments/files/23239068/repro.zip)

Good suggestion. I'm unsure if our yamllint formatter configuration is the issue/resolution here... We'd welcome a PR to fix this issue from the community!
