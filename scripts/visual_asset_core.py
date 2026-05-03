#!/usr/bin/env python3
"""Shared visual asset bible, prompt, and Grok image helpers.

This module is intentionally repo-local and dependency-light so both novel and
screen-script flows can use the same asset creation behavior.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


XAI_CHAT_COMPLETIONS_URL = "https://api.x.ai/v1/chat/completions"
XAI_IMAGE_GENERATIONS_URL = "https://api.x.ai/v1/images/generations"
OPENAI_IMAGE_GENERATIONS_URL = "https://api.openai.com/v1/images/generations"
DEFAULT_XAI_CHAT_MODELS = ["grok-4-fast-reasoning", "grok-3-fast", "grok-3"]
DEFAULT_XAI_IMAGE_MODEL = "grok-imagine-image"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-1.5"
DEFAULT_OPENAI_CHARACTER_QA_MODEL = "gpt-4o-mini"

AMBIGUOUS_WARDROBE_TOKENS = ("或", " or ", "任选", "候选", "二选一", "可选")
ABSTRACT_SCENE_NAMES = {
    "主居空间",
    "会客区域",
    "过渡回廊",
    "夜间外景",
    "事务处理处",
    "私密休憩区",
    "冲突缓冲区",
    "情绪修复点",
    "关系推进点",
    "关系修复点",
    "观察锚点",
}
TEXT_HEAVY_PROP_TOKENS = (
    "REPORT",
    "DOCUMENT",
    "SLIP",
    "WEBPAGE",
    "MESSAGE",
    "SMS",
    "DNA",
    "FORM",
    "FILE",
)
SCENE_MODIFIER_PROP_ID_TOKENS = (
    "WINDOW",
    "SEAT",
    "ARMREST",
    "SPEAKER",
    "GATE",
    "TRACK",
    "SKYLINE",
    "PLATFORM",
    "DOOR",
    "VEHICLE",
    "BUS",
    "CAR",
    "ELEVATOR",
    "ROOM",
)
SCENE_MODIFIER_DISPLAY_TOKENS = (
    "车窗",
    "窗",
    "座椅",
    "座席",
    "扶手",
    "扬声器",
    "闸机",
    "检票口",
    "铁轨",
    "轨道",
    "城市轮廓",
    "天际线",
    "站台",
    "门",
    "车门",
    "房间",
    "车厢",
)
TRUE_PROP_ID_TOKENS = (
    "PHOTO",
    "DOCUMENT",
    "REPORT",
    "FILE",
    "LETTER",
    "SLIP",
    "PHONE",
    "SMARTPHONE",
    "CIGARETTE",
    "LIGHTER",
    "SCARF",
)
TRUE_PROP_DISPLAY_TOKENS = (
    "照片",
    "文件",
    "报告",
    "记录页",
    "信",
    "信件",
    "挂号单",
    "手机",
    "香烟",
    "打火机",
    "丝巾",
)
PHONE_PROP_ID_TOKENS = ("PHONE", "SMARTPHONE", "MOBILE")
PHONE_PROP_DISPLAY_TOKENS = ("手机", "电话")
PHOTO_PROP_ID_TOKENS = ("PHOTO", "DRAWING")
PHOTO_PROP_DISPLAY_TOKENS = ("照片", "相片", "全家福", "儿童画")
SMALL_HANDHELD_PROP_ID_TOKENS = (
    "PREGNANCY_TEST",
    "TEST_STICK",
    "KEY",
    "RING",
    "PILL",
    "MEDICINE",
    "TICKET",
    "NOTE",
    "SLIP",
    "RECEIPT",
    "CARD",
)
SMALL_HANDHELD_PROP_DISPLAY_TOKENS = (
    "验孕棒",
    "钥匙",
    "戒指",
    "药片",
    "药丸",
    "药盒",
    "票",
    "票据",
    "纸条",
    "便签",
    "收据",
    "卡片",
)
COSTUME_MODIFIER_PROP_ID_TOKENS = (
    "DRESS",
    "UNIFORM",
    "WARDROBE",
    "COSTUME",
    "OUTFIT",
    "CLOTHING",
    "TIE",
    "SUIT",
    "SHIRT",
    "SHOE",
)
COSTUME_MODIFIER_DISPLAY_TOKENS = (
    "礼服",
    "连衣裙",
    "校服",
    "学生装",
    "服装",
    "衣服",
    "西装",
    "衬衫",
    "领带",
    "鞋",
)
BUSINESS_MALE_TEMPLATE_TOKENS = (
    "西装",
    "suit",
    "白色衬衫",
    "white shirt",
    "领带",
    "tie",
    "短黑发",
    "short black hair",
    "办公室",
    "office",
    "冷静",
    "calm",
)
ADULT_PROPORTION_RISK_TOKENS = (
    "girl-like",
    "teenage",
    "teenager",
    "childlike",
    "doll body",
    "oversized head",
    "少女感",
    "少女体态",
    "未成年感",
    "儿童化",
    "娃娃身材",
    "大头小身",
)
PRESCHOOL_PROPORTION_RISK_TOKENS = (
    "baby",
    "toddler",
    "infant",
    "chibi",
    "婴儿",
    "婴幼儿",
    "胖婴儿脸",
    "大头娃娃",
    "Q版",
    "短腿婴儿",
)
GENERIC_DISTINCTION_TOKENS = (
    "distinct",
    "different",
    "区分",
    "区别",
    "其他角色",
    "同项目",
)


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    models: list[str]
    temperature: float = 0.55
    timeout: int = 180
    max_retries: int = 2


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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {"raw_text": response.text}
    return data if isinstance(data, dict) else {"raw": data}


def resolve_xai_api_key(cli_value: str = "") -> str:
    key = cli_value.strip() or os.getenv("XAI_API_KEY", "").strip()
    if key and key != "your_xai_api_key_here":
        return key
    raise RuntimeError("XAI_API_KEY 未配置。请在 .env 填入真实 key，或通过 --xai-api-key 显式传入。")


def resolve_openai_api_key(cli_value: str = "") -> str:
    key = cli_value.strip() or os.getenv("OPENAI_API_KEY", "").strip()
    if key and key != "your_openai_api_key_here":
        return key
    raise RuntimeError("OPENAI_API_KEY 未配置。请在 .env 填入真实 key，或通过 --openai-api-key 显式传入。")


def selected_values(raw: str) -> set[str]:
    return {item.strip() for item in str(raw or "").split(",") if item.strip()}


def is_scene_modifier_prop(prop_id: str, profile: dict[str, Any] | None = None, contract: dict[str, Any] | None = None) -> bool:
    """Return True for fixed scene components that should not become prop assets."""
    profile = profile if isinstance(profile, dict) else {}
    upper_id = str(prop_id or "").upper()
    display_text = " ".join(
        str(value or "")
        for value in (
            profile.get("display_name"),
            profile.get("structure"),
            profile.get("material"),
        )
    )
    if any(token in upper_id for token in TRUE_PROP_ID_TOKENS) or any(token in display_text for token in TRUE_PROP_DISPLAY_TOKENS):
        return False
    return any(token in upper_id for token in SCENE_MODIFIER_PROP_ID_TOKENS) or any(
        token in display_text for token in SCENE_MODIFIER_DISPLAY_TOKENS
    )


def is_costume_modifier_prop(prop_id: str, profile: dict[str, Any] | None = None, contract: dict[str, Any] | None = None) -> bool:
    profile = profile if isinstance(profile, dict) else {}
    upper_id = str(prop_id or "").upper()
    display_text = " ".join(
        str(value or "")
        for value in (
            profile.get("display_name"),
            profile.get("structure"),
            profile.get("material"),
        )
    )
    if any(token in upper_id for token in TRUE_PROP_ID_TOKENS) or any(token in display_text for token in TRUE_PROP_DISPLAY_TOKENS):
        return False
    return any(token in upper_id for token in COSTUME_MODIFIER_PROP_ID_TOKENS) or any(
        token in display_text for token in COSTUME_MODIFIER_DISPLAY_TOKENS
    )


def is_non_reference_prop(prop_id: str, profile: dict[str, Any] | None = None, contract: dict[str, Any] | None = None) -> bool:
    return is_scene_modifier_prop(prop_id, profile, contract) or is_costume_modifier_prop(prop_id, profile, contract)


def prop_text_blob(prop_id: str, profile: dict[str, Any] | None = None, contract: dict[str, Any] | None = None) -> tuple[str, str]:
    profile = profile if isinstance(profile, dict) else {}
    contract = contract if isinstance(contract, dict) else {}
    upper_id = str(prop_id or "").upper()
    text = " ".join(
        str(value or "")
        for value in (
            prop_id,
            profile.get("display_name"),
            profile.get("name"),
            profile.get("size"),
            profile.get("structure"),
            profile.get("scale_policy"),
            profile.get("reference_mode"),
            contract.get("position"),
            contract.get("motion_policy"),
            contract.get("visibility_policy"),
            contract.get("controlled_by"),
        )
    )
    return upper_id, text


def is_phone_prop(prop_id: str, profile: dict[str, Any] | None = None, contract: dict[str, Any] | None = None) -> bool:
    profile = profile if isinstance(profile, dict) else {}
    upper_id = str(prop_id or "").upper()
    display_text = " ".join(str(profile.get(key) or "") for key in ("display_name", "name"))
    return any(token in upper_id for token in PHONE_PROP_ID_TOKENS) or any(token in display_text for token in PHONE_PROP_DISPLAY_TOKENS)


def is_photo_prop(prop_id: str, profile: dict[str, Any] | None = None, contract: dict[str, Any] | None = None) -> bool:
    profile = profile if isinstance(profile, dict) else {}
    upper_id = str(prop_id or "").upper()
    display_text = " ".join(str(profile.get(key) or "") for key in ("display_name", "name"))
    return any(token in upper_id for token in PHOTO_PROP_ID_TOKENS) or any(token in display_text for token in PHOTO_PROP_DISPLAY_TOKENS)


def is_small_handheld_prop(prop_id: str, profile: dict[str, Any] | None = None, contract: dict[str, Any] | None = None) -> bool:
    profile = profile if isinstance(profile, dict) else {}
    contract = contract if isinstance(contract, dict) else {}
    if is_non_reference_prop(prop_id, profile, contract) or is_phone_prop(prop_id, profile, contract) or is_photo_prop(prop_id, profile, contract):
        return False
    reference_mode = str(profile.get("reference_mode") or "").strip().lower()
    if reference_mode == "scale_context":
        return True
    if str(profile.get("scale_policy") or "").strip():
        return True
    upper_id, text = prop_text_blob(prop_id, profile, contract)
    if any(token in upper_id for token in SMALL_HANDHELD_PROP_ID_TOKENS):
        return True
    if any(token in text for token in SMALL_HANDHELD_PROP_DISPLAY_TOKENS):
        return True
    handheld_markers = ("手持", "手中", "手里", "手边", "掌心", "手掌", "随持有者手部", "随角色手部")
    size_markers = ("小型", "小道具", "厘米", "cm", "手掌", "手指")
    return any(token in text for token in handheld_markers) and any(token in text for token in size_markers)


def prop_reference_mode(prop: dict[str, Any]) -> str:
    profile = prop.get("profile", {}) if isinstance(prop.get("profile"), dict) else {}
    contracts = prop.get("contracts", []) if isinstance(prop.get("contracts"), list) else []
    first_contract = next((item for item in contracts if isinstance(item, dict)), {})
    prop_id = str(prop.get("prop_id") or first_contract.get("prop_id") or "").strip()
    if is_non_reference_prop(prop_id, profile, first_contract) or is_phone_prop(prop_id, profile, first_contract) or is_photo_prop(prop_id, profile, first_contract):
        return "product"
    explicit = str(profile.get("reference_mode") or "").strip().lower()
    if explicit in {"product", "scale_context"}:
        return explicit
    return "scale_context" if is_small_handheld_prop(prop_id, profile, first_contract) else "product"


def default_scale_policy(name: str) -> str:
    display = str(name or "小型手持道具").strip()
    return (
        f"{display}只占画面很小面积，以成人手掌、手指、身体局部或桌面/床沿作为比例锚点；"
        "不得像遥控器、手机、长尺、大号牌子或玩具一样巨大；剧情细节可辨但不能通过放大道具实现。"
    )


def default_reference_context_policy(name: str) -> str:
    display = str(name or "小型手持道具").strip()
    return (
        f"{display} reference 使用与人物中景镜头相近的摄影距离，可出现手掌、手指、前臂、膝盖、床沿或桌面作为比例锚点；"
        "不生成清晰陌生人脸，不做白底孤立产品图。"
    )


def sanitize_filename(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", str(value or "").strip())
    text = re.sub(r"\s+", "_", text).strip("._ ")
    return text or fallback


def compact_text(text: str, limit: int = 1600) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.S | re.I)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        if start < 0:
            raise
        data, _ = json.JSONDecoder().raw_decode(raw[start:])
    if not isinstance(data, dict):
        raise ValueError("LLM response JSON root must be an object")
    return data


def call_xai_chat_with_fallback(
    *,
    config: LLMConfig,
    messages: list[dict[str, str]],
) -> tuple[str, str]:
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    last_error = ""
    for model in config.models:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": config.temperature,
        }
        response = requests.post(
            XAI_CHAT_COMPLETIONS_URL,
            headers=headers,
            json=payload,
            timeout=max(30, int(config.timeout)),
        )
        data = safe_json(response)
        if response.status_code >= 400:
            last_error = f"HTTP {response.status_code}: {data}"
            if response.status_code == 404 or "model_not_found" in json.dumps(data).lower():
                continue
            raise RuntimeError(last_error)
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first, dict) else {}
            content = str((message or {}).get("content") or "").strip()
            if content:
                return content, model
        last_error = f"empty response from {model}: {data}"
    raise RuntimeError(f"All Grok chat models failed. Last error: {last_error}")


def aspect_ratio_from_size(size: str) -> str:
    text = str(size or "").strip().lower()
    match = re.match(r"^(\d+)\s*x\s*(\d+)$", text)
    if not match:
        return "9:16"
    width = int(match.group(1))
    height = int(match.group(2))
    if width <= 0 or height <= 0:
        return "9:16"
    from math import gcd

    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def is_retryable_error(status_code: int, message: str) -> bool:
    if status_code in {408, 409, 429, 500, 502, 503, 504}:
        return True
    lowered = str(message).lower()
    return any(
        token in lowered
        for token in ("rate limit", "retry after", "temporarily unavailable", "connection reset", "timed out")
    )


def retry_delay_seconds(result: dict[str, Any], default: int) -> int:
    message = json.dumps(result, ensure_ascii=False)
    match = re.search(r"retry after\s+(\d+)\s+seconds", message, re.IGNORECASE)
    if match:
        return max(1, int(match.group(1)))
    return max(1, int(default))


def post_xai_image_generation(
    *,
    api_key: str,
    model: str,
    prompt: str,
    size: str,
    timeout: int,
    max_retries: int,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "prompt": prompt, "n": 1, "aspect_ratio": aspect_ratio_from_size(size)}
    total = max(1, int(max_retries))
    last_result: dict[str, Any] = {}
    for attempt in range(1, total + 1):
        try:
            response = requests.post(
                XAI_IMAGE_GENERATIONS_URL,
                headers=headers,
                json=payload,
                timeout=max(30, int(timeout)),
            )
        except requests.RequestException as exc:
            last_result = {"error": str(exc)}
            if attempt >= total:
                raise RuntimeError(f"Grok 生图请求失败: {exc}") from exc
            time.sleep(min(60, 5 * attempt))
            continue
        result = safe_json(response)
        if response.status_code < 400:
            return result
        last_result = result
        if not is_retryable_error(response.status_code, json.dumps(result, ensure_ascii=False)) or attempt >= total:
            raise RuntimeError(f"Grok 生图失败: HTTP {response.status_code} - {result}")
        time.sleep(retry_delay_seconds(result, default=min(60, 5 * attempt)))
    raise RuntimeError(f"Grok 生图失败: {last_result}")


def post_openai_image_generation(
    *,
    api_key: str,
    model: str,
    prompt: str,
    size: str,
    quality: str,
    output_format: str,
    background: str,
    output_compression: int,
    timeout: int,
    max_retries: int,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    normalized_format = "jpeg" if output_format == "jpg" else str(output_format or "jpeg").strip().lower()
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
        "output_format": normalized_format,
        "background": background,
    }
    if normalized_format in {"jpeg", "webp"}:
        payload["output_compression"] = max(0, min(100, int(output_compression)))
    total = max(1, int(max_retries))
    last_result: dict[str, Any] = {}
    for attempt in range(1, total + 1):
        try:
            response = requests.post(
                OPENAI_IMAGE_GENERATIONS_URL,
                headers=headers,
                json=payload,
                timeout=max(30, int(timeout)),
            )
        except requests.RequestException as exc:
            last_result = {"error": str(exc)}
            if attempt >= total:
                raise RuntimeError(f"OpenAI 生图请求失败: {exc}") from exc
            time.sleep(min(60, 5 * attempt))
            continue
        result = safe_json(response)
        if response.status_code < 400:
            return result
        last_result = result
        if not is_retryable_error(response.status_code, json.dumps(result, ensure_ascii=False)) or attempt >= total:
            raise RuntimeError(f"OpenAI 生图失败: HTTP {response.status_code} - {result}")
        time.sleep(retry_delay_seconds(result, default=min(60, 5 * attempt)))
    raise RuntimeError(f"OpenAI 生图失败: {last_result}")


def summarize_image_response(result: dict[str, Any]) -> dict[str, Any]:
    summary = dict(result)
    data = summary.get("data")
    if isinstance(data, list):
        compact: list[Any] = []
        for item in data:
            if isinstance(item, dict):
                safe_item = dict(item)
                if "b64_json" in safe_item:
                    safe_item["b64_json"] = f"<base64 omitted; {len(str(safe_item.get('b64_json') or ''))} chars>"
                compact.append(safe_item)
            else:
                compact.append(item)
        summary["data"] = compact
    return summary


def extract_image_bytes(result: dict[str, Any]) -> bytes:
    data = result.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"Grok 响应中没有图片 data: {result}")
    first = data[0]
    if not isinstance(first, dict):
        raise RuntimeError(f"Grok 图片 data 格式异常: {result}")
    b64 = str(first.get("b64_json") or "").strip()
    if b64:
        return base64.b64decode(b64)
    url = str(first.get("url") or "").strip()
    if url:
        response = requests.get(url, timeout=180)
        if response.status_code >= 400:
            raise RuntimeError(f"下载 Grok 图片失败: HTTP {response.status_code}, url={url}")
        return response.content
    raise RuntimeError(f"Grok 响应中没有 b64_json 或 url: {result}")


def encode_local_image_as_data_uri(path: Path) -> str:
    raw = path.read_bytes()
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"


def parse_scene_detail(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"scene_detail.txt not found: {path}")
    text = path.read_text(encoding="utf-8")
    matches = list(re.finditer(r"^【(.+?)】\s*$", text, flags=re.MULTILINE))
    scenes: list[dict[str, str]] = []
    for idx, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        description = text[start:end].strip()
        if name and description:
            scenes.append(
                {
                    "scene_id": sanitize_filename(name, f"scene_{idx + 1:02d}"),
                    "name": name,
                    "description": description,
                }
            )
    return scenes


def iter_record_paths(records_dir: Path) -> list[Path]:
    if not records_dir.exists():
        raise FileNotFoundError(f"records dir not found: {records_dir}")
    return sorted(records_dir.glob("*.json"))


def compact_prop_contracts(contracts: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for contract in contracts:
        position = str(contract.get("position") or "").strip()
        motion = str(contract.get("motion_policy") or "").strip()
        visible = contract.get("first_frame_visible")
        text = "；".join(
            part
            for part in [
                f"位置:{position}" if position else "",
                f"首帧可见:{visible}" if visible is not None else "",
                f"运动政策:{motion}" if motion else "",
            ]
            if part
        )
        if text and text not in seen:
            seen.add(text)
            parts.append(text)
        if len(parts) >= 3:
            break
    return "；".join(parts)


def canonical_prop_id(prop_id: str, all_prop_ids: set[str]) -> str:
    if not prop_id.endswith("_01") and f"{prop_id}_01" in all_prop_ids:
        return f"{prop_id}_01"
    return prop_id


def extract_props(records_dir: Path) -> dict[str, dict[str, Any]]:
    raw_profiles: dict[str, dict[str, Any]] = {}
    raw_shots: dict[str, list[str]] = {}
    raw_contracts: dict[str, list[dict[str, Any]]] = {}
    for record_path in iter_record_paths(records_dir):
        shot_id = record_path.stem.replace("_record", "")
        record = read_json(record_path)
        i2v_contract = record.get("i2v_contract", {})
        if not isinstance(i2v_contract, dict):
            continue
        library = i2v_contract.get("prop_library", {})
        if isinstance(library, dict):
            for prop_id, profile in library.items():
                if isinstance(profile, dict):
                    raw_profiles.setdefault(str(prop_id), profile)
                    raw_shots.setdefault(str(prop_id), []).append(shot_id)
        contracts = i2v_contract.get("prop_contract", [])
        if isinstance(contracts, list):
            for item in contracts:
                if isinstance(item, dict):
                    prop_id = str(item.get("prop_id") or "").strip()
                    if prop_id:
                        raw_contracts.setdefault(prop_id, []).append(item)
    all_prop_ids = set(raw_profiles) | set(raw_contracts)
    props: dict[str, dict[str, Any]] = {}
    for prop_id in sorted(all_prop_ids):
        canonical = canonical_prop_id(prop_id, all_prop_ids)
        profile = raw_profiles.get(canonical) or raw_profiles.get(prop_id) or {}
        contracts_for_id = raw_contracts.get(prop_id, []) + ([] if prop_id == canonical else raw_contracts.get(canonical, []))
        if is_non_reference_prop(prop_id, profile, contracts_for_id[0] if contracts_for_id else {}):
            continue
        entry = props.setdefault(
            canonical,
            {
                "prop_id": canonical,
                "aliases": [],
                "profile": raw_profiles.get(canonical, {}),
                "source_prop_ids": [],
                "shots": [],
                "contracts": [],
            },
        )
        if prop_id != canonical:
            entry["aliases"].append(prop_id)
        entry["source_prop_ids"].append(prop_id)
        entry["shots"].extend(raw_shots.get(prop_id, []))
        entry["contracts"].extend(raw_contracts.get(prop_id, []))
        if not entry["profile"] and raw_profiles.get(prop_id):
            entry["profile"] = raw_profiles[prop_id]
    for entry in props.values():
        entry["aliases"] = sorted(set(entry["aliases"]))
        entry["source_prop_ids"] = sorted(set(entry["source_prop_ids"]))
        entry["shots"] = sorted(set(entry["shots"]))
    return props


def load_lock_profiles(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = read_json(path)
    profiles = data.get("profiles") if isinstance(data, dict) else []
    out: dict[str, dict[str, Any]] = {}
    if isinstance(profiles, list):
        for item in profiles:
            if not isinstance(item, dict):
                continue
            for key_name in ("lock_profile_id", "character_id", "name"):
                key = str(item.get(key_name) or "").strip()
                if key:
                    out[key] = item
    return out


def iter_character_nodes_from_records(records_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for path in iter_record_paths(records_dir):
        record = read_json(path)
        anchor = record.get("character_anchor", {})
        buckets: list[Any] = []
        if isinstance(anchor, dict):
            buckets.append(anchor.get("primary"))
            secondary = anchor.get("secondary")
            if isinstance(secondary, list):
                buckets.extend(secondary)
        for item in buckets:
            if not isinstance(item, dict):
                continue
            key = (
                str(item.get("character_id") or "").strip(),
                str(item.get("name") or "").strip(),
                str(item.get("lock_profile_id") or "").strip(),
            )
            if not any(key) or key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def character_needs_identity_asset(node: dict[str, Any], lock_profile: dict[str, Any] | None = None) -> bool:
    lock_id = str(node.get("lock_profile_id") or "").strip()
    if node.get("lock_prompt_enabled") is False and not lock_id:
        return False
    return bool(lock_id or lock_profile or str(node.get("visual_anchor") or "").strip())


def normalize_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    parts = re.split(r"[、,;；]\s*", text)
    return [part.strip() for part in parts if part.strip()]


def is_structured_contrast_blob(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return (
        text.startswith("{")
        or text.startswith("[")
        or ("'pair'" in lowered and "'forbidden'" in lowered)
        or ('"pair"' in lowered and '"forbidden"' in lowered)
    )


def character_source_defaults(source: dict[str, Any]) -> dict[str, str]:
    character_id = str(source.get("character_id") or source.get("id") or "").strip()
    name = str(source.get("name") or character_id).strip()
    combined = " ".join(
        str(source.get(key) or "")
        for key in ("profile_text", "visual_anchor", "character_id", "name")
    )
    role_key = ""
    if "SHEN_NIANGE" in character_id or name == "沈念歌":
        role_key = "shen_niange"
    elif "SHEN_ZHIYU" in character_id or name == "沈知予":
        role_key = "shen_zhiyu"
    elif "LU_JINGCHEN" in character_id or name == "陆景琛":
        role_key = "lu_jingchen"
    elif "ZHAO_YIMING" in character_id or name == "赵一鸣":
        role_key = "zhao_yiming"
    elif "沈念歌" in combined:
        role_key = "shen_niange"
    elif "沈知予" in combined:
        role_key = "shen_zhiyu"
    elif "赵一鸣" in combined:
        role_key = "zhao_yiming"
    elif "陆景琛" in combined:
        role_key = "lu_jingchen"

    if role_key == "shen_niange":
        return {
            "age_band": "26岁成年年轻母亲",
            "face_geometry": "成年女性略带棱角的椭圆脸，颧骨和下颌线自然清楚，气质成熟",
            "hair_silhouette": "黑色低马尾，发量自然，轮廓朴素稳定",
            "body_frame": "165cm左右成年女性正常头身比，肩颈和四肢比例成熟，符合26岁成人体态",
            "wardrobe_signature": "洗得发白的白色短袖T恤、直筒牛仔裤、白色帆布鞋",
            "proportion_contract": "成人正常头身比，头部大小约占全身1/7到1/8；保持成熟肩颈四肢、自然真人身材和明确26岁成年女性比例。",
        }
    if role_key == "shen_zhiyu":
        return {
            "age_band": "4岁半学龄前中班男孩 preschool child",
            "face_geometry": "4岁半学龄前中班男孩脸，脸颊自然圆但不过度圆胖，五官清楚，下巴和牙齿年龄感接近4-5岁儿童",
            "hair_silhouette": "黑色短直发，齐刘海略蓬松，儿童自然发量",
            "body_frame": "4岁半男孩正常儿童头身比，约1:4.7到1:5，腿部长度自然，身体能稳定站立奔跑，不矮胖",
            "wardrobe_signature": "蓝色牛仔背带裤、白色短袖T恤、白色帆布鞋",
            "proportion_contract": "必须像4岁半 kindergarten middle-class preschool child，保持约1:4.7到1:5头身比、自然腿长、清楚五官和写实儿童比例。",
        }
    if role_key == "lu_jingchen":
        return {
            "age_band": "32岁左右成熟男性企业掌权者",
            "face_geometry": "方菱角脸，宽下颌、明显颧骨、眉眼锋利，成熟压迫感强",
            "hair_silhouette": "短黑发侧分，发际线整洁，CEO式硬朗轮廓",
            "body_frame": "高大宽肩、胸背厚实、站姿正面压迫，不拿平板",
            "wardrobe_signature": "深灰定制西装、白衬衫、黑色丝质领带，整体比助理更昂贵硬挺",
            "proportion_contract": "成年男性正常头身比，宽肩长腿，头部不过大；不要生成助理型温和窄肩脸。",
        }
    if role_key == "zhao_yiming":
        return {
            "age_band": "28岁左右年轻男性总裁助理",
            "face_geometry": "窄长椭圆脸，五官端正温和，轮廓比陆景琛柔和年轻",
            "hair_silhouette": "短黑发后梳或偏整齐的商务短发，发型轻薄不过分霸气",
            "body_frame": "中等身高偏瘦、肩宽小于陆景琛，站姿谨慎微前倾",
            "wardrobe_signature": "藏青色单排扣西装、白衬衫、深灰领带，手持黑色平板电脑",
            "proportion_contract": "成年男性正常头身比，助理型窄肩比例；不要生成陆景琛式宽肩霸总脸。",
        }
    return {
        "age_band": str(source.get("age_band") or "符合角色设定的明确年龄段").strip(),
        "face_geometry": f"{name}有可执行的脸型骨相，与其他角色明显不同",
        "hair_silhouette": "发型轮廓来自角色设定，保持本集连续",
        "body_frame": "正常真人头身比，体态符合年龄、职业和剧情身份",
        "wardrobe_signature": "固定服装来自角色设定，同一集内不换装",
        "proportion_contract": "真人写实比例，头部不过大，身体不变形，年龄视觉必须准确。",
    }


def normalize_character_bible_from_source(bible: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(bible)
    defaults = character_source_defaults(source)
    character_id = str(source.get("character_id") or source.get("id") or normalized.get("id") or "").strip()
    known_role = character_id in {
        "SHEN_NIANGE_MAIN",
        "SHEN_ZHIYU_CHILD",
        "LU_JINGCHEN_MAIN",
        "ZHAO_YIMING_ASSISTANT",
    }
    normalized.setdefault("id", source.get("character_id") or source.get("id") or "")
    normalized.setdefault("name", source.get("name") or normalized.get("id") or "")
    for field in ("age_band", "face_geometry", "hair_silhouette", "body_frame", "wardrobe_signature", "proportion_contract"):
        if known_role or len(str(normalized.get(field) or "").strip()) < 4:
            normalized[field] = defaults[field]
    appearance = normalized.get("appearance") if isinstance(normalized.get("appearance"), dict) else {}
    if known_role:
        appearance["face_shape"] = defaults["face_geometry"]
        appearance["hair"] = defaults["hair_silhouette"]
        appearance["body"] = defaults["body_frame"]
        normalized["appearance"] = appearance
    final_replacements: dict[str, str] = {}
    def replace_recursive(value: Any, replacements: dict[str, str]) -> Any:
        if isinstance(value, dict):
            return {key: replace_recursive(item, replacements) for key, item in value.items()}
        if isinstance(value, list):
            return [replace_recursive(item, replacements) for item in value]
        if isinstance(value, str):
            text = value
            for old, new in replacements.items():
                if re.search(r"[A-Za-z]", old):
                    text = re.sub(re.escape(old), new, text, flags=re.I)
                else:
                    text = text.replace(old, new)
            return text
        return value

    if character_id == "SHEN_ZHIYU_CHILD":
        risky_replacements = {
            "baby": "preschool child",
            "babies": "preschool children",
            "toddler": "preschool child",
            "toddlers": "preschool children",
            "infant": "preschool child",
            "infants": "preschool children",
            "chibi": "realistic preschool child",
            "婴儿": "4岁半儿童",
            "幼儿": "学龄前儿童",
            "胖婴儿脸": "圆润儿童脸",
            "大头娃娃": "正常儿童头身比",
            "Q版": "写实",
            "q版": "写实",
            "oversized head": "normal preschool head-to-body ratio",
        }
        final_replacements.update(risky_replacements)
        normalized = replace_recursive(normalized, risky_replacements)
        appearance = normalized.get("appearance") if isinstance(normalized.get("appearance"), dict) else appearance
    if character_id == "SHEN_NIANGE_MAIN":
        adult_replacements = {
            "不少女化": "保持成熟成年女性气质",
            "禁止少女化": "保持成熟成年女性气质",
            "避免少女化": "保持成熟成年女性气质",
            "不儿童化": "保持成年女性比例",
            "禁止儿童化": "保持成年女性比例",
            "避免儿童化": "保持成年女性比例",
            "girl-like": "adult young mother",
            "teenage": "adult",
            "teenager": "adult",
            "childlike": "adult",
            "doll body": "normal adult body",
            "oversized head": "normal adult head-to-body ratio",
            "少女感": "成年女性气质",
            "少女体态": "成年女性体态",
            "未成年感": "成年感",
            "儿童化": "成年女性比例",
            "娃娃身材": "正常成人身材",
            "大头小身": "正常成人头身比",
        }
        final_replacements.update(adult_replacements)
        normalized = replace_recursive(normalized, adult_replacements)
        appearance = normalized.get("appearance") if isinstance(normalized.get("appearance"), dict) else appearance
    anchors = normalize_text_list(normalized.get("distinction_anchors"))
    contrast = source.get("contrast_bible") if isinstance(source.get("contrast_bible"), dict) else {}
    char_contrast = character_contrast_for_id(contrast, str(normalized.get("id") or source.get("character_id") or ""))
    for value in (
        defaults.get("face_geometry"),
        defaults.get("body_frame"),
        defaults.get("wardrobe_signature"),
        char_contrast.get("must_look_like"),
        char_contrast.get("must_not_look_like"),
    ):
        anchors.extend(normalize_text_list(value))
    normalized["distinction_anchors"] = list(dict.fromkeys(item for item in anchors if item))
    forbidden = [item for item in normalize_text_list(normalized.get("pairwise_forbidden_similarity")) if not is_structured_contrast_blob(item)]
    forbidden.extend(normalize_text_list(char_contrast.get("must_not_look_like")))
    normalized["pairwise_forbidden_similarity"] = list(dict.fromkeys(item for item in forbidden if item))
    proportion = str(normalized.get("proportion_contract") or defaults["proportion_contract"])
    prompt = str(normalized.get("portrait_prompt") or "").strip()
    if proportion and proportion not in prompt:
        normalized["portrait_prompt"] = f"{prompt}。比例契约：{proportion}".strip("。")
    if final_replacements:
        normalized = replace_recursive(normalized, final_replacements)
    return normalized


def character_contrast_for_id(contrast_bible: dict[str, Any], character_id: str) -> dict[str, Any]:
    chars = contrast_bible.get("characters") if isinstance(contrast_bible.get("characters"), dict) else {}
    item = chars.get(character_id) if isinstance(chars, dict) else None
    return item if isinstance(item, dict) else {}


def infer_project_style(*texts: str) -> dict[str, str]:
    combined = " ".join(str(t or "") for t in texts)
    if any(token in combined for token in ("滨海市", "现代中国", "中国都市", "中文短剧")):
        return {"region": "现代中国都市", "forbid_region": "现代日本都市悬疑质感"}
    if any(token in combined for token in ("银座", "东京", "日本")):
        return {"region": "现代日本都市", "forbid_region": ""}
    if any(token in combined for token in ("古代中国", "西汉", "长安")):
        return {"region": "古代中国", "forbid_region": "现代日本都市悬疑质感"}
    return {"region": "写实短剧世界", "forbid_region": ""}


def prop_is_text_heavy(prop_id: str, profile: dict[str, Any]) -> bool:
    upper = prop_id.upper()
    combined = " ".join(str(profile.get(k) or "") for k in ("display_name", "structure", "material"))
    return any(token in upper for token in TEXT_HEAVY_PROP_TOKENS) or any(
        token in combined for token in ("报告", "文件", "短信", "网页", "表格", "登记", "DNA")
    )


def prop_is_photo(prop_id: str, profile: dict[str, Any]) -> bool:
    combined = " ".join(
        str(profile.get(key) or "")
        for key in ("display_name", "structure", "material", "front_description", "back_description")
    )
    return any(token in f"{prop_id} {combined}".lower() for token in ("photo", "照片", "相片"))


def heuristic_character_bible(
    *,
    character_id: str,
    name: str,
    profile_text: str,
    lock_profile: dict[str, Any] | None = None,
    visual_anchor: str = "",
    project_style: dict[str, str] | None = None,
    model: str = "heuristic",
) -> dict[str, Any]:
    profile = lock_profile or {}
    anchor = visual_anchor or str(profile.get("visual_anchor") or "")
    source = compact_text(" ".join([anchor, profile_text]), 900)
    defaults = character_source_defaults(
        {
            "character_id": character_id,
            "name": name,
            "profile_text": profile_text,
            "visual_anchor": anchor,
        }
    )
    fixed_costume = anchor or "低饱和写实服装，符合角色年龄、职业、阶层和本集连续性"
    region = (project_style or {}).get("region", "写实短剧世界")
    prompt = (
        f"{name}，{source}。{region}写实电影角色定妆照，脸部清晰，"
        f"{defaults['face_geometry']}，{defaults['body_frame']}，{defaults['wardrobe_signature']}。"
        f"比例契约：{defaults['proportion_contract']}。"
        "三分之二正面，大半身构图，真实皮肤纹理，固定同一套服装，低饱和自然光影，ar 9:16, 8k"
    )
    return {
        "version": 1,
        "asset_type": "character",
        "id": character_id,
        "name": name,
        "created_at": datetime.now().isoformat(),
        "llm_model": model,
        "source_policy": "record_is_source_of_truth; bible_adds_visual_specificity_only",
        "age_band": defaults["age_band"],
        "face_geometry": defaults["face_geometry"],
        "hair_silhouette": defaults["hair_silhouette"],
        "body_frame": defaults["body_frame"],
        "wardrobe_signature": defaults["wardrobe_signature"],
        "proportion_contract": defaults["proportion_contract"],
        "pairwise_forbidden_similarity": [],
        "appearance": {
            "face_shape": defaults["face_geometry"],
            "facial_features": anchor or "五官自然写实，眼神与身份气质一致",
            "hair": defaults["hair_silhouette"],
            "skin": "真实皮肤纹理，低饱和自然肤色，不过度磨皮",
            "body": defaults["body_frame"],
            "expression": "表情克制，符合剧情压力，不夸张摆拍",
        },
        "costume": {
            "fixed_outfit": fixed_costume,
            "colors": "低饱和现实颜色",
            "materials": "现实布料材质，纹理可辨",
            "wardrobe_continuity": "同一集内保持这一套服装，除非原剧本明确换装",
        },
        "distinction_anchors": [name, anchor] if anchor else [name],
        "forbidden_drift": ["年龄漂移", "脸型漂移", "服装时代错误", "过度美颜", "候选服装二选一"],
        "portrait_prompt": prompt,
    }


def heuristic_scene_bible(
    *,
    scene: dict[str, str],
    project_style: dict[str, str] | None = None,
    model: str = "heuristic",
) -> dict[str, Any]:
    region = (project_style or {}).get("region", "写实短剧世界")
    description = scene.get("description", "")
    prompt = (
        f"{scene['name']}，{region}，空场景 establishing reference plate。"
        f"{compact_text(description, 700)}。空间布局、墙面、地面、家具/标识位置清楚，"
        "真实材质、自然光影、低饱和写实电影感，竖屏9:16，无人物，无字幕水印。"
    )
    return {
        "version": 1,
        "asset_type": "scene",
        "id": scene.get("scene_id") or sanitize_filename(scene.get("name", ""), "scene"),
        "name": scene.get("name", ""),
        "created_at": datetime.now().isoformat(),
        "llm_model": model,
        "source_policy": "record_is_source_of_truth; bible_adds_visual_specificity_only",
        "location": scene.get("name", ""),
        "layout": compact_text(description, 320),
        "materials": "按原 scene_detail 中的墙面、地面、门窗、家具和现实材质执行",
        "lighting": "自然或实景可用光，低饱和，稳定不过曝",
        "atmosphere": "写实短剧场景基调，避免海报式夸张装饰",
        "era_region": region,
        "establishing_prompt": prompt,
    }


def heuristic_prop_bible(
    *,
    prop: dict[str, Any],
    model: str = "heuristic",
) -> dict[str, Any]:
    profile = prop.get("profile", {}) if isinstance(prop.get("profile"), dict) else {}
    prop_id = str(prop.get("prop_id") or "").strip()
    display = str(profile.get("display_name") or prop_id).strip()
    contract_text = compact_prop_contracts(prop.get("contracts", []))
    count = str(profile.get("count") or "1件").strip()
    material = str(profile.get("material") or "现实材质").strip()
    structure = str(profile.get("structure") or display).strip()
    reference_mode = prop_reference_mode(prop)
    scale_policy = str(profile.get("scale_policy") or "").strip()
    reference_context_policy = str(profile.get("reference_context_policy") or "").strip()
    if reference_mode == "scale_context":
        scale_policy = scale_policy or default_scale_policy(display)
        reference_context_policy = reference_context_policy or default_reference_context_policy(display)
    text_policy = (
        "表面只允许不可读的灰色排版块，不生成清晰姓名、机构、页眉、号码或正文"
        if prop_is_text_heavy(prop_id, profile)
        else "不添加文字标签、logo、水印或说明字"
    )
    if reference_mode == "scale_context":
        prompt = (
            f"{display}，{count}，{material}，{structure}。{contract_text}。"
            f"{scale_policy}。{reference_context_policy}。{text_policy}。"
            "写实短剧中景比例 reference，竖屏9:16，朴素清楚可复用。"
        )
        shooting_angle = "人物中景距离的比例参考，手掌/手指/身体局部或桌面床沿作为尺度锚点"
    else:
        prompt = (
            f"{display}，{count}，{material}，{structure}。"
            f"{contract_text}。{text_policy}。单一道具产品摄影 reference，"
            "完整居中可见，边缘、厚度、材质和使用痕迹清楚，干净中性背景，竖屏9:16。"
        )
        shooting_angle = "单物体居中，三分之二或正面产品摄影角度，完整可见"
    return {
        "version": 1,
        "asset_type": "prop",
        "id": prop_id,
        "name": display,
        "reference_mode": reference_mode,
        "created_at": datetime.now().isoformat(),
        "llm_model": model,
        "source_policy": "record_is_source_of_truth; bible_adds_visual_specificity_only",
        "count": count,
        "size": str(profile.get("size") or "符合现实比例").strip(),
        "material": material,
        "structure": structure,
        "scale_policy": scale_policy,
        "reference_context_policy": reference_context_policy,
        "wear": "轻微真实使用痕迹，不随机增加装饰",
        "shooting_angle": shooting_angle,
        "readable_text_policy": text_policy,
        "reference_prompt": prompt,
    }


def prop_source_defaults(prop: dict[str, Any]) -> dict[str, Any]:
    profile = prop.get("profile", {}) if isinstance(prop.get("profile"), dict) else {}
    contracts = prop.get("contracts", []) if isinstance(prop.get("contracts"), list) else []
    first_contract = next((item for item in contracts if isinstance(item, dict)), {})
    prop_id = str(prop.get("prop_id") or first_contract.get("prop_id") or "").strip()
    display = str(profile.get("display_name") or prop_id).strip()
    quantity_policy = str(first_contract.get("quantity_policy") or profile.get("quantity_policy") or "").strip()
    count = str(profile.get("count") or "").strip()
    if not count and quantity_policy:
        if "一张" in quantity_policy:
            count = "1张"
        elif "一份" in quantity_policy:
            count = "1份"
        elif "一扇" in quantity_policy:
            count = "1扇"
        elif "一件" in quantity_policy or "只允许这一" in quantity_policy:
            count = "1件"
    if not count:
        count = "1件"
    size = str(profile.get("size") or "符合现实比例").strip()
    material = str(profile.get("material") or "现实材质").strip()
    structure = str(profile.get("structure") or display or prop_id).strip()
    position = str(first_contract.get("position") or "").strip()
    motion_policy = str(first_contract.get("motion_policy") or profile.get("canonical_motion_policy") or "").strip()
    reference_mode = str(profile.get("reference_mode") or "").strip().lower()
    scale_policy = str(profile.get("scale_policy") or "").strip()
    reference_context_policy = str(profile.get("reference_context_policy") or "").strip()
    visibility_policy = str(first_contract.get("visibility_policy") or profile.get("visibility_policy") or "").strip()
    upper_id = prop_id.upper()
    if "VEHICLE_DOOR" in upper_id or ("车门" in display and "DOOR" in upper_id):
        size = "车辆门真实尺寸，约一扇公交车或商务车车门的比例，不是手持小道具"
        material = "金属车门框、深色橡胶密封条与安全玻璃"
        structure = "一扇打开或半开的车辆门，门框、玻璃窗、把手和铰链边界清楚"
        shooting_angle = "车辆侧面三分之二角度，车门完整可见，门框和玻璃窗边界清楚"
        if not position or "手边" in position or "桌面" in position:
            position = "车辆侧面入口处或车身门框位置，首帧可见"
        if not motion_policy or "手部" in motion_policy:
            motion_policy = "固定在车身门框上，可保持打开或轻微摆动，不脱离车辆、不新增副本"
    elif "DOOR_PANEL" in upper_id or display in {"门", "门板"}:
        size = "建筑入口门板真实尺寸，接近医院入口单扇门比例，不是手持小道具"
        material = "安全玻璃、银灰金属门框、金属门把或自动门边框"
        structure = "一扇现代医院入口门板，垂直完整，门框、玻璃反光、把手或自动门导轨清楚"
        shooting_angle = "正面或三分之二角度，门板垂直完整可见，门框和导轨边界清楚"
        if not position or "手边" in position or "桌面" in position:
            position = "医院入口门框位置，首帧可见，作为空间结构的一部分"
        if not motion_policy or "手部" in motion_policy:
            motion_policy = "固定在门框轨道或铰链上，保持静止或轻微开合，不新增副本"
    else:
        shooting_angle = "单物体居中，三分之二或正面产品摄影角度，完整可见"

    prop_for_mode = {"prop_id": prop_id, "profile": profile, "contracts": [first_contract] if first_contract else []}
    reference_mode = reference_mode if reference_mode in {"product", "scale_context"} else prop_reference_mode(prop_for_mode)
    if reference_mode == "scale_context":
        scale_policy = scale_policy or default_scale_policy(display or prop_id)
        reference_context_policy = reference_context_policy or default_reference_context_policy(display or prop_id)
        if shooting_angle.startswith("单物体居中"):
            shooting_angle = "人物中景距离的比例参考，手掌/手指/身体局部或桌面床沿作为尺度锚点"

    return {
        "id": prop_id,
        "name": display or prop_id,
        "reference_mode": reference_mode,
        "count": count,
        "size": str(size or profile.get("size") or "符合现实比例").strip(),
        "material": str(material or profile.get("material") or "现实材质").strip(),
        "structure": str(structure or profile.get("structure") or display or prop_id).strip(),
        "scale_policy": scale_policy,
        "reference_context_policy": reference_context_policy,
        "shooting_angle": shooting_angle,
        "position": str(position).strip(),
        "motion_policy": str(motion_policy).strip(),
        "visibility_policy": visibility_policy,
        "first_frame_visible": first_contract.get("first_frame_visible"),
        "quantity_policy": quantity_policy,
    }


def normalize_prop_bible_from_source(bible: dict[str, Any], prop: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(bible)
    defaults = prop_source_defaults(prop)
    generic_tokens = ("手持或桌面小道具", "现实材质", "固定位置可见道具", "符合现实比例", "手边", "桌面", "手部")
    placeholder_values = {"N/A", "NA", "NONE", "NULL", "无", "不适用"}
    for field in ("id", "name", "count", "size", "material", "structure", "reference_mode", "scale_policy", "reference_context_policy"):
        value = str(normalized.get(field) or "").strip()
        if len(value) < 2 or value.upper() in placeholder_values or any(token in value for token in generic_tokens):
            normalized[field] = defaults[field]
    if len(str(normalized.get("wear") or "").strip()) < 2:
        normalized["wear"] = "轻微真实使用痕迹，不随机增加装饰"
    shooting = str(normalized.get("shooting_angle") or "").strip()
    if len(shooting) < 2 or shooting.upper() in placeholder_values or any(token in shooting for token in generic_tokens):
        normalized["shooting_angle"] = defaults["shooting_angle"]
    policy = str(normalized.get("readable_text_policy") or "").strip()
    if len(policy) < 2 or policy.upper() in placeholder_values:
        profile = prop.get("profile", {}) if isinstance(prop.get("profile"), dict) else {}
        normalized["readable_text_policy"] = (
            "表面只允许不可读的灰色排版块，不生成清晰姓名、机构、页眉、号码或正文"
            if prop_is_text_heavy(defaults["id"], profile)
            else "不添加文字标签、logo、水印或说明字"
        )
    source_contract = normalized.get("source_contract") if isinstance(normalized.get("source_contract"), dict) else {}
    for key in ("position", "motion_policy", "first_frame_visible", "quantity_policy"):
        current = str(source_contract.get(key) or "")
        if defaults.get(key) not in ("", None) and (
            not source_contract.get(key) or any(token in current for token in generic_tokens)
        ):
            source_contract[key] = defaults[key]
    if source_contract:
        normalized["source_contract"] = source_contract
    prompt = str(normalized.get("reference_prompt") or "").strip()
    structural_door = "DOOR" in str(defaults.get("id") or "").upper()
    reference_mode = str(normalized.get("reference_mode") or defaults.get("reference_mode") or "product").strip().lower()
    profile = prop.get("profile", {}) if isinstance(prop.get("profile"), dict) else {}
    contracts = prop.get("contracts", []) if isinstance(prop.get("contracts"), list) else []
    first_contract = next((item for item in contracts if isinstance(item, dict)), {})
    prop_id = str(defaults.get("id") or "").strip()
    if is_non_reference_prop(prop_id, profile, first_contract) or is_phone_prop(prop_id, profile, first_contract) or is_photo_prop(prop_id, profile, first_contract):
        reference_mode = "product"
        normalized["reference_mode"] = "product"
        normalized["scale_policy"] = ""
        normalized["reference_context_policy"] = ""
    elif reference_mode == "scale_context":
        normalized["reference_mode"] = "scale_context"
        if len(str(normalized.get("scale_policy") or "").strip()) < 8:
            normalized["scale_policy"] = defaults.get("scale_policy") or default_scale_policy(str(normalized.get("name") or prop_id))
        if len(str(normalized.get("reference_context_policy") or "").strip()) < 8:
            normalized["reference_context_policy"] = defaults.get("reference_context_policy") or default_reference_context_policy(str(normalized.get("name") or prop_id))
    if reference_mode == "scale_context" and ("产品摄影" in prompt or "干净中性背景" in prompt or "白底" in prompt or not prompt):
        prompt = (
            f"{normalized.get('name')}，{normalized.get('count')}，{normalized.get('size')}，"
            f"{normalized.get('material')}，{normalized.get('structure')}。"
            f"{normalized.get('scale_policy')}。{normalized.get('reference_context_policy')}。"
            f"位置:{defaults.get('position')}；运动政策:{defaults.get('motion_policy')}。"
            "写实短剧中景比例 reference，竖屏9:16，朴素清楚可复用。"
        )
    if structural_door and any(token in prompt for token in ("手持", "桌面", "小道具", "现实材质", "固定位置可见道具")):
        prompt = (
            f"{normalized.get('name')}，{normalized.get('count')}，{normalized.get('size')}，"
            f"{normalized.get('material')}，{normalized.get('structure')}。"
            f"位置:{defaults.get('position')}；运动政策:{defaults.get('motion_policy')}。"
            "单一结构件 reference，完整居中可见，边缘、厚度、玻璃/金属材质和真实比例清楚，"
            "干净中性背景，竖屏9:16。"
        )
    source_bits = [
        f"数量:{normalized.get('count')}",
        f"位置:{defaults.get('position')}" if defaults.get("position") else "",
        f"运动政策:{defaults.get('motion_policy')}" if defaults.get("motion_policy") else "",
    ]
    source_line = "；".join(bit for bit in source_bits if bit)
    if source_line and source_line not in prompt:
        normalized["reference_prompt"] = f"{prompt}。源记录硬约束：{source_line}。".strip("。")
    else:
        normalized["reference_prompt"] = prompt
    return normalized


def character_is_adult_female(bible: dict[str, Any]) -> bool:
    text = " ".join(
        str(bible.get(key) or "")
        for key in ("id", "name", "age_band", "proportion_contract", "body_frame")
    ).lower()
    return any(token in text for token in ("沈念歌", "young mother", "成年女性", "adult female", "mother"))


def character_is_preschool_child(bible: dict[str, Any]) -> bool:
    text = " ".join(
        str(bible.get(key) or "")
        for key in ("id", "name", "age_band", "proportion_contract", "body_frame")
    ).lower()
    return any(token in text for token in ("沈知予", "4岁半", "preschool", "学龄前", "小男孩"))


def character_is_mid_teen(bible: dict[str, Any]) -> bool:
    text = " ".join(
        str(bible.get(key) or "")
        for key in ("id", "name", "age_band", "proportion_contract", "body_frame", "portrait_prompt")
    ).lower()
    return any(token in text for token in ("mid-teens", "teen", "adolescent", "14", "15", "16", "17")) or any(
        token in text for token in ("青少年", "中学生", "少女", "十四", "十五", "十六", "十七")
    )


def character_is_business_male(bible: dict[str, Any]) -> bool:
    identity_text = " ".join(str(bible.get(key) or "") for key in ("id", "name")).lower()
    identity_tokens = ("LU_JINGCHEN", "ZHAO_YIMING", "陆景琛", "赵一鸣", "business", "male", "商务男", "职业男性")
    if not any(token.lower() in identity_text for token in identity_tokens):
        return False
    text = json.dumps(bible, ensure_ascii=False).lower()
    return sum(1 for token in BUSINESS_MALE_TEMPLATE_TOKENS if token.lower() in text) >= 4


def json_values_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(json_values_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(json_values_text(item) for item in value)
    if value is None:
        return ""
    return str(value)


def character_positive_risk_text(bible: dict[str, Any]) -> str:
    return json_values_text(
        {
            key: bible.get(key)
            for key in (
                "age_band",
                "face_geometry",
                "hair_silhouette",
                "body_frame",
                "wardrobe_signature",
                "proportion_contract",
                "portrait_prompt",
                "appearance",
                "costume",
            )
        }
    )


def contains_unnegated_token(text: str, token: str) -> bool:
    lowered = text.lower()
    needle = token.lower()
    start = 0
    while True:
        index = lowered.find(needle, start)
        if index < 0:
            return False
        prefix = lowered[max(0, index - 36) : index]
        if not any(
            marker in prefix
            for marker in (
                "不是",
                "非",
                "不",
                "无",
                "避免",
                "禁止",
                "不要",
                "不得",
                "not ",
                "not a ",
                "no ",
                "non-",
                "avoid ",
                "avoids ",
                "forbid ",
                "forbidden ",
                "never ",
            )
        ):
            return True
        start = index + len(needle)


def has_specific_pairwise_contrast(bible: dict[str, Any]) -> bool:
    contrast_fields = " ".join(
        [
            str(bible.get("face_geometry") or ""),
            str(bible.get("body_frame") or ""),
            str(bible.get("wardrobe_signature") or ""),
            " ".join(normalize_text_list(bible.get("distinction_anchors"))),
            " ".join(normalize_text_list(bible.get("pairwise_forbidden_similarity"))),
        ]
    ).lower()
    concrete_tokens = ("陆景琛", "赵一鸣", "宽肩", "窄肩", "方", "菱角", "椭圆", "平板", "ceo", "assistant", "助理", "霸总")
    return sum(1 for token in concrete_tokens if token.lower() in contrast_fields) >= 2


def validate_character_bible(bible: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    appearance = bible.get("appearance") if isinstance(bible.get("appearance"), dict) else {}
    costume = bible.get("costume") if isinstance(bible.get("costume"), dict) else {}
    prompt = str(bible.get("portrait_prompt") or "").strip()
    for field in ("face_shape", "facial_features", "hair", "skin", "body"):
        if len(str(appearance.get(field) or "").strip()) < 6:
            errors.append(f"appearance.{field} 太短或缺失")
    outfit = str(costume.get("fixed_outfit") or "").strip()
    if len(outfit) < 8:
        errors.append("costume.fixed_outfit 缺失或过短")
    lowered = f" {outfit.lower()} "
    if any(token in outfit or token in lowered for token in AMBIGUOUS_WARDROBE_TOKENS):
        errors.append("服装包含 或/or/任选/候选 等不确定表达")
    if len(prompt) < 80:
        errors.append("portrait_prompt 过短")
    for field in ("age_band", "face_geometry", "hair_silhouette", "body_frame", "wardrobe_signature", "proportion_contract"):
        if len(str(bible.get(field) or "").strip()) < 6:
            errors.append(f"{field} 缺失或过短")
    full_text = json_values_text(bible)
    lowered_positive = character_positive_risk_text(bible).lower()
    if character_is_adult_female(bible):
        for token in ADULT_PROPORTION_RISK_TOKENS:
            if contains_unnegated_token(lowered_positive, token):
                errors.append(f"成年女性比例契约含风险词: {token}")
                break
        if not any(token in full_text for token in ("成年", "adult", "26岁")):
            errors.append("成年女性必须明确成人年龄/身份")
    if character_is_preschool_child(bible):
        for token in PRESCHOOL_PROPORTION_RISK_TOKENS:
            if contains_unnegated_token(lowered_positive, token):
                errors.append(f"4岁半儿童比例契约含低龄/大头风险词: {token}")
                break
        if not any(token in full_text for token in ("4岁半", "preschool", "学龄前")):
            errors.append("儿童角色必须明确 4岁半/preschool，不可泛化为婴幼儿")
    if character_is_business_male(bible) and not has_specific_pairwise_contrast(bible):
        errors.append("商务男性角色共享模板过强，缺少具体 pairwise 反差锚点")
    return errors


def validate_scene_bible(bible: dict[str, Any], project_style: dict[str, str] | None = None) -> list[str]:
    errors: list[str] = []
    name = str(bible.get("name") or bible.get("location") or "").strip()
    prompt = str(bible.get("establishing_prompt") or "").strip()
    if not name or name in ABSTRACT_SCENE_NAMES:
        errors.append("scene name 必须是具体地点，不能是抽象功能名")
    for field in ("layout", "materials", "lighting", "atmosphere", "era_region"):
        if len(str(bible.get(field) or "").strip()) < 6:
            errors.append(f"{field} 太短或缺失")
    forbidden = str((project_style or {}).get("forbid_region") or "").strip()
    if forbidden and forbidden in prompt:
        errors.append(f"scene prompt 出现地域/时代漂移: {forbidden}")
    if len(prompt) < 80:
        errors.append("establishing_prompt 过短")
    return errors


def validate_prop_bible(bible: dict[str, Any], *, prop_id: str = "") -> list[str]:
    errors: list[str] = []
    if len(str(bible.get("count") or "").strip()) < 1:
        errors.append("count 缺失")
    if len(str(bible.get("material") or "").strip()) < 1:
        errors.append("material 缺失")
    for field in ("structure", "shooting_angle", "readable_text_policy"):
        if len(str(bible.get(field) or "").strip()) < 2:
            errors.append(f"{field} 缺失")
    reference_mode = str(bible.get("reference_mode") or "product").strip().lower()
    if reference_mode not in {"product", "scale_context"}:
        errors.append("reference_mode 必须是 product 或 scale_context")
    if reference_mode == "scale_context":
        if len(str(bible.get("scale_policy") or "").strip()) < 8:
            errors.append("scale_context 道具必须声明 scale_policy")
        if len(str(bible.get("reference_context_policy") or "").strip()) < 8:
            errors.append("scale_context 道具必须声明 reference_context_policy")
    prompt = str(bible.get("reference_prompt") or "").strip()
    if len(prompt) < 60:
        errors.append("reference_prompt 过短")
    if any(token in str(prop_id or bible.get("id") or "").upper() for token in TEXT_HEAVY_PROP_TOKENS):
        bad_tokens = ("清晰可读姓名", "清晰可读机构", "页眉清晰", "姓名清晰", "机构名清晰")
        if any(token in prompt for token in bad_tokens):
            errors.append("文本/报告类道具不得强制生成清晰可读姓名、机构或页眉")
        policy = str(bible.get("readable_text_policy") or "")
        if not any(token in policy for token in ("不可读", "模糊", "灰色排版块")):
            errors.append("文本/报告类道具必须声明不可读文字策略")
    return errors


def character_bible_messages(source: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "你是电影短剧角色定妆设计师。只输出 JSON 对象，不要 Markdown。"
        "你只能补充视觉细节，不能改剧情、身份、年龄、关系或事件。"
        "服装必须是单一明确方案，禁止 或/or/任选/候选。"
        "必须写可执行的脸型、五官、发型、体态和头身比例，不写抽象气质词。"
    )
    user = (
        "为下面角色生成 visual bible。JSON 字段必须包含："
        "asset_type,id,name,age_band,face_geometry,hair_silhouette,body_frame,wardrobe_signature,"
        "proportion_contract,pairwise_forbidden_similarity,"
        "appearance(face_shape,facial_features,hair,skin,body,expression),"
        "costume(fixed_outfit,colors,materials,wardrobe_continuity),distinction_anchors,"
        "forbidden_drift,portrait_prompt。\n"
        "如果角色资料中有 character_contrast_bible，必须严格采用其中的 must_look_like / must_not_look_like。"
        "成年角色必须写正常成人头身比；4岁半儿童必须写 preschool child 正常儿童比例，不可写婴儿、toddler、Q版或大头娃娃。\n\n"
        f"项目风格: {json.dumps(source.get('project_style', {}), ensure_ascii=False)}\n"
        f"角色资料: {json.dumps(source, ensure_ascii=False, indent=2)[:7000]}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def scene_bible_messages(source: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "你是电影美术与空间设计师。只输出 JSON 对象，不要 Markdown。"
        "只能补充空间视觉细节，不能加入人物动作或改剧情。"
    )
    user = (
        "为下面场景生成 visual bible。JSON 字段必须包含："
        "asset_type,id,name,location,layout,materials,lighting,atmosphere,era_region,establishing_prompt。"
        "location/name 必须是具体地点。establishing_prompt 必须适合空场景 reference image。\n\n"
        f"项目风格: {json.dumps(source.get('project_style', {}), ensure_ascii=False)}\n"
        f"场景资料: {json.dumps(source, ensure_ascii=False, indent=2)[:7000]}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def prop_bible_messages(source: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "你是短剧道具美术设计师。只输出 JSON 对象，不要 Markdown。"
        "Record 中的数量、位置、运动政策是硬约束，不能改。"
        "报告、短信、网页、DNA报告等文本类道具只允许不可读排版块。"
    )
    user = (
        "为下面道具生成 visual bible。JSON 字段必须包含："
        "asset_type,id,name,count,size,material,structure,wear,shooting_angle,"
        "readable_text_policy,reference_mode,scale_policy,reference_context_policy,reference_prompt。"
        "reference_mode 只能是 product 或 scale_context；小型手持道具使用 scale_context，"
        "允许手掌/身体局部/桌面作为比例锚点但不出现清晰陌生人脸。"
        "手机、照片、儿童画、报告/文件、门/车门/车身结构件必须使用 product，不使用 scale_context。\n\n"
        f"道具资料: {json.dumps(source, ensure_ascii=False, indent=2)[:7000]}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_bible_with_retries(
    *,
    kind: str,
    source: dict[str, Any],
    heuristic: dict[str, Any],
    validate,
    llm_config: LLMConfig | None,
    dry_run: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if dry_run or llm_config is None:
        errors = validate(heuristic)
        return heuristic, {"mode": "dry_run_heuristic" if dry_run else "heuristic", "valid": not errors, "errors": errors}

    if kind == "character":
        messages = character_bible_messages(source)
    elif kind == "scene":
        messages = scene_bible_messages(source)
    elif kind == "prop":
        messages = prop_bible_messages(source)
    else:
        raise ValueError(f"unknown bible kind: {kind}")

    last_errors: list[str] = []
    last_model = ""
    attempts = 0
    while attempts <= max(0, int(llm_config.max_retries)):
        attempts += 1
        raw, model = call_xai_chat_with_fallback(config=llm_config, messages=messages)
        last_model = model
        try:
            bible = extract_json_object(raw)
        except Exception as exc:
            bible = {}
            last_errors = [f"JSON 解析失败: {exc}"]
        else:
            bible.setdefault("version", 1)
            bible.setdefault("asset_type", kind)
            bible["llm_model"] = model
            bible["created_at"] = datetime.now().isoformat()
            bible.setdefault("source_policy", "record_is_source_of_truth; bible_adds_visual_specificity_only")
            if kind == "character":
                bible = normalize_character_bible_from_source(bible, source)
            if kind == "prop":
                bible = normalize_prop_bible_from_source(bible, source)
            last_errors = validate(bible)
            if not last_errors:
                return bible, {"mode": "llm", "valid": True, "attempts": attempts, "model": model, "errors": []}

        if attempts > max(0, int(llm_config.max_retries)):
            break
        repair = "\n".join(f"- {err}" for err in last_errors[:30])
        messages = messages + [
            {"role": "assistant", "content": raw if "raw" in locals() else "{}"},
            {
                "role": "user",
                "content": (
                    "上一版未通过校验。请完整重写 JSON 对象，只输出 JSON，修复这些问题：\n"
                    f"{repair}"
                ),
            },
        ]
    raise RuntimeError(
        f"{kind} visual bible generation failed after {attempts} attempts "
        f"(last_model={last_model}): {' | '.join(last_errors[:8])}"
    )


def heuristic_character_contrast_bible(characters: list[dict[str, Any]], model: str = "heuristic") -> dict[str, Any]:
    result: dict[str, Any] = {
        "version": 1,
        "asset_type": "character_contrast",
        "created_at": datetime.now().isoformat(),
        "llm_model": model,
        "source_policy": "record_is_source_of_truth; contrast_only_adds_visual_separation",
        "characters": {},
        "pairwise_rules": [],
    }
    for source in characters:
        cid = str(source.get("character_id") or source.get("id") or "").strip()
        if not cid:
            continue
        defaults = character_source_defaults(source)
        result["characters"][cid] = {
            "age_band": defaults["age_band"],
            "must_look_like": [
                defaults["face_geometry"],
                defaults["hair_silhouette"],
                defaults["body_frame"],
                defaults["wardrobe_signature"],
            ],
            "must_not_look_like": normalize_text_list(defaults["proportion_contract"]),
            "camera_priority": "正常真人比例，脸部清楚，头身比例准确",
        }
    if "LU_JINGCHEN_MAIN" in result["characters"] and "ZHAO_YIMING_ASSISTANT" in result["characters"]:
        result["pairwise_rules"].append(
            {
                "characters": ["LU_JINGCHEN_MAIN", "ZHAO_YIMING_ASSISTANT"],
                "rule": "陆景琛必须更成熟、更锋利、更宽肩、更强势；赵一鸣必须更年轻、更温和、更窄肩、更助理感，并以黑色平板作为职业识别物。",
            }
        )
    return result


def validate_character_contrast_bible(contrast: dict[str, Any], expected_ids: list[str]) -> list[str]:
    errors: list[str] = []
    chars = contrast.get("characters") if isinstance(contrast.get("characters"), dict) else {}
    for cid in expected_ids:
        item = chars.get(cid)
        if not isinstance(item, dict):
            errors.append(f"contrast missing character: {cid}")
            continue
        text = json.dumps(item, ensure_ascii=False)
        if len(text) < 80:
            errors.append(f"contrast too short: {cid}")
    if "LU_JINGCHEN_MAIN" in expected_ids and "ZHAO_YIMING_ASSISTANT" in expected_ids:
        combined = json.dumps(contrast, ensure_ascii=False)
        for token in ("宽肩", "窄肩", "平板", "成熟", "年轻"):
            if token not in combined:
                errors.append(f"陆景琛/赵一鸣 contrast 缺少关键差异: {token}")
    return errors


def character_contrast_messages(characters: list[dict[str, Any]], project_style: dict[str, str] | None = None) -> list[dict[str, str]]:
    system = (
        "你是短剧角色组定妆总监。只输出 JSON 对象，不要 Markdown。"
        "你的任务是让同一项目的角色在脸型、年龄感、肩宽、发型、服装识别物和姿态上明显区分。"
        "不能改剧情、身份、关系，只能补视觉差异锚点。"
    )
    user = (
        "为这些角色生成 character_contrast_bible。JSON 必须包含："
        "asset_type,characters,pairwise_rules。characters 的 key 是 character_id，每个 value 必须包含 "
        "age_band,must_look_like(list),must_not_look_like(list),camera_priority。\n"
        "特别规则：陆景琛必须更成熟、更锋利、更宽肩，方/菱角脸，深灰西装，不拿平板，强势 CEO 姿态；"
        "赵一鸣必须更年轻/温和，窄长椭圆脸，肩窄一些，藏青西装，黑色平板是职业识别物，助理谨慎姿态；"
        "沈念歌必须是26岁成年年轻母亲正常成人比例；沈知予必须是4岁半 preschool child，不能是婴儿/toddler/Q版大头。\n\n"
        f"项目风格: {json.dumps(project_style or {}, ensure_ascii=False)}\n"
        f"角色资料: {json.dumps(characters, ensure_ascii=False, indent=2)[:9000]}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_character_contrast_bible(
    *,
    characters: list[dict[str, Any]],
    project_style: dict[str, str],
    llm_config: LLMConfig | None,
    dry_run: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_ids = [str(item.get("character_id") or item.get("id") or "").strip() for item in characters]
    expected_ids = [item for item in expected_ids if item]
    heuristic = heuristic_character_contrast_bible(characters)
    if dry_run or llm_config is None:
        errors = validate_character_contrast_bible(heuristic, expected_ids)
        return heuristic, {"mode": "dry_run_heuristic" if dry_run else "heuristic", "valid": not errors, "errors": errors}
    messages = character_contrast_messages(characters, project_style)
    last_errors: list[str] = []
    last_model = ""
    attempts = 0
    while attempts <= max(0, int(llm_config.max_retries)):
        attempts += 1
        raw, model = call_xai_chat_with_fallback(config=llm_config, messages=messages)
        last_model = model
        try:
            contrast = extract_json_object(raw)
        except Exception as exc:
            contrast = {}
            last_errors = [f"JSON 解析失败: {exc}"]
        else:
            contrast.setdefault("version", 1)
            contrast.setdefault("asset_type", "character_contrast")
            contrast["llm_model"] = model
            contrast["created_at"] = datetime.now().isoformat()
            contrast.setdefault("source_policy", "record_is_source_of_truth; contrast_only_adds_visual_separation")
            merged = heuristic_character_contrast_bible(characters, model=model)
            merged_chars = merged.get("characters", {})
            if isinstance(contrast.get("characters"), dict):
                for cid, item in contrast["characters"].items():
                    if isinstance(item, dict):
                        base = merged_chars.get(cid, {}) if isinstance(merged_chars, dict) else {}
                        merged_chars[cid] = {**base, **item}
            contrast["characters"] = merged_chars
            pairwise_rules = []
            if isinstance(contrast.get("pairwise_rules"), list):
                pairwise_rules.extend(item for item in contrast["pairwise_rules"] if isinstance(item, dict))
            if isinstance(merged.get("pairwise_rules"), list):
                pairwise_rules.extend(item for item in merged["pairwise_rules"] if isinstance(item, dict))
            contrast["pairwise_rules"] = pairwise_rules
            last_errors = validate_character_contrast_bible(contrast, expected_ids)
            if not last_errors:
                return contrast, {"mode": "llm", "valid": True, "attempts": attempts, "model": model, "errors": []}
        if attempts > max(0, int(llm_config.max_retries)):
            break
        repair = "\n".join(f"- {err}" for err in last_errors[:30])
        messages = messages + [
            {"role": "assistant", "content": raw if "raw" in locals() else "{}"},
            {"role": "user", "content": f"上一版未通过校验。完整重写 JSON，只输出 JSON，修复：\n{repair}"},
        ]
    raise RuntimeError(
        f"character contrast bible generation failed after {attempts} attempts "
        f"(last_model={last_model}): {' | '.join(last_errors[:8])}"
    )


def build_character_image_prompt(bible: dict[str, Any], extra_prompt: str = "") -> str:
    appearance = bible.get("appearance") if isinstance(bible.get("appearance"), dict) else {}
    costume = bible.get("costume") if isinstance(bible.get("costume"), dict) else {}
    is_mid_teen = character_is_mid_teen(bible) and not character_is_preschool_child(bible)

    def clean_prompt_text(value: Any) -> str:
        text = str(value or "")
        if not is_mid_teen:
            return text
        replacements = {
            "childish cheeks": "soft youthful adolescent cheeks",
            "childish cheek": "soft youthful adolescent cheek",
            "childish": "youthful adolescent",
            "immature rounded features": "age-appropriate young teen rounded features",
            "immature features": "age-appropriate young teen features",
            "immature": "young teen",
            "child extremes": "age extremes",
            "儿童化": "低龄化",
            "幼儿化": "低龄化",
            "小孩": "青少年",
        }
        for old, new in replacements.items():
            text = re.sub(re.escape(old), new, text, flags=re.I)
        return text

    anchors = [clean_prompt_text(item) for item in normalize_text_list(bible.get("distinction_anchors")) if not is_structured_contrast_blob(item)]
    forbidden_similarity = [
        clean_prompt_text(item)
        for item in normalize_text_list(bible.get("pairwise_forbidden_similarity"))
        if not is_structured_contrast_blob(item)
    ]
    extra = f"\n补充要求：{extra_prompt.strip()}" if extra_prompt.strip() else ""
    if character_is_preschool_child(bible):
        age_proportion_requirement = (
            "4岁半儿童保持幼儿园中班年龄感、写实1:4.7到1:5头身比、自然腿长和清楚五官，"
            "不能婴儿化、toddler化、Q版化或大头娃娃化。"
        )
    else:
        if is_mid_teen:
            age_proportion_requirement = (
                "青少年/中学生角色必须清楚读作13-15岁阶段，接近14岁初中生；保持写实青少年脸部骨相、较长四肢、约7头身比例，"
                "不要成人化，也不要低龄化成小学生或幼儿大头比例。"
            )
        else:
            age_proportion_requirement = "成年人保持成熟成人比例；未成年角色保持其明确年龄段的写实比例，不要成人化、幼儿化或Q版化。"
    age_band = clean_prompt_text(bible.get("age_band", ""))
    face_geometry = clean_prompt_text(bible.get("face_geometry", ""))
    face_shape = clean_prompt_text(appearance.get("face_shape", ""))
    facial_features = clean_prompt_text(appearance.get("facial_features", ""))
    hair_silhouette = clean_prompt_text(bible.get("hair_silhouette", ""))
    hair = clean_prompt_text(appearance.get("hair", ""))
    skin = clean_prompt_text(appearance.get("skin", ""))
    body_frame = clean_prompt_text(bible.get("body_frame", ""))
    body = clean_prompt_text(appearance.get("body", ""))
    expression = clean_prompt_text(appearance.get("expression", ""))
    proportion_contract = clean_prompt_text(bible.get("proportion_contract", ""))
    wardrobe_signature = clean_prompt_text(bible.get("wardrobe_signature", ""))
    portrait_prompt = clean_prompt_text(bible.get("portrait_prompt", ""))
    return f"""根据下面的角色 visual bible，生成一张用于 AI 短剧 I2V 的角色身份参考图。

