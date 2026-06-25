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
  document.getElementById("hAdoption").textContent = (h.adoption || 0) + "%";

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
              return `${fmtTokens(r.consumed_tokens)} tokens - ${r.sessions} session(s)`;
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

load();
