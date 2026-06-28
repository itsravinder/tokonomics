/* rtk-dashboard - Claude token economics
 * Pulls /api/economics (rtk gain + ccusage + rtk session + rtk discover)
 * and renders health, usage, savings, spend-vs-savings chart, opportunities.
 */

const COLORS = {
  primary: "#4f46e5",
  sky: "#0ea5e9",
  emerald: "#059669",
  violet: "#7c3aed",
  ink: "#171a2b",
  muted: "#7e859a",
  grid: "#e9ebf3",
};
const RING_C = 2 * Math.PI * 52; // ~326.7

let state = { period: "daily", price: 3.0, payload: null, chart: null };

// ---- formatting -----------------------------------------------------------
function fmtTokens(n) {
  n = Number(n) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(2).replace(/\.?0+$/, "") + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
  return String(n);
}
function fmtUsd(v) {
  v = Number(v) || 0;
  if (v >= 1000) return "$" + Math.round(v).toLocaleString();
  if (v >= 1) return "$" + v.toFixed(2).replace(/\.00$/, "");
  return "$" + v.toFixed(2);
}
function bucketLabel(key) {
  if (/^\d{4}-\d{2}-\d{2}$/.test(key)) {
    const [, m, d] = key.split("-");
    const mo = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m)];
    return `${mo} ${Number(d)}`;
  }
  if (/^\d{4}-\d{2}$/.test(key)) {
    const [, m] = key.split("-");
    return ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m)];
  }
  return key;
}

// ---- status ---------------------------------------------------------------
function renderStatus(p) {
  const el = document.getElementById("status");
  const txt = document.getElementById("statusText");
  const badge = document.getElementById("srcBadge");
  const meta = document.getElementById("scanMeta");
  const t = p.totals || {};
  const errs = Object.keys(p.errors || {});
  el.classList.toggle("off", p.source === "mock" && errs.length > 0);

  if (p.source === "live") {
    txt.textContent = "Connected to your Claude history.";
    badge.textContent = "LIVE";
  } else if (p.source === "live-empty") {
    txt.textContent = "Connected - no Claude usage found yet.";
    badge.textContent = "LIVE (empty)";
  } else {
    txt.textContent = errs.length ? "Sample data - " + errs.join(", ") : "Showing sample data.";
    badge.textContent = "MOCK";
  }
  meta.textContent = t.sessions_scanned
    ? `${t.sessions} sessions - ${t.commands_scanned.toLocaleString()} commands scanned`
    : `${t.sessions || 0} sessions`;
}

// ---- cards -----------------------------------------------------------------
function renderCards(p) {
  const t = p.totals || {}, h = p.health || {};

  // health ring
  const score = Math.max(0, Math.min(100, h.score || 0));
  document.getElementById("healthScore").textContent = score;
  const ring = document.getElementById("ringFg");
  ring.style.strokeDashoffset = RING_C * (1 - score / 100);
  ring.style.stroke = score >= 67 ? COLORS.emerald : score >= 40 ? "#d97706" : "#e11d48";
  document.getElementById("hQuality").textContent = (h.cache_efficiency || 0) + "%";
  document.getElementById("hAdoption").textContent = (h.optimization || 0) + "%";

  // usage
  document.getElementById("sessions").textContent = t.sessions || 0;
  document.getElementById("consumed").textContent = fmtTokens(t.consumed_tokens) + " tokens";
  document.getElementById("spend").textContent = (t.spend_usd || 0).toLocaleString();

  // saved
  document.getElementById("savedTokens").textContent = fmtTokens(t.saved_tokens);
  document.getElementById("savedUsd").textContent = fmtUsd(t.saved_usd);
  document.getElementById("savedPct").textContent = (t.avg_savings_pct || 0) + "%";

  // potential
  document.getElementById("potentialUsd").textContent = fmtUsd(t.potential_usd);
  document.getElementById("potentialTokens").textContent = fmtTokens(t.potential_tokens) + " tokens unsaved";
}

