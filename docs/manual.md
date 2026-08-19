# Manual

Everything you can do with dev-proxy, one section per task.

## Requirements

1. macOS or Linux, Python 3.9+, `adb` on your PATH.
2. A debuggable build of your app. A release build trusts only system CAs, so
   you cannot intercept it. That is Android working correctly.
3. Your app must trust user CA certificates. Add this to
   `res/xml/network_security_config.xml`:

```xml
<network-security-config>
    <debug-overrides>
        <trust-anchors>
            <certificates src="user" />
        </trust-anchors>
    </debug-overrides>
</network-security-config>
```

`debug-overrides` applies only to debuggable builds, so this is safe to ship.

## Setup

```bash
brew install mitmproxy          # or: pipx install mitmproxy
git clone git@github.com:jishnu-sharechat/dev-proxy.git
cd dev-proxy
./install.sh                    # symlinks proxyctl, installs the Claude skill
```

`install.sh` creates `config.json` when the file does not exist. Set
`"package"` in `config.json` to your app id. Then:

```bash
proxyctl setup            # start + wire the device + push the CA
```

`proxyctl setup` ends with four taps on the phone: Downloads →
`mitmproxy-ca.crt` → OK → "Install anyway". Android does not let adb write to
the user CA store, so this part is manual. You do it once per device. Then:

```bash
proxyctl cert verify      # confirms HTTPS decryption works
```

On an emulator with a writable system image, `proxyctl cert system` installs
the CA with zero taps.

## Daily control

```bash
proxyctl status           # proxy, device, rules, flow count — start here
proxyctl start            # start the proxy
proxyctl stop             # stop it
proxyctl restart          # stop + start
proxyctl device on        # route device traffic through the proxy
proxyctl device off       # stop routing; the device talks directly again
proxyctl app restart      # force-stop and start the app under test
proxyctl update           # pull the latest dev-proxy and refresh everything
```

`proxyctl status` also checks for updates, at most once a day, and prints a
nudge when the clone is behind `origin/main`.

The device proxy is global. Every app on the phone routes through it. Run
`proxyctl device off` when you finish.

## Read traffic

```bash
proxyctl flows                       # the latest captured calls
proxyctl flows --host api.example    # only your backend
proxyctl flows --status 500          # only the failures
proxyctl flows --errors              # only failed flows
proxyctl flows --min-ms 2000         # only the slow ones
proxyctl flows --mocked              # only flows a rule touched
proxyctl flows --grep sessionId      # full-text search
proxyctl show 57                     # headers + body previews of one call
proxyctl body 57 resp                # prints the file path of the full body
proxyctl paths 57 gamesEnabled       # dotted JSON paths that match a name
proxyctl tail                        # follow new flows live
proxyctl clear                       # reset the log; ids restart at 1
```

`proxyctl body` prints a path instead of the payload. That keeps a 200 KB
JSON body out of a chat window or an agent context.

`proxyctl paths` lists the dotted paths inside a captured JSON response, with
the current values. Use it to verify a field name before you patch it.

## Change traffic

Each rule needs a `match` and one `action` (or a list under `actions`). Every
matching rule applies, in order. The proxy re-reads the file on every
request, so a rule edit takes effect on the next request. Never restart the
proxy for a rule change.

Match on: `host`, `path`, `url`, `method`, `req_body`, `req_header`. Values
are regexes (escape your dots), or globs with `*`, or a list of either.

```bash
# Change one field on the live response
proxyctl rules add --json '{
  "id": "empty_feed",
  "match": {"host": "api\\.example\\.com", "path": "/feed"},
  "action": {"type": "json_patch", "set": {"data.items": []}}
}'

# Slow, then fail — test a spinner and an error path at once
proxyctl rules add --json '{
  "id": "flaky",
  "match": {"path": "/api/v1/like"},
  "actions": [
    {"type": "delay", "response_ms": 3000},
    {"type": "status", "code": 503, "body": "{\"error\":\"try later\"}"}
  ]
}'

# Send one host to your local backend
proxyctl rules add --json '{
  "id": "local_be",
  "match": {"host": "api\\.example\\.com"},
  "action": {"type": "map_remote", "host": "10.0.0.5", "port": 8000, "scheme": "http"}
}'

# Simulate offline for one endpoint
proxyctl rules add --json '{
  "id": "offline",
  "match": {"path": "/sync"},
  "action": {"type": "block", "mode": "kill"}
}'
```

