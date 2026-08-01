"use strict";
// Pendulum Lab UI section — the reference example of a plugin view.
// The plugin owns both its markup and its behaviour: it injects its section
// into the Experiments view, then registers with the shell. Installing or
// removing the plugin is what puts this section on the page.

document.getElementById("view-experiments").insertAdjacentHTML("beforeend", `
  <section class="xsection" id="xsec-pendulum">
    <h2>Pendulum Lab</h2>
    <p class="viz-meta">The reference example plugin. Release a pendulum,
      integrate its motion, and compare the measured period against the
      closed form T = 2&pi;&radic;(L/g) — which holds only for small
      amplitudes, so the platform records the check as <em>inapplicable</em>
      above 5&deg; rather than quietly passing it.</p>
    <div class="subnav tabstrip" data-group="pendulum">
      <button data-pane="new-run" class="active">New Run</button>
      <button data-pane="runs">Runs</button>
    </div>

    <div class="pane" data-group="pendulum" id="pane-pendulum-new-run">
      <form id="pd-form">
        <!-- step="any": with a numeric step, min="0.05" step="0.1" makes
             1.0 an invalid value and the browser silently refuses to submit
             (caught in a real browser, not by any test of the handler). -->
        <label>Length (m) <input id="pd-length" type="number" value="1.0"
               step="any" min="0.05"></label>
        <label>Initial angle (&deg;) <input id="pd-angle" type="number"
               value="5" step="1" min="-170" max="170"></label>
        <label>Damping (1/s) <input id="pd-damping" type="number" value="0"
               step="any" min="0"></label>
        <label>Duration (s) <input id="pd-duration" type="number" value="20"
               step="1" min="1"></label>
        <button type="submit">Run experiment</button>
        <span id="pd-status" class="viz-meta"></span>
      </form>
      <div id="pd-result"></div>
    </div>

    <div class="pane hidden" data-group="pendulum" id="pane-pendulum-runs">
      <button id="pd-refresh">Refresh</button>
      <table id="pd-list"><thead>
        <tr><th>run</th><th>length (m)</th><th>angle (&deg;)</th>
            <th>status</th><th>created</th></tr>
      </thead><tbody></tbody></table>
    </div>
  </section>
`);

async function loadPendulumRuns() {
  const runs = await api("/pendulum/runs?limit=50");
  document.querySelector("#pd-list tbody").innerHTML = runs.map(r =>
    `<tr class="rowlink" onclick='showPendulumRun(${JSON.stringify(r.id)})'>
      <td><code>${r.id.slice(0, 12)}</code></td>
      <td>${esc(r.length_m)}</td><td>${esc(r.initial_angle_deg)}</td>` +
    statusCell(r.status === "completed" ? "passed" : r.status) +
    `<td class="viz-meta">${esc(r.created_at)}</td></tr>`).join("")
    || `<tr><td colspan="5">no runs yet</td></tr>`;
}

async function showPendulumRun(id) {
  const run = await api(`/pendulum/runs/${id}`);
  const r = run.result || {};
  const v = run.validation || {};
  const num = (x, d = 6) => (typeof x === "number" ? x.toFixed(d) : "—");
  document.getElementById("pd-result").innerHTML = `
    <div class="card">
      <h3>Run <code>${esc(id.slice(0, 12))}</code></h3>
      <p><b>Measured period</b> ${num(r.measured_period_s)} s ·
         <b>closed form</b> ${num(r.small_angle_period_s)} s ·
         <b>deviation</b> ${r.relative_deviation === null ? "—"
           : (r.relative_deviation * 100).toFixed(3) + " %"}</p>
      <p class="viz-meta">quality ${esc(r.quality)} ·
         ${esc(r.swings_measured)} zero crossing(s) ·
         energy drift ${typeof r.energy_drift === "number"
           ? r.energy_drift.toExponential(2) : "—"}</p>
      <p><b>Known-answer check</b>
        <span class="status-${v.status === "passed" ? "passed"
          : v.status === "failed" ? "failed" : "inconclusive"}"
          >${esc(v.status || "—")}</span>
        <span class="viz-meta">${esc(v.detail || "")}</span></p>
      ${(r.warnings || []).length
        ? `<ul class="viz-meta">${r.warnings.map(w =>
            `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
    </div>`;
}

document.getElementById("pd-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const status = document.getElementById("pd-status");
  status.textContent = "running…";
  const body = {
    length_m: parseFloat(document.getElementById("pd-length").value),
    initial_angle_deg: parseFloat(document.getElementById("pd-angle").value),
    damping: parseFloat(document.getElementById("pd-damping").value),
    duration_s: parseFloat(document.getElementById("pd-duration").value),
  };
  const res = await fetch("/api/v1/pendulum/runs", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const out = await res.json();
  if (!res.ok) { status.textContent = `failed: ${JSON.stringify(out)}`; return; }
  status.textContent = `run ${out.id.slice(0, 12)} ${out.status}`;
  await showPendulumRun(out.id);
  await loadPendulumRuns();
});

document.getElementById("pd-refresh").addEventListener("click", loadPendulumRuns);

ForgeUI.registerSection({
  plugin: "pendulum",
  section: "pendulum-lab",
  label: "Pendulum Lab",
  group: "pendulum",
  defaultPane: "new-run",
  panes: { "new-run": () => {}, runs: loadPendulumRuns },
  legacy: {},
});
