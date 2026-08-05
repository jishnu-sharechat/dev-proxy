#!/usr/bin/env bash
# Install dev-proxy: put proxyctl on the PATH and register the Claude Code skill.
# Safe to re-run — it overwrites its own symlinks and nothing else.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$HOME/.claude/skills/dev-proxy"

say()  { printf '\033[36m==>\033[0m %s\n' "$1"; }
ok()   { printf '\033[32mok\033[0m %s\n' "$1"; }
warn() { printf '\033[33mnote:\033[0m %s\n' "$1"; }
fail() { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 1; }

# ---------------------------------------------------------------- prequisites
command -v python3 >/dev/null || fail "python3 not found."

if ! command -v mitmdump >/dev/null; then
  fail "mitmdump not found. Install it first:
    brew install mitmproxy      # macOS
    pipx install mitmproxy      # anywhere else"
fi
ok "mitmproxy: $(mitmdump --version 2>/dev/null | head -1)"

command -v adb >/dev/null \
  && ok "adb: $(command -v adb)" \
  || warn "adb not on PATH. Set \"adb\" in config.json, or add the Android SDK platform-tools."

# ------------------------------------------------------------------- proxyctl
chmod +x "$ROOT/bin/proxyctl"

BIN_DIR=""
for candidate in /opt/homebrew/bin /usr/local/bin "$HOME/.local/bin"; do
  if [ -d "$candidate" ] && [ -w "$candidate" ]; then BIN_DIR="$candidate"; break; fi
done

if [ -n "$BIN_DIR" ]; then
  ln -sf "$ROOT/bin/proxyctl" "$BIN_DIR/proxyctl"
  ok "proxyctl -> $BIN_DIR/proxyctl"
  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not on your PATH. Add it to your shell profile." ;;
  esac
else
  warn "No writable bin dir found. Add this to your shell profile instead:
    export PATH=\"$ROOT/bin:\$PATH\""
fi

# ---------------------------------------------------------------------- skill
mkdir -p "$SKILL_DIR"
sed "s|__DEVPROXY_HOME__|$ROOT|g" "$ROOT/skill/SKILL.md" > "$SKILL_DIR/SKILL.md"
ok "Claude Code skill -> $SKILL_DIR/SKILL.md"

# --------------------------------------------------------------------- config
if [ ! -f "$ROOT/config.json" ]; then
  cp "$ROOT/config.example.json" "$ROOT/config.json"
  ok "created config.json"
  warn "Set \"package\" in config.json to your app id before you start."
else
  ok "config.json already exists, left alone"
fi

mkdir -p "$ROOT/var/bodies" "$ROOT/maps"

cat <<EOF

$(printf '\033[1mNext:\033[0m')
  1. Set "package" in config.json to your app id.
  2. proxyctl start
  3. proxyctl device on
  4. proxyctl cert          # then 4 taps on the phone
  5. proxyctl cert verify

  proxyctl web on --open    # the live dashboard
EOF
