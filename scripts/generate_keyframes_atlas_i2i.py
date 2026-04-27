#!/usr/bin/env python3
"""Generate shot start/end keyframes via Atlas generateImage (gpt-image-2/edit).

This script builds per-shot start/end image edit requests using character reference
images, then polls Atlas prediction results and writes a keyframe manifest.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote_to_bytes, urlparse

import requests

ATLAS_GENERATE_IMAGE_URL = "https://api.atlascloud.ai/api/v1/model/generateImage"
ATLAS_POLL_URL_TMPL = "https://api.atlascloud.ai/api/v1/model/prediction/{prediction_id}"
OPENAI_IMAGE_EDITS_URL = "https://api.openai.com/v1/images/edits"
XAI_IMAGE_EDITS_URL = "https://api.x.ai/v1/images/edits"

DEFAULT_IMAGE_MODEL = "atlas-openai"
DEFAULT_MODEL = "openai/gpt-image-2/edit"
DEFAULT_OPENAI_MODEL = "gpt-image-2"
DEFAULT_XAI_MODEL = "grok-imagine-image"
DEFAULT_RECORDS_DIR = (
    "SampleChapter_项目文件整理版/06_当前项目的视觉与AI执行层文档/records"
)
DEFAULT_CHARACTER_LOCK_FILE = (
    "SampleChapter_项目文件整理版/06_当前项目的视觉与AI执行层文档/"
    "35_character_lock_profiles_v1.json"
)


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def require_api_key() -> str:
    key = os.getenv("ATLASCLOUD_API_KEY", "").strip()
    if not key or key == "your_atlas_cloud_api_key_here":
        raise RuntimeError(
            "ATLASCLOUD_API_KEY 未配置。请在 .env 填入真实 key，"
            "或在环境变量中导出 ATLASCLOUD_API_KEY。"
        )
    return key


def resolve_xai_api_key(cli_value: str, required: bool) -> str:
    key = cli_value.strip() or os.getenv("XAI_API_KEY", "").strip()
    if key and key != "your_xai_api_key_here":
        return key
    if required:
        raise RuntimeError(
            "XAI_API_KEY 未配置。请在 .env 填入真实 key，"
            "或通过 --xai-api-key 显式传入。"
        )
    return ""


def resolve_openai_api_key(cli_value: str, required: bool) -> str:
    key = cli_value.strip() or os.getenv("OPENAI_API_KEY", "").strip()
    if key and key != "your_openai_api_key_here":
        return key
    if required:
        raise RuntimeError(
            "OPENAI_API_KEY 未配置。请在 .env 填入真实 key，"
            "或通过 --openai-api-key 显式传入。"
        )
    return ""


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
    raise ValueError(
        f"未知 IMAGE_MODEL: {value!r}。可选: openai, atlas-openai, grok"
    )


def resolve_image_model(args: argparse.Namespace) -> str:
    explicit = str(getattr(args, "image_model", "") or "").strip()
    env_value = os.getenv("IMAGE_MODEL", "").strip()
    provider_value = str(getattr(args, "provider", "") or "").strip()
    chosen = explicit or env_value or provider_value or DEFAULT_IMAGE_MODEL
    return normalize_image_model(chosen)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        return response.json()
    except Exception:
        return {"raw_text": response.text}


def parse_retry_after_seconds(message: str, default: int = 20) -> int:
    match = re.search(r"retry after\s+(\d+)\s+seconds", str(message), re.IGNORECASE)
    if match:
        return max(1, int(match.group(1)))
    return max(1, int(default))


def is_retryable_rate_limit_error(message: str) -> bool:
    lowered = str(message).lower()
    tokens = (
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "rate limit",
        "high demand",
        "retry after",
        "maximum usage size allowed",
        "provisioned throughput",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "timed out",
        "max retries exceeded",
    )
    return any(token in lowered for token in tokens)


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
    # keep order unique
    seen: set[str] = set()
    ordered: list[str] = []
    for s in requested:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    return ordered


def load_character_lock_catalog(profile_file: Path) -> dict[str, dict[str, Any]]:
    if not profile_file.exists():
        return {}
    data = read_json(profile_file)
    profiles = data.get("profiles")
    if not isinstance(profiles, list):
        return {}
    catalog: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        profile_id = str(profile.get("lock_profile_id", "")).strip()
        if profile_id:
            catalog[profile_id] = profile
    return catalog


def load_character_image_map(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError("character image map root must be object")
    out: dict[str, str] = {}
    for k, v in data.items():
        key = str(k).strip()
        val = str(v).strip() if isinstance(v, (str, Path)) else ""
        if key and val:
            out[key] = val
    return out


def encode_local_image_as_data_uri(path: Path) -> str:
    raw = path.read_bytes()
    guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{guessed};base64,{b64}"


def resolve_image_ref(value: str, project_root: Path) -> str:
    v = value.strip()
    if not v:
        return ""
    if v.startswith("http://") or v.startswith("https://") or v.startswith("data:"):
        return v
    p = Path(v).expanduser()
    if not p.is_absolute():
        p = (project_root / p).resolve()
    if p.exists():
        return encode_local_image_as_data_uri(p)
    return v


def first_non_empty(values: list[str]) -> str:
    for value in values:
        if value.strip():
            return value.strip()
    return ""


def merge_character_with_lock(
    node: dict[str, Any],
    lock_catalog: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    merged = json.loads(json.dumps(node, ensure_ascii=False))
    lock_id = str(merged.get("lock_profile_id", "")).strip()
    lock_profile = lock_catalog.get(lock_id, {})
    if not lock_profile:
        return merged

    for key in (
        "character_id",
        "name",
        "visual_anchor",
        "appearance_lock_profile",
        "costume_lock_profile",
        "appearance_anchor_tokens",
    ):
        if key not in merged or merged.get(key) in (None, "", [], {}):
            if key in lock_profile:
                merged[key] = lock_profile[key]
    return merged


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


def dialogue_visible_names(dialogue_lines: Any) -> list[str]:
    if not isinstance(dialogue_lines, list):
        return []
    names: list[str] = []
    for item in dialogue_lines:
        if not isinstance(item, dict):
            continue
        source = normalize_dialogue_source(item.get("source"), item.get("text", ""), item.get("purpose", ""))
        if source == "phone":
            listener = dialogue_listener_name(item)
            if listener:
                names.append(listener)
        elif source == "onscreen":
            speaker = str(item.get("speaker") or "").strip()
            if speaker:
                names.append(speaker)
    return [name for name in dict.fromkeys(names) if name]


def build_remote_dialogue_visual_contract(record: dict[str, Any]) -> str:
    dialogue_language = record.get("dialogue_language", {})
    dialogue_lines = dialogue_language.get("dialogue_lines", []) if isinstance(dialogue_language, dict) else []
    if not isinstance(dialogue_lines, list):
        return ""

    phone_listeners: list[str] = []
    phone_speakers: list[str] = []
    offscreen_listeners: list[str] = []
    offscreen_speakers: list[str] = []
    for item in dialogue_lines:
        if not isinstance(item, dict):
            continue
        source = normalize_dialogue_source(item.get("source"), item.get("text", ""), item.get("purpose", ""))
        listener = dialogue_listener_name(item)
        speaker = str(item.get("speaker") or "").strip()
        if source == "phone":
            if listener:
                phone_listeners.append(listener)
            if speaker:
                phone_speakers.append(speaker)
        elif source == "offscreen":
            if listener:
                offscreen_listeners.append(listener)
            if speaker:
                offscreen_speakers.append(speaker)

    parts: list[str] = []
    phone_listeners = [name for name in dict.fromkeys(phone_listeners) if name]
    phone_speakers = [name for name in dict.fromkeys(phone_speakers) if name]
    if phone_listeners:
        listener_text = "、".join(phone_listeners)
        speaker_text = "、".join(phone_speakers)
        parts.append(
            f"电话构图契约:{listener_text}在画面内接听手机，首帧必须清楚入镜，"
            "手持1部手机贴近耳边或正在接听"
            + (f"；{speaker_text}只作为电话另一端角色，不在画面内，不要分屏，不要第二空间" if speaker_text else "")
        )

    offscreen_listeners = [name for name in dict.fromkeys(offscreen_listeners) if name]
    offscreen_speakers = [name for name in dict.fromkeys(offscreen_speakers) if name]
    if offscreen_listeners:
        listener_text = "、".join(offscreen_listeners)
        speaker_text = "、".join(offscreen_speakers)
        parts.append(
            f"画外声构图契约:{listener_text}在画面内呈现倾听反应，首帧必须清楚入镜"
            + (f"；{speaker_text}不在画面内，不要分屏，不要第二空间" if speaker_text else "")
        )
    return "；".join(parts)


def build_shot_context_text(record: dict[str, Any]) -> str:
    prompt_render = record.get("prompt_render", {})
    shot_execution = record.get("shot_execution", {})
    camera_plan = shot_execution.get("camera_plan", {}) if isinstance(shot_execution, dict) else {}
    dialogue_language = record.get("dialogue_language", {})
    dialogue_lines = dialogue_language.get("dialogue_lines", []) if isinstance(dialogue_language, dict) else []
    visible_dialogue_text = " ".join(dialogue_visible_names(dialogue_lines))
    return " ".join(
        [
            str(prompt_render.get("shot_positive_core", "")) if isinstance(prompt_render, dict) else "",
            str(shot_execution.get("action_intent", "")) if isinstance(shot_execution, dict) else "",
            str(shot_execution.get("emotion_intent", "")) if isinstance(shot_execution, dict) else "",
            str(camera_plan.get("framing_focus", "")) if isinstance(camera_plan, dict) else "",
            visible_dialogue_text,
        ]
    )


def character_node_is_explicit(node: dict[str, Any], context_text: str) -> bool:
    if any(bool(node.get(key)) for key in ("must_appear_in_shot", "prompt_include", "include_in_prompt")):
        return True
    name = str(node.get("name") or "").strip()
    character_id = str(node.get("character_id") or "").strip()
    aliases = [name, character_id]
    if len(name) >= 3:
        aliases.append(name[-2:])
    return any(alias and alias in context_text for alias in dict.fromkeys(aliases))


def infer_ephemeral_character_node(context_text: str) -> dict[str, Any] | None:
    if any(token in context_text for token in ("服务员", "侍者", "酒店员工")):
        return {
            "character_id": "EXTRA_WAITER",
            "name": "服务员",
            "lock_profile_id": "",
            "lock_prompt_enabled": False,
            "visual_anchor": "银座高级酒店服务员，整洁制服，普通工作人员气质，反应真实不过度戏剧化",
            "persona_anchor": ["紧张", "职业化"],
            "speech_style_anchor": ["短促", "慌张"],
        }
    if any(token in context_text for token in ("警员", "警方", "警车", "刑警同事")):
        return {
            "character_id": "EXTRA_POLICE",
            "name": "警员",
            "lock_profile_id": "",
            "lock_prompt_enabled": False,
            "visual_anchor": "日本都市刑侦现场警员，深色制服或便装外套，维持秩序",
            "persona_anchor": ["克制", "执行"],
            "speech_style_anchor": ["简短"],
        }
    if any(token in context_text for token in ("人群", "路人", "客人", "围观")):
        return {
            "character_id": "EXTRA_CROWD",
            "name": "背景人群",
            "lock_profile_id": "",
            "lock_prompt_enabled": False,
            "visual_anchor": "银座酒店或街头背景人群，低调真实，只作为环境反应存在",
            "persona_anchor": ["压低声音", "克制"],
            "speech_style_anchor": ["背景反应"],
        }
    return None


def collect_characters(
    record: dict[str, Any],
    lock_catalog: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    character_anchor = record.get("character_anchor", {})
    out: list[dict[str, Any]] = []
    primary = character_anchor.get("primary")
    if isinstance(primary, dict):
        out.append(merge_character_with_lock(primary, lock_catalog))
    secondary = character_anchor.get("secondary")
    if isinstance(secondary, list):
        for item in secondary:
            if isinstance(item, dict):
                out.append(merge_character_with_lock(item, lock_catalog))
    context_text = build_shot_context_text(record)
    selected = [node for node in out if character_node_is_explicit(node, context_text)]
    if selected:
        return selected
    ephemeral = infer_ephemeral_character_node(context_text)
    if ephemeral is not None:
        return [ephemeral]
    return []


def collect_reference_characters(
    record: dict[str, Any],
    lock_catalog: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    character_anchor = record.get("character_anchor", {})
    out: list[dict[str, Any]] = []
    if not isinstance(character_anchor, dict):
        return out
    primary = character_anchor.get("primary")
    if isinstance(primary, dict):
        out.append(merge_character_with_lock(primary, lock_catalog))
    secondary = character_anchor.get("secondary")
    if isinstance(secondary, list):
        for item in secondary:
            if isinstance(item, dict):
                out.append(merge_character_with_lock(item, lock_catalog))
    return out


def build_character_brief(character: dict[str, Any]) -> str:
    name = str(character.get("name") or character.get("character_id") or "角色").strip()
    appearance = character.get("appearance_lock_profile", {})
    costume = character.get("costume_lock_profile", {})
    tokens = character.get("appearance_anchor_tokens", [])

    ap = appearance if isinstance(appearance, dict) else {}
    cp = costume if isinstance(costume, dict) else {}
    tks = [str(x).strip() for x in (tokens if isinstance(tokens, list) else []) if str(x).strip()]

    parts: list[str] = [f"{name}"]
    if str(ap.get("facial_features", "")).strip():
        parts.append(f"容貌:{ap.get('facial_features')}")
    if str(ap.get("hair_style_color", "")).strip():
        parts.append(f"发型发色:{ap.get('hair_style_color')}")
    if str(ap.get("skin_texture", "")).strip():
        parts.append(f"肤质:{ap.get('skin_texture')}")
    if str(cp.get("outerwear", "")).strip():
        parts.append(f"外层:{cp.get('outerwear')}")
    if str(cp.get("innerwear", "")).strip():
        parts.append(f"内层:{cp.get('innerwear')}")
    if str(cp.get("lower_garment", "")).strip():
        parts.append(f"下装:{cp.get('lower_garment')}")
    if str(cp.get("footwear", "")).strip():
        parts.append(f"鞋履:{cp.get('footwear')}")
    if tks:
        parts.append(f"锚点:{'、'.join(tks)}")
    return sanitize_keyframe_visual_text("；".join(parts))


def shot_has_hand_focus(
    shot_type: str,
    framing: str,
    action: str,
    core: str,
    props: str,
) -> bool:
    combined = " ".join([shot_type, framing, action, core, props])
    hand_focus_tokens = [
        "手部",
        "手指",
        "指腹",
        "掌",
        "抹过",
        "抹",
        "摸",
        "握",
        "捧",
        "端",
        "拿",
    ]
    closeup_tokens = ["特写", "近景", "极近"]
    has_hand_token = any(token in combined for token in hand_focus_tokens)
    has_closeup_token = any(token in shot_type or token in framing for token in closeup_tokens)
    return has_hand_token and (has_closeup_token or "手部" in combined)


def build_hand_constraint_text(
    shot_type: str,
    framing: str,
    action: str,
    core: str,
    props: str,
) -> str:
    parts = [
        "手部约束:人物手部解剖必须真实稳定，每只可见的手都清晰呈现五根手指",
        "禁止缺指、四指、多指、并指、手指粘连、手部扭曲、手掌变形、手部畸形",
    ]
    if shot_has_hand_focus(
        shot_type=shot_type,
        framing=framing,
        action=action,
        core=core,
        props=props,
    ):
        parts.extend(
            [
                "这是手部重点镜头，主手必须完整、清晰、稳定入镜，五根手指清楚可辨",
                "指节、指腹、指甲、掌缘结构自然，手指之间自然分开，不能融合或缺失",
                "不要用遮挡、裁切、运动模糊掩盖手指数量错误",
            ]
        )
    return "；".join(parts)


def sanitize_keyframe_safety_text(text: str) -> str:
    value = str(text or "")
    replacements = {
        "贴近田中健一耳侧": "与田中健一保持克制社交距离低声说话",
        "贴近健一耳侧": "与健一保持克制社交距离低声说话",
        "低语": "低声说话",
        "领带松开垂在他的胸前": "领带略松并清楚可见",
        "松开领带垂在胸前": "领带略松并清楚可见",
        "不出现裸露或性暗示": "衣着完整、保持日常社交距离",
        "必须非情色化安全呈现": "朴素日常呈现",
        "非情色化安全呈现": "朴素日常呈现",
        "非情色化": "朴素日常",
        "未成年稚气": "学生稚嫩感",
        "未成年": "学生",
        "十四岁少女": "中学生",
        "十四岁": "中学生",
        "少女": "学生",
        "姐姐的旧礼服": "灰色外套和素色连衣裙",
        "彩花旧礼服": "灰色外套和素色连衣裙",
        "旧礼服": "素色连衣裙",
        "旧丝质或缎面礼服": "素色连衣裙",
        "丝质礼服": "素色连衣裙",
        "礼服": "连衣裙",
        "丝质": "柔和布料",
        "丝绸": "柔和布料",
        "胸前": "上身前侧",
        "身体": "姿态",
        "银座夜场": "银座都市",
        "夜场": "都市服务业背景",
        "香水": "淡雅气味",
        "威士忌氛围": "暖色灯光氛围",
        "女人味": "成熟感",
        "职业性的亲近感": "职业性的礼貌感",
        "靠近可信赖的人": "站在可信赖的人附近",
        "亲密距离": "日常社交距离",
        "主动编织关系": "主动维持关系",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    value = re.sub(r"贴近([^，,；;。]+?)耳侧", r"与\1保持克制社交距离低声说话", value)
    return value


def sanitize_keyframe_visual_text(text: str) -> str:
    """Keep video/audio language controls out of image-generation prompts."""
    value = sanitize_keyframe_safety_text(text)
    if not value.strip():
        return ""

    value = re.sub(
        r"对白可见人物契约[:：]\s*([^，,；;。]+?)是画面内说话人[^；;。]*?首帧必须清楚入镜[。.]?",
        r"画面人物契约:\1首帧必须清楚入镜",
        value,
    )
    value = re.sub(
        r"对白可见人物契约[:：]\s*([^，,；;。]+?)首帧必须清楚入镜[。.]?",
        r"画面人物契约:\1首帧必须清楚入镜",
        value,
    )

    # These are valid for video/audio/subtitle rendering, but in image prompts they
    # encourage Grok/OpenAI image models to paint captions or narration text.
    drop_terms = (
        "字幕",
        "旁白",
        "对白",
        "台词",
        "普通话",
        "简体中文",
        "模型音频",
        "音频",
        "语言锁",
        "说话人",
        "亲口说出",
        "subtitle",
        "subtitles",
        "caption",
        "captions",
        "dialogue",
        "voiceover",
        "voice-over",
        "narration",
        "spoken",
        "Simplified Chinese",
    )
    fragments = [
        frag.strip()
        for frag in re.split(r"[，,；;。]\s*", value)
        if frag.strip()
    ]
    kept = [
        frag
        for frag in fragments
        if not any(term.lower() in frag.lower() for term in drop_terms)
    ]
    return "，".join(kept).strip("，,；;。 ").strip()


def infer_era_constraint(record: dict[str, Any]) -> str:
    scene_anchor = record.get("scene_anchor", {})
    prompt_render = record.get("prompt_render", {})
    project_meta = record.get("project_meta", {})
    text = " ".join(
        [
            str(scene_anchor.get("scene_name", "")),
            " ".join(str(x) for x in scene_anchor.get("must_have_elements", []) if str(x).strip()),
            str(prompt_render.get("positive_prefix", "")),
            str(prompt_render.get("shot_positive_core", "")),
            " ".join(str(x) for x in project_meta.get("core_selling_points", []) if str(x).strip()),
        ]
    )
    ancient_tokens = ("古代", "西汉", "长安", "穿越", "破庙", "乞丐少年", "布衣")
    modern_tokens = ("现代", "银座", "东京", "酒店", "都市", "刑警", "警车", "公司")
    if any(token in text for token in ancient_tokens):
        return "不要生成现代服装、现代建筑、现代道具或与古代设定冲突的元素。"
    if any(token in text for token in modern_tokens):
        return "不要生成古装、古代建筑、年代错置道具或非现代日本都市环境。"
    return "不要生成与当前故事时代、地域、服装、建筑和道具设定冲突的元素。"


def ensure_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def format_scene_motion_contract_for_keyframe(record: dict[str, Any], phase: str) -> tuple[str, str]:
    contract = record.get("scene_motion_contract", {})
    if not isinstance(contract, dict):
        return "", ""
    scene_mode = str(contract.get("scene_mode") or "").strip()
    policy = str(contract.get("description_policy") or "").strip()
    camera = str(contract.get("camera_motion_allowed") or "").strip()
    static_props = "、".join(ensure_text_list(contract.get("static_props")))
    active_subjects = "、".join(ensure_text_list(contract.get("active_subjects"))) or "无"
    manipulated_props = "、".join(ensure_text_list(contract.get("manipulated_props"))) or "无"
    forbidden = "、".join(ensure_text_list(contract.get("forbidden_scene_motion")))
    parts = [
        f"场景模式:{scene_mode}" if scene_mode else "",
        policy,
        f"镜头运动许可:{camera}" if camera else "",
        f"静态道具:{static_props}" if static_props else "",
        f"可动主体:{active_subjects}",
        f"可动道具:{manipulated_props}",
        f"禁止:{forbidden}" if forbidden else "",
    ]
    text = "；".join([part for part in parts if part])
    if scene_mode == "static_establishing":
        phase_text = (
            "静态场景建立帧：房间和全部道具在第一帧已经存在，数量、位置、形状清楚可见；"
            "不要暗示任何场内物体即将移动、出现或消失。"
        )
    else:
        phase_text = (
            "静态场景中的人物动作帧：只允许人物和人物直接操纵的物体发生动作；"
            "未被人物操纵的场景道具保持静止。"
        )
    return text, phase_text


def build_keyframe_prompt(
    shot_id: str,
    record: dict[str, Any],
    characters: list[dict[str, Any]],
    phase: str,
) -> str:
    scene_anchor = record.get("scene_anchor", {})
    shot_execution = record.get("shot_execution", {})
    continuity_rules = record.get("continuity_rules", {})
    prompt_render = record.get("prompt_render", {})

    scene_name = str(scene_anchor.get("scene_name", "")).strip()
    must_have = "、".join([str(x).strip() for x in scene_anchor.get("must_have_elements", []) if str(x).strip()])
    props = "、".join([str(x).strip() for x in scene_anchor.get("prop_must_visible", []) if str(x).strip()])
    lighting = str(scene_anchor.get("lighting_anchor", "")).strip()

    camera_plan = shot_execution.get("camera_plan", {})
    shot_type = str(camera_plan.get("shot_type", "")).strip()
    movement = str(camera_plan.get("movement", "")).strip()
    framing = str(camera_plan.get("framing_focus", "")).strip()
    action = str(shot_execution.get("action_intent", "")).strip()
    emotion = str(shot_execution.get("emotion_intent", "")).strip()
    static_anchor = record.get("keyframe_static_anchor", {}) if phase == "start" else {}
    if isinstance(static_anchor, dict) and str(static_anchor.get("policy") or "").strip():
        scene_name = str(static_anchor.get("scene_name") or scene_name).strip()
        movement = str(static_anchor.get("movement") or movement).strip()
        framing = str(static_anchor.get("framing_focus") or framing).strip()
        action = str(static_anchor.get("action_intent") or action).strip()
    framing = sanitize_keyframe_visual_text(framing)
    action = sanitize_keyframe_visual_text(action)

    continuity_items = []
    for key in ("character_state_transition", "scene_transition", "prop_continuity"):
        vals = continuity_rules.get(key, [])
        if isinstance(vals, list):
            continuity_items.extend(
                [
                    sanitized
                    for x in vals
                    if (sanitized := sanitize_keyframe_visual_text(str(x).strip()))
                ]
            )
    continuity = "；".join(continuity_items)
    motion_contract, motion_phase_action = format_scene_motion_contract_for_keyframe(record, phase)
    remote_dialogue_visual_contract = build_remote_dialogue_visual_contract(record)
    motion_contract_raw = record.get("scene_motion_contract", {})
    if isinstance(motion_contract_raw, dict) and str(motion_contract_raw.get("scene_mode") or "").strip() == "static_establishing":
        camera_motion = str(motion_contract_raw.get("camera_motion_allowed") or "").strip()
        if camera_motion:
            movement = camera_motion

    style_prefix = sanitize_keyframe_visual_text(
        str(prompt_render.get("positive_prefix", "")).strip()
    )
    core = str(prompt_render.get("shot_positive_core", "")).strip()
    if isinstance(static_anchor, dict) and str(static_anchor.get("positive_core") or "").strip():
        core = str(static_anchor.get("positive_core") or "").strip()
    core = sanitize_keyframe_visual_text(core)
    phase_cn = "镜头起始帧" if phase == "start" else "镜头收尾帧"
    phase_action = (
        "动作刚刚开始，角色处于发力前一瞬，神情与姿态克制蓄势。"
        if phase == "start"
        else "动作已经落点，角色处于动作完成后一瞬，情绪结果清晰。"
    )
    if motion_phase_action:
        phase_action = motion_phase_action
    hand_constraint = build_hand_constraint_text(
        shot_type=shot_type,
        framing=framing,
        action=action,
        core=core,
        props=props,
    )

    character_lines = "；".join([build_character_brief(c) for c in characters]) if characters else "无人物"
    era_constraint = infer_era_constraint(record)
    has_identity_refs = any(
        str(c.get("lock_profile_id") or "").strip()
        or bool(c.get("appearance_lock_profile"))
        or bool(c.get("appearance_anchor_tokens"))
        for c in characters
    )
    reference_instruction = (
        "请严格参考输入人物照片，保持人物面部特征、发型、肤质、服饰细节一致，"
        if has_identity_refs
        else "输入图只作为写实质感、光影和服装材质参考，本镜头人物身份以文字描述为准，"
    )

    no_overlay_text_policy = (
        "纯电影画面要求：画面内没有任何后期叠加文字、标题、镜头编号、水印、logo或说明性文字；"
        "所有文字层都留给后期流程，不在本图生成；"
        "除剧情必需的实体道具文字外，不出现可读文字，实体道具文字必须小而自然地贴合物体。"
    )

    parts: list[str] = [
        phase_cn,
        f"{reference_instruction}{era_constraint}不要生成多余人物。",
        "画面要求：竖屏9:16，写实电影感，低饱和，皮肤与布料纹理真实，稳定无畸变。",
        no_overlay_text_policy,
        f"场景:{scene_name}" if scene_name else "",
        f"场景必须出现:{must_have}" if must_have else "",
        f"关键道具:{props}" if props else "",
        f"光线:{lighting}" if lighting else "",
        f"镜头:{shot_type}；运动:{movement}；构图焦点:{framing}",
        remote_dialogue_visual_contract,
        f"场景运动契约:{motion_contract}" if motion_contract else "",
        f"动作意图:{action}" if action else "",
        f"情绪意图:{emotion}" if emotion else "",
        phase_action,
        hand_constraint,
        f"人物锁定:{character_lines}",
        f"连续性约束:{continuity}" if continuity else "",
        style_prefix,
        core,
    ]
    return "；".join([p for p in parts if p]).strip("；").strip()


def build_request_payload(
    model: str,
    prompt: str,
    images: list[str],
    input_fidelity: str,
    output_format: str,
    quality: str,
    size: str,
    enable_base64_output: bool,
    enable_sync_mode: bool,
) -> dict[str, Any]:
    return {
        "model": model,
        "enable_base64_output": bool(enable_base64_output),
        "enable_sync_mode": bool(enable_sync_mode),
        "images": images,
        "input_fidelity": input_fidelity,
        "output_format": output_format,
        "prompt": prompt,
        "quality": quality,
        "size": size,
    }


def post_generate_image(api_key: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    response = requests.post(ATLAS_GENERATE_IMAGE_URL, headers=headers, json=payload, timeout=60)
    result = safe_json(response)
    if response.status_code >= 400:
        raise RuntimeError(f"生成请求失败: HTTP {response.status_code} - {result}")
    try:
        prediction_id = str(result["data"]["id"])
    except Exception as exc:
        raise RuntimeError(f"未拿到 prediction id: {result}") from exc
    return prediction_id, result


def poll_until_done(
    api_key: str,
    prediction_id: str,
    poll_interval_sec: float,
    timeout_sec: int,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"}
    poll_url = ATLAS_POLL_URL_TMPL.format(prediction_id=prediction_id)
    deadline = time.time() + timeout_sec

    while True:
        response = requests.get(poll_url, headers=headers, timeout=60)
        result = safe_json(response)
        if response.status_code >= 400:
            raise RuntimeError(f"查询状态失败: HTTP {response.status_code} - {result}")

        status = str(result.get("data", {}).get("status", "")).lower()
        if status in {"completed", "succeeded"}:
            return result
        if status == "failed":
            err = result.get("data", {}).get("error") or "Generation failed"
            raise RuntimeError(str(err))
        if time.time() > deadline:
            raise TimeoutError(f"轮询超时（>{timeout_sec}s），最后状态: {status}, result={result}")
        time.sleep(poll_interval_sec)


def extract_output(result: dict[str, Any]) -> tuple[str, str]:
    data = result.get("data", {})
    outputs = data.get("outputs")
    if isinstance(outputs, list) and outputs:
        first = outputs[0]
        if isinstance(first, str):
            if first.startswith("http://") or first.startswith("https://"):
                return first, ""
            return "", first
        if isinstance(first, dict):
            url = str(first.get("url") or "").strip()
            b64 = str(first.get("b64_json") or "").strip()
            return url, b64
    # some providers may return output as string
    output = str(data.get("output") or "").strip()
    if output.startswith("http://") or output.startswith("https://"):
        return output, ""
    if output:
        return "", output
    raise RuntimeError(f"未从响应中解析到图片输出: {result}")


def summarize_openai_response(result: dict[str, Any]) -> dict[str, Any]:
    summary = json.loads(json.dumps(result, ensure_ascii=False))
    data = summary.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("b64_json"), str):
                item["b64_json_length"] = len(item["b64_json"])
                item.pop("b64_json", None)
    return summary


def parse_data_uri(data_uri: str) -> tuple[str, bytes]:
    if "," not in data_uri:
        raise ValueError("invalid data uri")
    header, payload = data_uri.split(",", 1)
    mime_match = re.match(r"^data:([^;,]+)", header)
    mime = mime_match.group(1).strip() if mime_match else "application/octet-stream"
    if ";base64" in header.lower():
        return mime, base64.b64decode(payload)
    return mime, unquote_to_bytes(payload)


def infer_suffix(mime_type: str, fallback: str = ".jpg") -> str:
    ext = mimetypes.guess_extension(mime_type.split(";")[0].strip()) or fallback
    if ext == ".jpe":
        return ".jpg"
    return ext


def materialize_image_ref_to_file(ref: str, index: int, temp_dir: Path) -> tuple[Path, str]:
    value = ref.strip()
    if not value:
        raise ValueError("empty image reference")

    raw = b""
    mime_type = ""
    if value.startswith("data:"):
        mime_type, raw = parse_data_uri(value)
    elif value.startswith("http://") or value.startswith("https://"):
        response = requests.get(value, timeout=180)
        if response.status_code >= 400:
            raise RuntimeError(f"下载参考图失败: HTTP {response.status_code}, url={value}")
        raw = response.content
        mime_type = str(response.headers.get("Content-Type") or "").split(";")[0].strip()
        if not mime_type:
            guessed = mimetypes.guess_type(urlparse(value).path)[0]
            mime_type = guessed or "application/octet-stream"
    else:
        path = Path(value).expanduser()
        if not path.exists():
            raise RuntimeError(f"参考图不存在: {value}")
        raw = path.read_bytes()
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    suffix = infer_suffix(mime_type)
    out_path = temp_dir / f"input_{index:02d}{suffix}"
    out_path.write_bytes(raw)
    return out_path, mime_type


def post_openai_image_edit(
    *,
    api_key: str,
    model: str,
    prompt: str,
    images: list[str],
    input_fidelity: str,
    output_format: str,
    quality: str,
    size: str,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"}
    with tempfile.TemporaryDirectory(prefix="keyframe_openai_") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        prepared: list[tuple[Path, str]] = []
        for idx, image_ref in enumerate(images, start=1):
            prepared.append(materialize_image_ref_to_file(image_ref, idx, temp_dir))

        normalized_model = model.strip().lower()
        data: dict[str, str] = {
            "model": model,
            "prompt": prompt,
            "output_format": output_format,
            "quality": quality,
            "size": size,
        }
        if normalized_model.startswith("gpt-image-1"):
            data["input_fidelity"] = input_fidelity
        with ExitStack() as stack:
            files = []
            for image_file, mime_type in prepared:
                fp = stack.enter_context(image_file.open("rb"))
                files.append(("image[]", (image_file.name, fp, mime_type)))
            response = requests.post(
                OPENAI_IMAGE_EDITS_URL,
                headers=headers,
                data=data,
                files=files,
                timeout=300,
            )

    result = safe_json(response)
    if response.status_code >= 400:
        raise RuntimeError(f"生成请求失败: HTTP {response.status_code} - {result}")
    return result


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


def build_xai_image_ref(ref: str) -> dict[str, str]:
    return {"type": "image_url", "url": ref}


def build_xai_request_payload(
    model: str,
    prompt: str,
    images: list[str],
    size: str,
) -> dict[str, Any]:
    clean_images = [str(image).strip() for image in images if str(image).strip()]
    if len(clean_images) > 5:
        clean_images = clean_images[:5]
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio_from_size(size),
    }
    if len(clean_images) == 1:
        payload["image"] = {"url": clean_images[0]}
    else:
        payload["images"] = [build_xai_image_ref(ref) for ref in clean_images]
    return payload


def extract_image_refs_from_payload(payload: dict[str, Any]) -> list[str]:
    raw_images = payload.get("images")
    if isinstance(raw_images, list):
        refs: list[str] = []
        for item in raw_images:
            if isinstance(item, str) and item.strip():
                refs.append(item.strip())
            elif isinstance(item, dict):
                url = str(item.get("url") or "").strip()
                if url:
                    refs.append(url)
        if refs:
            return refs
    raw_image = payload.get("image")
    if isinstance(raw_image, str) and raw_image.strip():
        return [raw_image.strip()]
    if isinstance(raw_image, dict):
        url = str(raw_image.get("url") or "").strip()
        if url:
            return [url]
    return []


def post_xai_image_edit(
    *,
    api_key: str,
    model: str,
    prompt: str,
    images: list[str],
    size: str,
    aspect_ratio: str = "",
) -> dict[str, Any]:
    if not images:
        raise RuntimeError("Grok image edit requires at least one reference image.")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = build_xai_request_payload(
        model=model,
        prompt=prompt,
        images=images,
        size=size,
    )
    if aspect_ratio.strip():
        payload["aspect_ratio"] = aspect_ratio.strip()

    response = requests.post(
        XAI_IMAGE_EDITS_URL,
        headers=headers,
        json=payload,
        timeout=300,
    )
    result = safe_json(response)
    if response.status_code >= 400:
        raise RuntimeError(f"生成请求失败: HTTP {response.status_code} - {result}")
    return result


def extract_output_from_openai(result: dict[str, Any]) -> tuple[str, str]:
    data = result.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            b64 = str(first.get("b64_json") or "").strip()
            url = str(first.get("url") or "").strip()
            if url:
                return url, ""
            if b64:
                return "", b64
    raise RuntimeError(f"未从 OpenAI 响应中解析到图片输出: {result}")


def extract_output_from_xai(result: dict[str, Any]) -> tuple[str, str]:
    data = result.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            url = str(first.get("url") or "").strip()
            b64 = str(first.get("b64_json") or "").strip()
            if url:
                return url, ""
            if b64:
                return "", b64
        if isinstance(first, str):
            if first.startswith("http://") or first.startswith("https://"):
                return first, ""
            return "", first
    output = result.get("output")
    if isinstance(output, str) and output.strip():
        value = output.strip()
        if value.startswith("http://") or value.startswith("https://"):
            return value, ""
        return "", value
    raise RuntimeError(f"未从 Grok 响应中解析到图片输出: {result}")


def download_file(url: str, out_file: Path) -> None:
    with requests.get(url, stream=True, timeout=180) as resp:
        if resp.status_code >= 400:
            raise RuntimeError(f"下载失败: HTTP {resp.status_code}, url={url}")
        with out_file.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def extract_phase_ref(phase_meta: dict[str, Any]) -> str:
    return first_non_empty(
        [
            str(phase_meta.get("output_url", "")).strip(),
            str(phase_meta.get("output_data_uri", "")).strip(),
            str(phase_meta.get("output_file", "")).strip(),
        ]
    )


def run_phase(
    *,
    phase: str,
    phase_dir: Path,
    prompt: str,
    payload: dict[str, Any],
    output_format: str,
    overwrite: bool,
    prepare_only: bool,
    image_model: str,
    atlas_api_key: str,
    openai_api_key: str,
    openai_model: str,
    xai_api_key: str,
    xai_model: str,
    atlas_retries_before_fallback: int,
    poll_interval: float,
    timeout: int,
    max_retries: int,
    retry_wait_sec: float,
) -> dict[str, Any]:
    phase_meta: dict[str, Any] = {
        "phase": phase,
        "prompt_path": str(phase_dir / "prompt.txt"),
        "payload_path": str(phase_dir / "payload.preview.json"),
        "images_used": extract_image_refs_from_payload(payload),
    }
    output_file = phase_dir / f"{phase}.{output_format}"
    if output_file.exists() and not overwrite:
        phase_meta["status"] = "skipped_existing"
        phase_meta["output_file"] = str(output_file)
        return phase_meta

    if prepare_only:
        (phase_dir / "output.pending.txt").write_text(
            "Run without --prepare-only to generate keyframe output.\n",
            encoding="utf-8",
        )
        phase_meta["status"] = "prepared"
        return phase_meta

    def run_with_atlas(atlas_max_retries: int) -> dict[str, Any]:
        atlas_meta = dict(phase_meta)
        atlas_meta["provider"] = "atlas"
        total_retries = max(1, int(atlas_max_retries))
        fallback_wait = max(1, int(retry_wait_sec))
        last_error = ""
        for attempt in range(1, total_retries + 1):
            atlas_meta["attempt"] = attempt
            try:
                prediction_id, generate_raw = post_generate_image(
                    api_key=atlas_api_key,
                    payload=payload,
                )
                write_json(phase_dir / "generate_response.json", generate_raw)
                atlas_meta["prediction_id"] = prediction_id

                final_result = poll_until_done(
                    api_key=atlas_api_key,
                    prediction_id=prediction_id,
                    poll_interval_sec=poll_interval,
                    timeout_sec=timeout,
                )
                write_json(phase_dir / "final_status.json", final_result)

                output_url, output_b64 = extract_output(final_result)
                atlas_meta["output_url"] = output_url
                if output_url:
                    (phase_dir / "output_url.txt").write_text(output_url + "\n", encoding="utf-8")
                    download_file(output_url, output_file)
                    atlas_meta["output_file"] = str(output_file)
                elif output_b64:
                    raw = base64.b64decode(output_b64)
                    output_file.write_bytes(raw)
                    atlas_meta["output_file"] = str(output_file)
                    atlas_meta["output_data_uri"] = f"data:image/{output_format};base64,{output_b64}"
                else:
                    raise RuntimeError("输出为空：既无 output_url 也无 base64 数据。")

                atlas_meta["status"] = "completed"
                return atlas_meta
            except Exception as exc:
                last_error = str(exc)
                atlas_meta["error"] = last_error
                retryable = is_retryable_rate_limit_error(last_error)
                if (not retryable) or (attempt >= total_retries):
                    break
                wait_sec = parse_retry_after_seconds(last_error, default=fallback_wait)
                print(
                    f"[WARN] {phase_dir.parent.name}/{phase} "
                    f"(atlas) attempt {attempt}/{total_retries} failed, "
                    f"retry in {wait_sec}s: {last_error}",
                    file=sys.stderr,
                )
                time.sleep(wait_sec)

        raise RuntimeError(
            f"{phase_dir.parent.name}/{phase} atlas failed after {total_retries} attempts: "
            f"{last_error or 'unknown error'}"
        )

    def run_with_openai(openai_max_retries: int) -> dict[str, Any]:
        openai_meta = dict(phase_meta)
        openai_meta["provider"] = "openai"
        total_retries = max(1, int(openai_max_retries))
        fallback_wait = max(1, int(retry_wait_sec))
        last_error = ""
        for attempt in range(1, total_retries + 1):
            openai_meta["attempt"] = attempt
            try:
                raw_response = post_openai_image_edit(
                    api_key=openai_api_key,
                    model=openai_model,
                    prompt=prompt,
                    images=list(payload.get("images", [])),
                    input_fidelity=str(payload.get("input_fidelity", "high")),
                    output_format=str(payload.get("output_format", output_format)),
                    quality=str(payload.get("quality", "medium")),
                    size=str(payload.get("size", "1024x1536")),
                )
                write_json(phase_dir / "openai_response.json", summarize_openai_response(raw_response))
                output_url, output_b64 = extract_output_from_openai(raw_response)
                openai_meta["output_url"] = output_url
                if output_url:
                    (phase_dir / "output_url.txt").write_text(output_url + "\n", encoding="utf-8")
                    download_file(output_url, output_file)
                    openai_meta["output_file"] = str(output_file)
                elif output_b64:
                    raw = base64.b64decode(output_b64)
                    output_file.write_bytes(raw)
                    openai_meta["output_file"] = str(output_file)
                    openai_meta["output_data_uri"] = (
                        f"data:image/{output_format};base64,{output_b64}"
                    )
                else:
                    raise RuntimeError("输出为空：既无 output_url 也无 base64 数据。")

                openai_meta["status"] = "completed"
                return openai_meta
            except Exception as exc:
                last_error = str(exc)
                openai_meta["error"] = last_error
                retryable = is_retryable_rate_limit_error(last_error)
                if (not retryable) or (attempt >= total_retries):
                    break
                wait_sec = parse_retry_after_seconds(last_error, default=fallback_wait)
                print(
                    f"[WARN] {phase_dir.parent.name}/{phase} "
                    f"(openai) attempt {attempt}/{total_retries} failed, "
                    f"retry in {wait_sec}s: {last_error}",
                    file=sys.stderr,
                )
                time.sleep(wait_sec)

        raise RuntimeError(
            f"{phase_dir.parent.name}/{phase} openai failed after {total_retries} attempts: "
            f"{last_error or 'unknown error'}"
        )

    def run_with_xai(xai_max_retries: int) -> dict[str, Any]:
        xai_meta = dict(phase_meta)
        xai_meta["provider"] = "grok"
        total_retries = max(1, int(xai_max_retries))
        fallback_wait = max(1, int(retry_wait_sec))
        last_error = ""
        for attempt in range(1, total_retries + 1):
            xai_meta["attempt"] = attempt
            try:
                raw_response = post_xai_image_edit(
                    api_key=xai_api_key,
                    model=xai_model,
                    prompt=prompt,
                    images=extract_image_refs_from_payload(payload),
                    size=str(payload.get("size", "1024x1536")),
                    aspect_ratio=str(payload.get("aspect_ratio") or ""),
                )
                write_json(phase_dir / "grok_response.json", summarize_openai_response(raw_response))
                output_url, output_b64 = extract_output_from_xai(raw_response)
                xai_meta["output_url"] = output_url
                if output_url:
                    (phase_dir / "output_url.txt").write_text(output_url + "\n", encoding="utf-8")
                    download_file(output_url, output_file)
                    xai_meta["output_file"] = str(output_file)
                elif output_b64:
                    raw = base64.b64decode(output_b64)
                    output_file.write_bytes(raw)
                    xai_meta["output_file"] = str(output_file)
                    xai_meta["output_data_uri"] = (
                        f"data:image/{output_format};base64,{output_b64}"
                    )
                else:
                    raise RuntimeError("输出为空：既无 output_url 也无 base64 数据。")

                xai_meta["status"] = "completed"
                return xai_meta
            except Exception as exc:
                last_error = str(exc)
                xai_meta["error"] = last_error
                retryable = is_retryable_rate_limit_error(last_error)
                if (not retryable) or (attempt >= total_retries):
                    break
                wait_sec = parse_retry_after_seconds(last_error, default=fallback_wait)
                print(
                    f"[WARN] {phase_dir.parent.name}/{phase} "
                    f"(grok) attempt {attempt}/{total_retries} failed, "
                    f"retry in {wait_sec}s: {last_error}",
                    file=sys.stderr,
                )
                time.sleep(wait_sec)

        raise RuntimeError(
            f"{phase_dir.parent.name}/{phase} grok failed after {total_retries} attempts: "
            f"{last_error or 'unknown error'}"
        )

    chosen = normalize_image_model(image_model)
    if chosen == "atlas-openai":
        result = run_with_atlas(max_retries)
        (phase_dir / "provider.used.txt").write_text("atlas-openai\n", encoding="utf-8")
        return result

    if chosen == "openai":
        result = run_with_openai(max_retries)
        (phase_dir / "provider.used.txt").write_text("openai\n", encoding="utf-8")
        return result

    if chosen == "grok":
        result = run_with_xai(max_retries)
        (phase_dir / "provider.used.txt").write_text("grok\n", encoding="utf-8")
        return result

    if chosen != "auto":
        raise RuntimeError(f"未知 IMAGE_MODEL: {image_model}")

    atlas_budget = min(max(1, int(max_retries)), max(1, int(atlas_retries_before_fallback)))
    atlas_error = ""
    try:
        result = run_with_atlas(atlas_budget)
        (phase_dir / "provider.used.txt").write_text("atlas-openai\n", encoding="utf-8")
        return result
    except Exception as exc:
        atlas_error = str(exc)
        if (not is_retryable_rate_limit_error(atlas_error)) or (not openai_api_key.strip()):
            if not openai_api_key.strip():
                raise RuntimeError(
                    f"{atlas_error}；且 provider=auto 但 OPENAI_API_KEY 不可用，无法 fallback 到 OpenAI。"
                ) from exc
            raise

    fallback_event = {
        "phase": phase,
        "from": "atlas",
        "to": "openai",
        "reason": "atlas_retryable_error",
        "atlas_error": atlas_error,
        "atlas_attempt_budget": atlas_budget,
        "created_at": datetime.now().isoformat(),
    }
    write_json(phase_dir / "fallback_event.json", fallback_event)
    print(
        f"[WARN] {phase_dir.parent.name}/{phase} fallback atlas -> openai: {atlas_error}",
        file=sys.stderr,
    )
    result = run_with_openai(max_retries)
    result["fallback_from"] = "atlas"
    result["fallback_reason"] = "atlas_retryable_error"
    result["fallback_error"] = atlas_error
    (phase_dir / "provider.used.txt").write_text("openai\n", encoding="utf-8")
    return result


def collect_character_refs_for_shot(
    characters: list[dict[str, Any]],
    image_map: dict[str, str],
    default_image_ref: str,
    project_root: Path,
) -> list[str]:
    refs: list[str] = []
    for char in characters:
        candidates = [
            str(char.get("character_id") or "").strip(),
            str(char.get("name") or "").strip(),
            str(char.get("lock_profile_id") or "").strip(),
        ]
        chosen = ""
        for key in candidates:
            if key and str(image_map.get(key, "")).strip():
                chosen = str(image_map[key]).strip()
                break
        if not chosen and default_image_ref.strip():
            chosen = default_image_ref.strip()
        resolved = resolve_image_ref(chosen, project_root) if chosen else ""
        if resolved:
            refs.append(resolved)

    # unique keep order
    out: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate start/end keyframes per shot via Atlas or OpenAI image edit API."
        )
    )
    parser.add_argument(
        "--experiment-name",
        default=datetime.now().strftime("exp_keyframes_%Y%m%d_%H%M%S"),
        help="Output directory name under test/.",
    )
    parser.add_argument(
        "--shots",
        default="",
        help="Comma-separated shot ids, e.g. SH01,SH02. Empty means all discovered records.",
    )
    parser.add_argument(
        "--phases",
        default="start,end",
        help="Comma-separated phases to generate. Supported: start,end.",
    )
    parser.add_argument(
        "--records-dir",
        default=DEFAULT_RECORDS_DIR,
        help="Record directory path.",
    )
    parser.add_argument(
        "--character-lock-profiles",
        default=DEFAULT_CHARACTER_LOCK_FILE,
        help="Character lock profile catalog json path.",
    )
    parser.add_argument(
        "--character-image-map",
        default="",
        help=(
            "JSON map for reference images by character key. "
            "Example: {\"LC_MAIN\":\"/abs/林辰.jpg\",\"AC_FEMALE\":\"https://...\"}"
        ),
    )
    parser.add_argument("--lc-image", default="", help="Override reference image for LC_MAIN.")
    parser.add_argument("--ac-image", default="", help="Override reference image for AC_FEMALE.")
    parser.add_argument(
        "--default-image",
        default="",
        help="Fallback reference image when character-specific image is not found.",
    )
    parser.add_argument(
        "--image-model",
        default="",
        choices=["", "openai", "atlas-openai", "grok", "auto"],
        help=(
            "Macro image provider selector. Empty means IMAGE_MODEL env, then --provider, "
            "then atlas-openai. Supported: openai, atlas-openai, grok."
        ),
    )
    parser.add_argument(
        "--provider",
        default="",
        choices=["", "atlas", "openai", "auto", "grok", "atlas-openai"],
        help=(
            "Legacy keyframe provider alias. Prefer --image-model or IMAGE_MODEL. "
            "auto=try Atlas first then fallback to OpenAI on retryable 429/5xx/network errors."
        ),
    )
    parser.add_argument(
        "--model",
        "--atlas-model",
        dest="model",
        default=DEFAULT_MODEL,
        help="Atlas image model name.",
    )
    parser.add_argument(
        "--openai-model",
        default=DEFAULT_OPENAI_MODEL,
        help="OpenAI image edit model name, e.g. gpt-image-2.",
    )
    parser.add_argument(
        "--openai-api-key",
        default="",
        help="Optional OPENAI_API_KEY override (otherwise read from env/.env).",
    )
    parser.add_argument(
        "--xai-model",
        default=DEFAULT_XAI_MODEL,
        help=f"xAI/Grok image edit model name, default {DEFAULT_XAI_MODEL}.",
    )
    parser.add_argument(
        "--xai-api-key",
        default="",
        help="Optional XAI_API_KEY override (otherwise read from env/.env).",
    )
    parser.add_argument("--input-fidelity", default="high", choices=["low", "high"])
    parser.add_argument("--output-format", default="jpeg", choices=["jpeg", "png"])
    parser.add_argument("--quality", default="medium", choices=["low", "medium", "high"])
    parser.add_argument("--size", default="1024x1536", help="Output size, e.g. 1024x1536.")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument(
        "--max-retries",
        type=int,
        default=10,
        help="Max retries per single frame generation when API is rate-limited.",
    )
    parser.add_argument(
        "--retry-wait-sec",
        type=float,
        default=20.0,
        help="Fallback retry wait seconds when provider does not return retry-after.",
    )
    parser.add_argument(
        "--atlas-retries-before-fallback",
        type=int,
        default=2,
        help=(
            "When --provider auto, max Atlas retries before switching to OpenAI. "
            "Clamped to [1, --max-retries]."
        ),
    )
    parser.add_argument(
        "--request-interval",
        type=float,
        default=3.0,
        help="Sleep seconds between each single-frame request (start/end) in API mode.",
    )
    parser.add_argument("--prepare-only", action="store_true", help="Only write payload preview files.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing keyframes.")
    parser.add_argument("--enable-base64-output", action="store_true")
    parser.add_argument("--enable-sync-mode", action="store_true")
    parser.add_argument(
        "--reuse-next-start-from-prev-end",
        action="store_true",
        help=(
            "Enable chain reuse. If shot N end frame is available, "
            "shot N+1 start frame will reuse it instead of regenerating."
        ),
    )
    parser.add_argument(
        "--no-reuse-next-start-from-prev-end",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def parse_phases_arg(phases_arg: str) -> list[str]:
    supported = {"start", "end"}
    requested = [str(x).strip().lower() for x in str(phases_arg or "").split(",") if str(x).strip()]
    if not requested:
        requested = ["start", "end"]
    ordered: list[str] = []
    seen: set[str] = set()
    for phase in requested:
        if phase not in supported:
            raise ValueError(f"未知 phases: {phase}。可选: start,end")
        if phase not in seen:
            ordered.append(phase)
            seen.add(phase)
    return ordered


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")

    records_dir = (project_root / args.records_dir).resolve()
    record_map = discover_record_files(records_dir)
    available_shots = sorted(record_map.keys())
    if not available_shots:
        print(f"[ERROR] 未发现 record 文件: {records_dir}", file=sys.stderr)
        return 1

    try:
        selected_shots = parse_shots_arg(args.shots, available_shots)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    try:
        selected_phases = parse_phases_arg(args.phases)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    try:
        image_model = resolve_image_model(args)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    lock_catalog_path = (project_root / args.character_lock_profiles).resolve()
    lock_catalog = load_character_lock_catalog(lock_catalog_path)

    image_map: dict[str, str] = {}
    if args.character_image_map.strip():
        try:
            image_map = load_character_image_map((project_root / args.character_image_map).resolve())
        except Exception as exc:
            print(f"[ERROR] character image map 解析失败: {exc}", file=sys.stderr)
            return 1
    if args.lc_image.strip():
        image_map["LC_MAIN"] = args.lc_image.strip()
    if args.ac_image.strip():
        image_map["AC_FEMALE"] = args.ac_image.strip()

    atlas_api_key = ""
    openai_api_key = ""
    xai_api_key = ""
    if not args.prepare_only:
        if image_model in {"atlas-openai", "auto"}:
            try:
                atlas_api_key = require_api_key()
            except RuntimeError as exc:
                print(f"[ERROR] {exc}", file=sys.stderr)
                return 1
        if image_model == "openai":
            try:
                openai_api_key = resolve_openai_api_key(args.openai_api_key, required=True)
            except RuntimeError as exc:
                print(f"[ERROR] {exc}", file=sys.stderr)
                return 1
        elif image_model == "auto":
            openai_api_key = resolve_openai_api_key(args.openai_api_key, required=False)
            if not openai_api_key:
                print(
                    "[WARN] provider=auto 但 OPENAI_API_KEY 不可用；如 Atlas 出现 429/500，无法 fallback。",
                    file=sys.stderr,
                )
        elif image_model == "grok":
            try:
                xai_api_key = resolve_xai_api_key(args.xai_api_key, required=True)
            except RuntimeError as exc:
                print(f"[ERROR] {exc}", file=sys.stderr)
                return 1

    experiment_dir = project_root / "test" / args.experiment_name
    experiment_dir.mkdir(parents=True, exist_ok=True)

    run_manifest: dict[str, Any] = {
        "created_at": datetime.now().isoformat(),
        "mode": "prepare_only" if args.prepare_only else "api_generate",
        "image_model": image_model,
        "provider": image_model,
        "model": args.model,
        "openai_model": args.openai_model,
        "xai_model": args.xai_model,
        "shots": selected_shots,
        "phases": selected_phases,
        "records_dir": str(records_dir),
        "character_lock_profiles": str(lock_catalog_path),
        "character_image_map_keys": sorted(image_map.keys()),
        "default_image": args.default_image,
        "settings": {
            "input_fidelity": args.input_fidelity,
            "output_format": args.output_format,
            "quality": args.quality,
            "size": args.size,
            "enable_base64_output": bool(args.enable_base64_output),
            "enable_sync_mode": bool(args.enable_sync_mode),
            "reuse_next_start_from_prev_end": bool(args.reuse_next_start_from_prev_end),
            "max_retries": int(args.max_retries),
            "retry_wait_sec": float(args.retry_wait_sec),
            "atlas_retries_before_fallback": int(args.atlas_retries_before_fallback),
            "request_interval_sec": float(args.request_interval),
        },
        "shots_result": {},
    }

    print(f"[INFO] keyframe experiment dir: {experiment_dir}")
    if not args.prepare_only:
        print(
            "[INFO] one-by-one mode: enabled "
            f"(image_model={image_model}, "
            f"max_retries={int(args.max_retries)}, retry_wait_sec={float(args.retry_wait_sec)}, "
            f"request_interval_sec={float(args.request_interval)})"
        )
    if args.no_reuse_next_start_from_prev_end:
        print(
            "[WARN] --no-reuse-next-start-from-prev-end is deprecated; independent start frames are now the default.",
            file=sys.stderr,
        )
    reuse_next_start_from_prev_end = bool(args.reuse_next_start_from_prev_end)
    previous_end_ref = ""
    previous_end_shot = ""

    for shot_id in selected_shots:
        shot_dir = experiment_dir / shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)
        shot_result: dict[str, Any] = {}
        run_manifest["shots_result"][shot_id] = shot_result
        try:
            record = read_json(record_map[shot_id])
            characters = collect_characters(record, lock_catalog)
            image_refs = collect_character_refs_for_shot(
                characters=characters,
                image_map=image_map,
                default_image_ref=args.default_image,
                project_root=project_root,
            )
            if not image_refs:
                reference_characters = collect_reference_characters(record, lock_catalog)
                image_refs = collect_character_refs_for_shot(
                    characters=reference_characters,
                    image_map=image_map,
                    default_image_ref=args.default_image,
                    project_root=project_root,
                )
                if image_refs:
                    shot_result["reference_fallback"] = (
                        "used record character refs as visual inputs; prompt character lock remains shot-specific"
                    )
            if not image_refs:
                raise RuntimeError(
                    "未找到可用人物参考图。请通过 --character-image-map / --lc-image / --ac-image / --default-image 传入。"
                )

            shot_result["character_refs_count"] = len(image_refs)

            reuse_start = (
                reuse_next_start_from_prev_end
                and (not args.prepare_only)
                and bool(previous_end_ref.strip())
            )
            for phase in selected_phases:
                phase_dir = shot_dir / phase
                phase_dir.mkdir(parents=True, exist_ok=True)
                if phase == "start" and reuse_start:
                    phase_meta = {
                        "phase": "start",
                        "status": "reused_from_previous_end",
                        "reused_from_shot": previous_end_shot,
                        "prompt_path": str(phase_dir / "prompt.reused.txt"),
                        "payload_path": "",
                        "images_used": [],
                    }
                    reused_note = (
                        f"Reused from previous end frame: {previous_end_shot} -> {shot_id}\n"
                        f"ref: {previous_end_ref}\n"
                    )
                    (phase_dir / "prompt.reused.txt").write_text(reused_note, encoding="utf-8")
                    if previous_end_ref.startswith("http://") or previous_end_ref.startswith("https://"):
                        phase_meta["output_url"] = previous_end_ref
                    elif previous_end_ref.startswith("data:"):
                        phase_meta["output_data_uri"] = previous_end_ref
                    else:
                        phase_meta["output_file"] = previous_end_ref
                    shot_result["start"] = phase_meta
                    print(f"[{shot_id}/start] reused from {previous_end_shot}/end")
                    continue

                prompt = build_keyframe_prompt(
                    shot_id=shot_id,
                    record=record,
                    characters=characters,
                    phase=phase,
                )
                payload = build_request_payload(
                    model=args.model,
                    prompt=prompt,
                    images=image_refs,
                    input_fidelity=args.input_fidelity,
                    output_format=args.output_format,
                    quality=args.quality,
                    size=args.size,
                    enable_base64_output=bool(args.enable_base64_output),
                    enable_sync_mode=bool(args.enable_sync_mode),
                )
                if image_model == "grok":
                    payload = build_xai_request_payload(
                        model=args.xai_model,
                        prompt=prompt,
                        images=image_refs,
                        size=args.size,
                    )
                (phase_dir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
                write_json(phase_dir / "payload.preview.json", payload)
                phase_meta = run_phase(
                    phase=phase,
                    phase_dir=phase_dir,
                    prompt=prompt,
                    payload=payload,
                    output_format=args.output_format,
                    overwrite=bool(args.overwrite),
                    prepare_only=bool(args.prepare_only),
                    image_model=image_model,
                    atlas_api_key=atlas_api_key,
                    openai_api_key=openai_api_key,
                    openai_model=args.openai_model,
                    xai_api_key=xai_api_key,
                    xai_model=args.xai_model,
                    atlas_retries_before_fallback=args.atlas_retries_before_fallback,
                    poll_interval=args.poll_interval,
                    timeout=args.timeout,
                    max_retries=args.max_retries,
                    retry_wait_sec=args.retry_wait_sec,
                )
                shot_result[phase] = phase_meta
                if phase_meta.get("status") == "completed":
                    print(f"[{shot_id}/{phase}] done -> {phase_meta.get('output_file', '')}")
                if (not args.prepare_only) and float(args.request_interval) > 0:
                    time.sleep(float(args.request_interval))

            # convenient map for run_seedance_test.py
            start_ref = extract_phase_ref(shot_result.get("start", {}))
            end_ref = extract_phase_ref(shot_result.get("end", {}))
            if start_ref and end_ref:
                shot_result["image_input_map_entry"] = {"image": start_ref, "last_image": end_ref}
            previous_end_ref = end_ref
            previous_end_shot = shot_id

        except Exception as exc:
            shot_result["status"] = "failed"
            shot_result["error"] = str(exc)
            (shot_dir / "error.txt").write_text(str(exc) + "\n", encoding="utf-8")
            print(f"[ERROR] {shot_id}: {exc}", file=sys.stderr)

    # build map if all urls are available
    image_input_map: dict[str, Any] = {}
    for shot_id, shot_meta in run_manifest["shots_result"].items():
        entry = shot_meta.get("image_input_map_entry")
        if isinstance(entry, dict):
            image_input_map[shot_id] = entry
    run_manifest["image_input_map"] = image_input_map

    write_json(experiment_dir / "keyframe_manifest.json", run_manifest)
    if image_input_map:
        write_json(experiment_dir / "image_input_map.from_keyframes.json", image_input_map)
        print(
            f"[INFO] image input map written: {experiment_dir / 'image_input_map.from_keyframes.json'}"
        )

    print("[INFO] keyframe generation finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
