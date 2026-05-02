#!/usr/bin/env python3
"""Run high-confidence shot chains with real tail-frame handoff.

The orchestrator keeps planning records immutable. It writes execution-only
overlays and generated artifacts under test/<experiment-name>/, then delegates
actual I2V calls to run_seedance_test.py.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import shot_chaining


REPO_ROOT = Path(__file__).resolve().parents[1]
NO_BURNED_IN_TEXT_BLOCK = (
    "画面无文字硬化软约束：对白只通过普通话声音、演员嘴型和表情表达；"
    "绝对不要把任何台词文字画进视频帧；不要生成中文字幕、英文字幕、caption、closed caption、"
    "底部字幕、白字黑边、漂浮文字、衣服上的字、屏幕叠字、title card、UI文字、水印或logo；"
    "画面下半区和人物衣服必须保持干净，没有任何可读或不可读文字。"
)
NO_TEXT_AVOID_TERMS = [
    "subtitle",
    "caption",
    "closed caption",
    "on-screen text",
    "bottom text",
    "Chinese characters",
    "text overlay",
    "burned-in subtitles",
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        return (REPO_ROOT / path).resolve()
    return path.resolve()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def run_cmd(cmd: list[str], dry_run: bool = False) -> int:
    print("[CMD] " + " ".join(cmd))
    if dry_run:
        return 0
    return subprocess.run(cmd, cwd=REPO_ROOT).returncode


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(path),
        ],
        text=True,
    ).strip()
    return float(out)


def probe_streams(path: Path) -> dict[str, Any]:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,r_frame_rate,channels,sample_rate",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        text=True,
    )
    return json.loads(out)


def extract_frame(source: Path, timestamp: float, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, timestamp):.3f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-update",
            "1",
            str(out_path),
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def encode_image_data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def image_used_matches_file(image_used_path: Path, image_path: Path) -> bool:
    if not image_used_path.exists() or not image_path.exists():
        return False
    return image_used_path.read_text(encoding="utf-8").strip() == encode_image_data_uri(image_path)


def copy_records(records_dir: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in records_dir.glob("*_record.json"):
        shutil.copy2(path, out_dir / path.name)
    return out_dir


def load_or_build_chain_plan(args: argparse.Namespace, records_dir: Path, experiment_dir: Path) -> tuple[dict[str, Any], Path]:
    if args.chain_plan.strip():
        path = resolve_path(args.chain_plan)
        return read_json(path), path
    shots = [item.strip() for item in args.shots.split(",") if item.strip()] if args.shots.strip() else None
    plan = shot_chaining.build_chain_plan(records_dir=records_dir, shots=shots, confidence=args.chain_confidence)
    path = experiment_dir / "shot_chain_plan.json"
    write_json(path, plan)
    return plan, path


def build_prev_overlay(prev_id: str, next_id: str, requirements: list[str]) -> dict[str, Any]:
    names_text = "；".join(requirements)
    tail_clause = (
        f"尾帧连续性软约束：视频最后0.8秒必须适合作为{next_id}首帧；{names_text}；"
        "关键人物不能离开画面、不能被裁切到只剩手或道具，场景、服装、道具状态保持稳定。"
    )
    return {
        prev_id: {
            "name": f"{prev_id}_tail_to_{next_id}",
            "append_positive_core": [tail_clause, NO_BURNED_IN_TEXT_BLOCK],
            "negative_prompt": NO_TEXT_AVOID_TERMS,
        }
    }


def build_next_overlay(next_id: str) -> dict[str, Any]:
    return {
        next_id: {
            "name": f"{next_id}_no_burned_in_text",
            "append_positive_core": [NO_BURNED_IN_TEXT_BLOCK],
            "negative_prompt": NO_TEXT_AVOID_TERMS,
        }
    }


def seedance_base_cmd(args: argparse.Namespace, records_dir: Path, experiment_name: str, shot_id: str) -> list[str]:
    cmd = [
        sys.executable,
        "scripts/run_seedance_test.py",
        "--experiment-name",
        experiment_name,
        "--shots",
        shot_id,
        "--records-dir",
        rel(records_dir),
        "--video-model",
        args.video_model,
        "--poll-interval",
        str(args.poll_interval),
        "--timeout",
        str(args.timeout),
        "--max-retries",
        str(args.max_retries),
        "--retry-wait-sec",
        str(args.retry_wait_sec),
    ]
    if args.model_profiles.strip():
        cmd.extend(["--model-profiles", args.model_profiles.strip()])
    if args.character_lock_profiles.strip():
        cmd.extend(["--character-lock-profiles", args.character_lock_profiles.strip()])
    if args.keyframe_prompts_root.strip():
        cmd.extend(["--keyframe-prompts-root", args.keyframe_prompts_root.strip()])
    if args.duration_overrides.strip():
        cmd.extend(["--duration-overrides", args.duration_overrides.strip()])
    if args.prepare_only:
        cmd.append("--prepare-only")
    if args.no_audio:
        cmd.append("--no-audio")
    return cmd


def run_seedance_for_shot(
    args: argparse.Namespace,
    records_dir: Path,
    experiment_name: str,
    shot_id: str,
    overlay_path: Path,
    image_input_map: str = "",
    image_url: str = "",
) -> int:
    cmd = seedance_base_cmd(args, records_dir, experiment_name, shot_id)
    cmd.extend(["--execution-overlays", rel(overlay_path)])
    if image_input_map:
        cmd.extend(["--image-input-map", image_input_map])
    if image_url:
        cmd.extend(["--image-url", image_url])
    return run_cmd(cmd, dry_run=bool(args.dry_run))


def filter_groups(plan: dict[str, Any], shots_arg: str) -> list[dict[str, Any]]:
    groups = [group for group in plan.get("groups", []) if isinstance(group, dict)]
    if not shots_arg.strip():
        return groups
    selected = {shot_chaining.normalize_shot_id(item) for item in shots_arg.split(",") if item.strip()}
    return [group for group in groups if set(group.get("shots", [])) <= selected]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run high-confidence Seedance shot chains.")
    parser.add_argument("--experiment-name", default=f"chained_seedance_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--records-dir", required=True)
    parser.add_argument("--image-input-map", default="")
    parser.add_argument("--keyframe-prompts-root", default="")
    parser.add_argument("--duration-overrides", default="")
    parser.add_argument("--video-model", default="novita-seedance1.5")
    parser.add_argument("--shots", default="")
    parser.add_argument("--chain-plan", default="")
    parser.add_argument("--chain-confidence", default="high", choices=["high"])
    parser.add_argument("--model-profiles", default="")
    parser.add_argument("--character-lock-profiles", default="")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--max-retries", type=int, default=10)
    parser.add_argument("--retry-wait-sec", type=float, default=20.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records_dir = resolve_path(args.records_dir)
    experiment_dir = REPO_ROOT / "test" / args.experiment_name
    experiment_dir.mkdir(parents=True, exist_ok=True)
    chain_records_dir = copy_records(records_dir, experiment_dir / "records")
    plan, plan_path = load_or_build_chain_plan(args, chain_records_dir, experiment_dir)
    groups = filter_groups(plan, args.shots)
    clip_overrides: dict[str, str] = {}
    manifest: dict[str, Any] = {
        "created_at": datetime.now().isoformat(),
        "experiment_name": args.experiment_name,
        "records_dir": str(records_dir),
        "chain_records_dir": str(chain_records_dir),
        "chain_plan": str(plan_path),
        "video_model": args.video_model,
        "prepare_only": bool(args.prepare_only),
        "groups": [],
    }
    used_shots: set[str] = set()

    for group in groups:
        shots = [str(item).strip().upper() for item in group.get("shots", [])]
        if len(shots) != 2:
            continue
        prev_id, next_id = shots
        group_report: dict[str, Any] = {
            "group_id": group.get("group_id"),
            "shots": shots,
            "status": "pending",
            "evidence": group.get("evidence", []),
        }
        if prev_id in used_shots or next_id in used_shots:
            group_report["status"] = "skipped"
            group_report["reason"] = "overlapping_chains_are_not_auto_executed_in_v1"
            manifest["groups"].append(group_report)
            continue
        used_shots.update(shots)

        tail_requirements = group.get("tail_requirements", {}).get(prev_id, [])
        prev_overlay_path = experiment_dir / "overlays" / f"{prev_id}_to_{next_id}_prev.json"
        next_overlay_path = experiment_dir / "overlays" / f"{prev_id}_to_{next_id}_next.json"
        write_json(prev_overlay_path, build_prev_overlay(prev_id, next_id, [str(item) for item in tail_requirements]))
        write_json(next_overlay_path, build_next_overlay(next_id))

        code = run_seedance_for_shot(
            args=args,
            records_dir=chain_records_dir,
            experiment_name=args.experiment_name,
            shot_id=prev_id,
            overlay_path=prev_overlay_path,
            image_input_map=args.image_input_map,
        )
        group_report["prev_returncode"] = code
        if code != 0 or args.prepare_only or args.dry_run:
            group_report["status"] = "prepared" if code == 0 else "failed"
            manifest["groups"].append(group_report)
            continue

        prev_output = experiment_dir / prev_id / "output.mp4"
        if not prev_output.exists():
            group_report["status"] = "failed"
            group_report["reason"] = "prev_output_missing"
            manifest["groups"].append(group_report)
            continue

        prev_duration = probe_duration(prev_output)
        tail_frame = experiment_dir / "tail_frames" / f"{prev_id}_tail_for_{next_id}.png"
        extract_frame(prev_output, max(0.0, prev_duration - 0.09), tail_frame)
        group_report["tail_frame"] = str(tail_frame)

        code = run_seedance_for_shot(
            args=args,
            records_dir=chain_records_dir,
            experiment_name=args.experiment_name,
            shot_id=next_id,
            overlay_path=next_overlay_path,
            image_url=rel(tail_frame),
        )
        group_report["next_returncode"] = code
        if code != 0:
            group_report["status"] = "failed"
            manifest["groups"].append(group_report)
            continue

        next_output = experiment_dir / next_id / "output.mp4"
        if not next_output.exists():
            group_report["status"] = "failed"
            group_report["reason"] = "next_output_missing"
            manifest["groups"].append(group_report)
            continue
        image_match = image_used_matches_file(experiment_dir / next_id / "image_used.txt", tail_frame)
        qa_dir = experiment_dir / "qa_frames" / f"{prev_id}_to_{next_id}"
        extract_frame(prev_output, max(0.0, prev_duration - 0.09), qa_dir / "before_boundary.png")
        next_duration = probe_duration(next_output)
        extract_frame(next_output, 0.04, qa_dir / "after_boundary.png")
        extract_frame(next_output, min(3.0, max(0.0, next_duration - 0.2)), qa_dir / "next_mid_dialogue.png")
        prev_payload = read_json(experiment_dir / prev_id / "payload.preview.json") if (experiment_dir / prev_id / "payload.preview.json").exists() else {}
        next_payload = read_json(experiment_dir / next_id / "payload.preview.json") if (experiment_dir / next_id / "payload.preview.json").exists() else {}

        clip_overrides[prev_id] = rel(prev_output)
        clip_overrides[next_id] = rel(next_output)
        group_report.update(
            {
                "status": "completed" if image_match else "failed",
                "image_match": image_match,
                "prev_output": str(prev_output),
                "next_output": str(next_output),
                "prev_ffprobe": probe_streams(prev_output),
                "next_ffprobe": probe_streams(next_output),
                "provider_capability_observed": {
                    "prev_payload_has_last_image": "last_image" in prev_payload,
                    "next_payload_has_last_image": "last_image" in next_payload,
                    "handoff_policy": "real_tail_frame_used_as_next_image",
                },
                "qa_frames": str(qa_dir),
            }
        )
        manifest["groups"].append(group_report)

    clip_overrides_path = experiment_dir / "clip_overrides.json"
    write_json(clip_overrides_path, clip_overrides)
    manifest["clip_overrides"] = str(clip_overrides_path)
    write_json(experiment_dir / "chain_execution_manifest.json", manifest)
    print(f"[INFO] chain execution manifest: {experiment_dir / 'chain_execution_manifest.json'}")
    print(f"[INFO] clip overrides: {clip_overrides_path}")
    return 0 if all(group.get("status") in {"completed", "prepared", "skipped"} for group in manifest["groups"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
