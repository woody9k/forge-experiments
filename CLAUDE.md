# CLAUDE.md — working guide for forge-experiments

Onboarding for AI agents (and humans) working in this repository.

**Read this before touching anything.** The single most important fact is the
first one below: this repository is *half of a pair*, and almost nothing here
works — or even imports — without the other half installed.

## 1. You are in the plugin repository

Two repositories make one product. They were split on 2026-07-29 and meet
only through `forge.plugins` setuptools entry points.

| repo | dist | contains |
|---|---|---|
| `woody9k/warpforge` | `forge-platform` | Forge Core, SAGE, the plugin SDK, fabric, API/UI shell, CLI, persistence. **No physics.** |
| `woody9k/forge-experiments` (**this one**) | `forge-experiments` | the geometry and matter domains, `pendulum-lab` (the reference plugin), their tests and docs. **No platform.** |

Consequences you will hit within the first ten minutes:

- **The platform must be installed for this repo's tests to run at all.** They
  import `apps.*` and `forge_sdk.*`, which live in the other repository.
- **Anything platform-shaped belongs over there.** API shell, SAGE loop
  machinery, fabric, auth, persistence contracts, the plugin registry — if
  you are about to edit one of those, you are in the wrong checkout.
- **`../warpforge/CLAUDE.md` is the authority on shared conventions** —
  commit style, the non-negotiable principles, the Docker/compose gotchas,
  the deliberate 501 gates. This file does not duplicate them, because a
  duplicated convention is one that will rot. Read that file too; it is
  long, and it is worth it.

## 2. Setup

```bash
git clone git@github.com:woody9k/warpforge.git
git clone git@github.com:woody9k/forge-experiments.git
cd warpforge
python3.12 -m venv .venv
.venv/bin/pip install -e ".[service,dev]"        # the platform
.venv/bin/pip install -e ../forge-experiments    # these plugins

# both suites — run BOTH, see §3
.venv/bin/python -m pytest -q                    # platform: ~522 passing
cd ../forge-experiments && pytest -q             # here: ~220 passing, ~2 min 50 s
```

There is one venv, and it lives in the **platform** checkout (`warpforge/.venv`).
Editable installs on both sides mean plugin edits need no publish step.

## 3. No CI runs this repository. None.

The platform's self-hosted runner is registered to `woody9k/warpforge` alone,
and `woody9k` is a user rather than an org, so there is no shared runner and
no workflow here. **A platform change is unverified against these plugins
until a human runs `pytest` in this checkout.**

