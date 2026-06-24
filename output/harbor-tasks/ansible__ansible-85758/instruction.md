Ability to hide 'included' lines when using include_role or include_tasks with default callback plugin
### Summary

I just upgraded, and notice that latest now prints "included: host1, host2, hostX" for all included roles.
I use this playbook to be able to auto tag roles.

```yaml
  tasks:
    - include_role:
        name: "{{ role_item }}"
        apply:
          tags: "{{ role_item | split('/') | last }}"
      tags: always
      loop_control:
        loop_var: role_item
      loop:
        - role1
        - role2
        - sub/rolea
        - sub/roleb
```

It produces an huge output with ~1000 hosts in inventory

```
included: role1 for host1, host2, host3
included: role2 for host1, host2, host3
included: sub/rolea for host1, host2, host3
included: sub/roleb for host1, host2, host3
```

### Issue Type

Feature Idea

### Component Name

callback

### Additional Information

I want to be able to configure default callback to ignore those lines, even in verbose

```
[defaults]
callback_pretty_results = yes
callback_result_format = yaml
display_skipped_hosts = no
display_failed_stderr = yes
show_custom_stats = yes
verbosity = 1

display_included = no
```

### Code of Conduct

- [X] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `52b7d4d092359e776da0b79db9752bfc6ca91969`

## Hints

Files identified in the description:

None

If these files are incorrect, please update the `component name` section of the description or use the [component](https://github.com/ansible/ansibotmini#commands) bot command.

<!--- boilerplate: components_banner --->


'included' appeared in 2.17.0

it was always supposed to show the include message, but at one point we 'broke' this and that bug was identified and fixed.

A custom callback plugin can easily achieve what you want.

It was not a bug, but a feature :)
Problem of the custom callback is that it is not cumulative. I mean, I use yaml output, and I want to be able to disable those lines in that callback.

I'd also like to throw my hat into the ring for this feature request - it'd be a nice option to round out the ability we already have to hide skipped or ok hosts.

I’m running into the exact same verbosity problem with the `included:` banner
lines.  I know the current recommendation is “just use a custom callback,”
but IMO this feels like functionality that would make sense in the *default*
callback too.  Here’s a small, fully backward-compatible tweak that solves the
issue for me—curious to know what you think:

* **Introduce a boolean option `display_included_hosts`** (default `true`) in
  the default callback.
* Expose the option via  
  * `ansible.cfg` (`[defaults] display_included_hosts = false`)  
  * environment variable `ANSIBLE_DISPLAY_INCLUDED_HOSTS`  
* Guard the call to `banner()` inside `v2_playbook_on_include()` with this flag.

The patch touches only two files:
- plugins/doc_fragments/default_callback.py # option definition
- plugins/callback/default.py # three-line if-guard


When the flag is set to `false`, the *included:* lines disappear while all
normal task output remains untouched.

If this direction looks acceptable, I’m happy to open a PR that closes this
issue. Thoughts?


Perhaps just open the PR regardless of whether the maintainers respond here. I cannot see a reason why this should be controversial.

+1 here, would be really elegant to disable this with the default callback.
