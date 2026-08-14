#!/usr/bin/env bash
# Integration tests. Drives a real proxy against a real local server.
#
# No mocks: mitmproxy's flow objects are more work to fake than to run, and the
# bugs worth catching here (buffering, file races, content-length, TLS) only
# happen for real.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROXYCTL="$ROOT/bin/proxyctl"
PORT=8399          # not the default, so we never touch a real session
SRV_PORT=9399
PASS=0; FAIL=0

green() { printf '\033[32m%s\033[0m\n' "$1"; }
red()   { printf '\033[31m%s\033[0m\n' "$1"; }

check() { # check <name> <expected-substring> <actual>
  if [[ "$3" == *"$2"* ]]; then
    green "  PASS  $1"; PASS=$((PASS+1))
  else
    red   "  FAIL  $1"; red "        want: $2"; red "        got:  $3"; FAIL=$((FAIL+1))
  fi
}

# ------------------------------------------------------------------ isolation
# Use a scratch DEVPROXY_HOME so a contributor's real flows and rules are
# never touched by a test run.
WORK="$(mktemp -d)"
mkdir -p "$WORK/rules" "$WORK/var/bodies" "$WORK/maps"
export DEVPROXY_HOME="$WORK"

cleanup() {
  [[ -n "${SRV_PID:-}" ]] && kill "$SRV_PID" 2>/dev/null
  [[ -n "${MITM_PID:-}" ]] && kill "$MITM_PID" 2>/dev/null
  rm -rf "$WORK"
}
trap cleanup EXIT

rules() { printf '%s' "$1" > "$WORK/rules/rules.json.tmp"; mv "$WORK/rules/rules.json.tmp" "$WORK/rules/rules.json"; }
p()     { curl -s -x "http://127.0.0.1:$PORT" "$@"; }

# --------------------------------------------------------------- test server
python3 - "$SRV_PORT" <<'PY' &
import json, sys, http.server
BODY = {"ok": True, "data": {"experiments": {"newFeed": False}, "items": [{"id": 1}]}}
class H(http.server.BaseHTTPRequestHandler):
    def go(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        if self.path.startswith("/badbytes"):
            # Invalid UTF-8 in a "textual" content type. The recorder must
            # survive this (issue #16).
            b = b'{"msg": "\xd0\x28 not utf-8"}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(b)))
            self.end_headers(); self.wfile.write(b)
            return
        out = json.loads(json.dumps(BODY))
        out.update(path=self.path, got=raw.decode(errors="replace"),
                   seen=self.headers.get("x-injected", ""))
        b = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.send_header("x-origin", "real")
        self.end_headers(); self.wfile.write(b)
    do_GET = do_POST = go
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PY
SRV_PID=$!
disown 2>/dev/null || true   # keep bash from printing "Terminated" on cleanup
sleep 1.5

# --------------------------------------------------------------------- proxy
echo '{"capture":{},"rules":[]}' > "$WORK/rules/rules.json"
mitmdump -q -s "$ROOT/addon/claude_addon.py" --listen-port "$PORT" \
  --set connection_strategy=lazy > "$WORK/var/mitm.log" 2>&1 &
MITM_PID=$!
disown 2>/dev/null || true
for _ in $(seq 40); do [[ -f "$WORK/var/ready" ]] && break; sleep 0.25; done
[[ -f "$WORK/var/ready" ]] || { red "proxy addon never became ready"; cat "$WORK/var/mitm.log"; exit 1; }

BASE="http://127.0.0.1:$SRV_PORT"
echo "running tests..."

# 1. passthrough
check "passthrough" '"ok": true' "$(p $BASE/plain)"

# 2. json_patch on an existing path
rules '{"capture":{},"rules":[{"id":"t","match":{"path":"/jp"},
  "action":{"type":"json_patch","set":{"data.experiments.newFeed":true}}}]}'
check "json_patch set" '"newFeed": true' "$(p $BASE/jp)"

