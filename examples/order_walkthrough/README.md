# Order Walkthrough Example

Illustrative order instances for `customers/example_customer`'s
`b2c_standard` order type - **not** structural config, **not** real
runtime data. Shows what an actual order looks like in the
header/position shape as it moves through split → workflow trigger →
completion → consolidation, exactly the scenario narrated in
[`docs/entity-glossary.md`](../../docs/entity-glossary.md) under
"Splitting and Completion".

Validate with:
```bash
python tools/validate_examples.py examples/order_walkthrough
```

## The flow

```
01_original_order.yaml        ORD-1001, target=DOOR_02
  L1: 2x ITEM_SMALL_GADGET (stored in the AutoStore cell)
  L2: 1x ITEM_BULKY_LAMP    (stored in the manual warehouse)

        │ split_rule: SPLIT_TO_AUTOSTORE           split_rule: SPLIT_TO_MANUAL_WAREHOUSE
        ▼                                          ▼
02_suborder_autostore.yaml                03_suborder_manual.yaml
  ORD-1001-A, target=EXIT (work_center)      ORD-1001-B, target=DOOR_02 (inherited)
  L1-A (source_line_id: L1)                  L2-B (source_line_id: L2)
  status: completed                          status: completed

        └──────────────┬───────────────────────────┘
                        │ completion_rule: CONSOLIDATE_AFTER_BOTH_SUBORDERS
                        │ (when: status=completed, quantifier=all_children)
                        ▼
        04_consolidation_order.yaml
          ORD-1001-C, target=DOOR_02 (spawn_target)
          C1: suborder_output_request -> ORD-1001-A
          C2: suborder_output_request -> ORD-1001-B
          status: completed
```

Note what's preserved throughout: `01_original_order.yaml`'s positions
`L1`/`L2` are never touched - every downstream position (`L1-A`, `L2-B`)
is a *new* position referencing the original via `source_line_id`, so
the original order always shows what was actually ordered.

## A gap this example surfaced

Building this concrete walkthrough exposed something the schema doesn't
yet handle: **who marks `ORD-1001` itself as done, and how do we stop
`CONSOLIDATE_AFTER_BOTH_SUBORDERS` from firing a second time?**

`ORD-1001-C` is also a child of `ORD-1001` (`parent_order_id:
"ORD-1001"`). Once it reaches `completed`:

1. Nothing currently updates `ORD-1001`'s own status - there's no
   `completion_rule` watching for *the consolidation order specifically*
   reaching a terminal status.
2. Worse: `CONSOLIDATE_AFTER_BOTH_SUBORDERS`'s own condition
   (`status: completed`, `quantifier: all_children`) would now also
   match again, since ORD-1001's children are `A`, `B`, *and* `C`, all
   completed - which would incorrectly try to `spawn_order` a *second*
   consolidation order.

`completion_rule.when` has no way yet to distinguish "the children
created by split_rules X/Y" from "the child a completion_rule itself
spawned". See the repo's "Open Validation Gap" / "Next Steps" in the
main README for the proposed fix (a `when.source` filter) - deliberately
left as an open question rather than silently designed around.
