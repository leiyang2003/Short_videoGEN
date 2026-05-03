#!/usr/bin/env python3
"""QA checks for language sync, cut timing, transition policy, and frame consistency."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_concat_file(path: Path) -> list[Path]:
    clips: list[Path] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("file "):
            value = line[5:].strip()
            if value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            elif value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            clips.append(Path(value).expanduser().resolve())
    return clips


def load_clip_overrides(path: Path | None) -> dict[str, Path]:
    if path is None:
        return {}
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError("clip overrides root must be a JSON object")

    project_root = Path(__file__).resolve().parents[1]
    overrides: dict[str, Path] = {}
    for raw_shot, raw_value in data.items():
        shot_id = str(raw_shot).strip().upper()
        if not shot_id:
            continue
        if isinstance(raw_value, dict):
            value = (
                raw_value.get("path")
                or raw_value.get("clip")
                or raw_value.get("file")
                or raw_value.get("output")
            )
        else:
            value = raw_value
        clip_text = str(value or "").strip()
        if not clip_text:
            continue
        clip_path = Path(clip_text).expanduser()
        if not clip_path.is_absolute():
            clip_path = project_root / clip_path
        overrides[shot_id] = clip_path.resolve()
    return overrides


def apply_clip_overrides(clips: list[Path], overrides: dict[str, Path]) -> tuple[list[Path], list[dict[str, str]]]:
    applied: list[dict[str, str]] = []
    resolved: list[Path] = []
    for clip in clips:
        shot_id = extract_shot_id(clip)
        override = overrides.get(shot_id) if shot_id else None
        if override:
            resolved.append(override)
            applied.append({"shot_id": shot_id, "from": str(clip), "to": str(override)})
        else:
            resolved.append(clip)
    return resolved, applied


def probe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nokey=1:noprint_wrappers=1",
        str(path),
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return float(out)


def extract_shot_id(path: Path) -> str:
    for part in reversed(path.parts):
        m = re.fullmatch(r"SH(\d+)", part.upper())
        if m:
            return f"SH{int(m.group(1)):02d}"
    m = re.search(r"(SH\d+)", path.name.upper())
    if m:
        return m.group(1)
    for part in reversed(path.parts):
        m = re.search(r"(?:^|[_-])(SH\d+)(?:[_-]|$)", part.upper())
        if m:
            return m.group(1)
    return ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QA report for 4 short-video issues.")
    parser.add_argument("--language-plan", required=True, help="language_plan.json path")
    parser.add_argument("--concat-file", required=True, help="concat list path used for assembly")
    parser.add_argument("--image-input-map", default="", help="image_input_map.json path")
    parser.add_argument("--assembly-report", default="", help="assembly_report.json path")
    parser.add_argument("--clip-overrides", default="", help="optional clip_overrides.json path used for assembly")
    parser.add_argument("--out", required=True, help="output qa report json path")
    parser.add_argument("--cut-margin-sec", type=float, default=0.12)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    language_plan_path = Path(args.language_plan).expanduser().resolve()
    concat_path = Path(args.concat_file).expanduser().resolve()
    image_map_path = Path(args.image_input_map).expanduser().resolve() if args.image_input_map.strip() else None
    assembly_report_path = (
        Path(args.assembly_report).expanduser().resolve() if args.assembly_report.strip() else None
    )
    clip_overrides_path = (
        Path(args.clip_overrides).expanduser().resolve() if args.clip_overrides.strip() else None
    )
    out_path = Path(args.out).expanduser().resolve()

    plan = read_json(language_plan_path)
    clips = parse_concat_file(concat_path)
    clip_overrides = load_clip_overrides(clip_overrides_path)
    clips, applied_clip_overrides = apply_clip_overrides(clips, clip_overrides)
    durations = [probe_duration(p) for p in clips]
    shot_ids = [extract_shot_id(p) for p in clips]

    image_map: dict[str, Any] = {}
    if image_map_path and image_map_path.exists():
        image_map = read_json(image_map_path)
        if not isinstance(image_map, dict):
            image_map = {}

    assembly_report: dict[str, Any] = {}
    if assembly_report_path and assembly_report_path.exists():
        assembly_report = read_json(assembly_report_path)

    findings: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    # Check 1: spoken text / subtitle consistency risk.
    subtitle_source = str(plan.get("settings", {}).get("subtitle_source", "")).strip().lower()
    checks["subtitle_source"] = subtitle_source
    if subtitle_source != "dialogue":
        findings.append(
            {
                "issue": "speech_subtitle_mismatch_risk",
                "severity": "high",
                "detail": "subtitle_source is not dialogue; spoken text and subtitles may diverge.",
            }
        )

    # Check 3: clip cuts before spoken content finishes.
    shot_plan = plan.get("shots_plan", {})
    cut_margin = max(0.0, float(args.cut_margin_sec))
    cut_risks = []
    for i, shot_id in enumerate(shot_ids):
        if not shot_id:
            continue
        p = shot_plan.get(shot_id, {})
        if not isinstance(p, dict):
            continue
        spoken_total = float(p.get("spoken_total_sec", 0.0))
        needed = spoken_total + cut_margin
        have = float(durations[i])
        if have + 1e-6 < needed:
            cut_risks.append(
                {
                    "shot_id": shot_id,
                    "clip_duration_sec": round(have, 3),
                    "needed_sec": round(needed, 3),
                    "spoken_total_sec": round(spoken_total, 3),
                }
            )
    checks["early_cut_risk_count"] = len(cut_risks)
    if cut_risks:
        findings.append(
            {
                "issue": "early_scene_cut",
                "severity": "high",
                "detail": "Some shots may cut before speech completion.",
                "items": cut_risks,
            }
        )

    # Check 4: frame consistency inputs.
    missing_keyframes = []
    missing_last_images = []
    for shot_id in shot_ids:
        if not shot_id:
            continue
        entry = image_map.get(shot_id, {})
        if not isinstance(entry, dict):
            missing_keyframes.append(shot_id)
            continue
        if not str(entry.get("image", "")).strip():
            missing_keyframes.append(shot_id)
        if not str(entry.get("last_image", "")).strip():
            missing_last_images.append(shot_id)
    checks["missing_keyframe_count"] = len(missing_keyframes)
    checks["missing_last_image_count"] = len(missing_last_images)
    if missing_keyframes:
        findings.append(
            {
                "issue": "character_scene_consistency_risk",
                "severity": "medium",
                "detail": "Some shots miss image/last_image anchors.",
                "items": missing_keyframes,
            }
        )

    # Check 2: shared-boundary transition policy.
    if assembly_report:
        bad_transitions = []
        for item in assembly_report.get("boundaries", []):
            if not isinstance(item, dict):
                continue
            if bool(item.get("shared_boundary_frame")) and str(item.get("visual_transition")) != "hard_cut":
                bad_transitions.append(item)
        checks["shared_boundary_bad_transition_count"] = len(bad_transitions)
        if bad_transitions:
            findings.append(
                {
                    "issue": "shared_boundary_transition_policy_violation",
                    "severity": "medium",
                    "detail": "Shared boundary should be hard cut (no visual transition).",
                    "items": bad_transitions,
                }
            )
    else:
        checks["shared_boundary_bad_transition_count"] = None

    result = {
        "created_at": datetime.now().isoformat(),
        "inputs": {
            "language_plan": str(language_plan_path),
            "concat_file": str(concat_path),
            "image_input_map": str(image_map_path) if image_map_path else "",
            "assembly_report": str(assembly_report_path) if assembly_report_path else "",
            "clip_overrides": str(clip_overrides_path) if clip_overrides_path else "",
        },
        "applied_clip_overrides": applied_clip_overrides,
        "checks": checks,
        "findings": findings,
        "pass": len(findings) == 0,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(out_path, result)
    print(f"[INFO] qa report: {out_path}")
    print(f"[INFO] pass: {result['pass']}")
    print(f"[INFO] findings: {len(findings)}")
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
