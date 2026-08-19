# dev-proxy

**Charles Proxy, but runs using natural language in Claude.**

Mock an API, force a 500, add 3 seconds of latency, or flip a server-driven
feature flag — by asking your agent instead of clicking through dialogs.

```
in the splashScreenConfig, mock my_imaginary_enabled to true.
```

Reload the screen on your phone. The change is live. No restart, no rebuild.

Under the hood it is [mitmproxy](https://mitmproxy.org). This repo adds a
rules engine, a machine-readable flow log, a CLI (`proxyctl`), a live web
dashboard, and a Claude Code skill that drives all of it.

---

## Documentation

| Page | Read it for |
|---|---|
| [Why dev-proxy](docs/why-dev-proxy.md) | The pitch: how it compares with Charles, with example usage |
| [Manual](docs/manual.md) | Every command and rule action, with examples |
| [How it works](docs/how-it-works.md) | What runs behind the scenes: mitmproxy, the addon, the files |
| [FAQ](docs/faq.md) | The sharp edges, collected the hard way |

---

## Quick start

```bash
brew install mitmproxy          # or: pipx install mitmproxy
git clone git@github.com:jishnu-sharechat/dev-proxy.git
cd dev-proxy
./install.sh                    # symlinks proxyctl, installs the Claude skill
```

Set `"package"` in `config.json` to your app id, then:

```bash
proxyctl setup                  # start + wire the device + push the CA
proxyctl cert verify            # confirm HTTPS decryption works
proxyctl web on --open          # the live dashboard
```

`proxyctl setup` ends with four taps on the phone to trust the CA. You do
that once per device. Your app must be a debuggable build that trusts user
CAs — see the [manual](docs/manual.md#requirements).

## The 30-second tour

```bash
proxyctl flows --host api.example    # what the app called
proxyctl show 57                     # one call in full
proxyctl mock 57 --name feed         # serve that response from an editable file
proxyctl map api.example.com /v1/feed  # same, without a captured flow
proxyctl rules add --json '{
  "id": "empty_feed",
  "match": {"host": "api\\.example\\.com", "path": "/feed"},
  "action": {"type": "json_patch", "set": {"data.items": []}}
}'
proxyctl device off                  # stop hijacking the phone when done
proxyctl update                      # pull the latest dev-proxy
```

## The Claude Code skill

This is not an MCP server — no extra process, no protocol. It is a
[Claude Code Skill](https://code.claude.com/docs/en/skills): a markdown file
that teaches Claude which `proxyctl` commands to run. `./install.sh`
generates it into `~/.claude/skills/dev-proxy/`. After that, this works:

> "What does the app call when I open the profile tab?"
>
> "Make the feed endpoint return an empty list so I can see the empty state."
>
> "Force the payment API to 500 and check we show the retry sheet."

The skill filters before it dumps, opens body files by path instead of
pasting them, verifies that a rule actually applied, and cleans up its rules
afterwards. An agent ran these flows end to end on a real phone — see
[REPORT.md](REPORT.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: `bin/proxyctl` is
the CLI, `addon/claude_addon.py` is the rules engine, and `test/run.sh`
drives a real proxy because mocking mitmproxy is more trouble than running
it.

## License

MIT — see [LICENSE](LICENSE).
