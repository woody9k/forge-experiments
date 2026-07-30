# Writing a Forge plugin

A plugin teaches Forge how to investigate a domain. You define what can be
observed, what may be run, how results are judged, and what SAGE needs to
know; the platform supplies the machinery around it. **You do not modify
Forge Core to add a domain.**

Read this beside `plugins/example/forge_pendulum/` — the pendulum-lab
plugin exercises every contribution point in ~600 readable lines and needs
no physics beyond secondary school. Its `plugin.py` is the whole contract in
one file.

## What Forge gives you

| the platform owns | you never implement it |
|---|---|
| projects, investigations, hypotheses, plans, approvals | the governed research loop |
| runs, execution, retries, leases, worker fleet | scheduling and dispatch |
| artifacts: identity, checksums, bundles, provenance | the reproducibility guarantee |
| evidence, claims (levels 1–6), decisions, audit | who is allowed to conclude what |
| SAGE: roles, prompts, policy, budgets, tool allowlist | agentic planning and its guardrails |
| the UI shell, router, API surface, persistence engine | plumbing |

## What your plugin provides

Its domain model, the schemas of what it observes, the instruments or
simulations that produce observations, the processing that turns them into
results, the interpretation that says what is trustworthy, the visualisations,
the safety rules, and the SAGE knowledge to reason about all of it.

## The contract

A plugin is an ordinary Python distribution with one entry point:

```toml
[project.entry-points."forge.plugins"]
pendulum = "forge_pendulum.plugin:plugin"
```

`plugin` is any object with a `manifest` and an optional `register(registry)`.
`SimplePlugin` covers most cases. Contribution points, all optional:

| call | contributes |
|---|---|
| `add_api_router(router)` | FastAPI routes, mounted only while you are active |
| `add_sage_tool(spec, handler)` | a typed tool a SAGE role may call |
| `add_sage_pack(pack)` | domain expertise composed into role prompts |
| `add_selftest_suite(suite)` | what a worker must prove before running your work |
| `add_task_type(task_type)` | a queue task the generic workers execute |
| `add_persistence_metadata(metadata)` | tables you own |
| `add_mcp_tools(tools_or_callable)` | the same tools over the MCP surface |
| `add_ui_module(path, name)` | a browser module that injects your UI section |
| `add_experiment_protocol(protocol)` | how SAGE runs a comparative experiment in your domain (below) |

Worker hosts get a separate, smaller entry point — see *Running on the
Worker Fabric* below.

Register from inside `register()`, import inside it (a broken import then
disables *your* plugin instead of breaking startup), and expect the platform
to withdraw everything you added the moment you are disabled.

## Joining the governed research loop

Contributing tools lets a SAGE role *call* your domain. Contributing an
`ExperimentProtocol` lets a research program be *about* it: the loop plans
arms, gets them approved by a human, submits them, verifies them, compares
them and builds a claim on the result. Four operations, about seventy lines
— `plugins/example/forge_pendulum/app/protocol.py` is the whole thing.

```python
from forge_sdk import ExperimentProtocol

PROTOCOL = ExperimentProtocol(
    domain="pendulum",
    artifact_type="pendulum_run",     # evidence links carry this; keep it stable
    required_tools=("run_pendulum_experiment",),
    submit=submit, exists=exists, verify=verify, compare=compare,
    validate_arm=validate_arm,        # optional, fail-early
)
```

- **`submit(ctx, arm, repeat_of=None)`** produces one arm's artifact *under
  the id the platform reserved* (`ctx.reserved_id`) — that reservation is
  what makes a crash resumable instead of duplicating work. `ctx.call_tool`
  is the same policy-checked, audited choke point the model goes through.
  `repeat_of` means "run this again for verification".
