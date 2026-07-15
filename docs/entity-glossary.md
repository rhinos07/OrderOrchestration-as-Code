# Entity Glossary

## Organizational Hierarchy

| Term | Meaning |
|---|---|
| `company` | Top-level tenant/organization (`company.yaml`). Lists one or more `channel` files. |
| `channel` | A sales channel (web, marketplace, B2B portal, …) belonging to a `company` (`channel.yaml`). Lists one or more `order_type` files. |
| `order_type` | A category of incoming order within a `channel` (e.g. `b2c_standard`). Imports its own `structure/` and `strategies/`. |

A company can have multiple channels, and each channel can define
multiple order types - **Company → Channel → Order Type**.
`tools/validate.py` accepts a path at any of the three levels and
cascades validation downward automatically.

## Structure

| Term | Meaning |
|---|---|
| `order` (header) | One order or sub-order instance. Carries identity (`order_id`, `order_type`), lineage (`parent_order_id`, `source_split_rule`), a `target`, and a `status`. Actual instances are runtime data (in the WMS/OMS) - this repo only defines the allowed shape, in `schemas/order-header.schema.json`. |
| `target` | The destination an order/sub-order must reach - a reference to a `door`, `work_center`, or `activity_area` defined in `Warehouse-as-Code`. A sub-order's target can differ from its parent's - see "Splitting and completion" below. |
| `position` (line item) | A single line item on an order header (`schemas/order-position.schema.json`). Requests exactly one of: `load_unit_request` (a specific load unit), `material_request` (item + quantity), or `suborder_output_request` (the output of an already-completed sub-order - used on consolidation orders). |
| `status` | The state machine an order type's orders/sub-orders move through (`structure/status.yaml`). Every order/sub-order has its own, independent position in this state machine. |
| `fields` | Per-order-type restriction of which `target` types and `position` kinds are allowed (`structure/fields.yaml`), on top of the canonical shapes in `schemas/order-header.schema.json` / `schemas/order-position.schema.json`. |

## Process Rules

| Term | Meaning |
|---|---|
| `split_rule` | Defines when/how an order is decomposed into sub-orders (`strategies/split_rules.yaml`). `condition` references `elements/split_reasons.yaml`. `target_override` sets a sub-order's target if it differs from the parent's - omit to inherit the parent's target unchanged. |
| `workflow_trigger` | Maps a `split_rule` outcome to the downstream process/workflow that should start for the resulting sub-order (`strategies/workflow_triggers.yaml`). Where that trigger is something a warehouse acts on, it references the same `process_type` id `Warehouse-as-Code`'s `movement_rule.trigger` uses. |
| `completion_rule` | Defines what happens once sub-order(s) reach a given status (`strategies/completion_rules.yaml`). `when` names the watched status and a quantifier (`all_children` / `any_child` / `n_of_m`). `action` is either `update_parent_status` or `spawn_order` (typically a consolidation order - see below). |

## Splitting and Completion (Key Architectural Principle)

A sub-order reaching its own target does **not** automatically complete
its parent. Example: an order is split between an AutoStore cell and a
manual warehouse area within the same facility (`split_by:
"storage_technology"`, `condition: "storage_technology_split"`). The
AutoStore sub-order's target is overridden to that cell's own `EXIT`
work_center (see `Warehouse-as-Code`'s `customers/autostore_customer` -
that building deliberately has no door/lane infrastructure, only
ENTRY/EXIT work_centers as its system boundary) - it can never reach the
parent order's actual outbound door on its own. The manual warehouse
sub-order, by contrast, inherits the parent's target unchanged and can
reach the door directly.

Once **both** sub-orders reach a terminal status (`completed`), a
`completion_rule` with `quantifier: "all_children"` spawns a new
**consolidation order**: a fresh order of the same `order_type`, whose
`target` is the original parent's door, and whose positions are
`suborder_output_request` entries - "take whatever these completed
sub-orders produced" - rather than fresh `material_request`s. This keeps
splitting, execution, and consolidation expressed uniformly in the same
header/position model, without a dedicated "consolidation" entity.

The original order's positions are never mutated by a split - a split
creates **new** positions on the sub-order(s) that reference the
original via `source_line_id`, so the original order always shows what
was actually ordered, independent of how it ended up being fulfilled.

## Reusable Catalogs (`elements/`)

| Term | Meaning |
|---|---|
| `split_reason` | Catalog of reasons an order can be split (`elements/split_reasons.yaml`). Referenced by `split_rule.condition`. |

## Key Architectural Principles

1. **Structure vs. runtime state**: These YAML files describe only the
   allowed shape and rules. Actual live orders, their current status,
   and real quantities/dates live in the OMS/WMS runtime database (KCC),
   not here - analogous to `Warehouse-as-Code`'s own structure-vs-runtime
   principle.

2. **`target` is decided once, not re-resolved dynamically**: A
   `target` references a specific `Warehouse-as-Code` door/work_center/
   activity_area id, chosen at order/sub-order creation time by the
   runtime. This repo does not model *which* facility/location gets
   chosen (that's an allocation decision) - only the shape of the
   reference and, via `split_rule.target_override`, when a sub-order's
   target legitimately differs from its parent's.

3. **Split ("may be decomposed") vs. trigger ("what starts") vs.
   completion ("what happens when done")**: three separate entities
   (`split_rule`, `workflow_trigger`, `completion_rule`), each with its
   own lifecycle - mirrors `Warehouse-as-Code`'s deliberate separation of
   `lane` ("can"), `movement_rule` ("may"), and `replenishment_strategy`.
