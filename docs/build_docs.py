"""
Generate docs/Tokonomics-Documentation.pdf from the content below.
Regenerate with:  python docs/build_docs.py
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Preformatted, Table, TableStyle,
    PageBreak, HRFlowable,
)

OUT = Path(__file__).resolve().parent / "Tokonomics-Documentation.pdf"

INK = colors.HexColor("#171a2b")
INDIGO = colors.HexColor("#4f46e5")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#e6e8f0")
CODEBG = colors.HexColor("#f3f4fa")
EMERALD = colors.HexColor("#059669")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle("TkCover", parent=styles["Title"], fontSize=34, textColor=INDIGO, spaceAfter=6))
styles.add(ParagraphStyle("TkCoverSub", parent=styles["Normal"], fontSize=13, textColor=MUTED, alignment=TA_CENTER, spaceAfter=4))
styles.add(ParagraphStyle("TkH1", parent=styles["Heading1"], fontSize=18, textColor=INDIGO, spaceBefore=16, spaceAfter=8))
styles.add(ParagraphStyle("TkH2", parent=styles["Heading2"], fontSize=13.5, textColor=INK, spaceBefore=12, spaceAfter=5))
styles.add(ParagraphStyle("TkBody", parent=styles["BodyText"], fontSize=10.3, leading=15, textColor=INK, spaceAfter=7))
styles.add(ParagraphStyle("TkBullet", parent=styles["TkBody"], leftIndent=14, bulletIndent=4, spaceAfter=3))
styles.add(ParagraphStyle("TkCode", parent=styles["Code"], fontSize=8.4, leading=11.5, textColor=INK))
styles.add(ParagraphStyle("TkSmall", parent=styles["Normal"], fontSize=8.5, textColor=MUTED))

story = []


def h1(t): story.append(Paragraph(t, styles["TkH1"]))
def h2(t): story.append(Paragraph(t, styles["TkH2"]))
def p(t): story.append(Paragraph(t, styles["TkBody"]))
def sp(h=6): story.append(Spacer(1, h))
def bullets(items):
    for it in items:
        story.append(Paragraph(it, styles["TkBullet"], bulletText="•"))
    sp(4)


def code(text):
    box = Table([[Preformatted(text.strip(chr(10)), styles["TkCode"])]], colWidths=[165 * mm])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODEBG),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(box)
    sp(8)


def table(rows, widths):
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CODEBG]),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
    ]))
    story.append(t)
    sp(8)


def cell(t):
    return Paragraph(t, ParagraphStyle("c", parent=styles["Normal"], fontSize=9, leading=12.5, textColor=INK))


# ---------------------------------------------------------------- cover
sp(150)
story.append(Paragraph("Tokonomics", styles["TkCover"]))
story.append(Paragraph("Active Claude token-optimization proxy + economics dashboard", styles["TkCoverSub"]))
story.append(Paragraph("Project Documentation", styles["TkCoverSub"]))
sp(10)
story.append(HRFlowable(width="40%", thickness=1, color=LINE))
sp(10)
story.append(Paragraph("Local web app &middot; Python stdlib server &middot; MIT licensed", styles["TkCoverSub"]))
story.append(PageBreak())

# ---------------------------------------------------------------- overview
h1("1. Overview")
p("Tokonomics is a local web application with two halves that share one UI:")
bullets([
    "<b>Active optimization proxy (main component)</b> &mdash; sits in the live request path "
    "between Claude Code and <font face='Courier'>api.anthropic.com</font>, runs each request "
    "through an optimization pipeline (rtk-style compression + markitdown + prompt minify), and "
    "measures tokens saved before vs. after.",
    "<b>Economics dashboard</b> &mdash; reports historical spend, savings, per-session health, "
    "and where your tokens go, built on the external tools <font face='Courier'>rtk</font> and "
    "<font face='Courier'>ccusage</font>.",
])
p("The dashboard half is a UI layer over external tools (never vendored). The proxy half is the "
  "active optimizer. Both run from one command and one local web server.")

# ---------------------------------------------------------------- architecture
h1("2. Architecture")
code(
    "Claude Code --(ANTHROPIC_BASE_URL=http://127.0.0.1:8788)--> proxy.py\n"
    "                  optimize body (pipeline.py) + measure        |\n"
    "                                                               v\n"
    "                                            https://api.anthropic.com\n"
    "                  <---------- stream SSE response back ---------\n\n"
    "rtk gain / session / discover  \\\n"
    "ccusage session --json          >  economics.py --\\\n"
    "                               /                    server.py (8765) -> web/\n"
    "          ~/.claude/projects + proxy_log.jsonl ----/   /api/* endpoints"
)
p("No TLS interception is needed: Claude Code talks plain HTTP to the local proxy, and the proxy "
  "makes its own HTTPS call upstream, streaming the response straight back. Auth headers are "
  "forwarded untouched, so existing login keeps working.")

h2("Components")
table([
    [cell("File"), cell("Responsibility")],
    [cell("<font face='Courier'>tokonomics/proxy.py</font>"),
     cell("Streaming intercept proxy (port 8788). Forwards <font face='Courier'>/v1/*</font>, optimizes "
          "<font face='Courier'>/v1/messages</font> bodies, resolves exact token counts off the hot path, "
          "logs token-count-only records to <font face='Courier'>~/.tokonomics/proxy_log.jsonl</font>.")],
    [cell("<font face='Courier'>tokonomics/pipeline.py</font>"),
     cell("The three optimization stages + a local token estimator (tiktoken or chars/4, fallback only). "
          "<font face='Courier'>optimize()</font> never raises.")],
    [cell("<font face='Courier'>tokonomics/server.py</font>"),
     cell("Python stdlib HTTP server (dashboard + proxy control plane). Serves the web UI and the JSON APIs.")],
    [cell("<font face='Courier'>tokonomics/economics.py</font>"),
     cell("Merges rtk + ccusage, computes the health score and day/week/month buckets, and the Insights "
          "breakdowns + recommendations.")],
    [cell("<font face='Courier'>tokonomics/web/</font>"),
     cell("Vanilla JS + vendored Chart.js UI. Views: Overview, Optimize, Pulse, Insights.")],
], [48 * mm, 117 * mm])

# ---------------------------------------------------------------- proxy
h1("3. The optimization proxy")
p("Claude Code honours the <font face='Courier'>ANTHROPIC_BASE_URL</font> environment variable. "
  "Point it at the local proxy and traffic flows through Tokonomics on the way to Anthropic. "
  "For each <font face='Courier'>/v1/messages</font> request the proxy:")
bullets([
    "reads and parses the JSON body;",
    "runs it through <font face='Courier'>pipeline.optimize()</font> (never raises; degrades to passthrough);",
    "forwards the optimized body upstream and streams the response back byte-for-byte (SSE or not);",
    "resolves exact token counts and appends a token-count-only log record &mdash; off the hot path.",
])

h1("4. The optimization pipeline")
p("Three stages run over the request's message blocks. They only ever touch "
  "<font face='Courier'>tool_result</font> and <font face='Courier'>document</font> blocks "
  "(machine output: tool results, logs, files, RAG chunks) &mdash; never the system prompt or the "
  "user's own text.")
table([
    [cell("Stage"), cell("What it does"), cell("Risk")],
    [cell("<b>rtk</b>"), cell("Strips ANSI codes, collapses blank runs, dedupes identical lines in noisy "
                              "command/log output. Truncation of huge outputs is opt-in."), cell("Low")],
    [cell("<b>markitdown</b>"), cell("Converts base64 PDF/Office <font face='Courier'>document</font> blocks "
                                     "to clean markdown. Memoized by content hash."), cell("Medium (doc fidelity)")],
    [cell("<b>prompt</b>"), cell("Minifies embedded JSON only (whitespace there is insignificant). Leaves "
                                 "code / YAML / diffs untouched."), cell("Low")],
], [26 * mm, 110 * mm, 29 * mm])

h2("Safety guarantees")
bullets([
    "<b>Never raises into the live path</b> &mdash; any failure returns the original body (passthrough).",
    "<b>Deterministic + uniform</b> &mdash; a given tool result compresses to identical bytes whether it is "
    "the newest turn or deep in history. This keeps Anthropic prompt-caching prefixes byte-stable across "
    "turns; non-deterministic or position-dependent rewriting would force cache misses that cost more than "
    "they save.",
    "<b>Logs store token counts only</b> &mdash; never message content, never API keys.",
    "<b>Master OFF switch</b> turns the proxy into a pure relay (measure-only).",
])

h1("5. Exact token counting")
p("Token counts shown to the user are <b>exact</b>, resolved off the hot path after the response "
  "streams:")
bullets([
    "<b>After (optimized)</b> count comes free from the response <font face='Courier'>usage</font> "
    "(parsed from the <font face='Courier'>message_start</font> SSE event for streams).",
    "<b>Before (original)</b> count comes from a <font face='Courier'>/v1/messages/count_tokens</font> call.",
    "The local tiktoken / chars-per-4 estimator is used only as a fallback when count_tokens is unavailable. "
    "Each request is tagged exact vs. estimate.",
    "<font face='Courier'>cache_read</font> / <font face='Courier'>cache_creation</font> are also recorded so "
    "the UI can flag if optimization is hurting prompt-cache hit rate.",
])

# ---------------------------------------------------------------- views
h1("6. The web views")
h2("Overview")
p("Session health ring, Claude usage (sessions / tokens / spend), savings, untapped potential, a "
  "spend-vs-savings chart (day / week / month), top opportunities, and the per-session table.")
h2("Optimize")
p("The headline control. A single master switch:")
bullets([
    "<b>ON</b> &mdash; compresses tool output, logs, files and JSON before they reach Claude. Advanced "
    "per-stage toggles (rtk / markitdown / prompt / truncate) are available below.",
    "<b>OFF</b> &mdash; measure-only: requests reach Claude unchanged, Tokonomics just counts tokens and "
    "money. The advanced toggles grey out.",
])
p("Also shows the connect command, original vs. optimized tokens, % and $ saved, request count, and "
  "exact-vs-estimate + cache health.")
h2("Pulse")
p("A live feed of recent proxied requests (time, model, original &rarr; optimized, saved, status) &mdash; "
  "token counts only.")
h2("Insights")
p("Where your tokens go, with an All / per-project dropdown:")
bullets([
    "<b>Tokens by project</b> &mdash; per-project token totals and cost.",
    "<b>Most-read files</b> &mdash; top files read/edited, with count and share (re-reads re-upload every turn).",
    "<b>Most-run commands</b> &mdash; top bash commands grouped (e.g. <font face='Courier'>git add</font>), "
    "with count and percentage.",
    "<b>Recommendations</b> &mdash; actionable advice derived from the data (noisy commands, heavy re-reads, "
    "proxy off, low cache hit, spend concentration).",
])
p("This is read-only analysis of local <font face='Courier'>~/.claude/projects</font> transcripts joined "
  "with ccusage totals &mdash; the proxy logs nothing extra.")

h1("7. Health score")
p("Health blends prompt quality with how much the proxy is actually optimizing:")
code("health = 0.5 x quality (cache reuse) + 0.5 x optimization (proxy savings %)")
bullets([
    "<b>quality</b> = <font face='Courier'>cacheRead / (cacheRead + cacheCreate + input)</font> &mdash; how "
    "efficiently context is reused (from ccusage).",
    "<b>optimization</b> = the live proxy's measured savings rate (0 when the proxy is off or idle).",
])
p("The score rises as the proxy saves tokens on real traffic &mdash; a metric you control, replacing the "
  "earlier rtk-adoption input.")

# ---------------------------------------------------------------- run
h1("8. Setup &amp; run")
code(
    "pip install -e .[proxy]         # optional: enables markitdown + tiktoken\n"
    "python -m tokonomics            # dashboard http://127.0.0.1:8765 + proxy :8788\n"
    "python -m tokonomics --port 9000 --proxy-port 9001 --price 3.5\n"
    "python -m tokonomics --no-proxy # dashboard only"
)
p("Route Claude Code through the proxy in a new shell, then start <font face='Courier'>claude</font>:")
code('setx ANTHROPIC_BASE_URL "http://127.0.0.1:8788"     ::  detach later: setx ANTHROPIC_BASE_URL ""')
p("Prerequisites: Python 3.9+. Dashboard data needs <font face='Courier'>rtk</font> "
  "(scripts/install-rtk) and <font face='Courier'>ccusage</font> "
  "(<font face='Courier'>npm i -g ccusage</font>). The proxy's full pipeline needs "
  "<font face='Courier'>pip install -e .[proxy]</font>.")

h2("Auto-start on login (Windows)")
bullets([
    "<font face='Courier'>scripts/start-tokonomics.bat</font> and "
    "<font face='Courier'>.ps1</font> launch the app minimized and log to "
    "<font face='Courier'>%TEMP%\\tokonomics.log</font>.",
    "<font face='Courier'>Tokonomics.bat</font> in the Startup folder auto-runs on login. "
    "(Windows does not auto-run <font face='Courier'>.ps1</font> from Startup &mdash; the .bat is the "
    "effective entry.)",
])

h1("9. API endpoints")
table([
    [cell("Endpoint"), cell("Purpose")],
    [cell("<font face='Courier'>GET /api/economics</font>"), cell("Overview payload: health, totals, buckets, sessions, opportunities.")],
    [cell("<font face='Courier'>GET /api/insights</font>"), cell("Per-project tokens, most-read files, most-run commands, recommendations.")],
    [cell("<font face='Courier'>GET /api/config</font>"), cell("rtk/ccusage presence, price.")],
    [cell("<font face='Courier'>GET /api/proxy/status</font>"), cell("Running?, port, upstream, pipeline config, counters.")],
    [cell("<font face='Courier'>GET /api/proxy/stats</font>"), cell("Aggregated savings, per-stage, cache health, recent requests.")],
    [cell("<font face='Courier'>GET /api/proxy/setup</font>"), cell("Exact ANTHROPIC_BASE_URL set/unset commands.")],
    [cell("<font face='Courier'>POST /api/proxy/{start,stop,config}</font>"), cell("Start/stop the proxy; toggle pipeline stages / passthrough.")],
], [62 * mm, 103 * mm])

h1("10. Privacy, conventions &amp; license")
bullets([
    "<b>Privacy</b> &mdash; the proxy handles real API traffic but logs token counts only; never message "
    "content, never API keys. Insights reads local transcripts already on disk.",
    "<b>Dependencies (scoped)</b> &mdash; the dashboard server is stdlib-only; the UI vendors Chart.js (MIT); "
    "the optional proxy may use markitdown + tiktoken (lazily imported, so the app runs without them).",
    "<b>External tools</b> &mdash; rtk and ccusage are invoked as programs, never vendored. Attribution lives "
    "in THIRD_PARTY_NOTICES.md.",
    "<b>License</b> &mdash; MIT.",
])
sp(10)
story.append(HRFlowable(width="100%", thickness=0.5, color=LINE))
sp(4)
story.append(Paragraph("Generated from docs/build_docs.py &middot; Tokonomics is not affiliated with or "
                       "endorsed by the authors of rtk or ccusage.", styles["TkSmall"]))


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 12 * mm, "Tokonomics &mdash; Project Documentation".replace("&mdash;", "-"))
    canvas.drawRightString(190 * mm, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(
    str(OUT), pagesize=A4,
    leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
    title="Tokonomics - Project Documentation", author="Tokonomics",
)
doc.build(story, onLaterPages=_footer, onFirstPage=lambda c, d: None)
print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
