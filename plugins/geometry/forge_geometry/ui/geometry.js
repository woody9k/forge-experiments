"use strict";
// Spacetime Geometry plugin views (platform-split Phase 2). Destined for
// the geometry plugin in forge-experiments; talks to the shell only through
// ForgeUI registration and the shared api/esc helpers.

// ---------------------------------------------------------------- metrics
// The plugin owns its markup as well as its behaviour: the shell's
// index.html has no geometry elements, so installing or removing this plugin
// is what puts the section on the page or takes it away.
const GEOMETRY_MARKUP = `
    <section class="xsection" id="xsec-geometry">
      <h2>Spacetime Geometry</h2>
      <p class="viz-meta">Start from a spacetime shape — derive the matter it
        demands, then ask whether that matter is physically reasonable
        (energy conditions). Known metrics are validated against published
        values before anything novel is trusted.</p>
      <div class="subnav tabstrip" data-group="geometry">
        <button data-pane="library" class="active">Library</button>
        <button data-pane="new-run">New Run</button>
        <button data-pane="results">Runs &amp; Results</button>
      </div>

      <div class="pane" data-group="geometry" id="pane-geometry-library">
        <div id="metric-list"></div>
      </div>

      <div class="pane hidden" data-group="geometry" id="pane-geometry-new-run">
        <form id="exp-form">
          <label>Metric
            <select id="b-metric"></select>
          </label>
          <fieldset id="b-params"><legend>Parameters</legend></fieldset>
          <fieldset><legend>Grid (2-D slice)</legend>
            <div id="b-grid"></div>
            <label>Resolution <input id="b-res" type="number" value="32" min="4" max="256"></label>
          </fieldset>
          <fieldset><legend>Energy conditions</legend>
            <label title="Null energy condition — the weakest requirement: light-ray observers never measure negative energy flux. Violating it requires exotic matter."><input type="checkbox" id="b-nec" checked> NEC</label>
            <label title="Weak energy condition — every observer measures non-negative energy density. Implies NEC."><input type="checkbox" id="b-wec" checked> WEC</label>
            <label title="Strong energy condition — gravity is attractive on average. The least fundamental: ordinary dark energy already violates it."><input type="checkbox" id="b-sec" checked> SEC</label>
            <label title="Dominant energy condition — energy never flows faster than light. Implies WEC."><input type="checkbox" id="b-dec" checked> DEC</label>
          </fieldset>
          <button type="submit">Submit experiment</button>
          <span id="b-status"></span>
        </form>
      </div>

      <div class="pane hidden" data-group="geometry" id="pane-geometry-results">
        <label>Experiment <select id="r-select"></select></label>
        <button id="r-refresh">Refresh</button>
        <a id="r-export" href="#" download>Download bundle</a>
        <div id="r-meta"></div>
        <div id="r-verdict" class="hidden"></div>
        <h3>Validations</h3>
        <table id="r-validations"><thead>
          <tr><th>check</th><th>status</th><th title="reproduced by the independent frame backend (same CAS, independent implementation)">independent</th><th>residual</th><th>tolerance</th><th>evidence</th></tr>
        </thead><tbody></tbody></table>
        <h3>Energy conditions</h3>
        <table id="r-ec"><thead>
          <tr><th>condition</th><th>status</th><th>min value</th><th>violating samples</th><th>tolerance</th></tr>
        </thead><tbody></tbody></table>
        <h3 title="Energy density measured by observers at rest in the spatial grid (the Eulerian frame) — negative values are the signature of exotic matter.">Eulerian energy density</h3>
        <div id="r-viz-meta" class="viz-meta"></div>
        <canvas id="r-heatmap" width="640" height="500"></canvas>
        <div id="r-hover" class="viz-meta">&nbsp;</div>
        <div id="r-warnings"></div>
      </div>
    </section>
`;

document.getElementById("view-experiments")
  .insertAdjacentHTML("beforeend", GEOMETRY_MARKUP);

