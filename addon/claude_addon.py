"""dev-proxy addon for mitmproxy.

Two jobs:
  1. Apply rules from rules/rules.json (Charles-style map local, map remote,
     block, delay, rewrite, status override, JSON patch). The file reloads
     automatically when it changes on disk. No proxy restart is necessary.
  2. Write one JSON line per flow to var/flows.jsonl, and write full bodies
     to var/bodies/. An agent reads these files to inspect the traffic.

The addon uses the standard library only. mitmproxy ships its own Python.
"""

import asyncio
import fnmatch
import json
import logging
import os
import re
import time
from pathlib import Path

from mitmproxy import http

ROOT = Path(os.environ.get("DEVPROXY_HOME", Path(__file__).resolve().parent.parent))
RULES_FILE = ROOT / "rules" / "rules.json"
VAR = ROOT / "var"
FLOWS_FILE = VAR / "flows.jsonl"
BODIES = VAR / "bodies"
READY_FILE = VAR / "ready"

PREVIEW_CHARS = 600
TEXTUAL = (
    "json", "text", "xml", "javascript", "html", "urlencoded",
    "graphql", "plain", "csv", "yaml",
)

log = logging.getLogger("dev-proxy")

# Write diagnostics to our own file. mitmproxy's terminal log does not carry
# addon warnings reliably, so a rule that fails to apply would leave no note
# anywhere except the flow log tag.
VAR.mkdir(parents=True, exist_ok=True)
_handler = logging.FileHandler(VAR / "addon.log")
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_handler)
log.setLevel(logging.INFO)
log.propagate = True  # keep mitmproxy's own log working too


def _is_textual(content_type: str) -> bool:
    ct = (content_type or "").lower()
    return any(marker in ct for marker in TEXTUAL)


