# Matter-configuration domain pack

Owned by the matter plugin (platform-split Phase 2); composed into role
prompts by SAGE Core. This is domain expertise, not a new role: the role's
rules always take precedence.

## Terminology

- A **matter configuration** is a physically parameterized genome
  (boundaries, materials, geometry parameters) compiled to a phenotype.
  The policy's `allowed_matter_versions` lists the configuration ids you
  may start from; it fails closed.
- **Mutation operators** (`allowed_mutation_operators`) are the only ways
  to derive new configurations; each application is recorded in lineage.
- **Confidence levels C0–C6** grade matter results; predicted-effect models
  (Casimir, classical gravity) cap at C3, and the platform can never
  self-assign C6 (experimental).

## Procedures

- Derive candidates with `mutate_matter_configuration` (allowlisted parent,
  allowlisted operator, explicit seed), then analyze with
  `submit_matter_analysis`. Analyses run gates 0–2; gates 3–5 and search
  campaigns are deliberately gated off — never propose bypassing them.
- Designer plans compare a mutated candidate against its parent baseline on
  the same observables (e.g. Casimir energy, force, energy accounting).
  Steps use `kind: "baseline"` for the parent and `kind: "mutation"` for
  derived candidates, with `matter_version` and `mutation_operator` fields
  naming the exact allowlisted values.

## Interpretation

- Gate failures and non-finite results arrive labeled (C0, warnings);
  treat them as evidence about the configuration, not noise to retry away.
- Energy-accounting entries must reconcile; an imbalance is a finding.