async function loadMetrics() {
  const metrics = await api("/metrics");
  document.getElementById("metric-list").innerHTML = metrics.map(m => m.error
    ? `<div class="metric-card"><h3>${m.name}</h3><p class="status-failed">${m.error}</p></div>`
    : `<div class="metric-card">
        <h3>${m.name} <span class="version">v${m.version}</span></h3>
        <p>${m.description || ""}</p>
        <p><b>Coordinates</b> (${m.coordinates.join(", ")}) · signature ${m.signature}
           · ${m.units_mode} units · hash <code>${m.hash.slice(0, 12)}</code></p>
        <p><b>Parameters</b> ${Object.entries(m.parameters).map(([k, p]) =>
            `${k} (${p.symbol}=${p.default})`).join(", ") || "none"}</p>
        <p class="cite">${m.source_citation}</p>
        <p><button onclick='runMetric(${JSON.stringify(m.name)})'>Run this metric</button></p>
       </div>`).join("");
}

// Cross-tab handoffs within the geometry section: "Run this metric"
// preselects the builder, and a fresh submission follows itself into
// Runs & Results. Each is consumed exactly once by its target loader.
let builderPreselect = null;
let resultsPreselect = null;

function runMetric(name) {
  builderPreselect = name;
  const target = "experiments/spacetime-geometry/new-run";
  if (location.hash.slice(1) === target) applyRoute(); else location.hash = target;
}
window.runMetric = runMetric;

function followExperiment(id) {
  resultsPreselect = id;
  const target = "experiments/spacetime-geometry/results";
  if (location.hash.slice(1) === target) applyRoute(); else location.hash = target;
}

// ---------------------------------------------------------------- builder
let metricCache = [];
async function loadBuilder() {
  metricCache = await api("/metrics");
  const sel = document.getElementById("b-metric");
  sel.innerHTML = metricCache.filter(m => !m.error)
    .map(m => `<option value="${m.name}">${m.name}</option>`).join("");
  if (builderPreselect) {
    const wanted = builderPreselect;
    builderPreselect = null;
    if ([...sel.options].some(o => o.value === wanted)) sel.value = wanted;
  }
  sel.onchange = renderBuilderFields;
  renderBuilderFields();
}

function renderBuilderFields() {
  const m = metricCache.find(x => x.name === document.getElementById("b-metric").value);
  if (!m) return;
  document.getElementById("b-params").innerHTML = "<legend>Parameters</legend>" +
    (Object.entries(m.parameters).map(([k, p]) =>
      `<label>${k} (${p.symbol}) <input type="number" step="any" data-param="${k}"
        value="${p.default}"></label>`).join("") || "<em>none</em>");
  // Per-metric sampling window from the definition YAML (e.g. the
  // Schwarzschild exterior). Fallback for metrics without one: vary the
  // 2nd and 3rd coordinates over a symmetric window.
  const dg = m.default_grid;
  const fallbackFix = { t: "0", z: "0", phi: "0", theta: "1.5708" };
  document.getElementById("b-grid").innerHTML = m.coordinates.map((c, i) => {
    const varying = dg ? c in dg.vary : (i === 1 || i === 2);
    const value = dg
      ? (varying ? `${dg.vary[c][0]}:${dg.vary[c][1]}` : `${dg.fix[c] ?? 0}`)
      : (varying ? "-2:2" : (fallbackFix[c] ?? "0"));
    return `<label>${c}
      <select data-coord="${c}" class="grid-mode">
        <option value="vary" ${varying ? "selected" : ""}>vary</option>
        <option value="fix" ${varying ? "" : "selected"}>fix</option>
      </select>
      <input type="text" data-range="${c}" value="${value}" size="8">
    </label>`;
  }).join("");
}

