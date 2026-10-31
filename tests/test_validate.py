"""Unit tests for tools/validate.py: the within-repo consistency checks of
an order type (status machine, split rules, workflow triggers, completion
rules, shortage policy) and the end-to-end example customer."""

import unittest

from helpers import REPO_ROOT, TempDirMixin, write_yaml

from validate import (  # noqa: E402
    allowed_shortage_policies,
    check_completion_rule_refs,
    check_shortage_policy,
    check_split_rule_refs,
    check_split_rule_when,
    check_status_refs,
    check_workflow_trigger_refs,
    collect_element_ids,
    make_validator,
    validate_company_file,
)

STATUS = {
    "statuses": [
        {"id": "created"}, {"id": "completed", "terminal": True},
        {"id": "superseded", "terminal": True},
    ],
    "transitions": [
        {"from": "created", "to": "completed"},
        {"from": "created", "to": "superseded"},
    ],
}


class ExampleCustomerTest(unittest.TestCase):
    def test_example_customer_is_valid(self):
        company = REPO_ROOT / "customers" / "example_customer" / "company.yaml"
        self.assertEqual(validate_company_file(company, collect_element_ids()), [])


class StatusTest(TempDirMixin, unittest.TestCase):
    def test_unknown_transition_status_is_reported(self):
        path = write_yaml(self.tmp, "status.yaml", {
            "statuses": [{"id": "created"}],
            "transitions": [{"from": "created", "to": "shipped"}],
        })
        errors = check_status_refs(path)
        self.assertTrue(any("'shipped'" in e for e in errors), errors)

    def test_valid_status_machine_passes(self):
        self.assertEqual(check_status_refs(write_yaml(self.tmp, "status.yaml", STATUS)), [])


class SplitRuleTest(TempDirMixin, unittest.TestCase):
    ELEMENTS = {"split_reasons": {"storage_technology_split"}, "split_dimensions": {"storage_technology"}}

    def rules(self, *rules):
        return write_yaml(self.tmp, "split_rules.yaml", {"split_rules": list(rules)})

    def test_unknown_catalog_refs_are_reported(self):
        path = self.rules({"id": "S1", "condition": "nope", "split_by": "colour"})
        errors = check_split_rule_refs(path, self.ELEMENTS)
        self.assertEqual(len(errors), 2, errors)

    def test_siblings_need_distinct_dimension_values(self):
        path = self.rules(
            {"id": "A", "split_by": "storage_technology", "when": {"dimension_value": "autostore"}},
            {"id": "B", "split_by": "storage_technology", "when": {"dimension_value": "autostore"}},
            {"id": "C", "split_by": "storage_technology"},
        )
        errors = check_split_rule_when(path, STATUS)
        self.assertTrue(any("already claimed" in e for e in errors), errors)
        self.assertTrue(any("'C'" in e and "required" in e for e in errors), errors)

    def test_single_rule_needs_no_dimension_value(self):
        path = self.rules({"id": "A", "split_by": "storage_technology"})
        self.assertEqual(check_split_rule_when(path, STATUS), [])

    def test_unknown_when_status_is_reported(self):
        path = self.rules({"id": "A", "split_by": "storage_technology", "when": {"status": "receipt_confirmed"}})
        self.assertTrue(any("when.status" in e for e in check_split_rule_when(path, STATUS)))


class WorkflowTriggerTest(TempDirMixin, unittest.TestCase):
    def test_unknown_split_rule_is_reported(self):
        path = write_yaml(self.tmp, "workflow_triggers.yaml", {
            "workflow_triggers": [{"id": "T1", "split_rule": "MISSING", "trigger": "pick_task"}],
        })
        errors = check_workflow_trigger_refs(path, {"split_rules": [{"id": "S1"}]})
        self.assertTrue(any("'MISSING'" in e for e in errors), errors)


class CompletionRuleTest(TempDirMixin, unittest.TestCase):
    SPLITS = {"split_rules": [{"id": "S1"}]}

    def rule(self, **overrides):
        rule = {
            "id": "C1",
            "when": {"status": "completed", "quantifier": "all_children"},
            "action": {"type": "update_parent_status", "new_status": "completed"},
        }
        rule.update(overrides)
        return write_yaml(self.tmp, "completion_rules.yaml", {"completion_rules": [rule]})

    def test_valid_rule_passes(self):
        self.assertEqual(check_completion_rule_refs(self.rule(), STATUS, self.SPLITS), [])

    def test_unknown_refs_are_reported(self):
        path = self.rule(
            when={"status": "gone", "quantifier": "any_child", "source_split_rules": ["S9"]},
            action={"type": "update_parent_status", "new_status": "lost"},
        )
        errors = check_completion_rule_refs(path, STATUS, self.SPLITS)
        self.assertEqual(len(errors), 3, errors)

    def test_supersedes_parent_needs_reachable_superseded_status(self):
        path = self.rule(action={
            "type": "spawn_order", "spawn_order_type": "x",
            "spawn_target": {"type": "door", "id": "D"}, "supersedes_parent": True,
        })
        no_status = {"statuses": [{"id": "created"}, {"id": "completed"}], "transitions": []}
        self.assertTrue(any("no 'superseded' status" in e for e in check_completion_rule_refs(path, no_status, self.SPLITS)))
        unreachable = {"statuses": STATUS["statuses"], "transitions": [{"from": "created", "to": "completed"}]}
        self.assertTrue(any("no transition" in e for e in check_completion_rule_refs(path, unreachable, self.SPLITS)))
        self.assertEqual(check_completion_rule_refs(path, STATUS, self.SPLITS), [])

    def test_schema_requires_n_for_n_of_m(self):
        validator = make_validator("completion-rule.schema.json")
        rule = {"id": "C1", "when": {"status": "completed", "quantifier": "n_of_m"},
                "action": {"type": "update_parent_status", "new_status": "completed"}}
        self.assertTrue(list(validator.iter_errors(rule)))


class ShortagePolicyTest(TempDirMixin, unittest.TestCase):
    def test_override_repeating_default_is_rejected(self):
        path = write_yaml(self.tmp, "shortage_policy.yaml", {
            "shortage_policy": {"default": "backorder", "allowed_overrides": ["backorder"]},
        })
        self.assertTrue(check_shortage_policy(path))

    def test_schema_rejects_unknown_policy(self):
        validator = make_validator("shortage-policy.schema.json")
        self.assertTrue(list(validator.iter_errors({"shortage_policy": {"default": "later"}})))

    def test_allowed_policies_include_default_and_overrides(self):
        write_yaml(self.tmp, "strategies/shortage_policy.yaml", {
            "shortage_policy": {"default": "backorder", "allowed_overrides": ["ship_partial"]},
        })
        order_type = write_yaml(self.tmp, "order_type.yaml", {
            "order_type": {"id": "x", "imports": ["strategies/shortage_policy.yaml"]},
        })
        self.assertEqual(allowed_shortage_policies(order_type), {"backorder", "ship_partial"})

    def test_no_policy_means_none(self):
        order_type = write_yaml(self.tmp, "order_type.yaml", {"order_type": {"id": "x", "imports": []}})
        self.assertIsNone(allowed_shortage_policies(order_type))


if __name__ == "__main__":
    unittest.main()
