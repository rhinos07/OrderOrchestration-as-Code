# OrderOrchestration-as-Code

OrderOrchestration-as-Code: declarative, version-controlled description of
**how incoming orders are split into fulfillable units, and which
downstream workflow each resulting unit triggers**, as YAML, validated
via CI. Sibling project to
[`Warehouse-as-Code`](../Warehouse-as-Code) (physical structure +
movement rules) and `MasterData-as-Code` (items, UOM, packaging) - this
repo covers the layer between the two: the *decision logic* for how an
order becomes one or more concrete fulfillment tasks.

## Core Principle

| Layer | What | Change Frequency | Who Changes It |
|---|---|---|---|
| `elements/` | Reusable templates (order line templates, SLA classes, etc.) | very rarely | Architect |
| `customers/<customer>/company.yaml` | Tenant/organization identity | very rarely (onboarding/offboarding) | Admin |
| `customers/<customer>/channels/<channel>/channel.yaml` | Sales channel identity (web, marketplace, B2B portal, …) | rarely | Admin/Business Analyst |
| `.../channels/<channel>/structure/` | Order type definitions, line structure, status/state machine | rarely (new business model) | Business Analyst, strict review |
| `.../channels/<channel>/strategies/` | Split rules and workflow-trigger mappings | frequently | Order Operations / Logistics Planner, lenient review |

A company can have multiple sales channels, and each channel can define
multiple order types - **Company → Channel → Order Type**. This mirrors
`Warehouse-as-Code`'s Company → Facility → Building split: a stable
identity layer, then a `structure/` vs. `strategies/` split by change
frequency and reviewer.

**What this repo is not**: it does not track live orders, their current
status, or actual quantities/dates (that's runtime state in the OMS/WMS
- here, KCC). It does not define item/article master data (that's
`MasterData-as-Code`). And it does not define *how* a triggered workflow
is executed inside the warehouse (that's `Warehouse-as-Code`'s
`movement_rules.yaml`/`replenishment.yaml`). This repo only defines: for
an order of type X arriving via channel Y, under what conditions does it
get split, into what, and which named workflow/trigger does each
resulting piece hand off to. Analogous to Terraform: the code describes
the orchestration logic, not any single order's live journey through it.

## Repo Structure

```
order-orchestration-definitions/
├── schemas/                  # JSON Schema for validating all YAML files
├── elements/                 # Reusable templates and catalogs
│   ├── order_line_templates.yaml   # Reusable order line shapes
│   ├── sla_classes.yaml            # Delivery-promise / priority classes
│   └── split_reasons.yaml          # Catalog of reasons an order can be split
├── customers/
│   └── <customer>/                          # = Company
│       ├── company.yaml                     # Top level, lists channels
│       └── channels/
│           └── <channel>/                   # = Sales channel (web, marketplace, B2B, …)
│               ├── channel.yaml             # Lists order types
│               └── order_types/
│                   └── <order_type>/        # = Order Type (e.g. "b2c_standard")
│                       ├── order_type.yaml         # Imports structure/strategies below
│                       ├── structure/              # Order shape (stable)
│                       │   ├── fields.yaml         # Order/line fields, required data
│                       │   └── status.yaml         # Status values + allowed transitions
│                       └── strategies/             # Process rules (changes often)
│                           ├── split_rules.yaml     # When/how an order splits
│                           └── workflow_triggers.yaml  # Which workflow each split
│                                                        #   outcome hands off to
├── tools/
│   ├── validate.py          # Validation script (schema + consistency checks)
│   └── compile.py           # Expands template/generator syntax into concrete
│                             #   split-rule instances (build/ output)
├── docs/
│   └── entity-glossary.md
└── .github/workflows/validate.yaml   # CI pipeline
```

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Validates a company.yaml, channel.yaml, or order_type.yaml - cascades
# down to every channel/order_type it references
python tools/validate.py customers/example_customer/company.yaml

# Expand any generator syntax into concrete split_rule/workflow_trigger
# instances for one specific order type
python tools/compile.py customers/example_customer/channels/web/order_types/b2c_standard/order_type.yaml --output build/split_rules.yaml
```

## Examples

- `customers/example_customer/` - *(to be added)* one channel with two or
  three order types (e.g. a simple single-location order, a
  multi-location split order, and a cross-dock passthrough) to show most
  entity types at once.

## Core Concepts (Quick Reference)

- **order_type** — a category of incoming order (e.g. `b2c_standard`,
  `b2b_bulk`, `cross_dock`) with its own field structure, status/state
  machine, split rules, and workflow triggers.
- **split_rule** — defines whether/how an order (or order line) is
  decomposed into sub-units - by fulfillment location, by partial
  availability, by carrier/shipping method, by promise date, etc.
  Independent of *which* workflow the result goes to (see
  `workflow_trigger`) - same separation of concerns as
  `Warehouse-as-Code`'s `lane` ("can") vs. `movement_rule` ("may").
- **workflow_trigger** — maps a split outcome to the named downstream
  workflow/process it hands off to (e.g. `ship_from_dc`,
  `direct_ship`, `pickup_in_store`, `cross_dock_passthrough`). Where
  that trigger is something a warehouse acts on, it should reference the
  *same* `process_type` id as `Warehouse-as-Code`'s
  `movement_rule.trigger` (e.g. `putaway_task`, `pick_task`,
  `cross_dock_task`) - see "Shared Vocabulary" below.
- **status** / state machine — the lifecycle an order (or a split unit)
  moves through (e.g. `created` → `split` → `allocated` → `released` →
  `fulfilled` → `closed`), and which transitions are allowed.
- **sla_class** — delivery-promise/priority classification an order
  type can carry, referenced by split rules to decide urgency-driven
  splitting.

Full glossary: `docs/entity-glossary.md` *(to be written - mirror the
structure of Warehouse-as-Code's docs/entity-glossary.md)*

## Shared Vocabulary with Warehouse-as-Code

`workflow_trigger` values that hand off to the warehouse should reuse the
*same* `process_type` catalog that `Warehouse-as-Code`'s
`movement_rule.trigger` references, rather than inventing a parallel set
of names. Right now that catalog (`elements/process_types.yaml`) lives
inside `Warehouse-as-Code` and would need to be duplicated here or
extracted into a small shared repo both projects reference. **Don't
solve this prematurely** - start with a duplicated/local copy here,
and only extract a shared catalog repo once the duplication actually
causes real drift or pain.

## Next Steps for This Repo

- [ ] Define `schemas/order-type.schema.json`, `schemas/split-rule.schema.json`,
      `schemas/workflow-trigger.schema.json`
- [ ] Build `customers/example_customer/` with 2-3 worked order types
- [ ] Decide the shared-vocabulary question above (duplicate vs. extract
      a shared catalog repo with `Warehouse-as-Code`/`MasterData-as-Code`)
- [ ] `tools/validate.py` / `tools/compile.py` - port from
      `Warehouse-as-Code`'s tooling as a starting point, adjust entity
      names

### Out of Scope (By Design)

- **Runtime state**: actual live orders, their current status, real
  quantities/dates, waves, warehouse tasks - these live in the OMS/WMS
  runtime database (KCC), not here.
- **Item/article master data**: SKUs, batches, UOM conversions - that's
  `MasterData-as-Code`.
- **Warehouse structure and movement rules**: physical layout,
  storage_types, `movement_rules.yaml` - that's `Warehouse-as-Code`.
  This repo only decides *which* workflow trigger fires; what that
  trigger physically does inside a warehouse is `Warehouse-as-Code`'s
  concern.
- **Labor management, yard management** - same reasoning as
  `Warehouse-as-Code`'s own exclusions.
