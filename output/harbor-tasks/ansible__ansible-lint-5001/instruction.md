Exit code 2 when all warnings are skipped using .ansible-lint-ignore and --strict
<!--- Verify first that your issue is not already reported on GitHub -->
<!--- Also test if the latest release and main branch are affected too -->

##### Summary

When all the warnings are skipped using `skip` in `.ansible-lint-ignore`, `ansible-lint --strict` still fails with 0 error and 0 warning

##### Issue Type

- Bug Report

##### OS / ENVIRONMENT

<!--- Paste verbatim output between triple backticks -->

```console (paste below)
ansible-lint --version
ansible-lint 26.3.0 using ansible-core:2.20.3 ansible-compat:25.12.1 ruamel-yaml:0.19.1 ruamel-yaml-clib:None
```

- ansible installation method: pip
- ansible-lint installation method: pip

##### STEPS TO REPRODUCE

In a directory, with no `.ansible-lint` config

and this input file

```
bad_indentation:
- blah: plop
  zz: 42
```

Running ansible-lint (with `--generate-ignore`)

```
$ansible-lint --force-color --strict --offline --generate-ignore
WARNING  Project directory /.ansible cannot be used for caching as it is not writable.
WARNING  Listing 1 violation(s) that are fatal
yaml[indentation]: Wrong indentation: expected at least 1
test.yml:2

Read documentation for instructions on how to ignore specific rule violations.

# Rule Violation Summary

  1 yaml profile:basic tags:formatting,yaml

Failed: 1 failure(s), 0 warning(s) in 1 files processed of 2 encountered. Last profile that met the validation criteria was 'min'.

$ echo $?
2
```

✅ This is expected as there is an error

It generates the following file:

```
$ cat .ansible-lint-ignore
# This file contains ignores rule violations for ansible-lint
test.yml yaml[indentation]
```

```console (paste below)
ansible-lint --force-color --strict --offline
WARNING  Project directory /.ansible cannot be used for caching as it is not writable.
WARNING  Listing 1 violation(s) marked as ignored, likely already known
yaml[indentation]: Wrong indentation: expected at least 1 (warning) # ignored
test.yml:2


Failed: 0 failure(s), 1 warning(s) in 1 files processed of 2 encountered. Last profile that met the validation criteria was 'production'.

$ echo $?
2
```

✅ This is expected as there is a warning and running with strict

Updating to skip

```diff
# This file contains ignores rule violations for ansible-lint
- test.yml yaml[indentation]
+ test.yml yaml[indentation] skip
```

and running again:

```
ansible-lint --force-color --strict --offline
WARNING  Project directory /.ansible cannot be used for caching as it is not writable.

Failed: 0 failure(s), 0 warning(s) in 1 files processed of 2 encountered. Last profile that met the validation criteria was 'production'.
$ echo $?
2
```

🔴 The exit code should be 0 as there is no error and no warning just like when the rule is skipped using `skip_list`

If I add:

```
$cat .ansible-lint
skip_list:
  - yaml[indentation]
```

I get:

```
ansible-lint --force-color  --offline --strict

Passed: 0 failure(s), 0 warning(s) in 2 files processed of 3 encountered. Last profile that met the validation criteria was 'production'.

echo $?
0
```

##### Desired Behavior

When all warnings are skipped in `.ansible-lint-ignore`, the exit code should be 0, even with `--strict`

##### Actual Behavior

the exit code is 2 when there is no failure and no warning

**Repository:** `ansible/ansible-lint`
**Base commit:** `f07c652e32a102c0286680dc50d247cb2c9e00fb`
