# OrderOrchestration-as-Code

OrderOrchestration-as-Code: declarative, version-controlled description of
**how incoming orders are split into fulfillable units, and which
downstream workflow each resulting unit triggers**, as YAML, validated
via CI. Covers the layer between warehouse structure and item master
data: the *decision logic* for how an order becomes one or more concrete
fulfillment tasks.

## Related Projects

Part of a family of sibling "-as-Code" repos sharing the same declarative
pattern (JSON Schema validation, `structure/` vs. `strategies/`,
`elements/` catalogs):

| Repo | Covers |
|---|---|
| [`Warehouse-as-Code`](https://github.com/rhinos07/Warehouse-as-Code) | Physical warehouse structure, material-flow communication, movement/replenishment rules |
| **OrderOrchestration-as-Code** (this repo) | How incoming orders are split, and which downstream workflow each split triggers |
| [`MasterData-as-Code`](https://github.com/rhinos07/MasterData-as-Code) | Item/article master data, packaging/UOM hierarchy, sourcing & lifecycle rules |

This repo's `workflow_trigger` values that hand off to the warehouse are
meant to reference `Warehouse-as-Code`'s `elements/process_types.yaml`
vocabulary (see "Shared Vocabulary" below), and `order_position`'s
`material_request.item_id` references item ids owned by
`MasterData-as-Code`; `load_unit_request.load_unit_type` currently
references `Warehouse-as-Code`'s `elements/load_unit_types.yaml`.

## Core Principle

| Layer | What | Change Frequency | Who Changes It |
|---|---|---|---|
| `elements/` | Reusable catalogs (split reasons, etc.) | very rarely | Architect |
| `customers/<customer>/company.yaml` | Tenant/organization identity | very rarely (onboarding/offboarding) | Admin |
| `customers/<customer>/channels/<channel>/channel.yaml` | Sales channel identity (web, marketplace, B2B portal, …) | rarely | Admin/Business Analyst |
| `.../order_types/<order_type>/structure/` | Order/sub-order shape: header target, position kinds, status state machine | rarely (new business model) | Business Analyst, strict review |
| `.../order_types/<order_type>/strategies/` | Split, workflow-trigger, and completion rules | frequently | Order Operations / Logistics Planner, lenient review |

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
an order of type X arriving via channel Y, what shape its header/positions
have, under what conditions it gets split, which named workflow each
resulting piece hands off to, and what happens once sub-orders complete.
Analogous to Terraform: the code describes the orchestration logic, not
any single order's live journey through it.

## Repo Structure

```
order-orchestration-definitions/
├── schemas/                          # JSON Schema for validating all YAML files
│   ├── company.schema.json
│   ├── channel.schema.json
│   ├── order-type.schema.json
│   ├── fields.schema.json            # Per-order-type allowed target/position kinds
│   ├── status.schema.json            # Status state machine
│   ├── order-header.schema.json      # Canonical order/sub-order header shape (incl. 'target')
│   ├── order-position.schema.json    # Canonical line-item shape (3 request kinds, see below)
│   ├── split-rule.schema.json
│   ├── workflow-trigger.schema.json
│   ├── completion-rule.schema.json
│   └── split-reason.schema.json
├── elements/
│   └── split_reasons.yaml            # Catalog of reasons an order can be split
├── customers/
│   └── <customer>/                          # = Company
│       ├── company.yaml                     # Top level, lists channels
│       └── channels/
│           └── <channel>/                   # = Sales channel (web, marketplace, B2B, …)
│               ├── channel.yaml             # Lists order types
│               └── order_types/
│                   └── <order_type>/        # = Order Type (e.g. "b2c_standard")
│                       ├── order_type.yaml         # Imports structure/strategies below
│                       ├── structure/
│                       │   ├── fields.yaml         # Allowed target types / position kinds
│                       │   └── status.yaml         # Statuses + allowed transitions
│                       └── strategies/
│                           ├── split_rules.yaml       # When/how an order splits
│                           ├── workflow_triggers.yaml # Which workflow each split starts
│                           └── completion_rules.yaml  # What happens when sub-order(s) finish
├── tools/
│   └── validate.py          # Validation script (schema + cross-file consistency checks)
├── docs/
│   └── entity-glossary.md
└── .github/workflows/validate.yaml   # CI pipeline (dynamic per-customer matrix)
```

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Validates a company.yaml, channel.yaml, or order_type.yaml - cascades
# down to every channel/order_type it references
python tools/validate.py customers/example_customer/company.yaml
```

## Examples

- `customers/example_customer/` - one channel (`web`) with one order type
  (`b2c_standard`) demonstrating the full model: an order gets split
  across two storage technologies within one facility (AutoStore vs.
  manual warehouse - `split_by: "storage_technology"`), each sub-order
  gets its own `target` (the AutoStore sub-order's target is overridden
  to that cell's own `EXIT` work_center, since it can't reach the real
  outbound door on its own - see `Warehouse-as-Code`'s
  `customers/autostore_customer`), and a `completion_rule` spawns a
  consolidation order once both sub-orders finish. Walked through in
  `docs/entity-glossary.md` under "Splitting and Completion".

## Core Concepts (Quick Reference)

- **order (header)** — one order/sub-order instance: identity, lineage
  (`parent_order_id`, `source_split_rule`), a `target`, and a `status`.
- **target** — the destination an order/sub-order must reach: a
  reference to a `door`, `work_center`, or `activity_area` defined in
  `Warehouse-as-Code`. A sub-order's target can legitimately differ from
  its parent's.
- **position (line item)** — requests exactly one of a `load_unit_request`
  (a specific load unit), a `material_request` (item + quantity), or a
  `suborder_output_request` (the output of an already-completed
  sub-order - used on consolidation orders). Splitting never mutates the
  original position; it creates new positions on the sub-order(s)
  referencing the original via `source_line_id`.
- **split_rule** — defines whether/how an order is decomposed into
  sub-orders (`condition` references `elements/split_reasons.yaml`;
  `target_override` sets a sub-order's target if different from the
  parent's). Independent of *which* workflow the result goes to (see
  `workflow_trigger`) - same separation of concerns as
  `Warehouse-as-Code`'s `lane` ("can") vs. `movement_rule` ("may").
- **workflow_trigger** — maps a `split_rule` outcome to the named
  downstream workflow/process it hands off to. Where that trigger is
  something a warehouse acts on, it should reference the *same*
  `process_type` id as `Warehouse-as-Code`'s `movement_rule.trigger`
  (e.g. `putaway_task`, `pick_task`, `cross_dock_task`) - see "Shared
  Vocabulary" below.
- **completion_rule** — defines what happens once sub-order(s) reach a
  given status: either the parent's own status changes
  (`update_parent_status`), or a new order is spawned
  (`spawn_order` - typically a consolidation order).
- **status** / state machine — the lifecycle an order or sub-order moves
  through, and which transitions are allowed. Every order/sub-order has
  its own independent position in the state machine - a sub-order
  reaching a terminal status does not by itself complete its parent.

Full glossary: [`docs/entity-glossary.md`](docs/entity-glossary.md)

## Shared Vocabulary with Warehouse-as-Code

`workflow_trigger` values that hand off to the warehouse should reuse the
*same* `process_type` catalog that `Warehouse-as-Code`'s
`movement_rule.trigger` references, rather than inventing a parallel set
of names. Right now that catalog (`elements/process_types.yaml`) lives
inside `Warehouse-as-Code` and would need to be duplicated here or
extracted into a small shared repo both projects reference. The same
applies to `order-position.schema.json`'s `load_unit_request.load_unit_type`
(currently referencing `Warehouse-as-Code`'s `elements/load_unit_types.yaml`,
itself flagged as a candidate to move to `MasterData-as-Code`). **Don't
solve this prematurely** - start with a duplicated/local copy here,
and only extract a shared catalog repo once the duplication actually
causes real drift or pain.

## Next Steps for This Repo

- [ ] Build out `MasterData-as-Code` far enough that `material_request.item_id`
      can be cross-checked against real item ids (not yet validated -
      `tools/validate.py` has no referential-integrity check against
      another repo's data)
- [ ] Decide the shared-vocabulary question above (duplicate vs. extract
      a shared catalog repo with `Warehouse-as-Code`/`MasterData-as-Code`)
- [ ] Add more order types / channels to `customers/example_customer/`
      (e.g. a `b2b_bulk` type, a `cross_dock` type)
- [ ] Consider a `sla_class` catalog (delivery-promise/priority
      classification) if/when split rules need to reference urgency

### Open Validation Gap

`tools/validate.py` checks structural cross-references *within* this
repo (e.g. `split_rule.condition` → `elements/split_reasons.yaml`,
`completion_rule.when.status` → `structure/status.yaml`). It does
**not** check references that cross repo boundaries (`target.id` →
an actual `Warehouse-as-Code` door/work_center/activity_area id,
`material_request.item_id` → an actual `MasterData-as-Code` item,
`load_unit_request.load_unit_type` → `Warehouse-as-Code`'s
`elements/load_unit_types.yaml`) - same category of gap
`Warehouse-as-Code` itself started with before cross-file checks were
added there.

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