角色 ID：{bible.get("id", "")}
角色名：{bible.get("name", "")}
年龄段：{age_band}

容貌：
- 脸型几何：{face_geometry}
- 脸型骨相：{face_shape}
- 五官：{facial_features}
- 发型轮廓：{hair_silhouette}
- 发型：{hair}
- 皮肤：{skin}
- 身体框架：{body_frame}
- 体态：{body}
- 表情：{expression}
- 头身比例契约：{proportion_contract}

服饰：
- 服装识别物：{wardrobe_signature}
- 固定服装：{costume.get("fixed_outfit", "")}
- 颜色：{costume.get("colors", "")}
- 材质：{costume.get("materials", "")}
- 连续性：{costume.get("wardrobe_continuity", "")}

区别锚点：{"、".join(str(x) for x in anchors if str(x).strip())}
禁止相似项：{"、".join(str(x) for x in forbidden_similarity if str(x).strip())}

画面 prompt：
{portrait_prompt}

硬性画面要求：
- 画面中只有这一个人物，不出现其他人、镜中人物、照片人物或背景人群。
- 固定使用 70mm/85mm 人像镜头感，相机在胸口高度，避免广角畸变、俯拍大头、近距离夸张透视。
- 全身或膝上稳定构图，头部到脚/膝上的比例自然；头部大小不得超过真人年龄对应的合理比例。
- 竖屏 9:16，三分之二正面或轻微侧身，脸部清晰可见。
- 严格保持脸型、五官、发型、肤质、体态和固定服装；同一集内不要换装。
- 严格遵守年龄视觉与头身比例契约；{age_proportion_requirement}
- 如有禁止相似项，必须主动避开，不要生成成同项目另一个角色的脸型、年龄感、肩宽、姿态或道具。
- 写实电影感，低饱和，真实皮肤纹理，自然光影，服装轮廓稳定清楚。
- 不添加文字、logo、水印、边框、海报标题、夸张妆容、卡通感、二次元感或游戏建模感。
- 手部如入镜必须自然真实，不允许多指、缺指、粘连、畸形手或额外肢体。{extra}
"""


def local_character_image_preflight(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "image_exists": path.exists(),
        "file_size": path.stat().st_size if path.exists() else 0,
        "format_ok": False,
        "width": 0,
        "height": 0,
        "errors": [],
    }
    if not path.exists():
        report["errors"].append("image file missing")
        return report
    if path.stat().st_size <= 0:
        report["errors"].append("image file empty")
        return report
    try:
        from PIL import Image

        with Image.open(path) as image:
            report["width"], report["height"] = image.size
            report["format_ok"] = image.width > 0 and image.height > 0
    except Exception as exc:
        report["errors"].append(f"image parse failed: {exc}")
    return report


def default_character_qa_report(
    *,
    character_id: str,
    provider: str,
    model: str,
    status: str,
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    failed = bool(reasons)
    return {
        "character_id": character_id,
        "provider": provider,
        "model": model,
        "status": status,
        "age_match": not failed,
        "gender_match": not failed,
        "face_visible": not failed,
        "body_proportion_ok": not failed,
        "wardrobe_match": not failed,
        "identity_distinctiveness": not failed,
        "failure_reasons": reasons or [],
        "created_at": datetime.now().isoformat(),
    }


def character_visual_qa_prompt(
    *,
    bible: dict[str, Any],
    contrast_bible: dict[str, Any] | None = None,
) -> str:
    contrast = character_contrast_for_id(contrast_bible or {}, str(bible.get("id") or ""))
    age_rule = (
        "For a 4.5-year-old, fail if the child appears younger than 4, has overly infant-like round cheeks, "
        "a squat low-age body, very short legs, or a head-to-body ratio outside roughly 1:4.7 to 1:5. "
        "A passing 4.5-year-old should read as kindergarten middle/upper class age with clear facial features and stable standing posture. "
        if character_is_preschool_child(bible)
        else ""
    )
    if character_is_mid_teen(bible) and not character_is_preschool_child(bible):
        age_rule += (
            "For a mid-teens character, pass only if the person clearly reads as about 13-15 years old with realistic adolescent "
            "facial structure, age-appropriate school uniform styling, longer adolescent limbs, and roughly seven-head proportion. "
            "Fail if the image reads as an elementary-school child, preschool child, adult woman, chibi, doll-like, or sexualized. "
        )
    return (
        "You are a strict character reference image QA reviewer. Return JSON only. "
        "Check whether the image matches the character visual bible for short-video I2V identity locking. "
        "Required JSON fields: age_match, gender_match, face_visible, body_proportion_ok, wardrobe_match, "
        "identity_distinctiveness, failure_reasons(list), repair_prompt.\n"
        "Fail body_proportion_ok if an adult looks like a teenager/child or has an oversized head, "
        "or if a child/teen has a chibi, doll-like, or big-head body. "
        f"{age_rule}"
        "Fail identity_distinctiveness if the character can easily be confused with forbidden peer anchors.\n\n"
        f"Character bible: {json.dumps(bible, ensure_ascii=False)[:5000]}\n"
        f"Contrast anchors: {json.dumps(contrast, ensure_ascii=False)[:2000]}"
    )


def call_openai_character_visual_qa(
    *,
    api_key: str,
    model: str,
    image_path: Path,
    bible: dict[str, Any],
    contrast_bible: dict[str, Any] | None,
    timeout: int = 120,
) -> dict[str, Any]:
    prompt = character_visual_qa_prompt(bible=bible, contrast_bible=contrast_bible)
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": encode_local_image_as_data_uri(image_path)}},
                ],
            }
        ],
    }
    response = requests.post(
        OPENAI_CHAT_COMPLETIONS_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=max(30, int(timeout)),
    )
    data = safe_json(response)
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI character visual QA failed: HTTP {response.status_code}: {data}")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"OpenAI character visual QA empty response: {data}")
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    content = str((message or {}).get("content") or "").strip()
    qa = extract_json_object(content)
    for key in ("age_match", "gender_match", "face_visible", "body_proportion_ok", "wardrobe_match", "identity_distinctiveness"):
        qa[key] = bool(qa.get(key))
    reasons = qa.get("failure_reasons")
    qa["failure_reasons"] = [str(x) for x in reasons] if isinstance(reasons, list) else []
    qa["provider"] = "openai"
    qa["model"] = model
    qa["created_at"] = datetime.now().isoformat()
    qa["status"] = "passed" if all(
        qa.get(key)
        for key in ("age_match", "gender_match", "face_visible", "body_proportion_ok", "wardrobe_match", "identity_distinctiveness")
    ) else "failed"
    return qa


def build_character_repair_prompt(qa_report: dict[str, Any]) -> str:
    reasons = qa_report.get("failure_reasons") if isinstance(qa_report.get("failure_reasons"), list) else []
    repair = str(qa_report.get("repair_prompt") or "").strip()
    reason_text = "；".join(str(x) for x in reasons if str(x).strip())
    pieces = [
        "上一张角色参考图未通过视觉 QA，请重生并修复。",
        f"失败原因：{reason_text}" if reason_text else "",
        f"QA repair prompt：{repair}" if repair else "",
        "保持角色身份与服装不变，只修正脸型差异、年龄感、头身比例、构图和可辨识度。",
    ]
    return "\n".join(piece for piece in pieces if piece)


def build_scene_image_prompt(bible: dict[str, Any], extra_prompt: str = "") -> str:
    extra = f"\n补充要求：{extra_prompt.strip()}" if extra_prompt.strip() else ""
    return f"""根据下面的场景 visual bible，生成一张可复用的 AI 短剧场景 reference image。

