"use strict";
document.getElementById("view-experiments").insertAdjacentHTML("beforeend", `
<section class="xsection" id="xsec-lattice"><h2>Forge Lattice</h2>
<p class="viz-meta">A bounded 1D quasistatic model for alternating Mg-Zn/Bi layers under normal DC and RF electric fields. The gravity output is an energy-equivalent scale, not evidence of anomalous gravity.</p>
<form id="lat-form">
<label>Layers <input id="lat-count" type="number" value="10" min="2" max="1000"></label>
<label>Thickness/layer (m) <input id="lat-thickness" type="number" value="0.000001" step="any" min="0"></label>
<label>Frequency (Hz) <input id="lat-frequency" type="number" value="1000000" step="any" min="0"></label>
<label>DC field (V/m) <input id="lat-dc" type="number" value="10000" step="any" min="0"></label>
<label>RF amplitude (V/m) <input id="lat-rf" type="number" value="10000" step="any" min="0"></label>
<button type="submit">Simulate stack</button><span id="lat-status" class="viz-meta"></span></form>
<div id="lat-result"></div></section>`);

document.getElementById("lat-form").addEventListener("submit", async ev => {
  ev.preventDefault(); const status = document.getElementById("lat-status"); status.textContent = "running…";
  const value = id => parseFloat(document.getElementById(id).value);
  const body = {layer_count: value("lat-count"), layer_thickness_m: value("lat-thickness"),
    frequency_hz: value("lat-frequency"), dc_field_v_m: value("lat-dc"),
    rf_field_amplitude_v_m: value("lat-rf")};
  const res = await fetch("/api/v1/lattice/simulate", {method:"POST", headers:{"content-type":"application/json"}, body:JSON.stringify(body)});
  const out = await res.json(); if (!res.ok) { status.textContent = `failed: ${JSON.stringify(out)}`; return; }
  status.textContent = "complete"; const t = out.totals; const e = out.effective_properties;
  document.getElementById("lat-result").innerHTML = `<div class="card"><h3>Layered field response</h3>
  <p><b>EM energy</b> ${t.em_energy_j.toExponential(4)} J · <b>largest interface force</b> ${t.max_abs_interface_force_n.toExponential(4)} N</p>
  <p><b>Effective conductivity</b> ${e.dc_conductivity_normal_s_m.toExponential(4)} S/m · <b>bulk density</b> ${e.bulk_density_kg_m3.toFixed(1)} kg/m³</p>
  <p class="viz-meta">Weak-field acceleration scale: ${t.weak_field_acceleration_scale_m_s2.toExponential(4)} m/s². ${esc(out.interpretation.gravity)}</p></div>`;
});

ForgeUI.registerSection({plugin:"lattice", section:"forge-lattice", label:"Forge Lattice", group:"lattice", defaultPane:"model", panes:{model:()=>{}}, legacy:{}});
