#!/usr/bin/env python3
"""Shared per-shot character location tracker.

The source selection planner decides what each shot should cover. This module
adds a lightweight continuity pass that tracks where visible and remote
characters are before downstream records are rendered.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import source_selection_planner as ssp


ALLOWED_VISIBILITY = {"visible", "offscreen_phone", "offscreen_voice", "not_present", "inherited"}


@dataclass(frozen=True)
class LocationQAReport:
    passed: bool
    findings: list[dict[str, Any]]
    checks: dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value


def compact_text(text: str, limit: int = 1200) -> str:
    return ssp.compact_text(text, limit)


def tracker_rules_text() -> str:
    return """角色地点连续性规则：
- 源文本和 selection_plan 是事实来源；tracker 只能补充省略的地点/可见性，不能覆盖当前 source 明确事实。
- 每个 shot 必须结合 previous_state、当前 source_excerpt、context_excerpt、selection_plan、semantic_annotation 判断。
- 当前 shot 没有明确换地点时，可以继承上一个 shot 的角色位置和通话状态。
- 电话/语音远端人物默认 visibility=offscreen_phone，不能作为画面内 visible 人物；现场接听/回复者才是 visible。
- 若一个角色在上一镜已经建立在车内/房间/门口，而当前镜只是继续同一通话或同一动作，必须继承该地点。
- 荣誉墙、墙上照片、展板照片属于环境位置，不是手持照片道具。
- 若 current source、selection 和 previous_state 冲突，写入 warnings 并设置 needs_manual_review=true。
"""


def build_tracking_request(
    *,
    source_type: str,
    episode_id: str,
    title: str,
    shots: list[dict[str, Any]],
    characters: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "task": "character_location_tracker",
        "source_type": source_type,
        "episode_id": episode_id,
        "title": title,
        "rules": tracker_rules_text(),
        "system_prompt": "\n".join(
            [
                "你是短剧/小说转视频的角色地点连续性 tracker。",
                "只输出严格 JSON 对象，不要 Markdown。",
                tracker_rules_text(),
                "返回 JSON: {\"shots\":[...]}。",
                "每个 shot 字段: shot_id, shot_location, character_locations, continuity_action, source_basis, confidence, needs_manual_review, warnings。",
                "character_locations 是对象，key 为角色名；每个角色包含 location, visibility, basis。",
            ]
        ),
        "characters": characters,
        "shots": shots,
    }


def normalize_visibility(value: Any) -> str:
    text = str(value or "").strip()
    if text in ALLOWED_VISIBILITY:
        return text
    lowered = text.lower()
    if any(token in lowered for token in ("phone", "电话", "remote")):
        return "offscreen_phone"
    if any(token in lowered for token in ("voice", "画外", "offscreen")):
        return "offscreen_voice"
    if any(token in lowered for token in ("not", "absent", "不在")):
        return "not_present"
    if any(token in lowered for token in ("inherit", "延续", "继承")):
        return "inherited"
    return "visible" if text else "not_present"


def normalize_trace(payload: dict[str, Any], shot_ids: list[str]) -> dict[str, dict[str, Any]]:
    rows = payload.get("shots") if isinstance(payload.get("shots"), list) else []
    allowed = set(shot_ids)
    trace: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        shot_id = str(raw.get("shot_id") or "").strip().upper()
        if shot_id not in allowed:
            continue
        raw_locations = raw.get("character_locations") if isinstance(raw.get("character_locations"), dict) else {}
        character_locations: dict[str, dict[str, str]] = {}
        for name, item in raw_locations.items():
            if not isinstance(item, dict):
                continue
            clean_name = str(name or "").strip()
            if not clean_name:
                continue
            character_locations[clean_name] = {
                "location": str(item.get("location") or "").strip(),
                "visibility": normalize_visibility(item.get("visibility")),
                "basis": str(item.get("basis") or item.get("source_basis") or "").strip(),
            }
        warnings = raw.get("warnings") if isinstance(raw.get("warnings"), list) else []
        trace[shot_id] = {
            "shot_id": shot_id,
            "shot_location": str(raw.get("shot_location") or raw.get("scene_location") or "").strip(),
            "character_locations": character_locations,
            "continuity_action": str(raw.get("continuity_action") or "").strip(),
            "source_basis": str(raw.get("source_basis") or "").strip(),
            "confidence": str(raw.get("confidence") or "").strip() or "medium",
            "needs_manual_review": bool(raw.get("needs_manual_review")),
            "warnings": [str(item).strip() for item in warnings if str(item).strip()],
        }
    return trace


def qa_location_trace(trace: dict[str, dict[str, Any]], shot_ids: list[str]) -> LocationQAReport:
    findings: list[dict[str, Any]] = []
    for shot_id in shot_ids:
        item = trace.get(shot_id)
        if not isinstance(item, dict):
            findings.append({"severity": "high", "issue": "missing_location_trace", "shot_id": shot_id})
            continue
        if not str(item.get("shot_location") or "").strip():
            findings.append({"severity": "medium", "issue": "missing_shot_location", "shot_id": shot_id})
        if item.get("needs_manual_review"):
            findings.append(
                {
                    "severity": "high",
                    "issue": "location_tracker_needs_manual_review",
                    "shot_id": shot_id,
                    "warnings": item.get("warnings", []),
                }
            )
        locations = item.get("character_locations") if isinstance(item.get("character_locations"), dict) else {}
        for name, state in locations.items():
            if not isinstance(state, dict):
                findings.append({"severity": "high", "issue": "invalid_character_location_state", "shot_id": shot_id, "character": name})
                continue
            visibility = normalize_visibility(state.get("visibility"))
            if visibility != state.get("visibility"):
                findings.append({"severity": "medium", "issue": "normalized_character_visibility", "shot_id": shot_id, "character": name, "visibility": visibility})
    blocking = [item for item in findings if item.get("severity") == "high"]
    return LocationQAReport(
        passed=not blocking,
        findings=findings,
        checks={"shots": len(shot_ids), "traced_shots": len(trace)},
    )


def make_chat_payload(request: dict[str, Any], model: str, max_output_tokens: int) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": str(request.get("system_prompt") or "")},
            {"role": "user", "content": json.dumps({k: v for k, v in request.items() if k != "system_prompt"}, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "max_tokens": max_output_tokens,
        "response_format": {"type": "json_object"},
    }


def run_llm_tracking(
    *,
    source_type: str,
    episode_id: str,
    title: str,
    shots: list[dict[str, Any]],
    characters: list[dict[str, Any]],
    out_dir: Path,
    provider: str,
    model: str,
    api_key_env: str,
    base_url: str,
    timeout_sec: int,
    retry_count: int,
    retry_wait_sec: int,
    max_output_tokens: int,
    overwrite: bool,
    dry_run: bool,
) -> tuple[dict[str, dict[str, Any]], LocationQAReport | None, dict[str, Any]]:
    request = build_tracking_request(
        source_type=source_type,
        episode_id=episode_id,
        title=title,
        shots=shots,
        characters=characters,
    )
    llm_dir = out_dir / "llm_requests"
    request_path = llm_dir / "character_location_tracker.request.json"
    response_path = llm_dir / "character_location_tracker.response.json"
    trace_path = out_dir / "character_location_trace.json"
    ssp.write_json(request_path, {"provider": provider, "model": model, "request": request}, overwrite, dry_run)
    if dry_run:
        return {}, None, {"request_path": str(request_path), "dry_run": True}
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"{api_key_env} is not set")
    payload = make_chat_payload(request, model, max_output_tokens=max_output_tokens)
    parsed, raw = ssp.call_openai_compatible_json(
        request=request,
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_sec=timeout_sec,
        retry_count=retry_count,
        retry_wait_sec=retry_wait_sec,
        max_output_tokens=max_output_tokens,
    )
    # Keep the exact payload shape used by this tracker for audit; the shared
    # caller returns its own payload preview, so store both when possible.
    raw_with_payload = dict(raw)
    raw_with_payload.setdefault("payload", payload)
    ssp.write_json(response_path, {"provider": provider, "model": model, "parsed": parsed, "raw": raw_with_payload.get("response", raw_with_payload)}, overwrite, dry_run)
    shot_ids = [str(item.get("shot_id") or "").strip().upper() for item in shots if str(item.get("shot_id") or "").strip()]
    trace = normalize_trace(parsed, shot_ids)
    qa = qa_location_trace(trace, shot_ids)
    ssp.write_json(trace_path, {"source_type": source_type, "episode_id": episode_id, "title": title, "shots": trace, "qa": to_jsonable(qa)}, overwrite, dry_run)
    return trace, qa, {"request_path": str(request_path), "response_path": str(response_path), "trace_path": str(trace_path)}


def offscreen_character_names(location_state: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    locations = location_state.get("character_locations") if isinstance(location_state.get("character_locations"), dict) else {}
    for name, state in locations.items():
        if not isinstance(state, dict):
            continue
        if normalize_visibility(state.get("visibility")) in {"offscreen_phone", "offscreen_voice", "not_present"}:
            names.add(str(name).strip())
    return {name for name in names if name}


def visible_character_names(location_state: dict[str, Any]) -> list[str]:
    out: list[str] = []
    locations = location_state.get("character_locations") if isinstance(location_state.get("character_locations"), dict) else {}
    for name, state in locations.items():
        if not isinstance(state, dict):
            continue
        if normalize_visibility(state.get("visibility")) in {"visible", "inherited"}:
            clean = str(name).strip()
            if clean and clean not in out:
                out.append(clean)
    return out


def source_text_indicates_environment_photo(text: str) -> bool:
    raw = str(text or "")
    return "照片" in raw and any(token in raw for token in ("荣誉墙", "照片墙", "墙上", "展板", "公告栏", "捐赠照片", "挂着", "贴着", "摆在墙"))

