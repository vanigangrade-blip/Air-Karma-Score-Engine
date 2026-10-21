"use strict";
window.__appStarted = true;
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v) ? "n/a" : Number(v).toFixed(d));
const COLORS = { "Clean": "#2e9e6f", "Fair": "#9bbf3a", "Poor": "#e0a21b", "Very poor": "#d9534f", "Severe": "#8e1b2e", "Not scorable": "#9aa5a0" };
const scoreColor = (s) => (s === null || s === undefined ? COLORS["Not scorable"] : s >= 75 ? COLORS.Clean : s >= 55 ? COLORS.Fair : s >= 35 ? COLORS.Poor : s >= 15 ? COLORS["Very poor"] : COLORS.Severe);
const pill = (label) => `<span class="pill" style="background:${COLORS[label] || "#888"}">${esc(label)}</span>`;
const charts = {};
function chart(id, cfg) { if (charts[id]) charts[id].destroy(); charts[id] = new Chart($(id), cfg); }
const api = async (p, o) => { const r = await fetch("/api" + p, o); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText); return r.json(); };
const tick = () => getComputedStyle(document.body).color;
Chart.defaults.font.family = "system-ui, sans-serif";

// ---------- tabs ----------
document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === b.dataset.tab));
  if (b.dataset.tab === "overview" && window.lmap) setTimeout(() => lmap.invalidateSize(), 50);
}));

// ---------- boot ----------
async function boot() {
  const ban = $("#banner");
  for (;;) {
    try {
      const s = await api("/status");
      if (s.status === "ready") { ban.hidden = true; break; }
      ban.hidden = false;
      ban.className = "banner" + (s.status === "error" ? " err" : "");
      ban.textContent = s.status === "error" ? "Error: " + s.error : "Analysing data: " + (s.message || "starting") + " ...";
      if (s.status === "error") return;
    } catch (e) { ban.hidden = false; ban.textContent = "Waiting for server ..."; }
    await new Promise((r) => setTimeout(r, 2000));
  }
  await Promise.all([loadOverview(), loadFairness(), loadModel(), loadQuality(), loadData(), searchStations()]);
}

// ---------- overview ----------
async function loadOverview() {
  const s = await api("/summary");
  $("#snap").textContent = "Data: " + s.meta.snapshot + " IST";
  const poor = (s.labels["Poor"] || 0) + (s.labels["Very poor"] || 0) + (s.labels["Severe"] || 0);
  $("#kpis").innerHTML = [
    [s.meta.n_scored, `stations scored (of ${s.meta.n_stations})`],
    [s.meta.n_cities, "cities, " + s.meta.n_states + " states/UTs"],
    [fmt(s.national_mean), "national mean score (50 = legal limit)"],
    [fmt(100 * poor / s.meta.n_scored) + "%", "stations rated Poor or worse"],
    [fmt(100 * (s.fairness.variance?.within_city_share ?? NaN)) + "%", "of PM2.5 variation is inside cities"],
  ].map(([b, t]) => `<div class="kpi"><b>${esc(b)}</b><span>${esc(t)}</span></div>`).join("");

  const st = await api("/stations");
  if (!window.lmap) {
    window.lmap = L.map("map", { zoomControl: true }).setView([22.8, 79], 5);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 12, attribution: "&copy; OpenStreetMap" }).addTo(lmap);
    window.mlayer = L.layerGroup().addTo(lmap);
  }
  mlayer.clearLayers();
  st.forEach((x) => {
    if (x.lat == null) return;
    const m = L.circleMarker([x.lat, x.lon], { radius: 5, color: "#fff", weight: 0.6, fillColor: scoreColor(x.score), fillOpacity: 0.9 });
    m.bindTooltip(`${esc(x.station)}<br>${x.score == null ? "not scorable" : "score " + fmt(x.score)}`);
    m.on("click", () => openStation(x.id));
    m.addTo(mlayer);
  });
  const pts = st.filter((x) => x.lat != null).map((x) => [x.lat, x.lon]);
  if (pts.length) lmap.fitBounds(pts, { padding: [10, 10] });
  $("#legend").innerHTML = ["Clean", "Fair", "Poor", "Very poor", "Severe", "Not scorable"].map((l) => `<span><i style="background:${COLORS[l]}"></i>${l}${s.labels[l] ? " (" + s.labels[l] + ")" : ""}</span>`).join("");

  const rows = [...s.worst_cities, ...s.best_cities];
  chart("#cityChart", { type: "bar", data: { labels: rows.map((c) => c.city + (c.stations > 1 ? ` (${c.stations})` : "")), datasets: [{ data: rows.map((c) => c.score), backgroundColor: rows.map((c) => scoreColor(c.score)) }] },
    options: { indexAxis: "y", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => "score " + fmt(c.raw, 1) } } }, scales: { x: { min: 0, max: 100, title: { display: true, text: "Air Karma Score" } } } } });
  const sts = s.states;
  chart("#stateChart", { type: "bar", data: { labels: sts.map((x) => x.state), datasets: [{ data: sts.map((x) => x.score), backgroundColor: sts.map((x) => scoreColor(x.score)) }] },
    options: { plugins: { legend: { display: false } }, scales: { y: { min: 0, max: 100, title: { display: true, text: "mean score (station-weighted)" } }, x: { ticks: { maxRotation: 70, minRotation: 50, autoSkip: false } } } } });
}

