# Why dev-proxy

Charles and Proxyman are good tools. They are also mouse-driven. That is the
problem this project removes.

## The agent workflow breaks at the GUI

You can ask a coding agent to change code. You cannot ask it to see what the
app sent, or to make an API return an empty list. Those actions live behind a
GUI that the agent cannot touch. So you become a screenshot relay. You ferry
payloads between the proxy window and the chat by hand.

dev-proxy moves the same capabilities into two plain files:

| File | Purpose |
|---|---|
| `var/flows.jsonl` | Every request, one JSON line each — what the app did |
| `rules/rules.json` | What to change about the traffic — read fresh on every request |

A human and an agent can both read and write files. That is the entire trick.
The included Claude Code skill teaches the agent the recipes, so "mock this
endpoint and show me the empty state" just works.

## Everyday friction, compared with Charles

| Point | Charles | dev-proxy |
|---|---|---|
| Connection | Mac and phone must share a network | The USB cable that `adb` already uses |
| License | Paid after the trial | Free, MIT |
| Recovery | Can get silently stuck mid-session | `proxyctl restart` is one command |
| Control | Mouse and dialogs | One CLI, two files, natural language through Claude |
| Scripting | Limited | Everything is a file or a command |

## Feature map

| Rule action | Charles equivalent | What it does |
|---|---|---|
| `map_local` | Map Local | Serve a response from a file |
| `map_remote` | Map Remote | Send a request somewhere else |
| `body_replace` | Rewrite | Regex-replace in a body |
| `set_header` | Rewrite | Add or drop headers |
| `block` | Block List | Kill the connection, or return an error |
| `delay` | Throttle | Add latency |
| `status` | — | Force a status code |
| `json_patch` | — | Change one field, keep the rest live |

`json_patch` has no Charles equivalent, and it is the one you use most. Map
Local means you capture a 200 KB payload and edit it by hand. `json_patch`
flips one key on the real live response and leaves the other 359 keys
untouched.

## Example: check an empty state

By hand:

```bash
proxyctl rules add --json '{
  "id": "empty_feed",
  "match": {"host": "api\\.example\\.com", "path": "/feed"},
  "action": {"type": "json_patch", "set": {"data.items": []}}
}'
```

Reload the screen on the phone. The feed is empty. No rebuild, no restart.

Through Claude, the same test is one sentence:

> "Make the feed endpoint return an empty list so I can see the empty state."

## Example: find a slow call

```bash
proxyctl flows --min-ms 2000        # only the slow ones
proxyctl show 57                    # headers, timing, body preview
```

Or ask:

> "This screen is slow — which call takes the longest?"

## This is real, not a promise

An agent ran these flows end to end on a real phone. It changed a live HTTPS
response with `json_patch`, and it forced the same endpoint to return a 503.
See [REPORT.md](../REPORT.md) for the full run.
