# Multi-System Reallocation Walkthrough

Illustrative order instances for `customers/example_customer`'s
`b2c_standard` order type - **not** structural config, **not** real
runtime data. Works through the "multi-system outbound fulfillment"
scenario from [`docs/entity-glossary.md`](../../docs/entity-glossary.md)
("Order Target vs. Movement Target"): one order line has to be
fulfilled across multiple sub-warehouse systems with different physical
reach, and a system that can only move goods part-way to the order's
real destination triggers a *reactive* re-split, not a planned one.

Validate with:
```bash
python tools/validate_examples.py examples/multi_system_reallocation_walkthrough
```

## The flow

```
01_original_order.yaml        ORD-2001, target=order_target=GATE_3
  L1: 50x ITEM_WIDGET

        │ split_rule: SPLIT_TO_SHUTTLE_ZONE     split_rule: SPLIT_TO_MANUAL_PICK_ZONE
        ▼                                       ▼
02_suborder_shuttle.yaml                03_suborder_manualpick.yaml
  ORD-2001-A, qty 30                      ORD-2001-B, qty 20
  target=CONSOLIDATION_1 (override)       target=GATE_3 (inherited)
  order_target=GATE_3                     order_target=GATE_3
  status: completed                       status: completed
  target != order_target -> target_gap    target == order_target -> DONE

        │ completion_rule: REALLOCATE_SHUTTLE_TARGET_GAP
        │ (when: status=completed, quantifier=any_child, target_gap=true)
        ▼
04_suborder_reallocated.yaml
  ORD-2001-C
  target=order_target=GATE_3
  L1-C: suborder_output_request -> ORD-2001-A (take its 30 units)
  status: completed -> target == order_target -> DONE
```

`ORD-2001` closes once every leaf whose `target == order_target` sums
to the original line's requested quantity: `ORD-2001-B` (20) +
`ORD-2001-C` (30) = 50.

## Why this needed a schema change

Before this scenario, `target` on an order/sub-order header served two
jobs at once: "the next reachable hop for this sub-order's system" and
"whether the order is really done". That conflation works for a single
planned split (see `examples/order_walkthrough/`, where the AutoStore
sub-order's target is a *known-upfront* override), but not for a
system that only discovers its own reach gap *after* confirming
quantity, or for a shortfall/failure discovered at runtime.

`order-header.schema.json` now separates the two:

- **`target`** - the movement target: this order/sub-order's own next
  reachable hop, optionally overridden per sub-order (`split_rule.target_override`).
- **`order_target`** - the immutable business destination, inherited
  unchanged by every descendant no matter how many times the demand is
  split or re-split.

`completion-rule.schema.json` gained `when.target_gap` (fires when a
watched child confirmed its quantity but `target != order_target`) and
action type `reallocate_remainder` (spawns a new sub-order for the
outstanding remainder, inheriting `order_target` unchanged - no static
target is declared for it, since *how* the gap gets closed is a
runtime allocation/routing decision). `order-position.schema.json`'s
`suborder_output_request` is no longer described as consolidation-only,
since `ORD-2001-C` uses it the same way a consolidation order does:
"take what that sub-order produced," just re-targeted rather than
merged with a sibling.

The same mechanism (`target_gap` + `reallocate_remainder`) also covers
a system falling short on quantity or failing outright - both would be
modeled as another `completion_rule` watching a different status (or
the same status with a different condition), spawning a
`reallocate_remainder` sub-order for whatever quantity is still
missing. Not built out as a separate example here since the shape is
identical to the target-gap case above; only the trigger condition
differs.
