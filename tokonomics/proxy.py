"""
proxy.py - the Tokonomics active optimization proxy.

Sits between Claude Code and api.anthropic.com. Point Claude Code at it with
ANTHROPIC_BASE_URL=http://127.0.0.1:8788. For each /v1/messages request it:

  1. reads + parses the JSON body,
  2. runs it through pipeline.optimize() (never raises; degrades to passthrough),
  3. measures tokens before/after with a consistent estimator,
  4. forwards the (optimized) body to the upstream over HTTPS,
  5. streams the response back byte-for-byte (works for SSE and non-streaming),
  6. appends a token-count-only record to ~/.tokonomics/proxy_log.jsonl.

No TLS interception: Claude Code talks plain HTTP to localhost; this proxy makes
its own HTTPS call upstream. Auth headers are forwarded untouched.

Runtime state (config + counters + server handle) lives in a single STATE dict
so the dashboard server can start/stop and reconfigure the proxy in-process.
"""

from __future__ import annotations

import http.client
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import pipeline

DEFAULT_PROXY_PORT = 8788
DEFAULT_UPSTREAM = "https://api.anthropic.com"

LOG_DIR = Path.home() / ".tokonomics"
LOG_FILE = LOG_DIR / "proxy_log.jsonl"

# headers we must not copy verbatim to the upstream connection
_HOP_BY_HOP = {"host", "content-length", "connection", "keep-alive",
               "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"}

STATE = {
    "server": None,          # ThreadingHTTPServer instance when running
    "thread": None,          # serving thread
    "port": DEFAULT_PROXY_PORT,
    "upstream": DEFAULT_UPSTREAM,
    "config": dict(pipeline.DEFAULT_CONFIG),
    "price_per_mtok": 3.0,
    "counters": {"requests": 0, "orig_tokens": 0, "opt_tokens": 0, "saved_tokens": 0},
    "log_lock": threading.Lock(),
}


