v25.12.1: PR #4855 adds trailing spaces to blank comment lines, triggering yaml[trailing-spaces]
## Summary

After upgrading to ansible-lint v25.12.1, our CI started failing with `yaml[trailing-spaces]` errors on lines that previously passed. The issue is caused by PR #4855 which was intended to fix `yaml[comments]` by adding a space after `#comment` → `# comment`.

However, the fix also incorrectly adds a trailing space to **blank comment lines** (lines with just `#`):

```diff
-#
+# 
```

This then triggers the `yaml[trailing-spaces]` rule, causing failures.

## Steps to Reproduce

1. Create a YAML file with blank comment lines in a comment block:

```yaml
---
# This is a comment
#
# Another comment after blank line
- name: Test task
  debug:
    msg: "hello"
```

2. Run `ansible-lint --fix` with v25.12.1

3. Observe that the blank `#` line becomes `# ` (with trailing space)

4. Run `ansible-lint` again - it now fails with `yaml[trailing-spaces]`

## Expected Behavior

Blank comment lines (`#` with nothing after) should remain unchanged. Only comments with text missing a space (`#comment`) should be fixed to (`# comment`).

## Actual Behavior

Blank comment lines are being modified from `#` to `# ` (adding a trailing space), which then triggers the `yaml[trailing-spaces]` rule.

## Environment

```
ansible-lint 25.12.1 using ansible-core:2.20.0 ansible-compat:25.8.2 ruamel-yaml:0.18.16 ruamel-yaml-clib:0.2.14
```

- Linux x86_64
- Python 3.12
- Also reproduced in GitHub Actions with ubuntu-latest

## Workaround

Pin to v25.11.1 which does not have this issue:
```bash
uv tool install ansible-lint==25.11.1
# or
pip install ansible-lint==25.11.1
```

## Related

- PR #4855 introduced this regression
- Issue #4831 was the original issue that #4855 attempted to fix

**Repository:** `ansible/ansible-lint`
**Base commit:** `40f24c2d511c6662ba96b53a35f386cf8b0c11ad`
