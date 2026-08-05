---
name: dev-proxy
description: Inspect and manipulate Android network traffic through a local mitmproxy. Use for any request about seeing what the app sends or receives, mocking or stubbing an API response, forcing an error or a timeout, adding latency, flipping a server-driven feature flag or experiment, redirecting a host to staging or localhost, or exporting a HAR. This replaces Charles Proxy map-local, map-remote, rewrite, block, and throttle. Triggers on "what does the app call", "mock this endpoint", "map local", "map remote", "make this API fail", "simulate slow network", "simulate offline", "override the response", "change the API response", "intercept traffic", "check the request payload", "why is this call failing", "capture traffic", "export HAR".
---

# dev-proxy

Drive `mitmproxy` to read and change Android network traffic. Everything runs
through one command and two files, so you never need a GUI.

`proxyctl` is on the PATH after `install.sh`. The repo lives at
`__DEVPROXY_HOME__`.

Read `__DEVPROXY_HOME__/README.md` for the full rule reference.

## Check the state first

Always run this before anything else. It shows the proxy, the device, the active
rules, and the flow count in one screen.

```bash
proxyctl status
```

If the proxy is stopped, run `proxyctl start`. If the device proxy is `null`,
run `proxyctl device on`. If HTTPS rows show `client TLS failed`, the CA is not
installed. Tell the user to run `proxyctl cert` and do the 4 taps. You cannot do
those taps. Android blocks adb from writing to the user CA store.

## Read traffic

Do not paste whole payloads into the chat. Filter first, then open one body.

```bash
proxyctl flows --host api.example.com   # find the call
proxyctl show 57                           # headers and previews
proxyctl body 57 resp                      # prints a file path
```

`proxyctl body` gives a path. Open that path with the Read tool. That keeps a
large JSON payload out of the context window.

Useful filters: `--host`, `--url`, `--method`, `--status`, `--errors`,
`--grep`, `--min-ms`, `--last`, `--mocked`, `--json`.

To capture a fresh interaction:

1. Run `proxyctl clear`.
2. Run `proxyctl app restart`, or ask the user to tap the screen you care about.
3. Run `proxyctl flows`.

`proxyctl clear` resets ids to 1, so ids stay short.

## Change traffic

Add a rule, then tell the user to reload that screen in the app. The proxy
rereads the rules file on every request, so never restart the proxy after a rule
change.

Pick the smallest action that answers the question:

- Change a few fields in a real response: `json_patch`. Prefer this.
- Replace a whole response with a file you can edit: `proxyctl mock <id>`.
- Force a failure: `status`, or `block`.
- Test a spinner or a timeout: `delay`.
- Send a host to staging or localhost: `map_remote`.

```bash
proxyctl rules add --json '{
  "id": "empty_feed",
  "match": {"host": "api\\.example\\.com", "path": "/feed"},
  "action": {"type": "json_patch", "set": {"data.items": []}}
}'
```

`match` values are regexes. Escape the dots in a host name.

`json_patch` `set` changes an existing field only. A missing path does not
apply, and the flow log tags the rule with `!NOT_APPLIED`. Check it after you
add a rule:

```bash
proxyctl flows --mocked      # shows which rules fired
cat __DEVPROXY_HOME__/var/addon.log
```

Add `"create": true` when you mean to add a new field. Use `merge` for a new
top level key. Never assume a patch applied. Confirm it in the flow log.

Some endpoints may return `application/x-protobuf`. `json_patch` cannot edit
those. Use `map_local` or `status` instead.

Turn a real captured response into an editable mock:

```bash
proxyctl mock 57 --name feed    # writes maps/feed.json plus a map_local rule
```

Then edit `maps/feed.json` with the Edit tool. The next request serves it.

## Clean up

Always remove the rules you added once the user confirms the test is done. A
forgotten rule looks like a real bug later.

```bash
proxyctl rules disable empty_feed   # keep it for reuse
proxyctl rules rm empty_feed        # delete it
proxyctl device off                 # stop routing device traffic
```

The device proxy is global. Leaving it on breaks other apps on the phone.

## When traffic does not appear

Check these in order.

1. `proxyctl status` shows the device proxy and `adb reverse` are set.
2. The app is a debug build. A release build trusts system CAs only, so you
   cannot intercept it.
3. The flow log shows `client TLS failed`. The CA is missing. Run `proxyctl cert`.
4. The host is in `exclude_hosts` in `rules/rules.json`.
5. The call uses QUIC or HTTP/3. Those bypass an HTTP proxy.
6. The app caches the proxy setting. Run `proxyctl app restart`.
