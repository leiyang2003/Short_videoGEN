#!/usr/bin/env python3
"""Run the novel-to-video pipeline for a range of episodes.

The batch runner intentionally keeps the existing single-purpose scripts as
the source of behavior. Its main job is to make the EP01 manual recovery flow
repeatable: generate per-episode visual references before director keyframes,
pass those references into director prep, then continue through Seedance,
assembly, and sync QA.
"""

from __future__ import annotations

import argparse
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
DEFAULT_STAGES = ("plan", "refs", "director", "seedance", "assemble", "qa")


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_repo_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def parse_episode_token(token: str) -> int:
    match = re.fullmatch(r"(?:EP)?(\d{1,3})", token.strip().upper())
    if not match:
        raise ValueError(f"invalid episode token: {token!r}")
    return int(match.group(1))


def parse_episodes(raw: str) -> list[int]:
    episodes: list[int] = []
    for chunk in raw.split(","):
        part = chunk.strip().upper()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            start = parse_episode_token(left)
            end = parse_episode_token(right)
            if end < start:
                raise ValueError(f"episode range goes backwards: {part}")
            episodes.extend(range(start, end + 1))
        else:
            episodes.append(parse_episode_token(part))
    unique: list[int] = []
    for episode in episodes:
        if episode not in unique:
            unique.append(episode)
    if not unique:
        raise ValueError("--episodes did not contain any episode ids")
    return unique


def format_template(template: str, ctx: dict[str, Any]) -> str:
    return template.format(**ctx)


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
        return [item.strip().upper() for item in shots_arg.split(",") if item.strip()]
    shot_ids: list[str] = []
    for path in sorted(records_dir.glob(f"{episode_id}_SH*_record.json")):
        match = re.search(r"(SH\d+)", path.name.upper())
        if match:
            shot_ids.append(match.group(1))
    if not shot_ids:
        raise FileNotFoundError(f"no records found for {episode_id}: {records_dir}")
    return shot_ids


def run_cmd(name: str, cmd: list[str], dry_run: bool) -> int:
    print(f"[STEP] {name}")
    print("[CMD] " + " ".join(cmd))
    if dry_run:
        return 0
    completed = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True)
    return int(completed.returncode)


def stage_enabled(stage: str, through: str) -> bool:
    return DEFAULT_STAGES.index(stage) <= DEFAULT_STAGES.index(through)


