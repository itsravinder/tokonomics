"""
TokenScope server - a local web UI for Claude token economics.

A thin UI layer on top of two existing tools:
  - rtk (https://github.com/rtk-ai/rtk)       - token savings
  - ccusage (https://github.com/ryoppippi/ccusage) - Claude usage and spend

Stdlib only. No pip installs for the server itself.

Usage:
    python -m tokenscope                  # serve on http://127.0.0.1:8765
    python -m tokenscope --port 9000
    python -m tokenscope --price 3.5      # USD per 1M saved tokens
    python -m tokenscope --rtk /path/rtk  # override rtk location
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

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
MOCK_GAIN_FILE = BASE_DIR / "sample" / "mock_gain.json"
MOCK_ECON_FILE = BASE_DIR / "sample" / "mock_economics.json"

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
    if os.environ.get("TOKENSCOPE_RTK"):
        candidates.append(os.environ["TOKENSCOPE_RTK"])
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
                payload = economics.assemble(CONFIG["rtk_path"], CONFIG["price_per_mtok"])
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

        self._send_static(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tokenscope", description="Local Claude token-economics dashboard")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--price", type=float, default=DEFAULT_PRICE_PER_MTOK, help="USD per 1,000,000 saved tokens")
    ap.add_argument("--rtk", default=None, help="path to rtk executable (auto-detected if omitted)")
    args = ap.parse_args(argv)

    CONFIG["price_per_mtok"] = args.price
    CONFIG["rtk_path"] = resolve_rtk(args.rtk)

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    rtk_ok = "found" if Path(CONFIG["rtk_path"]).exists() else "NOT found - run scripts/install-rtk"
    ccu_ok = "found" if economics.ccusage_available() else "NOT found - npm i -g ccusage"
    print(f"TokenScope serving at {url}")
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
    return 0
