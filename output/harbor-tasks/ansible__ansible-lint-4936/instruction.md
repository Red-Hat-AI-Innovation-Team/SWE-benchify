ansible-lint --fix Indents mappings in list after anchor
##### Summary

When adding an anchor to a list item that is a mapping, ansible-lint --fix will indent the mapping to the level of the anchor
Running just ansible-lint will detect this as incorrect indentation.

##### Issue Type

- Bug Report

##### OS / ENVIRONMENT


```console (paste below)
python -m ansiblelint --version
ansible-lint 26.1.1 using ansible-core:2.19.5 ansible-compat:25.12.0 ruamel-yaml:0.19.1 ruamel-yaml-clib:0.2.15
```

<!--- Provide all relevant information below, e.g. target OS versions, network
 device firmware, etc. -->
Ubuntu 22.04 Python 3.11

- ansible installation method: pip
- ansible-lint installation method: pip

##### STEPS TO REPRODUCE

<!--- Describe exactly how to reproduce the problem, using a minimal test case -->

<!--- Paste example playbooks or commands between triple backticks below -->

```yaml
---
- &my_anchor
  name: my_name
  map_key_1: map_value_1
  map_key_2: map_value_2
- <<: *my_anchor
  name: my_other_name
````
```console (paste below)
python -m ansiblelint --fix
```
```yaml
---
- &my_anchor
            name: my_name
            map_key_1: map_value_1
            map_key_2: map_value_2
- <<: *my_anchor
  name: my_other_name
```

<!--- HINT: You can paste gist.github.com links for larger files -->

##### Desired Behavior

<!--- Describe what you expected to happen when running the steps above -->

The autofix should not touch the snippet.

**Repository:** `ansible/ansible-lint`
**Base commit:** `5781d34cc97c1e6dfa2c0a19445e010d7f1c720b`
