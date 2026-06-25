"""
economics.py - merge rtk savings with ccusage Claude spend into one payload.

Data sources (all existing tools, nothing reinvented):
  - rtk gain --all --format json     -> tokens saved (daily/weekly/monthly + totals)
  - ccusage session --json           -> Claude sessions, tokens consumed, USD spent
  - rtk session                      -> per-session rtk adoption (text, parsed)
  - rtk discover --all --format json -> missed savings (opportunities) + adoption base

Health score (0-100) blends prompt quality and token savings, per the user's ask:
  health = 0.5 * cache_efficiency  (prompt quality: how well context is reused)
         + 0.5 * adoption          (token savings: how much is routed through rtk)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path

IS_WIN = os.name == "nt"


def ccusage_available() -> bool:
    """True if the ccusage CLI is resolvable on PATH."""
    if shutil.which("ccusage"):
        return True
    if IS_WIN and (shutil.which("ccusage.cmd") or shutil.which("ccusage.ps1")):
        return True
    return False


def _run(parts: list[str], timeout: int = 90) -> tuple[str | None, str | None]:
    try:
        proc = subprocess.run(
            parts, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"{parts[0]} failed: {exc}"
    if proc.returncode != 0 and not proc.stdout.strip():
        return None, f"{parts[0]} exited {proc.returncode}: {proc.stderr.strip()[:200]}"
    return proc.stdout, None


def _run_ccusage(args: list[str], timeout: int = 120) -> tuple[dict | None, str | None]:
    # ccusage is a .cmd shim on Windows; run through cmd /c.
    parts = (["cmd", "/c", "ccusage"] if IS_WIN else ["ccusage"]) + args
    out, err = _run(parts, timeout=timeout)
    if out is None:
        return None, err
    try:
        return json.loads(out), None
    except json.JSONDecodeError as exc:
        return None, f"ccusage json parse error: {exc}"


def _run_rtk_json(rtk: str, args: list[str]) -> tuple[dict | None, str | None]:
    out, err = _run([rtk] + args)
    if out is None:
        return None, err
    try:
        return json.loads(out), None
    except json.JSONDecodeError as exc:
        return None, f"rtk json parse error: {exc}"


# --- rtk session (text table) ---------------------------------------------
_SESSION_RE = re.compile(r"^([0-9a-fA-F]{8})\s+(.+?)\s+(\d+)\s+(\d+)\s+(\d+)%")


def parse_rtk_session(rtk: str) -> tuple[dict, str | None]:
    """Return {shortId: {cmds, rtk, adoption_pct}} from `rtk session` text."""
    out, err = _run([rtk, "session"])
    if out is None:
        return {}, err
    rows = {}
    for line in out.splitlines():
        m = _SESSION_RE.match(line.strip())
        if not m:
            continue
        sid, _datestr, cmds, rtkc, adopt = m.groups()
        rows[sid.lower()] = {
            "cmds": int(cmds),
            "rtk": int(rtkc),
            "adoption_pct": int(adopt),
        }
    return rows, None


# --- bucket keys -----------------------------------------------------------
def _week_start(d: date) -> str:
    return (d - timedelta(days=d.weekday())).isoformat()


def _bucketize(sessions: list[dict]) -> dict:
    """Bucket Claude sessions by day/week/month -> spend, consumed, count."""
    daily, weekly, monthly = defaultdict(lambda: [0.0, 0, 0]), defaultdict(lambda: [0.0, 0, 0]), defaultdict(lambda: [0.0, 0, 0])
    for s in sessions:
        iso = (s.get("metadata") or {}).get("lastActivity")
        if not iso:
            continue
        try:
            d = datetime.fromisoformat(iso.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        cost = float(s.get("totalCost") or 0)
        toks = int(s.get("totalTokens") or 0)
        for bucket, key in ((daily, d.isoformat()), (weekly, _week_start(d)), (monthly, f"{d.year:04d}-{d.month:02d}")):
            bucket[key][0] += cost
            bucket[key][1] += toks
            bucket[key][2] += 1

    def to_rows(bucket):
        rows = []
        for key in sorted(bucket):
            cost, toks, cnt = bucket[key]
            rows.append({"key": key, "spend_usd": round(cost, 2), "consumed_tokens": toks, "sessions": cnt})
        return rows

    return {"daily": to_rows(daily), "weekly": to_rows(weekly), "monthly": to_rows(monthly)}


def _gain_by_period(gain: dict) -> dict:
    """Index rtk gain saved_tokens by date/week/month key."""
    idx = {"daily": {}, "weekly": {}, "monthly": {}}
    for r in gain.get("daily", []):
        idx["daily"][r.get("date")] = r.get("saved_tokens", 0)
    for r in gain.get("weekly", []):
        idx["weekly"][r.get("week_start")] = r.get("saved_tokens", 0)
    for r in gain.get("monthly", []):
        idx["monthly"][r.get("month")] = r.get("saved_tokens", 0)
    return idx


def assemble(rtk_path: str, price: float) -> dict:
    errors = {}

    gain, errors["rtk_gain"] = _run_rtk_json(rtk_path, ["gain", "--all", "--format", "json"])
    gain = gain or {"summary": {}, "daily": [], "weekly": [], "monthly": []}

    ccu, errors["ccusage"] = _run_ccusage(["session", "--json"])
    sessions_all = (ccu or {}).get("session", []) if ccu else []
    claude = [s for s in sessions_all if s.get("agent") == "claude"]

    sess_adopt, errors["rtk_session"] = parse_rtk_session(rtk_path)
    discover, errors["rtk_discover"] = _run_rtk_json(rtk_path, ["discover", "--all", "--format", "json"])
    discover = discover or {}

    # ---- totals ----
    summary = gain.get("summary", {})
    saved_tokens = int(summary.get("total_saved", 0))
    spend_usd = round(sum(float(s.get("totalCost") or 0) for s in claude), 2)
    consumed_tokens = sum(int(s.get("totalTokens") or 0) for s in claude)

    cache_read = sum(int(s.get("cacheReadTokens") or 0) for s in claude)
    cache_create = sum(int(s.get("cacheCreationTokens") or 0) for s in claude)
    input_t = sum(int(s.get("inputTokens") or 0) for s in claude)
    denom = cache_read + cache_create + input_t
    cache_efficiency = round(100 * cache_read / denom, 1) if denom else 0.0

    # adoption from discover: already_rtk / (already_rtk + missed compressible)
    supported = discover.get("supported", []) or []
    missed_count = sum(int(o.get("count", 0)) for o in supported)
    already = int(discover.get("already_rtk", 0))
    adoption = round(100 * already / (already + missed_count), 1) if (already + missed_count) else 0.0

    savings_rate = round(float(summary.get("avg_savings_pct", 0)), 1)
    health = round(0.5 * cache_efficiency + 0.5 * adoption)

    potential_tokens = sum(int(o.get("estimated_savings_tokens", 0)) for o in supported)

    # ---- buckets (saved vs spent) ----
    buckets = _bucketize(claude)
    gidx = _gain_by_period(gain)
    for period, gkey in (("daily", "daily"), ("weekly", "weekly"), ("monthly", "monthly")):
        for row in buckets[period]:
            st = gidx[gkey].get(row["key"], 0)
            row["saved_tokens"] = st
            row["saved_usd"] = round(st / 1e6 * price, 2)

    # ---- per-session table ----
    per_session = []
    for s in claude:
        sid = (s.get("period") or "")[:8].lower()
        ad = sess_adopt.get(sid, {})
        cr = int(s.get("cacheReadTokens") or 0)
        cc = int(s.get("cacheCreationTokens") or 0)
        it = int(s.get("inputTokens") or 0)
        den = cr + cc + it
        ceff = round(100 * cr / den, 1) if den else 0.0
        adopt_i = ad.get("adoption_pct", 0)
        per_session.append({
            "id": sid,
            "date": (s.get("metadata") or {}).get("lastActivity", "")[:10],
            "model": (s.get("modelsUsed") or ["?"])[0],
            "consumed_tokens": int(s.get("totalTokens") or 0),
            "spend_usd": round(float(s.get("totalCost") or 0), 2),
            "cache_efficiency": ceff,
            "adoption_pct": adopt_i,
            "commands": ad.get("cmds", 0),
            "rtk_commands": ad.get("rtk", 0),
            "health": round(0.5 * ceff + 0.5 * adopt_i),
        })
    per_session.sort(key=lambda r: r["spend_usd"], reverse=True)

    # ---- opportunities ----
    opportunities = [{
        "command": o.get("command"),
        "count": o.get("count"),
        "rtk_equivalent": o.get("rtk_equivalent"),
        "category": o.get("category"),
        "saved_tokens": int(o.get("estimated_savings_tokens", 0)),
        "saved_pct": round(float(o.get("estimated_savings_pct", 0)), 1),
    } for o in supported[:12]]

    live = bool(claude) or bool(summary.get("total_commands"))
    return {
        "source": "live" if live else "live-empty",
        "errors": {k: v for k, v in errors.items() if v},
        "price_per_mtok": price,
        "totals": {
            "sessions": len(claude),
            "spend_usd": spend_usd,
            "consumed_tokens": consumed_tokens,
            "saved_tokens": saved_tokens,
            "saved_usd": round(saved_tokens / 1e6 * price, 2),
            "avg_savings_pct": savings_rate,
            "potential_tokens": potential_tokens,
            "potential_usd": round(potential_tokens / 1e6 * price, 2),
            "commands_scanned": int(discover.get("total_commands", 0)),
            "sessions_scanned": int(discover.get("sessions_scanned", 0)),
        },
        "health": {
            "score": health,
            "cache_efficiency": cache_efficiency,
            "adoption": adoption,
            "savings_rate": savings_rate,
        },
        "buckets": buckets,
        "sessions": per_session,
        "opportunities": opportunities,
    }
