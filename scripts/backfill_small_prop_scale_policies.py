#!/usr/bin/env python3
"""Backfill scale policies for existing small handheld prop records.

Default mode is dry-run: it reports proposed changes without writing files.
Use --write to update records. This script intentionally never runs implicitly
from the generation flow, so historical records remain auditable.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import visual_asset_core as vac


GENERIC_SIZE_MARKERS = (
    "手持或桌面小道具尺寸",
    "符合现实比例",
    "现实比例",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iter_record_paths(records_dir: Path) -> list[Path]:
    if not records_dir.exists():
        raise FileNotFoundError(f"records dir not found: {records_dir}")
    return sorted(records_dir.glob("*.json"))


def weak_size(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or any(marker in text for marker in GENERIC_SIZE_MARKERS)


def default_size_for_prop(prop_id: str, display: str) -> str:
    combined = f"{prop_id} {display}"
    if "验孕棒" in combined or "PREGNANCY_TEST" in prop_id.upper():
        return "约12厘米长、2厘米宽、0.8厘米厚，手掌内的小型塑料测试条"
    if "戒指" in combined or "RING" in prop_id.upper():
        return "小型戒指，直径约2厘米，明显小于成人手掌"
    if "钥匙" in combined or "KEY" in prop_id.upper():
        return "小型钥匙，约5-7厘米长，明显小于成人手掌"
    if any(token in combined for token in ("药片", "药丸")) or any(token in prop_id.upper() for token in ("PILL", "MEDICINE")):
        return "小型药片或药丸，约0.5-2厘米，必须远小于成人手指"
    if any(token in combined for token in ("票", "票据", "纸条", "便签", "收据", "卡片")):
        return "小型纸质手持物，约手掌内或半掌大小，按剧情真实比例"
    return "现实小型手持道具尺寸，必须以成人手掌或桌面比例为准"


def apply_profile_backfill(prop_id: str, profile: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    display = str(profile.get("display_name") or profile.get("name") or prop_id).strip()

    def set_field(field: str, value: str, reason: str, replace_weak: bool = False) -> None:
        current = str(profile.get(field) or "").strip()
        should_set = not current or (replace_weak and weak_size(current))
        if should_set and current != value:
            profile[field] = value
            changes.append({"field": f"prop_library.{prop_id}.{field}", "before": current, "after": value, "reason": reason})

    set_field("reference_mode", "scale_context", "small handheld prop needs scale-context reference")
    set_field("size", default_size_for_prop(prop_id, display), "small handheld prop needs real relative size", replace_weak=True)
    set_field("scale_policy", vac.default_scale_policy(display or prop_id), "small handheld prop needs relative scale policy")
    set_field(
        "reference_context_policy",
        vac.default_reference_context_policy(display or prop_id),
        "scale-context reference needs hand/body/table anchors",
    )
    return changes


def apply_contract_backfill(prop_id: str, contract: dict[str, Any], display: str) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    current = str(contract.get("visibility_policy") or "").strip()
    if not current or ("清晰" in current and "不能通过放大" not in current and "不得把" not in current):
        value = f"{display or prop_id}必须按剧情可辨，但不能通过放大道具实现；不得变成前景大物，人物脸、动作和情绪仍是主体"
        contract["visibility_policy"] = value
        changes.append(
            {
                "field": f"prop_contract.{prop_id}.visibility_policy",
                "before": current,
                "after": value,
                "reason": "visibility must not encourage oversized prop close-up",
            }
        )
    return changes


def backfill_library_and_contracts(library: Any, contracts: Any) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    if not isinstance(library, dict) or not isinstance(contracts, list):
        return changes
    contract_by_id = {
        str(item.get("prop_id") or "").strip(): item
        for item in contracts
        if isinstance(item, dict) and str(item.get("prop_id") or "").strip()
    }
    for prop_id, profile in library.items():
        if not isinstance(profile, dict):
            continue
        contract = contract_by_id.get(str(prop_id), {})
        if not vac.is_small_handheld_prop(str(prop_id), profile, contract):
            continue
        changes.extend(apply_profile_backfill(str(prop_id), profile, contract if isinstance(contract, dict) else {}))
        if isinstance(contract, dict):
            display = str(profile.get("display_name") or profile.get("name") or prop_id).strip()
            changes.extend(apply_contract_backfill(str(prop_id), contract, display))
    return changes


def backfill_record(record: dict[str, Any]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    changes.extend(backfill_library_and_contracts(record.get("prop_library"), record.get("prop_contract")))
    i2v = record.get("i2v_contract")
    if isinstance(i2v, dict):
        changes.extend(backfill_library_and_contracts(i2v.get("prop_library"), i2v.get("prop_contract")))
    return changes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill scale_context policies for existing small handheld prop records.")
    parser.add_argument("--records-dir", required=True, help="Primary records directory to inspect.")
    parser.add_argument(
        "--static-records-dir",
        default="",
        help="Optional keyframe static records directory to backfill with the same policy.",
    )
    parser.add_argument("--write", action="store_true", help="Write changes. Omit for dry-run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dirs = [Path(args.records_dir).expanduser()]
    if args.static_records_dir.strip():
        dirs.append(Path(args.static_records_dir).expanduser())

    report: dict[str, Any] = {
        "mode": "write" if args.write else "dry_run",
        "generated_at": datetime.now().isoformat(),
        "directories": [],
        "changed_files": 0,
        "changes": 0,
    }
    for records_dir in dirs:
        dir_report = {"records_dir": str(records_dir), "files": []}
        for path in iter_record_paths(records_dir):
            record = read_json(path)
            changes = backfill_record(record)
            if changes:
                report["changed_files"] += 1
                report["changes"] += len(changes)
                if args.write:
                    write_json(path, record)
                dir_report["files"].append({"path": str(path), "changes": changes})
        report["directories"].append(dir_report)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
