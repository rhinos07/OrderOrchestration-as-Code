"""Tests for tools/validate_examples.py: the illustrative order instances
under examples/ match the header/position schemas, and an order's
shortage_policy override is allowed by its order type."""

import unittest

from helpers import REPO_ROOT

import validate_examples  # noqa: E402


class ExamplesTest(unittest.TestCase):
    def test_every_example_directory_is_valid(self):
        directories = sorted(p for p in (REPO_ROOT / "examples").iterdir() if p.is_dir())
        self.assertTrue(directories)
        for directory in directories:
            for path in sorted(directory.glob("*.yaml")):
                with self.subTest(example=path.name, directory=directory.name):
                    self.assertEqual(validate_examples.validate_example_file(path), [])

    def test_allowed_override_passes(self):
        order = {"order_type": "b2c_standard", "shortage_policy": "ship_partial"}
        self.assertEqual(validate_examples.check_order_shortage_policy(REPO_ROOT / "x.yaml", order), [])

    def test_disallowed_override_is_rejected(self):
        order = {"order_type": "b2c_standard", "shortage_policy": "hold"}
        errors = validate_examples.check_order_shortage_policy(REPO_ROOT / "x.yaml", order)
        self.assertTrue(any("not allowed" in e for e in errors), errors)

    def test_override_without_policy_is_rejected(self):
        order = {"order_type": "inbound_advice", "shortage_policy": "backorder"}
        errors = validate_examples.check_order_shortage_policy(REPO_ROOT / "x.yaml", order)
        self.assertTrue(any("declares no shortage_policy" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
