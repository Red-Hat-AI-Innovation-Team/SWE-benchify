SQLite `RemoveVolume` does not verify a volume was actually removed
### Issue Description

The `RemoveVolume` function in SQLite does not validate the number of rows deleted, so it can return no error if no volume was actually removed. This should be fixed - we need to check that only 1 row was removed, and error otherwise.

### Steps to reproduce the issue

N/A


### Describe the results you received

N/A

### Describe the results you expected

N/A

### podman info output

```yaml
N/A
```

### Podman in a container

No

### Privileged Or Rootless

None

### Upstream Latest Release

Yes

### Additional environment details

Additional environment details

### Additional information

Additional information like issue happens only occasionally or issue happens with a particular architecture or on a particular setting

**Repository:** `containers/podman`
**Base commit:** `9ac300c6af5192c4ecd9cc1fcb2399f321575858`

## Hints

/assign

@akervald I would like to work on this, are you still looking at this issue?

@osullivandonal go ahead :)

/assign