// ---------- locality ----------
let tmr;
$("#search").addEventListener("input", () => { clearTimeout(tmr); tmr = setTimeout(searchStations, 200); });
$("#stateSel").addEventListener("change", searchStations);
async function searchStations() {
  const q = $("#search").value.trim(), state = $("#stateSel").value;
  const p = new URLSearchParams(); if (q) p.set("q", q); if (state) p.set("state", state);
  const list = await api("/stations?" + p);
  if (!$("#stateSel").dataset.filled) {
    const all = await api("/stations"); const states = [...new Set(all.map((x) => x.state))].sort();
    $("#stateSel").innerHTML = '<option value="">All states</option>' + states.map((s) => `<option>${esc(s)}</option>`).join("");
    $("#stateSel").dataset.filled = 1;
  }
  list.sort((a, b) => (a.score ?? 999) - (b.score ?? 999));
  $("#results").innerHTML = list.slice(0, 80).map((x) => `<div data-id="${esc(x.id)}"><span>${esc(x.station)}<br><small>${esc(x.city)}, ${esc(x.state)}</small></span><span>${x.score == null ? '<small>no score</small>' : pill(x.label) + " " + fmt(x.score)}</span></div>`).join("") || "<div><small>No match</small></div>";
  document.querySelectorAll("#results div[data-id]").forEach((d) => d.addEventListener("click", () => openStation(d.dataset.id)));
}
async function openStation(id) {
  document.querySelector('#tabs [data-tab="locality"]').click();
  const s = await api("/station/" + id);
  const pols = Object.keys(s.ratios);
  const cols = ["#1f6f54", "#d9a441", "#c0392b", "#4a6fa5", "#8e6bbf", "#6b7f77"];
  const total = s.burden || 0;
  const bar = s.score == null ? "" : `<div class="bar" title="Share of pollution burden">${pols.map((p, i) => `<i style="width:${100 * (s.contrib[p] || 0) / total}%;background:${cols[i % cols.length]}" title="${esc(p)}"></i>`).join("")}</div>
    <div class="legend">${pols.map((p, i) => `<span><i style="background:${cols[i % cols.length]}"></i>${esc(p)} ${fmt(100 * (s.contrib[p] || 0) / total)}%</span>`).join("")}</div>`;
  const unit = (p) => (p === "CO" ? "mg/m3?" : "ug/m3");
  const rowsHtml = Object.keys(s.readings).map((p) => `<tr><td>${esc(p)}</td><td class="n">${s.readings[p] == null ? "no reading" : fmt(s.readings[p], 1)}</td><td class="n">${s.ratios[p] == null ? (p === "CO" ? "not scored" : "-") : fmt(s.ratios[p], 2) + "x"}</td></tr>`).join("");
  const ex = s.pm25_explanation;
  let shap = "";
  if (ex) {
    const items = Object.entries(ex.contrib).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
    shap = `<h3>Why the model's PM2.5 estimate is ${fmt(ex.pred)} ug/m3</h3><p class="sub">Starts at the national average (${fmt(ex.base)}) and each input pushes it up or down (SHAP).</p>` +
      `<table>${items.map(([k, v]) => `<tr><td>${esc(k === "nbr_pm25" ? "nearby stations' PM2.5" : k)}</td><td class="n">${v >= 0 ? "+" : ""}${fmt(v, 1)}</td><td style="width:45%"><div class="bar" style="justify-content:${v >= 0 ? "flex-start" : "flex-end"}"><i style="width:${Math.min(100, Math.abs(v) * 2)}%;background:${v >= 0 ? "#c0392b" : "#2e9e6f"}"></i></div></td></tr>`).join("")}</table>`;
  }
  const peers = s.peers.length ? `<h3>Other stations in ${esc(s.city)}</h3><table>${s.peers.sort((a, b) => (a.score ?? 999) - (b.score ?? 999)).map((p) => `<tr><td><a href="#" data-id="${esc(p.id)}" class="peer">${esc(p.station)}</a></td><td class="n">${p.score == null ? "n/a" : fmt(p.score)}</td><td>${pill(p.label)}</td></tr>`).join("")}</table>` : "";
  $("#detail").innerHTML = `<div class="card"><div class="row" style="justify-content:space-between;align-items:flex-start">
      <div><h2>${esc(s.station)}</h2><div class="sub">${esc(s.city)}, ${esc(s.state)}</div>${pill(s.label)}</div>
      <div style="text-align:right"><div class="bigscore" style="color:${scoreColor(s.score)}">${s.score == null ? "-" : fmt(s.score)}</div><div class="sub">Air Karma Score / 100</div></div></div>
      ${bar}
      <div class="reasons">${s.text.map((t) => `<p>${esc(t)}</p>`).join("")}</div></div>
    <div class="grid2"><div class="card"><h3 style="margin-top:0">Readings vs the legal limit</h3><table><tr><th>Pollutant</th><th class="n">Value</th><th class="n">x limit</th></tr>${rowsHtml}</table>
      <p class="sub">CO is shown but not scored: its values in this feed are not in mg/m3.</p></div>
      <div class="card">${peers}${shap}</div></div>`;
  document.querySelectorAll(".peer").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openStation(a.dataset.id); }));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ---------- fairness ----------
