`LookupBase.get_option_and_origin()` always returns default value
### Summary

It seems that `LookupBase.get_option_and_origin()` always returns the default value, instead of the option's value and source. `LookupBase.get_option()` works fine.

### Issue Type

Bug Report

### Component Name

LookupBase

### Ansible Version

```console
devel
```

### Configuration

```console
/
```

### OS / Environment

/

### Steps to Reproduce

Plugin:
```py
# -*- coding: utf-8 -*-
# Copyright (c) 2025, Felix Fontein <felix@fontein.de>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r"""
name: test
short_description: Test input precedence
author: Felix Fontein (@felixfontein)
description:
  - Test input precedence.
options:
  _terms:
    description:
      - Ignored.
    type: list
    elements: str
    required: true
  some_option:
    description:
      - The interesting part.
    type: str
    default: default value
    env:
      - name: PLAYGROUND_TEST_1
      - name: PLAYGROUND_TEST_2
    vars:
      - name: playground_test_1
      - name: playground_test_2
    ini:
      - key: playground_test_1
        section: playground
      - key: playground_test_2
        section: playground
"""

EXAMPLES = r"""#"""

RETURN = r"""
_list:
  description:
    - The value of O(some_option).
  type: list
  elements: str
"""

from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        """Generate list."""
        self.set_options(var_options=variables, direct=kwargs)

        return [self.get_option("some_option"), *self.get_option_and_origin("some_option")]
```
Playbook:
```yaml
- hosts: localhost
  gather_facts: false
  tasks:
    - name: Task with explicit specification
      ansible.builtin.debug:
        msg: >-
          {{ query('felixfontein.playground.test', some_option='foo') }}
    - name: Task with explicit specification and Ansible vars
      ansible.builtin.debug:
        msg: >-
          {{ query('felixfontein.playground.test', some_option='foo') }}
      vars:
        playground_test_1: var 1
        playground_test_2: var 2
    - name: Task without explicit specification and without Ansible vars
      ansible.builtin.debug:
        msg: >-
          {{ query('felixfontein.playground.test') }}
    - name: Task without explicit specification and with Ansible vars
      ansible.builtin.debug:
        msg: >-
          {{ query('felixfontein.playground.test') }}
      vars:
        playground_test_1: var 1
        playground_test_2: var 2
```

### Expected Results

In the four `debug` outputs, I would expect the second value to be equal to the first one, and the third having different values (depending on which value is taken).

### Actual Results

```console
The first entry of `msg` is correct, but the second is always `default value`, and the third is always `default`.
```

### Code of Conduct

- [x] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `a0d56d2f4f32f174bd6c463118a3a38eeb70921b`

## Hints

Files identified in the description:

None

If these files are incorrect, please update the `component name` section of the description or use the [component](https://github.com/ansible/ansibotmini#commands) bot command.

<!--- boilerplate: components_banner --->


very confusing since `get_option` calls `get_optoin_and_origin` ...

the 'set' keeps local cache, get_option uses that and only falls back to get_option_and_origin if it was not set, but the latter does not get all the info it needs (kwargs!) ....