document.getElementById("exp-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const name = document.getElementById("b-metric").value;
  const params = {};
  document.querySelectorAll("#b-params [data-param]").forEach(i =>
    params[i.dataset.param] = parseFloat(i.value));
  const bounds = {}, slices = {};
  document.querySelectorAll("#b-grid [data-coord]").forEach(sel => {
    const c = sel.dataset.coord;
    const val = document.querySelector(`#b-grid [data-range="${c}"]`).value;
    if (sel.value === "vary") {
      const [lo, hi] = val.split(":").map(Number);
      bounds[c] = [lo, hi];
    } else {
      slices[c] = parseFloat(val);
    }
  });
  const res = parseInt(document.getElementById("b-res").value, 10);
  const conditions = ["nec", "wec", "sec", "dec"]
    .filter(c => document.getElementById(`b-${c}`).checked)
    .map(c => c.toUpperCase());
  const body = {
    metric_name: name, parameter_values: params,
    grid: {
      bounds,
      resolution: Object.fromEntries(Object.keys(bounds).map(k => [k, res])),
      slice_values: slices,
    },
    energy_conditions: conditions.length ? { conditions } : null,
  };
  const st = document.getElementById("b-status");
  st.textContent = "submitting…";
  const r = await fetch("/api/v1/experiments", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (!r.ok) { st.textContent = `error: ${JSON.stringify(j.detail)}`; return; }
  st.textContent = `submitted ${j.id.slice(0, 12)} (${j.status}) — opening results…`;
  followExperiment(j.id);
});

// ---------------------------------------------------------------- results
async function loadResults() {
  const exps = await api("/experiments?limit=50");
  const sel = document.getElementById("r-select");
  sel.innerHTML = exps.map(e =>
    `<option value="${e.id}">${e.metric_name} · ${e.id.slice(0, 12)} · ${e.status}</option>`).join("");
  if (resultsPreselect) {
    // A just-submitted experiment may not be in the listing yet (async
    // stack): pin a placeholder option so it is selectable immediately —
    // the poll below fills in the real label as soon as the record lands.
    if (![...sel.options].some(o => o.value === resultsPreselect))
      sel.insertAdjacentHTML("afterbegin", `<option value="${resultsPreselect}">
        ${resultsPreselect.slice(0, 12)} · just submitted</option>`);
    sel.value = resultsPreselect;
    resultsPreselect = null;
  }
  sel.onchange = renderResult;
  document.getElementById("r-refresh").onclick = renderResult;
  if (sel.value) renderResult();
}

// Live-follow a run: while the selected experiment is still pending, queued
// or running, re-render every 2 s. One timer only, re-armed per render; it
// dies the moment the results pane is hidden or the selection changes, so
// navigating away never leaves a background poll running.
let resultPollTimer = null;
function scheduleResultPoll(id, status) {
  clearTimeout(resultPollTimer);
  if (!["pending", "queued", "running"].includes(status)) return;
  resultPollTimer = setTimeout(() => {
    if (document.getElementById("pane-geometry-results").classList.contains("hidden")) return;
    if (document.getElementById("r-select").value !== id) return;
    renderResult();
  }, 2000);
}

