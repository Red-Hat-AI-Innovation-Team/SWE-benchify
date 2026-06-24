--no-offline argument doesn't install roles and collections when "offline: true" is set in .ansible-lint file
<!--- Verify first that your issue is not already reported on GitHub -->
<!--- Also test if the latest release and main branch are affected too -->

##### Summary

`ansible-lint --no-offline
`
doesn't install the roles and collections when the ./.ansible-lint file has

`offline: true
`

is set.

##### Issue Type

- Bug Report

##### OS / ENVIRONMENT

<!--- Paste verbatim output between triple backticks -->

```
ansible-lint 25.9.0 using ansible-core:2.19.2 ansible-compat:25.8.1 ruamel-yaml:0.18.15 ruamel-yaml-clib:0.2.12
A new release of ansible-lint is available: 25.9.0 → 25.11.0[/] Upgrade by running: pip3 install --user --upgrade ansible-lint
<!--- Provide all relevant information below, e.g. target OS versions, network
 device firmware, etc. -->

```
- ansible installation method: one of source, pip, OS package
- ansible-lint installation method: one of source, pip, OS package

##### STEPS TO REPRODUCE

ensure ./ansible-lint contains:

```offline: true```


At command line:

`ansible-lint --no-offline .
`


##### Desired Behavior

Roles and collections should be installed in ./ansible directory.

##### Actual Behavior

```
./ansible/roles
./ansible/collections
./ansible/modules
```

directories are created but they are devoid of roles/collections.

**Repository:** `ansible/ansible-lint`
**Base commit:** `9d68614719b1a6f0950ecbfe64576706e5970801`
