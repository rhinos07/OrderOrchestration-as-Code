#!/usr/bin/env python3
"""
Validates illustrative order-instance examples under examples/ against
the canonical order-header.schema.json / order-position.schema.json -
distinct from tools/validate.py, which validates structural customer
config (company/channel/order_type cascade), not instance data.

These examples are NOT structural config and NOT real runtime data -
see examples/order_walkthrough/README.md.

Usage:
    python tools/validate_examples.py examples/order_walkthrough
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import load_yaml, make_validator  # noqa: E402


def validate_example_file(path: Path) -> list[str]:
    errors = []
    data = load_yaml(path)
    if data is None:
        return [f"{path}: File is empty or invalid."]

    header_validator = make_validator("order-header.schema.json")
    order = data.get("order", {})
    for err in header_validator.iter_errors(order):
        loc = " -> ".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{path}: order [{loc}] {err.message}")

    position_validator = make_validator("order-position.schema.json")
    for i, position in enumerate(data.get("positions", [])):
        for err in position_validator.iter_errors(position):
            loc = " -> ".join(str(p) for p in err.absolute_path) or "(root)"
            errors.append(f"{path}: positions[{i}] [{loc}] {err.message}")

    return errors


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(argv) != 2:
        print("Usage: python tools/validate_examples.py <directory-of-order-instance-yaml>")
        return 2

    target_dir = Path(argv[1]).resolve()
    if not target_dir.is_dir():
        print(f"Not a directory: {target_dir}")
        return 2

    all_errors: list[str] = []
    files = sorted(target_dir.glob("*.yaml"))
    if not files:
        print(f"No .yaml files found in {target_dir}")
        return 2

    for f in files:
        all_errors += validate_example_file(f)

    if all_errors:
        print(f"❌ {len(all_errors)} validation errors found:\n")
        for e in all_errors:
            print(f"  - {e}")
        return 1

    print(f"✅ {len(files)} example order instance(s) validated successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
