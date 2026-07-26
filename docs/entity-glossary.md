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
| `order` (header) | One order or sub-order instance. Carries identity (`order_id`, `order_type`), lineage (`parent_order_id`, `source_split_rule`), a `target` and `order_target`, and a `status`. Actual instances are runtime data (in the WMS/OMS) - this repo only defines the allowed shape, in `schemas/order-header.schema.json`. |
| `target` | The **movement target**: the destination *this specific* order/sub-order's executing system must physically reach - the next reachable hop, not necessarily the final business destination. A reference to a `door`, `work_center`, or `activity_area` defined in `Warehouse-as-Code`. A sub-order's target can differ from its parent's and from its own `order_target` - see "Splitting and completion" and "Order Target vs. Movement Target" below. |
| `order_target` | The **order target**: the immutable business destination for the order line, set once on the top-level order and inherited unchanged by every descendant sub-order no matter how many times it is split or re-split. Same shape as `target`. An order/sub-order is only truly fulfilled once its confirmed quantity is reached **and** `target == order_target`. |
| `position` (line item) | A single line item on an order header (`schemas/order-position.schema.json`). Requests exactly one of: `load_unit_request` (a specific load unit), `material_request` (item + quantity), or `suborder_output_request` (the output of an already-completed sub-order - used on consolidation orders). |
| `status` | The state machine an order type's orders/sub-orders move through (`structure/status.yaml`). Every order/sub-order has its own, independent position in this state machine. |
| `fields` | Per-order-type restriction of which `target` types and `position` kinds are allowed (`structure/fields.yaml`), on top of the canonical shapes in `schemas/order-header.schema.json` / `schemas/order-position.schema.json`. |

## Process Rules

