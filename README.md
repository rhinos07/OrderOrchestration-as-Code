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
| [`Topology-as-Code`](https://github.com/rhinos07/Topology-as-Code) | Physical warehouse structure, material-flow communication, movement/replenishment rules |
| **OrderOrchestration-as-Code** (this repo) | How incoming orders are split, and which downstream workflow each split triggers |
| [`MasterData-as-Code`](https://github.com/rhinos07/MasterData-as-Code) | Item/article master data, packaging/UOM hierarchy, sourcing & lifecycle rules |
| [`Allocation-as-Code`](https://github.com/rhinos07/Allocation-as-Code) | Stock-search configuration: search-zone sequence, selection strategy, constraints |

This repo's `workflow_trigger` values that hand off to the warehouse are
meant to reference `Topology-as-Code`'s `elements/process_types.yaml`
vocabulary (see "Shared Vocabulary" below), and `order_position`'s
`material_request.item_id` references item ids owned by
`MasterData-as-Code`; `load_unit_request.load_unit_type` currently
references `Topology-as-Code`'s `elements/load_unit_types.yaml`. A
`material_request.item_id`/`quantity` is also the same demand shape
`Allocation-as-Code`'s `search_rule.applies_to.item_id` scopes a search
strategy to - this repo doesn't itself trigger or consult a stock
search, it only produces the item/quantity demand that a runtime
component would hand to one.

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
`Topology-as-Code`'s Company → Facility → Building split: a stable
identity layer, then a `structure/` vs. `strategies/` split by change
frequency and reviewer.

**What this repo is not**: it does not track live orders, their current
status, or actual quantities/dates (that's runtime state in the OMS/WMS
- here, KCC). It does not define item/article master data (that's
`MasterData-as-Code`). And it does not define *how* a triggered workflow
is executed inside the warehouse (that's `Topology-as-Code`'s
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
│   ├── split_reasons.yaml            # Catalog of reasons an order can be split
│   └── split_dimensions.yaml         # Catalog of dimensions an order can be split along
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
├── examples/
│   └── order_walkthrough/    # Illustrative order instances (NOT structural config,
│                             #   NOT real runtime data) - see its own README
├── tools/
│   ├── validate.py           # Validation script (schema + cross-file consistency checks)
│   └── validate_examples.py  # Validates examples/ instance files against
│                              #   order-header.schema.json / order-position.schema.json
├── docs/
│   └── entity-glossary.md
└── .github/workflows/validate.yaml   # CI pipeline (dynamic per-customer matrix)
```

## Schema Versioning

Every `order_type.yaml` declares the schema generation it conforms to:

```yaml
api_version: "order-orchestration-as-code/v1"
```

It sits on the order type because that is this repo's self-contained,
independently loadable scope - the unit an engine loads to run one order
flow, and the same role `warehouse.yaml` plays in `Topology-as-Code`.
`company.yaml` and `channel.yaml` index the level below them rather than
being datasets of their own, so they carry no version.

This matters more here than in the structural repos: several open items in
"Next Steps" below (a trigger-status concept for `split_rule`, real
semantics for `split_rule.condition`) are incompatible changes when they
land. The version is what lets them land as a new generation instead of
silently reinterpreting existing order types. See
[`Warehouse-as-Code` ADR-0001](https://github.com/rhinos07/Warehouse-as-Code/blob/main/docs/adr/0001-layered-specification-model.md),
measure 2.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Validates a company.yaml, channel.yaml, or order_type.yaml - cascades
# down to every channel/order_type it references
python tools/validate.py customers/example_customer/company.yaml

# Validates the illustrative order-instance examples (header + positions)
# against order-header.schema.json / order-position.schema.json
python tools/validate_examples.py examples/order_walkthrough
```

## Examples

- `customers/example_customer/` - one channel (`web`) with one order type
  (`b2c_standard`) demonstrating the full model: an order gets split
  across two storage technologies within one facility (AutoStore vs.
  manual warehouse - `split_by: "storage_technology"`), each sub-order
  gets its own `target` (the AutoStore sub-order's target is overridden
  to that cell's own `EXIT` work_center, since it can't reach the real
  outbound door on its own - see `Topology-as-Code`'s
  `customers/autostore_customer`), and a `completion_rule` spawns a
  consolidation order once both sub-orders finish. Walked through in
  `docs/entity-glossary.md` under "Splitting and Completion".
- `examples/order_walkthrough/` - concrete, illustrative order instances
  (header + positions with real-looking item ids/quantities) for the
  scenario above - not structural config, not real runtime data. See its
  own README for the flow diagram; building it surfaced a real gap in
  `completion_rule` (see "Next Steps" below).
- `examples/multi_system_reallocation_walkthrough/` - a second scenario,
  under its own `b2c_multi_system` order type: one order line split
  across a shuttle-served zone and a manually picked zone
  (`SPLIT_TO_SHUTTLE_ZONE` / `SPLIT_TO_MANUAL_PICK_ZONE`), where the
  shuttle zone can only reach an intermediate consolidation area, not
  the order's real target. `REALLOCATE_SHUTTLE_TARGET_GAP`
  (`when.target_gap` + `action.reallocate_remainder`) reactively closes
  that gap with a further sub-order. Originally lived under
  `b2c_standard` alongside the AutoStore/manual scenario, until running
  both together showed `REALLOCATE_SHUTTLE_TARGET_GAP` also firing on
  the AutoStore sub-order (its `target_override` makes `target !=
  order_target` too) - see its own README and `docs/entity-glossary.md`'s
  "Order Target vs. Movement Target".
- `customers/example_customer/channels/inbound/` - a third scenario, on
  the inbound side: `inbound_advice` models an ASN (Avisierung - an
  announced, not-yet-arrived shipment) that, once goods receipt is
  confirmed, splits into putaway sub-orders per storage technology
  (`SPLIT_TO_AUTOSTORE_PUTAWAY` / `SPLIT_TO_MANUAL_PUTAWAY`), each
  triggering a `putaway_task`. `MARK_RECEIVED_AFTER_ALL_PUTAWAY` marks
  the ASN itself `completed` once every putaway sub-order is done. Both
  putaway rules also set `order_target_override` (see "Next Steps"),
  since the storage destination decided by the split *is* the sub-order's
  real final destination here, unlike outbound's fixed customer target.
  That these splits may only fire after goods receipt is confirmed used to
  be describable only in a comment; both rules now state it as
  `when.status: "receipt_confirmed"`, so it is enforced - see "Split
  Conditions" below.

## Core Concepts (Quick Reference)

- **order (header)** — one order/sub-order instance: identity, lineage
  (`parent_order_id`, `source_split_rule`), a `target`/`order_target`,
  and a `status`.
- **target** — the *movement target*: the destination this specific
  order/sub-order's executing system must physically reach (the next
  reachable hop). A reference to a `door`, `work_center`, or
  `activity_area` defined in `Topology-as-Code`. A sub-order's target
  can legitimately differ from its parent's (planned, via
  `split_rule.target_override`, or reactive, via
  `completion_rule.action.reallocate_remainder`).
- **order_target** — the immutable business destination, set once on
  the top-level order and inherited unchanged by every descendant
  sub-order. An order/sub-order is only truly fulfilled once its
  confirmed quantity is met **and** `target == order_target` - see
  `docs/entity-glossary.md`'s "Order Target vs. Movement Target".
- **position (line item)** — requests exactly one of a `load_unit_request`
  (a specific load unit), a `material_request` (item + quantity), or a
  `suborder_output_request` (the output of an already-completed
  sub-order - used on consolidation orders). Splitting never mutates the
  original position; it creates new positions on the sub-order(s)
  referencing the original via `source_line_id`.
- **split_rule** — defines whether/how an order is decomposed into
  sub-orders (`condition` references `elements/split_reasons.yaml` for the
  reason; `when` says when this particular rule applies - see "Split
  Conditions"; `target_override` sets a sub-order's target if different
  from the parent's). Independent of *which* workflow the result goes to (see
  `workflow_trigger`) - same separation of concerns as
  `Topology-as-Code`'s `lane` ("can") vs. `movement_rule` ("may").
- **workflow_trigger** — maps a `split_rule` outcome to the named
  downstream workflow/process it hands off to. Where that trigger is
  something a warehouse acts on, it should reference the *same*
  `process_type` id as `Topology-as-Code`'s `movement_rule.trigger`
  (e.g. `putaway_task`, `pick_task`, `cross_dock_task`) - see "Shared
  Vocabulary" below.
- **completion_rule** — defines what happens once sub-order(s) reach a
  given status: the parent's own status changes
  (`update_parent_status`), a new order is spawned once every piece is
  truly done (`spawn_order` - typically a consolidation order; set
  `action.supersedes_parent: true` to also move the parent to the
  reserved terminal `superseded` status, since a superseded parent isn't
  itself fulfilled), or the still-outstanding remainder is reactively
  re-split into a new sub-order (`reallocate_remainder`, via
  `when.target_gap` - covers a system falling short, failing, or only
  reaching an intermediate point instead of the order's real target). A
  rule fires **at most once per parent** - it does not re-arm if the set
  of children it watches changes later.
- **status** / state machine — the lifecycle an order or sub-order moves
  through, and which transitions are allowed. Every order/sub-order has
  its own independent position in the state machine - a sub-order
  reaching a terminal status does not by itself complete its parent.

Full glossary: [`docs/entity-glossary.md`](docs/entity-glossary.md)

## Split Conditions

A `split_rule` separates *why* an order is split from *when a particular
rule applies*:

```yaml
- id: "SPLIT_TO_AUTOSTORE_PUTAWAY"
  condition: "putaway_destination_split"   # the reason - shared by siblings
  split_by: "storage_technology"           # the dimension
  when:
    status: "receipt_confirmed"            # not decidable before goods receipt
    dimension_value: "autostore"           # the value THIS rule covers
```

`condition` alone could never distinguish rules: `b2c_standard`'s
`SPLIT_TO_AUTOSTORE` and `SPLIT_TO_MANUAL_WAREHOUSE` were identical in
every declared field, so only a runtime engine's hardcoded rule list could
tell which part of an order each was meant to handle (`WMS-POC` Finding
#1). `when.dimension_value` is what makes a set of split rules
dispatchable, and `tools/validate.py` requires siblings sharing a
`split_by` to declare distinct values.

`when.status` gates timing: omit it for splits decidable at intake (the
outbound case), state it for splits that depend on something having
physically happened.

**Why not an expression language.** A predicate like
`stock.storage_type == 'AUTOSTORE_GRID'` looks more powerful but could not
answer the actual question: which storage technology holds an item's stock
is live inventory state, which this repo family deliberately does not
model. The honest division is that the rule declares which value it
claims, and the runtime resolves what a given position's value actually
is. `when` therefore mirrors `completion_rule.when` - a small structured
object with enumerated fields - rather than introducing a parser. See
[`Warehouse-as-Code` ADR-0001](https://github.com/rhinos07/Warehouse-as-Code/blob/main/docs/adr/0001-layered-specification-model.md),
measure 4.

`dimension_value` is a free string rather than a catalog field: the value
space differs per dimension, and inventing a catalog per dimension before
a second dimension is in real use would be exactly the premature
generalisation this family avoids elsewhere. For the one dimension that
does have a real cross-repo anchor, use it: when `split_by` is
`storage_technology`, values should be ids from `Topology-as-Code`'s
`elements/storage_technologies.yaml` (`autostore`, `manual_warehouse`,
`shuttle`, `channel_storage`) - the same loosely-coupled, unchecked
string-id convention this repo already uses for `target.id` and
`material_request.item_id`. `b2c_multi_system`'s `SPLIT_TO_MANUAL_PICK_ZONE`
used to invent its own `"manual_pick"` instead of reusing
`manual_warehouse`; `WMS-POC` reading the real technology from
`Topology-as-Code` is what caught it. `tools/validate.py` does not check
this reference - no repo's does, for any cross-repo reference (see "Open
Validation Gaps" below).

## Split Dimensions

`split_rule.split_by` references `elements/split_dimensions.yaml` rather
than being a closed enum. The dimensions a business splits orders along are
open-ended - a new one is a catalog entry now instead of a schema change,
the same way `condition` already references `elements/split_reasons.yaml`.
See
[`Warehouse-as-Code` ADR-0001](https://github.com/rhinos07/Warehouse-as-Code/blob/main/docs/adr/0001-layered-specification-model.md),
measure 3.

The catalog ships with exactly the five values the enum had
(`storage_technology`, `fulfillment_location`, `carrier`, `promise_date`,
`item_category`) - no dimensions were invented ahead of a real scenario
needing one. `tools/validate.py` checks the reference.

Note this names the dimension only. Deciding which concrete sub-orders a
split produces remains runtime logic, because `split_rule.condition` is a
reason id rather than an evaluable predicate - see "Next Steps" and
ADR-0001 measure 4.

Structural enums stay closed: `completion_rule`'s `quantifier` and
`action.type` are grammar, not vocabulary.

## Shared Vocabulary with Topology-as-Code

`workflow_trigger` values that hand off to the warehouse should reuse the
*same* `process_type` catalog that `Topology-as-Code`'s
`movement_rule.trigger` references, rather than inventing a parallel set
of names. Right now that catalog (`elements/process_types.yaml`) lives
inside `Topology-as-Code` and would need to be duplicated here or
extracted into a small shared repo both projects reference. The same
applies to `order-position.schema.json`'s `load_unit_request.load_unit_type`
(currently referencing `Topology-as-Code`'s `elements/load_unit_types.yaml`,
itself flagged as a candidate to move to `MasterData-as-Code`), and to
`split_rule.when.dimension_value` when `split_by` is `storage_technology`
(references `Topology-as-Code`'s `elements/storage_technologies.yaml` -
see "Split Conditions" above). **Don't solve this prematurely** - start
with a duplicated/local copy here, and only extract a shared catalog repo
once the duplication actually causes real drift or pain.

## Next Steps for This Repo

- [x] ~~**Fix the completion_rule re-fire / parent-completion gap**
      (found while building `examples/order_walkthrough/`): once a
      spawned consolidation order also reaches the watched status, it's
      indistinguishable from the original split children, so (a) nothing
      marks the top-level order itself as done, and (b) the same
      `completion_rule` could fire again and spawn a second consolidation
      order.~~ - fixed as two separate things, confirmed by actually
      reproducing (b) against `WMS-POC`'s engine with its re-fire guard
      removed: a `reallocate_remainder`-created sibling sharing a
      `source_split_rule` with an already-counted child was enough to
      make `all_children` match a second time - `source_split_rules`
      alone doesn't prevent this, since the new sibling's origin id is
      one it's already scoped to. (a) `action.supersedes_parent` (new,
      required when `type: spawn_order`) transitions the parent to a
      reserved terminal `superseded` status when true - `b2c_standard`'s
      `CONSOLIDATE_AFTER_BOTH_SUBORDERS` sets it, and
      `structure/status.yaml` now has that status and a transition to it;
      `tools/validate.py` checks both exist whenever a rule declares
      `supersedes_parent: true`. (b) `completion-rule.schema.json` now
      states normatively that a rule fires **at most once per parent** -
      formalizing what `WMS-POC`'s `_fired_rules` guard already did as an
      undocumented workaround, rather than the `when.source` filter
      originally guessed at here (which already exists as
      `source_split_rules` and doesn't solve this specific case). See
      `examples/order_walkthrough/README.md` for the concrete case this
      was found in.
- [ ] Build out `MasterData-as-Code` far enough that `material_request.item_id`
      can be cross-checked against real item ids (not yet validated -
      `tools/validate.py` has no referential-integrity check against
      another repo's data)
- [ ] Decide the shared-vocabulary question above (duplicate vs. extract
      a shared catalog repo with `Topology-as-Code`/`MasterData-as-Code`)
- [ ] Add more order types / channels to `customers/example_customer/`
      (e.g. a `b2b_bulk` type, a `cross_dock` type)
- [ ] Consider a `sla_class` catalog (delivery-promise/priority
      classification) if/when split rules need to reference urgency
- [x] ~~**Give `split_rule` a trigger-status concept.** All existing splits
      implicitly assume the split is decidable at order intake. That's true
      for `b2c_standard` but not for inbound putaway, which can only split
      *after* the ASN reaches `receipt_confirmed`.~~ - fixed as
      `split_rule.when.status`, mirroring `completion_rule.when` as
      suggested. `inbound_advice`'s two putaway rules now state
      `receipt_confirmed`, so the precondition is enforced rather than
      described in a comment. See "Split Conditions" above.
- [x] ~~**Give `split_rule.condition` real semantics.** `condition` names a
      reason, not a predicate - nothing said which rule applied to a given
      order, so two sibling rules could be identical in every declared
      field (`WMS-POC` Finding #1).~~ - fixed as `split_rule.when`, which
      splits the reason (`condition`, shared by siblings) from what
      actually distinguishes and gates a rule. `when.dimension_value`
      declares which value of `split_by` each rule claims, and
      `tools/validate.py` requires siblings sharing a `split_by` to be
      distinguishable. Deliberately not an expression language - see
      "Split Conditions" above for why one would not have helped.
- [x] ~~Let a split optionally override `order_target`, not just
      `target`~~ - fixed: `split-rule.schema.json` gained an optional
      `order_target_override`, sibling to `target_override`, for the
      cases (like inbound putaway) where the split's destination *is*
      the new final destination rather than an intermediate hop.
      `inbound_advice`'s two putaway rules set it to the same
      `activity_area` as their `target_override`, so `target ==
      order_target` genuinely holds once a putaway sub-order completes -
      see `customers/example_customer/channels/inbound/.../strategies/split_rules.yaml`.
      Outbound rules (`b2c_standard`, `b2c_multi_system`) are unaffected -
      omitting the field keeps `order_target` immutable, as before.
- [x] ~~`completion_rule` can't scope itself to a specific `split_rule`'s
      children~~ - fixed at the schema level:
      `completion-rule.schema.json`'s `when` gained an optional
      `source_split_rules` (list of `split_rule` ids) - a rule now only
      considers children created by those specific rules. Applied to
      every existing `completion_rule` (`CONSOLIDATE_AFTER_BOTH_SUBORDERS`,
      `REALLOCATE_SHUTTLE_TARGET_GAP`, `MARK_RECEIVED_AFTER_ALL_PUTAWAY`)
      as defense in depth, even where splitting `b2c_standard`/
      `b2c_multi_system` apart already prevents the concrete collision
      that surfaced this. `tools/validate.py` cross-checks the ids
      against `split_rules.yaml`.
- [ ] `channel.schema.json` is titled "Sales Channel" but
      `customers/example_customer/channels/inbound/` isn't one - it
      reuses the same grouping level for identity purposes only. Rename
      the concept (e.g. to a neutral "Order Source") once a second
      non-sales use case confirms the pattern, rather than guessing now.

### Open Validation Gaps

`tools/validate.py` checks structural cross-references *within* this
repo (e.g. `split_rule.condition` → `elements/split_reasons.yaml`,
`completion_rule.when.status` → `structure/status.yaml`). It does
**not** check references that cross repo boundaries (`target.id` →
an actual `Topology-as-Code` door/work_center/activity_area id,
`material_request.item_id` → an actual `MasterData-as-Code` item,
`load_unit_request.load_unit_type` → `Topology-as-Code`'s
`elements/load_unit_types.yaml`) - same category of gap
`Topology-as-Code` itself started with before cross-file checks were
added there.

`tools/validate_examples.py` only checks each order instance and its
positions against the canonical schemas in isolation. It does **not**
check instance-level consistency across a set of example files - e.g.
that `source_line_id`/`source_order_id`/`parent_order_id` references
actually resolve to another file in the same walkthrough, or that a
`split_rule`'s `target_override` was applied correctly to the resulting
sub-order. `examples/order_walkthrough/` is hand-verified against
`docs/entity-glossary.md`'s narrative for now.

### Out of Scope (By Design)

- **Runtime state**: actual live orders, their current status, real
  quantities/dates, waves, warehouse tasks - these live in the OMS/WMS
  runtime database (KCC), not here.
- **Item/article master data**: SKUs, batches, UOM conversions - that's
  `MasterData-as-Code`.
- **Warehouse structure and movement rules**: physical layout,
  storage_types, `movement_rules.yaml` - that's `Topology-as-Code`.
  This repo only decides *which* workflow trigger fires; what that
  trigger physically does inside a warehouse is `Topology-as-Code`'s
  concern.
- **Labor management, yard management** - same reasoning as
  `Topology-as-Code`'s own exclusions.
