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

## A gap this example surfaced - since fixed

Building this concrete walkthrough exposed something the schema didn't
yet handle: **who marks `ORD-1001` itself as done, and how do we stop
`CONSOLIDATE_AFTER_BOTH_SUBORDERS` from firing a second time?** Both are
fixed now; this section records what the gap actually was, since the
diagnosis mattered as much as the fix.

`ORD-1001-C` is also a child of `ORD-1001` (`parent_order_id:
"ORD-1001"`). Once it reaches `completed`, two things needed answering:

1. **Nothing updated `ORD-1001`'s own status.** Fixed:
   `CONSOLIDATE_AFTER_BOTH_SUBORDERS` now sets
   `action.supersedes_parent: true`, which moves `ORD-1001` to the
   reserved terminal `superseded` status (see `structure/status.yaml`) -
   it isn't itself fulfilled, it's replaced by `ORD-1001-C`.
2. **Could the same rule re-fire because `C` is a sibling too?** Turns
   out no, already: `CONSOLIDATE_AFTER_BOTH_SUBORDERS`'s
   `when.source_split_rules: ["SPLIT_TO_AUTOSTORE",
   "SPLIT_TO_MANUAL_WAREHOUSE"]` (added earlier as defense in depth, see
   main README) already excludes `ORD-1001-C` from `scoped_siblings` -
   it wasn't created by either split_rule, so it has no
   `source_split_rule` matching either id. The *real* remaining re-fire
   risk was narrower and different: a `reallocate_remainder`-created
   sibling that reuses an *already-scoped* `source_split_rule` id (the
   id of the child whose gap it's closing) would still make
   `all_children` match a second time, since `source_split_rules`
   filters by *which rule created a child*, not by *whether this
   specific child was already counted*. Fixed by formalizing that a
   `completion_rule` fires **at most once per parent**, full stop - see
   `completion-rule.schema.json`.