- **`exists(artifact_id)`** is the cheap poll the wait state uses.
- **`verify(artifact_id, *, program, plan_id, arm)`** re-derives the
  artifact's evidence *coordinator-side*, so the thing that produced a
  result never certifies it. Say what validity means in your domain, then
  lean on the platform for the rest:

  ```python
  from apps.coordinator import sage_evidence

  sage_evidence.assert_owned(program, artifact_id, plan_id=plan_id, arm=arm)
  verified = sage_evidence.verify_bundle(bundle_name, artifact_id)
  return {"my_observable": ..., **verified}
  ```

  The return **must** carry `manifest_checksum` and `artifact_path`; the
  platform will not invent them, and a claim cannot rest on an artifact its
  domain will not checksum. Raise to reject.
- **`compare(ctx, artifacts, mode, tolerances)`** returns whatever the
  comparison means to you — `mode="arms"` is what the analyst role reads,
  `mode="repeat"` is what level-2 verification reads. The platform passes it
  through untouched; it never interprets your numbers.

`required_tools` are authorized *before* a human is asked to approve the
plan, so a program whose policy forbids the work is refused up front. Naming
a tool you do not register is a conformance failure, not a runtime surprise.

What stays the platform's: the state machine, the human gates, budgets,
reserve-first idempotency, the audit trail, evidence re-verification and the
claim ladder. Your protocol supplies the method and nothing else.

## Running on the Worker Fabric

A Worker Fabric agent runs on a host with no database, no coordinator and no
plugin registry — it cannot import your `plugin.py`. So worker-side
contributions come through a second, tiny entry point:

```toml
[project.entry-points."forge.worker"]
pendulum = "forge_pendulum.worker"
```

The module it names exposes either or both of:

```python
SUITES = [...]                       # SelftestSuite: what a host must prove
JOB_EXECUTORS = {"pendulum_run": run_pendulum_job}
```

An executor is `execute(payload, workdir) -> JobResult`: run the work, write
your bundle under `workdir` (the agent has already pointed
`EXPERIMENTS_DIR` there), and return where you put it plus the domain id and
any provenance you want on the attempt. The agent uploads it and the
coordinator re-verifies every checksum — nothing you report about your own
run is taken on trust.

**The one hard rule: this module and everything it imports must work with no
database.** `forge_pendulum/worker.py` imports `app.runner.run_to_bundle`,
which is the store-free half of the pipeline, and imports it lazily so that
stays visible. Importing your `app.store` here makes every agent need a
database it has no reason to have.

Contribute suites without an executor (you validate hosts but submit no
fabric jobs), an executor without suites (your jobs need only the baseline
capability), or both. A host with none of your plugin installed simply
refuses your job type, naming what it *can* run — install your distribution
there with `agent-install.sh --plugin <spec>`.

## Check yourself in one command

```bash
python -m forge_sdk.testing my-plugin      # or --all, or --strict
```

Failures mean the contract is broken. Warnings are legal-but-suspect: no
owner, an unnamespaced queue name, a table called `observations`, a tool
declared with no handler. The pendulum plugin passes with zero warnings, and
its test suite asserts that it keeps doing so.

## Deciding what belongs where

**Your plugin**, if it knows domain terminology, implements a specific
equation/solver/instrument, defines domain observations, renders a
domain-specific view, or teaches SAGE how to reason in your field.

**The platform**, if multiple unrelated domains need it, it describes the
universal investigation lifecycle, or it manages identity, provenance,
execution, storage or access. If you find yourself wanting a platform change,
say what second domain would also need it — that is the test.

**Nowhere yet**, if only your plugin needs it. Keep it in your plugin until a
second domain proves it is shared. Forge is not the attic.

## Designing observations

Keep these distinct; conflating them is the most common way a research
platform starts lying to itself:

| | what it is |
|---|---|
| **artifact** | raw bytes you produced, checksummed and addressable |
| **observation** | a measured value with units, uncertainty and quality |
| **evidence** | an observation *linked to a claim*, with provenance |
| **finding** | an interpretation a human or role committed to |
| **claim** | a finding at a declared confidence level, gated |

