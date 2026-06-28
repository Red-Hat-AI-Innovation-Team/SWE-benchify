traceutil:  Trace log event names include a random runtime trace ID
### Bug report criteria

- [x] This bug report is not security related, security issues should be disclosed privately via security@etcd.io.
- [x] This is not a support request or question, support requests or questions should be raised in the etcd [discussion forums](https://github.com/etcd-io/etcd/discussions).
- [x] You have read the etcd [bug reporting guidelines](https://github.com/etcd-io/etcd/blob/main/Documentation/contributor-guide/reporting_bugs.md).
- [x] Existing open issues along with etcd [frequently asked questions](https://etcd.io/docs/latest/faq) have been checked and this is not a duplicate.

### What happened?

## Anti-pattern

This issue is limited to one logging entrypoint in `pkg/traceutil/trace.go`. The trace logger builds the zap message from `fmt.Sprintf("trace[%d] %s", traceNum, t.operation)`, where `traceNum` comes from `rand.Int31()`. In structured logging, the event name should be stable; the random trace identifier should be emitted as a structured field value instead of changing the message surface.

## Impact on observability platforms

Each emitted slow-trace log can have a different event name such as `trace[12345] range` or `trace[67890] transaction`. This splits one logical trace event across many message values, increases log-message cardinality, and makes grouping, alerting, and dashboard queries harder. The trace number is also an opaque identifier in the event name rather than a queryable field.



### What did you expect to happen?

## Expected behavior

The log message should be a stable event name such as `trace`, with the random trace number and operation emitted as structured fields.

### How can we reproduce it (as minimally and precisely as possible)?

## How to reproduce

Trigger a slow etcd request path that emits a trace log, then inspect the log message.

### Anything else we need to know?

_No response_

### Etcd version (please run commands below)

3.7.0-alpha.0
commit: 326d5a2e7765d1d918865d2c3897f0a27320db80
git describe: v3.6.0-alpha.0-6966-g326d5a2e7-dirty

### Etcd configuration (command line flags or environment variables)

<details>

# paste your configuration here

</details>


### Etcd debug information (please run commands below, feel free to obfuscate the IP address or FQDN in the output)

<details>

```console
$ etcdctl member list -w table
# paste output here

$ etcdctl --endpoints=<member list> endpoint status -w table
# paste output here
```

</details>


### Relevant log output

```Shell

```

**Repository:** `etcd-io/etcd`
**Base commit:** `315e04328c6a19c107081870e5cdadaa6044d45d`

## Hints

Makes sense.
