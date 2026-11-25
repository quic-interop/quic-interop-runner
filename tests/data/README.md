# Test captures

Each directory `<protocol>/<test case>/<server>_<client>` holds the logs of a test
case, from a run of the interop runner between these implementations:

* `trace_node_left.pcap` and `trace_node_right.pcap`: the captures on the client
  and server side
* `client_keys.log` and `server_keys.log`: the TLS key logs of the endpoints, when
  they wrote one

To keep them small, some captures were trimmed with `editcap`. A trimmed capture
gives the same check results and messages as the full one, unless it is only used
by the tests of the `TraceAnalyzer`.

Every fixture stays in the git history, so aim for less than 100 KB per fixture,
trimming its captures when the check allows it, and only replace a fixture when
the check it tests changes.