// ---- chart -----------------------------------------------------------------
function renderChart(p) {
  const rows = (p.buckets && p.buckets[state.period]) || [];
  const labels = rows.map(r => bucketLabel(r.key));
  const spend = rows.map(r => r.spend_usd || 0);
  const saved = rows.map(r => r.saved_usd || 0);

  document.getElementById("note").textContent = rows.length
    ? `Bars = USD spent on Claude, line = USD saved by rtk (at $${state.price.toFixed(2)}/1M saved tokens).`
    : "No usage in this range yet.";

  const cfg = {
    type: "bar",
    data: {
      labels,
      datasets: [
        { type: "bar", label: "Spent", data: spend, backgroundColor: COLORS.sky, borderRadius: 4, maxBarThickness: 40, order: 2 },
        { type: "line", label: "Saved by rtk", data: saved, yAxisID: "y1", borderColor: COLORS.emerald, backgroundColor: COLORS.emerald,
          tension: 0.3, borderWidth: 2.5, pointRadius: 3, pointBackgroundColor: COLORS.emerald, order: 1 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: { duration: 450 },
      plugins: {
        legend: { display: true, position: "top", align: "end", labels: { boxWidth: 12, color: COLORS.muted, font: { size: 12 } } },
        tooltip: {
          callbacks: {
            afterTitle: (items) => {
              const r = rows[items[0].dataIndex];
              return [
                `Spent: ${fmtTokens(r.consumed_tokens)} tokens`,
                `Saved by rtk: ${fmtTokens(r.saved_tokens || 0)} tokens`,
                `${r.sessions} session(s)`,
              ];
            },
            label: (ctx) => `${ctx.dataset.label}: ${fmtUsd(ctx.parsed.y)}`,
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: COLORS.muted } },
        y: { grid: { color: COLORS.grid }, ticks: { color: COLORS.muted, callback: (v) => fmtUsd(v) },
          title: { display: true, text: "spent", color: COLORS.muted, font: { size: 11 } } },
        y1: { position: "right", grid: { display: false }, beginAtZero: true,
          ticks: { color: COLORS.emerald, callback: (v) => fmtUsd(v) },
          title: { display: true, text: "saved", color: COLORS.emerald, font: { size: 11 } } },
      },
    },
  };

  if (state.chart) { state.chart.data = cfg.data; state.chart.options = cfg.options; state.chart.update(); }
  else state.chart = new Chart(document.getElementById("chart"), cfg);
}

// ---- opportunities ---------------------------------------------------------
function renderOpps(p) {
  const el = document.getElementById("opps");
  const opps = p.opportunities || [];
  if (!opps.length) { el.innerHTML = `<div class="row"><span class="grow cat">No missed savings found - nice adoption.</span></div>`; return; }
  el.innerHTML = opps.map(o => `
    <div class="row">
      <span class="mono">${o.command}</span>
      <span class="arrow">&rarr;</span>
      <span class="pill">${o.rtk_equivalent}</span>
      <span class="count">x${o.count}</span>
      <span class="grow cat">${o.category}</span>
      <span class="save">${fmtTokens(o.saved_tokens)} &middot; ${o.saved_pct}%</span>
    </div>`).join("");
}

// ---- sessions --------------------------------------------------------------
function renderSessions(p) {
  const el = document.getElementById("sessRows");
  const ss = p.sessions || [];
  if (!ss.length) { el.innerHTML = `<div class="srow"><span class="grow cat">No sessions yet.</span></div>`; return; }
  el.innerHTML = ss.slice(0, 8).map(s => {
    const cls = s.health >= 67 ? "good" : s.health >= 40 ? "mid" : "low";
    return `
    <div class="srow">
      <span class="sid">${s.id}</span>
      <span><span class="sdate">${s.date}</span> &middot; ${fmtTokens(s.consumed_tokens)} &middot; ${s.adoption_pct}% rtk</span>
      <span class="sspend">${fmtUsd(s.spend_usd)}</span>
      <span class="hscore ${cls}">${s.health}</span>
    </div>`;
  }).join("");
}

// ---- load + wiring ---------------------------------------------------------
async function load() {
  const forceMock = new URLSearchParams(location.search).get("mock") === "1";
  const res = await fetch("/api/economics" + (forceMock ? "?mock=1" : ""));
  const p = await res.json();
  state.payload = p;
  state.price = p.price_per_mtok || state.price;
  renderStatus(p);
  renderCards(p);
  renderChart(p);
  renderOpps(p);
  renderSessions(p);
}

document.getElementById("seg").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  state.period = btn.dataset.p;
  [...document.querySelectorAll("#seg button")].forEach(b => b.classList.toggle("active", b === btn));
  renderChart(state.payload);
});

