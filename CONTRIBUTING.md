# Contributing

## The layout

```
bin/proxyctl            The CLI. Everything a human or agent runs. Stdlib only.
addon/claude_addon.py   The mitmproxy addon: rules engine + flow log.
webui/index.html        The live dashboard. One file, no build, no deps.
skill/SKILL.md          The Claude Code skill. install.sh substitutes the path.
rules/rules.json        Live rules. Re-read on every request.
var/                    Runtime output. Gitignored. Holds real credentials.
```

Two processes, and it helps to keep them straight:

- **`proxyctl`** runs, does one thing, exits. It never talks to the running
  proxy over a socket — it edits files.
- **`claude_addon.py`** runs *inside* mitmproxy for the whole session and picks
  up file changes on its own.

That is why a rule change needs no restart, and why the two never need an IPC
channel. Keep it that way.

## Setup

```bash
brew install mitmproxy
git clone git@github.com:jishnu-sharechat/dev-proxy.git
cd dev-proxy && ./install.sh
```

`bin/proxyctl` and the addon are **standard library only**. mitmproxy ships its
own bundled Python, so the addon cannot import anything you pip install. Please
don't add dependencies.

## Testing

There is no unit test suite. Mocking mitmproxy's flow objects costs more than it
returns, so the tests drive a real proxy against a real local server:

```bash
./test/run.sh
```

It starts a throwaway HTTP server, starts the proxy, exercises every rule action
against it, and asserts on the actual responses. Takes about 20 seconds. Run it
before opening a PR.

If you touch device or certificate handling, that path needs a real phone and the
script skips it. Say so in your PR, and paste the output of:

```bash
proxyctl cert verify
```

## Adding a rule action

1. Add the branch in `_apply_request_action` or `_apply_response_action` in
   `addon/claude_addon.py`.
2. Add the name to `VALID_ACTIONS` in `bin/proxyctl`, and validate its required
   fields in `_validate_rule` — a rule that fails should fail when it is
   *added*, not silently at request time.
3. Tag the flow via `flow.metadata["dp_rules"]`, so it shows up in
   `proxyctl flows --mocked` and in the dashboard.
4. Add a case to `test/run.sh`.
5. Add a row to the action table in `README.md`.

Step 3 matters more than it looks. An action that changes traffic without
leaving a trace is how you lose an afternoon.

## House style

**Fail loudly, never silently.** The nastiest bug this project has had was
`json_patch` quietly *creating* a missing path — the mock looked like it worked
and proved nothing. If a rule cannot do what it was asked, it must refuse and
say so in both `var/addon.log` and the flow tag.

**Assume an agent is reading the output.** Error messages should name the fix,
not just the failure. `proxyctl body` prints a path instead of 200KB of JSON for
exactly this reason.

**Comment the surprises, not the syntax.** The codebase has comments explaining
why start waits for a readiness file, and why `var/` files must not be unlinked
while the proxy runs. Both were real bugs. That is the bar: if the next person
would reasonably remove your line, explain why they shouldn't.

## Please don't

- Commit anything under `var/`. It contains live session tokens.
- Commit `config.json`. It has your absolute paths and a generated password.
- Add a build step to `webui/`. Plain HTML in one file is a feature.
- Add pip dependencies to the addon. mitmproxy's bundled Python can't see them.
