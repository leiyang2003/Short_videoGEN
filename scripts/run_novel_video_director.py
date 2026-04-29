#!/usr/bin/env python3
"""Prepare a novel video bundle for video generation.

This director layer stops before video generation. It runs:
1. language timing plan
2. start keyframe preparation/generation
3. start-only image_input_map export
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTION_DIR_NAME = "06_当前项目的视觉与AI执行层文档"
KEYFRAME_STATIC_FRAME_GUARD = (
    "首帧静态构图约束：只生成一个连续完整的单一画面，只表现这一镜头的起始瞬间；"
    "不要拼贴、不要多格漫画、不要分屏、不要contact sheet、不要插入镜头、不要闪回画面、不要同图呈现多个时间点。"
)
KEYFRAME_STATIC_MOVEMENT = "固定机位或极轻微稳定镜头"
TEMPORAL_SPLIT_RE = re.compile(r"[；;。.!！?？]\s*")
CLAUSE_SPLIT_RE = re.compile(r"[，,；;。.!！?？]\s*")
KEYFRAME_UNSAFE_FRAGMENT_TOKENS = (
    "随后",
    "之后",
    "然后",
    "最后",
    "最终",
    "转到",
    "转入",
    "进入后",
    "后段",
    "响起后",
    "回答后",
    "敲门声",
    "门外忽然",
    "猛地",
    "走向",
    "走去",
    "推门",
    "推开",
    "接起",
    "下滑",
    "听见",
    "听到",
    "传出",
    "插入",
    "闪回",
    "回忆近景",
    "回忆",
    "多个时间点",
    "分屏",
    "多格",
    "拼贴",
    "contact sheet",
)
KEYFRAME_UNSAFE_MOVEMENT_TOKENS = (
    "插入",
    "闪回",
    "转",
    "跟拍",
    "推进",
    "推近",
    "横移",
)
KEYFRAME_FIRST_FRAME_HINT_TOKENS = (
    "首帧",
    "静止",
    "坐",
    "站",
    "手袋",
    "照片",
    "桌面",
    "调查室",
    "门口",
    "走廊",
    "街道",
    "卧室",
    "可见",
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_repo_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    else:
        path = path.resolve()
    return path


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def find_execution_dir(bundle: Path) -> Path:
    direct = bundle / EXECUTION_DIR_NAME
    if direct.exists():
        return direct
    candidates = sorted(bundle.glob("06_*视觉*AI*执行*"))
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"execution dir not found under bundle: {bundle}")


def discover_shots(records_dir: Path, episode_id: str, shots_arg: str) -> list[str]:
    if shots_arg.strip():
        requested = [s.strip().upper() for s in shots_arg.split(",") if s.strip()]
        if not requested:
            raise ValueError("--shots was provided but no shot ids were parsed")
        return requested

    pattern = f"{episode_id.upper()}_SH*_record.json"
    shot_ids: list[str] = []
    for path in sorted(records_dir.glob(pattern)):
        try:
            data = read_json(path)
            shot_id = str(data.get("record_header", {}).get("shot_id", "")).strip().upper()
        except Exception:
            shot_id = ""
        if not shot_id:
            match = re.search(r"(SH\d+)", path.name.upper())
            if match:
                shot_id = match.group(1)
        if shot_id and shot_id not in shot_ids:
            shot_ids.append(shot_id)
    if not shot_ids:
        raise FileNotFoundError(f"no records found for {episode_id}: {records_dir}")
    return shot_ids


def is_remote_or_data_ref(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("http://", "https://", "data:image/"))


def resolve_image_ref(value: str, map_path: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    map_relative = (map_path.parent / path).resolve()
    if map_relative.exists():
        return map_relative
    return (REPO_ROOT / path).resolve()


def character_refs_from_record(data: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    anchor = data.get("character_anchor", {}) if isinstance(data, dict) else {}
    buckets: list[Any] = []
    if isinstance(anchor, dict):
        buckets.append(anchor.get("primary", {}))
        secondary = anchor.get("secondary", [])
        if isinstance(secondary, list):
            buckets.extend(secondary)
    for item in buckets:
        if not isinstance(item, dict):
            continue
        lock_profile_id = str(item.get("lock_profile_id", "")).strip()
        if item.get("lock_prompt_enabled") is False and not lock_profile_id:
            continue
        for key in ("character_id", "name", "lock_profile_id"):
            value = str(item.get(key, "")).strip()
            if value:
                refs.add(value)
    return refs


def validate_character_image_map(character_image_map: Path, records_dir: Path, episode_id: str, shots: list[str]) -> list[str]:
    try:
        image_map = read_json(character_image_map)
    except Exception as exc:
        return [f"character image map is not valid JSON: {character_image_map} ({exc})"]
    needed_refs: set[str] = set()
    for shot_id in shots:
        record_path = records_dir / f"{episode_id}_{shot_id}_record.json"
        if not record_path.exists():
            return [f"record not found for selected shot {shot_id}: {record_path}"]
        try:
            needed_refs.update(character_refs_from_record(read_json(record_path)))
        except Exception as exc:
            return [f"record is not valid JSON: {record_path} ({exc})"]

    errors: list[str] = []
    for ref in sorted(needed_refs):
        raw_value = image_map.get(ref)
        if not raw_value:
            errors.append(f"missing character image map key: {ref}")
            continue
        value = str(raw_value).strip()
        if not value:
            errors.append(f"empty character image map value for key: {ref}")
            continue
        if is_remote_or_data_ref(value):
            continue
        image_path = resolve_image_ref(value, character_image_map)
        if not image_path.exists() or not image_path.is_file():
            errors.append(f"character image file not found for key {ref}: {value} -> {image_path}")
    return errors


def has_keyframe_temporal_risk(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token.lower() in lowered for token in KEYFRAME_UNSAFE_FRAGMENT_TOKENS)


def clean_keyframe_fragment(fragment: str) -> str:
    text = str(fragment or "").strip(" ，,；;。.\n\t")
    text = text.replace("。，", "。").replace("；，", "；")
    text = text.replace("首帧后段可见", "首帧可见")
    text = text.replace("首帧进入后静止", "首帧静止")
    text = text.replace("进入后静止", "静止")
    text = re.sub(r"被临时警员带入后", "", text)
    return text.strip(" ，,；;。.\n\t")


def sanitize_keyframe_static_text(text: str, fallback: str = "") -> str:
    raw = str(text or "").strip()
    if not raw:
        return fallback
    raw = clean_keyframe_fragment(raw)
    unsafe_positions = [
        raw.find(token) for token in KEYFRAME_UNSAFE_FRAGMENT_TOKENS
        if token in raw and raw.find(token) > 0
    ]
    if unsafe_positions:
        raw = clean_keyframe_fragment(raw[:min(unsafe_positions)])
    candidates: list[str] = []
    for sentence in TEMPORAL_SPLIT_RE.split(raw):
        sentence = clean_keyframe_fragment(sentence)
        if not sentence:
            continue
        for clause in CLAUSE_SPLIT_RE.split(sentence):
            clause = clean_keyframe_fragment(clause)
            if not clause:
                continue
            if has_keyframe_temporal_risk(clause):
                continue
            candidates.append(clause)

    hinted = [
        item for item in candidates
        if any(token in item for token in KEYFRAME_FIRST_FRAME_HINT_TOKENS)
    ]
    selected = hinted or candidates
    if not selected:
        return fallback or clean_keyframe_fragment(raw)
    return "，".join(selected[:5])


def sanitize_keyframe_movement(movement: str) -> str:
    text = str(movement or "").strip()
    if not text:
        return KEYFRAME_STATIC_MOVEMENT
    if any(token in text for token in KEYFRAME_UNSAFE_MOVEMENT_TOKENS):
        return KEYFRAME_STATIC_MOVEMENT
    return text


def sanitize_keyframe_scene_name(scene_name: str, risk_detected: bool) -> str:
    text = str(scene_name or "").strip()
    if not risk_detected:
        return text
    parts = [part.strip() for part in re.split(r"[至到与]", text, maxsplit=1) if part.strip()]
    return parts[0] if parts else text


def normalize_dialogue_source(value: Any, text: str = "", purpose: str = "") -> str:
    raw = str(value or "").strip().lower()
    if raw in {"phone", "telephone", "call", "mobile", "手机", "电话", "通话"}:
        return "phone"
    if raw in {"offscreen", "off-screen", "voiceover", "voice_over", "radio", "broadcast", "画外", "画外声", "广播"}:
        return "offscreen"
    combined = " ".join([str(text or ""), str(purpose or "")])
    if any(token in combined for token in ("电话里", "电话中", "手机里", "听筒", "来电", "接起电话", "通话中")):
        return "phone"
    if any(token in combined for token in ("画外声", "门外传来", "广播里", "对讲机里")):
        return "offscreen"
    return "onscreen"


def dialogue_listener_name(item: dict[str, Any]) -> str:
    for key in ("listener", "heard_by", "receiver", "listening_character", "phone_listener"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def dialogue_visibility_contract(record: dict[str, Any]) -> str:
    dialogue_language = record.get("dialogue_language", {})
    dialogue_lines = dialogue_language.get("dialogue_lines", []) if isinstance(dialogue_language, dict) else []
    if not isinstance(dialogue_lines, list):
        return ""
    onscreen: list[str] = []
    listeners: list[str] = []
    for item in dialogue_lines:
        if not isinstance(item, dict):
            continue
        source = normalize_dialogue_source(item.get("source"), item.get("text", ""), item.get("purpose", ""))
        if source == "phone":
            listener = dialogue_listener_name(item)
            if listener:
                listeners.append(listener)
        elif source == "onscreen":
            speaker = str(item.get("speaker") or "").strip()
            if speaker:
                onscreen.append(speaker)
    onscreen = [name for name in dict.fromkeys(onscreen) if name]
    listeners = [name for name in dict.fromkeys(listeners) if name]
    parts: list[str] = []
    if len(onscreen) == 1:
        parts.append(f"对白可见人物契约：{onscreen[0]}是画面内说话人，首帧必须清楚入镜。")
    elif len(onscreen) >= 2:
        parts.append(f"对白可见人物契约：{'、'.join(onscreen)}是画面内说话人，首帧必须同时清楚入镜。")
    if listeners:
        parts.append(f"电话/画外声音契约：{'、'.join(listeners)}是听电话/接收声音的人，首帧必须清楚入镜并呈现听电话或倾听动作；远端说话人不强制入镜。")
    return "".join(parts)


def prepare_keyframe_static_records(
    records_dir: Path,
    out_dir: Path,
    episode_id: str,
    shots: list[str],
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "enabled": True,
        "records_dir": str(out_dir),
        "shots": {},
    }
    for shot_id in shots:
        src = records_dir / f"{episode_id}_{shot_id}_record.json"
        record = read_json(src)
        sanitized = copy.deepcopy(record)
        shot_execution = sanitized.setdefault("shot_execution", {})
        camera_plan = shot_execution.setdefault("camera_plan", {})
        prompt_render = sanitized.setdefault("prompt_render", {})
        scene_anchor = sanitized.setdefault("scene_anchor", {})

        original_scene_name = str(scene_anchor.get("scene_name", "")).strip()
        original_movement = str(camera_plan.get("movement", "")).strip()
        original_framing = str(camera_plan.get("framing_focus", "")).strip()
        original_action = str(shot_execution.get("action_intent", "")).strip()
        original_core = str(prompt_render.get("shot_positive_core", "")).strip()
        risk_detected = any(
            has_keyframe_temporal_risk(value)
            for value in (original_scene_name, original_movement, original_framing, original_action, original_core)
        )
        static_anchor = sanitized.get("keyframe_static_anchor")
        if not isinstance(static_anchor, dict):
            static_anchor = {}

        static_framing = sanitize_keyframe_static_text(original_framing, fallback=original_core)
        static_core = sanitize_keyframe_static_text(original_core, fallback=static_framing)
        static_movement = sanitize_keyframe_movement(original_movement)
        static_scene_name = sanitize_keyframe_scene_name(original_scene_name, risk_detected)
        anchor_scene_name = str(static_anchor.get("scene_name", "")).strip()
        anchor_movement = str(static_anchor.get("movement", "")).strip()
        anchor_framing = str(static_anchor.get("framing_focus", "")).strip()
        anchor_action = str(static_anchor.get("action_intent", "")).strip()
        anchor_core = str(static_anchor.get("positive_core", "")).strip()

        if anchor_scene_name:
            static_scene_name = anchor_scene_name
        if anchor_movement:
            static_movement = anchor_movement
        if anchor_framing:
            static_framing = anchor_framing
        if anchor_core:
            static_core = anchor_core
        visibility_contract = dialogue_visibility_contract(sanitized)
        if visibility_contract:
            if static_framing and "对白可见人物契约" not in static_framing and "电话/画外声音契约" not in static_framing:
                static_framing = f"{static_framing} {visibility_contract}"
            if static_core and "对白可见人物契约" not in static_core and "电话/画外声音契约" not in static_core:
                static_core = f"{static_core} {visibility_contract}"

        if static_scene_name:
            scene_anchor["scene_name"] = static_scene_name
        if static_framing:
            camera_plan["framing_focus"] = static_framing
        camera_plan["movement"] = static_movement
        if anchor_action:
            shot_execution["action_intent"] = anchor_action
        elif static_framing:
            shot_execution["action_intent"] = f"只表现起始帧的静态状态：{static_framing}"
        if static_core:
            prompt_render["shot_positive_core"] = f"{static_core}，{KEYFRAME_STATIC_FRAME_GUARD}"
        else:
            prompt_render["shot_positive_core"] = KEYFRAME_STATIC_FRAME_GUARD

        negative = prompt_render.get("negative_prompt")
        if isinstance(negative, list):
            for item in ("collage", "split screen", "multi-panel", "comic panels", "contact sheet", "storyboard layout"):
                if item not in negative:
                    negative.append(item)

        changed = (
            original_scene_name != scene_anchor.get("scene_name")
            or
            original_movement != camera_plan.get("movement")
            or original_framing != camera_plan.get("framing_focus")
            or original_action != shot_execution.get("action_intent")
            or original_core != prompt_render.get("shot_positive_core")
        )
        report["shots"][shot_id] = {
            "changed": bool(changed),
            "risk_detected": bool(risk_detected),
            "scene_name": {
                "before": original_scene_name,
                "after": str(scene_anchor.get("scene_name", "")),
            },
            "movement": {
                "before": original_movement,
                "after": str(camera_plan.get("movement", "")),
            },
            "framing_focus": {
                "before": original_framing,
                "after": str(camera_plan.get("framing_focus", "")),
            },
            "action_intent": {
                "before": original_action,
                "after": str(shot_execution.get("action_intent", "")),
            },
            "shot_positive_core": {
                "before": original_core,
                "after": str(prompt_render.get("shot_positive_core", "")),
            },
        }
        write_json(out_dir / src.name, sanitized)
    write_json(out_dir / "keyframe_static_sanitizer_report.json", report)
    return report


def run_step(name: str, cmd: list[str], cwd: Path, dry_run: bool) -> int:
    print(f"[STEP] {name}")
    print("[CMD] " + " ".join(cmd))
    if dry_run:
        return 0
    completed = subprocess.run(cmd, cwd=str(cwd), text=True)
    return int(completed.returncode)


def normalize_image_model(value: str) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "atlas": "atlas-openai",
        "atlas_openai": "atlas-openai",
        "atlas-openai": "atlas-openai",
        "openai": "openai",
        "grok": "grok",
        "xai": "grok",
        "auto": "auto",
    }
    if raw in aliases:
        return aliases[raw]
    raise ValueError(f"未知 IMAGE_MODEL: {value!r}。可选: openai, atlas-openai, grok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run director preparation: language plan -> start keyframes -> image_input_map."
    )
    parser.add_argument("--bundle", required=True, help="Planning bundle directory.")
    parser.add_argument("--episode", default="EP01", help="Episode id, default EP01.")
    parser.add_argument("--experiment-prefix", default="", help="Prefix for test experiment folders.")
    parser.add_argument("--shots", default="", help="Comma-separated shot ids. Empty means all episode records.")
    parser.add_argument(
        "--image-model",
        default="",
        choices=["", "openai", "atlas-openai", "grok", "auto"],
        help="Macro image provider selector. Empty means IMAGE_MODEL env, then --provider, then openai.",
    )
    parser.add_argument(
        "--provider",
        default="",
        choices=["", "atlas", "openai", "auto", "grok", "atlas-openai"],
        help="Legacy keyframe provider alias. Prefer --image-model or IMAGE_MODEL.",
    )
    parser.add_argument("--prepare-only", action="store_true", help="Prepare keyframe payloads without API calls.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    parser.add_argument("--character-image-map", default="", help="Override character_image_map.json path.")
    parser.add_argument("--default-image", default="", help="Fallback reference image for scene-only keyframes.")
    parser.add_argument(
        "--visual-reference-manifest",
        default="",
        help="Optional visual_reference_manifest.json with scene/prop references for scene-only or temporary-character keyframes.",
    )
    parser.add_argument("--allow-data-uri-from-local", action="store_true", help="Convert local image refs to data URIs in image_input_map.")
    parser.add_argument("--strict", action="store_true", help="Stop on step failure and use strict image map export.")
    parser.add_argument("--keyframe-model", default="", help="Optional Atlas keyframe model override.")
    parser.add_argument("--openai-model", default="", help="Optional OpenAI image edit model override.")
    parser.add_argument("--xai-model", default="", help="Optional xAI/Grok image edit model override.")
    parser.add_argument("--quality", default="", choices=["", "low", "medium", "high"], help="Optional keyframe quality override.")
    parser.add_argument("--size", default="", help="Optional keyframe output size override, e.g. 1024x1536.")
    parser.add_argument(
        "--disable-keyframe-static-sanitize",
        action="store_true",
        help="Do not create static-frame-safe record copies for keyframe generation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle = resolve_repo_path(args.bundle)
    if not bundle.exists() or not bundle.is_dir():
        print(f"[ERROR] bundle not found: {bundle}", file=sys.stderr)
        return 2

    episode_id = args.episode.strip().upper() or "EP01"
    execution_dir = find_execution_dir(bundle)
    records_dir = execution_dir / "records"
    lock_profiles = execution_dir / "35_character_lock_profiles_v1.json"
    if not records_dir.exists():
        print(f"[ERROR] records dir not found: {records_dir}", file=sys.stderr)
        return 2
    if not lock_profiles.exists():
        print(f"[ERROR] character lock profiles not found: {lock_profiles}", file=sys.stderr)
        return 2

    novel_dir = bundle.parent
    character_image_map = resolve_repo_path(args.character_image_map) if args.character_image_map.strip() else novel_dir / "character_image_map.json"
    if not character_image_map.exists():
        print(f"[ERROR] character image map not found: {character_image_map}", file=sys.stderr)
        return 2

    try:
        shots = discover_shots(records_dir, episode_id, args.shots)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    try:
        image_model = normalize_image_model(
            args.image_model.strip()
            or os.getenv("IMAGE_MODEL", "").strip()
            or args.provider.strip()
            or "openai"
        )
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    image_map_errors = validate_character_image_map(character_image_map, records_dir, episode_id, shots)
    if image_map_errors:
        print("[ERROR] character image map preflight failed:", file=sys.stderr)
        for error in image_map_errors:
            print(f"  - {error}", file=sys.stderr)
        print("[HINT] Fix the map or pass --character-image-map before running keyframe generation.", file=sys.stderr)
        return 2

    prefix = args.experiment_prefix.strip() or f"{bundle.name}_{episode_id.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shots_arg = ",".join(shots)
    language_exp = f"{prefix}_language"
    keyframe_exp = f"{prefix}_keyframes"
    language_plan_path = REPO_ROOT / "test" / language_exp / "language" / "language_plan.json"
    duration_overrides_path = REPO_ROOT / "test" / language_exp / "language" / "duration_overrides.json"
    keyframe_manifest_path = REPO_ROOT / "test" / keyframe_exp / "keyframe_manifest.json"
    image_input_map_path = REPO_ROOT / "test" / keyframe_exp / "image_input_map.json"
    keyframe_records_dir = REPO_ROOT / "test" / keyframe_exp / "keyframe_static_records"
    sanitizer_report: dict[str, Any] = {"enabled": False}
    keyframe_source_records_dir = records_dir
    if not args.disable_keyframe_static_sanitize:
        sanitizer_report = prepare_keyframe_static_records(
            records_dir=records_dir,
            out_dir=keyframe_records_dir,
            episode_id=episode_id,
            shots=shots,
        )
        keyframe_source_records_dir = keyframe_records_dir

    steps: list[tuple[str, list[str]]] = []
    steps.append(
        (
            "language plan",
            [
                sys.executable,
                "scripts/build_episode_language_plan.py",
                "--records-dir",
                rel(records_dir),
                "--experiment-name",
                language_exp,
                "--shots",
                shots_arg,
            ],
        )
    )

    keyframe_cmd = [
        sys.executable,
        "scripts/generate_keyframes_atlas_i2i.py",
        "--records-dir",
        rel(keyframe_source_records_dir),
        "--character-lock-profiles",
        rel(lock_profiles),
        "--character-image-map",
        rel(character_image_map),
        "--phases",
        "start",
        "--image-model",
        image_model,
        "--experiment-name",
        keyframe_exp,
        "--shots",
        shots_arg,
    ]
    if args.prepare_only:
        keyframe_cmd.append("--prepare-only")
    if args.keyframe_model.strip():
        keyframe_cmd.extend(["--model", args.keyframe_model.strip()])
    if args.openai_model.strip():
        keyframe_cmd.extend(["--openai-model", args.openai_model.strip()])
    if args.xai_model.strip():
        keyframe_cmd.extend(["--xai-model", args.xai_model.strip()])
    if args.quality.strip():
        keyframe_cmd.extend(["--quality", args.quality.strip()])
    if args.size.strip():
        keyframe_cmd.extend(["--size", args.size.strip()])
    if args.default_image.strip():
        keyframe_cmd.extend(["--default-image", args.default_image.strip()])
    if args.visual_reference_manifest.strip():
        visual_reference_manifest = resolve_repo_path(args.visual_reference_manifest)
        keyframe_cmd.extend(["--visual-reference-manifest", rel(visual_reference_manifest)])
    steps.append(("start keyframes", keyframe_cmd))

    image_map_cmd = [
        sys.executable,
        "scripts/build_image_input_map.py",
        "--manifest",
        rel(keyframe_manifest_path),
        "--out",
        rel(image_input_map_path),
        "--allow-missing-last-image",
        "--shots",
        shots_arg,
    ]
    if args.allow_data_uri_from_local or image_model in {"openai", "grok"}:
        image_map_cmd.append("--allow-data-uri-from-local")
    if args.strict:
        image_map_cmd.append("--strict")
    steps.append(("image input map", image_map_cmd))

    result: dict[str, Any] = {
        "created_at": datetime.now().isoformat(),
        "bundle": str(bundle),
        "episode_id": episode_id,
        "shots": shots,
        "image_model": image_model,
        "prepare_only": bool(args.prepare_only),
        "dry_run": bool(args.dry_run),
        "outputs": {
            "language_plan": str(language_plan_path),
            "duration_overrides": str(duration_overrides_path),
            "keyframe_manifest": str(keyframe_manifest_path),
            "image_input_map": str(image_input_map_path),
            "keyframe_records_dir": str(keyframe_source_records_dir),
            "visual_reference_manifest": str(resolve_repo_path(args.visual_reference_manifest))
            if args.visual_reference_manifest.strip()
            else "",
            "keyframe_static_sanitizer_report": str(keyframe_records_dir / "keyframe_static_sanitizer_report.json")
            if sanitizer_report.get("enabled")
            else "",
        },
        "keyframe_static_sanitizer": sanitizer_report,
        "steps": [],
    }

    for name, cmd in steps:
        code = run_step(name, cmd, REPO_ROOT, bool(args.dry_run))
        result["steps"].append({"name": name, "cmd": cmd, "returncode": code})
        if code != 0:
            result["status"] = "failed"
            result["failed_step"] = name
            manifest_path = REPO_ROOT / "test" / f"{prefix}_director_manifest.json"
            write_json(manifest_path, result)
            print(f"[ERROR] {name} failed with code {code}", file=sys.stderr)
            print(f"[INFO] director manifest: {manifest_path}")
            return code if args.strict else code

    result["status"] = "completed"
    manifest_path = REPO_ROOT / "test" / f"{prefix}_director_manifest.json"
    write_json(manifest_path, result)
    print(f"[INFO] director manifest: {manifest_path}")
    print(f"[INFO] duration overrides: {duration_overrides_path}")
    print(f"[INFO] keyframe manifest: {keyframe_manifest_path}")
    print(f"[INFO] image input map: {image_input_map_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
