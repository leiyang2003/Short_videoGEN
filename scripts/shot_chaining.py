#!/usr/bin/env python3
"""Detect high-confidence adjacent shot chains from planning records.

This module is intentionally record-only: it does not inspect keyframe prompts,
generated clips, or source scripts directly. Records remain the source of truth;
the output chain plan is an execution hint for later I2V orchestration.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SHOT_ID_RE = re.compile(r"SH(\d+)", re.IGNORECASE)

HARD_REJECT_TOKENS = (
    "蒙太奇",
    "闪回",
    "回忆",
    "跳时",
    "跳切",
    "多年后",
    "几年后",
    "数年后",
    "字幕卡",
    "title card",
    "黑场",
    "切黑",
    "画面暗下",
    "淡出",
    "转场",
)
PREV_END_BREAK_TOKENS = (
    "离开画面",
    "走出画面",
    "走出房间",
    "走远",
    "关门",
    "门关上",
    "转身离开",
    "背影消失",
    "镜头转向空处",
    "画面暗下",
    "黑场",
    "切黑",
)
SCENE_ONLY_TOKENS = ("空镜", "无人", "无人物", "scene-only", "scene_only")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_shot_id(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = SHOT_ID_RE.search(text)
    if not match:
        return text
    return f"SH{int(match.group(1)):02d}"


def shot_sort_key(shot_id: str) -> tuple[int, str]:
    match = SHOT_ID_RE.fullmatch(shot_id)
    if match:
        return int(match.group(1)), shot_id
    return 9999, shot_id


def discover_record_files(records_dir: Path) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for path in sorted(records_dir.glob("*_record.json")):
        shot_id = ""
        try:
            shot_id = normalize_shot_id(read_json(path).get("record_header", {}).get("shot_id"))
        except Exception:
            shot_id = ""
        if not shot_id:
            match = SHOT_ID_RE.search(path.name)
            if match:
                shot_id = f"SH{int(match.group(1)):02d}"
        if shot_id:
            mapping[shot_id] = path
    return mapping


def ensure_list_str(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def unique_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = compact_text(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def text_blob(record: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("source_trace", "scene_anchor", "shot_execution", "first_frame_contract", "continuity_rules", "scene_motion_contract", "prompt_render"):
        value = record.get(key)
        if isinstance(value, (dict, list)):
            parts.append(json.dumps(value, ensure_ascii=False))
        elif value:
            parts.append(str(value))
    return "\n".join(parts)


def scene_key(record: dict[str, Any]) -> str:
    scene_anchor = record.get("scene_anchor") if isinstance(record.get("scene_anchor"), dict) else {}
    first_frame = record.get("first_frame_contract") if isinstance(record.get("first_frame_contract"), dict) else {}
    candidates = [
        scene_anchor.get("scene_name"),
        scene_anchor.get("scene_id"),
        first_frame.get("location"),
    ]
    return compact_text(next((item for item in candidates if str(item or "").strip()), ""))


def visible_characters(record: dict[str, Any]) -> list[str]:
    first_frame = record.get("first_frame_contract") if isinstance(record.get("first_frame_contract"), dict) else {}
    names: list[str] = []
    names.extend(ensure_list_str(first_frame.get("visible_characters")))
    cardinality = first_frame.get("foreground_character_cardinality")
    if isinstance(cardinality, dict):
        names.extend(ensure_list_str(cardinality.get("names")))
    overlay = first_frame.get("scene_overlay")
    if isinstance(overlay, dict):
        names.extend(ensure_list_str(overlay.get("foreground_characters")))
    dialogue = record.get("dialogue_language") if isinstance(record.get("dialogue_language"), dict) else {}
    for line in dialogue.get("dialogue_lines", []) if isinstance(dialogue.get("dialogue_lines"), list) else []:
        if not isinstance(line, dict):
            continue
        if str(line.get("source") or "onscreen").strip().lower() in {"phone", "offscreen", "voiceover"}:
            continue
        names.extend(ensure_list_str(line.get("speaker")))
        listener = str(line.get("listener") or "").strip()
        if listener and all(token not in listener for token in ("电话", "画外", "offscreen", "phone")):
            names.append(listener)
    return unique_keep_order(names)


def has_dialogue(record: dict[str, Any]) -> bool:
    dialogue = record.get("dialogue_language") if isinstance(record.get("dialogue_language"), dict) else {}
    return bool(dialogue.get("dialogue_lines"))


def contains_any(text: str, tokens: tuple[str, ...]) -> list[str]:
    folded = text.lower()
    return [token for token in tokens if token.lower() in folded]


def is_scene_only(record: dict[str, Any], visible: list[str]) -> bool:
    if visible:
        return False
    return bool(contains_any(text_blob(record), SCENE_ONLY_TOKENS))


def analyze_pair(prev_id: str, prev_record: dict[str, Any], next_id: str, next_record: dict[str, Any]) -> dict[str, Any]:
    prev_text = text_blob(prev_record)
    next_text = text_blob(next_record)
    prev_visible = visible_characters(prev_record)
    next_visible = visible_characters(next_record)
    evidence: list[str] = []
    reject_reasons: list[str] = []

    if scene_key(prev_record) and scene_key(prev_record) == scene_key(next_record):
        evidence.append("same_scene")
    else:
        reject_reasons.append("scene_changed_or_missing")

    hard_tokens = unique_keep_order(contains_any(prev_text, HARD_REJECT_TOKENS) + contains_any(next_text, HARD_REJECT_TOKENS))
    if hard_tokens:
        reject_reasons.append("hard_transition_or_time_jump:" + ",".join(hard_tokens[:4]))

    break_tokens = contains_any(prev_text, PREV_END_BREAK_TOKENS)
    if break_tokens:
        reject_reasons.append("previous_shot_breaks_tail_continuity:" + ",".join(break_tokens[:4]))

    prev_set = {compact_text(name) for name in prev_visible}
    next_set = {compact_text(name) for name in next_visible}
    if prev_set and next_set:
        missing = [name for name in next_visible if compact_text(name) not in prev_set]
        if missing:
            reject_reasons.append("next_requires_new_foreground_characters:" + ",".join(missing))
        elif prev_set == next_set:
            evidence.append("same_visible_characters")
        else:
            evidence.append("next_visible_subset_of_previous")
    elif is_scene_only(prev_record, prev_visible) and next_visible:
        reject_reasons.append("scene_only_to_character_dialogue")
    else:
        reject_reasons.append("visible_characters_missing")

    if has_dialogue(prev_record) and has_dialogue(next_record):
        evidence.append("continuous_dialogue")

    confidence = "none"
    if not reject_reasons and {"same_scene", "continuous_dialogue"} <= set(evidence) and (
        "same_visible_characters" in evidence or "next_visible_subset_of_previous" in evidence
    ):
        confidence = "high"

    return {
        "from_shot": prev_id,
        "to_shot": next_id,
        "confidence": confidence,
        "evidence": evidence,
        "reject_reasons": reject_reasons,
        "visible_characters": {prev_id: prev_visible, next_id: next_visible},
    }


def tail_requirements(prev_id: str, next_id: str, prev_record: dict[str, Any], next_record: dict[str, Any]) -> dict[str, list[str]]:
    names = visible_characters(next_record) or visible_characters(prev_record)
    required = [
        f"keep {', '.join(names)} in final 0.8s" if names else "keep required foreground characters in final 0.8s",
        "no burned-in subtitles or text",
        "keep scene and key props stable",
    ]
    return {prev_id: required}


def build_chain_plan(records_dir: Path, shots: list[str] | None = None, confidence: str = "high") -> dict[str, Any]:
    record_files = discover_record_files(records_dir)
    selected = [normalize_shot_id(item) for item in shots] if shots else sorted(record_files, key=shot_sort_key)
    selected = [shot_id for shot_id in selected if shot_id in record_files]
    records = {shot_id: read_json(record_files[shot_id]) for shot_id in selected}
    groups: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    group_index = 1

    for prev_id, next_id in zip(selected, selected[1:]):
        pair = analyze_pair(prev_id, records[prev_id], next_id, records[next_id])
        pairs.append(pair)
        if pair["confidence"] != confidence:
            continue
        groups.append(
            {
                "group_id": f"G{group_index:02d}",
                "shots": [prev_id, next_id],
                "confidence": pair["confidence"],
                "method": "tail_frame_to_next_first_frame",
                "evidence": pair["evidence"],
                "tail_requirements": tail_requirements(prev_id, next_id, records[prev_id], records[next_id]),
                "fallback": "skip_chain_and_use_original_independent_clips",
            }
        )
        group_index += 1

    return {
        "version": 1,
        "created_at": datetime.now().isoformat(),
        "mode": "high_confidence_tail_to_next_first",
        "records_dir": str(records_dir.resolve()),
        "confidence_threshold": confidence,
        "shots": selected,
        "groups": groups,
        "pairs": pairs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect high-confidence adjacent shot chains from records.")
    parser.add_argument("--records-dir", required=True, help="Directory containing *_record.json files.")
    parser.add_argument("--out", required=True, help="Output shot_chain_plan.json path.")
    parser.add_argument("--shots", default="", help="Optional comma-separated shot ids to consider in order.")
    parser.add_argument("--confidence", default="high", choices=["high"], help="Minimum confidence to emit as executable groups.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records_dir = Path(args.records_dir).expanduser()
    if not records_dir.is_absolute():
        records_dir = (REPO_ROOT / records_dir).resolve()
    shots = [item.strip() for item in args.shots.split(",") if item.strip()] if args.shots.strip() else None
    plan = build_chain_plan(records_dir=records_dir, shots=shots, confidence=args.confidence)
    out = Path(args.out).expanduser()
    if not out.is_absolute():
        out = (REPO_ROOT / out).resolve()
    write_json(out, plan)
    print(f"[INFO] chain plan: {out}")
    print(f"[INFO] high-confidence groups: {len(plan.get('groups', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
