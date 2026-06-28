# Tokonomics - Claude Code project guide

Tokonomics has two halves:

1. **Active optimization proxy** (the main component) - sits in the live request
   path between Claude Code and `api.anthropic.com`, runs each request through an
   optimization pipeline (rtk-style compression + markitdown + prompt minify),
   and measures tokens saved before/after.
2. **Economics dashboard** (the original) - reports historical spend, savings,
   per-session health, and opportunities, built on `rtk` + `ccusage`.

Both are served by one local web app. The dashboard half remains a **UI layer**
on top of external tools (not vendored): [rtk](https://github.com/rtk-ai/rtk)
(savings) and [ccusage](https://github.com/ryoppippi/ccusage) (usage/spend).

## Architecture

```
Claude Code --(ANTHROPIC_BASE_URL=http://127.0.0.1:8788)--> proxy.py
                  optimize body (pipeline.py) + measure        |
                                                               v
                                            https://api.anthropic.com
                  <---------- stream SSE response back ---------

rtk gain / session / discover  \
ccusage session --json          >  economics.py --\
                               /                    server.py (8765) -> web/
                            proxy_log.jsonl --------/   /api/proxy/* + /api/economics
```

- `tokonomics/proxy.py` - stdlib streaming intercept proxy (default port 8788).
  Forwards `/v1/*` to the upstream, optimizes `/v1/messages` bodies, logs
  token-count-only records to `~/.tokonomics/proxy_log.jsonl`. Runs in a thread
  alongside the dashboard so a per-request error never kills the dashboard.
  Token counts are EXACT, resolved off the hot path after the response streams:
  the "after" count comes free from the response `usage` (`message_start` for
  streams), the "before" from a `/v1/messages/count_tokens` call. The local
  estimator is only a fallback. It also records `cache_read`/`cache_creation`
  so the UI can flag if optimization is hurting prompt-cache hit rate.
- `tokonomics/pipeline.py` - the three optimization stages + a local token
  estimator (tiktoken if installed, else chars/4) used only as a fallback.
  `optimize()` NEVER raises; on any error it returns the original body.
  Compression is DETERMINISTIC and applied UNIFORMLY to every message, and only
  ever touches `tool_result` / `document` blocks (tool output, logs, files, RAG
  chunks) - never `system` or the user's own text. Uniform determinism is what
  keeps the Anthropic prompt-cache prefix byte-stable across turns; treating the
  newest turn differently from history would force cache misses.
- `tokonomics/server.py` - Python stdlib HTTP server (dashboard + proxy control
  plane). Endpoints: `/api/economics`, `/api/gain`, `/api/config`,
  `/api/proxy/{status,stats,setup,start,stop,config}`.
- `tokonomics/economics.py` - merges rtk + ccusage, computes the health score
  (`0.5 x cache_efficiency + 0.5 x rtk_adoption`) and day/week/month buckets.
- `tokonomics/web/` - vanilla JS + vendored Chart.js UI. Views: Overview
  (economics), Optimize (proxy control + measured savings), Pulse (live request
  feed). The sidebar nav switches views.
- `tokonomics/sample/` - mock data used as fallback and for `?mock=1` preview.
- `tokonomics/bin/` - rtk binary, git-ignored (fetched via `scripts/install-rtk`).

## Run

```sh
pip install -e .[proxy]         # optional: enables markitdown + tiktoken
python -m tokonomics            # dashboard http://127.0.0.1:8765/ + proxy :8788
python -m tokonomics --port 9000 --proxy-port 9001 --price 3.5
python -m tokonomics --no-proxy # dashboard only
```

Route Claude Code through the proxy in a new shell:
`setx ANTHROPIC_BASE_URL "http://127.0.0.1:8788"` (Windows) then start `claude`.
Detach with `setx ANTHROPIC_BASE_URL ""`.

Prereqs: Python 3.9+. For the dashboard: `rtk` (scripts/install-rtk.ps1 or .sh,
or on PATH) and `ccusage` (`npm i -g ccusage`). For the proxy's full pipeline:
`pip install -e .[proxy]` (markitdown + tiktoken). Append `?mock=1` to preview
the dashboard with sample data.

## Conventions

- No emojis in code, docs, or commit messages.
- **Dependency policy (scoped):** the dashboard server stays dependency-free
  (stdlib only); the UI vendors Chart.js (MIT). The optional **proxy** may use
  `markitdown` + `tiktoken`, both lazily imported so the app still runs without
  them (markitdown stage no-ops, estimator falls back to chars/4).
- rtk and ccusage are external tools - never copy their source into this repo.
  Keep attribution in NOTICE / THIRD_PARTY_NOTICES.md.
- The proxy handles real API traffic: logs store **token counts only** - never
  message content, never API keys. Optimization must never raise into the live
  request path (fail open to passthrough), and must stay deterministic +
  uniform so it doesn't break prompt caching (the cache key is an exact byte
  prefix). Prefer exact `count_tokens` over the local estimator for any number
  shown to the user.
- MIT licensed. Use this project's own name/branding, not upstream marks.
