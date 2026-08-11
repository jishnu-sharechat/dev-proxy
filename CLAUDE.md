# dev-proxy

Bootstrap a fresh clone. Use this file whenever you're asked to set dev-proxy
up, or handed this repo's link with no other context — that is exactly the
scenario it exists for.

Once setup finishes, hand off to the Claude Code Skill this installs
(`skill/SKILL.md`) for day-to-day driving. This file's job ends at the last
step below.

## Check prerequisites

```bash
command -v python3; command -v mitmdump; command -v adb
```

Install whatever's missing:

- `mitmdump` missing → `brew install mitmproxy` (`pipx install mitmproxy` off macOS).
- `adb` missing → `brew install --cask android-platform-tools`. Backend
  engineers usually don't have this installed — install it, don't just warn
  about it.
- `python3` missing → tell the user. Don't guess a fix; it varies too much by
  machine.

## Run the installer

```bash
./install.sh
```

Safe to re-run. Symlinks `proxyctl` onto the PATH, generates the skill at
`~/.claude/skills/dev-proxy/`, and creates `config.json` from the template if
one doesn't exist yet.

## Fill in config.json

`package` and `main_activity` can't be auto-detected. Ask the user for their
app's package id (e.g. `com.example.app`) and main activity's fully-qualified
name (`pkg/.ActivityName` form), then edit those two fields in `config.json`
directly.

## Connect the device

Confirm one is visible first:

```bash
adb devices
```

If nothing shows up, tell the user to plug in the phone and enable USB
debugging (Settings → About phone → tap Build number 7 times → Developer
options → USB debugging). You cannot do this for them.

## Bring the proxy up

```bash
proxyctl setup
```

Starts the proxy, wires the device (`adb reverse` plus the device's global
HTTP proxy), and pushes the CA certificate. It stops there on purpose — the
next step needs a human.

## Hand off the 4 manual taps

Tell the user: Downloads → `mitmproxy-ca.crt` → OK → "Install anyway".
Android blocks `adb` from writing to the user CA store, so you cannot do this
part. Wait for them to confirm, then:

```bash
proxyctl cert verify
```

## Open the dashboard

```bash
proxyctl web on --open
```

Setup is done. Switch to `skill/SKILL.md` for everything from here — reading
traffic, adding rules, cleaning up.
