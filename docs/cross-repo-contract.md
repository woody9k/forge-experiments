# Cross-repository contract and cutover requirements

How this repository and the Forge platform meet, and what the platform's
Phase 3 cutover PR still has to change. Written from a working end-to-end
run of the pair (platform installed as a wheel *without* the domain
packages, this repository installed editable next to it).

## What is proven to work

* **Discovery is entry points only.** The platform registers nothing about
  geometry or matter; it reads `forge.plugins` and both plugins arrive with
  every contribution (routers, SAGE tools, selftest suites, queue task
  types, persistence metadata, SAGE packs).
* **Domain data resolves from package data.** Bundled metric YAML, JSON
  Schemas, and SAGE packs ship inside `forge_geometry` / `forge_matter` and
  load identically from a source checkout and an installed wheel.
* **A real experiment completes across the boundary**: submit Schwarzschild
  with a grid → geometry pipeline runs → 5/5 validations pass →
  visualization data served. Matter materials and configurations likewise.
* **112 plugin tests pass** against the installed platform.

## What the platform cutover PR must change

Every remaining cross-repo failure is the same shape: **platform modules
still reach domain rows through `apps.coordinator.store`**, whose shims
disappear when the domain packages leave. Concretely:

| platform module | calls | resolution |
|---|---|---|
| `sage_repeat.py` | `store.load_matter_analysis` | reach matter storage through the plugin (`forge_matter.app.store`), lazily — the same TRACKED_DEBT that already sanctions its `forge_matter` import |
| `sage_runtime.py` | `store.load_matter_analysis`, `store.load_experiment` | same |
| `apps/api/sage.py` | `store.list_matter_configurations` | same |
| `sage_evidence.py` | geometry experiment lookups | same, via `forge_geometry.app.store` |

This is limitations **P2** (the v0.1 governed loop is matter-path-only)
surfacing as a storage dependency. It is retired properly by the
observation envelope (backlog **P-4**), not by this cutover; until then the
honest behavior is: **the governed loop requires the matter plugin
installed, and says so loudly when it is not.**

The cutover PR must also drop, in the platform:

* `packages/forge_{geometry,math,metrics,validation,verify,matter,scoring}`
* the plugin-owned `apps/` modules listed in the platform's
  `PLUGIN_OWNED_APPS`, plus `metrics/`, `schemas/`, `prompts/sage/packs/`
* the `_compat_` re-export shims in `forge_domain` and `apps.coordinator.store`
* in-repo plugin registration in `apps/plugins/registry.py` (discovery only)
* every entry in the platform's `CUTOVER_DEBT` ledger

## Development workflow

```bash
# platform checkout next to this one
pip install -e ../warpforge[service,dev]
pip install -e .
pytest plugins integration-tests -m "not slow"
```

Editable installs on both sides: no publishing step for a plugin change,
and the platform's data files resolve from its checkout.
