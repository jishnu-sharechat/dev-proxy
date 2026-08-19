# How it works

You do not need this page for daily use. Read it when you want to know what
runs behind the commands.

## The parts

```
phone ──USB/adb reverse──▶ mitmdump (port 8080)
                              │
                              ├─ addon/claude_addon.py   applies rules, records flows
                              │      ├─ reads  rules/rules.json   (re-read on change)
                              │      ├─ writes var/flows.jsonl    (one JSON line per flow)
                              │      └─ writes var/bodies/*       (full bodies)
                              │
bin/proxyctl ─────────────────┘  starts/stops everything, queries the files
proxyctl web  ──▶ a small HTTP server (port 8090) for webui/index.html + JSON routes
```

[mitmproxy](https://mitmproxy.org) does the hard part: TLS interception and
HTTP parsing. This repo is the rules engine, the machine-readable log, and
the ergonomics around both.

## The life of a request

1. The app opens a connection. The device's global `http_proxy` setting
   points at `127.0.0.1:8080` on the phone.
2. `adb reverse` carries that phone-local port to the Mac over USB. No shared
   Wi-Fi network is needed.
3. mitmdump terminates TLS with its own CA and hands the flow to the addon.
4. The addon matches the request against the rules, in file order. A
   `map_local` or `block` rule answers directly. A `map_remote` rule rewrites
   the target. Other rules mutate the request or the response.
5. The addon writes one JSON line to `var/flows.jsonl` and saves the bodies
   under `var/bodies/`. The line records which rules fired, and whether a
   patch did not apply.

## Rule hot-reload

The addon checks the mtime of `rules/rules.json` on every request and
re-parses the file when the mtime changed. That is why a rule edit needs no
restart. `proxyctl` writes the file atomically (write to a temp file, then
rename), so a request never sees a half-written file.

`map_local` reads the mapped file's bytes on every matching request. That is
why an edit to a mapping file shows up on the next hit.

## The certificate

HTTPS interception works only when the app trusts the mitmproxy CA.

- `proxyctl cert` pushes the CA to the phone's Downloads folder and opens the
  installer. Android blocks adb from writing to the user CA store, so the
  final four taps are manual, once per device.
- A debuggable build with `<certificates src="user" />` in its network
  security config trusts that user CA. A release build does not. That is an
  Android security guarantee, not a bug.
- Google and Play hosts pin their own certificates. Their flows show
  `client TLS failed` and that is expected.
- On an emulator or a rooted device, `proxyctl cert system` installs the CA
  into the system store instead (bind-mount on Android 14+).

## The device wiring

`proxyctl device on` does three things:

1. `adb reverse tcp:8080 tcp:8080` — the USB tunnel.
2. `settings put global http_proxy 127.0.0.1:8080` — the global proxy.
3. A bypass list for `localhost` and friends — otherwise the proxy eats React
   Native's Metro connection and the JS bundle never loads.

The reverse tunnel dies when the adb server restarts or the cable
re-enumerates, while the phone keeps its proxy setting. Traffic then goes
nowhere. `proxyctl status` flags this state, and most commands repair the
tunnel automatically.

## The flow id sequence

Ids continue across proxy restarts: on start, the addon scans the existing
log for the highest id. `proxyctl clear` deletes the log, and the addon then
restarts the sequence at 1, exactly once, even when a burst of requests races
the reset.

## The dashboard

`proxyctl web on` starts a small Python HTTP server. It serves the repo as
static files — the page polls `var/flows.jsonl` and `rules/rules.json`
directly — plus a few JSON routes for actions that must touch state:
clear, rule toggle, app restart, device list, device disconnect, version.

The server binds to `127.0.0.1` only. Mutating routes reject cross-site
browser requests via the `Sec-Fetch-Site` header. Every response carries
`Cache-Control: no-store`, so a plain refresh always shows the current UI.

## The Claude Code skill

The skill is not an MCP server. There is no extra process or protocol. It is
a markdown file, `skill/SKILL.md`, that teaches Claude which `proxyctl`
commands to run and how to read the two data files. `install.sh` (and
`proxyctl update`) generate it into `~/.claude/skills/dev-proxy/` with the
repo path substituted. Claude runs the same CLI you run by hand.

## Files on disk

| Path | What it holds |
|---|---|
| `var/flows.jsonl` | One JSON line per captured flow |
| `var/bodies/` | Full request/response bodies, one file each |
| `var/flows.mitm` | The raw mitmproxy dump; the source for HAR export |
| `var/mitm.log` | mitmproxy's own log |
| `var/addon.log` | Rule warnings, e.g. a `json_patch` that did not apply |
| `var/ready` | Written when the addon is loaded; `proxyctl start` waits for it |
| `var/update_check.json` | The cached once-a-day update check |
| `rules/rules.json` | The rules and the capture filter |
| `maps/` | Mapping files served by `map_local` rules |

`var/` holds real credentials: session tokens, auth headers, user ids. The
directory is gitignored. Keep it that way, and never paste flows into a
public issue.

Do not `rm` files in `var/` while the proxy runs. The process holds them
open, so writes vanish into an unlinked inode. Use `proxyctl clear`.
