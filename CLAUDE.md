# Tokonomics - Claude Code project guide

Tokonomics is a local web dashboard for **Claude token economics**: how many
sessions you ran, how much you spent, how many tokens `rtk` saved, a per-session
health score, and concrete opportunities to save more.

It is a **UI layer** on top of two existing tools, invoked as external programs
(not vendored): [rtk](https://github.com/rtk-ai/rtk) (savings) and
[ccusage](https://github.com/ryoppippi/ccusage) (Claude usage/spend).

## Architecture

```
rtk gain / session / discover   \
ccusage session --json           >  tokonomics/economics.py -> server.py -> web/
                                /
```

- `tokonomics/server.py` - Python stdlib HTTP server (no runtime deps).
  Endpoints: `/api/economics`, `/api/gain`, `/api/config`.
- `tokonomics/economics.py` - merges the data sources, computes the health score
  (`0.5 x cache_efficiency + 0.5 x rtk_adoption`) and day/week/month buckets.
- `tokonomics/web/` - vanilla JS + vendored Chart.js UI.
- `tokonomics/sample/` - mock data used as fallback and for `?mock=1` preview.
- `tokonomics/bin/` - rtk binary, git-ignored (fetched via `scripts/install-rtk`).

## Run

```sh
python -m tokonomics            # http://127.0.0.1:8765/
python -m tokonomics --port 9000 --price 3.5
```

Prereqs: Python 3.9+, `rtk` (scripts/install-rtk.ps1 or .sh, or on PATH),
`ccusage` (`npm i -g ccusage`). Append `?mock=1` to preview with sample data.

## Conventions

- No emojis in code, docs, or commit messages.
- The server stays dependency-free (stdlib only); the UI vendors Chart.js (MIT).
- rtk and ccusage are external tools - never copy their source into this repo.
  Keep attribution in NOTICE / THIRD_PARTY_NOTICES.md.
- MIT licensed. Use this project's own name/branding, not upstream marks.