def _ext_for(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "json" in ct:
        return "json"
    if "xml" in ct:
        return "xml"
    if "html" in ct:
        return "html"
    if "javascript" in ct:
        return "js"
    if "text" in ct or "urlencoded" in ct:
        return "txt"
    return "bin"


def _dotted_set(obj, path: str, value, create: bool = False):
    """Set a value at a dotted path. Digits index into a list.

    A missing parent raises KeyError unless create is true. Silent creation is
    worse than a loud failure here: a typed path would fabricate a node, the
    app would receive a payload the server never sends, and the test would
    prove nothing. Pass "create": true in the action to opt in.
    """
    parts = path.split(".")
    cur = obj
    for i, part in enumerate(parts[:-1]):
        if isinstance(cur, list):
            cur = cur[int(part)]
            continue
        if not isinstance(cur, dict):
            raise KeyError(f"{'.'.join(parts[:i])} is not an object")
        if part not in cur or not isinstance(cur[part], (dict, list)):
            if not create:
                raise KeyError(
                    f"{'.'.join(parts[:i + 1])} does not exist in the response"
                )
            cur[part] = {}
        cur = cur[part]
    last = parts[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    elif isinstance(cur, dict):
        if last not in cur and not create:
            raise KeyError(f"{path} does not exist in the response")
        cur[last] = value
    else:
        raise KeyError(f"{path} has no object to set on")


def _dotted_delete(obj, path: str):
    parts = path.split(".")
    cur = obj
    for part in parts[:-1]:
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    last = parts[-1]
    if isinstance(cur, list):
        del cur[int(last)]
    elif last in cur:
        del cur[last]


class Config:
    """Holds rules.json and reloads it when the file changes."""

    def __init__(self):
        self.mtime = 0.0
        self.rules = []
        self.capture = {}
        self.load()

    def load(self):
        try:
            mtime = RULES_FILE.stat().st_mtime
        except OSError:
            self.rules, self.capture, self.mtime = [], {}, 0.0
            return
        if mtime == self.mtime:
            return
        try:
            data = json.loads(RULES_FILE.read_text() or "{}")
        except (json.JSONDecodeError, OSError) as exc:
            log.error("dev-proxy: cannot read rules.json: %s", exc)
            return
        self.mtime = mtime
        self.rules = [r for r in data.get("rules", []) if r.get("enabled", True)]
        self.capture = data.get("capture", {})
        log.info("dev-proxy: loaded %d active rule(s)", len(self.rules))


def _match(rule: dict, flow: http.HTTPFlow) -> bool:
    m = rule.get("match") or {}
    req = flow.request
    if "method" in m and req.method.upper() not in [
        x.upper() for x in _as_list(m["method"])
    ]:
        return False
    if "host" in m and not _any_match(m["host"], req.pretty_host):
        return False
    if "path" in m and not _any_match(m["path"], req.path):
        return False
    if "url" in m and not _any_match(m["url"], req.pretty_url):
        return False
    if "req_body" in m:
        try:
            body = req.get_text(strict=False) or ""
        except ValueError:
            body = ""
        if not _any_match(m["req_body"], body):
            return False
    if "req_header" in m:
        for name, pattern in m["req_header"].items():
            if not _any_match(pattern, req.headers.get(name, "")):
                return False
    return True


def _as_list(value):
    return value if isinstance(value, list) else [value]


def _any_match(pattern, text: str) -> bool:
    """Match a regex, or a glob when the pattern contains * and no regex chars."""
    for pat in _as_list(pattern):
        if _one_match(pat, text):
            return True
    return False


def _one_match(pat: str, text: str) -> bool:
    if "*" in pat and not re.search(r"[\\\[\](){}|+?^$]", pat):
        return fnmatch.fnmatch(text, pat)
    try:
        return re.search(pat, text) is not None
    except re.error:
        return pat in text


class DevProxy:
    def __init__(self):
        self.cfg = Config()
        self.counter = self._last_id()
        VAR.mkdir(parents=True, exist_ok=True)
        BODIES.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _last_id() -> int:
        """Continue the id sequence across restarts."""
        highest = 0
        if FLOWS_FILE.exists():
            try:
                for line in FLOWS_FILE.read_text(errors="replace").splitlines():
                    if not line.strip():
                        continue
                    try:
                        fid = int(json.loads(line).get("id", 0))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
                    highest = max(highest, fid)
            except OSError:
                pass
        return highest

    # ---------------------------------------------------------------- hooks

    def running(self):
        """mitmproxy calls this when the proxy is up and this addon is loaded.

        proxyctl waits for this file. Without the wait, mitmdump accepts
        traffic a few seconds before the addon is ready, so the first requests
        bypass every rule and never reach the flow log.
        """
        try:
            READY_FILE.write_text(f"{os.getpid()} {time.time()}\n")
        except OSError:
            pass

    def done(self):
        READY_FILE.unlink(missing_ok=True)

    async def request(self, flow: http.HTTPFlow):
        self.cfg.load()
        if not FLOWS_FILE.exists():
            # `proxyctl clear` removed the log. Restart the id sequence so ids
            # stay short, and so they line up with the body files on disk.
            self.counter = 0
        self.counter += 1
        flow.metadata["dp_id"] = self.counter
        flow.metadata["dp_rules"] = []

        for rule in self.cfg.rules:
            if not _match(rule, flow):
                continue
            for action in _as_list(rule.get("action") or rule.get("actions") or []):
                await self._apply_request_action(rule, action, flow)
                if flow.response is not None or not flow.live:
                    return

    async def response(self, flow: http.HTTPFlow):
        self.cfg.load()
        if flow.metadata.get("dp_served_local"):
            self._record(flow)
            return
        for rule in self.cfg.rules:
            if not _match(rule, flow):
                continue
            for action in _as_list(rule.get("action") or rule.get("actions") or []):
                await self._apply_response_action(rule, action, flow)
        self._record(flow)

    def error(self, flow: http.HTTPFlow):
        if isinstance(flow, http.HTTPFlow):
            self._record(flow, error=str(flow.error) if flow.error else "error")

    def tls_failed_client(self, data):
        """Log a client TLS handshake failure.

        This is the signal that the app does not trust the mitmproxy CA. Without
        this hook such traffic leaves no trace at all, and the flow log looks
        misleadingly empty.
        """
        conn = getattr(data, "conn", None)
        ctx = getattr(data, "context", None)
        sni = getattr(conn, "sni", None)
        if not sni and ctx is not None:
            sni = getattr(getattr(ctx, "server", None), "address", ["?"])[0]
        reason = getattr(conn, "error", None) or "TLS handshake failed"
        self.counter += 1
        entry = {
            "id": self.counter,
            "ts": round(time.time(), 3),
            "time": time.strftime("%H:%M:%S"),
            "method": "CONNECT",
            "host": sni or "unknown",
            "path": "/",
            "url": f"https://{sni or 'unknown'}",
            "error": f"client TLS failed: {reason}",
            "hint": "the app does not trust the mitmproxy CA, or it pins certificates",
        }
        try:
            with FLOWS_FILE.open("a") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except OSError:
            pass

    # -------------------------------------------------------------- actions

    async def _apply_request_action(self, rule, action, flow: http.HTTPFlow):
        kind = action.get("type")
        tag = rule.get("id") or rule.get("name") or kind

        if kind == "map_local":
            path = Path(action["file"])
            if not path.is_absolute():
                path = ROOT / path
            if not path.exists():
                log.error("dev-proxy: map_local file missing: %s", path)
                return
            body = path.read_bytes()
            headers = {"content-type": action.get("content_type") or _guess_ct(path)}
            headers.update(action.get("headers") or {})
            delay = action.get("delay_ms")
            if delay:
                await asyncio.sleep(delay / 1000)
            flow.response = http.Response.make(
                int(action.get("status", 200)), body, headers
            )
            flow.metadata["dp_served_local"] = str(path)
            flow.metadata["dp_rules"].append(f"{tag}:map_local")

        elif kind == "map_remote":
            if action.get("url"):
                flow.request.url = action["url"]
            elif action.get("replace"):
                rep = action["replace"]
                flow.request.url = re.sub(
                    rep["from"], rep["to"], flow.request.pretty_url
                )
            if action.get("host"):
                flow.request.host = action["host"]
            if action.get("port"):
                flow.request.port = int(action["port"])
            if action.get("scheme"):
                flow.request.scheme = action["scheme"]
            if action.get("keep_host_header") is False:
                flow.request.headers["host"] = flow.request.host
            flow.metadata["dp_rules"].append(f"{tag}:map_remote")

        elif kind == "block":
            mode = action.get("mode", "kill")
            flow.metadata["dp_rules"].append(f"{tag}:block:{mode}")
            if mode == "kill":
                self._record(flow, error="blocked (connection killed)")
                flow.kill()
            elif mode == "timeout":
                await asyncio.sleep(float(action.get("seconds", 60)))
                self._record(flow, error="blocked (timeout)")
                flow.kill()
            else:
                code = int(action.get("status", 404 if mode == "404" else 503))
                flow.response = http.Response.make(
                    code,
                    (action.get("body") or "").encode(),
                    {"content-type": action.get("content_type", "application/json")},
                )
                flow.metadata["dp_served_local"] = f"block:{code}"

        elif kind == "delay":
            ms = action.get("request_ms") or action.get("ms") or 0
            if ms:
                await asyncio.sleep(ms / 1000)
                flow.metadata["dp_rules"].append(f"{tag}:delay_req:{ms}ms")

        elif kind == "set_header":
            for name, value in (action.get("request") or {}).items():
                flow.request.headers[name] = str(value)
            for name in action.get("remove_request") or []:
                flow.request.headers.pop(name, None)
            if action.get("request") or action.get("remove_request"):
                flow.metadata["dp_rules"].append(f"{tag}:set_header_req")

        elif kind == "body_replace" and action.get("target", "response") == "request":
            try:
                text = flow.request.get_text(strict=False) or ""
            except ValueError:
                return
            flow.request.set_text(re.sub(action["from"], action["to"], text))
            flow.metadata["dp_rules"].append(f"{tag}:body_replace_req")

        elif kind == "json_patch" and action.get("target") == "request":
            self._patch_json(flow.request, action, flow, tag, "req")

    async def _apply_response_action(self, rule, action, flow: http.HTTPFlow):
        kind = action.get("type")
        tag = rule.get("id") or rule.get("name") or kind
        resp = flow.response
        if resp is None:
            return

        if kind == "delay":
            ms = action.get("response_ms") or 0
            if ms:
                await asyncio.sleep(ms / 1000)
                flow.metadata["dp_rules"].append(f"{tag}:delay_resp:{ms}ms")

        elif kind == "status":
            resp.status_code = int(action["code"])
            if action.get("reason"):
                resp.reason = action["reason"]
            if action.get("body") is not None:
                resp.set_content(str(action["body"]).encode())
                resp.headers["content-type"] = action.get(
                    "content_type", "application/json"
                )
            flow.metadata["dp_rules"].append(f"{tag}:status:{resp.status_code}")

        elif kind == "set_header":
            for name, value in (action.get("response") or {}).items():
                resp.headers[name] = str(value)
            for name in action.get("remove_response") or []:
                resp.headers.pop(name, None)
            if action.get("response") or action.get("remove_response"):
                flow.metadata["dp_rules"].append(f"{tag}:set_header_resp")

        elif kind == "body_replace" and action.get("target", "response") == "response":
            try:
                text = resp.get_text(strict=False) or ""
            except ValueError:
                return
            resp.set_text(re.sub(action["from"], action["to"], text))
            flow.metadata["dp_rules"].append(f"{tag}:body_replace_resp")

        elif kind == "json_patch" and action.get("target", "response") == "response":
            self._patch_json(resp, action, flow, tag, "resp")

    def _patch_json(self, message, action, flow, tag, side):
        try:
            text = message.get_text(strict=False)
        except ValueError:
            return
        if not text:
            return
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            log.warning("dev-proxy: json_patch on non-JSON body (%s)", flow.request.path)
            return
        create = bool(action.get("create"))
        failed = []
        for path, value in (action.get("set") or {}).items():
            try:
                _dotted_set(data, path, value, create=create)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                failed.append(f"{path} ({exc})")
                log.warning(
                    "dev-proxy: rule %s: json_patch set %s did NOT apply: %s. "
                    'Add "create": true if you mean to add a new field.',
                    tag, path, exc,
                )
        for path in action.get("delete") or []:
            try:
                _dotted_delete(data, path)
            except (KeyError, IndexError, TypeError, ValueError):
                pass
        if action.get("merge"):
            if isinstance(data, dict) and isinstance(action["merge"], dict):
                data.update(action["merge"])
        message.set_text(json.dumps(data))
        mark = f"{tag}:json_patch_{side}"
        if failed:
            # Make a partly applied patch visible in `proxyctl flows`, not just
            # in the proxy log that nobody reads.
            mark += f"!NOT_APPLIED[{'; '.join(failed)}]"
        flow.metadata["dp_rules"].append(mark)

    # --------------------------------------------------------------- record

    def _record(self, flow: http.HTTPFlow, error: str | None = None):
        if flow.metadata.get("dp_recorded"):
            return
        flow.metadata["dp_recorded"] = True

        cap = self.cfg.capture
        host = flow.request.pretty_host
        for pattern in cap.get("exclude_hosts") or []:
            if _one_match(pattern, host):
                return
        include = cap.get("include_hosts") or []
        if include and not any(_one_match(p, host) for p in include):
            return

        fid = flow.metadata.get("dp_id") or 0
        max_body = int(cap.get("max_body_kb", 1024)) * 1024
        save_bodies = cap.get("save_bodies", True)

        req = flow.request
        resp = flow.response
        req_ct = req.headers.get("content-type", "")
        resp_ct = resp.headers.get("content-type", "") if resp else ""

        entry = {
            "id": fid,
            "ts": round(req.timestamp_start or time.time(), 3),
            "time": time.strftime(
                "%H:%M:%S", time.localtime(req.timestamp_start or time.time())
            ),
            "method": req.method,
            "status": resp.status_code if resp else None,
            "host": host,
            "path": req.path.split("?")[0],
            "query": dict(req.query) or None,
            "url": req.pretty_url,
            "duration_ms": None,
            "req_type": req_ct.split(";")[0] or None,
            "resp_type": resp_ct.split(";")[0] or None,
            "req_size": len(req.raw_content or b""),
            "resp_size": len(resp.raw_content or b"") if resp else 0,
            "rules": flow.metadata.get("dp_rules") or None,
            "mocked": flow.metadata.get("dp_served_local") or None,
            "error": error,
        }
        if resp and resp.timestamp_end and req.timestamp_start:
            entry["duration_ms"] = int((resp.timestamp_end - req.timestamp_start) * 1000)

        entry["req_headers"] = dict(req.headers)
        if resp:
            entry["resp_headers"] = dict(resp.headers)

        entry["req_preview"], entry["req_body_file"] = self._body(
            fid, "req", req, req_ct, max_body, save_bodies
        )
        if resp:
            entry["resp_preview"], entry["resp_body_file"] = self._body(
                fid, "resp", resp, resp_ct, max_body, save_bodies
            )

        entry = {k: v for k, v in entry.items() if v is not None}
        try:
            with FLOWS_FILE.open("a") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
        except OSError as exc:
            log.error("dev-proxy: cannot write flow log: %s", exc)

    def _body(self, fid, side, message, content_type, max_body, save_bodies):
        raw = message.raw_content or b""
        if not raw:
            return None, None
        preview = None
        if _is_textual(content_type):
            try:
                text = message.get_text(strict=False) or ""
            except ValueError:
                text = ""
            preview = text[:PREVIEW_CHARS]
            if len(text) > PREVIEW_CHARS:
                preview += f"... [{len(text)} chars total]"
        else:
            preview = f"<binary {content_type or 'unknown'} {len(raw)} bytes>"

        path = None
        if save_bodies and len(raw) <= max_body:
            ext = _ext_for(content_type)
            target = BODIES / f"{fid:06d}.{side}.{ext}"
            try:
                if _is_textual(content_type):
                    body = message.get_text(strict=False) or ""
                    if "json" in (content_type or "").lower():
                        try:
                            body = json.dumps(json.loads(body), indent=2)
                        except json.JSONDecodeError:
                            pass
                    target.write_text(body)
                else:
                    target.write_bytes(raw)
                path = str(target.relative_to(ROOT))
            except OSError as exc:
                log.error("dev-proxy: cannot write body: %s", exc)
        return preview, path


def _guess_ct(path: Path) -> str:
    return {
        ".json": "application/json",
        ".xml": "application/xml",
        ".html": "text/html",
        ".txt": "text/plain",
        ".js": "application/javascript",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")


addons = [DevProxy()]
