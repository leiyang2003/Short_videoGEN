#!/usr/bin/env python3
"""Build episode language plan from records.

Outputs:
- per-shot subtitle files (shot-local timeline)
- episode subtitle file (global timeline)
- duration_overrides.json (shot -> recommended duration_sec)
- language_plan.json (full planning details)
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_RECORDS_DIR = (
    "SampleChapter_项目文件整理版/06_当前项目的视觉与AI执行层文档/records"
)

PUNCTUATION_PAUSE = {
    "，": 0.12,
    ",": 0.12,
    "、": 0.10,
    "。": 0.22,
    ".": 0.22,
    "！": 0.24,
    "!": 0.24,
    "？": 0.24,
    "?": 0.24,
    "；": 0.20,
    ";": 0.20,
    "：": 0.18,
    ":": 0.18,
    "…": 0.25,
}


@dataclass
class LineTiming:
    index: int
    line_id: str
    speaker_id: str
    speaker: str
    text: str
    start_sec: float
    end_sec: float
    purpose: str = ""
    mouth_owner: str = ""
    silent_characters: tuple[str, ...] = ()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def format_ts(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    ms = int(round(sec * 1000))
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def discover_record_files(records_dir: Path) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    if not records_dir.exists():
        return mapping
    for path in sorted(records_dir.glob("*_record.json")):
        shot_id = ""
        try:
            data = read_json(path)
            shot_id = str(data.get("record_header", {}).get("shot_id", "")).strip().upper()
        except Exception:
            shot_id = ""
        if not shot_id:
            m = re.search(r"(SH\d+)", path.name.upper())
            if m:
                shot_id = m.group(1)
        if shot_id:
            mapping[shot_id] = path
    return mapping


def parse_shots_arg(shots_arg: str, available_shots: list[str]) -> list[str]:
    if not shots_arg.strip():
        return available_shots
    requested = [s.strip().upper() for s in shots_arg.split(",") if s.strip()]
    unknown = [s for s in requested if s not in available_shots]
    if unknown:
        raise ValueError(
            f"未知 shots: {', '.join(unknown)}。可选: {', '.join(available_shots)}"
        )
    seen: set[str] = set()
    out: list[str] = []
    for shot in requested:
        if shot not in seen:
            out.append(shot)
            seen.add(shot)
    return out


def calc_text_duration(text: str, chars_per_sec: float, base_sec: float) -> float:
    stripped = re.sub(r"\s+", "", text)
    effective_chars = max(1, len(stripped))
    sec = base_sec + (effective_chars / max(0.1, chars_per_sec))
    for ch in stripped:
        sec += PUNCTUATION_PAUSE.get(ch, 0.0)
    return max(0.45, sec)


def collect_character_nodes(record: dict[str, Any]) -> list[dict[str, Any]]:
    character_anchor = record.get("character_anchor", {})
    nodes: list[dict[str, Any]] = []
    primary = character_anchor.get("primary")
    if isinstance(primary, dict):
        nodes.append(primary)
    secondary = character_anchor.get("secondary", [])
    if isinstance(secondary, list):
        nodes.extend([item for item in secondary if isinstance(item, dict)])
    return nodes


def collect_character_maps(record: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    name_to_id: dict[str, str] = {}
    character_ids: list[str] = []
    for node in collect_character_nodes(record):
        character_id = str(node.get("character_id", "")).strip()
        name = str(node.get("name", "")).strip()
        if character_id:
            character_ids.append(character_id)
            name_to_id[character_id] = character_id
        if name and character_id:
            name_to_id[name] = character_id

    seen: set[str] = set()
    unique_ids: list[str] = []
    for cid in character_ids:
        if cid and cid not in seen:
            unique_ids.append(cid)
            seen.add(cid)
    return name_to_id, unique_ids


def collect_dialogue_lines(record: dict[str, Any]) -> list[dict[str, Any]]:
    dialogue_language = record.get("dialogue_language", {})
    raw_lines = dialogue_language.get("dialogue_lines", [])
    name_to_id, character_ids = collect_character_maps(record)
    out: list[dict[str, Any]] = []
    if isinstance(raw_lines, list):
        for item in raw_lines:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            speaker = str(item.get("speaker", "")).strip()
            speaker_id = str(item.get("speaker_id", "")).strip() or name_to_id.get(speaker, "")
            silent_characters = [
                cid for cid in character_ids if cid and cid != speaker_id
            ]
            out.append(
                {
                    "speaker": speaker,
                    "speaker_id": speaker_id,
                    "text": text,
                    "purpose": str(item.get("purpose", "")).strip(),
                    "mouth_owner": str(item.get("mouth_owner", "")).strip() or speaker_id,
                    "silent_characters": silent_characters,
                }
            )
    return out


def collect_subtitle_lines(record: dict[str, Any], source: str) -> list[str]:
    dialogue_language = record.get("dialogue_language", {})
    if source == "dialogue":
        lines = collect_dialogue_lines(record)
        texts = [line["text"] for line in lines if line.get("text")]
        if texts:
            return texts

    compact = dialogue_language.get("subtitle_compact_lines", [])
    if isinstance(compact, list):
        texts = [str(x).strip() for x in compact if str(x).strip()]
        if texts:
            return texts

    # fallback
    lines = collect_dialogue_lines(record)
    return [line["text"] for line in lines if line.get("text")]


def build_line_timeline(
    shot_id: str,
    lines: list[dict[str, str]],
    chars_per_sec: float,
    base_sec: float,
    line_gap_sec: float,
    lead_in_sec: float,
) -> tuple[list[LineTiming], float]:
    cursor = max(0.0, lead_in_sec) if lines else 0.0
    timeline: list[LineTiming] = []
    for idx, line in enumerate(lines, start=1):
        text = str(line.get("text", "")).strip()
        if not text:
            continue
        dur = calc_text_duration(text, chars_per_sec=chars_per_sec, base_sec=base_sec)
        start = cursor
        end = start + dur
        timeline.append(
            LineTiming(
                index=idx,
                line_id=f"{shot_id}_{idx:03d}",
                speaker_id=str(line.get("speaker_id", "")).strip(),
                speaker=str(line.get("speaker", "")).strip(),
                text=text,
                start_sec=start,
                end_sec=end,
                purpose=str(line.get("purpose", "")).strip(),
                mouth_owner=str(line.get("mouth_owner", "")).strip(),
                silent_characters=tuple(line.get("silent_characters", []) or ()),
            )
        )
        cursor = end + line_gap_sec
    spoken_total = 0.0 if not timeline else timeline[-1].end_sec
    return timeline, spoken_total


def write_srt(path: Path, lines: list[LineTiming], offset_sec: float = 0.0) -> None:
    chunks: list[str] = []
    for i, line in enumerate(lines, start=1):
        text = line.text
        if line.speaker:
            text = f"{line.speaker}：{text}"
        start = format_ts(offset_sec + line.start_sec)
        end = format_ts(offset_sec + line.end_sec)
        chunks.append(f"{i}\n{start} --> {end}\n{text}\n")
    path.write_text("\n".join(chunks).strip() + ("\n" if chunks else ""), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build unified dialogue/subtitle timing plan and duration overrides."
    )
    parser.add_argument(
        "--experiment-name",
        default=datetime.now().strftime("exp_language_%Y%m%d_%H%M%S"),
        help="Output directory under test/.",
    )
    parser.add_argument("--shots", default="", help="Comma-separated shots. Empty means all records.")
    parser.add_argument("--records-dir", default=DEFAULT_RECORDS_DIR)
    parser.add_argument(
        "--subtitle-source",
        default="dialogue",
        choices=["dialogue", "compact"],
        help="Subtitle source. Use dialogue to keep spoken text and subtitle text consistent.",
    )
    parser.add_argument("--chars-per-sec", type=float, default=4.2)
    parser.add_argument("--base-sec-per-line", type=float, default=0.18)
    parser.add_argument("--line-gap-sec", type=float, default=0.08)
    parser.add_argument("--lead-in-sec", type=float, default=0.35)
    parser.add_argument("--tail-pad-sec", type=float, default=0.35)
    parser.add_argument("--min-duration", type=float, default=4.0)
    parser.add_argument("--max-duration", type=float, default=12.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    records_dir = (project_root / args.records_dir).resolve()
    mapping = discover_record_files(records_dir)
    available_shots = sorted(mapping.keys())
    if not available_shots:
        print(f"[ERROR] no records found: {records_dir}")
        return 1

    try:
        selected_shots = parse_shots_arg(args.shots, available_shots)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return 1

    out_dir = project_root / "test" / args.experiment_name / "language"
    shot_srt_dir = out_dir / "shot_srt"
    shot_srt_dir.mkdir(parents=True, exist_ok=True)

    duration_overrides: dict[str, int] = {}
    shots_plan: dict[str, Any] = {}
    episode_lines: list[LineTiming] = []
    episode_cursor = 0.0
    risks: list[dict[str, Any]] = []

    for shot_id in selected_shots:
        record = read_json(mapping[shot_id])
        global_settings = record.get("global_settings", {})
        requested_duration = float(global_settings.get("duration_sec", args.min_duration))

        dialogue_lines = collect_dialogue_lines(record)
        subtitle_texts = collect_subtitle_lines(record, source=args.subtitle_source)
        if args.subtitle_source == "dialogue":
            subtitle_seed = [dict(line) for line in dialogue_lines]
        else:
            subtitle_seed = [{"speaker": "", "text": t} for t in subtitle_texts]
            if not subtitle_seed and dialogue_lines:
                subtitle_seed = [dict(line) for line in dialogue_lines]

        shot_timeline, spoken_total = build_line_timeline(
            shot_id=shot_id,
            lines=subtitle_seed,
            chars_per_sec=args.chars_per_sec,
            base_sec=args.base_sec_per_line,
            line_gap_sec=args.line_gap_sec,
            lead_in_sec=args.lead_in_sec,
        )

        recommended = max(requested_duration, spoken_total + args.tail_pad_sec)
        clamped = max(float(args.min_duration), min(float(args.max_duration), recommended))
        recommended_int = int(math.ceil(clamped - 1e-6))
        duration_overrides[shot_id] = recommended_int

        if spoken_total + args.tail_pad_sec > requested_duration:
            risks.append(
                {
                    "shot_id": shot_id,
                    "type": "speech_overflow_risk",
                    "detail": (
                        f"spoken_total={spoken_total:.2f}s + tail_pad={args.tail_pad_sec:.2f}s "
                        f"> requested_duration={requested_duration:.2f}s"
                    ),
                }
            )
        if recommended > args.max_duration + 1e-6:
            risks.append(
                {
                    "shot_id": shot_id,
                    "type": "max_duration_limit_risk",
                    "detail": (
                        f"recommended={recommended:.2f}s exceeds max_duration={args.max_duration:.2f}s; "
                        f"clamped={clamped:.2f}s"
                    ),
                }
            )

        write_srt(shot_srt_dir / f"{shot_id}.srt", shot_timeline, offset_sec=0.0)

        shot_episode_lines: list[LineTiming] = []
        for line in shot_timeline:
            shot_episode_lines.append(
                LineTiming(
                    index=len(episode_lines) + len(shot_episode_lines) + 1,
                    line_id=line.line_id,
                    speaker_id=line.speaker_id,
                    speaker=line.speaker,
                    text=line.text,
                    start_sec=episode_cursor + line.start_sec,
                    end_sec=episode_cursor + line.end_sec,
                    purpose=line.purpose,
                    mouth_owner=line.mouth_owner,
                    silent_characters=line.silent_characters,
                )
            )
        episode_lines.extend(shot_episode_lines)
        episode_cursor += float(recommended_int)

        shots_plan[shot_id] = {
            "requested_duration_sec": requested_duration,
            "spoken_total_sec": round(spoken_total, 3),
            "recommended_duration_sec": recommended_int,
            "line_count": len(shot_timeline),
            "subtitle_source": args.subtitle_source,
            "shot_srt_path": str(shot_srt_dir / f"{shot_id}.srt"),
            "lines": [
                {
                    "speaker": line.speaker,
                    "speaker_id": line.speaker_id,
                    "text": line.text,
                    "line_id": line.line_id,
                    "start_sec": round(line.start_sec, 3),
                    "end_sec": round(line.end_sec, 3),
                    "purpose": line.purpose,
                    "mouth_owner": line.mouth_owner,
                    "silent_characters": list(line.silent_characters),
                }
                for line in shot_timeline
            ],
        }

    write_srt(out_dir / "episode.srt", episode_lines, offset_sec=0.0)

    plan = {
        "created_at": datetime.now().isoformat(),
        "records_dir": str(records_dir),
        "shots": selected_shots,
        "settings": {
            "subtitle_source": args.subtitle_source,
            "chars_per_sec": args.chars_per_sec,
            "base_sec_per_line": args.base_sec_per_line,
            "line_gap_sec": args.line_gap_sec,
            "lead_in_sec": args.lead_in_sec,
            "tail_pad_sec": args.tail_pad_sec,
            "min_duration": args.min_duration,
            "max_duration": args.max_duration,
        },
        "duration_overrides": duration_overrides,
        "shots_plan": shots_plan,
        "risks": risks,
    }
    write_json(out_dir / "language_plan.json", plan)
    write_json(out_dir / "duration_overrides.json", duration_overrides)

    print(f"[INFO] language outputs: {out_dir}")
    print(f"[INFO] episode subtitle: {out_dir / 'episode.srt'}")
    print(f"[INFO] duration overrides: {out_dir / 'duration_overrides.json'}")
    print(f"[INFO] risks: {len(risks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