def write_concat_file(path: Path, seedance_dir: Path, shots: list[str]) -> None:
    lines = []
    for shot_id in shots:
        clip = seedance_dir / shot_id / "output.mp4"
        lines.append(f"file '{clip.resolve()}'")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_outputs_exist(seedance_dir: Path, shots: list[str]) -> list[str]:
    missing: list[str] = []
    for shot_id in shots:
        if not (seedance_dir / shot_id / "output.mp4").exists():
            missing.append(shot_id)
    return missing


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-run novel2video planning, visual refs, keyframes, Seedance, assembly, and QA."
    )
    parser.add_argument("--novel", required=True, help="Source novel markdown, e.g. novel/ginza_night/ginza_night.md")
    parser.add_argument("--project-name", required=True, help="Project name passed to novel2video_plan.py")
    parser.add_argument("--project-title", default="", help="Optional project title passed to novel2video_plan.py")
    parser.add_argument("--episodes", default="EP01-EP10", help="Comma/range list, e.g. EP01-EP10 or EP01,EP03")
    parser.add_argument("--shots", default="", help="Optional comma-separated shots for every episode. Empty means all records.")
    parser.add_argument("--through", choices=DEFAULT_STAGES, default="qa", help="Last stage to run.")
    parser.add_argument(
        "--bundle-template",
        default="{novel_parent}/{project_name}_{episode}_fullrun_v1",
        help="--out template for novel2video_plan.py under novel/. Fields: novel_parent, project_name, episode, ep_num.",
    )
    parser.add_argument(
        "--experiment-template",
        default="{project_slug}_{episode_lower}_fullrun_v1",
        help="test/ experiment prefix template. Fields: project_slug, episode_lower, episode, ep_num.",
    )
    parser.add_argument(
        "--visual-ref-root",
        default="{novel_parent}/assets/visual_refs_batch_v1",
        help="Shared visual reference root under repo/novel by default. Fields: novel_parent, project_name, episode, ep_num.",
    )
    parser.add_argument("--cover-page-dir", default="", help="Cover page dir. Defaults to <novel parent>/assets/cover_page.")
    parser.add_argument("--audio-policy", default="keep", choices=["keep", "mute"])
    parser.add_argument("--force-plan", action="store_true", help="Rerun planning even when the bundle already exists.")
    parser.add_argument("--overwrite-visual-refs", action="store_true", help="Regenerate existing scene/prop reference images.")
    parser.add_argument("--max-ref-retries", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="Print commands and write manifests/concat previews only.")
    parser.add_argument("--strict", action="store_true", help="Stop on first failing stage.")
    parser.add_argument("--batch-name", default="", help="Manifest name under test/. Defaults to timestamped batch name.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(REPO_ROOT / ".env")

    novel = resolve_repo_path(args.novel)
    if not novel.exists():
        print(f"[ERROR] novel not found: {novel}", file=sys.stderr)
        return 2
    try:
        episodes = parse_episodes(args.episodes)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    novel_root = REPO_ROOT / "novel"
    try:
        novel_parent = str(novel.parent.relative_to(novel_root))
    except ValueError:
        novel_parent = novel.parent.name
    project_slug = re.sub(r"[^a-z0-9]+", "_", args.project_name.lower()).strip("_") or "project"
    batch_name = args.batch_name.strip() or f"{project_slug}_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    batch_manifest_path = REPO_ROOT / "test" / f"{batch_name}.json"
    batch: dict[str, Any] = {
        "created_at": datetime.now().isoformat(),
        "novel": str(novel),
        "project_name": args.project_name,
        "episodes": [f"EP{ep:02d}" for ep in episodes],
        "through": args.through,
        "dry_run": bool(args.dry_run),
        "items": [],
    }

    final_status = 0
    for ep_num in episodes:
        episode_id = f"EP{ep_num:02d}"
        ctx = {
            "novel_parent": novel_parent,
            "project_name": args.project_name,
            "project_slug": project_slug,
            "episode": episode_id,
            "episode_lower": episode_id.lower(),
            "ep_num": ep_num,
        }
        bundle_out = format_template(args.bundle_template, ctx)
        bundle = novel_root / bundle_out
        experiment_prefix = format_template(args.experiment_template, ctx)
        visual_ref_root = novel_root / format_template(args.visual_ref_root, ctx)
        cover_page_dir = resolve_repo_path(args.cover_page_dir) if args.cover_page_dir.strip() else novel.parent / "assets" / "cover_page"
        seedance_dir = REPO_ROOT / "test" / f"{experiment_prefix}_seedance"
        concat_file = seedance_dir / f"concat_{episode_id.lower()}.txt"
        final_video = seedance_dir / f"{episode_id}_final.mp4"

        item: dict[str, Any] = {
            "episode": episode_id,
            "bundle": str(bundle),
            "experiment_prefix": experiment_prefix,
            "visual_ref_root": str(visual_ref_root),
            "seedance_dir": str(seedance_dir),
            "final_video": str(final_video),
            "steps": [],
        }
        batch["items"].append(item)
        print(f"\n[EPISODE] {episode_id}")

        if stage_enabled("plan", args.through):
            if bundle.exists() and not args.force_plan:
                print(f"[SKIP] plan: bundle exists ({bundle})")
                item["steps"].append({"name": "plan", "returncode": 0, "skipped": True})
            else:
                cmd = [
                    sys.executable,
                    "scripts/novel2video_plan.py",
                    "--novel",
                    rel(novel),
                    "--project-name",
                    args.project_name,
                    "--episode",
                    episode_id,
                    "--out",
                    bundle_out,
                ]
                if args.project_title.strip():
                    cmd.extend(["--project-title", args.project_title.strip()])
                code = run_cmd(f"{episode_id} plan", cmd, args.dry_run)
                item["steps"].append({"name": "plan", "cmd": cmd, "returncode": code})
                if code != 0:
                    final_status = code
                    if args.strict:
                        break

        if not bundle.exists() and not args.dry_run:
            print(f"[ERROR] bundle missing after plan stage: {bundle}", file=sys.stderr)
            final_status = final_status or 2
            if args.strict:
                break
            continue

        execution_dir = find_execution_dir(bundle) if bundle.exists() else bundle / EXECUTION_DIR_NAME
        records_dir = execution_dir / "records"
        lock_profiles = execution_dir / "35_character_lock_profiles_v1.json"
        model_profiles = execution_dir / "30_model_capability_profiles_v1.json"
        character_map = novel.parent / "character_image_map.json"
        scene_manifest = visual_ref_root / "visual_reference_manifest.json"

        if stage_enabled("refs", args.through):
            cmd = [
                sys.executable,
                "scripts/generate_visual_reference_assets.py",
                "--episode-root",
                rel(execution_dir),
                "--asset-types",
                "scenes,props",
                "--output-root",
                rel(visual_ref_root),
                "--max-retries",
                str(args.max_ref_retries),
            ]
            if args.overwrite_visual_refs:
                cmd.append("--overwrite")
            code = run_cmd(f"{episode_id} visual refs", cmd, args.dry_run)
            item["steps"].append({"name": "refs", "cmd": cmd, "returncode": code})
            if code != 0:
                final_status = code
                if args.strict:
                    break

        if stage_enabled("director", args.through):
            cmd = [
                sys.executable,
                "scripts/run_novel_video_director.py",
                "--bundle",
                rel(bundle),
                "--episode",
                episode_id,
                "--experiment-prefix",
                experiment_prefix,
                "--character-image-map",
                rel(character_map),
            ]
            if scene_manifest.exists() or args.dry_run:
                cmd.extend(["--visual-reference-manifest", rel(scene_manifest)])
            if args.shots.strip():
                cmd.extend(["--shots", args.shots.strip()])
            code = run_cmd(f"{episode_id} director", cmd, args.dry_run)
            item["steps"].append({"name": "director", "cmd": cmd, "returncode": code})
            if code != 0:
                final_status = code
                if args.strict:
                    break

        keyframe_map = REPO_ROOT / "test" / f"{experiment_prefix}_keyframes" / "image_input_map.json"
        duration_overrides = REPO_ROOT / "test" / f"{experiment_prefix}_language" / "language" / "duration_overrides.json"
        shots = discover_shots(records_dir, episode_id, args.shots) if records_dir.exists() else []
        shots_arg = ",".join(shots)

        if stage_enabled("seedance", args.through):
            cmd = [
                sys.executable,
                "scripts/run_seedance_test.py",
                "--experiment-name",
                f"{experiment_prefix}_seedance",
                "--shots",
                shots_arg,
                "--records-dir",
                rel(records_dir),
                "--model-profiles",
                rel(model_profiles),
                "--character-lock-profiles",
                rel(lock_profiles),
                "--image-input-map",
                rel(keyframe_map),
                "--duration-overrides",
                rel(duration_overrides),
            ]
            code = run_cmd(f"{episode_id} Seedance", cmd, args.dry_run)
            item["steps"].append({"name": "seedance", "cmd": cmd, "returncode": code})
            if code != 0:
                final_status = code
                if args.strict:
                    break

        if stage_enabled("assemble", args.through):
            if not args.dry_run:
                missing = ensure_outputs_exist(seedance_dir, shots)
                if missing:
                    print(f"[ERROR] missing clips for {episode_id}: {', '.join(missing)}", file=sys.stderr)
                    final_status = final_status or 2
                    if args.strict:
                        break
                    continue
                write_concat_file(concat_file, seedance_dir, shots)
            else:
                write_concat_file(concat_file, seedance_dir, shots or [f"SH{i:02d}" for i in range(1, 14)])
            cmd = [
                sys.executable,
                "scripts/assemble_episode.py",
                "--concat-file",
                rel(concat_file),
                "--image-input-map",
                rel(keyframe_map),
                "--episode",
                episode_id,
                "--cover-page-dir",
                rel(cover_page_dir),
                "--audio-policy",
                args.audio_policy,
                "--out",
                rel(final_video),
            ]
            code = run_cmd(f"{episode_id} assemble", cmd, args.dry_run)
            item["steps"].append({"name": "assemble", "cmd": cmd, "returncode": code})
            if code != 0:
                final_status = code
                if args.strict:
                    break

        if stage_enabled("qa", args.through):
            qa_out = REPO_ROOT / "test" / f"{experiment_prefix}_language" / "language" / "qa_sync_report.json"
            cmd = [
                sys.executable,
                "scripts/qa_episode_sync.py",
                "--language-plan",
                rel(REPO_ROOT / "test" / f"{experiment_prefix}_language" / "language" / "language_plan.json"),
                "--concat-file",
                rel(concat_file),
                "--image-input-map",
                rel(keyframe_map),
                "--assembly-report",
                rel(seedance_dir / "assembly_report.json"),
                "--out",
                rel(qa_out),
            ]
            code = run_cmd(f"{episode_id} QA", cmd, args.dry_run)
            item["steps"].append({"name": "qa", "cmd": cmd, "returncode": code})
            if code != 0:
                final_status = code
                if args.strict:
                    break

        item["status"] = "completed" if not any(step.get("returncode") for step in item["steps"]) else "failed"
        write_json(batch_manifest_path, batch)

    batch["status"] = "completed" if final_status == 0 else "failed"
    write_json(batch_manifest_path, batch)
    print(f"\n[INFO] batch manifest: {batch_manifest_path}")
    print(f"[INFO] status: {batch['status']}")
    return final_status


if __name__ == "__main__":
    raise SystemExit(main())
