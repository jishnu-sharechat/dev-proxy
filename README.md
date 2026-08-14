# dev-proxy

**Charles Proxy, but runs using natural language in Claude.**

Mock an API, force a 500, add 3s of latency, or flip a server-driven feature
flag — by asking your agent to do it instead of clicking through dialogs.

```bash
in the splashScreenConfig, mock my_imaginary_enabled to true.
```

Reload the screen on your phone. The feed is empty. No restart, no rebuild.

---

## Why this exists

Charles and Proxyman are excellent. They are also **mouse-driven**, and that is
the whole problem.

They also carry real, everyday friction of their own: Charles only intercepts
once your Mac and phone share a network, needs a license key past the trial,
and has a habit of getting silently stuck mid-session. dev-proxy runs over the
same USB cable `adb` already uses — no network requirement, no license, and if
it ever wedges, `proxyctl restart` is one command away.

Once you start pairing with a coding agent, the workflow breaks in a specific
way. You can ask the agent to change code. You cannot ask it to *see what the
app actually sent*, or to *make the API return an empty list so we can check the
empty state*. Those live behind a GUI it cannot touch. So you become a
screenshot relay, ferrying payloads back and forth by hand.

dev-proxy moves the same capabilities behind two plain files:

| File | Purpose |
|---|---|
| `var/flows.jsonl` | Every request, one JSON line each — what the app *did* |
| `rules/rules.json` | What to change about it — read fresh on every request |