场景名：{bible.get("name") or bible.get("location") or ""}
地点：{bible.get("location", "")}

空间设定：
- 布局：{bible.get("layout", "")}
- 材质：{bible.get("materials", "")}
- 光线：{bible.get("lighting", "")}
- 氛围：{bible.get("atmosphere", "")}
- 时代地域：{bible.get("era_region", "")}

画面 prompt：
{bible.get("establishing_prompt", "")}

硬性画面要求：
- 只生成空场景，不出现任何人物、人体局部、倒影人物、照片人物或背景人群。
- 竖屏 9:16，写实电影感，低饱和，真实光影。
- 画面是稳定的 establishing reference plate，空间结构、墙面、地板、家具位置清晰可复用。
- 不生成剧情动作，不要戏剧化烟雾、夸张霓虹、强烈镜头畸变或过度装饰。
- 画面内没有字幕、标题、镜头编号、水印、logo、说明文字、海报字。
- 如果出现环境文字，只能是极小且自然的背景标识，不要成为画面主体。
- 保持材质清楚：木纹、织物、皮革、玻璃、墙面各自可辨。
- 不要拼贴、分屏、多格漫画或 contact sheet。{extra}
"""


def build_prop_image_prompt(bible: dict[str, Any], extra_prompt: str = "") -> str:
    extra = f"\n补充要求：{extra_prompt.strip()}" if extra_prompt.strip() else ""
    reference_mode = str(bible.get("reference_mode") or "product").strip().lower()
    if reference_mode == "scale_context":
        return f"""根据下面的道具 visual bible，生成一张可复用的 AI 短剧小型手持道具比例 reference image。

