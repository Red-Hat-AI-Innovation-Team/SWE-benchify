Empty template rendered as "None" make blockinfile task fail
### Ansible Version

```console
ansible [core 2.19.0]
  config file = None
  python version = 3.11.2 (main, Apr 28 2025, 14:11:48) [GCC 12.2.0] (/home/ikus060/Downloads/TEST/.venv/bin/python3)
  jinja version = 3.1.6
  pyyaml version = 6.0.2 (with libyaml v0.2.5)
```

### Summary

Starting with ansible 2.19, I'm running into issue with templating of empty block. Here an example.

```
- hosts: localhost
  vars:
  tasks:
    - blockinfile:
        path: output.txt
        block: "{% if False %}{% endif %}"
```

**Expected Result**

The expected result would be an empty block or no operation at all.

**Current result**

Instead the playbook fail with this error. As if the template was rendered as None instead of an empty block...

```
PLAY [localhost] ***************************************************************************************************************************

TASK [Gathering Facts] *********************************************************************************************************************
ok: [localhost]

TASK [blockinfile] *************************************************************************************************************************
[ERROR]: Task failed: Module failed: argument 'block' is of type NoneType and we were unable to convert to str: 'None' is not a string and conversion is not allowed
Origin: /home/ikus060/Downloads/TEST/test.yml:24:7

22       key2: "foo"
23   tasks:
24     - blockinfile:
         ^ column 7

fatal: [localhost]: FAILED! => {"changed": false, "msg": "argument 'block' is of type NoneType and we were unable to convert to str: 'None' is not a string and conversion is not allowed"}

```

This might be related to #85116, but I still have the same issue with this version of ansible:



### <!-- Bot instructions (ignore this) -->

<!--
### Component Name
bin/ansible
### Issue Type
Bug Report
### Configuration
### OS / Environment
-->

**Repository:** `ansible/ansible`
**Base commit:** `76748b8478abc10b7bb476db86a27d3041d47d40`

## Hints

Files identified in the description:

* [`bin/ansible`](https://github.com/ansible/ansible/blob/devel/bin/ansible)

If these files are incorrect, please update the `component name` section of the description or use the [component](https://github.com/ansible/ansibotmini#commands) bot command.

<!--- boilerplate: components_banner --->


I assume this example comes from a real world code block that doesn't have a reasonable else path. In the end, the block gets converted to a string. Therefore, I wonder if this example might help you mitigate your problem:

    block: "{% if False %}{% else %}{{ \"\" }}{% endif %}"



2.19 has a much stricter templating engine, now types are preserved, so instead of 'empty == string' now empty == None.

another workaround:
```
block: "{% if False %}''{% endif %}"
```
2 single quotes in case it is not clear

Thanks @fallbackerik @bcoca 

1. `"{% if False %}''{% endif %}"` is not working and raise the same None issue.
2. `"{% if False %}{% else %}{{ \"\" }}{% endif %}"` is a workarround, 

But I would really expect this behaviour to get fixed in a final release. I'm very surprise ansible-core was even release with this regression. In my case alone, I would need to review hundred of playbooks to ensure the proper behaviour for something simple as a "if" block !

If my specific case, `blockinfile.block` required a string. I think it's safe to asume that anything rendered as "None" should be cast into an empty string...

----

While working on other part of my playbooks, I also notice similar behaviour for templates.

```
{{ ansible_managed }}

{% macro mymacro(myvar) %}
{% if myvar %}
foo
{% endif %}
{% endmacro %}

{{ mymacro(False) }}
```
get endered as:
```
Ansible managed


None
```
I would expect the template to be rendered as:

```
Ansible managed


```
As it did with ansible 2.18. I would never expect "None" to be rendered literally in a jinja2 template.


The underlying issue is that we have to guess what the consumer of a given template actually wants, since the template engine (invoked at task creation time) is pretty far disconnected from the ultimate consumer (an action/module execution). The problem has actually always existed, since we delegate most stringification duties to Python's `str`/`repr`, which stringify `None` as "None". Pre-2.19 templating had code littered all over the place that tried (and often failed) to coerce `None` template results to empty strings, so unless you hit one of the "holes" in the logic, you may never have seen it.

This exact problem didn't come up during the beta period, though #85116 is related. In that case, we do know that the consumer *always* expects a string (since we're writing the template result to a file) and that an embedded `None`->"None" is almost certainly not what was desired. That fix works (for that module anyway) when the *entire* result is a `None`, but it doesn't handle the general case where we're `concat`ing multiple results containing one or more `None`s (as in your example).

The changes to the 2.19+ templating engine give us a lot more options, more consistent behavior, and more clues to use when guessing how we should handle non-string output from a template. There might actually be a fairly straightforward fix for this one, at least for top-level block results from the template concat (which would restore the majority of the previous behavior you're looking for) - we're playing with some ideas this afternoon. The fix we're playing with would likely *not* address, e.g., embedded `None`s in data structures, but then again neither did <=2.18.

@nitzmahone Awesome. I was afraid that it would not get fixed ! Just knowing you are working on a possible solution is a big relief.

Thanks alot !