Manage the rules:

```bash
proxyctl rules list
proxyctl rules disable empty_feed    # keep it for later
proxyctl rules enable empty_feed
proxyctl rules rm empty_feed         # delete it
proxyctl rules clear                 # delete all rules
```

## Serve a response from a file

Two ways in. Both end with a `map_local` rule and a file you edit live.

From a captured flow:

```bash
proxyctl mock 57 --name feed    # writes maps/feed.json + a map_local rule
```

From a URL, no capture needed:

```bash
proxyctl map api.example.com /v1/feed --file maps/feed.json
```

`proxyctl map` creates the file when the file is missing. It seeds the file
from the newest captured response for that URL when one exists. Host and
path are literals here. Pass `--regex` for patterns.

Edit the file with any editor. The next matching request serves the new
content. No restart is needed.

## json_patch refuses paths that do not exist

`set` changes a field that is already there. A missing path does not apply,
and the response passes through untouched.

This is on purpose. Silent creation would hand your app a payload the server
never sends, and your test would prove nothing. A typo must fail loudly.

A refused patch is visible in two places:

```
proxyctl flows --mocked
  57  200  ...  [exp:json_patch_resp!NOT_APPLIED[payload.abc (does not exist)]]

cat var/addon.log
WARNING rule exp: json_patch set payload.abc did NOT apply. Add "create": true …
```

To add a field on purpose: `"create": true` for nested paths, or `merge` for
top-level keys.

Verify a field name before you patch it:

```bash
proxyctl flows --url splashScreenConfig     # find the flow id
proxyctl paths 57 gamesenabled              # find the exact dotted path
```

The filter is case-insensitive, so it catches capitalization mistakes.

## The web dashboard

```bash
proxyctl web on --open     # http://127.0.0.1:8090/webui/
proxyctl web off
```

The dashboard polls the flow log once a second. It shows:

- The flow list with filters, next to a detail inspector.
- Copy buttons: cURL and response body on each row, and copy buttons in the
  detail panel.
- The connected devices, with a green dot when traffic can reach the proxy,
  and a disconnect button per device.
- A "restart app" button, and a restart link in the empty state.
- The rules, with a per-rule enable/disable toggle.
- The dev-proxy version, and an "update available" pill when the clone is
  behind.

`#42` in the URL deep-links to flow 42, so you can paste one call into Slack.

mitmproxy's own UI is also available: `proxyctl restart --web` prints a URL
with a token. Use it for intercept and breakpoints.

## Export and replay

```bash
proxyctl har out.har       # export the whole proxy run as HAR
proxyctl replay 57         # send a captured request again, through the rules
```

`proxyctl har` covers the whole current proxy run. Restart the proxy first
when you need a clean export.

## Quiet the log

The `capture` block in `rules/rules.json` filters the log, not the traffic:

```json
{
  "capture": {
    "save_bodies": true,
    "max_body_kb": 1024,
    "exclude_hosts": ["^localhost$", "googleapis\\.com"],
    "include_hosts": []
  }
}
```

Set `include_hosts` to watch one backend and ignore everything else. Image
and video CDNs otherwise bury your API calls.

## config.json reference

| Key | Meaning |
|---|---|
| `port` | Proxy listen port (default 8080) |
| `web_port` | mitmweb UI port (default 8081) |
| `dashboard_port` | Dashboard port (default 8090) |
| `package` | Your app id, e.g. `com.example.app` — required |
| `main_activity` | Launcher activity; auto-detected when empty |
| `adb`, `mitmdump` | Binary paths; auto-detected when empty |
| `proxy_bypass` | Hosts the device must reach directly (Metro on 8081 needs this) |
| `app_hosts` | Your backend host patterns; `cert verify` reports on them |
| `web_password` | mitmweb password; generated on first `--web` start |

## Update dev-proxy

```bash
proxyctl update
```

One command. It pulls the repo fast-forward only, regenerates the installed
Claude skill, and restarts the dashboard server when one runs. Refresh the
dashboard tab afterwards. When the proxy itself runs, run `proxyctl restart`
to load the new addon code.
