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
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path

IS_WIN = os.name == "nt"

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
# bash invocations worth keeping a sub-verb on (git add vs git commit)
_CMD_GROUPS = {"git", "npm", "npx", "pip", "pip3", "cargo", "go", "python",
               "python3", "uv", "pnpm", "yarn", "docker", "kubectl", "gh"}


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


def assemble(rtk_path: str, price: float, optimization_pct: float = 0.0) -> dict:
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
    # health = prompt quality (cache reuse) + how much the proxy is optimizing.
    # optimization_pct comes from the live proxy's measured savings (0 if off).
    optimization = round(float(optimization_pct or 0.0), 1)
    health = round(0.5 * cache_efficiency + 0.5 * optimization)

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
            "optimization": optimization,
            "rtk_adoption": adoption,
            "savings_rate": savings_rate,
        },
        "buckets": buckets,
        "sessions": per_session,
        "opportunities": opportunities,
    }


# --- insights: where tokens go (read-only analysis of local Claude history) ---
def _project_cwd(transcripts: list, folder_name: str) -> str:
    """Real project path from a transcript `cwd`; fall back to the folder name."""
    for t in transcripts:
        try:
            with t.open(encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if i > 40:
                        break
                    try:
                        cwd = json.loads(line).get("cwd")
                    except ValueError:
                        continue
                    if cwd:
                        return cwd
        except OSError:
            continue
    return folder_name


def _cmd_label(command: str) -> str:
    """Group a bash command: first token, plus a sub-verb for tools like git."""
    parts = command.strip().split()
    if not parts:
        return "?"
    head = parts[0].split("/")[-1].split("\\")[-1]
    if head in _CMD_GROUPS and len(parts) > 1 and not parts[1].startswith("-"):
        return f"{head} {parts[1]}"
    return head


def _topn(counter: Counter, n: int = 15) -> list:
    total = sum(counter.values()) or 1
    return [{"key": k, "count": c, "pct": round(100 * c / total, 1)} for k, c in counter.most_common(n)]


def insights(rtk_path: str, price: float) -> dict:
    """Per-project tokens, most-read files, and most-run commands/tools.

    Read-only: derived from ~/.claude/projects transcripts (same local data
    ccusage reads) joined with ccusage per-session totals. Logs nothing.
    """
    errors = {}
    tool_counts, file_counts, cmd_counts = Counter(), Counter(), Counter()
    # per-project counters, keyed by the project's full path
    p_tools, p_files, p_cmds = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    sid_to_proj, proj_path = {}, {}

    proj_dirs = [p for p in CLAUDE_PROJECTS.iterdir() if p.is_dir()] if CLAUDE_PROJECTS.exists() else []
    for d in proj_dirs:
        transcripts = list(d.glob("*.jsonl"))
        full = _project_cwd(transcripts, d.name)
        proj_path[d.name] = full
        for t in transcripts:
            sid_to_proj[t.stem] = d.name
            try:
                with t.open(encoding="utf-8") as fh:
                    for line in fh:
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        msg = rec.get("message") or {}
                        content = msg.get("content") if isinstance(msg, dict) else None
                        if not isinstance(content, list):
                            continue
                        for b in content:
                            if not isinstance(b, dict) or b.get("type") != "tool_use":
                                continue
                            name = b.get("name", "?")
                            tool_counts[name] += 1
                            p_tools[full][name] += 1
                            inp = b.get("input") or {}
                            if name in ("Read", "Edit", "Write") and inp.get("file_path"):
                                file_counts[inp["file_path"]] += 1
                                p_files[full][inp["file_path"]] += 1
                            elif name == "Bash" and inp.get("command"):
                                label = _cmd_label(inp["command"])
                                cmd_counts[label] += 1
                                p_cmds[full][label] += 1
            except OSError:
                continue

    # per-project tokens + cost, reusing ccusage's accurate session totals
    ccu, errors["ccusage"] = _run_ccusage(["session", "--json"])
    sessions = (ccu or {}).get("session", []) if ccu else []
    proj_tok = defaultdict(lambda: [0, 0.0])
    for s in sessions:
        if s.get("agent") != "claude":
            continue
        pkey = sid_to_proj.get(s.get("period", ""))
        if not pkey:
            continue
        proj_tok[pkey][0] += int(s.get("totalTokens") or 0)
        proj_tok[pkey][1] += float(s.get("totalCost") or 0)

    projects = []
    for k, (toks, cost) in proj_tok.items():
        full = proj_path.get(k, k)
        projects.append({
            "project": full,
            "name": Path(full).name or full,
            "tokens": toks,
            "cost": round(cost, 2),
        })
    projects.sort(key=lambda r: r["tokens"], reverse=True)

    # per-project breakdowns the UI can switch between without refetching
    by_project = {}
    for full in set(list(proj_path.values())):
        by_project[full] = {
            "files": _topn(p_files[full]),
            "commands": _topn(p_cmds[full]),
            "tools": _topn(p_tools[full]),
            "tool_calls": sum(p_tools[full].values()),
            "files_touched": len(p_files[full]),
        }

    return {
        "source": "live" if proj_dirs else "live-empty",
        "errors": {k: v for k, v in errors.items() if v},
        "price_per_mtok": price,
        "projects": projects,
        "files": _topn(file_counts),
        "commands": _topn(cmd_counts),
        "tools": _topn(tool_counts),
        "by_project": by_project,
        "totals": {
            "projects": len(projects),
            "files_touched": len(file_counts),
            "tool_calls": sum(tool_counts.values()),
        },
    }


_RTK_NOISY = {"grep", "find", "cat", "ls", "tail", "head", "tree", "rg"}


def build_recommendations(data: dict, signals: dict) -> list:
    """Turn the insights data + live proxy signals into actionable advice.

    Pure function: `signals` carries proxy state so this module stays unaware
    of proxy.py. Each rec is {level: good|info|warn, title, detail}.
    """
    recs = []
    running = signals.get("running")
    passthrough = signals.get("passthrough")
    reqs = int(signals.get("requests") or 0)
    saved_pct = float(signals.get("saved_pct") or 0)
    cache_hit = float(signals.get("cache_hit_pct") or 0)

    # 1) proxy state
    if not running:
        recs.append({"level": "warn", "title": "Proxy is stopped",
                     "detail": "Start it on the Optimize tab so live requests get optimized."})
    elif passthrough:
        recs.append({"level": "warn", "title": "Optimization is off (measure-only)",
                     "detail": "Flip the Optimize switch on to start compressing tool output before Claude."})
    elif reqs == 0:
        recs.append({"level": "info", "title": "Proxy on, no traffic yet",
                     "detail": "Point Claude Code at the proxy (Optimize tab) to measure real savings."})
    else:
        recs.append({"level": "good", "title": f"Optimization on - saving {saved_pct}% so far",
                     "detail": f"Across {reqs} request(s) routed through the proxy."})

    # 2) cache health
    if reqs > 0 and 0 < cache_hit < 50:
        recs.append({"level": "warn", "title": f"Cache hit only {cache_hit}%",
                     "detail": "Compression may be hurting prompt caching. For code-heavy work, try optimization off and compare."})

    # 3) heavy re-reads
    files = data.get("files") or []
    if files and files[0]["count"] >= 20:
        top = files[0]
        name = top["key"].replace("\\", "/").split("/")[-1]
        recs.append({"level": "warn", "title": f"{name} read {top['count']}x ({top['pct']}%)",
                     "detail": "Re-reads re-upload the whole file every turn. Keep it in context or read targeted line ranges."})

    # 4) rtk-optimizable noisy commands
    cmds = data.get("commands") or []
    noisy = next((c for c in cmds if c["key"].split()[0] in _RTK_NOISY and c["count"] >= 10), None)
    if noisy:
        recs.append({"level": "info", "title": f"{noisy['key']} ran {noisy['count']}x",
                     "detail": "Routing this through rtk strips noise from its output before it reaches the model."})
    cd = next((c for c in cmds if c["key"] == "cd"), None)
    if cd and cd["pct"] >= 40:
        recs.append({"level": "info", "title": f"cd is {cd['pct']}% of your commands",
                     "detail": "Mostly navigation, not real work. Chaining commands (cd X && cmd) cuts tool calls."})

    # 5) spend concentration
    projs = data.get("projects") or []
    total = sum(p["tokens"] for p in projs) or 1
    if projs and projs[0]["tokens"] / total >= 0.5:
        p = projs[0]
        recs.append({"level": "info", "title": f"{p['name']} is {round(100 * p['tokens'] / total)}% of your tokens",
                     "detail": f"Most of your spend is concentrated here (about ${p['cost']:.0f})."})

    if not recs:
        recs.append({"level": "good", "title": "Nothing urgent",
                     "detail": "No high-impact issues found in your recent usage."})
    return recs