# 3. json_patch refuses a missing path (the important one)
rules '{"capture":{},"rules":[{"id":"t","match":{"path":"/miss"},
  "action":{"type":"json_patch","set":{"data.nope.deep":"x"}}}]}'
OUT="$(p $BASE/miss)"
check "json_patch refuses missing path" '"ok": true' "$OUT"
if [[ "$OUT" == *"nope"* ]]; then
  red "  FAIL  json_patch fabricated a missing path"; FAIL=$((FAIL+1))
else
  green "  PASS  json_patch did not fabricate"; PASS=$((PASS+1))
fi

# 4. create:true opts in
rules '{"capture":{},"rules":[{"id":"t","match":{"path":"/create"},
  "action":{"type":"json_patch","create":true,"set":{"data.nope.deep":"x"}}}]}'
check "json_patch create:true" '"deep": "x"' "$(p $BASE/create)"

# 5. status override
rules '{"capture":{},"rules":[{"id":"t","match":{"path":"/boom"},
  "action":{"type":"status","code":503,"body":"{\"e\":1}"}}]}'
check "status override" "503" "$(p -o /dev/null -w '%{http_code}' $BASE/boom)"

# 6. delay
rules '{"capture":{},"rules":[{"id":"t","match":{"path":"/slow"},
  "action":{"type":"delay","response_ms":1200}}]}'
T="$(p -o /dev/null -w '%{time_total}' $BASE/slow)"
if awk "BEGIN{exit !($T >= 1.2)}"; then
  green "  PASS  delay (${T}s)"; PASS=$((PASS+1))
else
  red "  FAIL  delay too fast: ${T}s"; FAIL=$((FAIL+1))
fi

# 7. block kills the connection
rules '{"capture":{},"rules":[{"id":"t","match":{"path":"/dead"},
  "action":{"type":"block","mode":"kill"}}]}'
p -o /dev/null "$BASE/dead" 2>/dev/null
check "block kill" "52" "$?"

# 8. map_local
echo '{"mocked":true}' > "$WORK/maps/m.json"
rules '{"capture":{},"rules":[{"id":"t","match":{"path":"/local"},
  "action":{"type":"map_local","file":"maps/m.json","status":201}}]}'
check "map_local body"   '"mocked":true' "$(p $BASE/local)"
check "map_local status" "201" "$(p -o /dev/null -w '%{http_code}' $BASE/local)"

# 9. set_header, both directions
rules '{"capture":{},"rules":[{"id":"t","match":{"path":"/hdr"},
  "action":{"type":"set_header","request":{"X-Injected":"yes"},
            "response":{"X-Added":"1"},"remove_response":["x-origin"]}}]}'
check "set_header request"  '"seen": "yes"' "$(p $BASE/hdr)"
H="$(p -D - -o /dev/null $BASE/hdr)"
check "set_header response" "X-Added: 1" "$H"
if [[ "$H" == *"x-origin"* ]]; then
  red "  FAIL  remove_response did not drop the header"; FAIL=$((FAIL+1))
else
  green "  PASS  remove_response"; PASS=$((PASS+1))
fi

# 10. request body rewrite keeps content-length correct
rules '{"capture":{},"rules":[{"id":"t","match":{"path":"/grow"},
  "action":{"type":"body_replace","target":"request","from":"x","to":"xxxxxxxxxx"}}]}'
check "body_replace + content-length" 'xxxxxxxxxx' \
  "$(p -X POST -H 'content-type: application/json' -d '{"k":"x"}' $BASE/grow)"

# 11. map_remote
rules '{"capture":{},"rules":[{"id":"t","match":{"path":"^/old"},
  "action":{"type":"map_remote","replace":{"from":"/old","to":"/new"}}}]}'
check "map_remote" '"path": "/newpath"' "$(p $BASE/oldpath)"

# 12. multiple actions on one rule
rules '{"capture":{},"rules":[{"id":"t","match":{"path":"/multi"},
  "actions":[{"type":"json_patch","set":{"ok":"multi"}},
             {"type":"set_header","response":{"X-Multi":"1"}}]}]}'
