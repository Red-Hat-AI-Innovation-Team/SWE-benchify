unable to lint a limited subset of yaml tags on command line
<!--- Verify first that your issue is not already reported on GitHub -->
<!--- Also test if the latest release and main branch are affected too -->

##### Summary

running `ansible-lint --tags yaml[truthy]` should check only "yaml[truthy]" tag. But it checks all "yaml" tags.
I suspect this might be related to #3896 

##### Issue Type

- Bug Report

##### OS / ENVIRONMENT

```console (paste below)
ansible-lint --version
ansible-lint 25.1.2 using ansible-core:2.16.14 ansible-compat:25.1.2 ruamel-yaml:0.18.6 ruamel-yaml-clib:0.2.8
```

<!--- Provide all relevant information below, e.g. target OS versions, network
 device firmware, etc. -->

RHEL8 UBI Image:
$ rpm -qa | grep ^ansible
ansible-core-2.16.14-2.el8ap.noarch
ansible-runner-2.4.1-1.el8ap.noarch
ansible-sign-0.1.1-2.el8ap.noarch
ansible-lint-25.1.2-1.el8ap.noarch
ansible-test-2.16.14-2.el8ap.noarch

##### STEPS TO REPRODUCE

<!--- Describe exactly how to reproduce the problem, using a minimal test case -->

<!--- Paste example playbooks or commands between triple backticks below -->

1. create a file testfile.yml with this content:

```
first_var: "vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv"
second_var: yes
```

2. check linting for `yaml[truthy]` tag

```console (paste below)
$ ansible-lint --tags yaml[truthy] testfile.yml
WARNING  Skipped installing old role dependencies due to running in offline mode.
WARNING  Skipped installing collection dependencies due to running in offline mode.
WARNING  Listing 2 violation(s) that are fatal
yaml[line-length]: Line too long (169 > 160 characters)
testfile.yml:1

yaml[truthy]: Truthy value should be one of [false, true]
testfile.yml:2

Read documentation for instructions on how to ignore specific rule violations.

# Rule Violation Summary

  1 yaml profile:basic tags:formatting,yaml
  1 yaml profile:basic tags:formatting,yaml

Failed: 2 failure(s), 0 warning(s) on 1 files. Last profile that met the validation criteria was 'min'.
```

<!--- HINT: You can paste gist.github.com links for larger files -->

##### Desired Behavior

<!--- Describe what you expected to happen when running the steps above -->

only `yaml[truthy]` violations should be returned

##### Actual Behavior

<!--- Describe what happened. If possible run with extra verbosity (-vvvv) -->

all yaml violations are returned

**Repository:** `ansible/ansible-lint`
**Base commit:** `6b2cee92ad42e71ffcdeeceac03a5cc484b807a9`

## Hints

@DonEstefan I see you're using an older version of ansible-lint, can you try upgrading to latest and retry? 

@alisonlhart I just tried the latest version and the problem is still present.
```
ansible-lint 25.6.1 using ansible-core:2.19.0 ansible-compat:25.6.0 ruamel-yaml:0.18.14 ruamel-yaml-clib:0.2.12
```
