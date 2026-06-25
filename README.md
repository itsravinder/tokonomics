# TokenScope

A local web dashboard for **Claude token economics** on Windows (also macOS/Linux):
how many sessions you ran, how much you spent, how many tokens `rtk` saved, a
per-session **health score**, and concrete **opportunities** to save more.

> TokenScope is a **UI layer** built on top of two existing open-source tools:
> [**rtk**](https://github.com/rtk-ai/rtk) (token-savings engine) and
> [**ccusage**](https://github.com/ryoppippi/ccusage) (Claude usage and spend).
> It calls them as external programs and visualizes the result. It does not copy
> or modify their code. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## What it shows

- **Session health** (0-100 ring) = `0.5 x prompt quality + 0.5 x rtk adoption`
- **Claude usage** - sessions, tokens consumed, USD spent (from ccusage)
- **Saved by rtk** - tokens and dollars saved
- **Untapped potential** - extra savings available at full adoption (from `rtk discover`)
- **Spend vs savings** chart - day / week / month
- **Top opportunities** - exact commands to route through rtk, ranked by savings
- **Sessions** - per-session spend, adoption, and health

## How it works

```
rtk gain         (tokens saved)          \
ccusage session  (Claude spend/usage)     >  economics.py -> server.py -> browser
rtk session      (per-session adoption)   /
rtk discover     (missed savings)        /
```

The server is **Python standard library only** - no pip dependencies.

## Quick start

1. **Get the prerequisites**
   - Python 3.9+
   - `rtk`: `powershell -ExecutionPolicy Bypass -File scripts/install-rtk.ps1`
     (Windows) or `bash scripts/install-rtk.sh` (macOS/Linux). Or install rtk
     yourself and make sure it is on your `PATH`.
   - `ccusage` (for spend/usage): `npm i -g ccusage`
2. **Run**
   ```sh
   python -m tokenscope
   ```
   Open http://127.0.0.1:8765/

Optional install as a command:
```sh
pip install -e .
tokenscope --port 9000 --price 3.5
```

### Options

| Flag | Meaning |
| --- | --- |
| `--port` | server port (default 8765) |
| `--price` | USD per 1,000,000 saved tokens (default 3.0) |
| `--rtk` | path to the rtk executable (auto-detected if omitted) |

Append `?mock=1` to the URL to preview with bundled sample data before you have
real history.

## Auto-detection

- **rtk** is resolved in this order: `--rtk` flag -> `TOKENSCOPE_RTK` env var ->
  `rtk` on `PATH` -> bundled `tokenscope/bin/`.
- **ccusage** is resolved from `PATH`. If missing, usage/spend fall back to mock
  while rtk savings still work.

## Health score

- **prompt quality** = cache reuse: `cacheRead / (cacheRead + cacheCreate + input)`
  (from ccusage) - how efficiently context is reused across a session.
- **adoption** = compressible commands routed through rtk (from `rtk discover` /
  `rtk session`) - how much of your work actually benefits from rtk.

A high score means efficient prompts AND good rtk coverage.

## Notes on hitting big savings

Most token savings are missed not because the tools are weak but because
**adoption is low** - commands are not routed through rtk. The opportunities
panel tells you exactly which commands to switch. To cut output tokens too,
pair this with the [caveman](https://github.com/JuliusBrussee/caveman) skill.

## License

TokenScope is released under the [MIT License](LICENSE).
Third-party tools retain their own licenses - see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Acknowledgements

Built on the excellent work of [rtk](https://github.com/rtk-ai/rtk) and
[ccusage](https://github.com/ryoppippi/ccusage). This project is not affiliated
with or endorsed by their authors.
