# Forge Experiments

Experiment-domain plugins for the [Forge platform](https://github.com/woody9k/warpforge):
the spacetime-geometry and matter domains extracted from the platform
monorepo (platform-split Phase 3), plus — as this repository grows — example
plugins, plugin templates, and the authoritative plugin-authoring
documentation.

```
plugins/
  example/      pendulum-lab: the reference plugin. Exercises every
                contribution point on a domain that needs no physics to read,
                and is the worked example for docs/plugin-authoring-guide.md
  geometry/     spacetime-geometry domain: metric library + symbolic tensor
                pipeline (forge_math), restricted-format metric loading
                (forge_metrics), energy conditions + known-answer validation
                (forge_validation), the independent verification backend
                (forge_verify — never imports forge_math, by contract),
                domain entities + worker selftests (forge_geometry), and the
                app-layer contributions (API router, pipeline runner, queue
                tasks, SAGE tools, persistence, UI section, SAGE pack)
  matter/       matter domain: genome→phenotype compiler, materials DB,
                Casimir + classical models, mutations (forge_matter) and its
                app-layer contributions. Campaign execution remains
                deliberately 501-gated (see the platform's
                docs/matter-forge-design.md §9)
integration-tests/   cross-plugin + governed-loop (§21) integration tests
docs/                plugin-authoring-guide.md + design docs
```

## Writing a plugin

Start with **[docs/plugin-authoring-guide.md](docs/plugin-authoring-guide.md)**
and read `plugins/example/forge_pendulum/` alongside it. Check your work with

```bash
python -m forge_sdk.testing my-plugin      # or --all, or --strict
```

## Status: wired and proven

Extracted from the platform monorepo with `git filter-repo` (history and
blame travel with the code), then wired into two real plugins:

* `forge-experiments` is an installable distribution depending on
  `forge-platform>=0.4,<0.5`, declaring both plugins as `forge.plugins`
  entry points — the platform registers nothing about them.
* Domain data (bundled metrics, JSON Schemas, SAGE packs) ships as plugin
  package data, so it resolves identically from a checkout and a wheel.

**Verified end to end against a platform installed without any domain
packages**: both plugins activate through entry-point discovery alone, a
Schwarzschild experiment runs to 5/5 passing validations with visualization
data, the matter path serves and simulates, and **112 plugin tests pass**.

The platform cutover has landed, so this repository is the only home of the
domains. The full plugin and integration suite passes against an installed
platform, and all three plugins pass the conformance harness. Matter and
pendulum each contribute an `ExperimentProtocol`, so a SAGE research program
can be *about* either domain; geometry does not yet (platform backlog P-9).

Since then (2026-07-31 → 08-01):

* **Geodesic and tidal diagnostics** (`forge_math/diagnostics.py`, B-5): the
  tidal tensor `E_μν = R_μανβ uᵃuᵝ` with its principal stretches, and
  `solve_ivp` worldline integration that carries norm drift as its own error
  estimate. The 4-velocity is validated rather than assumed — before that a
  5×-scaled observer silently returned a 20× tidal magnitude, and the vacuum
  trace check cannot catch it. Library only so far: no API, no UI, and
  nothing scores with it yet, so the campaign gate stays shut.
* **`POST /api/v1/experiments` rejects unknown fields** instead of ignoring
  them. Sending `parameters` where the field is `parameter_values` used to
  run the metric's *defaults* and report success — a 27-point sweep came
  back as 27 identical runs that all "passed". `extra="forbid"` makes that
  a `422`.
* **Compare Runs** fits a scaling law across a sweep, reading each run's
  parameters from its bundle manifest via `/experiments/summary`. First real
  result: Alcubierre's peak negative energy density goes as **v²σ²,
  essentially independent of R** — ×4.00 per doubling of velocity.
* **Plain-language results**: a verdict sentence and a glossary over the
  evidence tables, so `confirmed_violation` reads as what it is (for a warp
  metric, the expected finding) rather than as a failure.
* **Our MCP tools were written against a signature that does not exist** and
  nothing caught it, because the contribution is a lazily-resolved callable.
  Fixed, with a test that resolves it — see the authoring guide.
* Each UI section declares a **display label**, which is what the platform's
  Experiments menu shows now that each experiment has its own page.
