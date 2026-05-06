#!/usr/bin/env python3
"""Normalize prop aliases in record JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from novel2video_plan import active_record_prop_ids, canonical_prop_id, canonicalize_record_props


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iter_record_paths(records_dir: Path, shots: set[str]) -> list[Path]:
    paths = sorted(records_dir.glob("*_record.json"))
    if not shots:
        return paths
    return [path for path in paths if any(path.name.endswith(f"{shot}_record.json") for shot in shots)]


def prop_id_map_before(record: dict[str, Any]) -> dict[str, str]:
    record_context = json.dumps(record, ensure_ascii=False)
    out: dict[str, str] = {}
    for prop_id in sorted(active_record_prop_ids(record)):
        canonical_id = canonical_prop_id(prop_id, prop_id, record_context)
        if canonical_id != prop_id:
            out[prop_id] = canonical_id
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize duplicate/alias prop ids in record JSON files.")
    parser.add_argument("--records-dir", required=True)
    parser.add_argument("--shots", default="", help="Comma-separated shot ids, e.g. SH01,SH02. Defaults to all records.")
    parser.add_argument("--write", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records_dir = Path(args.records_dir).expanduser().resolve()
    shots = {item.strip() for item in args.shots.split(",") if item.strip()}
    report: dict[str, Any] = {
        "records_dir": str(records_dir),
        "write": args.write,
        "files": [],
    }
    for path in iter_record_paths(records_dir, shots):
        before = read_json(path)
        before_map = prop_id_map_before(before)
        after = canonicalize_record_props(json.loads(json.dumps(before, ensure_ascii=False)))
        after_map = prop_id_map_before(after)
        changed = before != after
        report["files"].append(
            {
                "path": str(path),
                "changed": changed,
                "before_aliases": before_map,
                "after_aliases": after_map,
                "active_props": sorted(active_record_prop_ids(after)),
            }
        )
        if args.write and changed:
            write_json(path, after)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
