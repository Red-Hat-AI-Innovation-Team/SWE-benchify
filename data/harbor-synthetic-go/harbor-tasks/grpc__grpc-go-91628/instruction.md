# Connection establishment hangs indefinitely when a connect deadline or timeout is configured. It seems like the timeout 

**Repository:** grpc/grpc-go
**Base Commit:** b73616d3e1e07c14ff3dc329c226a7576d5fa01d

## Problem Statement

Connection establishment hangs indefinitely when a connect deadline or timeout is configured. It seems like the timeout context is never actually being applied during the connection attempt, so instead of failing fast, the dial just blocks forever.

Might be related to the changes in #9171.

```
--- FAIL: Test (26.34s)
    --- FAIL: Test/CloseConnectionWhenServerPrefaceNotReceived (20.04s)
        tlogger.go:133: INFO clientconn.go:1837 [core] original dial target is: "127.0.0.1:57482"  (t=+385µs)
        tlogger.go:133: INFO clientconn.go:516 [core] [Channel #29] Channel created for target "127.0.0.1:57482"  (t=+405.917µs)
        tlogger.go:133: INFO clientconn.go:247 [core] [Channel #29] parsed dial target is: resolver.Target{URL:url.URL{Scheme:"dns", Opaque:"", User:(*url.Userinfo)(nil), Host:"", Path:"/127.0.0.1:57482", Fragment:"", RawQuery:"", RawPath:"", RawFragment:"", ForceQuery:false, OmitHost:false}}  (t=+426.292µs)
        tlogger.go:133: INFO clientconn.go:248 [core] [Channel #29] Channel authority set to "127.0.0.1:57482"  (t=+441.375µs)
        tlogger.go:133: INFO clientconn.go:620 [core] [Channel #29] Channel Connectivity change to CONNECTING  (t=+477.292µs)
        tlogger.go:133: INFO resolver_wrapper.go:211 [core] [Channel #29] Resolver state updated: {
              "Addresses": [
                {
                  "Addr": "127.0.0.1:57482",
                  "ServerName": "",
                  "Attributes": null,
                  "BalancerAttributes": null,
                  "Metadata": null
                }
              ],
              "Endpoints": [
                {
                  "Addresses": [
                    {
                      "Addr": "127.0.0.1:57482",
                      "ServerName": "",
                      "Attributes": null,
                      "BalancerAttributes": null,
                      "Metadata": null
                    }
                  ],
                  "Attributes": null
                }
              ],
              "ServiceConfig": null,
              "Attributes": null
            } (resolver returned new addresses)  (t=+543.792µs)
        tlogger.go:133: INFO balancer_wrapper.go:121 [core] [Channel #29] Channel switches to new LB policy "pick_first"  (t=+569.084µs)
```

The test expects the connection to be torn down quickly when the server never sends its preface, but it just sits in CONNECTING until the test times out at 20 seconds.

## Task

Fix the bug described above. The repository is checked out at the base
commit in `/testbed`. Make your changes there.

Do NOT modify any files in test directories (test/, tests/, e2e/, testing/, testdata/).
Do NOT modify any test files (*_test.go, test_*.py, *_test.py, *_test.rs, *.test.*, *_spec.*, *.spec.*).
Focus on making the minimal change needed to fix the described issue.
