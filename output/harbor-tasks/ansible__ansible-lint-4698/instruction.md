ansible-lint with ansible-core 2.19 can still call `lookup()`
##### Summary
While playing around with current `main`, I found some more ways to make ansible-lint call lookup plugins: add round brackets around `lookup`/`query`/`q`: `(lookup)('name.of.plugin', 'parameters')` is not caught by the regular expression.

I think this shows that the only way to properly handle this is to look at the AST.

##### Issue Type
- Bug Report

**Repository:** `ansible/ansible-lint`
**Base commit:** `f16e1ce1a2ab8f94f03121ea4e499ba042677d2a`

## Hints

```
from jinja2 import Environment, meta, nodes

def find_lookup_calls(template_str):
    env = Environment()
    ast = env.parse(template_str)
    lookup_names = {'lookup', 'q', 'query'}

    found = []
    for node in ast.find_all(nodes.Call):
        func_name = getattr(node.node, 'name', None)
        if func_name in lookup_names:
            found.append({
                'name': func_name,
                'lineno': node.lineno,
                'args': [str(a) for a in node.args]
            })
    return found

# Example usage:
if __name__ == "__main__":
    templates = [
        "{{ lookup('file', '/etc/passwd') }}",
        "{{ q('env', 'HOME') }}",
        "{{ query('sequence', 'start=1 end=5') }}",
        "{{ (lookup)('pipe', 'date') }}",
        "{{ some_filter(lookup('env', 'USER')) }}",
        "{{ (q)('pipe', 'whoami') }}",
        "{% set fn = lookup %}{{ fn('file', '/etc/shadow') }}", # Indirect call, won't be detected
    ]
    for tpl in templates:
        print(f"Template: {tpl}")
        lookups = find_lookup_calls(tpl)
        if lookups:
            print("  Detected lookup calls:")
            for call in lookups:
                print(f"    Line {call['lineno']}: {call['name']} with args {call['args']}")
        else:
            print("  No direct lookup call detected.")
```

Can you think of any others?  It will never be bulletproof :)

That should be quite bullet-proof, compared to all previous solutions (except passing `disable_lookups=True` for pre-2.19).

Generally I don't think ansible-lint should ever evaluate templates, but only parse them. (Or are the values needed anywhere? I never really got a clear answer on that; see #4652.)
