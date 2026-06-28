ansible-galaxy installs collections that are not compatible with the running Ansible version
### Summary

Today, if you execute `ansible-galaxy collection install community.docker`, you get version 3.0.1 which is only declaring compatibility with Ansible 2.11+ (see https://github.com/ansible-collections/community.docker/blob/3.0.1/meta/runtime.yml#L6)

However, you get that version also when you're using `ansible-galaxy` from 2.10.

### Issue Type

Bug Report

### Component Name

ansible-galaxy

### Ansible Version

```console
$ ansible --version
2.10.17.post0
```


### Configuration

```console
# if using a version older than ansible-core 2.12 you should omit the '-t all'
$ ansible-config dump --only-changed -t all
```


### OS / Environment

Fedora

### Steps to Reproduce

1. `ansible-galaxy collection install community.docker` on Ansible 2.10

### Expected Results

It to install a version before 3.0 which dropped 2.10 support

### Actual Results

```console
it installs 3.0.1
```


### Code of Conduct

- [X] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `948f8f42d09e9ad1f0582611fa17a6f5ad52a395`

## Hints

Files identified in the description:
* `lib/ansible/galaxy`

If these files are incorrect, please update the `component name` section of the description or use the `!component` bot command.

[click here for bot help](https://github.com/ansible/ansibullbot/blob/devel/ISSUE_HELP.md)
<!--- boilerplate: components_banner --->

Oh, and this is tagged 2.10, but obviously will apply to any newer version of Ansible, once collections start dropping support for them.

There is only a runtime check if a collection `requires_ansible` as you could install collections for execution with a different version of Ansible than the one doing the install. This is specially common in the context of EEs, so if we wanted to add this restriction it would require an extra toggle (something like `--check-required-ansible-version`)

While I personally would do the toggle the other way round (`--allow-unsupported-ansible-version` or whatever), this particular decision is up to you.
And yes, this needs to be overridaable for sure :)

that would break backwards compatibility, so it would have to default to current behaviour

Do the galaxy APIs present this data now, when we added this feature they did not. Since it was a core only feature it only was checked at runtime, otherwise we'd have to download every collection version to determine the value of `requires_ansible`.

I can confirm that community galaxy does not expose this.

looking at https://github.com/ansible/galaxy_ng/commit/1215271a15d1945065844839b17ac105c35df50b I'd say galaxy-ng has this data.

we know they have the data, the problem is being able to query it over the web API

Assuming that we eventually add this functionality, there are a few things to note:

1. It will only work for galaxy servers that return `requires_ansible` in API responses, so for at least the time being, the change would not benefit users of community galaxy
2. The change would not be backported, and would only appear in a new version of ansible-core
3. We're pretty late in the dev cycle for 2.14, so I don't really see this being handled until a future release unless things happen to fall into place.  I have no prioritization on this, so I cannot really state by which version it would be included.

I guess 1 would be yet another motivation for community galaxy to be upgraded to galaxy_ng :-)

2 is unfortunate, but has already been a problem now because Ansible 2.9 does ignore meta/runtime.yml completely, so you don't get a runtime warning there. (That might have avoided some unnecessary 'bug reports' for community.general when it dropped 2.9 support ;-) ). With such a feature in, at least at some point in the future (when folks stopped using too old ansible-core versions) everything will be better. (Like the good old pip versions in some ancient OS containers that do not understand Python requirements for PyPi packages, and thus require manual tests/utils/constraints.txt entries once a random dependency drops Python 2 support...)
