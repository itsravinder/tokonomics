"""
Tokonomics server - a local web UI for Claude token economics.

A thin UI layer on top of two existing tools:
  - rtk (https://github.com/rtk-ai/rtk)       - token savings
  - ccusage (https://github.com/ryoppippi/ccusage) - Claude usage and spend

Stdlib only. No pip installs for the server itself.

Usage:
    python -m tokonomics                  # serve on http://127.0.0.1:8765
    python -m tokonomics --port 9000
    python -m tokonomics --price 3.5      # USD per 1M saved tokens
    python -m tokonomics --rtk /path/rtk  # override rtk location
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import economics
from . import proxy

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
MOCK_GAIN_FILE = BASE_DIR / "sample" / "mock_gain.json"
MOCK_ECON_FILE = BASE_DIR / "sample" / "mock_economics.json"
MOCK_INSIGHTS_FILE = BASE_DIR / "sample" / "mock_insights.json"

DEFAULT_PORT = 8765
DEFAULT_PRICE_PER_MTOK = 3.0

CONFIG = {"rtk_path": "", "price_per_mtok": DEFAULT_PRICE_PER_MTOK}

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


def resolve_rtk(override: str | None) -> str:
    """Find rtk: explicit override, then env, then PATH, then bundled bin/."""
    candidates = []
    if override:
        candidates.append(override)
    if os.environ.get("TOKONOMICS_RTK"):
        candidates.append(os.environ["TOKONOMICS_RTK"])
    for c in candidates:
        if Path(c).exists():
            return str(Path(c).resolve())
    on_path = shutil.which("rtk")
    if on_path:
        return on_path
    name = "rtk.exe" if os.name == "nt" else "rtk"
    bundled = BASE_DIR / "bin" / name
    if bundled.exists():
        return str(bundled)
    # last resort: return the name and let subprocess fail with a clear error
    return override or name


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("  " + (fmt % args) + "\n")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, rel: str) -> None:
        if rel in ("", "/"):
            rel = "index.html"
        target = (WEB_DIR / rel.lstrip("/")).resolve()
        if WEB_DIR not in target.parents and target != WEB_DIR:
            self.send_error(403, "forbidden")
            return
        if not target.exists() or not target.is_file():
            self.send_error(404, "not found")
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", STATIC_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        force_mock = qs.get("mock", ["0"])[0] == "1"

        if path == "/api/economics":
            if force_mock:
                payload = load_json(MOCK_ECON_FILE) or {"errors": {"mock": "missing mock file"}}
                payload["source"] = "mock"
                self._send_json(payload)
                return
            try:
                opt_pct = 0.0
                try:
                    opt_pct = float(proxy.stats(CONFIG["price_per_mtok"]).get("saved_pct") or 0.0)
                except Exception:  # noqa: BLE001
                    opt_pct = 0.0
                payload = economics.assemble(CONFIG["rtk_path"], CONFIG["price_per_mtok"], optimization_pct=opt_pct)
            except Exception as exc:  # noqa: BLE001
                payload = load_json(MOCK_ECON_FILE)
                payload["source"] = "mock"
                payload.setdefault("errors", {})["assemble"] = str(exc)
            self._send_json(payload)
            return

        if path == "/api/gain":
            if force_mock:
                self._send_json({"source": "mock", "price_per_mtok": CONFIG["price_per_mtok"], "data": load_json(MOCK_GAIN_FILE)})
                return
            data, error = economics._run_rtk_json(CONFIG["rtk_path"], ["gain", "--all", "--format", "json"])
            if data is None:
                self._send_json({"source": "mock", "error": error, "price_per_mtok": CONFIG["price_per_mtok"], "data": load_json(MOCK_GAIN_FILE)})
                return
            self._send_json({"source": "live", "error": None, "price_per_mtok": CONFIG["price_per_mtok"], "data": data})
            return

        if path == "/api/config":
            self._send_json({
                "rtk_path": CONFIG["rtk_path"],
                "rtk_present": Path(CONFIG["rtk_path"]).exists(),
                "ccusage_present": economics.ccusage_available(),
                "price_per_mtok": CONFIG["price_per_mtok"],
            })
            return

        if path == "/api/insights":
            if force_mock:
                self._send_json(load_json(MOCK_INSIGHTS_FILE) or {"source": "mock", "projects": [], "files": [], "commands": [], "tools": [], "recommendations": [], "totals": {}})
                return
            try:
                data = economics.insights(CONFIG["rtk_path"], CONFIG["price_per_mtok"])
                ps, pst = proxy.status(), proxy.stats(CONFIG["price_per_mtok"])
                signals = {
                    "running": ps.get("running"),
                    "passthrough": (ps.get("config") or {}).get("passthrough", False),
                    "requests": pst.get("requests", 0),
                    "saved_pct": pst.get("saved_pct", 0),
                    "cache_hit_pct": pst.get("cache_hit_pct", 0),
                }
                data["recommendations"] = economics.build_recommendations(data, signals)
                self._send_json(data)
            except Exception as exc:  # noqa: BLE001
                self._send_json({"source": "error", "errors": {"insights": str(exc)},
                                 "projects": [], "files": [], "commands": [], "tools": [],
                                 "recommendations": [], "totals": {}, "price_per_mtok": CONFIG["price_per_mtok"]})
            return

        if path == "/api/proxy/status":
            self._send_json(proxy.status())
            return

        if path == "/api/proxy/stats":
            self._send_json(proxy.stats(CONFIG["price_per_mtok"]))
            return

        if path == "/api/proxy/setup":
            self._send_json(_setup_commands(proxy.STATE["port"]))
            return

        self._send_static(path)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            return {}

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path

        if path == "/api/proxy/start":
            proxy.start(
                rtk_path=CONFIG["rtk_path"],
                price_per_mtok=CONFIG["price_per_mtok"],
            )
            self._send_json(proxy.status())
            return

        if path == "/api/proxy/stop":
            proxy.stop()
            self._send_json(proxy.status())
            return

        if path == "/api/proxy/config":
            patch = self._read_json_body()
            allowed = {k: patch[k] for k in ("passthrough", "rtk", "markitdown", "prompt", "truncate") if k in patch}
            self._send_json(proxy.set_config(allowed))
            return

        self.send_error(404, "not found")


def _setup_commands(port: int) -> dict:
    """Exact shell commands to attach/detach Claude Code via ANTHROPIC_BASE_URL."""
    base = f"http://127.0.0.1:{port}"
    return {
        "base_url": base,
        "windows_persist": f'setx ANTHROPIC_BASE_URL "{base}"',
        "windows_session": f'$env:ANTHROPIC_BASE_URL = "{base}"',
        "unix_session": f'export ANTHROPIC_BASE_URL="{base}"',
        "windows_unset": 'setx ANTHROPIC_BASE_URL ""',
        "unix_unset": "unset ANTHROPIC_BASE_URL",
        "note": "Set it, then start Claude Code in that shell. Requests now route through Tokonomics.",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tokonomics", description="Local Claude token-economics dashboard")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--price", type=float, default=DEFAULT_PRICE_PER_MTOK, help="USD per 1,000,000 saved tokens")
    ap.add_argument("--rtk", default=None, help="path to rtk executable (auto-detected if omitted)")
    ap.add_argument("--proxy-port", type=int, default=proxy.DEFAULT_PROXY_PORT, help="port for the optimization proxy")
    ap.add_argument("--upstream", default=proxy.DEFAULT_UPSTREAM, help="upstream Anthropic API base URL")
    ap.add_argument("--no-proxy", action="store_true", help="start the dashboard only; do not launch the proxy")
    ap.add_argument("--proxy-only", action="store_true", help="start the proxy only; no dashboard")
    args = ap.parse_args(argv)

    CONFIG["price_per_mtok"] = args.price
    CONFIG["rtk_path"] = resolve_rtk(args.rtk)
    proxy.STATE["port"] = args.proxy_port
    proxy.STATE["upstream"] = args.upstream
    proxy.STATE["price_per_mtok"] = args.price

    rtk_ok = "found" if Path(CONFIG["rtk_path"]).exists() else "NOT found - run scripts/install-rtk"
    ccu_ok = "found" if economics.ccusage_available() else "NOT found - npm i -g ccusage"

    if not args.no_proxy:
        proxy.start(rtk_path=CONFIG["rtk_path"], price_per_mtok=args.price)
        print(f"Proxy listening on http://127.0.0.1:{args.proxy_port} -> {args.upstream}")
        print(f"  Route Claude Code through it:  setx ANTHROPIC_BASE_URL \"http://127.0.0.1:{args.proxy_port}\"")
        print(f"  tiktoken estimator: [{'on' if proxy.status()['tiktoken'] else 'off - using chars/4'}]")

    if args.proxy_only:
        print("  proxy-only mode; Ctrl+C to stop")
        try:
            while True:
                __import__("time").sleep(3600)
        except KeyboardInterrupt:
            print("\nstopped")
        finally:
            proxy.stop()
        return 0

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Tokonomics serving at {url}")
    print(f"  rtk:     {CONFIG['rtk_path']} [{rtk_ok}]")
    print(f"  ccusage: [{ccu_ok}]")
    print(f"  price:   ${args.price:.2f} per 1M saved tokens")
    print("  Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
        proxy.stop()
    return 0