// ---- proxy view ------------------------------------------------------------
let proxy = { status: null, timer: null };

async function jpost(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

function fmtClock(ts) {
  const d = new Date((Number(ts) || 0) * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function renderProxyStatus(s) {
  proxy.status = s;
  const on = !!s.running;
  document.getElementById("proxyStatus").classList.toggle("on", on);
  document.getElementById("psTitle").textContent = on ? "Proxy running" : "Proxy stopped";
  document.getElementById("psSub").textContent = on
    ? `Listening on ${s.base_url} -> ${s.upstream}`
    : "Routes live Claude Code traffic through the optimization pipeline.";
  const est = s.tiktoken ? "tiktoken fallback" : "chars/4 fallback";
  document.getElementById("psMeta").textContent = `${(s.counters || {}).requests || 0} req - exact via count_tokens (${est})`;
  const btn = document.getElementById("proxyToggle");
  btn.textContent = on ? "Stop proxy" : "Start proxy";
  btn.classList.toggle("stop", on);

  // master switch: ON = optimizing, OFF = passthrough (measure-only)
  const cfg = s.config || {};
  const optOn = !cfg.passthrough;
  const master = document.getElementById("optMaster");
  if (master) master.checked = optOn;
  document.querySelector(".master-card").classList.toggle("off", !optOn);
  document.getElementById("optTitle").textContent = optOn ? "Token optimization: on" : "Token optimization: off";
  document.getElementById("optSub").textContent = optOn
    ? "Compressing tool output, logs, files & JSON before they reach Claude."
    : "Measuring only - counting tokens and money saved; requests reach Claude unchanged.";

  // advanced per-stage toggles (disabled while optimization is off)
  document.querySelectorAll("#toggles input").forEach(inp => {
    inp.checked = cfg[inp.dataset.k] !== false;
    inp.disabled = !optOn;
  });
}

function renderProxyStats(st) {
  document.getElementById("pxOrig").textContent = fmtTokens(st.orig_tokens);
  document.getElementById("pxOpt").textContent = fmtTokens(st.opt_tokens);
  document.getElementById("pxSaved").textContent = fmtTokens(st.saved_tokens);
  document.getElementById("pxSavedPct").textContent = (st.saved_pct || 0) + "%";
  document.getElementById("pxSavedUsd").textContent = fmtUsd(st.saved_usd);
  document.getElementById("pxReq").textContent = st.requests || 0;

  const stg = st.stages || {}, su = st.stages_usd || {};
  document.getElementById("stageRows").innerHTML = ["rtk", "markitdown", "prompt"].map(k => `
    <div class="row">
      <span class="pill">${k}</span>
      <span class="grow cat">${fmtUsd(su[k] || 0)} saved</span>
      <span class="save">${fmtTokens(stg[k] || 0)}</span>
    </div>`).join("");

  // method + cache-health note
  const reqs = st.requests || 0, exact = st.exact_requests || 0;
  const methodTxt = reqs
    ? (exact === reqs ? "All counts exact (count_tokens)."
       : exact ? `${exact}/${reqs} counts exact (count_tokens); rest estimated.`
       : "Counts estimated (count_tokens unavailable).")
    : "No requests yet.";
  const cacheTxt = (st.cache_read_tokens || st.cache_hit_pct)
    ? ` Cache: ${st.cache_hit_pct}% of cacheable prompt read from cache (${fmtTokens(st.cache_read_tokens)} tokens). Higher is cheaper - watch this stay high.`
    : "";
  document.getElementById("pxMethod").textContent = methodTxt + cacheTxt;

  const recent = st.recent || [];
  const rows = recent.map(r => {
    const warn = (r.status || "ok") !== "ok" && r.status !== "passthrough";
    const tag = r.method === "exact" ? "exact" : (r.status || "ok");
    return `<div class="prow">
      <span class="ptime">${fmtClock(r.ts)}</span>
      <span class="pflow">${fmtTokens(r.orig_tokens)}<span class="arrow">&rarr;</span>${fmtTokens(r.opt_tokens)}</span>
      <span class="psave">-${fmtTokens(r.saved_tokens)}</span>
      <span class="pstat ${warn ? "warn" : ""}">${tag}</span>
    </div>`;
  }).join("");
  const empty = `<div class="prow"><span class="grow cat">No requests yet. Connect Claude Code and start a session.</span></div>`;
  document.getElementById("pulseRows").innerHTML = rows || empty;
}

async function loadProxy() {
  try {
    const [s, st, setup] = await Promise.all([
      fetch("/api/proxy/status").then(r => r.json()),
      fetch("/api/proxy/stats").then(r => r.json()),
      fetch("/api/proxy/setup").then(r => r.json()),
    ]);
    renderProxyStatus(s);
    renderProxyStats(st);
    document.getElementById("setupCmd").textContent = setup.windows_persist;
  } catch (e) { /* dashboard may be reloading */ }
}

document.getElementById("proxyToggle").addEventListener("click", async () => {
  const running = proxy.status && proxy.status.running;
  await jpost(running ? "/api/proxy/stop" : "/api/proxy/start");
  loadProxy();
});

// master switch: checked = optimize (passthrough off); unchecked = measure-only
document.getElementById("optMaster").addEventListener("change", async (e) => {
  const s = await jpost("/api/proxy/config", { passthrough: !e.target.checked });
  renderProxyStatus(s);
});

document.getElementById("toggles").addEventListener("change", async (e) => {
  const inp = e.target.closest("input");
  if (!inp) return;
  const s = await jpost("/api/proxy/config", { [inp.dataset.k]: inp.checked });
  renderProxyStatus(s);
});

document.getElementById("copySetup").addEventListener("click", async () => {
  const txt = document.getElementById("setupCmd").textContent;
  try { await navigator.clipboard.writeText(txt); } catch (e) {}
  const btn = document.getElementById("copySetup");
  btn.textContent = "Copied"; setTimeout(() => (btn.textContent = "Copy"), 1200);
});

// ---- insights view ---------------------------------------------------------
function esc(s) { return String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
function shortPath(p) { return String(p).split(/[\\/]/).slice(-2).join("/"); }
function emptyRow(t) { return `<div class="row"><span class="grow cat">${t}</span></div>`; }

function listRows(items, fmtKey) {
  items = items || [];
  if (!items.length) return emptyRow("Nothing yet.");
  return items.map(i => `
    <div class="row">
      <span class="mono">${esc(fmtKey ? fmtKey(i.key) : i.key)}</span>
      <span class="grow"></span>
      <span class="count">x${i.count}</span>
      <span class="save">${i.pct}%</span>
    </div>`).join("");
}

let insightsData = null;

function renderInsightActivity() {
  const d = insightsData;
  if (!d) return;
  const sel = document.getElementById("inProject").value;
  const t = d.totals || {};

  if (sel === "__all__") {
    document.getElementById("inLbl1").textContent = "Projects";
    document.getElementById("inVal1").textContent = t.projects || 0;
    document.getElementById("inSub1").textContent = "with Claude usage";
    document.getElementById("inVal2").textContent = (t.files_touched || 0).toLocaleString();
    document.getElementById("inVal3").textContent = (t.tool_calls || 0).toLocaleString();
    document.getElementById("inFileRows").innerHTML = listRows(d.files, shortPath);
    document.getElementById("inCmdRows").innerHTML = listRows(d.commands);
    return;
  }

  const scope = (d.by_project || {})[sel] || { files: [], commands: [], files_touched: 0, tool_calls: 0 };
  const proj = (d.projects || []).find(p => p.project === sel) || { tokens: 0, cost: 0, name: sel };
  document.getElementById("inLbl1").textContent = "Tokens";
  document.getElementById("inVal1").textContent = fmtTokens(proj.tokens);
  document.getElementById("inSub1").textContent = `${fmtUsd(proj.cost)} · ${esc(proj.name)}`;
  document.getElementById("inVal2").textContent = (scope.files_touched || 0).toLocaleString();
  document.getElementById("inVal3").textContent = (scope.tool_calls || 0).toLocaleString();
  document.getElementById("inFileRows").innerHTML = listRows(scope.files, shortPath);
  document.getElementById("inCmdRows").innerHTML = listRows(scope.commands);
}

async function loadInsights() {
  let d;
  const forceMock = new URLSearchParams(location.search).get("mock") === "1";
  try { d = await fetch("/api/insights" + (forceMock ? "?mock=1" : "")).then(r => r.json()); } catch (e) { return; }
  insightsData = d;

  const recs = d.recommendations || [];
  document.getElementById("inRecs").innerHTML = recs.length ? recs.map(r => `
    <div class="rec ${r.level}">
      <span class="rdot"></span>
      <span class="rbody"><b>${esc(r.title)}</b><small>${esc(r.detail)}</small></span>
    </div>`).join("") : emptyRow("No recommendations.");

  const projs = d.projects || [];
  document.getElementById("inProjRows").innerHTML = projs.length ? projs.map(p => `
    <div class="row">
      <span class="grow"><b>${esc(p.name)}</b></span>
      <span class="count">${fmtUsd(p.cost)}</span>
      <span class="save">${fmtTokens(p.tokens)}</span>
    </div>`).join("") : emptyRow("No project usage found.");

  // populate the project filter (preserve selection across reloads)
  const dd = document.getElementById("inProject");
  const prev = dd.value;
  dd.innerHTML = `<option value="__all__">All projects</option>` +
    projs.map(p => `<option value="${esc(p.project)}">${esc(p.name)}</option>`).join("");
  if ([...dd.options].some(o => o.value === prev)) dd.value = prev;

  renderInsightActivity();
}

document.getElementById("inProject").addEventListener("change", renderInsightActivity);

// ---- nav / view switching --------------------------------------------------
function showView(view) {
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + view));
  document.querySelectorAll(".nav-item[data-view]").forEach(n => n.classList.toggle("active", n.dataset.view === view));
  const proxyView = view === "optimize" || view === "pulse";
  clearInterval(proxy.timer);
  if (proxyView) { loadProxy(); proxy.timer = setInterval(loadProxy, 4000); }
  if (view === "insights") loadInsights();
  try { history.replaceState(null, "", "#" + view); } catch (e) { /* ignore */ }
}

document.querySelectorAll(".nav-item[data-view]").forEach(item => {
  item.addEventListener("click", () => showView(item.dataset.view));
});

load();

// deep-link: honor #optimize / #pulse / #insights on first load
const _initView = (location.hash || "").replace("#", "");
if (["optimize", "pulse", "insights"].includes(_initView)) showView(_initView);