道具 ID：{bible.get("id", "")}
道具名：{bible.get("name", "")}

道具设定：
- 数量：{bible.get("count", "")}
- 尺寸：{bible.get("size", "")}
- 材质：{bible.get("material", "")}
- 结构：{bible.get("structure", "")}
- 比例政策：{bible.get("scale_policy", "")}
- 比例参考上下文：{bible.get("reference_context_policy", "")}
- 使用痕迹：{bible.get("wear", "")}
- 拍摄角度：{bible.get("shooting_angle", "")}
- 文字策略：{bible.get("readable_text_policy", "")}

画面 prompt：
{bible.get("reference_prompt", "")}

硬性画面要求：
- 这是 scale-context reference，不是白底孤立产品图；使用与人物中景镜头相近的摄影距离、焦段和构图感。
- 允许出现手掌、手指、前臂、膝盖、床沿或桌面作为比例锚点；禁止出现清晰陌生人脸或可识别身份。
- 道具必须是画面中的小型手持物，只占很小面积；不得贴近镜头、不得微距、不得像遥控器、手机、长尺、大号牌子或玩具一样巨大。
- 剧情细节可以可辨，但不能通过把道具放大到前景来实现清晰。
- 严格遵守数量，除非设定明确写多个，不新增副本；道具必须被手、桌面或床沿真实支撑，不漂浮。
- 不添加文字标签、logo、水印、说明文字、尺寸标尺、拼贴、多视角分屏。
- 竖屏 9:16，reference asset 用途，朴素、清楚、可复用。{extra}
"""
    return f"""根据下面的道具 visual bible，生成一张可复用的 AI 短剧道具 reference image。

