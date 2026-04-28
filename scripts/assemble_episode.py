#!/usr/bin/env python3
"""Assemble shot clips into one episode with boundary-aware transitions.

Rules:
- If previous shot last_image == next shot image, use hard cut at boundary.
- Non-shared boundaries default to hard cut (transition-mode=none).
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
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


def probe_has_audio(path: Path) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=index",
        "-of",
        "default=nokey=1:noprint_wrappers=1",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, text=True).strip()
    except subprocess.CalledProcessError:
        return False
    return bool(out)


def probe_video_dimensions(path: Path) -> dict[str, int]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(path),
    ]
    data = json.loads(subprocess.check_output(cmd, text=True))
    streams = data.get("streams", [])
    if not streams:
        return {"width": 0, "height": 0}
    stream = streams[0]
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
    }


def parse_episode_number(value: str) -> int:
    match = re.search(r"(?:EP|episode[_-]?)(\d+)", value, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"\b(\d{1,3})\b", value)
    if not match:
        raise ValueError(f"could not infer episode number from: {value}")
    number = int(match.group(1))
    if number <= 0:
        raise ValueError(f"episode number must be positive: {value}")
    return number


def infer_episode_number(args_episode: str, concat_path: Path, out_path: Path) -> int:
    if args_episode.strip():
        return parse_episode_number(args_episode.strip())
    for value in (concat_path.stem, out_path.stem):
        try:
            return parse_episode_number(value)
        except ValueError:
            continue
    raise ValueError("cover page requires --episode, e.g. --episode EP01")


def resolve_cover_page(cover_dir: Path, episode_number: int) -> Path:
    if not cover_dir.exists() or not cover_dir.is_dir():
        raise FileNotFoundError(f"cover page dir not found: {cover_dir}")

    extensions = {".png", ".jpg", ".jpeg", ".webp"}
    number_re = re.compile(rf"(?:^|[^0-9])0*{episode_number}(?:[^0-9]|$)")
    candidates: list[Path] = []
    for path in sorted(cover_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        stem = path.stem.lower()
        if "cover" not in stem or "no_number" in stem:
            continue
        if number_re.search(path.stem):
            candidates.append(path)

    exact = [
        path
        for path in candidates
        if path.stem.endswith(f"_{episode_number:02d}") or path.stem.endswith(f"-{episode_number:02d}")
    ]
    if exact:
        return exact[0].resolve()
    if candidates:
        return candidates[0].resolve()
    raise FileNotFoundError(
        f"cover page for episode {episode_number:02d} not found in {cover_dir}"
    )


def normalize_hint(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def cover_dir_score(cover_dir: Path, hints: list[str]) -> int:
    path_norm = normalize_hint(str(cover_dir))
    score = 0
    parts = [part.lower() for part in cover_dir.parts]
    joined = "/".join(parts)
    if "characters/cover_pages" in joined:
        score += 40
    if "asset/characters/cover_pages" in joined or "assets/characters/cover_pages" in joined:
        score += 20
    if "cover_page" in parts:
        score += 10
    for hint in hints:
        hint_norm = normalize_hint(hint)
        if hint_norm and hint_norm in path_norm:
            score += 30
    return score


def discover_cover_page_dir(
    project_root: Path,
    episode_number: int,
    hints: list[str],
) -> Path | None:
    novel_root = project_root / "novel"
    if not novel_root.exists():
        return None

    candidate_dirs: list[Path] = []
    preferred_suffixes = [
        ("asset", "characters", "cover_pages"),
        ("assets", "characters", "cover_pages"),
        ("asset", "cover_pages"),
        ("assets", "cover_pages"),
        ("asset", "cover_page"),
        ("assets", "cover_page"),
    ]
    for novel_dir in sorted([p for p in novel_root.iterdir() if p.is_dir()]):
        for suffix in preferred_suffixes:
            candidate_dirs.append(novel_dir.joinpath(*suffix))

    for path in novel_root.rglob("*"):
        if path.is_dir() and path.name.lower() in {"cover_page", "cover_pages"}:
            candidate_dirs.append(path)

    valid_dirs: list[Path] = []
    seen: set[Path] = set()
    for path in candidate_dirs:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            resolve_cover_page(resolved, episode_number)
        except FileNotFoundError:
            continue
        valid_dirs.append(resolved)

    if not valid_dirs:
        return None
    return sorted(valid_dirs, key=lambda p: (-cover_dir_score(p, hints), str(p)))[0]


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


def load_image_input_map(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    data = read_json(path)
    out: dict[str, dict[str, str]] = {}
    if not isinstance(data, dict):
        return out
    for shot, entry in data.items():
        shot_id = str(shot).strip().upper()
        if not shot_id:
            continue
        if isinstance(entry, dict):
            image = str(entry.get("image", "")).strip()
            last_image = str(entry.get("last_image", "")).strip()
            out[shot_id] = {"image": image, "last_image": last_image}
    return out


def load_clip_overrides(path: Path | None, project_root: Path) -> dict[str, Path]:
    if path is None:
        return {}
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError("clip overrides root must be a JSON object")

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


def non_empty(v: str) -> str:
    return str(v or "").strip()


def boundary_is_shared(
    prev_shot_id: str,
    next_shot_id: str,
    image_input_map: dict[str, dict[str, str]],
) -> bool:
    prev_entry = image_input_map.get(prev_shot_id, {})
    next_entry = image_input_map.get(next_shot_id, {})
    prev_end = non_empty(prev_entry.get("last_image", ""))
    next_start = non_empty(next_entry.get("image", ""))
    return bool(prev_end and next_start and prev_end == next_start)


def clamp_fade(duration: float, fade: float) -> float:
    if fade <= 0:
        return 0.0
    upper = max(0.0, duration / 2.0 - 0.03)
    return max(0.0, min(fade, upper))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assemble episode clips with boundary-aware hard cuts/fades."
    )
    parser.add_argument("--concat-file", required=True, help="FFmpeg concat list path.")
    parser.add_argument("--out", required=True, help="Output mp4 path.")
    parser.add_argument(
        "--image-input-map",
        default="",
        help="Optional image_input_map JSON. Used for boundary shared-frame detection.",
    )
    parser.add_argument(
        "--clip-overrides",
        default="",
        help=(
            "Optional JSON map of shot id to replacement clip path, e.g. "
            "{\"SH12\": \"test/.../output.phone_fixed.retry.mp4\"}. "
            "Overrides are applied after reading --concat-file while preserving shot order."
        ),
    )
    parser.add_argument(
        "--transition-mode",
        default="none",
        choices=["fade", "none"],
        help="Transition style for non-shared boundaries.",
    )
    parser.add_argument(
        "--transition-sec",
        type=float,
        default=0.14,
        help="Visual fade-in/out duration for non-shared boundaries.",
    )
    parser.add_argument(
        "--hard-cut-when-shared",
        action="store_true",
        default=True,
        help="Keep hard cut when boundary frame is shared. (default: true)",
    )
    parser.add_argument(
        "--audio-policy",
        default="keep",
        choices=["mute", "keep"],
        help=(
            "mute: drop source audio (recommended when model speech may mismatch subtitles); "
            "keep: keep source audio and apply boundary-aware afade."
        ),
    )
    parser.add_argument(
        "--audio-fade-sec",
        type=float,
        default=0.12,
        help="Audio fade-in/out for non-shared boundaries when --audio-policy keep.",
    )
    parser.add_argument(
        "--shared-audio-fade-sec",
        type=float,
        default=0.015,
        help="Tiny anti-pop fade at shared hard-cut boundaries when --audio-policy keep.",
    )
    parser.add_argument(
        "--target-width",
        type=int,
        default=496,
        help="Normalize all source clips to this output width before concat. Use 0 to disable.",
    )
    parser.add_argument(
        "--target-height",
        type=int,
        default=864,
        help="Normalize all source clips to this output height before concat. Use 0 to disable.",
    )
    parser.add_argument(
        "--fit-mode",
        default="cover",
        choices=["cover", "contain"],
        help=(
            "cover: fill target frame and crop overflow; contain: preserve full source "
            "frame and pad with black bars."
        ),
    )
    parser.add_argument(
        "--target-fps",
        type=float,
        default=24.0,
        help="Normalize all video segments to this frame rate before concat. Use 0 to disable.",
    )
    parser.add_argument(
        "--episode",
        default="",
        help=(
            "Episode id/number for cover page selection, e.g. EP01. If omitted, "
            "the script tries to infer it from --concat-file or --out."
        ),
    )
    parser.add_argument(
        "--cover-page-dir",
        default="",
        help=(
            "Optional cover page directory. When omitted, the script auto-searches "
            "novel/<name>/asset(s)/characters/cover_pages, then legacy cover_page dirs."
        ),
    )
    parser.add_argument(
        "--cover-duration-sec",
        type=float,
        default=1.0,
        help="Duration of the prepended cover page in seconds.",
    )
    parser.add_argument(
        "--no-cover-page",
        action="store_true",
        help="Disable cover page insertion, including automatic cover discovery.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    concat_path = Path(args.concat_file).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    image_map_path = Path(args.image_input_map).expanduser().resolve() if args.image_input_map.strip() else None
    project_root = Path(__file__).resolve().parents[1]
    clip_overrides_path = (
        Path(args.clip_overrides).expanduser().resolve() if args.clip_overrides.strip() else None
    )
    cover_dir = Path(args.cover_page_dir).expanduser().resolve() if args.cover_page_dir.strip() else None
    cover_path: Path | None = None
    cover_dimension: dict[str, int] | None = None
    episode_number: int | None = None
    cover_duration = max(0.0, float(args.cover_duration_sec))

    if not concat_path.exists():
        print(f"[ERROR] concat file not found: {concat_path}", file=sys.stderr)
        return 1
    if (cover_dir or not args.no_cover_page) and cover_duration <= 0:
        print("[ERROR] --cover-duration-sec must be positive when cover page is enabled.", file=sys.stderr)
        return 1

    try:
        clips = parse_concat_file(concat_path)
    except Exception as exc:
        print(f"[ERROR] failed to parse concat file: {exc}", file=sys.stderr)
        return 1
    if not clips:
        print("[ERROR] concat file contains no clips.", file=sys.stderr)
        return 1

    try:
        clip_overrides = load_clip_overrides(clip_overrides_path, project_root)
    except Exception as exc:
        print(f"[ERROR] failed to load clip overrides: {exc}", file=sys.stderr)
        return 1
    applied_clip_overrides: list[dict[str, str]] = []
    if clip_overrides:
        next_clips: list[Path] = []
        for clip in clips:
            shot_id = extract_shot_id(clip)
            override = clip_overrides.get(shot_id)
            if override is not None:
                applied_clip_overrides.append(
                    {"shot_id": shot_id, "from": str(clip), "to": str(override)}
                )
                next_clips.append(override)
            else:
                next_clips.append(clip)
        clips = next_clips

    for clip in clips:
        if not clip.exists():
            print(f"[ERROR] clip not found: {clip}", file=sys.stderr)
            return 1

    cover_enabled = False
    if not args.no_cover_page:
        try:
            episode_number = infer_episode_number(args.episode, concat_path, out_path)
        except ValueError as exc:
            if cover_dir:
                print(f"[ERROR] {exc}", file=sys.stderr)
                return 1
            episode_number = None
        if cover_dir is None and episode_number is not None:
            hints = [concat_path.stem, out_path.stem] + [part for clip in clips for part in clip.parts]
            cover_dir = discover_cover_page_dir(
                project_root=project_root,
                episode_number=episode_number,
                hints=hints,
            )
            if cover_dir:
                print(f"[INFO] auto cover page dir: {cover_dir}")
        cover_enabled = bool(cover_dir and episode_number is not None)

    try:
        durations = [probe_duration(p) for p in clips]
        source_dimensions = [probe_video_dimensions(p) for p in clips]
        if cover_enabled:
            assert cover_dir is not None
            assert episode_number is not None
            cover_path = resolve_cover_page(cover_dir, episode_number)
            print(f"[INFO] cover page: {cover_path}")
            cover_dimension = probe_video_dimensions(cover_path)
    except Exception as exc:
        print(f"[ERROR] ffprobe failed: {exc}", file=sys.stderr)
        return 1

    shot_ids = [extract_shot_id(p) for p in clips]
    image_input_map = load_image_input_map(image_map_path)

    boundary_shared: list[bool] = []
    for i in range(len(clips) - 1):
        prev_shot = shot_ids[i]
        next_shot = shot_ids[i + 1]
        shared = boundary_is_shared(prev_shot, next_shot, image_input_map)
        boundary_shared.append(shared)

    transition_sec = max(0.0, float(args.transition_sec))
    transition_mode = args.transition_mode
    target_width = max(0, int(args.target_width))
    target_height = max(0, int(args.target_height))
    normalize_video = target_width > 0 and target_height > 0
    fit_mode = str(args.fit_mode or "cover").strip()
    target_fps = max(0.0, float(args.target_fps))

    # fallback to mute if keeping audio is impossible.
    audio_policy = args.audio_policy
    if audio_policy == "keep":
        has_audio = [probe_has_audio(p) for p in clips]
        if not all(has_audio):
            audio_policy = "mute"
            print(
                "[WARN] some clips have no audio stream; fallback to --audio-policy mute.",
                file=sys.stderr,
            )

    fade_in_v: list[float] = []
    fade_out_v: list[float] = []
    fade_in_a: list[float] = []
    fade_out_a: list[float] = []

    for i, dur in enumerate(durations):
        prev_shared = (i > 0 and boundary_shared[i - 1])
        next_shared = (i < len(durations) - 1 and boundary_shared[i])

        if transition_mode == "none":
            fi_v = 0.0
            fo_v = 0.0
        else:
            fi_v = 0.0 if (args.hard_cut_when_shared and prev_shared) else transition_sec
            fo_v = 0.0 if (args.hard_cut_when_shared and next_shared) else transition_sec
            fi_v = clamp_fade(dur, fi_v)
            fo_v = clamp_fade(dur, fo_v)

        if audio_policy == "keep":
            non_shared = max(0.0, float(args.audio_fade_sec))
            shared = max(0.0, float(args.shared_audio_fade_sec))
            fi_a = shared if (args.hard_cut_when_shared and prev_shared) else (
                0.0 if transition_mode == "none" else non_shared
            )
            fo_a = shared if (args.hard_cut_when_shared and next_shared) else (
                0.0 if transition_mode == "none" else non_shared
            )
            fi_a = clamp_fade(dur, fi_a)
            fo_a = clamp_fade(dur, fo_a)
        else:
            fi_a = 0.0
            fo_a = 0.0

        fade_in_v.append(fi_v)
        fade_out_v.append(fo_v)
        fade_in_a.append(fi_a)
        fade_out_a.append(fo_a)

    filter_parts: list[str] = []
    segment_video_labels: list[str] = []
    segment_audio_labels: list[str] = []

    if cover_enabled:
        cover_image_input_index = 0
        cover_audio_input_index = 1
        v_chain = [f"[{cover_image_input_index}:v]setpts=PTS-STARTPTS"]
        if normalize_video:
            if fit_mode == "cover":
                v_chain.extend(
                    [
                        f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase",
                        f"crop={target_width}:{target_height}:(iw-ow)/2:(ih-oh)/2",
                        "setsar=1",
                    ]
                )
            else:
                v_chain.extend(
                    [
                        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease",
                        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black",
                        "setsar=1",
                    ]
                )
        if target_fps > 0:
            v_chain.append(f"fps={target_fps:.3f}")
        v_chain.append("format=yuv420p")
        filter_parts.append(",".join(v_chain) + "[vcover]")
        filter_parts.append(
            f"[{cover_audio_input_index}:a]atrim=0:{cover_duration:.3f},asetpts=PTS-STARTPTS,aresample=24000[acover]"
        )
        segment_video_labels.append("vcover")
        segment_audio_labels.append("acover")

    clip_input_offset = 2 if cover_enabled else 0
    for i, dur in enumerate(durations):
        input_index = i + clip_input_offset
        v_chain = [f"[{input_index}:v]setpts=PTS-STARTPTS"]
        if normalize_video:
            if fit_mode == "cover":
                v_chain.extend(
                    [
                        f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase",
                        f"crop={target_width}:{target_height}:(iw-ow)/2:(ih-oh)/2",
                        "setsar=1",
                    ]
                )
            else:
                v_chain.extend(
                    [
                        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease",
                        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black",
                        "setsar=1",
                    ]
                )
        if target_fps > 0:
            v_chain.append(f"fps={target_fps:.3f}")
        v_chain.append("format=yuv420p")
        if fade_in_v[i] > 0:
            v_chain.append(f"fade=t=in:st=0:d={fade_in_v[i]:.3f}")
        if fade_out_v[i] > 0:
            st = max(0.0, dur - fade_out_v[i])
            v_chain.append(f"fade=t=out:st={st:.3f}:d={fade_out_v[i]:.3f}")
        filter_parts.append(",".join(v_chain) + f"[v{i}]")
        segment_video_labels.append(f"v{i}")

        if audio_policy == "keep":
            a_chain = [f"[{input_index}:a]asetpts=PTS-STARTPTS,aresample=24000"]
            if fade_in_a[i] > 0:
                a_chain.append(f"afade=t=in:st=0:d={fade_in_a[i]:.3f}")
            if fade_out_a[i] > 0:
                st = max(0.0, dur - fade_out_a[i])
                a_chain.append(f"afade=t=out:st={st:.3f}:d={fade_out_a[i]:.3f}")
            filter_parts.append(",".join(a_chain) + f"[a{i}]")
            segment_audio_labels.append(f"a{i}")

    if audio_policy == "keep" or cover_enabled:
        if audio_policy == "mute":
            for i, dur in enumerate(durations):
                filter_parts.append(
                    f"anullsrc=channel_layout=stereo:sample_rate=24000,atrim=0:{dur:.3f},asetpts=PTS-STARTPTS[a{i}]"
                )
                segment_audio_labels.append(f"a{i}")
        concat_inputs = "".join(
            f"[{v_label}][{a_label}]"
            for v_label, a_label in zip(segment_video_labels, segment_audio_labels, strict=True)
        )
        filter_parts.append(f"{concat_inputs}concat=n={len(segment_video_labels)}:v=1:a=1[vout][aout]")
    else:
        concat_inputs = "".join(f"[{label}]" for label in segment_video_labels)
        filter_parts.append(f"{concat_inputs}concat=n={len(segment_video_labels)}:v=1:a=0[vout]")

    filter_complex = ";".join(filter_parts)

    cmd: list[str] = ["ffmpeg", "-y"]
    if cover_enabled:
        assert cover_path is not None
        cmd += ["-loop", "1", "-t", f"{cover_duration:.3f}", "-i", str(cover_path)]
        cmd += [
            "-f",
            "lavfi",
            "-t",
            f"{cover_duration:.3f}",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=24000",
        ]
    for clip in clips:
        cmd += ["-i", str(clip)]
    cmd += ["-filter_complex", filter_complex, "-map", "[vout]"]
    if audio_policy == "keep" or cover_enabled:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path)]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] ffmpeg assemble failed: {exc}", file=sys.stderr)
        print(f"[DEBUG] cmd: {shlex.join(cmd)}", file=sys.stderr)
        return 1

    boundaries_report: list[dict[str, Any]] = []
    for i in range(len(clips) - 1):
        boundaries_report.append(
            {
                "from_index": i,
                "to_index": i + 1,
                "from_shot": shot_ids[i],
                "to_shot": shot_ids[i + 1],
                "shared_boundary_frame": boundary_shared[i],
                "visual_transition": "hard_cut"
                if (args.hard_cut_when_shared and boundary_shared[i])
                else transition_mode,
            }
        )

    report = {
        "created_at": datetime.now().isoformat(),
        "concat_file": str(concat_path),
        "output_file": str(out_path),
        "clip_overrides_file": str(clip_overrides_path) if clip_overrides_path else "",
        "applied_clip_overrides": applied_clip_overrides,
        "audio_policy": audio_policy,
        "cover_page": {
            "enabled": bool(cover_enabled),
            "episode_number": episode_number,
            "duration_sec": round(cover_duration, 3) if cover_enabled else 0,
            "path": str(cover_path) if cover_path else None,
            "source_width": cover_dimension["width"] if cover_dimension else None,
            "source_height": cover_dimension["height"] if cover_dimension else None,
            "audio_policy": "silent" if cover_enabled else None,
        },
        "normalize_video": normalize_video,
        "fit_mode": fit_mode if normalize_video else None,
        "target_fps": target_fps if target_fps > 0 else None,
        "target_width": target_width if normalize_video else None,
        "target_height": target_height if normalize_video else None,
        "transition_mode": transition_mode,
        "transition_sec": transition_sec,
        "hard_cut_when_shared": bool(args.hard_cut_when_shared),
        "clips": [
            {
                "index": i,
                "path": str(clips[i]),
                "shot_id": shot_ids[i],
                "source_width": source_dimensions[i]["width"],
                "source_height": source_dimensions[i]["height"],
                "output_width": target_width if normalize_video else source_dimensions[i]["width"],
                "output_height": target_height if normalize_video else source_dimensions[i]["height"],
                "duration_sec": round(durations[i], 3),
                "fade_in_v": round(fade_in_v[i], 3),
                "fade_out_v": round(fade_out_v[i], 3),
                "fade_in_a": round(fade_in_a[i], 3),
                "fade_out_a": round(fade_out_a[i], 3),
            }
            for i in range(len(clips))
        ],
        "boundaries": boundaries_report,
        "ffmpeg_cmd": shlex.join(cmd),
    }
    write_json(out_path.parent / "assembly_report.json", report)
    print(f"[INFO] assembled episode: {out_path}")
    print(f"[INFO] report: {out_path.parent / 'assembly_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