| Term | Meaning |
|---|---|
| `split_rule` | Defines when/how an order is decomposed into sub-orders (`strategies/split_rules.yaml`). `condition` references `elements/split_reasons.yaml` and names the *reason*, which sibling rules share. `when` is what distinguishes and gates an individual rule: `when.status` restricts it to orders that have reached a given status (omit for splits decidable at intake), and `when.dimension_value` declares which value of `split_by` this rule covers - `tools/validate.py` requires siblings sharing a `split_by` to declare distinct values, since without that a set of rules is not dispatchable. Deliberately a structured object rather than an expression language: which storage technology holds an item's stock is live inventory state this repo family does not model, so the runtime resolves a position's actual value and the rule only declares which value it claims. `target_override` sets a sub-order's **movement target** (`target`) if it differs from the parent's. `order_target_override` additionally sets the sub-order's **order target** too - by default `order_target` always inherits unchanged regardless of `target_override`; use `order_target_override` only when this split's destination genuinely becomes the sub-order's new final business destination (e.g. inbound putaway), not for outbound-style splits where `order_target` is the customer's fixed destination. Omit both to inherit the parent's `target`/`order_target` unchanged. |
| `workflow_trigger` | Maps a `split_rule` outcome to the downstream process/workflow that should start for the resulting sub-order (`strategies/workflow_triggers.yaml`). Where that trigger is something a warehouse acts on, it references the same `process_type` id `Warehouse-as-Code`'s `movement_rule.trigger` uses. |
| `completion_rule` | Defines what happens once sub-order(s) reach a given status (`strategies/completion_rules.yaml`). `when` names the watched status, a quantifier (`all_children` / `any_child` / `n_of_m`), optionally `target_gap` (fires only for a child whose `target != order_target` at that status - "confirmed but not actually there yet"), and optionally `source_split_rules` (restricts which children are considered to those created by the named `split_rule`s - without it, two `completion_rule`s on the same order_type can cross-fire on each other's children whenever their `when` conditions happen to overlap, e.g. any `target_override` makes `target != order_target`). `action` is `update_parent_status`, `spawn_order` (typically a consolidation order - see below), or `reallocate_remainder` (reactively re-splits the outstanding remainder into a new sub-order - see "Order Target vs. Movement Target" below). |

## Splitting and Completion (Key Architectural Principle)

See [`examples/order_walkthrough/`](../examples/order_walkthrough/) for
this scenario worked out as concrete, illustrative order instances
(header + positions) - including a real gap it surfaced in
`completion_rule` (see that folder's README and the main README's "Next
Steps").

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

## Order Target vs. Movement Target (Multi-System Reallocation)

The scenario above is a *planned* split: the AutoStore sub-order's
target override is known upfront, at config time, because that
building's connectivity is a fixed fact. Some multi-system outbound
scenarios can't be planned that way - a system may confirm its
requested quantity but only physically reach an intermediate point
(e.g. a shuttle system that can only move goods as far as a
consolidation area), or it may fall short on quantity or fail outright,
and which of these happens is only known at runtime.

To cover this with the same split mechanism, `order-header.schema.json`
separates two things that a single `target` field used to conflate:

- **`target`** (movement target) - the destination *this* order/sub-order's
  executing system must physically reach. Can be overridden per
  sub-order (`split_rule.target_override`), same as before.
- **`order_target`** - the immutable business destination, set once on
  the top-level order and inherited **unchanged** by every descendant,
  no matter how many times the demand is split or re-split. Never
  touched by `target_override`.

An order/sub-order is only truly fulfilled once **both** hold: its
confirmed quantity meets what was requested, **and**
`target == order_target`. `completion_rule.when.target_gap: true`
watches for the case where the first is true but the second isn't -
typically paired with `quantifier: "any_child"` so each gapped child is
handled the moment it's detected, not batched with siblings the way
`quantifier: "all_children"` is used for planned consolidation above.
`action.type: "reallocate_remainder"` then spawns a new sub-order for
the outstanding remainder; that sub-order always inherits
`order_target` unchanged (there is no static "reallocate_target" to
configure) - *which* system or route actually closes the gap is a
runtime allocation decision, same as the "target is decided once, not
re-resolved dynamically here" principle below.

Worked example: 50 units requested, `order_target` = door `GATE_3`.
30 units sit in a shuttle-served zone (reachable only as far as a
consolidation area), 20 in a manually picked zone (reachable directly
to the door).

```
1. OrderLine: qty 50, order_target = GATE_3

2. Split (planned, by storage_technology):
   Sub-order A: qty 30, target = CONSOLIDATION_1 (target_override)
   Sub-order B: qty 20, target = GATE_3 (inherited)

3. Sub-order B reaches "completed": target == order_target -> done, closed.

4. Sub-order A reaches "completed": target != order_target -> target_gap.
   completion_rule (when.target_gap, quantifier: any_child) fires
   action.reallocate_remainder -> spawns Sub-order C:
     target = order_target = GATE_3 (inherited, not statically declared)
     position: suborder_output_request -> Sub-order A (take its 30 units)

5. Sub-order C reaches "completed": target == order_target -> done.

6. OrderLine closes: sum over leaves with target == order_target
   (B=20 + C=30) = 50.
```

A quantity shortfall or an execution failure would be modeled the same
way - a `completion_rule` watching a different status (or the same
status under a different condition) with `action.type:
"reallocate_remainder"` - since in both cases the fix is identical:
spawn a new sub-order for the still-outstanding quantity, inheriting
`order_target` unchanged. Only the trigger condition differs from the
target-gap case; the reallocation mechanism itself is one thing, not
three. See
[`examples/multi_system_reallocation_walkthrough/`](../examples/multi_system_reallocation_walkthrough/)
for this scenario worked out as concrete order instances.

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
   reference and, via `split_rule.target_override` (planned) or
   `completion_rule.action.reallocate_remainder` (reactive), when a
   sub-order's target legitimately differs from its parent's. Its
   `order_target`, by contrast, never differs from its parent's - see
   "Order Target vs. Movement Target" below.

3. **Split ("may be decomposed") vs. trigger ("what starts") vs.
   completion ("what happens when done")**: three separate entities
   (`split_rule`, `workflow_trigger`, `completion_rule`), each with its
   own lifecycle - mirrors `Warehouse-as-Code`'s deliberate separation of
   `lane` ("can"), `movement_rule` ("may"), and `replenishment_strategy`.