Files are something both a human and an agent can read and write. That is the
entire trick. It ships with a [Claude Code skill](#the-claude-code-skill), so
"mock this endpoint and show me the empty state" just works.

Under the hood it is [mitmproxy](https://mitmproxy.org) doing the hard part.
This repo is the rules engine, the machine-readable log, and the ergonomics.

---

## What you get

| Rule action | Charles equivalent | What it does |
|---|---|---|
| `map_local` | Map Local | Serve a response from a file |
| `map_remote` | Map Remote | Send a request somewhere else |
| `body_replace` | Rewrite | Regex-replace in a body |
| `set_header` | Rewrite | Add or drop headers |
| `block` | Block List | Kill the connection, or return an error |
| `delay` | Throttle | Add latency |
| `status` | — | Force a status code |
| `json_patch` | — | **Change one field, keep the rest live** |

`json_patch` is the one with no Charles equivalent, and the one you will
actually use. Map Local means capturing a 200KB payload and hand-editing it.
`json_patch` flips `payload.abTestKeys.NewFeed` to `variant-2` and leaves the
other 359 keys untouched, on the real live response.

Plus: a live web dashboard, HAR export, request replay, and filters over the
captured log.

---

## Requirements

1. **macOS or Linux**, Python 3.9+, `adb` on your PATH.
2. **A debuggable build of your app.** Release builds trust only system CAs, so
   they cannot be intercepted. That is Android working correctly, not a bug.
3. **Your app must trust user CA certificates.** Add this to
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

---

## Setup

```bash
brew install mitmproxy          # or: pipx install mitmproxy
git clone git@github.com:jishnu-sharechat/dev-proxy.git
cd dev-proxy
./install.sh                    # symlinks proxyctl, installs the Claude skill
```

`install.sh` creates `config.json` for you if it doesn't already exist. Point
it at your app — set `"package"` in `config.json` to your app id — then:

```bash
proxyctl start
proxyctl device on                     # adb reverse + set the device proxy
proxyctl cert                          # pushes the CA, opens the installer
```

`proxyctl cert` ends in **four taps on the phone**: Downloads →
`mitmproxy-ca.crt` → OK → "Install anyway". Android does not let adb write to
the user CA store, so this part is unavoidably manual. Once per device.

Then confirm it worked:

```bash
proxyctl cert verify
```

```
ok HTTPS decryption works. The certificate is trusted. 39/41 HTTPS flows decrypted.
  decrypted hosts: api.example.com, cdn.example.com
```

On an emulator with a writable system image, `proxyctl cert system` does it with
zero taps.

---

## The 30-second tour

```bash
proxyctl flows                       # what just happened
proxyctl flows --host api.example    # only your backend
proxyctl flows --status 500          # only the failures
proxyctl flows --min-ms 2000         # only the slow ones
proxyctl show 57                     # headers + body of one call
proxyctl body 57 resp                # prints a file path, for big payloads
proxyctl tail                        # follow live
```

`proxyctl body` printing a *path* rather than 200KB of JSON is deliberate — it
keeps huge payloads out of an agent's context window.

Turn a real response into an editable mock:

```bash
proxyctl mock 57 --name feed   # writes maps/feed.json + a map_local rule
$EDITOR maps/feed.json         # change whatever you want
```

Reload the screen. You are now served your edited version.

Clean up when you're done:

```bash
proxyctl rules disable empty_feed   # keep for later
proxyctl rules rm empty_feed        # delete
proxyctl device off                 # stop hijacking the phone's traffic
```

---

## Watching it live

Two views, deliberately different.

**The dashboard** — `proxyctl web on --open` → `http://127.0.0.1:8090/webui/`

Flow list on the left, inspector on the right. Shows exactly what
`proxyctl show` would print, live, and tags any flow a rule touched. No login.
`#42` in the URL deep-links to flow 42, so you can paste one call into Slack.

**mitmproxy's own UI** — `proxyctl restart --web` → prints a URL with a token

The full thing: intercept, breakpoints, replay. Use it when you need those.

They can't share one page — mitmweb sends `X-Frame-Options: DENY` and refuses to
be framed. Two windows.

---

## Rules reference

Each rule needs a `match` and one `action` (or a list under `actions`). Every
matching rule applies, in order. Edits take effect on the **next request** — the
proxy re-reads the file every time, so never restart it for a rule change.

Match on: `host`, `path`, `url`, `method`, `req_body`, `req_header`. Values are
regexes (escape your dots), or globs with `*`, or a list of either.

```bash
# Slow, then fail — test a spinner and an error path at once
proxyctl rules add --json '{
  "id": "flaky",
  "match": {"path": "/api/v1/like"},
  "actions": [
    {"type": "delay", "response_ms": 3000},
    {"type": "status", "code": 503, "body": "{\"error\":\"try later\"}"}
  ]
}'

# Send one host at your local backend
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

### json_patch refuses paths that don't exist

`set` only changes a field that is already there. A missing path does **not**
apply, and the response passes through untouched.

This is on purpose. Silently creating the node would hand your app a payload the
server never sends, and your test would prove nothing. A typo'd path should
fail loudly, not fake a pass.

When it refuses, you'll see it in two places:

```
proxyctl flows --mocked
  57  200  ...  [exp:json_patch_resp!NOT_APPLIED[payload.abc (does not exist)]]

cat var/addon.log
WARNING rule exp: json_patch set payload.abc did NOT apply. Add "create": true …
```

Adding a field on purpose? `"create": true` for nested paths, or `merge` for
top-level keys.

### Quieting the log

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

Set `include_hosts` to watch one backend and ignore everything else. Image and
video CDNs will otherwise bury your API calls.

---

## Things that will bite you

Collected the hard way. Most of these cost real debugging time.

- **The device proxy is global.** Every app on the phone routes through it, so
  others throw certificate errors until they trust your CA. `proxyctl device off`
  when you're done.
- **`adb reverse` dies silently** when the adb server restarts or the cable
  re-enumerates, while the phone keeps its proxy setting. Traffic then goes
  nowhere. `proxyctl status` flags this, and `app restart` repairs it.
- **`localhost` must bypass the proxy.** Otherwise the global proxy eats React
  Native's Metro connection on port 8081 and your JS bundle never loads. The
  default `proxy_bypass` handles it.
- **Google and Play hosts won't decrypt.** They pin their own certificates. A
  `client TLS failed` row for `googleapis.com` is expected, not broken.
- **QUIC / HTTP-3 skips an HTTP proxy entirely.** If traffic is missing rather
  than failing, suspect this.
- **`client TLS failed` on *your* host** means the app rejected the CA — a
  release build, or a missing `network_security_config`. It does not mean the
  request itself failed.
- **Debug builds may register more than one launcher activity.** LeakCanary does
  this, and `monkey` will cheerfully start *that* instead of your app.
  `proxyctl app restart` resolves the real one.
- **Don't `rm` anything in `var/` while the proxy runs.** The process holds those
  files open, so writes vanish into an unlinked inode. Use `proxyctl clear`.
- **`proxyctl har` covers a whole proxy run.** Restart first if you want a clean
  export.
- **Not everything is JSON.** protobuf endpoints exist, and `json_patch` can't
  touch them. Use `map_local` or `status`.
- **`var/` holds real credentials.** Session tokens, auth headers, user IDs. It
  is gitignored. Keep it that way, and don't paste flows into a public issue.

---

## The Claude Code skill

This isn't an MCP server — there's no extra process or protocol to run. It's a
[Claude Code Skill](https://code.claude.com/docs/en/skills): a
markdown file, `skill/SKILL.md`, that teaches Claude which `proxyctl` commands
to run and how to read the two data files above. `./install.sh` generates it
into `~/.claude/skills/dev-proxy/`. Claude ends up running the exact same CLI
you would by hand — it just knows the recipes.

After that, this kind of thing works:

> "What does the app call when I open the profile tab?"
>
> "Make the feed endpoint return an empty list so I can see the empty state."
>
> "This screen is slow — which call is taking the longest?"
>
> "Force the payment API to 500 and check we show the retry sheet."

It knows to filter before dumping, to open body files by path instead of pasting
them, to verify a rule actually applied, and to clean up its rules afterward.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: `bin/proxyctl` is the
CLI, `addon/claude_addon.py` is the rules engine, and there's a manual test
script because mocking mitmproxy is more trouble than running it.

## License

MIT — see [LICENSE](LICENSE).
