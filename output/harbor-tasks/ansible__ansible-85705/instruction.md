ansible_lvm.lvs fact assumes that logical volume names are unique
### Summary

I have a system where I am trying to confirm through Ansible facts that a logical volume `/dev/vg_name/var` does not exist, which I would expect to _not_ find in `ansible_lvm.lvs` on this system however, the volume `/dev/vg_other_name/var` exists.  Therefore, there is no way to tell whether the volume I am interested in exists.

`ansible_lvm.lvs` should have been a list of dictionaries (with an extra key of `lv:`) rather  than a dictionary of dictionaries.  Obviously it can't be "corrected" now, but another fact (`ansible_lvm.lvs_list`?) could be created that would not depend upon this assumption.

### Issue Type

Feature Idea

### Component Name

setup

### Additional Information

<!--- Paste example playbooks or commands between quotes below -->
```yaml (paste below)
- vars:
    vg: vg_name
    lv: lv_name
  debug:
      var: ansible_lv.lvs_list |
           selectattr('vg', 'eq', vg) |
           selectattr('lv', 'eq', lv) != []
```


### Code of Conduct

- [x] I agree to follow the Ansible Code of Conduct

**Repository:** `ansible/ansible`
**Base commit:** `7b1644e0b3f69cd91c4c973d2e4ce12a8c29c764`

## Hints

Files identified in the description:

* [`lib/ansible/modules/setup.py`](https://github.com/ansible/ansible/blob/devel/lib/ansible/modules/setup.py)

If these files are incorrect, please update the `component name` section of the description or use the [component](https://github.com/ansible/ansibotmini#commands) bot command.

<!--- boilerplate: components_banner --->