def _log_record(rec: dict) -> None:
    """Append one JSONL record. Token counts only - never content or keys."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with STATE["log_lock"]:
            with LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
    except Exception:  # noqa: BLE001 - logging must never break the request
        pass


# buffer this many response bytes to recover Anthropic's usage block
_HEAD_CAP = 32768
# fields count_tokens accepts; others (max_tokens, stream, ...) would 400
_COUNT_FIELDS = ("model", "messages", "system", "tools", "tool_choice", "thinking")


def _usage_from(u: dict) -> dict:
    inp = int(u.get("input_tokens") or 0)
    cr = int(u.get("cache_read_input_tokens") or 0)
    cc = int(u.get("cache_creation_input_tokens") or 0)
    return {"input": inp, "cache_read": cr, "cache_creation": cc, "total": inp + cr + cc}


def _extract_billed(buf: bytes) -> dict | None:
    """Recover the response usage from a non-streamed body or an SSE stream.

    Non-streaming: top-level `usage`. Streaming: the `message_start` event's
    `message.usage`. Returns exact, model-counted input + cache breakdown.
    """
    if not buf:
        return None
    text = buf.decode("utf-8", "replace")
    try:  # non-streaming JSON reply
        u = (json.loads(text).get("usage")) or {}
        if u:
            return _usage_from(u)
    except Exception:  # noqa: BLE001
        pass
    for line in text.splitlines():  # SSE: scan for message_start
        line = line.strip()
        if not line.startswith("data:"):
            continue
        try:
            obj = json.loads(line[5:].strip())
        except Exception:  # noqa: BLE001
            continue
        if obj.get("type") == "message_start":
            u = (obj.get("message") or {}).get("usage") or {}
            if u:
                return _usage_from(u)
    return None


def _count_tokens(req_headers: dict, body: dict, upstream: str) -> int | None:
    """Exact, model-specific token count via /v1/messages/count_tokens.

    Free and not billed. Returns None on any failure (caller falls back to the
    local estimate). Runs off the hot path.
    """
    if not isinstance(body, dict):
        return None
    payload = {k: body[k] for k in _COUNT_FIELDS if k in body}
    if "messages" not in payload:
        return None
    data = json.dumps(payload).encode("utf-8")
    headers = {k: v for k, v in req_headers.items() if k.lower() not in _HOP_BY_HOP}
    headers["Content-Type"] = "application/json"
    headers["Content-Length"] = str(len(data))
    conn = _upstream_conn(upstream)
    try:
        conn.request("POST", "/v1/messages/count_tokens", body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        if resp.status == 200:
            return int(json.loads(raw).get("input_tokens"))
    except Exception:  # noqa: BLE001 - best-effort
        return None
    finally:
        conn.close()
    return None


def _finalize(orig_body, opt_body, report: dict, billed: dict | None,
              req_headers: dict, upstream: str) -> None:
    """Resolve exact before/after token counts, then record. Background thread."""
    method = "estimate"
    orig_t = report["orig_tokens"]
    opt_t = report["opt_tokens"]
    saved = report["saved_tokens"]

    orig_exact = _count_tokens(req_headers, orig_body, upstream)
    # The optimized body is what upstream actually counted - reuse its usage
    # (free, already in hand) instead of a second count_tokens call.
    opt_exact = billed["total"] if (billed and billed["total"] > 0) else \
        _count_tokens(req_headers, opt_body, upstream)

    if orig_exact and opt_exact:
        method = "exact"
        orig_t, opt_t = orig_exact, opt_exact
        saved = max(0, orig_t - opt_t)

    with STATE["log_lock"]:
        c = STATE["counters"]
        c["requests"] += 1
        c["orig_tokens"] += orig_t
        c["opt_tokens"] += opt_t
        c["saved_tokens"] += saved

    rec = {
        "ts": time.time(),
        "method": method,
        "orig_tokens": orig_t,
        "opt_tokens": opt_t,
        "saved_tokens": saved,
        "stages": report["stages"],
        "status": report["status"],
    }
    if billed:
        rec["billed_input"] = billed["input"]
        rec["cache_read"] = billed["cache_read"]
        rec["cache_creation"] = billed["cache_creation"]
    _log_record(rec)


def _upstream_conn(upstream: str) -> http.client.HTTPConnection:
    u = urlparse(upstream)
    host = u.hostname or "api.anthropic.com"
    if u.scheme == "http":
        return http.client.HTTPConnection(host, u.port or 80, timeout=600)
    return http.client.HTTPSConnection(host, u.port or 443, timeout=600)


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter logging
        pass

    # all methods funnel through here
    def _handle(self):
        try:
            self._proxy()
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001 - never crash the handler
            try:
                self.send_error(502, f"proxy error: {type(exc).__name__}")
            except Exception:  # noqa: BLE001
                pass

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_DELETE = _handle

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _proxy(self):
        body = self._read_body()
        path = self.path
        is_messages = self.command == "POST" and path.startswith("/v1/messages")

        report = None
        parsed = optimized = None
        out_body = body
        if is_messages and body:
            try:
                parsed = json.loads(body)
                optimized, report = pipeline.optimize(parsed, STATE["config"])
                out_body = json.dumps(optimized).encode("utf-8")
            except Exception:  # noqa: BLE001 - any parse/opt failure => relay original
                out_body = body
                report = None
                parsed = optimized = None

        # ---- forward upstream ----
        conn = _upstream_conn(STATE["upstream"])
        fwd_headers = {k: v for k, v in self.headers.items() if k.lower() not in _HOP_BY_HOP}
        fwd_headers["Content-Length"] = str(len(out_body))
        try:
            conn.request(self.command, path, body=out_body, headers=fwd_headers)
            resp = conn.getresponse()
        except Exception as exc:  # noqa: BLE001 - upstream unreachable
            self.send_error(502, f"upstream error: {type(exc).__name__}")
            conn.close()
            return

        # ---- stream response back ----
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() in ("transfer-encoding", "connection", "content-length"):
                continue
            self.send_header(k, v)
        # we relay with explicit chunking control: close after body
        self.send_header("Connection", "close")
        self.end_headers()

        # Buffer the head of the response so we can read Anthropic's real usage
        # (exact billed input + cache hit/miss) whether or not it streamed.
        collected = bytearray()
        try:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
                if len(collected) < _HEAD_CAP:
                    collected.extend(chunk[: _HEAD_CAP - len(collected)])
        except Exception:  # noqa: BLE001 - client/upstream dropped mid-stream
            pass
        finally:
            conn.close()

        if report is not None:
            billed = _extract_billed(bytes(collected))
            req_headers = {k: v for k, v in self.headers.items()}
            # Exact counting + logging happen OFF the hot path - the user already
            # has their full response by now.
            threading.Thread(
                target=_finalize,
                args=(parsed, optimized, report, billed, req_headers, STATE["upstream"]),
                daemon=True,
            ).start()


def is_running() -> bool:
    return STATE["server"] is not None


def start(port: int | None = None, upstream: str | None = None,
          config: dict | None = None, rtk_path: str | None = None,
          price_per_mtok: float | None = None) -> dict:
    """Start the proxy in a background thread. Idempotent-ish: errors if running."""
    if is_running():
        return status()
    if port is not None:
        STATE["port"] = port
    if upstream is not None:
        STATE["upstream"] = upstream
    if config:
        STATE["config"] = {**pipeline.DEFAULT_CONFIG, **config}
    if price_per_mtok is not None:
        STATE["price_per_mtok"] = price_per_mtok
    pipeline._set_rtk_binary(rtk_path)

    server = ThreadingHTTPServer(("127.0.0.1", STATE["port"]), ProxyHandler)
    thread = threading.Thread(target=server.serve_forever, name="tokonomics-proxy", daemon=True)
    thread.start()
    STATE["server"] = server
    STATE["thread"] = thread
    return status()


def stop() -> dict:
    server = STATE["server"]
    if server is not None:
        try:
            server.shutdown()
            server.server_close()
        except Exception:  # noqa: BLE001
            pass
    STATE["server"] = None
    STATE["thread"] = None
    return status()


def set_config(patch: dict) -> dict:
    STATE["config"] = {**STATE["config"], **{k: bool(v) for k, v in patch.items()}}
    return status()


def status() -> dict:
    return {
        "running": is_running(),
        "port": STATE["port"],
        "upstream": STATE["upstream"],
        "config": STATE["config"],
        "counters": dict(STATE["counters"]),
        "tiktoken": pipeline._encoder() is not None,
        "base_url": f"http://127.0.0.1:{STATE['port']}",
    }


def stats(price_per_mtok: float, limit: int = 50) -> dict:
    """Aggregate proxy_log.jsonl into totals, per-stage savings, and recents."""
    records: list[dict] = []
    try:
        if LOG_FILE.exists():
            with LOG_FILE.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except ValueError:
                        continue
    except Exception:  # noqa: BLE001
        records = []

    orig = sum(int(r.get("orig_tokens") or 0) for r in records)
    opt = sum(int(r.get("opt_tokens") or 0) for r in records)
    saved = sum(int(r.get("saved_tokens") or 0) for r in records)
    cache_read = sum(int(r.get("cache_read") or 0) for r in records)
    cache_create = sum(int(r.get("cache_creation") or 0) for r in records)
    billed = sum(int(r.get("billed_input") or 0) for r in records)
    exact = sum(1 for r in records if r.get("method") == "exact")
    stages = {"rtk": 0, "markitdown": 0, "prompt": 0}
    for r in records:
        for k in stages:
            stages[k] += int((r.get("stages") or {}).get(k, 0) or 0)

    pct = round(100 * saved / orig, 1) if orig else 0.0
    # cache hit rate over the cacheable prompt (read vs read+freshly-written)
    cache_denom = cache_read + cache_create
    cache_hit_pct = round(100 * cache_read / cache_denom, 1) if cache_denom else 0.0
    recent = list(reversed(records[-limit:]))
    return {
        "requests": len(records),
        "orig_tokens": orig,
        "opt_tokens": opt,
        "saved_tokens": saved,
        "saved_pct": pct,
        "saved_usd": round(saved / 1e6 * price_per_mtok, 4),
        "stages": stages,
        "stages_usd": {k: round(v / 1e6 * price_per_mtok, 4) for k, v in stages.items()},
        "exact_requests": exact,
        "cache_read_tokens": cache_read,
        "cache_hit_pct": cache_hit_pct,
        "billed_input_tokens": billed,
        "recent": recent,
        "price_per_mtok": price_per_mtok,
    }
