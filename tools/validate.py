#!/usr/bin/env python3
"""
Validates a company.yaml, channel.yaml, or order_type.yaml (and everything
it references, cascading down the Company -> Channel -> Order Type
hierarchy) against the JSON schemas in schemas/ and runs cross-file
consistency checks.

Usage:
    python tools/validate.py customers/example_customer/company.yaml
    python tools/validate.py customers/example_customer/channels/web/channel.yaml
    python tools/validate.py customers/example_customer/channels/web/order_types/b2c_standard/order_type.yaml

Any of the three levels can be passed directly; validation cascades
downward from whichever level you start at.
"""

import sys
import json
from pathlib import Path

import yaml
from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"
ELEMENTS_DIR = REPO_ROOT / "elements"

ELEMENT_CATALOGS = {
    "split_reasons.yaml": ("split-reason.schema.json", "split_reasons"),
}


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_schema(name: str) -> dict:
    with open(SCHEMA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_schema_registry() -> Registry:
    """Pre-load all local schemas into a referencing.Registry, keyed by
    their $id, so cross-file $ref (e.g. split-rule.schema.json ->
    order-header.schema.json#/definitions/target) resolves correctly."""
    resources = []
    for schema_file in SCHEMA_DIR.glob("*.json"):
        schema_data = json.loads(schema_file.read_text(encoding="utf-8"))
        uri = schema_data.get("$id") or f"{SCHEMA_DIR.as_uri()}/{schema_file.name}"
        resources.append((uri, Resource.from_contents(schema_data, default_specification=DRAFT7)))
    return Registry().with_resources(resources)


SCHEMA_REGISTRY: Registry = _build_schema_registry()


def make_validator(schema_name: str) -> Draft7Validator:
    schema = load_schema(schema_name)
    return Draft7Validator(schema, registry=SCHEMA_REGISTRY)


def collect_imports(order_type_file: Path) -> list[Path]:
    data = load_yaml(order_type_file)
    imports = data.get("order_type", {}).get("imports", [])
    base_dir = order_type_file.parent
    return [base_dir / rel for rel in imports]


def collect_relative_refs(path: Path, root_key: str, list_key: str) -> list[Path]:
    data = load_yaml(path)
    refs = data.get(root_key, {}).get(list_key, [])
    base_dir = path.parent
    return [base_dir / rel for rel in refs]


def validate_file(path: Path, schema_name: str) -> list[str]:
    errors = []
    data = load_yaml(path)
    if data is None:
        return [f"{path}: File is empty or invalid."]

    validator = make_validator(schema_name)
    for err in validator.iter_errors(data):
        loc = " -> ".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{path}: [{loc}] {err.message}")
    return errors


def validate_list_items(path: Path, schema_name: str, list_key: str) -> list[str]:
    """Validates each item in data[list_key] against schema_name (item-level
    schema, not a wrapper). Used for split_rules.yaml / workflow_triggers.yaml /
    completion_rules.yaml, mirroring how Warehouse-as-Code validates
    storage_types/movement_rules per-item."""
    errors = []
    data = load_yaml(path)
    if data is None:
        return [f"{path}: File is empty or invalid."]

    validator = make_validator(schema_name)
    for item in data.get(list_key, []):
        for err in validator.iter_errors(item):
            errors.append(f"{path}: {list_key} '{item.get('id', '?')}': {err.message}")
    return errors


def collect_element_ids() -> dict[str, set[str]]:
    """Loads all element catalogs and returns a mapping of list_key -> set
    of known IDs. Missing catalog files are silently skipped."""
    ids: dict[str, set[str]] = {}
    for filename, (_schema_name, list_key) in ELEMENT_CATALOGS.items():
        catalog_file = ELEMENTS_DIR / filename
        if catalog_file.exists():
            data = load_yaml(catalog_file)
            if data:
                ids[list_key] = {
                    item.get("id") for item in data.get(list_key, []) if item.get("id")
                }
    return ids


def validate_element_catalog(path: Path, schema_name: str, list_key: str) -> list[str]:
    errors = []
    data = load_yaml(path)
    if data is None:
        return [f"{path}: File is empty or invalid."]
    validator = make_validator(schema_name)
    for item in data.get(list_key, []):
        for err in validator.iter_errors(item):
            errors.append(f"{path}: {list_key} '{item.get('id', '?')}': {err.message}")
    return errors


def check_status_refs(path: Path) -> list[str]:
    """Checks that status.yaml's transitions[].from/to reference declared
    statuses[].id, within the same file."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data:
        return errors

    status_ids = {s.get("id") for s in data.get("statuses", []) if s.get("id")}
    for i, trans in enumerate(data.get("transitions", [])):
        for field in ("from", "to"):
            ref = trans.get(field)
            if ref and ref not in status_ids:
                errors.append(
                    f"{path}: transitions[{i}].{field} '{ref}' not found in statuses"
                )
    return errors


def check_split_rule_refs(path: Path, element_ids: dict[str, set[str]]) -> list[str]:
    """Checks split_rules.yaml's condition -> elements/split_reasons.yaml id."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data:
        return errors

    reason_ids = element_ids.get("split_reasons", set())
    for rule in data.get("split_rules", []):
        rule_id = rule.get("id", "?")
        cond = rule.get("condition")
        if cond and reason_ids and cond not in reason_ids:
            errors.append(
                f"{path}: split_rule '{rule_id}': condition '{cond}' not found in elements/split_reasons.yaml"
            )
    return errors


def check_workflow_trigger_refs(path: Path, split_rules_data: dict | None) -> list[str]:
    """Checks workflow_triggers.yaml's split_rule -> split_rules.yaml id,
    within the same order_type."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data:
        return errors

    split_rule_ids = {
        r.get("id") for r in (split_rules_data or {}).get("split_rules", []) if r.get("id")
    }
    for trig in data.get("workflow_triggers", []):
        trig_id = trig.get("id", "?")
        ref = trig.get("split_rule")
        if ref and split_rule_ids and ref not in split_rule_ids:
            errors.append(
                f"{path}: workflow_trigger '{trig_id}': split_rule '{ref}' not found in strategies/split_rules.yaml"
            )
    return errors


def check_completion_rule_refs(path: Path, status_data: dict | None, split_rules_data: dict | None) -> list[str]:
    """Checks completion_rules.yaml's when.status / action.new_status ->
    status.yaml statuses id, and when.source_split_rules -> split_rules.yaml
    ids, within the same order_type."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data:
        return errors

    status_ids = {s.get("id") for s in (status_data or {}).get("statuses", []) if s.get("id")}
    split_rule_ids = {r.get("id") for r in (split_rules_data or {}).get("split_rules", []) if r.get("id")}
    for rule in data.get("completion_rules", []):
        rule_id = rule.get("id", "?")
        when = rule.get("when") or {}
        watched = when.get("status")
        if watched and status_ids and watched not in status_ids:
            errors.append(
                f"{path}: completion_rule '{rule_id}': when.status '{watched}' not found in structure/status.yaml"
            )

        for source_rule_id in when.get("source_split_rules", []):
            if split_rule_ids and source_rule_id not in split_rule_ids:
                errors.append(
                    f"{path}: completion_rule '{rule_id}': when.source_split_rules '{source_rule_id}' not found in strategies/split_rules.yaml"
                )

        action = rule.get("action") or {}
        new_status = action.get("new_status")
        if new_status and status_ids and new_status not in status_ids:
            errors.append(
                f"{path}: completion_rule '{rule_id}': action.new_status '{new_status}' not found in structure/status.yaml"
            )
    return errors


def validate_order_type_file(order_type_file: Path, element_ids: dict[str, set[str]] = {}) -> list[str]:
    """Validates a single order-type-level order_type.yaml and everything it imports."""
    if not order_type_file.exists():
        return [f"order_type file missing: {order_type_file}"]

    all_errors = validate_file(order_type_file, "order-type.schema.json")

    imports: dict[str, Path] = {}
    for imported in collect_imports(order_type_file):
        if not imported.exists():
            all_errors.append(f"{order_type_file}: imported file missing: {imported}")
            continue

        imports[imported.name] = imported
        name = imported.name
        if name == "fields.yaml":
            all_errors += validate_file(imported, "fields.schema.json")
        elif name == "status.yaml":
            all_errors += validate_file(imported, "status.schema.json")
            all_errors += check_status_refs(imported)
        elif name == "split_rules.yaml":
            all_errors += validate_list_items(imported, "split-rule.schema.json", "split_rules")
            all_errors += check_split_rule_refs(imported, element_ids)
        elif name == "workflow_triggers.yaml":
            all_errors += validate_list_items(imported, "workflow-trigger.schema.json", "workflow_triggers")
        elif name == "completion_rules.yaml":
            all_errors += validate_list_items(imported, "completion-rule.schema.json", "completion_rules")
        else:
            data = load_yaml(imported)
            if data is None:
                all_errors.append(f"{imported}: File is empty or invalid.")

    # Cross-file checks within this order_type.
    split_rules_data = load_yaml(imports["split_rules.yaml"]) if "split_rules.yaml" in imports else {}
    status_data = load_yaml(imports["status.yaml"]) if "status.yaml" in imports else {}

    if "workflow_triggers.yaml" in imports:
        all_errors += check_workflow_trigger_refs(imports["workflow_triggers.yaml"], split_rules_data)

    if "completion_rules.yaml" in imports:
        all_errors += check_completion_rule_refs(imports["completion_rules.yaml"], status_data, split_rules_data)

    return all_errors


def validate_channel_file(channel_file: Path, element_ids: dict[str, set[str]] = {}) -> list[str]:
    """Validates a channel.yaml and cascades into every order_type it lists."""
    if not channel_file.exists():
        return [f"channel file missing: {channel_file}"]

    all_errors = validate_file(channel_file, "channel.schema.json")

    for order_type_file in collect_relative_refs(channel_file, "channel", "order_types"):
        all_errors += validate_order_type_file(order_type_file, element_ids)

    return all_errors


def validate_company_file(company_file: Path, element_ids: dict[str, set[str]] = {}) -> list[str]:
    """Validates a company.yaml and cascades into every channel it lists."""
    all_errors = validate_file(company_file, "company.schema.json")

    for channel_file in collect_relative_refs(company_file, "company", "channels"):
        all_errors += validate_channel_file(channel_file, element_ids)

    return all_errors


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(argv) != 2:
        print("Usage: python tools/validate.py <path-to-company|channel|order_type.yaml>")
        return 2

    target_file = Path(argv[1]).resolve()
    if not target_file.exists():
        print(f"File not found: {target_file}")
        return 2

    all_errors: list[str] = []

    for filename, (schema_name, list_key) in ELEMENT_CATALOGS.items():
        catalog_file = ELEMENTS_DIR / filename
        if catalog_file.exists():
            all_errors += validate_element_catalog(catalog_file, schema_name, list_key)

    element_ids = collect_element_ids()

    data = load_yaml(target_file)
    if data is None:
        all_errors.append(f"{target_file}: File is empty or invalid.")
    elif "company" in data:
        all_errors += validate_company_file(target_file, element_ids)
    elif "channel" in data:
        all_errors += validate_channel_file(target_file, element_ids)
    elif "order_type" in data:
        all_errors += validate_order_type_file(target_file, element_ids)
    else:
        all_errors.append(
            f"{target_file}: unrecognized root key (expected one of "
            f"'company', 'channel', 'order_type')."
        )

    if all_errors:
        print(f"❌ {len(all_errors)} validation errors found:\n")
        for e in all_errors:
            print(f"  - {e}")
        return 1

    print("✅ Validation successful.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