This is not hypothetical. When authentication shipped in the platform
(warpforge #82, 2026-07-30) it was `required` by default; the platform gave
`FORGE_AUTH=off` to *its own* `tests/conftest.py` and nothing gave it to
ours. **32 tests here returned `401` for two days** — across matter, pendulum
and the whole SAGE vertical slice — while both repositories' READMEs stated
the cross-repo suite was green. It was found by a documentation pass that
tried to cite a test count and ran the suite.

The fix is the root `conftest.py`, which turns authentication off by default
and lets a test opt back in with the `auth` marker. Do not delete it.

Closing the structural hole (registering the same box as a second runner) is
tracked as platform backlog **P-11** and needs the operator, not a PR.

## 4. Two traps that will waste your afternoon

**A stale editable install of the platform.** If the venv still holds
`metric-forge` — the platform's pre-split distribution name — it exposes
`packages/*` but **no `apps`**. From a WarpForge checkout that is invisible
because cwd supplies `apps`; from *this* repository it is fatal, and it
presents as ~50 tests erroring with `ModuleNotFoundError: No module named
'apps'` **raised from a fixture that has just purged `sys.modules`** — which
reads exactly like a test-isolation bug and is not one. If the suite errors
*en masse* on imports, check first:

```bash
pip list | grep -i forge     # want forge-platform, NOT metric-forge
cd /tmp && python -c "import apps.api.main"   # must work from a neutral cwd
```

Fix with `pip uninstall metric-forge && pip install -e ".[service,dev]"` from
the platform checkout. Verify from `/tmp`, never from a checkout.

**A multi-root `[tool.setuptools.packages.find] where = [...]`.** This
repository has several plugin roots, and a multi-root `where` pushes
setuptools into a copy-based editable install that silently omits subpackages
*and* package data — the plugin registers and then fails on first use. Use an
explicit `package-dir` map. (The platform's own `where = ["packages", "."]`
is fine and verified; don't "fix" that one on the strength of this paragraph.)

## 5. Writing and changing plugins

`docs/plugin-authoring-guide.md` is the contract, with `plugins/example`
(pendulum-lab) as the worked example — written *against* the published
contract rather than extracted from the platform, which is what makes it
evidence the contract is writable-to.

```bash
# conformance check, from the platform checkout
.venv/bin/python -m forge_sdk.testing --all
.venv/bin/python -m forge_sdk.testing geometry --strict
```

Non-obvious requirements, each of which was once a live bug:

- **Package data is not automatic.** Metric YAML, JSON Schemas, SAGE packs,
  UI modules, prompts and *migrations* must be declared in
  `[tool.setuptools.package-data]` or the wheel ships without them, silently.
- **Ship your own Alembic branch** (`registry.add_migrations`). A plugin whose
  tables are in no migration has **no schema at all** on PostgreSQL; SQLite's
  `create_all` dev path hides it completely.
- **Worker-side contributions are a separate entry point** (`forge.worker`:
  `SUITES`, `JOB_EXECUTORS`) and **must import with no database**.
- **`add_mcp_tools` takes a zero-argument callable**, resolved lazily — so a
  wrong signature is not a startup error. Ours sat in the tree passing its own
  tests until someone actually started the server. Write a test that resolves
  the callable.
- **UI sections declare a `label`**, which is what the platform's Experiments
  menu shows. Each experiment gets its own page.

## 6. Domain gotchas (expensive lessons, keep them)

- SymPy's `Matrix.inv()` takes **minutes to hours** on warp metrics. Use
  adjugate + per-entry `cancel` (`forge_math/pipeline.py`). This is why
  `SIMPLIFY_OP_BUDGET = 40` in `forge_geometry/app/runner.py` — larger
  metrics run unsimplified rather than hanging.
- `sqrt(x**2)` evaluates to `Abs(x)`, and `Abs` derivatives drag `sign()`
  through everything until simplification diverges. The tetrad builder strips
  it — the difference between a 0.4 s Schwarzschild and a hang.
- Natário's zero-expansion proof needs `sin`/`cos(theta)` abstracted as free
  symbols, or `cancel` divides by `sin(theta)` and invents a `Piecewise` on
  the polar axis. Same trap bites anything simplifying a quotient near a
  coordinate-degenerate locus.
- **YAML 1.1: `1.0e10` parses as a string.** Write `1.0e+10`.
- **Energy integrals**: three measures side by side, never aggregated
  (`forge_math/energy.py`, U-4). A **2-D slice integral is energy per unit
  length**, not an energy — promoting it would be wrong by a dimension and
  would look entirely reasonable beside a published figure. ADM is *gated*,
  not approximated. Every gridded run writes them to
  `energy_integrals.json` in its bundle (B-16 part 2).
- **Alcubierre's chart sensitivity is exactly 1.0 and that is correct.** Its
  spatial 3-metric is flat — the whole distortion lives in the lapse and
  shift — so `√det ³g = 1` and the proper and coordinate integrals agree to
  the bit. Natário's is not 1 (spherical chart, `det ³g = r²` over the
  sampled `(r, θ)` plane). Do not "fix" the Alcubierre case; the pair is the
  regression guard in `test_energy_integrals_in_bundle.py`, and if the two
  ever agree it means the volume element stopped being applied.
- **Golden hashes must never be updated to make a test pass.** If
  `test_metric_hash_stability.py` fails, the change altered provenance inputs
  — fix the change. Updating a golden silently orphans every bundle produced
  before it.

## 7. Verifying your work

The platform's rule applies here doubly: **a green suite proves little.**
Every significant fault in the split was found by installing the wheel or
driving the running product, never by tests — unpackaged prompts, a wheel with
no SPA, `relation "pendulum_runs" does not exist` on PostgreSQL only, a login
gate that never visually hid.

- Physics changes → check a **known published value**, not just a unit test.
- Packaging/schema/UI changes → build and install the wheel into a clean venv,
  run against real PostgreSQL, and **look at a screenshot** (CDP
  `Page.captureScreenshot` with `fromSurface: false`; the surface capture
  returns stale frames after scripted interaction).
- Then add the test that would have caught it.

## 8. Where things stand

Three plugins, all passing conformance; pendulum-lab passes with zero
warnings. **All three now contribute an `ExperimentProtocol`**, so a SAGE
research program can be about any of them — geometry's landed 2026-08-01
(platform backlog P-9), and the physics decision it was parked on is
answered by B-16: `compare`'s verdict is the three energy measures plus
chart sensitivity.

Two refusals in `forge_geometry/app/protocol.py` are **correct behaviour,
not gaps**. Arms integrating over different numbers of dimensions are never
differenced, and arms in different charts are reported side by side with no
delta — so an Alcubierre-vs-Natário comparison gives you both metrics'
numbers and no subtraction. If a future change makes those deltas appear,
it has reintroduced the "plausible number in the wrong units" failure the
whole module exists to prevent.

Current suite: **236 passing, ~4 min 50 s** (the warp-metric symbolic work
lives here now, so this is the slow half of the pair).

For what is next, read the platform's `docs/backlog.md` — the B-series items
that live here are **B-16** (scoring; parts 1 and 2 shipped — the "blocked on
persisting `g_μν`" item turned out never to have been true, the metric has
always been in `arrays/grid.npz`), **B-5** (geodesic/tidal diagnostics, computed
but consumed by nothing) and **B-1** (numeric Kretschmann). And read the
platform's `docs/limitations.md`, which is deliberately candid and should
stay that way.
