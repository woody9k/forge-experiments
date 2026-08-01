"use strict";
// Matter Configurations plugin views (platform-split Phase 2). Destined for
// the matter plugin in forge-experiments.

// ----------------------------------------------------------------- matter
// The plugin owns its markup as well as its behaviour: the shell's
// index.html has no matter elements, so installing or removing this plugin
// is what puts the section on the page or takes it away.
const MATTER_MARKUP = `
    <section class="xsection" id="xsec-matter">
      <h2>Matter Configurations</h2>
      <p class="viz-meta">Start from real matter — predict its effect on
        spacetime. Physically parameterized configurations → stress-energy →
        predicted effects. Gates 0–2 (schema, engineering, fast physics) are
        live; gates 3–5 and search campaigns are explicitly gated — see
        docs/matter-forge-design.md.</p>
      <div class="subnav tabstrip" data-group="matter">
        <button data-pane="configurations" class="active">Configurations</button>
        <button data-pane="casimir">Casimir Tool</button>
      </div>

      <div class="pane" data-group="matter" id="pane-matter-configurations">
        <button id="mc-demo">Create demo plate stack</button>
        <table id="mc-list"><thead>
          <tr><th>id</th><th>name</th><th>gen</th><th>state</th><th>actions</th></tr>
        </thead><tbody></tbody></table>
        <div id="mc-detail"></div>
      </div>

      <div class="pane hidden" data-group="matter" id="pane-matter-casimir">
        <h3>Casimir analyzer (ideal parallel plates, T = 0)</h3>
        <form id="casimir-form">
          <label>Separation (m) <input id="cz-sep" type="text" value="1e-7"></label>
          <label>Plate area (m²) <input id="cz-area" type="text" value="1e-4"></label>
          <label>Plates <input id="cz-count" type="number" value="2" min="2"></label>
          <label>Temperature (K) <input id="cz-temp" type="text" value="0"></label>
          <button type="submit">Analyze</button>
        </form>
        <div id="cz-result"></div>
      </div>
    </section>
`;

document.getElementById("view-experiments")
  .insertAdjacentHTML("beforeend", MATTER_MARKUP);

const DEMO_GENOME = {
  name: "casimir_stack", version: "0.1.0",
  coordinate_system: { type: "cartesian", units: "SI" },
  quantum_boundaries: [{
    id: "stack", type: "parallel_plate_array",
    plate_count: 2, plate_area_m2: 1e-4, separation_m: 1e-7,
    plate_thickness_m: 1e-4, material_model: "ideal_conductor",
    plate_material_id: "gold", temperature_k: 0.0,
  }],
  observation_regions: [{ id: "center", type: "point", position: [0, 0, 0] }],
};

document.getElementById("casimir-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const r = await fetch("/api/v1/matter/casimir/analyze", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({
      separation_m: parseFloat(document.getElementById("cz-sep").value),
      plate_area_m2: parseFloat(document.getElementById("cz-area").value),
      plate_count: parseInt(document.getElementById("cz-count").value, 10),
      temperature_k: parseFloat(document.getElementById("cz-temp").value),
    }),
  });
  const j = await r.json();
  const el = document.getElementById("cz-result");
  if (!r.ok) { el.innerHTML = `<p class="status-failed">${JSON.stringify(j.detail)}</p>`; return; }
  const a = j.energy_account;
  el.innerHTML = `
    <div class="card">
      <p><b>${j.model}</b> v${j.model_version} · validity <b>${j.validity}</b> ·
         confidence <b>${j.confidence}</b></p>
      <p>Energy density in gap: <code>${j.energy_density_j_m3.toExponential(4)} J/m³</code> ·
         Force/area: <code>${j.force_per_area_pa.toExponential(4)} Pa</code> (attractive) ·
         E/area per gap: <code>${j.energy_per_area_j_m2.toExponential(4)} J/m²</code></p>
      <p><b>Energy account</b> — integrated vacuum:
         <code>${a.integrated_vacuum_energy_j.toExponential(3)} J</code>,
         apparatus rest: <code>${a.apparatus_rest_energy_j.toExponential(3)} J</code>,
         total system: <code>${a.total_system_energy_j.toExponential(3)} J</code></p>
      <p class="viz-meta">⚠ ${a.warning}</p>
      ${(j.warnings || []).map(w => `<p class="viz-meta">⚠ ${w}</p>`).join("")}
    </div>`;
});

