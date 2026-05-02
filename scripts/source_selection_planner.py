#!/usr/bin/env python3
"""Shared LLM source parsing/selection/merging planner.

The screen and novel planners keep their own downstream ShotDraft/ShotPlan
types. This module only owns the common source-unit schema, LLM prompt, response
normalization, and QA so both pipelines can use the same selection contract.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # pragma: no cover - requests may be unavailable in dry-run environments.
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore


@dataclass(frozen=True)
class SourceUnit:
    unit_id: str
    index: int
    source_type: str
    kind: str
    text: str
    scene_name: str = ""
    speaker: str = ""
    line_start: int = 0
    line_end: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SelectedShot:
    shot_id: str
    source_unit_ids: list[str]
    source_range: list[int]
    summary: str
    scene_name: str
    story_function: str
    selection_reason: str
    merge_reason: str
    keyframe_moment: str
    must_include_evidence: list[str]
    dialogue_policy: str
    key_props: list[str]
    i2v_risk_notes: list[str]
    omitted_unit_ids: list[str]
    is_montage: bool = False


@dataclass(frozen=True)
class SelectionPlan:
    mode: str
    source_type: str
    episode_id: str
    title: str
    selected_shots: list[SelectedShot]
    omitted_units: list[dict[str, Any]]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass(frozen=True)
class SelectionQAReport:
    passed: bool
    findings: list[dict[str, Any]]
    checks: dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


CRITICAL_TEXT_TOKENS = (
    "验孕棒",
    "两条红线",
    "手机",
    "消息",
    "照片",
    "画",
    "报告",
    "DNA",
    "父亲",
    "怀孕",
    "出生",
    "医生",
    "手术",
)
PROP_TOKEN_MAP = {
    "验孕棒": "PREGNANCY_TEST_STICK_01",
    "手机": "SMARTPHONE_01",
    "照片": "PHOTO_01",
    "画": "CHILD_DRAWING_01",
    "报告": "DOCUMENT_REPORT_01",
    "DNA": "DNA_REPORT_01",
}
ENVIRONMENT_PHOTO_TOKENS = ("荣誉墙", "照片墙", "墙上", "展板", "公告栏", "捐赠照片", "挂着", "贴着", "摆在墙")


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value


def compact_text(text: str, limit: int = 1600) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def unique_text(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def detected_key_props(text: str) -> list[str]:
    props: list[str] = []
    raw = str(text or "")
    environment_photo = "照片" in raw and any(token in raw for token in ENVIRONMENT_PHOTO_TOKENS)
    for token, prop_id in PROP_TOKEN_MAP.items():
        if token not in raw:
            continue
        if token == "照片" and environment_photo:
            props.append("ENVIRONMENT_MOUNTED_PHOTO_01")
            continue
        if token in raw:
            props.append(prop_id)
    return unique_text(props)


def shot_requires_must_include_evidence(shot: SelectedShot, units: list[SourceUnit]) -> bool:
    lookup = {unit.unit_id: unit for unit in units}
    selected_text = " ".join(lookup[unit_id].text for unit_id in shot.source_unit_ids if unit_id in lookup)
    combined = " ".join(
        [
            selected_text,
            shot.summary,
            shot.story_function,
            shot.keyframe_moment,
            shot.dialogue_policy,
            " ".join(shot.key_props),
        ]
    )
    if shot.key_props:
        return True
    return any(token in combined for token in CRITICAL_TEXT_TOKENS + ("电话", "语音", "集尾", "钩子", "hook", "悬念", "证据"))


def unit_range_for_ids(units: list[SourceUnit], unit_ids: list[str]) -> list[int]:
    lookup = {unit.unit_id: unit for unit in units}
    selected = [lookup[item] for item in unit_ids if item in lookup]
    if not selected:
        return [0, 0]
    starts = [unit.line_start or unit.index for unit in selected]
    ends = [unit.line_end or unit.index for unit in selected]
    return [min(starts), max(ends)]


def source_excerpt_for_ids(units: list[SourceUnit], unit_ids: list[str], max_chars: int = 1600) -> str:
    lookup = {unit.unit_id: unit for unit in units}
    selected = [lookup[item] for item in unit_ids if item in lookup]
    selected.sort(key=lambda item: item.index)
    text = "\n\n".join(unit.text for unit in selected if unit.text.strip())
    return compact_text(text, max_chars)


def selection_rules_text() -> str:
    return """选择/合并规则：