check "multi-action" '"ok": "multi"' "$(p $BASE/multi)"

# 13. hot reload — no restart between these two
rules '{"capture":{},"rules":[]}'
check "hot reload off" '"newFeed": false' "$(p $BASE/jp)"
rules '{"capture":{},"rules":[{"id":"t","match":{"path":"/jp"},
  "action":{"type":"json_patch","set":{"data.experiments.newFeed":true}}}]}'
check "hot reload on"  '"newFeed": true'  "$(p $BASE/jp)"

# 14. the flow log is written and parseable
sleep 1
check "flow log written" "127.0.0.1" "$(tail -1 "$WORK/var/flows.jsonl")"
check "flow log is valid jsonl" "ok" \
  "$(python3 -c "
import json,pathlib
[json.loads(l) for l in pathlib.Path('$WORK/var/flows.jsonl').read_text().splitlines() if l.strip()]
print('ok')" 2>&1)"

# 15. a refused patch is visible in the flow tag
check "NOT_APPLIED is recorded" "NOT_APPLIED" \
  "$(grep -o 'NOT_APPLIED' "$WORK/var/flows.jsonl" | head -1)"

# 16. map_remote to an excluded host still records the flow (issue #15)
rules '{"capture":{"exclude_hosts":["^127\\.0\\.0\\.1$"]},
  "rules":[{"id":"mr","match":{"host":"testhost\\.devproxy"},
  "action":{"type":"map_remote","host":"127.0.0.1","port":'$SRV_PORT',"scheme":"http"}}]}'
check "map_remote reaches the target" '"path": "/mapped"' "$(p http://testhost.devproxy/mapped)"
sleep 1
LOGLINE="$(grep '/mapped' "$WORK/var/flows.jsonl" | tail -1)"
check "flow kept the original host"  '"host": "testhost.devproxy"' "$LOGLINE"
check "flow records mapped_to"       '"mapped_to": "http://127.0.0.1:'$SRV_PORT'/mapped"' "$LOGLINE"
rules '{"capture":{},"rules":[]}'

# 17. a body with invalid UTF-8 must not drop the flow (issue #16)
check "bad-bytes body passes through" "not utf-8" "$(p $BASE/badbytes | LC_ALL=C tr -c '[:print:]' '?')"
sleep 1
check "bad-bytes flow is recorded" '"path": "/badbytes"' \
  "$(grep '/badbytes' "$WORK/var/flows.jsonl" | tail -1)"
check "bad-bytes body file saved" "badbytes" \
  "$(python3 -c "
import json,pathlib
line=[l for l in pathlib.Path('$WORK/var/flows.jsonl').read_text().splitlines() if '/badbytes' in l][-1]
f=json.loads(line)
p=pathlib.Path('$WORK')/f['resp_body_file']
print('badbytes' if p.exists() else 'missing:'+str(p))" 2>&1)"

# 18. ids stay unique through a burst right after a clear (issue #17)
rm -f "$WORK/var/flows.jsonl"
for i in $(seq 1 10); do p -o /dev/null "$BASE/burst?i=$i" & done
wait
sleep 1
check "ids unique after clear + burst" "unique" \
  "$(python3 -c "
import json,pathlib
ids=[json.loads(l)['id'] for l in pathlib.Path('$WORK/var/flows.jsonl').read_text().splitlines() if l.strip()]
burst=[json.loads(l)['id'] for l in pathlib.Path('$WORK/var/flows.jsonl').read_text().splitlines() if 'burst' in l]
print('unique' if len(ids)==len(set(ids)) and len(burst)==10 and min(burst)==1 else f'dupes or missing: {sorted(ids)}')" 2>&1)"

echo
if [[ $FAIL -eq 0 ]]; then
  green "all $PASS checks passed"
else
  red "$FAIL failed, $PASS passed"; exit 1
fi
