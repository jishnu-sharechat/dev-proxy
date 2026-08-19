# FAQ

Collected the hard way. Most of these cost real debugging time.

## No traffic appears at all. Why?

Check these in order:

1. `proxyctl status` must show the device proxy and `adb reverse` as set.
   The reverse tunnel dies silently when the adb server restarts; status
   flags this and most commands repair it.
2. The app must be a debug build. A release build trusts only system CAs.
3. The flow log shows `client TLS failed`: the CA is missing on the device.
   Run `proxyctl cert`.
4. The host sits in `exclude_hosts` in `rules/rules.json`, so the log skips
   it.
5. The call uses QUIC / HTTP-3. Those bypass an HTTP proxy entirely. Traffic
   that is missing rather than failing points here.
6. The app cached the proxy setting. Run `proxyctl app restart`.

## HTTPS rows show `client TLS failed` for Google hosts. Is that broken?

No. Google and Play services pin their own certificates. Those rows are
expected. A `client TLS failed` row for **your** host means the app rejected
the CA — a release build, or a missing `network_security_config`.

## My json_patch rule does nothing.

The path probably does not exist in the response. `json_patch` refuses a
missing path on purpose, and tags the flow with `!NOT_APPLIED`. Check:

```bash
proxyctl flows --mocked
cat var/addon.log
```

Verify the exact field name first with `proxyctl paths <id> <name>`. Add
`"create": true` only when you mean to add a new field.

## Can I edit a mock file while the app runs?

Yes. `map_local` reads the file on every matching request. Edit
`maps/feed.json`, reload the screen, and the app receives the new content.
No restart is needed. See `proxyctl map` in the [manual](manual.md).

## Why does another app on my phone show certificate errors?

The device proxy is global. Every app routes through it, and apps that do
not trust the CA fail. Run `proxyctl device off` when you finish testing.
The dashboard also has a per-device disconnect button.

## The React Native bundle never loads with the proxy on.

`localhost` must bypass the proxy, or the global proxy eats Metro's
connection on port 8081. The default `proxy_bypass` in `config.json` handles
this. Do not remove it.

## proxyctl app restart starts LeakCanary instead of my app.

Debug builds can register more than one launcher activity, and `monkey`
happily starts the wrong one. dev-proxy resolves the real activity and skips
LeakCanary. Set `main_activity` in `config.json` to pin it explicitly.

## My HAR export contains old traffic.

`proxyctl har` covers the whole current proxy run. Run `proxyctl restart`
first when you need a clean export.

## The response is protobuf. Can json_patch edit it?

No. `json_patch` works on JSON bodies only. Use `map_local` or `status` for
`application/x-protobuf` endpoints.

## Can I delete files in var/ by hand?

No, not while the proxy runs. The process holds those files open, so writes
vanish into an unlinked inode. Use `proxyctl clear`.

## Is var/ safe to share?

No. It holds real credentials: session tokens, auth headers, user ids. The
directory is gitignored. Never paste flows into a public issue.

## How do I update dev-proxy?

```bash
proxyctl update
```

It pulls the repo, regenerates the Claude skill, and restarts the dashboard
server. `proxyctl status` also prints a nudge, at most once a day, when the
clone is behind `origin/main`. See the [manual](manual.md#update-dev-proxy).

## The mitmweb token from the log does not work.

Known mitmproxy 12.2.3 issue: the printed auto-token does not match what the
server checks. dev-proxy sets its own `web_password` instead and prints a URL
that works. Use that URL.

## Does dev-proxy work with an emulator?

Yes. Use `proxyctl cert system` on an emulator with a writable system image
to install the CA with zero taps. `10.0.2.2` is already in the default
bypass list.

## Can the dashboard and mitmweb share one page?

No. mitmweb sends `X-Frame-Options: DENY` and refuses to be framed. Use two
windows.
