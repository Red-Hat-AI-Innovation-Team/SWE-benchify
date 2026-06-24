`ansible-galaxy collection list` fails
##### SUMMARY
When running `ansible-galaxy collection list` on an Ansible 2.10.4 install, I get an error:
```
ERROR! - None of the provided paths were usable. Please specify a valid path with --collections-path
```
1. When trying to specify `--collections-path` (`ansible-galaxy collection list --collections-path .`) it errors out with `ansible-galaxy: error: unrecognized arguments: --collections-path`.
2. Shouldn't it just work and show the collections installed (in this case: no collections installed manually, only some in /usr/local/lib/python3.7/dist-packages/ansible_collections/ - so without #72940 it should be an empty list)?

##### ISSUE TYPE
- Bug Report

##### COMPONENT NAME
ansible-galaxy

##### ANSIBLE VERSION
```paste below
ansible-base 2.10.4
```

**Repository:** `ansible/ansible`
**Base commit:** `2cedaa24b6b0d7cbe691f8aae0f23764ccdb38dd`

## Hints

Files identified in the description:
* `lib/ansible/galaxy`

If these files are incorrect, please update the `component name` section of the description or use the `!component` bot command.

[click here for bot help](https://github.com/ansible/ansibullbot/blob/master/ISSUE_HELP.md)
<!--- boilerplate: components_banner --->

note: we have duplicate options for collection paths, with different spellings.

There are several things going on here:

1. We have incorrect/inconsistent options that need to be corrected: `--collections-path` vs `--collection-path`
2. #72940 was just merged yesterday and will be in the next release.
3. What is the value of `.` in your command line? The value of `--collections-path` replaces the list of default paths. 

@samdoran the intention of `.` was to give it a path so it stops complaining that none of the provided paths are usable.

One other thing that was brought up: should this be a warning not an error?

@samdoran I would expect it to be a warning. "The list is empty" is a valid answer, not an error.

Well, if there are zero valid paths, then it's an error, I guess. If there are any legitimate paths, then empty list would make sense to say "the list is empty" w/o erroring out, I guess.

If the list is supposed to be empty, why should there be legitimate paths? It should only be an error if you actually need at least one path to exist (f.ex. while installing).

The list of paths to search won't be empty by adding `-p .`. I doubled checked the behavior. Paths passed to `-p` are combined with the default `COLLECTIONS_PATHS`.

Each path is examined for a `collections` subdir. If none of the paths provided contain a `collections` sub dir, then an error is produced. Whether this should be an error or a warning is debatable. I'm not convinced this should silently produce no output, though.

I believe the reason this was made an error rather than a warning was an error also shows the command help output.

I've been going round and round trying to work out the desired behavior. I'm going to have to look again tomorrow.

I want to say something like `env ANSIBLE_COLLECTIONS_PATHS='' ansible-galaxy collection list` should silently list nothing, but I think that may depend on the presence of external dirs and whether or not they contain an `ansible_collections` subdir.

I should mention that this bug seems to also happen with current stable 2.14.5 and is impacting 
 https://github.com/ansible/ansible-compat/pull/265

Such things should never say "ERROR". I got it on a freshly installed Ansible on running `ansible-galaxy collection list` which made me google and find this ticket to verify I don't have a broken installation or something and it's just the list is empty.

And it's not about "error" or "warning" (the latter is as much confusing), it's about telling the user clearly what's going on and whether he's done something wrong or not.

This just bit me once again. `ansible-galaxy collection list --format json` failing in a container where ansible-core was just installed, but no collection is present. I stlil cannot imagine why on earth this should result in an error.