- 源文本是唯一事实来源；不得改写剧情、台词、人物关系或事件顺序。
- 不得丢掉关键剧情 beat、关键实物证据、对白、情绪转折、角色决定和集尾钩子。
- 结尾 15%-20% 的 source units、episode hook、悬念收束、电话/消息收束默认是关键剧情；不得因为 max_shots 预算而整段省略。若预算紧，优先压缩早期无对白环境/过渡/重复反应镜头，不能丢掉结尾 setup、关键电话对白、收尾反应或 hook 画面。
- 关键实物证据包括验孕棒/两条红线、手机消息、照片/画、报告、DNA、药物、票据等；若影响剧情，必须进入对应 shot 的 key_props 或 must_include_evidence。
- selection/merging 不能只按镜头标记；必须按剧情动作、视觉可执行性、情绪节点和 I2V 可执行性切分。
- max_shots 是可用预算，不是必须压缩到很少镜头；当 max_shots 充足时，应保留 70%-100% 的可执行剧情 beat。不要把整场多轮对白压成一个大镜头。
- 仅当 source units 相邻、同场/同时间、动作目标一致、视觉任务兼容时才合并。
- 遇到时间、地点、动作目标、关键证据、说话关系、身体状态或情绪目标明显变化时必须拆分。
- I2V 硬规则：一个 selected shot 最多只能有一位 active onscreen speaker。相邻 source units 里出现不同说话人时，默认拆成多个 selected shots；不能把问答、多人来回对白、老师提问+孩子回答合并到同一个 selected shot。
- 电话/语音硬规则：远端电话说话人和现场人物回复必须拆成不同 selected shots。电话远端人物默认不进入首帧 visible characters；可用“手机里传来声音/现场人物听到电话”表达，但不要把远端人物与现场回复者合并为同一 active dialogue shot。
- 电话/语音收束必须保留地点 setup、现场持机/接听者、关键远端问题、关键现场回答和挂断/沉默后的情绪反应；不能只用 omitted_units 理由概括掉电话段。
- 对白段可合并的唯一常见例外：同一说话人连续两句、或无对白动作/反应紧贴一个单说话人对白，且 keyframe_moment 仍是单一瞬间。
- 蒙太奇/跳时/多地点镜头必须指定一个单一 keyframe_moment；不能把多个时间点拼成一张图。
- 每个 omitted source unit 必须给出 omitted_unit_ids 和理由；不能静默遗漏。
- 输出 shot_id 必须从 SH01 连续编号；source_unit_ids 必须来自输入。"""


def build_selection_request(
    *,
    mode: str,
    source_type: str,
    episode_id: str,
    title: str,
    units: list[SourceUnit],
    max_shots: int,
    characters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    include_rules = mode == "llm-rules"
    prompt = [
        "你是短剧/小说转视频的 source parsing、shot selection 和 merging planner。",
        "只输出严格 JSON 对象，不要 Markdown。",
        selection_rules_text() if include_rules else "不提供额外规则；请按你的理解选择和合并镜头，但仍需忠实源文本。",
        "返回 JSON: {\"selected_shots\":[...], \"omitted_units\":[...]}。",
        "selected_shots 每项字段: shot_id, source_unit_ids, source_range, summary, scene_name, story_function, selection_reason, merge_reason, keyframe_moment, must_include_evidence, dialogue_policy, key_props, i2v_risk_notes, omitted_unit_ids, is_montage。",
        "source_range 是源文本行号/段落号的 [start,end]；must_include_evidence/key_props/i2v_risk_notes/omitted_unit_ids 必须是数组。",
        f"max_shots={max_shots}；在不超过 max_shots 的前提下优先拆成 I2V 可执行小镜头，不要过度合并。",
    ]
    return {
        "task": "source_selection",
        "mode": mode,
        "source_type": source_type,
        "episode_id": episode_id,
        "title": title,
        "max_shots": max_shots,
        "rules": selection_rules_text() if include_rules else "",
        "system_prompt": "\n".join(prompt),
        "characters": characters or [],
        "source_units": [to_jsonable(unit) for unit in units],
    }


def make_chat_payload(request: dict[str, Any], model: str, max_output_tokens: int = 12000) -> dict[str, Any]:
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


def extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.S | re.I)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("LLM response JSON root must be an object")
    return data


def call_openai_compatible_json(
    *,
    request: dict[str, Any],
    api_key: str,
    base_url: str,
    model: str,
    timeout_sec: int,
    retry_count: int,
    retry_wait_sec: int,
    max_output_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if requests is None:
        raise RuntimeError("requests is unavailable")
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = make_chat_payload(request, model, max_output_tokens=max_output_tokens)
    last_error = ""
    for attempt in range(1, max(1, retry_count) + 1):
        response = requests.post(url, headers=headers, json=payload, timeout=max(30, timeout_sec))
        try:
            body = response.json()
        except Exception:
            body = {"raw_text": response.text}
        if response.status_code < 400:
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices:
                raise RuntimeError(f"LLM response missing choices: {body}")
            content = str(((choices[0] or {}).get("message") or {}).get("content") or "")
            parsed = extract_json_object(content)
            return parsed, {"payload": payload, "response": body}
        last_error = f"HTTP {response.status_code}: {body}"
        retryable = response.status_code in {408, 409, 429, 500, 502, 503, 504}
        if not retryable or attempt >= max(1, retry_count):
            break
        time.sleep(max(0, retry_wait_sec))
    raise RuntimeError(f"source selection LLM failed: {last_error}")


def normalize_selected_shot(raw: dict[str, Any], units: list[SourceUnit], index: int) -> SelectedShot:
    unit_lookup = {unit.unit_id: unit for unit in units}
    shot_id = str(raw.get("shot_id") or f"SH{index:02d}").strip().upper()
    unit_ids = [str(item).strip() for item in raw.get("source_unit_ids", []) if str(item).strip()] if isinstance(raw.get("source_unit_ids"), list) else []
    raw_range = raw.get("source_range") or raw.get("line_range")
    if isinstance(raw_range, list) and len(raw_range) >= 2:
        try:
            source_range = [int(raw_range[0]), int(raw_range[1])]
        except Exception:
            source_range = unit_range_for_ids(units, unit_ids)
    else:
        source_range = unit_range_for_ids(units, unit_ids)
    selected_units = [unit_lookup[item] for item in unit_ids if item in unit_lookup]
    selected_text = " ".join(unit.text for unit in selected_units)
    scene_name = str(raw.get("scene_name") or "").strip()
    if not scene_name and selected_units:
        scene_name = next((unit.scene_name for unit in selected_units if unit.scene_name), "")
    summary = str(raw.get("summary") or "").strip() or compact_text(source_excerpt_for_ids(units, unit_ids), 180)
    return SelectedShot(
        shot_id=shot_id,
        source_unit_ids=unit_ids,
        source_range=source_range,
        summary=summary,
        scene_name=scene_name,
        story_function=str(raw.get("story_function") or "推进剧情").strip(),
        selection_reason=str(raw.get("selection_reason") or "LLM selected this source range as a visual story beat").strip(),
        merge_reason=str(raw.get("merge_reason") or "source units are adjacent and visually compatible").strip(),
        keyframe_moment=str(raw.get("keyframe_moment") or summary).strip(),
        must_include_evidence=unique_text([str(item) for item in raw.get("must_include_evidence", [])]) if isinstance(raw.get("must_include_evidence"), list) else [],
        dialogue_policy=str(raw.get("dialogue_policy") or "").strip(),
        key_props=unique_text([str(item) for item in raw.get("key_props", [])] + detected_key_props(selected_text)) if isinstance(raw.get("key_props"), list) else detected_key_props(selected_text),
        i2v_risk_notes=unique_text([str(item) for item in raw.get("i2v_risk_notes", [])]) if isinstance(raw.get("i2v_risk_notes"), list) else [],
        omitted_unit_ids=unique_text([str(item) for item in raw.get("omitted_unit_ids", [])]) if isinstance(raw.get("omitted_unit_ids"), list) else [],
        is_montage=bool(raw.get("is_montage")),
    )


def normalize_selection_plan(
    payload: dict[str, Any],
    *,
    units: list[SourceUnit],
    mode: str,
    source_type: str,
    episode_id: str,
    title: str,
    max_shots: int,
) -> SelectionPlan:
    raw_shots = payload.get("selected_shots") or payload.get("shots")
    if not isinstance(raw_shots, list):
        raise ValueError("selection response missing selected_shots")
    selected = [
        normalize_selected_shot(item, units, idx)
        for idx, item in enumerate(raw_shots[:max_shots], start=1)
        if isinstance(item, dict)
    ]
    # Re-number for downstream compatibility; source ranges remain untouched.
    renumbered = [
        SelectedShot(**{**to_jsonable(shot), "shot_id": f"SH{idx:02d}"})
        for idx, shot in enumerate(selected, start=1)
    ]
    omitted = payload.get("omitted_units") if isinstance(payload.get("omitted_units"), list) else []
    return SelectionPlan(
        mode=mode,
        source_type=source_type,
        episode_id=episode_id,
        title=title,
        selected_shots=renumbered,
        omitted_units=[item for item in omitted if isinstance(item, dict)],
    )


def qa_selection_plan(plan: SelectionPlan, units: list[SourceUnit]) -> SelectionQAReport:
    findings: list[dict[str, Any]] = []
    unit_lookup = {unit.unit_id: unit for unit in units}
    min_line = min((unit.line_start or unit.index for unit in units), default=1)
    max_line = max((unit.line_end or unit.index for unit in units), default=1)
    used: list[str] = []
    last_start = -1
    prior_ranges: list[tuple[int, int, str, bool]] = []
    for shot in plan.selected_shots:
        if not shot.source_unit_ids:
            findings.append({"severity": "high", "issue": "selected_shot_missing_source_units", "shot_id": shot.shot_id})
        invalid = [unit_id for unit_id in shot.source_unit_ids if unit_id not in unit_lookup]
        if invalid:
            findings.append({"severity": "high", "issue": "invalid_source_unit_ids", "shot_id": shot.shot_id, "unit_ids": invalid})
        if shot.source_range[0] <= 0 or shot.source_range[1] < shot.source_range[0]:
            findings.append({"severity": "high", "issue": "invalid_source_range", "shot_id": shot.shot_id, "source_range": shot.source_range})
        elif shot.source_range[0] < min_line or shot.source_range[1] > max_line:
            findings.append({"severity": "high", "issue": "source_range_outside_source_units", "shot_id": shot.shot_id, "source_range": shot.source_range})
        if shot.source_range[0] < last_start and not shot.is_montage:
            findings.append({"severity": "medium", "issue": "source_ranges_not_ordered", "shot_id": shot.shot_id})
        for prior_start, prior_end, prior_shot_id, prior_is_montage in prior_ranges:
            overlaps = shot.source_range[0] <= prior_end and prior_start <= shot.source_range[1]
            if overlaps and not shot.is_montage and not prior_is_montage:
                findings.append({"severity": "high", "issue": "overlapping_selected_shots", "shot_id": shot.shot_id, "overlaps_with": prior_shot_id, "source_range": shot.source_range})
        last_start = max(last_start, shot.source_range[0])
        for field_name in ("selection_reason", "merge_reason", "keyframe_moment"):
            if not str(getattr(shot, field_name) or "").strip():
                findings.append({"severity": "high", "issue": f"missing_{field_name}", "shot_id": shot.shot_id})
        if not shot.must_include_evidence and shot_requires_must_include_evidence(shot, units):
            findings.append({"severity": "medium", "issue": "missing_must_include_evidence", "shot_id": shot.shot_id})
        used.extend(shot.source_unit_ids)
        prior_ranges.append((shot.source_range[0], shot.source_range[1], shot.shot_id, shot.is_montage))

    used_set = set(used)
    omitted_ids: set[str] = set()
    for item in plan.omitted_units:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("omitted_unit_ids"), list):
            omitted_ids.update(str(unit_id).strip() for unit_id in item.get("omitted_unit_ids", []) if str(unit_id).strip())
        unit_id = str(item.get("unit_id") or item.get("source_unit_id") or "").strip()
        if unit_id:
            omitted_ids.add(unit_id)
    for item in plan.omitted_units:
        if not isinstance(item, dict):
            continue
        unit_ids = [str(unit_id).strip() for unit_id in item.get("omitted_unit_ids", []) if str(unit_id).strip()] if isinstance(item.get("omitted_unit_ids"), list) else []
        unit_id = str(item.get("unit_id") or item.get("source_unit_id") or "").strip()
        if unit_id:
            unit_ids.append(unit_id)
        reason = str(item.get("reason") or item.get("omission_reason") or item.get("why") or "").strip()
        if not unit_ids:
            findings.append({"severity": "high", "issue": "omitted_unit_missing_id", "item": item})
        for omitted_id in unit_ids:
            if omitted_id not in unit_lookup:
                findings.append({"severity": "high", "issue": "omitted_unit_invalid_id", "unit_id": omitted_id})
        if not reason:
            findings.append({"severity": "high", "issue": "omitted_unit_missing_reason", "unit_id": unit_id or unit_ids})
    for unit in units:
        if unit.kind == "scene":
            continue
        if unit.unit_id not in used_set and unit.unit_id not in omitted_ids:
            severity = "medium" if any(token in unit.text for token in CRITICAL_TEXT_TOKENS) else "info"
            findings.append({"severity": severity, "issue": "source_unit_not_selected_or_omitted", "unit_id": unit.unit_id, "text": compact_text(unit.text, 160)})
        if unit.unit_id not in used_set and any(token in unit.text for token in CRITICAL_TEXT_TOKENS):
            findings.append({"severity": "medium", "issue": "critical_unit_omitted", "unit_id": unit.unit_id, "text": compact_text(unit.text, 160)})
    blocking = [item for item in findings if item.get("severity") == "high"]
    return SelectionQAReport(
        passed=not blocking,
        findings=findings,
        checks={"source_units": len(units), "selected_shots": len(plan.selected_shots), "used_units": len(used_set)},
    )


def write_json(path: Path, data: Any, overwrite: bool, dry_run: bool) -> bool:
    if dry_run:
        print(f"[DRY] write {path}")
        return True
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def write_text(path: Path, text: str, overwrite: bool, dry_run: bool) -> bool:
    if dry_run:
        print(f"[DRY] write {path}")
        return True
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return True


def render_compare_markdown(rule_plan: SelectionPlan | None, no_rules: SelectionPlan | None, rules: SelectionPlan | None) -> str:
    def rows(label: str, plan: SelectionPlan | None) -> list[str]:
        if plan is None:
            return [f"| {label} | - | - | - | unavailable |"]
        out = []
        for shot in plan.selected_shots:
            out.append(
                f"| {label} | {shot.shot_id} | {shot.source_range[0]}-{shot.source_range[1]} | "
                f"{shot.scene_name} | {shot.summary.replace('|', '/')} |"
            )
        return out

    lines = [
        "# Source Selection Compare",
        "",
        "| mode | shot | range | scene | summary |",
        "|---|---:|---:|---|---|",
    ]
    lines.extend(rows("rule", rule_plan))
    lines.extend(rows("llm-no-rules", no_rules))
    lines.extend(rows("llm-rules", rules))
    return "\n".join(lines)


def run_llm_selection(
    *,
    mode: str,
    source_type: str,
    episode_id: str,
    title: str,
    units: list[SourceUnit],
    max_shots: int,
    characters: list[dict[str, Any]] | None,
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
) -> tuple[SelectionPlan | None, SelectionQAReport | None, dict[str, Any]]:
    request = build_selection_request(
        mode=mode,
        source_type=source_type,
        episode_id=episode_id,
        title=title,
        units=units,
        max_shots=max_shots,
        characters=characters,
    )
    llm_dir = out_dir / "llm_requests"
    suffix = "rules" if mode == "llm-rules" else "no_rules"
    request_path = llm_dir / f"source_selection.{suffix}.request.json"
    response_path = llm_dir / f"source_selection.{suffix}.response.json"
    write_json(request_path, {"provider": provider, "model": model, "request": request}, overwrite, dry_run)
    if dry_run:
        return None, None, {"request_path": str(request_path), "dry_run": True}
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"{api_key_env} is not set")
    parsed, raw = call_openai_compatible_json(
        request=request,
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_sec=timeout_sec,
        retry_count=retry_count,
        retry_wait_sec=retry_wait_sec,
        max_output_tokens=max_output_tokens,
    )
    write_json(response_path, {"provider": provider, "model": model, "parsed": parsed, "raw": raw.get("response", raw)}, overwrite, dry_run)
    plan = normalize_selection_plan(
        parsed,
        units=units,
        mode=mode,
        source_type=source_type,
        episode_id=episode_id,
        title=title,
        max_shots=max_shots,
    )
    qa = qa_selection_plan(plan, units)
    return plan, qa, {"request_path": str(request_path), "response_path": str(response_path), "dry_run": False}