async function renderResult() {
  const id = document.getElementById("r-select").value;
  if (!id) return;
  document.getElementById("r-export").href = `/api/v1/experiments/${id}/export`;
  const [exp, validations] = await Promise.all([
    api(`/experiments/${id}`), api(`/experiments/${id}/validations`),
  ]);
  if (!exp || typeof exp !== "object" || !exp.id || !exp.status) {
    document.getElementById("r-meta").textContent =
      `experiment ${id.slice(0, 12)} not available yet — retrying…`;
    // Clear the prior experiment's interpretability chrome so a stale
    // verdict/heatmap does not linger while we poll for this id.
    document.getElementById("r-verdict").classList.add("hidden");
    document.getElementById("r-verdict").textContent = "";
    drawHeatmap(null);
    scheduleResultPoll(id, "pending");  // keep polling
    return;
  }
  // Keep the picker's label in step with the status the poll just fetched.
  const opt = [...document.getElementById("r-select").options].find(o => o.value === id);
  if (opt) opt.textContent = `${exp.metric_name} · ${id.slice(0, 12)} · ${exp.status}`;
  scheduleResultPoll(id, exp.status);
  document.getElementById("r-meta").innerHTML =
    `<p><b>${exp.metric_name}</b> v${exp.metric_version} ·
     status <span class="status-${exp.status}">${exp.status}</span> ·
     params <code>${JSON.stringify(exp.parameter_values)}</code> ·
     seed ${exp.random_seed} · metric hash <code>${exp.metric_hash.slice(0, 12)}</code>
     ${exp.error ? `<br><span class="status-failed">error: ${exp.error}</span>` : ""}</p>`;
  document.querySelector("#r-validations tbody").innerHTML = validations.map(v =>
    `<tr><td>${v.validation_type}</td>` + statusCell(v.status) +
    `<td>${v.independently_verified ? "yes" : "—"}</td>` +
    `<td>${v.residual ?? "—"}</td><td>${v.tolerance}</td><td>${v.evidence}</td></tr>`
  ).join("") || `<tr><td colspan="6">no validations recorded</td></tr>`;

  let viz = { fields: {}, warnings: [] };
  try { viz = await api(`/experiments/${id}/visualizations`, { quiet: true }); }
  catch (e) { /* no bundle */ }
  document.getElementById("r-warnings").innerHTML =
    (viz.warnings || []).map(w => `<p>⚠ ${esc(w)}</p>`).join("");

  const ec = viz.energy_conditions;
  document.querySelector("#r-ec tbody").innerHTML = ec
    ? Object.values(ec).map(c =>
        `<tr><td title="${esc(EC_TIP[c.condition] || "")}">${c.condition}</td>` + statusCell(c.status) +
        `<td>${c.min_value !== null ? Number(c.min_value).toExponential(3) : "—"}</td>` +
        `<td>${c.violation_fraction !== null
              ? (100 * c.violation_fraction).toFixed(1) + "%" : "—"}</td>` +
        `<td>${c.tolerance}</td></tr>`).join("")
    : `<tr><td colspan="5">no energy-condition analysis for this experiment</td></tr>`;

  renderVerdict(exp, validations, ec);
  drawHeatmap(viz.fields && viz.fields.eulerian_energy_density);
}

const EC_TIP = {
  NEC: "Null energy condition — the weakest requirement: light-ray observers never measure negative energy flux. Violating it requires exotic matter.",
  WEC: "Weak energy condition — every observer measures non-negative energy density. Implies NEC.",
  SEC: "Strong energy condition — gravity is attractive on average. The least fundamental: ordinary dark energy already violates it.",
  DEC: "Dominant energy condition — energy never flows faster than light. Implies WEC.",
};

// Plain-language verdict rendered above the evidence tables. It only
// compresses what those tables already say, and keeps the platform's honesty
// rules: sampling is never called proof, failures are named, nothing masked.
function renderVerdict(exp, validations, ec) {
  const el = document.getElementById("r-verdict");
  el.classList.remove("hidden");
  if (exp.status === "failed") {
    el.className = "banner bad";
    el.innerHTML = `<b>This run failed.</b> ${esc(exp.error || "No error was recorded.")}
      Nothing below is a result.`;
    return;
  }
  if (exp.status !== "completed") {
    el.className = "banner";
    el.innerHTML = `This experiment is <b>${esc(exp.status)}</b> — the view
      refreshes every 2 s until it finishes.`;
    return;
  }
  const lines = [];
  let cls = "ok";
  const bad = validations.filter(v =>
    v.status === "failed" || v.status === "computation_failed");
  const shaky = validations.filter(v => v.status === "inconclusive");
  if (!validations.length) {
    lines.push("No validation checks were recorded for this run.");
    cls = "warn";
  } else if (bad.length) {
    lines.push(`<b>${bad.length} of ${validations.length} validation checks
      failed</b> (${esc(bad.map(v => v.validation_type).join(", "))}) — treat
      this result as unreliable.`);
    cls = "bad";
  } else {
    lines.push(`All ${validations.length} validation checks passed`
      + (shaky.length ? ` (${shaky.length} inconclusive)` : "") + ".");
  }
  const conds = ec ? Object.values(ec) : [];
  const violated = conds.filter(c => c.status === "confirmed_violation");
  const clean = conds.filter(c => c.status === "no_violation_detected");
  if (violated.length) {
    const worst = Math.max(...violated.map(c => c.violation_fraction || 0));
    lines.push(`⚠ <b>${esc(violated.map(c => c.condition).join(", "))}
      violated</b> on up to ${(100 * worst).toFixed(1)}% of sampled grid
      points — producing this geometry would require <b>exotic matter</b>
      (locally negative energy density; blue regions in the map below).`);
    if (cls === "ok") cls = "warn";
  } else if (clean.length) {
    lines.push(`No energy-condition violations detected
      (${esc(clean.map(c => c.condition).join(", "))}) on this grid —
      sampling, not a proof.`);
  } else if (conds.length) {
    lines.push(`Energy-condition sampling was inconclusive on this grid
      (not enough clean samples to say anything either way) — details in
      the table below.`);
    if (cls === "ok") cls = "warn";
  }
  el.className = `banner ${cls}`;
  el.innerHTML = lines.join("<br>");
}