let cityRows = [];
async function loadFairness() {
  const f = await api("/fairness");
  const mi = f.moran;
  $("#fairKpis").innerHTML = [
    [fmt(100 * (f.variance?.within_city_share ?? NaN)) + "%", `of PM2.5 variation is inside the same city (${f.variance?.cities ?? 0} cities, 2+ stations)`],
    [fmt(f.median_gap), "median score gap, best vs worst station in a city"],
    [fmt(mi.I, 2), `Moran's I (spatial clustering; p=${mi.p_value < 0.001 ? "<0.001" : fmt(mi.p_value, 3)})`],
    [f.cities_multi, "cities compared"],
  ].map(([b, t]) => `<div class="kpi"><b>${esc(b)}</b><span>${esc(t)}</span></div>`).join("");
  const w = f.widest;
  chart("#gapChart", { type: "bar", data: { labels: w.map((c) => `${c.city} (${c.stations})`), datasets: [{ label: "worst to best station", data: w.map((c) => [c.worst_score, c.best_score]), backgroundColor: "#4a6fa5", borderSkipped: false }] },
    options: { indexAxis: "y", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `worst ${fmt(c.raw[0])} (${w[c.dataIndex].worst_station}) , best ${fmt(c.raw[1])} (${w[c.dataIndex].best_station})` } } }, scales: { x: { min: 0, max: 100, title: { display: true, text: "Air Karma Score" } } } } });
  cityRows = await api("/cities");
  $("#multiOnly").addEventListener("change", drawCityTable);
  drawCityTable();
  const eq = await api("/equity");
  $("#equityCard").innerHTML = "<h2>Who bears the burden?</h2>" + (eq.available
    ? `<p>${eq.matched_cities} of ${eq.of} cities matched your covariates. ` + Object.entries(eq.correlations).map(([k, v]) => `Score vs <b>${esc(k)}</b>: Spearman ${fmt(v.rho, 2)} (p=${fmt(v.p, 3)}, n=${v.n}).`).join(" ") + (eq.people_in_poor_air ? ` About ${eq.people_in_poor_air.toLocaleString()} people live in cities scored Poor or worse.` : "") + "</p>"
    : `<p class="sub">This CSV has no demographic data, so I can't say who is exposed, only where. ${esc(eq.how)}</p>`);
}
function drawCityTable() {
  const only = $("#multiOnly").checked;
  const rows = cityRows.filter((c) => !only || c.stations >= 2).sort((a, b) => b.gap - a.gap || a.score - b.score);
  $("#cityTable").innerHTML = "<tr><th>City</th><th class='n'>Stations</th><th class='n'>Mean</th><th class='n'>Gap</th><th class='n'>Gini</th></tr>" +
    rows.map((c) => `<tr><td>${esc(c.city)}<br><small>${esc(c.state)}</small></td><td class="n">${c.stations}</td><td class="n">${fmt(c.score)}</td><td class="n">${c.stations > 1 ? fmt(c.gap) : "-"}</td><td class="n">${c.burden_gini == null ? "-" : fmt(c.burden_gini, 2)}</td></tr>`).join("");
}