document.getElementById("mc-demo").addEventListener("click", async () => {
  await fetch("/api/v1/matter/configurations", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify(DEMO_GENOME),
  });
  loadMatter();
});

async function mcSimulate(id) {
  await fetch(`/api/v1/matter/configurations/${id}/simulate`, { method: "POST" });
  mcDetail(id);
  loadMatter();
}

async function mcMutate(id) {
  await fetch(`/api/v1/matter/configurations/${id}/mutate`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ operator: "alter_separation",
                           params: { target: "stack", factor: 0.5 },
                           seed: 42, reason: "UI: halve gap" }),
  });
  loadMatter();
}

async function mcDetail(id) {
  const el = document.getElementById("mc-detail");
  let se;
  try {
    const r = await fetch(`/api/v1/matter/configurations/${id}/stress-energy`);
    if (!r.ok) throw new Error();
    se = await r.json();
  } catch { el.innerHTML = "<p class='viz-meta'>not simulated yet</p>"; return; }
  const lin = await api(`/matter/configurations/${id}/lineage`);
  const a = se.energy_account;
  let cmp = "";
  if (lin.ancestors.length) {
    try {
      const c = await api(`/matter/configurations/${id}/compare-parent`, { quiet: true });
      const d = c.local_min_energy_density_j_m3;
      if (d) cmp = `<p><b>vs parent:</b> local min energy density
        ${d.parent.toExponential(3)} → ${d.child.toExponential(3)} J/m³</p>`;
    } catch { /* parent not simulated */ }
  }
  el.innerHTML = `<div class="card">
    <p><b>${id.slice(0, 12)}</b> · generation ${lin.generation} ·
       ${lin.mutation_history.length} mutation(s)</p>
    ${lin.mutation_history.map(m =>
      `<p class="viz-meta">${m.operator}@${m.operator_version} seed ${m.seed}:
       ${JSON.stringify(m.parameters_before)} → ${JSON.stringify(m.parameters_after)}</p>`).join("")}
    <p><b>Vacuum contributions:</b> ${se.contributions
        .filter(c => c.contribution_type === "vacuum")
        .map(c => `<code>${c.tensor_diag_si_j_m3.map(x => x.toExponential(2)).join(", ")}</code> J/m³ (diag)`)
        .join("; ") || "none"}</p>
    <p><b>Energy account:</b> vacuum ${a.integrated_vacuum_energy_j.toExponential(3)} J ·
       rest ${a.apparatus_rest_energy_j.toExponential(3)} J ·
       total ${a.total_system_energy_j.toExponential(3)} J</p>
    ${cmp}
    <p class="viz-meta">⚠ ${a.warning}</p>
  </div>`;
}

async function loadMatter() {
  const configs = await api("/matter/configurations?limit=30");
  document.querySelector("#mc-list tbody").innerHTML = configs.map(c =>
    `<tr><td><code>${c.id.slice(0, 12)}</code></td><td>${c.name}</td>
     <td>${c.generation}</td><td>${c.validation_state}</td>
     <td><button onclick="mcSimulate('${c.id}')">simulate</button>
         <button onclick="mcMutate('${c.id}')">mutate ½a</button>
         <button onclick="mcDetail('${c.id}')">detail</button></td></tr>`).join("");
}
window.mcSimulate = mcSimulate; window.mcMutate = mcMutate; window.mcDetail = mcDetail;



ForgeUI.registerSection({
  plugin: "matter",
  section: "matter",
  label: "Matter Configurations",
  group: "matter",
  defaultPane: "configurations",
  panes: { configurations: loadMatter },  // casimir pane is a stateless calculator
  legacy: { matter: "experiments/matter/configurations" },
});
