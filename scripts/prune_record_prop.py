#!/usr/bin/env python3
"""Remove a stale prop id from record JSON files and leave a tombstone."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_dict(node: Any) -> dict[str, Any]:
    return node if isinstance(node, dict) else {}


def remove_library_prop(library: Any, prop_id: str) -> bool:
    if isinstance(library, dict) and prop_id in library:
        del library[prop_id]
        return True
    return False


def remove_contract_prop(contracts: Any, prop_id: str) -> tuple[Any, int]:
    if not isinstance(contracts, list):
        return contracts, 0
    kept: list[Any] = []
    removed = 0
    for item in contracts:
        if isinstance(item, dict) and str(item.get("prop_id") or "") == prop_id:
            removed += 1
            continue
        kept.append(item)
    return kept, removed


def remove_list_value(values: Any, prop_id: str) -> tuple[Any, int]:
    if not isinstance(values, list):
        return values, 0
    kept = [item for item in values if str(item) != prop_id]
    return kept, len(values) - len(kept)


def append_tombstone(
    record: dict[str, Any],
    prop_id: str,
    replacement: str,
    reason: str,
) -> None:
    i2v = record.setdefault("i2v_contract", {})
    if not isinstance(i2v, dict):
        record["i2v_contract"] = {}
        i2v = record["i2v_contract"]
    tombstone = {
        "prop_id": prop_id,
        "status": "removed_pollution",
        "reason": reason,
        "replacement": replacement,
    }
    existing = i2v.get("removed_prop_tombstones")
    tombstones = existing if isinstance(existing, list) else []
    if not any(isinstance(item, dict) and item.get("prop_id") == prop_id for item in tombstones):
        tombstones.append(tombstone)
    i2v["removed_prop_tombstones"] = tombstones


def prune_record(record: dict[str, Any], prop_id: str, replacement: str, reason: str) -> dict[str, Any]:
    changes: dict[str, Any] = {
        "prop_id": prop_id,
        "removed_libraries": [],
        "removed_contracts": [],
        "removed_lists": [],
    }

    if remove_library_prop(record.get("prop_library"), prop_id):
        changes["removed_libraries"].append("prop_library")
    root_contract, removed = remove_contract_prop(record.get("prop_contract"), prop_id)
    if removed:
        record["prop_contract"] = root_contract
        changes["removed_contracts"].append({"path": "prop_contract", "count": removed})

    i2v = ensure_dict(record.get("i2v_contract"))
    if i2v:
        if remove_library_prop(i2v.get("prop_library"), prop_id):
            changes["removed_libraries"].append("i2v_contract.prop_library")
        i2v_contract, removed = remove_contract_prop(i2v.get("prop_contract"), prop_id)
        if removed:
            i2v["prop_contract"] = i2v_contract
            changes["removed_contracts"].append({"path": "i2v_contract.prop_contract", "count": removed})

    first_frame = ensure_dict(record.get("first_frame_contract"))
    key_props, removed = remove_list_value(first_frame.get("key_props"), prop_id)
    if removed:
        first_frame["key_props"] = key_props
        changes["removed_lists"].append({"path": "first_frame_contract.key_props", "count": removed})

    scene_motion = ensure_dict(record.get("scene_motion_contract"))
    for key in ("static_props", "manipulated_props"):
        values, removed = remove_list_value(scene_motion.get(key), prop_id)
        if removed:
            scene_motion[key] = values
            changes["removed_lists"].append({"path": f"scene_motion_contract.{key}", "count": removed})

    if changes["removed_libraries"] or changes["removed_contracts"] or changes["removed_lists"]:
        append_tombstone(record, prop_id, replacement, reason)
    changes["changed"] = bool(changes["removed_libraries"] or changes["removed_contracts"] or changes["removed_lists"])
    return changes


def iter_record_paths(records_dir: Path, shots: set[str]) -> list[Path]:
    paths = sorted(records_dir.glob("*_record.json"))
    if not shots:
        return paths
    return [path for path in paths if any(path.name.endswith(f"{shot}_record.json") for shot in shots)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove a stale prop id from record JSON files.")
    parser.add_argument("--records-dir", required=True)
    parser.add_argument("--prop-id", required=True)
    parser.add_argument("--replacement", default="")
    parser.add_argument("--reason", default="Removed stale polluted prop from record source of truth.")
    parser.add_argument("--shots", default="", help="Comma-separated shot ids, e.g. SH01,SH02. Defaults to all records.")
    parser.add_argument("--write", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records_dir = Path(args.records_dir).expanduser().resolve()
    shots = {item.strip() for item in args.shots.split(",") if item.strip()}
    report: dict[str, Any] = {
        "records_dir": str(records_dir),
        "prop_id": args.prop_id,
        "replacement": args.replacement,
        "write": args.write,
        "files": [],
    }
    for path in iter_record_paths(records_dir, shots):
        record = read_json(path)
        changes = prune_record(record, args.prop_id, args.replacement, args.reason)
        report["files"].append({"path": str(path), **changes})
        if args.write and changes["changed"]:
            write_json(path, record)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
