# Forge Experiments

Experiment-domain plugins for the [Forge platform](https://github.com/woody9k/warpforge):
the spacetime-geometry and matter domains extracted from the platform
monorepo (platform-split Phase 3), plus — as this repository grows — example
plugins, plugin templates, and the authoritative plugin-authoring
documentation.

```
plugins/
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
docs/                plugin design docs (authoring guide lands here)
```

## Status: wired and proven; awaiting the platform cutover

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

**Not yet complete**: the platform still reaches domain rows through
compatibility shims that vanish when the domains leave it, so part of the
governed-loop integration suite fails until the platform's cutover PR
lands. Exactly what that PR must change — with the failure inventory — is
in [docs/cross-repo-contract.md](docs/cross-repo-contract.md).