Forge owns the observation *envelope* (ids, timestamps, run linkage, units
mode, quality, provenance, payload type + version). You own the payload and
its schema. Concretely, from the example: the integration is the artifact,
the measured period is the observation, and the small-angle comparison is the
evidence a claim about the pendulum would rest on.

## Being honest about uncertainty

This is the part reviewers care about, and the example demonstrates all three
outcomes deliberately:

* a 5° swing **passes** the known-answer check, and reports its deviation
  (`+4.8e-04`) rather than just "ok";
* a 90° swing is **inapplicable** — outside the small-angle regime, so the
  closed form is not expected to hold. It is *not* a pass and *not* a
  failure, and calling it either would be a lie;
* a 0.5 s run is **unresolved** — no period is measurable, so no number is
  returned at all, with a warning saying what to change.

Rules worth copying: fail loudly on invalid input *before* computing; never
return a plausible number you do not trust; report the diagnostic that would
let someone else disbelieve you (here, energy drift); and never let your code
decide that its own result is valid — hand the evidence to the platform.

## Exposing safe actions

A SAGE tool spec declares which roles may call it and at what risk class. The
platform enforces both, and a plugin **cannot** widen policy: shadowing a
core tool, or claiming a lower risk class than your action deserves, is
refused at registration. Treat tool arguments as untrusted model output —
validate types and ranges, reject ids that are not the shape you expect, and
raise rather than coerce. Declare hard limits in `safety_policies` so an
operator can read them on the Plugins page.

## Packaging: the two traps everyone hits

1. **Non-module files must be declared as package data**, or your wheel ships
   without them and the failure is silent. Prompts, JSON Schemas, bundled
   data, UI modules — all of it:

   ```toml
   [tool.setuptools.package-data]
   forge_pendulum = ["sage/*.md", "ui/*.js"]
   ```

   Resolve them with `importlib.resources`, never a path relative to the
   repository root, so a checkout and a wheel behave identically.

2. **Use an explicit `package-dir` map, not multi-root discovery.** Two
   `where` roots push setuptools into a copy-based editable install that
   omits subpackages and data — your plugin then registers and fails at first
   use.

## Development loop

```bash
pip install -e ../warpforge[service,dev]     # the platform
pip install -e .                              # your plugin
python -m forge_sdk.testing --all             # contract check
pytest                                        # your tests
FORGE_EAGER=1 uvicorn apps.api.main:app       # drive it in a browser
```

Editable installs on both sides: no publishing step for a plugin change. To
run your plugin in the Docker stack, stage a wheel
(`scripts/forge-plugins.sh <checkout>` in the platform repo) and rebuild.

`FORGE_PLUGINS_DISABLE=<id>` turns a plugin off without uninstalling — useful
for proving the platform still works without you, which it must.

## A worked investigation

The tutorial the example supports, from question to report:

1. **Question.** "Does a pendulum's period depend on how far you pull it
   back?"
2. **Baseline.** `predict_pendulum_period` gives the closed form: no, in the
   small-angle limit — `T = 2π√(L/g)` has no amplitude term.
3. **Experiment.** `run_pendulum_experiment` at 5°, then 90°, same length.
4. **Observations.** Measured periods, with deviation, swing count and energy
   drift attached to each.
5. **Evidence.** The 5° run's known-answer check passes; the 90° run's is
   recorded inapplicable — which is itself informative.
6. **Finding.** The period *does* grow with amplitude (+18% at 90°), and the
   closed form is a small-angle approximation rather than a general law.
7. **Report.** The bundle for each run carries spec, result, validation and
   provenance with checksums, so the finding is re-derivable by someone who
   trusts none of it.

That is the whole shape of Forge: your plugin supplied the competence, SAGE
could have proposed the plan, and the platform kept everyone honest about
what was actually shown.
