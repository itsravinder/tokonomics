# Third-party notices

TokenScope is an independent UI layer. It calls the tools below as external
programs (subprocesses) and does not copy or modify their source code. Their
licenses are reproduced/linked here as attribution.

## rtk

- Project: https://github.com/rtk-ai/rtk
- License: Apache License 2.0
- Role: provides token-savings data (`rtk gain`, `rtk session`, `rtk discover`).
- Distribution: NOT bundled in this repository. Users obtain the official
  binary via `scripts/install-rtk.ps1` / `scripts/install-rtk.sh`, or their own
  install (Homebrew, cargo, release download). If you choose to bundle the rtk
  binary in a fork, include rtk's `LICENSE` and `NOTICE` files alongside it and
  state any changes, per the Apache-2.0 terms. Do not use the rtk name or marks
  to brand a fork.

## ccusage

- Project: https://github.com/ryoppippi/ccusage
- License: MIT License
- Role: reads Claude Code's local usage logs to report sessions, tokens, and
  USD cost (`ccusage session --json`).
- Distribution: NOT bundled. Users install it with `npm i -g ccusage`.

## Chart.js

- Project: https://github.com/chartjs/Chart.js
- License: MIT License
- Role: renders the spend-vs-savings chart.
- Distribution: bundled as `tokenscope/web/chart.umd.min.js`. The MIT license
  permits redistribution provided this notice is retained.

---

These notices satisfy attribution requirements but are not legal advice. If you
redistribute a build that bundles any of the above (for example, a Windows
installer that ships the rtk binary), include that component's full license
text and comply with its terms.
