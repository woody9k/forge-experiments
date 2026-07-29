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

## Status: extraction complete, wiring in progress

This repository was extracted from the platform monorepo with
`git filter-repo`, so file history and blame travel with the code. The
**platform monorepo remains the working system**: module import paths in
this tree still reference their monorepo locations (`apps.coordinator.*`,
`forge_metrics`, …) and are rewired by the Phase 3 wiring PRs, which also
add packaging (`forge-experiments` dist consuming the platform's
`forge-platform`/`forge-sdk` dists), `forge.plugins` entry points, and CI.
Until the platform-side cutover PR removes the moved code there, treat this
tree as read-mostly.