// Margins host the axes (left/bottom) and the colorbar (right).
const HEAT_M = { left: 62, top: 12, right: 96, bottom: 42 };
let heatState = null;   // geometry + data of the last drawn field, for hover

/** Diverging map shared by the field and the colorbar: t ∈ [−1, 1],
 *  blue < 0 ≤ red. */
const heatColor = (t) => [
  t > 0 ? 200 : 255 + t * 175,
  235 - Math.abs(t) * 160,
  t < 0 ? 200 : 255 - t * 175,
];

function drawHeatmap(field) {
  const canvas = document.getElementById("r-heatmap");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const meta = document.getElementById("r-viz-meta");
  document.getElementById("r-hover").innerHTML = "&nbsp;";
  heatState = null;
  if (!field) {
    meta.textContent = "no 2-D energy-density field available for this experiment";
    return;
  }
  // values[i][j]: i runs over the first varying coordinate, j over the
  // second. Drawn in the conventional reading — first axis across (min→max,
  // left→right), second axis up (min at the bottom).
  const vals = field.values, names = Object.keys(field.axes || {});
  if (!vals || !vals.length || !vals[0] || !vals[0].length
      || names.length < 2 || !field.axes[names[0]] || !field.axes[names[1]]) {
    meta.textContent = "energy-density field is present but incomplete (no 2-D grid)";
    return;
  }
  const n0 = vals.length, n1 = vals[0].length;
  const ax0 = field.axes[names[0]], ax1 = field.axes[names[1]];
  let lo = Infinity, hi = -Infinity;
  for (const row of vals) for (const v of row) if (v !== null) {
    lo = Math.min(lo, v); hi = Math.max(hi, v);
  }
  const amax = Math.max(Math.abs(lo), Math.abs(hi), 1e-300);
  meta.textContent =
    `range [${lo.toExponential(3)}, ${hi.toExponential(3)}] · ${field.units} · ` +
    `resolution ${n0}×${n1} · solver ${field.solver_backend} · ` +
    `params ${JSON.stringify(field.parameter_values)} · ` +
    `gray = non-finite (flagged, never masked) · hover for values`;

  const W = canvas.width, H = canvas.height;
  const px = HEAT_M.left, py = HEAT_M.top,
        pw = W - HEAT_M.left - HEAT_M.right, ph = H - HEAT_M.top - HEAT_M.bottom;
  const img = ctx.createImageData(n0, n1);
  for (let j = 0; j < n1; j++) for (let i = 0; i < n0; i++) {
    const v = vals[i][j], k = 4 * ((n1 - 1 - j) * n0 + i);
    if (v === null) { img.data[k] = img.data[k+1] = img.data[k+2] = 128; }
    else {
      const [r, g, b] = heatColor(Math.max(-1, Math.min(1, v / amax)));
      img.data[k] = r; img.data[k+1] = g; img.data[k+2] = b;
    }
    img.data[k+3] = 255;
  }
  const off = new OffscreenCanvas(n0, n1);
  off.getContext("2d").putImageData(img, 0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(off, px, py, pw, ph);

  // Axes: frame plus min/mid/max ticks taken from the actual coordinate
  // arrays — labels report what was computed, not a rescaled abstraction.
  const css = getComputedStyle(document.documentElement);
  const fgCol = css.getPropertyValue("--fg").trim() || "#222";
  const mutedCol = css.getPropertyValue("--muted").trim() || "#777";
  ctx.strokeStyle = mutedCol; ctx.fillStyle = fgCol;
  ctx.lineWidth = 1; ctx.font = "11px system-ui, sans-serif";
  ctx.strokeRect(px + 0.5, py + 0.5, pw, ph);
  const t3 = (a) => [a[0], a[Math.floor(a.length / 2)], a[a.length - 1]];
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  t3(ax0).forEach((v, k) => {
    const x = px + (k / 2) * pw;
    ctx.beginPath(); ctx.moveTo(x, py + ph); ctx.lineTo(x, py + ph + 4); ctx.stroke();
    ctx.fillText(sgNum(v), x, py + ph + 7);
  });
  ctx.fillText(names[0], px + pw / 2, py + ph + 24);
  ctx.textAlign = "right"; ctx.textBaseline = "middle";
  t3(ax1).forEach((v, k) => {
    const y = py + ph - (k / 2) * ph;
    ctx.beginPath(); ctx.moveTo(px, y); ctx.lineTo(px - 4, y); ctx.stroke();
    ctx.fillText(sgNum(v), px - 7, y);
  });
  ctx.save();
  ctx.translate(16, py + ph / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(names[1], 0, 0);
  ctx.restore();

  // Colorbar: the exact display mapping, labelled at +max / 0 / −max.
  const cbx = W - HEAT_M.right + 24, cbw = 14;
  for (let yy = 0; yy < ph; yy++) {
    const [r, g, b] = heatColor(1 - 2 * (yy / (ph - 1)));
    ctx.fillStyle = `rgb(${r},${g},${b})`;
    ctx.fillRect(cbx, py + yy, cbw, 1);
  }
  ctx.strokeStyle = mutedCol;
  ctx.strokeRect(cbx + 0.5, py + 0.5, cbw, ph);
  ctx.fillStyle = fgCol; ctx.textAlign = "left"; ctx.textBaseline = "middle";
  ctx.fillText(`+${amax.toExponential(1)}`, cbx + cbw + 5, py + 6);
  ctx.fillText("0", cbx + cbw + 5, py + ph / 2);
  ctx.fillText(`−${amax.toExponential(1)}`, cbx + cbw + 5, py + ph - 6);

  heatState = { vals, ax0, ax1, names, n0, n1, px, py, pw, ph };
}

// One hover readout, bound once: canvas pixel → grid cell → coordinates and
// the actual stored value (non-finite shown as such, matching the gray cells).
{
  const canvas = document.getElementById("r-heatmap");
  const hover = document.getElementById("r-hover");
  canvas.addEventListener("mousemove", (ev) => {
    if (!heatState) return;
    const rect = canvas.getBoundingClientRect();
    const x = (ev.clientX - rect.left) * (canvas.width / rect.width);
    const y = (ev.clientY - rect.top) * (canvas.height / rect.height);
    const { vals, ax0, ax1, names, n0, n1, px, py, pw, ph } = heatState;
    const i = Math.floor(((x - px) / pw) * n0);
    const j = n1 - 1 - Math.floor(((y - py) / ph) * n1);
    if (i < 0 || i >= n0 || j < 0 || j >= n1) { hover.innerHTML = "&nbsp;"; return; }
    const v = vals[i][j];
    hover.textContent = `${names[0]} = ${sgNum(ax0[i])} · ${names[1]} = ${sgNum(ax1[j])}`
      + ` · ρ = ${v === null ? "non-finite" : Number(v).toExponential(4)}`;
  });
  canvas.addEventListener("mouseleave", () => { hover.innerHTML = "&nbsp;"; });
}



ForgeUI.registerSection({
  plugin: "geometry",
  section: "spacetime-geometry",
  group: "geometry",
  defaultPane: "library",
  panes: { library: loadMetrics, "new-run": loadBuilder, results: loadResults },
  legacy: {
    metrics: "experiments/spacetime-geometry/library",
    builder: "experiments/spacetime-geometry/new-run",
    results: "experiments/spacetime-geometry/results",
  },
});