// ---------- model ----------
async function loadModel() {
  const m = await api("/model");
  const cv = m.cv;
  const sets = [...new Set(cv.filter((r) => r.model !== "-").map((r) => r.features))];
  const schemes = ["Random stations", "Leave-city-out", "Leave-state-out"];
  const best = (fs, sc) => Math.max(...cv.filter((r) => r.features === fs && r.scheme === sc).map((r) => r.r2));
  const pal = ["#9aa5a0", "#4a6fa5", "#1f6f54"];
  chart("#cvChart", { type: "bar", data: { labels: sets, datasets: schemes.map((sc, i) => ({ label: sc, data: sets.map((fs) => best(fs, sc)), backgroundColor: pal[i] })) },
    options: { plugins: { legend: { position: "bottom" } }, scales: { y: { title: { display: true, text: "R² on unseen stations (best model per set)" }, min: 0, max: 1 }, x: { ticks: { maxRotation: 30, autoSkip: false } } } } });
  const b = m.best_spatial, rnd = cv.filter((r) => r.features === b.features && r.model === b.model && r.scheme === "Random stations")[0];
  $("#cvLead").textContent = `Trained on ${m.n_train} stations with a PM2.5 sensor; ${m.n_filled} stations without one received an estimate. Best honest setup (${b.features}, ${b.model}): R² ${fmt(b.r2, 2)} and error ${fmt(b.mae, 0)} ug/m3 when a whole state is held out, vs ${fmt(rnd.r2, 2)} under a random split.`;
  $("#cvTable").innerHTML = "<tr><th>Split</th><th>Features</th><th>Model</th><th class='n'>R²</th><th class='n'>MAE</th></tr>" +
    cv.slice().sort((a, b) => schemes.indexOf(a.scheme) - schemes.indexOf(b.scheme) || b.r2 - a.r2).map((r) => `<tr><td>${esc(r.scheme)}</td><td>${esc(r.features)}</td><td>${esc(r.model)}</td><td class="n">${fmt(r.r2, 3)}</td><td class="n">${fmt(r.mae, 1)}</td></tr>`).join("");

  const x = m.xai, feats = x.features, meth = ["SHAP", "Permutation", "Impurity"];
  const norm = (o) => { const t = Object.values(o).reduce((a, c) => a + Math.max(c, 0), 0); return feats.map((f) => 100 * Math.max(o[f], 0) / t); };
  chart("#impChart", { type: "bar", data: { labels: feats.map((f) => (f === "nbr_pm25" ? "nearby PM2.5" : f)), datasets: meth.map((k, i) => ({ label: k, data: norm(x.importance[k]), backgroundColor: pal[i] })) },
    options: { plugins: { legend: { position: "bottom" } }, scales: { y: { title: { display: true, text: "share of total importance (%)" } } } } });
  const top = x.stability.SHAP;
  $("#xaiLead").textContent = `Random forest on ${feats.length} inputs. All three methods name ${top.top1_feature === "nbr_pm25" ? "nearby PM2.5" : top.top1_feature} first.`;
  const ag = x.method_agreement_rho;
  $("#stab").innerHTML = `<p>Refitting on ${x.n_boot} bootstrap resamples of the stations:</p><table>` +
    meth.map((k) => `<tr><td>${k}</td><td>ranks <b>${esc(x.stability[k].top1_feature)}</b> first in ${fmt(100 * x.stability[k].top1_frequency)}% of refits</td></tr>`).join("") + "</table>" +
    `<h3>Do the methods agree? (Spearman rank correlation)</h3><table>` + Object.entries(ag).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${fmt(v[0], 2)} ± ${fmt(v[1], 2)}</td></tr>`).join("") + "</table>" +
    `<div class="note">Correlated inputs can mislead SHAP and permutation importance. The most correlated pairs here: ${x.correlated_pairs.map((p) => `${esc(p.a)}/${esc(p.b)} (${fmt(p.abs_corr, 2)})`).join(", ")}.</div>`;
}

// ---------- quality ----------
async function loadQuality() {
  const q = await api("/quality"), c = q.qc, s = q.sensitivity;
  $("#qcBox").innerHTML = `<p>${c.rows_loaded} rows loaded, ${c.rows_clean} kept (${c.pct_kept}%).</p><table><tr><th>Step</th><th class="n">Removed</th></tr>${c.steps.map((x) => `<tr><td>${esc(x.step)}</td><td class="n">${x.removed}</td></tr>`).join("")}</table>` +
    `<h3>Sensors not reporting</h3><p class="sub">${Object.entries(c.na_by_pollutant).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${esc(k)}: ${v}`).join(" · ")}</p>` +
    `<h3>Stations by number of pollutants reporting</h3><p class="sub">${Object.entries(c.stations_by_n_pollutants).map(([k, v]) => `${k} pollutants: ${v}`).join(" · ")}</p>` +
    c.notes.map((n) => `<div class="note">${esc(n)}</div>`).join("");
  $("#sensBox").innerHTML = `<p>Station ranks barely change when the score weights are varied (Spearman ${fmt(Math.min(...s.grid.map((g) => g.station_rho)), 3)} to ${fmt(Math.max(...s.grid.map((g) => g.station_rho)), 3)} over 9 settings).</p>
    <table><tr><th>Weight on worst pollutant</th><th>Decay k</th><th class="n">Rank agreement</th></tr>${s.grid.map((g) => `<tr><td>${g.w_max}</td><td>${g.k}</td><td class="n">${fmt(g.station_rho, 3)}</td></tr>`).join("")}</table>
    <div class="note">The Karma Score ranks stations almost exactly like the indicative CPCB AQI (rank correlation ${fmt(s.vs_cpcb_aqi_rho, 3)}). What it adds is the exact split of each score by pollutant, the within-city fairness view and PM2.5 estimates where no sensor exists.</div>
    <div class="note">If CO were scored as if it were mg/m3, the ranking would collapse to a rank correlation of ${fmt(s.with_co_rho, 2)} with the current one. That is why CO is excluded until its unit is confirmed.</div>`;
}

// ---------- data ----------
async function loadData() {
  const h = await api("/history");
  $("#snapList").innerHTML = h.snapshots.map((x) => `<li>${esc(x)}</li>`).join("");
  $("#upload").onclick = async () => {
    const f = $("#file").files[0]; if (!f) { $("#upmsg").textContent = "Choose a CSV first."; return; }
    const fd = new FormData(); fd.append("file", f);
    try { const r = await api("/ingest", { method: "POST", body: fd }); $("#upmsg").textContent = `Received ${r.rows_received} rows (${r.rows_new} new). Re-analysing, the page will refresh when done.`; boot(); }
    catch (e) { $("#upmsg").textContent = "Upload failed: " + e.message; }
  };
}
boot().catch((e) => { const b = $("#banner"); b.hidden = false; b.className = "banner err"; b.textContent = "Dashboard error: " + e.message; console.error(e); });