道具 ID：{bible.get("id", "")}
道具名：{bible.get("name", "")}

道具设定：
- 数量：{bible.get("count", "")}
- 尺寸：{bible.get("size", "")}
- 材质：{bible.get("material", "")}
- 结构：{bible.get("structure", "")}
- 使用痕迹：{bible.get("wear", "")}
- 拍摄角度：{bible.get("shooting_angle", "")}
- 文字策略：{bible.get("readable_text_policy", "")}

画面 prompt：
{bible.get("reference_prompt", "")}

硬性画面要求：
- 画面中只出现这一个道具，不出现人物、手、身体局部、其他道具、包装盒堆叠或背景杂物。
- 道具居中，完整可见，形状、厚度、边缘、材质和颜色清晰。
- 使用干净中性浅灰背景或简单摄影台，写实产品摄影感，低饱和，自然柔和阴影。
- 严格遵守数量，除非设定明确写多个，不新增副本。
- 报告、文件、短信、网页、DNA 报告等文本类道具只显示不可读排版块，不生成清晰姓名、机构名、页眉或正文。
- 不添加文字标签、logo、水印、说明文字、尺寸标尺、拼贴、多视角分屏。
- 不把道具改成相近但不同的物品；不增加随机花纹、屏幕内容或无关装饰。
- 竖屏 9:16，reference asset 用途，朴素、清楚、可复用。{extra}
"""
