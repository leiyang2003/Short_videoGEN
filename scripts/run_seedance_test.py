#!/usr/bin/env python3
"""Run Seedance image-to-video API flows for test shots.

Outputs are stored at:
  test/<experiment_name>/<shot_id>/
or in multi-profile mode:
  test/<experiment_name>/<profile_id>/<shot_id>/
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

ATLAS_API_BASE = "https://api.atlascloud.ai/api/v1/model"
ATLAS_GENERATE_URL = f"{ATLAS_API_BASE}/generateVideo"
ATLAS_POLL_URL_TMPL = f"{ATLAS_API_BASE}/prediction/{{prediction_id}}"
NOVITA_GENERATE_URL = "https://api.novita.ai/v3/async/seedance-v1.5-pro-i2v"
NOVITA_TASK_RESULT_URL = "https://api.novita.ai/v3/async/task-result"
MODEL_NAME = "bytedance/seedance-v1.5-pro/image-to-video"
NOVITA_MODEL_NAME = "seedance-v1.5-pro-i2v"
DEFAULT_VIDEO_MODEL = "novita-seedance1.5"
DEFAULT_RESOLUTION = "480p"
DEFAULT_RATIO = "9:16"
MIN_DURATION_SEC = 4  # Atlas Seedance duration lower bound
MAX_DURATION_SEC = 12  # Seedance v1.5 image-to-video upper bound
DEFAULT_DURATION_BUFFER_SEC = 0.5
DEFAULT_NARRATION_CANDIDATE_ATTEMPTS = 3
DEFAULT_PROFILE_ID = "seedance15_i2v_novita"
VIDEO_MODEL_PROFILE_IDS = {
    "atlas-seedance1.5": "seedance15_i2v_atlas",
    "novita-seedance1.5": "seedance15_i2v_novita",
}
DEFAULT_RECORDS_DIR = (
    "SampleChapter_项目文件整理版/06_当前项目的视觉与AI执行层文档/records"
)
DEFAULT_PROFILE_FILE = (
    "SampleChapter_项目文件整理版/06_当前项目的视觉与AI执行层文档/"
    "30_model_capability_profiles_v1.json"
)
DEFAULT_CHARACTER_LOCK_FILE = (
    "SampleChapter_项目文件整理版/06_当前项目的视觉与AI执行层文档/"
    "35_character_lock_profiles_v1.json"
)

GLOBAL_PREFIX = (
    "竖屏短剧，写实电影感，低饱和，真实光影，角色一致性稳定，24fps，9:16"
)

NEGATIVE_PROMPT = (
    "卡通, 二次元, 游戏建模感, 塑料皮肤, 不符合故事设定的服装建筑道具, "
    "过度磨皮, 过饱和, 畸形手指, 手部崩坏, 面部扭曲, 多余肢体, 水印, logo, "
    "低清晰度, 严重噪点, 闪烁, 频繁跳帧, 穿帮"
)
DEFAULT_LANGUAGE_POLICY = {
    "spoken_language": "zh-CN",
    "spoken_language_label": "普通话中文",
    "subtitle_language": "zh-CN",
    "subtitle_language_label": "后期简体中文字幕",
    "model_audio_language": "zh-CN",
    "voice_language_lock": "Mandarin Chinese only. No Japanese, English, or mixed-language speech.",
    "screen_text_language_lock": "Do not render subtitles or caption text inside the video frames; subtitles are added only in post-production.",
    "environment_signage_language": "ja-JP allowed only as silent background signage.",
    "forbidden_spoken_languages": ["ja-JP", "en-US"],
}
LARGE_SCENE_PROP_ID_TOKENS = ("DOOR_PANEL", "VEHICLE_DOOR", "BUS", "CAR_DOOR", "ELEVATOR_DOOR")
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
LARGE_SCENE_ELEMENT_TEXT_TOKENS = ("门", "车", "公交车", "大门", "车门", "房门", "电梯门", "柜台", "沙发", "楼梯")
PROHIBITED_CIGARETTE_ACTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:点燃|点起|点上|点着|点)\s*(?:一?支|一?根|那支|这支|一?截|1支|1根)?\s*(?:香烟|卷烟|烟卷|烟\b|CIGARETTE)", re.I),
    re.compile(r"(?:香烟|卷烟|烟卷|烟头|烟\b|CIGARETTE).{0,12}(?:按灭|熄灭|摁灭|掐灭)", re.I),
    re.compile(r"(?:按灭|熄灭|摁灭|掐灭).{0,12}(?:香烟|卷烟|烟卷|烟头|烟\b|CIGARETTE)", re.I),
    re.compile(r"(?:香烟|卷烟|烟卷|烟头|烟\b|CIGARETTE).{0,12}(?:按入|按进|摁入|摁进).{0,8}烟灰缸", re.I),
)


@dataclass(frozen=True)
class Shot:
    shot_id: str
    prompt: str


SHOTS: list[Shot] = [
    Shot(
        shot_id="SH02",
        prompt=(
            "18-22岁消瘦少年躺在破庙泥地上突然惊醒，面部冷汗清晰，呼吸急促，"
            "瞳孔由涣散到聚焦，眼神从恐惧快速转硬，镜头近景微手持，背景虚化保留"
            "破庙冷光与残墙质感，情绪是“濒死后强行清醒”"
        ),
    ),
    Shot(
        shot_id="SH05",
        prompt=(
            "木门缓慢推开，寒风先入镜，16-18岁清秀布衣女孩端一碗冒热气的稀粥小心"
            "进门，门外冷蓝夜色与门内微暖火光形成明显冷暖对比，女孩神情温柔克制带"
            "隐忍，镜头中景向近景过渡，突出“寒夜里唯一温度”"
        ),
    ),
    Shot(
        shot_id="SH10",
        prompt=(
            "手部极近特写，粗糙指腹缓慢抹过石面与泥土，白色盐渍纹理清晰可辨，"
            "水汽与泥粒细节明显，动作从迟疑到确认，镜头微推进，情绪从绝望切到兴奋，"
            "必须让观众看清“盐渍就是机会”"
        ),
    ),
]


def clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def clamp_float(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def format_duration_value(value: float) -> str:
    return format_seconds_label(value)


def estimate_duration_seconds(prompt: str) -> int:
    """Estimate duration from prompt while capping at <= 5 seconds."""
    matches = re.findall(r"(\d+)\s*秒", prompt)
    if matches:
        explicit = int(matches[-1])
        return clamp_int(explicit, MIN_DURATION_SEC, MAX_DURATION_SEC)

    normalized = re.sub(r"\s+", "", prompt)
    estimated = 4 if len(normalized) <= 90 else 5
    return clamp_int(estimated, MIN_DURATION_SEC, MAX_DURATION_SEC)


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


def require_api_key(provider: str) -> str:
    provider_key_map = {
        "atlascloud": "ATLASCLOUD_API_KEY",
        "novita": "NOVITA_API_KEY",
    }
    env_name = provider_key_map.get(str(provider or "").strip().lower())
    if not env_name:
        raise RuntimeError(f"暂不支持 provider={provider or 'unknown'} 的 API key 解析。")

    key = os.getenv(env_name, "").strip()
    placeholder = f"your_{env_name.lower()}_here"
    if not key or key == placeholder:
        raise RuntimeError(
            f"{env_name} 未配置。请在 .env 填入真实 key，"
            f"或在环境变量中导出 {env_name}。"
        )
    return key


def normalize_video_model(value: str) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "atlas": "atlas-seedance1.5",
        "atlas-seedance": "atlas-seedance1.5",
        "atlas-seedance1.5": "atlas-seedance1.5",
        "atlas_seedance1.5": "atlas-seedance1.5",
        "seedance15_i2v_atlas": "atlas-seedance1.5",
        "novita": "novita-seedance1.5",
        "novita-seedance": "novita-seedance1.5",
        "novita-seedance1.5": "novita-seedance1.5",
        "novita_seedance1.5": "novita-seedance1.5",
        "seedance15_i2v_novita": "novita-seedance1.5",
    }
    if raw in aliases:
        return aliases[raw]
    raise ValueError(
        f"未知 VIDEO_MODEL: {value!r}。可选: atlas-seedance1.5, novita-seedance1.5"
    )


def resolve_video_model(cli_value: str) -> str:
    raw = str(cli_value or "").strip() or os.getenv("VIDEO_MODEL", "").strip()
    if not raw:
        return DEFAULT_VIDEO_MODEL
    normalized = normalize_video_model(raw)
    if normalized == "atlas-seedance1.5":
        raise ValueError("Atlas Seedance is temporarily disabled for production runs; use novita-seedance1.5.")
    return normalized


def profile_id_for_video_model(video_model: str) -> str:
    normalized = normalize_video_model(video_model)
    return VIDEO_MODEL_PROFILE_IDS[normalized]


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


def is_retryable_api_error(message: str) -> bool:
    lowered = str(message).lower()
    tokens = (
        "http 429",
        "http 500",
        "http 503",
        "high demand",
        "retry after",
        "maximum usage size allowed",
        "provisioned throughput",
        "temporarily unavailable",
        "timed out",
        "max retries exceeded",
        "connection aborted",
        "connection reset",
    )
    return any(token in lowered for token in tokens)


def post_generate_payload_atlas(
    api_key: str, payload: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    response = requests.post(ATLAS_GENERATE_URL, headers=headers, json=payload, timeout=60)
    result = safe_json(response)
    if response.status_code >= 400:
        raise RuntimeError(f"生成请求失败: HTTP {response.status_code} - {result}")
    try:
        prediction_id = result["data"]["id"]
    except Exception as exc:
        raise RuntimeError(f"未拿到 prediction id: {result}") from exc
    return prediction_id, {"payload": payload, "response": result}


def post_generate_payload_novita(
    api_key: str, payload: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    response = requests.post(NOVITA_GENERATE_URL, headers=headers, json=payload, timeout=60)
    result = safe_json(response)
    if response.status_code >= 400:
        raise RuntimeError(f"生成请求失败: HTTP {response.status_code} - {result}")
    task_id = str(result.get("task_id") or result.get("id") or "").strip()
    if not task_id:
        raise RuntimeError(f"未拿到 task id: {result}")
    return task_id, {"payload": payload, "response": result}


def post_generate_payload(
    provider: str, api_key: str, payload: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    normalized = str(provider or "").strip().lower()
    if normalized == "atlascloud":
        return post_generate_payload_atlas(api_key=api_key, payload=payload)
    if normalized == "novita":
        return post_generate_payload_novita(api_key=api_key, payload=payload)
    raise RuntimeError(f"暂不支持 provider={provider or 'unknown'} 的生成请求。")


def extract_output_url_atlas(result: dict[str, Any]) -> str:
    data = result.get("data", {})
    outputs = data.get("outputs")
    if isinstance(outputs, list) and outputs:
        first = outputs[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            for k in ("url", "output", "video_url"):
                if isinstance(first.get(k), str):
                    return first[k]
    if isinstance(data.get("output"), str):
        return data["output"]
    raise RuntimeError(f"未从响应中解析到视频 URL: {result}")


def extract_output_url_novita(result: dict[str, Any]) -> str:
    videos = result.get("videos")
    if isinstance(videos, list) and videos:
        first = videos[0]
        if isinstance(first, dict) and isinstance(first.get("video_url"), str):
            return str(first["video_url"])
    raise RuntimeError(f"未从 Novita 响应中解析到视频 URL: {result}")


def extract_output_url(provider: str, result: dict[str, Any]) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "atlascloud":
        return extract_output_url_atlas(result)
    if normalized == "novita":
        return extract_output_url_novita(result)
    raise RuntimeError(f"暂不支持 provider={provider or 'unknown'} 的输出解析。")


def poll_until_done_atlas(
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


def poll_until_done_novita(
    api_key: str,
    task_id: str,
    poll_interval_sec: float,
    timeout_sec: int,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    deadline = time.time() + timeout_sec

    while True:
        response = requests.get(
            NOVITA_TASK_RESULT_URL,
            headers=headers,
            params={"task_id": task_id},
            timeout=60,
        )
        result = safe_json(response)
        if response.status_code >= 400:
            raise RuntimeError(f"查询状态失败: HTTP {response.status_code} - {result}")

        status = str(result.get("task", {}).get("status", "")).strip().upper()
        if status == "TASK_STATUS_SUCCEED":
            return result
        if status == "TASK_STATUS_FAILED":
            err = result.get("task", {}).get("reason") or "Generation failed"
            raise RuntimeError(str(err))
        if time.time() > deadline:
            raise TimeoutError(f"轮询超时（>{timeout_sec}s），最后状态: {status}, result={result}")

        time.sleep(poll_interval_sec)


def poll_until_done(
    provider: str,
    api_key: str,
    prediction_id: str,
    poll_interval_sec: float,
    timeout_sec: int,
) -> dict[str, Any]:
    normalized = str(provider or "").strip().lower()
    if normalized == "atlascloud":
        return poll_until_done_atlas(
            api_key=api_key,
            prediction_id=prediction_id,
            poll_interval_sec=poll_interval_sec,
            timeout_sec=timeout_sec,
        )
    if normalized == "novita":
        return poll_until_done_novita(
            api_key=api_key,
            task_id=prediction_id,
            poll_interval_sec=poll_interval_sec,
            timeout_sec=timeout_sec,
        )
    raise RuntimeError(f"暂不支持 provider={provider or 'unknown'} 的轮询逻辑。")


def download_file(url: str, out_file: Path) -> None:
    with requests.get(url, stream=True, timeout=180) as resp:
        if resp.status_code >= 400:
            raise RuntimeError(f"下载失败: HTTP {resp.status_code}, url={url}")
        with out_file.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def copy_file_if_exists(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def encode_image_data_uri(path: Path) -> str:
    raw = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def resolve_image_ref_for_payload(value: str, project_root: Path) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://") or text.startswith("data:"):
        return text

    image_path = Path(text).expanduser()
    if not image_path.is_absolute():
        image_path = (project_root / image_path).resolve()
    if image_path.exists() and image_path.is_file():
        return encode_image_data_uri(image_path)
    return text


def ensure_list_str(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def is_scene_modifier_prop_id(prop_id: str) -> bool:
    upper_id = str(prop_id or "").upper()
    if any(token in upper_id for token in TRUE_PROP_ID_TOKENS):
        return False
    return any(token in upper_id for token in SCENE_MODIFIER_PROP_ID_TOKENS + COSTUME_MODIFIER_PROP_ID_TOKENS)


def parse_optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("-"):
            sign = -1
            text = text[1:]
        else:
            sign = 1
        if text.isdigit():
            return sign * int(text)
    return None


def parse_optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def load_duration_overrides(path: Path) -> dict[str, float]:
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError("duration overrides root must be object")
    out: dict[str, float] = {}
    for k, v in data.items():
        shot_id = str(k).strip().upper()
        if not shot_id:
            continue
        fv = parse_optional_float(v)
        if fv is None:
            continue
        out[shot_id] = float(fv)
    return out


def load_execution_overlays(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError("execution overlays root must be object")
    return data


def overlay_entries_for_shot(overlays: dict[str, Any], shot_id: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for key in ("default", "*", shot_id.upper()):
        raw = overlays.get(key)
        if isinstance(raw, dict):
            entries.append(raw)
    return entries


def append_prompt_text(base: str, additions: list[str]) -> str:
    text = str(base or "").strip()
    for addition in additions:
        clean = str(addition or "").strip()
        if not clean or clean in text:
            continue
        text = f"{text} {clean}".strip() if text else clean
    return text


def apply_execution_overlays(record: dict[str, Any], shot_id: str, overlays: dict[str, Any]) -> dict[str, Any]:
    if not overlays:
        return record
    entries = overlay_entries_for_shot(overlays, shot_id)
    if not entries:
        return record

    hydrated = json.loads(json.dumps(record, ensure_ascii=False))
    prompt_render = hydrated.setdefault("prompt_render", {})
    if not isinstance(prompt_render, dict):
        prompt_render = {}
        hydrated["prompt_render"] = prompt_render

    applied: list[dict[str, Any]] = []
    for entry in entries:
        prompt_entry = entry.get("prompt_render") if isinstance(entry.get("prompt_render"), dict) else {}
        additions = (
            ensure_list_str(entry.get("append_positive_core"))
            + ensure_list_str(entry.get("positive_core_append"))
            + ensure_list_str(entry.get("shot_positive_core_append"))
            + ensure_list_str(prompt_entry.get("append_positive_core"))
            + ensure_list_str(prompt_entry.get("positive_core_append"))
            + ensure_list_str(prompt_entry.get("shot_positive_core_append"))
        )
        if additions:
            prompt_render["shot_positive_core"] = append_prompt_text(
                str(prompt_render.get("shot_positive_core") or ""),
                additions,
            )

        negative_terms = (
            ensure_list_str(entry.get("negative_prompt"))
            + ensure_list_str(entry.get("avoid_terms"))
            + ensure_list_str(prompt_entry.get("negative_prompt"))
            + ensure_list_str(prompt_entry.get("avoid_terms"))
        )
        if negative_terms:
            prompt_render["negative_prompt"] = unique_keep_order(
                ensure_list_str(prompt_render.get("negative_prompt")) + negative_terms
            )

        applied.append(
            {
                "name": str(entry.get("name") or entry.get("overlay_id") or "execution_overlay"),
                "positive_core_additions": additions,
                "negative_prompt_additions": negative_terms,
            }
        )

    hydrated["execution_overlay"] = {
        "shot_id": shot_id,
        "applied": applied,
        "source": "run_seedance_test.py --execution-overlays",
        "policy": "execution-only prompt overlay; original planning record is not mutated",
    }
    return hydrated


def parse_image_input_map(image_input_map_path: Path) -> dict[str, Any]:
    if not image_input_map_path.exists():
        raise FileNotFoundError(f"image input map not found: {image_input_map_path}")
    payload = read_json(image_input_map_path)
    if not isinstance(payload, dict):
        raise ValueError("image input map root must be a JSON object")
    return payload


def split_prompt_segments(text: str) -> list[str]:
    return [seg.strip() for seg in re.split(r"[；;\n]+", str(text or "").strip()) if seg.strip()]


def split_value_items(value: str) -> list[str]:
    items = [part.strip() for part in re.split(r"[、,，/]+", str(value or "").strip())]
    return [item for item in items if item]


def extract_labeled_value(segments: list[str], label: str) -> str:
    prefix = f"{label}:"
    for seg in segments:
        if seg.startswith(prefix):
            return seg[len(prefix) :].strip()
    return ""


def parse_keyframe_prompt_metadata(prompt_text: str) -> dict[str, Any]:
    segments = split_prompt_segments(prompt_text)
    scene_must = split_value_items(extract_labeled_value(segments, "场景必须出现"))
    props = split_value_items(extract_labeled_value(segments, "关键道具"))
    return {
        "scene_name": extract_labeled_value(segments, "场景"),
        "must_have_elements": scene_must,
        "prop_must_visible": props,
        "lighting_anchor": extract_labeled_value(segments, "光线"),
        "shot_type": extract_labeled_value(segments, "镜头"),
        "movement": extract_labeled_value(segments, "运动"),
        "framing_focus": extract_labeled_value(segments, "构图焦点"),
        "action_intent": extract_labeled_value(segments, "动作意图"),
        "emotion_intent": extract_labeled_value(segments, "情绪意图"),
    }


def resolve_keyframe_prompt_path(
    shot_id: str,
    image_input_map_path: Path | None,
    keyframe_prompts_root: Path | None,
) -> Path | None:
    candidates: list[Path] = []
    if keyframe_prompts_root is not None:
        candidates.append(keyframe_prompts_root / shot_id / "start" / "prompt.txt")
    if image_input_map_path is not None:
        candidates.append(image_input_map_path.parent / shot_id / "start" / "prompt.txt")

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


def load_keyframe_prompt_metadata(
    shot_id: str,
    image_input_map_path: Path | None,
    keyframe_prompts_root: Path | None,
) -> tuple[dict[str, Any], str]:
    prompt_path = resolve_keyframe_prompt_path(
        shot_id=shot_id,
        image_input_map_path=image_input_map_path,
        keyframe_prompts_root=keyframe_prompts_root,
    )
    if prompt_path is None:
        return {}, ""
    prompt_text = prompt_path.read_text(encoding="utf-8")
    metadata = parse_keyframe_prompt_metadata(prompt_text)
    metadata["prompt_path"] = str(prompt_path)
    return metadata, prompt_text


def parse_image_input_entry(raw: Any) -> tuple[str, str]:
    if isinstance(raw, str):
        image = raw.strip()
        return image, ""
    if isinstance(raw, dict):
        image = str(
            raw.get("image")
            or raw.get("image_url")
            or raw.get("first_image")
            or raw.get("first_frame_url")
            or ""
        ).strip()
        last_image = str(
            raw.get("last_image")
            or raw.get("last_image_url")
            or raw.get("last_frame_url")
            or raw.get("end_image")
            or ""
        ).strip()
        return image, last_image
    return "", ""


def resolve_image_inputs(
    shot_id: str,
    record: dict[str, Any],
    image_input_map: dict[str, Any],
    cli_image_url: str,
    cli_last_image_url: str,
) -> tuple[str, str]:
    global_settings = record.get("global_settings", {})
    prompt_render = record.get("prompt_render", {})
    artifacts = record.get("artifacts", {})

    shot_entry = image_input_map.get(shot_id, {})
    default_entry = image_input_map.get("default", {})
    shot_image, shot_last_image = parse_image_input_entry(shot_entry)
    default_image, default_last_image = parse_image_input_entry(default_entry)

    record_image_candidates = [
        global_settings.get("image"),
        global_settings.get("image_url"),
        global_settings.get("first_image"),
        global_settings.get("first_frame_url"),
        global_settings.get("start_image"),
        global_settings.get("start_image_url"),
        prompt_render.get("image"),
        prompt_render.get("image_url"),
        prompt_render.get("first_image"),
        prompt_render.get("first_frame_url"),
        artifacts.get("first_frame_url"),
        artifacts.get("keyframe_start_url"),
    ]
    record_last_image_candidates = [
        global_settings.get("last_image"),
        global_settings.get("last_image_url"),
        global_settings.get("end_image"),
        global_settings.get("end_image_url"),
        global_settings.get("last_frame_url"),
        prompt_render.get("last_image"),
        prompt_render.get("last_image_url"),
        prompt_render.get("last_frame_url"),
        prompt_render.get("end_image"),
        artifacts.get("last_frame_url"),
        artifacts.get("keyframe_end_url"),
    ]

    def first_non_empty(values: list[Any]) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    image = first_non_empty(
        [
            shot_image,
            cli_image_url,
            first_non_empty(record_image_candidates),
            default_image,
        ]
    )
    last_image = first_non_empty(
        [
            shot_last_image,
            cli_last_image_url,
            first_non_empty(record_last_image_candidates),
            default_last_image,
        ]
    )
    return image, last_image


def fallback_non_negative_profile(profile_id: str = "fallback_non_negative") -> dict[str, Any]:
    return {
        "profile_id": profile_id,
        "provider": "fallback",
        "model": MODEL_NAME,
        "supports_negative_prompt": False,
        "supports_audio_generation": True,
        "duration_min_sec": MIN_DURATION_SEC,
        "duration_max_sec": MAX_DURATION_SEC,
        "supported_resolutions": [DEFAULT_RESOLUTION],
        "supported_ratios": [DEFAULT_RATIO],
        "payload_fields": {
            "positive_prompt_field": "prompt",
            "negative_prompt_field": None,
            "duration_field": "duration",
            "resolution_field": "resolution",
            "ratio_field": "ratio",
            "audio_field": "generate_audio",
        },
    }


def builtin_seedance15_i2v_atlas_profile() -> dict[str, Any]:
    return {
        "profile_id": "seedance15_i2v_atlas",
        "provider": "atlascloud",
        "model": MODEL_NAME,
        "supports_negative_prompt": False,
        "supports_audio_generation": True,
        "duration_min_sec": 4,
        "duration_max_sec": 12,
        "default_resolution": DEFAULT_RESOLUTION,
        "default_ratio": DEFAULT_RATIO,
        "supported_resolutions": ["480p", "720p", "1080p"],
        "supported_ratios": ["9:16"],
        "payload_fields": {
            "positive_prompt_field": "prompt",
            "negative_prompt_field": None,
            "duration_field": "duration",
            "resolution_field": "resolution",
            "ratio_field": "aspect_ratio",
            "audio_field": "generate_audio",
            "image_field": "image",
            "last_image_field": "last_image",
        },
    }


def builtin_seedance15_i2v_novita_profile() -> dict[str, Any]:
    return {
        "profile_id": "seedance15_i2v_novita",
        "provider": "novita",
        "model": NOVITA_MODEL_NAME,
        "include_model_in_payload": False,
        "supports_negative_prompt": False,
        "supports_audio_generation": True,
        "duration_min_sec": 4,
        "duration_max_sec": 12,
        "default_resolution": "480p",
        "default_ratio": "9:16",
        "supported_resolutions": ["480p", "720p", "1080p"],
        "supported_ratios": ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
        "payload_defaults": {
            "fps": 24,
            "seed": 42,
            "watermark": False,
            "camera_fixed": False,
            "service_tier": "default",
            "execution_expires_after": 172800,
        },
        "payload_fields": {
            "positive_prompt_field": "prompt",
            "negative_prompt_field": None,
            "duration_field": "duration",
            "resolution_field": "resolution",
            "ratio_field": "ratio",
            "audio_field": "generate_audio",
            "image_field": "image",
            "last_image_field": None,
            "camera_fixed_field": "camera_fixed",
            "seed_field": "seed",
        },
    }


def builtin_model_profile(profile_id: str) -> dict[str, Any] | None:
    normalized = str(profile_id or "").strip()
    if normalized == "seedance15_i2v_atlas":
        return builtin_seedance15_i2v_atlas_profile()
    if normalized == "seedance15_i2v_novita":
        return builtin_seedance15_i2v_novita_profile()
    return None


def apply_video_model_profile_defaults(profile: dict[str, Any], video_model: str) -> dict[str, Any]:
    if not video_model:
        return profile
    normalized = normalize_video_model(video_model)
    builtin = builtin_model_profile(profile_id_for_video_model(normalized))
    if builtin is None:
        return profile
    merged = json.loads(json.dumps(builtin, ensure_ascii=False))
    for key, value in profile.items():
        if key == "payload_fields" and isinstance(value, dict):
            fields = merged.get("payload_fields", {})
            if isinstance(fields, dict):
                fields.update(value)
                if normalized == "novita-seedance1.5":
                    fields["last_image_field"] = None
                merged["payload_fields"] = fields
            continue
        if key == "payload_defaults" and isinstance(value, dict):
            defaults = merged.get("payload_defaults", {})
            if isinstance(defaults, dict):
                defaults.update(value)
                merged["payload_defaults"] = defaults
            continue
        merged[key] = value
    if normalized == "novita-seedance1.5":
        merged["provider"] = "novita"
        merged["model"] = NOVITA_MODEL_NAME
        merged["include_model_in_payload"] = False
        merged["default_resolution"] = str(merged.get("default_resolution") or "480p")
        merged["default_ratio"] = str(merged.get("default_ratio") or "9:16")
    return merged


def load_model_profiles_catalog(
    profile_file: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if not profile_file.exists():
        issues.append(
            {
                "type": "missing_profile_file",
                "detail": f"profile file not found: {profile_file}",
            }
        )
        return {}, issues

    try:
        data = read_json(profile_file)
    except Exception as exc:
        issues.append(
            {
                "type": "invalid_profile_file",
                "detail": f"failed to parse profile file: {exc}",
            }
        )
        return {}, issues

    profiles = data.get("profiles")
    if not isinstance(profiles, list):
        issues.append(
            {"type": "invalid_profiles_format", "detail": "profiles field is not a list"}
        )
        return {}, issues

    catalog: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        profile_id = str(profile.get("profile_id", "")).strip()
        if not profile_id:
            continue
        catalog[profile_id] = profile
    return catalog, issues


def load_character_lock_catalog(
    profile_file: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if not profile_file.exists():
        issues.append(
            {
                "type": "missing_character_lock_profile_file",
                "detail": f"character lock file not found: {profile_file}",
            }
        )
        return {}, issues

    try:
        data = read_json(profile_file)
    except Exception as exc:
        issues.append(
            {
                "type": "invalid_character_lock_profile_file",
                "detail": f"failed to parse character lock file: {exc}",
            }
        )
        return {}, issues

    profiles = data.get("profiles")
    if not isinstance(profiles, list):
        issues.append(
            {
                "type": "invalid_character_lock_profiles_format",
                "detail": "profiles field is not a list",
            }
        )
        return {}, issues

    catalog: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        profile_id = str(profile.get("lock_profile_id", "")).strip()
        if not profile_id:
            continue
        catalog[profile_id] = profile
    return catalog, issues


def is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def merge_character_node_with_lock(
    node: dict[str, Any],
    lock_catalog: dict[str, dict[str, Any]],
    downgrades: list[dict[str, Any]],
) -> dict[str, Any]:
    merged = json.loads(json.dumps(node, ensure_ascii=False))
    lock_profile_id = str(merged.get("lock_profile_id", "")).strip()
    if not lock_profile_id:
        return merged

    lock_profile = lock_catalog.get(lock_profile_id)
    if lock_profile is None:
        downgrades.append(
            {
                "type": "character_lock_profile_not_found",
                "detail": (
                    f"lock_profile_id={lock_profile_id} not found for "
                    f"character={merged.get('character_id', '')}"
                ),
            }
        )
        return merged

    keys_to_fill = [
        "character_id",
        "name",
        "visual_anchor",
        "appearance_lock_profile",
        "costume_lock_profile",
        "appearance_anchor_tokens",
        "forbidden_drift",
    ]
    for key in keys_to_fill:
        if is_missing_value(merged.get(key)) and (key in lock_profile):
            merged[key] = lock_profile[key]

    return merged


def hydrate_record_with_character_locks(
    record: dict[str, Any],
    lock_catalog: dict[str, dict[str, Any]],
    lock_catalog_issues: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    hydrated = json.loads(json.dumps(record, ensure_ascii=False))
    downgrades = list(lock_catalog_issues)
    character_anchor = hydrated.get("character_anchor")
    if not isinstance(character_anchor, dict):
        return hydrated, downgrades

    primary = character_anchor.get("primary")
    if isinstance(primary, dict):
        character_anchor["primary"] = merge_character_node_with_lock(
            node=primary,
            lock_catalog=lock_catalog,
            downgrades=downgrades,
        )

    secondary = character_anchor.get("secondary")
    if isinstance(secondary, list):
        new_secondary: list[dict[str, Any]] = []
        for item in secondary:
            if isinstance(item, dict):
                new_secondary.append(
                    merge_character_node_with_lock(
                        node=item,
                        lock_catalog=lock_catalog,
                        downgrades=downgrades,
                    )
                )
        character_anchor["secondary"] = new_secondary

    hydrated["character_anchor"] = character_anchor
    return hydrated, downgrades


def resolve_model_profile(
    profile_id: str,
    catalog: dict[str, dict[str, Any]],
    catalog_issues: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    downgrades = list(catalog_issues)
    if profile_id in catalog:
        return catalog[profile_id], downgrades

    builtin = builtin_model_profile(profile_id)
    if builtin is not None:
        downgrades.append(
            {
                "type": "profile_loaded_from_builtin",
                "detail": f"profile_id={profile_id} not found in catalog; using built-in profile",
            }
        )
        return builtin, downgrades

    downgrades.append(
        {
            "type": "profile_not_found",
            "detail": f"profile_id={profile_id} not found in profile catalog",
        }
    )
    return fallback_non_negative_profile(profile_id), downgrades


def parse_profile_ids(profile_ids_arg: str, model_profile_id: str) -> list[str]:
    if profile_ids_arg.strip():
        requested = [s.strip() for s in profile_ids_arg.split(",") if s.strip()]
    else:
        requested = [model_profile_id.strip() or DEFAULT_PROFILE_ID]

    ordered = unique_keep_order(requested)
    if not ordered:
        return [DEFAULT_PROFILE_ID]
    return ordered


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


def is_conditional_modern_setting_term(term: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(term or "").strip().lower())
    if "modern clothes" in normalized and "unless required" in normalized:
        return True
    return "现代服装" in term and "除非" in term and "设定" in term


def normalize_avoid_term(term: str) -> str:
    stripped = str(term or "").strip()
    if is_conditional_modern_setting_term(stripped):
        return "setting-inconsistent clothing, architecture, or props"
    if stripped == "现代穿帮":
        return "时代/地域感错误"
    return stripped


def normalize_avoid_terms(terms: list[str]) -> list[str]:
    return unique_keep_order(
        [normalized for term in terms if (normalized := normalize_avoid_term(term))]
    )


def has_explicit_modern_ban(avoid_terms: list[str]) -> bool:
    for term in avoid_terms:
        if is_conditional_modern_setting_term(term):
            continue
        lowered = str(term or "").lower()
        if any(
            token in lowered
            for token in [
                "modern clothes",
                "modern clothing",
                "modern architecture",
                "modern building",
                "modern props",
                "modern objects",
            ]
        ):
            return True
        if any(token in str(term or "") for token in ["现代服装", "现代建筑", "现代道具"]):
            return True
    return False


def build_positive_constraints_from_avoid(avoid_terms: list[str]) -> str:
    base = (
        "质量与连续性约束：保持写实电影质感与真实皮肤纹理；人物脸部和手部解剖结构稳定；"
        "遵循当前项目的时代、地域、服装、建筑与道具设定；画面干净，无水印与logo；"
        "帧间连续稳定，无明显闪烁和跳帧。"
    )
    if not avoid_terms:
        return base
    joined = " / ".join(avoid_terms)
    return f"{base} 重点控制项参考：{joined}。"


def collect_character_nodes(character_anchor: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    primary = character_anchor.get("primary")
    if isinstance(primary, dict):
        nodes.append(primary)
    secondary = character_anchor.get("secondary")
    if isinstance(secondary, list):
        nodes.extend([item for item in secondary if isinstance(item, dict)])
    return nodes


def build_shot_context_text(record: dict[str, Any]) -> str:
    prompt_render = record.get("prompt_render", {})
    shot_execution = record.get("shot_execution", {})
    camera_plan = shot_execution.get("camera_plan", {}) if isinstance(shot_execution, dict) else {}
    dialogue_language = record.get("dialogue_language", {})
    if not isinstance(dialogue_language, dict):
        dialogue_language = {}
    dialogue_lines = dialogue_language.get("dialogue_lines", []) if isinstance(dialogue_language, dict) else []
    dialogue_text = " ".join(
        " ".join([str(item.get("speaker", "")), str(item.get("text", ""))])
        for item in dialogue_lines
        if isinstance(item, dict)
    )
    return " ".join(
        [
            str(prompt_render.get("shot_positive_core", "")) if isinstance(prompt_render, dict) else "",
            str(shot_execution.get("action_intent", "")) if isinstance(shot_execution, dict) else "",
            str(shot_execution.get("emotion_intent", "")) if isinstance(shot_execution, dict) else "",
            str(camera_plan.get("framing_focus", "")) if isinstance(camera_plan, dict) else "",
            dialogue_text,
        ]
    )


def prohibited_cigarette_action_matches(text: str) -> list[str]:
    raw = str(text or "")
    matches: list[str] = []
    for pattern in PROHIBITED_CIGARETTE_ACTION_PATTERNS:
        for match in pattern.finditer(raw):
            matches.append(raw[max(0, match.start() - 36) : min(len(raw), match.end() + 48)].strip())
    return list(dict.fromkeys(matches))


def assert_no_prohibited_cigarette_actions(shot_id: str, text: str) -> None:
    matches = prohibited_cigarette_action_matches(text)
    if not matches:
        return
    raise RuntimeError(
        f"{shot_id} prompt contains prohibited cigarette-lighting/extinguishing action: "
        + " | ".join(matches[:4])
        + "。禁止生成点香烟、点燃香烟、按灭香烟、熄灭烟头等吸烟动作；烧文件等非香烟火源动作不在此规则内。"
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
            "lock_profile_id": "EXTRA_WAITER_LOCK_V1",
            "lock_prompt_enabled": True,
            "visual_anchor": "银座高级酒店服务员，整洁制服，普通工作人员气质，反应真实不过度戏剧化",
            "persona_anchor": ["紧张", "职业化"],
            "speech_style_anchor": ["短促", "慌张"],
        }
    if any(token in context_text for token in ("警员", "警方", "警车", "刑警同事")):
        return {
            "character_id": "EXTRA_POLICE",
            "name": "警员",
            "lock_profile_id": "EXTRA_POLICE_LOCK_V1",
            "lock_prompt_enabled": True,
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


def filter_character_anchor_for_shot(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    source_anchor = record.get("character_anchor", {})
    if not isinstance(source_anchor, dict):
        return {}, {"policy": "no_character_anchor", "selected": []}

    context_text = build_shot_context_text(record)
    selected = [
        node
        for node in collect_character_nodes(source_anchor)
        if character_node_is_explicit(node, context_text)
    ]
    source_count = len(collect_character_nodes(source_anchor))
    inferred = False
    if not selected:
        ephemeral = infer_ephemeral_character_node(context_text)
        if ephemeral is not None:
            selected = [ephemeral]
            inferred = True
        elif source_count:
            selected = [
                {
                    "character_id": "SCENE_ONLY",
                    "name": "场景主体",
                    "lock_profile_id": "",
                    "lock_prompt_enabled": False,
                    "visual_anchor": "本镜头以空间、道具或群体反应为主体，不强制出现系列主角",
                    "persona_anchor": ["环境叙事"],
                    "speech_style_anchor": [],
                }
            ]
            inferred = True

    filtered = {
        "primary": selected[0] if selected else {},
        "secondary": selected[1:],
    }
    report = {
        "policy": "explicit_shot_characters_only",
        "source_count": source_count,
        "selected": [
            str(node.get("character_id") or node.get("name") or "").strip()
            for node in selected
        ],
        "inferred_ephemeral": inferred,
    }
    return filtered, report


def build_character_lock_phrases(character_anchor: dict[str, Any]) -> list[str]:
    phrases: list[str] = []
    for char in collect_character_nodes(character_anchor):
        if char.get("lock_prompt_enabled") is False:
            continue
        name = str(char.get("name") or char.get("character_id") or "角色").strip()

        appearance = char.get("appearance_lock_profile", {})
        if isinstance(appearance, dict):
            ap_fields = [
                ("形象定位", "image_positioning_tag"),
                ("人种族裔", "ethnicity"),
                ("整体身材", "body_shape"),
                ("三维体围", "measurements"),
                ("发型发色", "hair_style_color"),
                ("脸部细节", "facial_features"),
                ("皮肤质感", "skin_texture"),
                ("体态步态", "posture_gait"),
                ("额外识别", "extra_identifiers"),
            ]
            ap_parts = [
                f"{label}:{str(appearance.get(key, '')).strip()}"
                for (label, key) in ap_fields
                if str(appearance.get(key, "")).strip()
            ]
            if ap_parts:
                phrases.append(f"{name}容貌锁定：{'；'.join(ap_parts)}")

        costume = char.get("costume_lock_profile", {})
        if isinstance(costume, dict):
            cs_fields = [
                ("外层服饰", "outerwear"),
                ("内层服饰", "innerwear"),
                ("下装", "lower_garment"),
                ("鞋履", "footwear"),
                ("配饰", "accessories"),
                ("主色盘", "color_palette"),
                ("材质质感", "material_texture"),
                ("磨损脏污", "wear_and_tear"),
            ]
            cs_parts = [
                f"{label}:{str(costume.get(key, '')).strip()}"
                for (label, key) in cs_fields
                if str(costume.get(key, "")).strip()
            ]
            if cs_parts:
                phrases.append(f"{name}服饰锁定：{'；'.join(cs_parts)}")

        anchor_tokens = ensure_list_str(char.get("appearance_anchor_tokens"))
        if anchor_tokens:
            phrases.append(f"{name}容貌锁定锚点：{'、'.join(anchor_tokens)}")

    return phrases


def infer_voice_hint(char: dict[str, Any]) -> str:
    explicit = str(char.get("voice_hint") or "").strip()
    if explicit:
        return explicit

    name = str(char.get("name") or "").strip()
    char_id = str(char.get("character_id") or "").strip().upper()
    combined = f"{name} {char_id}"
    if "阿翠" in combined or "FEMALE" in char_id or "女" in combined:
        return "轻柔克制女声"
    if "林辰" in combined or "MALE" in char_id or "男" in combined:
        return "低沉沙哑男声"
    return ""


def build_character_role_lock_lines(character_anchor: dict[str, Any], record: dict[str, Any] | None = None) -> list[str]:
    record = record or {}
    lines: list[str] = []
    for char in collect_character_nodes(character_anchor):
        name = str(char.get("name") or char.get("character_id") or "角色").strip()
        visual_anchor = str(char.get("visual_anchor") or "").strip()
        if character_has_age_body_overlay(record, name):
            visual_anchor = remove_age_body_lock_conflicts(visual_anchor)
        appearance = char.get("appearance_lock_profile", {})
        costume = char.get("costume_lock_profile", {})
        hair = str(appearance.get("hair_style_color") or "").strip() if isinstance(appearance, dict) else ""
        face = str(appearance.get("facial_features") or "").strip() if isinstance(appearance, dict) else ""
        skin = str(appearance.get("skin_texture") or "").strip() if isinstance(appearance, dict) else ""
        outerwear = str(costume.get("outerwear") or "").strip() if isinstance(costume, dict) else ""
        innerwear = str(costume.get("innerwear") or "").strip() if isinstance(costume, dict) else ""
        persona = "、".join(ensure_list_str(char.get("persona_anchor")))
        voice = infer_voice_hint(char)

        parts = [
            visual_anchor,
            face,
            hair,
            skin,
            outerwear,
            innerwear,
            voice,
            persona,
        ]
        parts = unique_keep_order([part for part in parts if part])
        if parts:
            line = f"- {name}：{'；'.join(parts)}。"
            if character_has_age_body_overlay(record, name):
                line = remove_age_body_lock_conflicts(line)
            lines.append(line)
        else:
            lines.append(f"- {name}：保持既有容貌与服饰一致。")
    return lines


def format_seconds_label(value: float) -> str:
    text = f"{max(0.0, float(value)):.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return text


def normalize_spoken_lines(items: Any, default_speaker: str = "") -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return lines
    for item in items:
        if isinstance(item, str):
            text = item.strip()
            if text:
                lines.append({"speaker": default_speaker, "text": text})
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("line") or item.get("content") or "").strip()
        if not text:
            continue
        line = dict(item)
        line["speaker"] = str(item.get("speaker") or default_speaker).strip()
        line["text"] = text
        lines.append(line)
    return lines


def estimate_dialogue_timeline(
    dialogue_lines: list[dict[str, Any]],
    duration_sec: float,
) -> list[dict[str, Any]]:
    if not dialogue_lines:
        return []

    explicit: list[dict[str, Any]] = []
    all_explicit = True
    for item in dialogue_lines:
        start_sec = parse_optional_float(item.get("start_sec"))
        end_sec = parse_optional_float(item.get("end_sec"))
        if start_sec is None or end_sec is None or end_sec <= start_sec:
            all_explicit = False
            break
        explicit.append(
            {
                "speaker": str(item.get("speaker") or "角色").strip(),
                "text": str(item.get("text") or "").strip(),
                "source": normalize_dialogue_source(item.get("source"), item.get("text", ""), item.get("purpose", "")),
                "listener": dialogue_listener_name(item),
                "start_sec": max(0.0, start_sec),
                "end_sec": max(start_sec, end_sec),
            }
        )
    if all_explicit:
        return explicit

    normalized_lines = [
        {
            "speaker": str(item.get("speaker") or "角色").strip(),
            "text": str(item.get("text") or "").strip(),
            "source": normalize_dialogue_source(item.get("source"), item.get("text", ""), item.get("purpose", "")),
            "listener": dialogue_listener_name(item),
        }
        for item in dialogue_lines
    ]
    n = len(normalized_lines)
    lead_in = 0.5
    pause_sec = 0.4 if n >= 3 else (0.3 if n == 2 else 0.0)
    tail_hold = 0.5
    pause_total = max(0.0, (n - 1) * pause_sec)
    speak_budget = max(1.2, float(duration_sec) - lead_in - tail_hold - pause_total)

    weights: list[float] = []
    for line in normalized_lines:
        text = re.sub(r"[\s，。！？!?,、：:；;\"'“”‘’]", "", line["text"])
        weights.append(max(1.0, 0.9 + len(text) * 0.35))

    total_weight = sum(weights) or float(n)
    cursor = lead_in
    timeline: list[dict[str, Any]] = []
    for idx, line in enumerate(normalized_lines):
        raw_span = speak_budget * (weights[idx] / total_weight)
        remaining_lines = n - idx - 1
        max_end = float(duration_sec) - tail_hold - (remaining_lines * pause_sec)
        end_sec = min(max_end, cursor + raw_span)
        if end_sec <= cursor:
            end_sec = min(float(duration_sec) - tail_hold, cursor + 0.8)
        timeline.append(
            {
                "speaker": line["speaker"],
                "text": line["text"],
                "source": line.get("source", "onscreen"),
                "listener": line.get("listener", ""),
                "start_sec": round(cursor, 2),
                "end_sec": round(end_sec, 2),
            }
        )
        cursor = end_sec + pause_sec
    return timeline


def estimate_narration_timeline(
    narration_lines: list[dict[str, Any]],
    duration_sec: float,
) -> list[dict[str, Any]]:
    if not narration_lines:
        return []

    explicit: list[dict[str, Any]] = []
    all_explicit = True
    for item in narration_lines:
        start_sec = parse_optional_float(item.get("start_sec"))
        end_sec = parse_optional_float(item.get("end_sec"))
        if start_sec is None or end_sec is None or end_sec <= start_sec:
            all_explicit = False
            break
        explicit.append(
            {
                "text": str(item.get("text") or "").strip(),
                "start_sec": max(0.0, start_sec),
                "end_sec": max(start_sec, end_sec),
            }
        )
    if all_explicit:
        return explicit

    normalized_lines = [
        {"text": str(item.get("text") or "").strip()}
        for item in narration_lines
        if str(item.get("text") or "").strip()
    ]
    n = len(normalized_lines)
    if n == 0:
        return []

    lead_in = 0.4
    pause_sec = 0.35 if n >= 2 else 0.0
    tail_hold = 0.4
    pause_total = max(0.0, (n - 1) * pause_sec)
    speak_budget = max(1.2, float(duration_sec) - lead_in - tail_hold - pause_total)
    weights = [
        max(1.0, 0.8 + len(re.sub(r"[\s，。！？!?,、：:；;\"'“”‘’]", "", line["text"])) * 0.3)
        for line in normalized_lines
    ]
    total_weight = sum(weights) or float(n)
    cursor = lead_in
    timeline: list[dict[str, Any]] = []
    for idx, line in enumerate(normalized_lines):
        raw_span = speak_budget * (weights[idx] / total_weight)
        remaining_lines = n - idx - 1
        max_end = float(duration_sec) - tail_hold - (remaining_lines * pause_sec)
        end_sec = min(max_end, cursor + raw_span)
        if end_sec <= cursor:
            end_sec = min(float(duration_sec) - tail_hold, cursor + 0.8)
        timeline.append(
            {
                "text": line["text"],
                "start_sec": round(cursor, 2),
                "end_sec": round(end_sec, 2),
            }
        )
        cursor = end_sec + pause_sec
    return timeline


def build_dialogue_timeline_block(
    dialogue_lines: list[dict[str, Any]],
    character_anchor: dict[str, Any],
    duration_sec: float,
) -> list[str]:
    timeline = estimate_dialogue_timeline(dialogue_lines=dialogue_lines, duration_sec=duration_sec)
    if not timeline:
        return []

    known_names = [
        str(node.get("name") or node.get("character_id") or "").strip()
        for node in collect_character_nodes(character_anchor)
    ]
    known_names = [name for name in known_names if name]

    lines: list[str] = []
    for idx, line in enumerate(timeline):
        speaker = line["speaker"]
        source = normalize_dialogue_source(line.get("source"), line.get("text", ""), line.get("purpose", ""))
        listener = str(line.get("listener") or "").strip()
        if source == "phone":
            listener_text = listener or "画面内接电话的人"
            lines.append(
                f"{format_seconds_label(line['start_sec'])}-{format_seconds_label(line['end_sec'])}秒："
                f"电话/手机听筒里传来{speaker}的声音：“{line['text']}”；"
                f"{listener_text}正在听电话或接电话，画面内人物不要替{speaker}开口。"
            )
            if idx < len(timeline) - 1:
                next_line = timeline[idx + 1]
                if next_line["start_sec"] > line["end_sec"]:
                    lines.append(
                        f"{format_seconds_label(line['end_sec'])}-"
                        f"{format_seconds_label(next_line['start_sec'])}秒：短暂停顿，情绪延续。"
                    )
            continue
        if source == "offscreen":
            listener_text = listener or "画面内人物"
            visible_text = "、".join(known_names) if known_names else "画面内人物"
            lines.append(
                f"{format_seconds_label(line['start_sec'])}-{format_seconds_label(line['end_sec'])}秒："
                f"画外传来{speaker}的声音：“{line['text']}”；"
                f"旁白开始前画面先淡出或明显转暗；{listener_text}只做倾听反应，不替画外声音开口；"
                f"{visible_text}嘴唇闭合、下颌静止、不得出现旁白口型。"
            )
            if idx < len(timeline) - 1:
                next_line = timeline[idx + 1]
                if next_line["start_sec"] > line["end_sec"]:
                    lines.append(
                        f"{format_seconds_label(line['end_sec'])}-"
                        f"{format_seconds_label(next_line['start_sec'])}秒：短暂停顿，情绪延续。"
                    )
            continue
        others = [name for name in known_names if name and name != speaker]
        silent_clause = ""
        if others:
            silent_clause = (
                f" {'、'.join(others)}不说话，不张口，只保持沉默反应。"
            )
        lines.append(
            f"{format_seconds_label(line['start_sec'])}-{format_seconds_label(line['end_sec'])}秒："
            f"{speaker}开口说：“{line['text']}”{silent_clause}".strip()
        )
        if idx < len(timeline) - 1:
            next_line = timeline[idx + 1]
            if next_line["start_sec"] > line["end_sec"]:
                lines.append(
                    f"{format_seconds_label(line['end_sec'])}-"
                    f"{format_seconds_label(next_line['start_sec'])}秒：短暂停顿，情绪延续。"
                )
    return lines


def build_narration_timeline_block(
    narration_lines: list[dict[str, Any]],
    duration_sec: float,
    character_anchor: dict[str, Any],
) -> list[str]:
    timeline = estimate_narration_timeline(
        narration_lines=narration_lines,
        duration_sec=duration_sec,
    )
    if not timeline:
        return []

    visible_names = [
        str(node.get("name") or node.get("character_id") or "").strip()
        for node in collect_character_nodes(character_anchor)
    ]
    visible_names = unique_keep_order([name for name in visible_names if name])
    if visible_names:
        closed_mouth_clause = (
            f"声音来自画面外独立旁白，不属于{'、'.join(visible_names)}；"
            f"{'、'.join(visible_names)}全程闭嘴、嘴唇闭合、不做说话口型。"
        )
    else:
        closed_mouth_clause = "声音来自画面外独立旁白；画面内无人开口或做说话口型。"

    lines: list[str] = []
    for idx, line in enumerate(timeline):
        lines.append(
            f"{format_seconds_label(line['start_sec'])}-{format_seconds_label(line['end_sec'])}秒："
            f"画外旁白音轨播放：“{line['text']}”；{closed_mouth_clause}"
        )
        if idx < len(timeline) - 1:
            next_line = timeline[idx + 1]
            if next_line["start_sec"] > line["end_sec"]:
                lines.append(
                    f"{format_seconds_label(line['end_sec'])}-"
                    f"{format_seconds_label(next_line['start_sec'])}秒：短暂停顿，画面情绪延续。"
            )
    return lines


def onscreen_dialogue_speakers(dialogue_lines: list[dict[str, Any]]) -> list[str]:
    speakers: list[str] = []
    for line in dialogue_lines:
        source = normalize_dialogue_source(
            line.get("source"), line.get("text", ""), line.get("purpose", "")
        )
        if source != "onscreen":
            continue
        speaker = str(line.get("speaker") or "").strip()
        if speaker:
            speakers.append(speaker)
    return unique_keep_order(speakers)


def build_speaker_first_frame_self_check_lines(
    dialogue_lines: list[dict[str, Any]],
) -> list[str]:
    speakers = onscreen_dialogue_speakers(dialogue_lines)
    if not speakers:
        return []
    speaker_text = "、".join(speakers)
    return [
        f"首帧中画面内说话人（{speaker_text}）不得背对观众；脸部和嘴部必须对观众可辨认，眼神方向服从对白视线关系，不默认看镜头。",
        f"首帧中{speaker_text}的脸部和嘴部必须清楚可见、未被手机/手/道具/身体轮廓遮挡，便于后续口型自查。",
    ]


def build_dialogue_gaze_lines(record: dict[str, Any]) -> list[str]:
    first_frame = record.get("first_frame_contract") if isinstance(record.get("first_frame_contract"), dict) else {}
    dialogue_blocking = record.get("dialogue_blocking") if isinstance(record.get("dialogue_blocking"), dict) else {}
    contract: dict[str, Any] = {}
    for source in (dialogue_blocking, first_frame):
        for key in ("gaze_contract", "dialogue_addressing"):
            candidate = source.get(key) if isinstance(source, dict) else None
            if isinstance(candidate, dict) and candidate:
                contract = candidate
                break
        if contract:
            break
    if not contract:
        return []
    lines: list[str] = []
    entries = contract.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            rule = str(entry.get("rule") or "").strip()
            if rule:
                lines.append(rule)
    global_rule = str(contract.get("global_rule") or "").strip()
    if global_rule:
        lines.append(global_rule)
    return unique_keep_order(lines)


def build_speaker_face_visibility_lines(record: dict[str, Any], dialogue_lines: list[dict[str, Any]]) -> list[str]:
    first_frame = record.get("first_frame_contract") if isinstance(record.get("first_frame_contract"), dict) else {}
    speakers = onscreen_dialogue_speakers(dialogue_lines)
    explicit = first_frame.get("speaker_face_visibility") if isinstance(first_frame, dict) else {}
    if isinstance(explicit, dict):
        speakers.extend(str(key).strip() for key in explicit.keys() if str(key).strip())
    speakers = unique_keep_order([name for name in speakers if name])
    if not speakers:
        return []
    speaker_text = "、".join(speakers)
    return [
        f"{speaker_text}是本镜头画面内说话人，keyframe/首帧必须看见{speaker_text}的脸和嘴。",
        "说话人必须是正脸、三分之二侧脸或清晰侧脸；说话人脸部、眼睛和嘴部必须清楚无遮挡，并占主视觉。",
        "相机必须在说话人前侧或侧前方45度，不能从说话人背后拍；如果双方脸部可见性冲突，优先保证说话人的脸和嘴可见。",
    ]


def build_visible_character_first_frame_lines(
    record: dict[str, Any],
    dialogue_lines: list[dict[str, Any]],
) -> list[str]:
    names = visible_character_names_from_record(record)
    if not names:
        return []
    phone_listener_names: list[str] = []
    for line in dialogue_lines:
        if normalize_dialogue_source(line.get("source"), line.get("text", ""), line.get("purpose", "")) == "phone":
            listener = dialogue_listener_name(line)
            if listener:
                phone_listener_names.append(listener)
    visible_text = "、".join(names)
    lines = [
        f"首帧中可见角色（{visible_text}）必须露出脸部，正侧脸或三分之二侧脸均可；画面主体以可见五官和眼神为准；脸部可见不等于眼神看镜头。",
    ]
    phone_listener_text = "、".join(unique_keep_order(phone_listener_names))
    if phone_listener_text:
        lines.append(
            f"电话听者（{phone_listener_text}）可由手机或手部自然遮住部分嘴部，但脸部轮廓、眼睛和鼻梁必须可见。"
        )
    return lines


def visible_character_first_frame_policy_review(record: dict[str, Any]) -> dict[str, Any]:
    names = visible_character_names_from_record(record)
    first_frame = record.get("first_frame_contract", {})
    prompt_render = record.get("prompt_render", {})
    shot_execution = record.get("shot_execution", {})
    camera_plan = shot_execution.get("camera_plan", {}) if isinstance(shot_execution, dict) else {}
    visual_text = " ".join(
        [
            json.dumps(first_frame, ensure_ascii=False) if isinstance(first_frame, dict) else "",
            str(prompt_render.get("shot_positive_core") or "") if isinstance(prompt_render, dict) else "",
            str(camera_plan.get("shot_type") or "") if isinstance(camera_plan, dict) else "",
            str(camera_plan.get("framing_focus") or "") if isinstance(camera_plan, dict) else "",
            str(shot_execution.get("action_intent") or "") if isinstance(shot_execution, dict) else "",
        ]
    )
    lowered = visual_text.lower()
    negation_prefixes = ("不能", "不得", "不可", "不使用", "不要", "避免", "禁止", "严禁", "not ", "no ")
    back_view_terms: list[str] = []
    for term in ("背对", "背向", "背影", "背侧", "后侧", "后背", "from behind", "back to camera"):
        term_lower = term.lower()
        start = lowered.find(term_lower)
        if start < 0:
            continue
        prefix = lowered[max(0, start - 10):start]
        if any(marker in prefix for marker in negation_prefixes):
            continue
        back_view_terms.append(term)
    face_terms = [
        term
        for term in ("首帧人物脸部可见契约", "露出脸部", "脸部可见", "面向观众", "三分之二侧脸", "正侧脸", "可见五官", "face visible")
        if term.lower() in visual_text.lower()
    ]
    return {
        "applies": bool(names),
        "visible_characters": names,
        "rule": "first frame visible characters must show their face",
        "face_visibility_terms_found": unique_keep_order(face_terms),
        "back_view_terms_found": unique_keep_order(back_view_terms),
        "requires_review": bool(names and (back_view_terms or not face_terms)),
    }


def speaker_first_frame_policy_review(
    record: dict[str, Any],
    dialogue_lines: list[dict[str, Any]],
) -> dict[str, Any]:
    speakers = onscreen_dialogue_speakers(dialogue_lines)
    first_frame = record.get("first_frame_contract", {})
    prompt_render = record.get("prompt_render", {})
    shot_execution = record.get("shot_execution", {})
    camera_plan = shot_execution.get("camera_plan", {}) if isinstance(shot_execution, dict) else {}
    visual_text = " ".join(
        [
            json.dumps(first_frame, ensure_ascii=False) if isinstance(first_frame, dict) else "",
            str(prompt_render.get("shot_positive_core") or "") if isinstance(prompt_render, dict) else "",
            str(camera_plan.get("shot_type") or "") if isinstance(camera_plan, dict) else "",
            str(camera_plan.get("framing_focus") or "") if isinstance(camera_plan, dict) else "",
            str(shot_execution.get("action_intent") or "") if isinstance(shot_execution, dict) else "",
        ]
    )
    lowered = visual_text.lower()
    negation_prefixes = ("不能", "不得", "不可", "不使用", "不要", "避免", "禁止", "严禁", "not ", "no ")
    back_view_terms: list[str] = []
    for term in ("背对", "背向", "背影", "背侧", "后侧", "后背", "from behind", "back to camera"):
        term_lower = term.lower()
        start = lowered.find(term_lower)
        if start < 0:
            continue
        prefix = lowered[max(0, start - 10):start]
        if any(marker in prefix for marker in negation_prefixes):
            continue
        back_view_terms.append(term)
    return {
        "applies": bool(speakers),
        "onscreen_speakers": speakers,
        "rule": "first frame onscreen speaker must not face away from audience",
        "back_view_terms_found": unique_keep_order(back_view_terms),
        "requires_review": bool(speakers and back_view_terms),
    }


def build_scene_header(
    prefix: str,
    scene_name: str,
    must_elements: list[str],
    shot_type: str,
    lighting_anchor: str,
) -> str:
    header_parts = [
        prefix,
        scene_name,
        "、".join(must_elements) if must_elements else "",
        shot_type,
        lighting_anchor,
    ]
    header_parts = [part.strip("，,。；;[] ") for part in header_parts if str(part).strip()]
    return f"[场景：{'，'.join(unique_keep_order(header_parts))}]"


def shot_has_hand_focus(
    shot_type: str,
    framing_focus: str,
    action_intent: str,
    core: str,
    props: list[str],
) -> bool:
    combined = " ".join(
        [shot_type, framing_focus, action_intent, core, " ".join(props)]
    )
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
    has_closeup_token = any(token in shot_type or token in framing_focus for token in closeup_tokens)
    return has_hand_token and (has_closeup_token or "手部" in combined)


def build_hand_constraint_lines(
    shot_type: str,
    framing_focus: str,
    action_intent: str,
    core: str,
    props: list[str],
) -> list[str]:
    lines = [
        "人物手部解剖必须真实稳定，每只可见的手都清晰呈现五根手指。",
        "禁止缺指、四指、多指、并指、手指粘连、手部扭曲、手掌变形、手部畸形。",
    ]
    if shot_has_hand_focus(
        shot_type=shot_type,
        framing_focus=framing_focus,
        action_intent=action_intent,
        core=core,
        props=props,
    ):
        lines.extend(
            [
                "这是手部重点镜头，主手必须完整、清晰、稳定入镜，五根手指清楚可辨。",
                "指节、指腹、指甲、掌缘结构自然，手指之间自然分开，不能融合或缺失。",
                "不要用遮挡、裁切、运动模糊掩盖手指数量错误。",
            ]
        )
    return lines


def text_mentions_mobile_phone(text: str) -> bool:
    lowered = text.lower()
    return any(token in text for token in ("手机", "智能手机")) or any(
        token in lowered for token in ("mobile phone", "cell phone", "smartphone")
    )


COMMON_CHARACTER_NAME_EXPANSIONS = {
    "石川": "石川悠一",
    "悠一": "石川悠一",
    "健一": "田中健一",
    "田中": "田中健一",
    "美咲": "佐藤美咲",
    "彩花": "佐藤彩花",
    "樱子": "佐藤樱子",
    "小樱": "佐藤樱子",
}


def expand_common_character_name(value: str) -> str:
    text = str(value or "").strip()
    return COMMON_CHARACTER_NAME_EXPANSIONS.get(text, text)


def normalize_dialogue_source(value: Any, text: str = "", purpose: str = "") -> str:
    raw = str(value or "").strip().lower()
    if raw in {"phone", "telephone", "call", "mobile", "手机", "电话", "通话"}:
        return "phone"
    if raw in {"voiceover", "voice_over", "voice-over", "旁白", "画外音", "画外旁白"}:
        return "voiceover"
    if raw in {"offscreen", "off-screen", "radio", "broadcast", "画外", "画外声", "广播"}:
        return "offscreen"
    combined = " ".join([str(text or ""), str(purpose or "")])
    if any(token in combined for token in ("画外音", "画外旁白", "旁白")):
        return "voiceover"
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


def first_matching_character(text: str, character_anchor: dict[str, Any]) -> str:
    normalized = str(text or "").strip()
    for node in collect_character_nodes(character_anchor):
        name = str(node.get("name") or node.get("character_id") or "").strip()
        if name and (name in normalized or normalized in name):
            return name
        char_id = str(node.get("character_id") or "").strip()
        if char_id and (char_id in normalized or normalized in char_id):
            return name or char_id
        for alias in ensure_list_str(node.get("aliases")):
            if alias and (alias in normalized or normalized in alias):
                return name or alias
    return ""


def infer_phone_holder(text: str, character_anchor: dict[str, Any]) -> str:
    for node in collect_character_nodes(character_anchor):
        name = str(node.get("name") or node.get("character_id") or "").strip()
        if not name:
            continue
        candidates = [name] + ensure_list_str(node.get("aliases"))
        for candidate in candidates:
            if not candidate:
                continue
            if re.search(rf"{re.escape(candidate)}的手机", text):
                return name
            if re.search(
                rf"{re.escape(candidate)}[^。；，,]*?(拿|握|掏|取出|点开|推|接起|放下)[^。；，,]*?手机",
                text,
            ):
                return name
            if re.search(
                rf"手机[^。；，,]*?{re.escape(candidate)}[^。；，,]*?(拿|握|接起|查看|看)",
                text,
            ):
                return name
    return first_matching_character(text, character_anchor)


def infer_phone_screen_viewer(text: str, holder: str, character_anchor: dict[str, Any]) -> str:
    for pattern in (
        r"推到([^，。；,]{1,12})面前",
        r"朝向([^，。；,]{1,12})",
        r"给([^，。；,]{1,12})看",
    ):
        match = re.search(pattern, text)
        if match:
            raw = match.group(1).strip()
            expanded = expand_common_character_name(raw)
            if expanded != raw:
                return expanded
            matched = first_matching_character(raw, character_anchor)
            if matched:
                return matched
            if raw:
                return raw

    if re.search(r"手机[^。；]*?(来电|接起|震动)|(来电|接起|震动)[^。；]*?手机", text):
        return holder

    if "酒吧合影" in text or "不在场" in text or "照片" in text:
        if "石川" in text:
            return "石川悠一"
        if "警员" in text:
            return "警员"

    for node in collect_character_nodes(character_anchor):
        name = str(node.get("name") or node.get("character_id") or "").strip()
        if name and name != holder and name in text:
            return name
    return holder


def infer_phone_display_content(text: str) -> str:
    if "酒吧合影" in text or "合影" in text:
        return "酒吧合影或不在场证明照片"
    if "来电" in text:
        caller_match = re.search(r"显示([^，。；,]{1,16})来电", text)
        if caller_match:
            return f"{caller_match.group(1).strip()}来电"
        return "来电界面"
    if "照片" in text:
        return "剧情中提到的照片"
    return "剧情要求的手机画面"


def build_phone_prop_constraint_lines(
    *,
    record: dict[str, Any],
    character_anchor: dict[str, Any],
    core: str,
    framing_focus: str,
    action_intent: str,
    props: list[str],
    continuity_items: list[str],
) -> list[str]:
    scene_anchor = record.get("scene_anchor", {})
    shot_execution = record.get("shot_execution", {})
    text_parts = [
        core,
        framing_focus,
        action_intent,
        " ".join(props),
        " ".join(continuity_items),
        " ".join(ensure_list_str(scene_anchor.get("must_have_elements"))),
        " ".join(ensure_list_str(scene_anchor.get("prop_must_visible"))),
        str(shot_execution.get("sound_plan") or ""),
    ]
    text = " ".join(part for part in text_parts if part).strip()
    if not text_mentions_mobile_phone(text):
        return []

    holder = infer_phone_holder(text, character_anchor) or "剧情指定角色"
    viewer = infer_phone_screen_viewer(text, holder, character_anchor) or holder
    content = infer_phone_display_content(text)
    is_phone_call = any(
        normalize_dialogue_source(item.get("source"), item.get("text", ""), item.get("purpose", "")) == "phone"
        for item in normalize_spoken_lines(
            record.get("dialogue_language", {}).get("dialogue_lines", [])
            if isinstance(record.get("dialogue_language", {}), dict)
            else []
        )
    )
    if re.search(r"手机[^。；]*?(桌面|茶几)|(?:桌面|茶几)[^。；]*?手机", text):
        placement = "放在桌面时屏幕朝上"
        orientation = f"显示朝向{viewer}"
        content_clause = f"屏幕内容为{content}，不得改成无关照片、聊天软件或随机界面。"
    elif is_phone_call:
        placement = "手持接听时靠近耳侧或自然持握"
        orientation = f"屏幕朝内面向{holder}，屏幕内容不朝向镜头且不作为可见画面"
        content_clause = "不要在手机屏幕上生成额外画面、字幕、聊天界面或随机照片。"
    else:
        placement = "手持时屏幕稳定可见"
        orientation = f"显示朝向{viewer}"
        content_clause = f"屏幕内容为{content}，不得改成无关照片、聊天软件或随机界面。"
    return [
        "手机出现时必须明确归属、持握和屏幕朝向；不得凭空换手、漂移或自行滑动。",
        f"手机由{holder}控制；{placement}，{orientation}；{content_clause}",
    ]


def record_prop_library(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    library: dict[str, dict[str, Any]] = {}
    root_library = record.get("prop_library")
    if isinstance(root_library, dict):
        library.update({str(k): v for k, v in root_library.items() if isinstance(v, dict) and not is_scene_modifier_prop_id(str(k))})
    i2v_contract = record.get("i2v_contract", {})
    i2v_library = i2v_contract.get("prop_library") if isinstance(i2v_contract, dict) else {}
    if isinstance(i2v_library, dict):
        library.update({str(k): v for k, v in i2v_library.items() if isinstance(v, dict) and not is_scene_modifier_prop_id(str(k))})
    return library


def record_prop_contracts(record: dict[str, Any]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    root_contract = record.get("prop_contract")
    if isinstance(root_contract, list):
        contracts.extend([item for item in root_contract if isinstance(item, dict) and not is_scene_modifier_prop_id(str(item.get("prop_id") or ""))])
    i2v_contract = record.get("i2v_contract", {})
    i2v_props = i2v_contract.get("prop_contract") if isinstance(i2v_contract, dict) else []
    if isinstance(i2v_props, list):
        contracts.extend([item for item in i2v_props if isinstance(item, dict) and not is_scene_modifier_prop_id(str(item.get("prop_id") or ""))])
    return contracts


def is_screen_record(record: dict[str, Any]) -> bool:
    source_trace = record.get("source_trace")
    if not isinstance(source_trace, dict):
        return False
    return str(source_trace.get("source_type") or "").strip() == "screen_script"


def record_uses_montage_keyframe_moment(record: dict[str, Any]) -> bool:
    source_trace = record.get("source_trace") if isinstance(record.get("source_trace"), dict) else {}
    excerpt = str(source_trace.get("shot_source_excerpt") or "")
    scene_anchor = record.get("scene_anchor") if isinstance(record.get("scene_anchor"), dict) else {}
    scene_name = str(scene_anchor.get("scene_name") or "")
    return bool(str(record.get("keyframe_moment") or "").strip()) and (
        "蒙太奇" in scene_name or "蒙太奇" in excerpt or "快速剪辑" in excerpt or "【画面" in excerpt
    )


def large_scene_prop_ids_in_record(record: dict[str, Any]) -> list[str]:
    prop_ids: list[str] = []
    prop_ids.extend(record_prop_library(record).keys())
    prop_ids.extend(
        str(contract.get("prop_id") or "").strip()
        for contract in record_prop_contracts(record)
        if str(contract.get("prop_id") or "").strip()
    )
    first_frame = record.get("first_frame_contract") if isinstance(record.get("first_frame_contract"), dict) else {}
    key_props = first_frame.get("key_props") if isinstance(first_frame, dict) else []
    if isinstance(key_props, list):
        prop_ids.extend(str(item).strip() for item in key_props if str(item).strip())
    return [
        prop_id
        for prop_id in dict.fromkeys(prop_ids)
        if prop_id and any(token in prop_id.upper() for token in LARGE_SCENE_PROP_ID_TOKENS)
    ]


def large_scene_motion_props_in_record(record: dict[str, Any]) -> list[str]:
    motion_contract = record.get("scene_motion_contract")
    if not isinstance(motion_contract, dict):
        return []
    values: list[str] = []
    for key in ("static_props", "manipulated_props"):
        raw = motion_contract.get(key)
        if isinstance(raw, list):
            values.extend(str(item).strip() for item in raw if str(item).strip())
    return [
        value
        for value in dict.fromkeys(values)
        if any(token in value for token in LARGE_SCENE_ELEMENT_TEXT_TOKENS)
    ]


def assert_no_large_scene_props_for_screen(record: dict[str, Any], shot_id: str) -> None:
    if not is_screen_record(record):
        return
    bad_ids = large_scene_prop_ids_in_record(record)
    bad_motion_props = large_scene_motion_props_in_record(record)
    if not bad_ids and not bad_motion_props:
        return
    raise RuntimeError(
        f"{shot_id}: screen script record has large scene elements in prop/motion contract: {', '.join(bad_ids + bad_motion_props)}. "
        "门、车、公交车门等必须放入 first_frame_contract.scene_overlay，而不是 prop_library/prop_contract/key_props/static_props/manipulated_props。"
    )


def build_scene_overlay_lines(record: dict[str, Any]) -> list[str]:
    first_frame = record.get("first_frame_contract")
    if not isinstance(first_frame, dict):
        return []
    overlay = first_frame.get("scene_overlay")
    if not isinstance(overlay, dict):
        overlay = {}
    lines: list[str] = []
    required = ensure_list_str(overlay.get("required_elements"))
    if required:
        lines.append("场景修饰必须出现：" + "、".join(required))
    rules = ensure_list_str(overlay.get("physical_rules"))
    for rule in rules:
        lines.append(f"大物件物理规则：{rule}")
    cardinality = first_frame.get("foreground_character_cardinality")
    foreground = ensure_list_str(overlay.get("foreground_characters"))
    count = overlay.get("foreground_character_count")
    focus = ""
    if isinstance(cardinality, dict):
        if not foreground:
            foreground = ensure_list_str(cardinality.get("names"))
        if not count:
            count = cardinality.get("count")
        focus = str(cardinality.get("focus") or "").strip()
    if foreground and count:
        lines.append(f"首帧前景主体人物数量 exactly {count}：{'、'.join(foreground)}")
        if focus and focus in foreground:
            lines.append(f"画面焦点人物：{focus}；焦点人物可以说话或承接情绪，但不得删除其他前景人物")
    background_policy = str(overlay.get("background_character_policy") or "").strip()
    if background_policy:
        lines.append(background_policy)
    return unique_keep_order(lines)


def iter_character_state_overlays(record: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    overlay = record.get("character_state_overlay")
    if not isinstance(overlay, dict):
        return []
    entries: list[tuple[str, dict[str, Any]]] = []
    for character, raw_items in overlay.items():
        if isinstance(raw_items, dict):
            raw_items = [raw_items]
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if isinstance(item, dict):
                entries.append((str(character or "").strip(), item))
    return entries


BACK_VIEW_CONSTRAINT_TOKENS = (
    "背影",
    "背对",
    "背向",
    "后脑",
    "后背",
    "只见背",
    "背部轮廓",
    "back view",
    "back-view",
    "from behind",
    "back facing",
    "rear view",
)


def render_safe_visible_constraints(value: Any) -> tuple[list[str], bool]:
    constraints = ensure_list_str(value)
    if not any(any(token in rule.lower() for token in BACK_VIEW_CONSTRAINT_TOKENS) for rule in constraints):
        return constraints, False
    repaired = [
        rule
        for rule in constraints
        if not any(token in rule.lower() for token in BACK_VIEW_CONSTRAINT_TOKENS)
    ]
    face_visible_rule = "行走/离开姿态可见，但首帧仍需正侧脸或三分之二侧脸可辨认"
    if face_visible_rule not in repaired:
        repaired.append(face_visible_rule)
    return repaired, True


def build_character_state_overlay_lines(record: dict[str, Any]) -> list[str]:
    entries = iter_character_state_overlays(record)
    if not entries:
        return []
    lines = [
        "shot-local，只适用于本镜头，不延续到其他镜头；如果与人物锁定的年龄/身形/身体状态冲突，以本段为准，身份和脸部连续性仍参考角色锁。"
    ]
    for character, item in entries:
        if not character:
            continue
        parts: list[str] = []
        state_id = str(item.get("state_id") or "").strip()
        source_basis = str(item.get("source_basis") or "").strip()
        evidence_quote = str(item.get("evidence_quote") or "").strip()
        body_state = str(item.get("body_state") or "").strip()
        visible_constraint_items, repaired_back_view = render_safe_visible_constraints(item.get("visible_constraints"))
        negative_constraint_items = ensure_list_str(item.get("negative_constraints"))
        if repaired_back_view:
            for rule in ("不得只有背影或后脑作为主体", "不得让说话人的脸和嘴不可辨认"):
                if rule not in negative_constraint_items:
                    negative_constraint_items.append(rule)
        visible_constraints = "、".join(visible_constraint_items)
        negative_constraints = "、".join(negative_constraint_items)
        key_props = "、".join(ensure_list_str(item.get("key_props")))
        keyframe_moment = str(item.get("keyframe_moment") or record.get("keyframe_moment") or "").strip()
        if state_id:
            parts.append(f"state_id={state_id}")
        if source_basis:
            parts.append(f"source={source_basis}")
        if evidence_quote:
            parts.append(f"evidence={evidence_quote}")
        if body_state:
            parts.append(f"body_state={body_state}")
        if visible_constraints:
            parts.append(f"可视约束={visible_constraints}")
        if negative_constraints:
            parts.append(f"禁止={negative_constraints}")
        if key_props:
            parts.append(f"关键道具={key_props}")
        if keyframe_moment:
            parts.append(f"首帧瞬间={keyframe_moment}")
        if parts:
            lines.append(f"{character}: " + "；".join(parts))
    return unique_keep_order(lines)


def build_movement_boundary_lines(record: dict[str, Any]) -> list[str]:
    shot_execution = record.get("shot_execution")
    if not isinstance(shot_execution, dict):
        return []
    boundary = shot_execution.get("movement_boundary")
    if not isinstance(boundary, dict):
        return []
    lines: list[str] = []
    for key, label in (
        ("source_action", "源文动作"),
        ("allowed_motion", "允许动作"),
        ("forbidden_motion", "禁止动作"),
        ("end_state", "本镜结尾状态"),
        ("next_shot_bridge", "下一镜衔接"),
    ):
        value = str(boundary.get(key) or "").strip()
        if value:
            lines.append(f"{label}：{value}")
    return unique_keep_order(lines)


def character_has_age_body_overlay(record: dict[str, Any], character_name: str) -> bool:
    target = str(character_name or "").strip()
    if not target:
        return False
    age_body_tokens = ("婴儿", "新生儿", "幼儿", "infant", "baby", "toddler", "年龄", "age", "岁")
    for character, item in iter_character_state_overlays(record):
        if character != target:
            continue
        combined = " ".join(
            [
                str(item.get("state_id") or ""),
                str(item.get("body_state") or ""),
                " ".join(ensure_list_str(item.get("visible_constraints"))),
            ]
        ).lower()
        if any(token.lower() in combined for token in age_body_tokens):
            return True
    return False


def remove_age_body_lock_conflicts(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"\d+岁半?[^，；。]*[，；]?", "", cleaned)
    for token in ("蓝色牛仔背带裤，", "蓝色牛仔背带裤；", "蓝色牛仔背带裤", "小虎牙，", "小虎牙；", "小虎牙"):
        cleaned = cleaned.replace(token, "")
    cleaned = re.sub(r"[，；]{2,}", "，", cleaned).strip("，； ")
    if "本镜头年龄/身形以角色身体状态附加信息为准" not in cleaned:
        cleaned += "；本镜头年龄/身形以角色身体状态附加信息为准"
    return cleaned


def scene_modifier_display_map(record: dict[str, Any]) -> dict[str, str]:
    first_frame = record.get("first_frame_contract") if isinstance(record.get("first_frame_contract"), dict) else {}
    mapping: dict[str, str] = {}
    if not isinstance(first_frame, dict):
        return mapping
    for key in ("scene_modifiers", "costume_modifiers"):
        raw = first_frame.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            display = str(item.get("display_name") or "").strip()
            if item_id and display:
                mapping[item_id] = display
    return mapping


def replace_scene_modifier_ids(text: str, record: dict[str, Any]) -> str:
    out = str(text or "")
    for item_id, display in scene_modifier_display_map(record).items():
        out = out.replace(item_id, display)
    return out


def prop_contract_is_photo(prop_id: str, profile: dict[str, Any], contract: dict[str, Any]) -> bool:
    combined = " ".join(
        str(value or "")
        for value in [
            prop_id,
            profile.get("display_name"),
            profile.get("structure"),
            profile.get("front_description"),
            profile.get("back_description"),
            contract.get("front_description"),
            contract.get("back_description"),
        ]
    )
    upper_id = str(prop_id or "").upper()
    display_text = " ".join(str(profile.get(key) or "") for key in ("display_name", "name"))
    return (
        any(token in upper_id for token in PHOTO_PROP_ID_TOKENS)
        or any(token in display_text for token in PHOTO_PROP_DISPLAY_TOKENS)
        or any(token in combined for token in ("照片", "相片", "photo", "photograph"))
    )


PHOTO_PROP_CANONICAL_ALIASES = {
    "SAKURA_SCHOOL_PHOTO": "SAKURA_PHOTO_01",
}

PHOTO_PROP_ID_TOKENS = ("PHOTO", "DRAWING")
PHOTO_PROP_DISPLAY_TOKENS = ("照片", "相片", "全家福", "儿童画")
PHONE_PROP_ID_TOKENS = ("PHONE", "SMARTPHONE", "MOBILE")
PHONE_PROP_DISPLAY_TOKENS = ("手机", "电话")
SMALL_HANDHELD_PROP_ID_TOKENS = (
    "PREGNANCY_TEST",
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


def infer_photo_side_description(profile: dict[str, Any], contract: dict[str, Any], side: str) -> str:
    explicit_key = f"{side}_description"
    explicit = str(profile.get(explicit_key) or contract.get(explicit_key) or "").strip()
    if explicit:
        return explicit

    structure = str(profile.get("structure") or contract.get("structure") or "").strip()
    if not structure:
        return ""
    marker = "正面" if side == "front" else "背面"
    match = re.search(rf"{marker}[是为:]?([^；。;]+)", structure)
    if match:
        return match.group(1).strip()
    return ""


def build_photo_prop_constraint_lines(record: dict[str, Any]) -> list[str]:
    library = record_prop_library(record)
    contracts = record_prop_contracts(record)
    contract_prop_ids = {
        str(contract.get("prop_id") or "").strip()
        for contract in contracts
        if str(contract.get("prop_id") or "").strip()
    }
    lines: list[str] = []
    seen: set[str] = set()
    for contract in contracts:
        prop_id = str(contract.get("prop_id") or "").strip()
        if not prop_id:
            continue
        canonical_prop_id = PHOTO_PROP_CANONICAL_ALIASES.get(prop_id, prop_id)
        if canonical_prop_id != prop_id and canonical_prop_id in contract_prop_ids:
            continue
        profile = library.get(prop_id, {})
        if canonical_prop_id != prop_id:
            profile = library.get(canonical_prop_id, profile)
        if not prop_contract_is_photo(prop_id, profile, contract):
            continue
        if canonical_prop_id in seen:
            continue
        seen.add(canonical_prop_id)
        display = str(profile.get("display_name") or contract.get("display_name") or canonical_prop_id).strip()
        size = str(profile.get("size") or contract.get("size") or "约10cm x 15cm x 0.3mm").strip()
        material = str(profile.get("material") or contract.get("material") or "半光泽相纸").strip()
        front = infer_photo_side_description(profile, contract, "front") or "照片正面有剧情指定影像"
        back = infer_photo_side_description(profile, contract, "back") or "照片背面按记录指定，不自行添加图像、文字或花纹"
        visible_side = str(contract.get("current_visible_side") or contract.get("visible_side") or "").strip()
        orientation = str(contract.get("orientation_to_camera") or "").strip()
        viewer_policy = str(contract.get("photo_viewer_policy") or "").strip()
        position = str(contract.get("position") or "").strip()
        quantity = str(contract.get("quantity_policy") or profile.get("count") or "只允许这一张照片；不要生成散落照片、照片堆或额外照片").strip()
        flip = str(contract.get("flip_policy") or "除非镜头明确写翻面，否则不翻面，保持同一可见面").strip()
        motion = str(contract.get("motion_policy") or profile.get("canonical_motion_policy") or "").strip()

        lines.append(f"{canonical_prop_id}（{display}）：{size}，{material}。")
        lines.append(f"正面：{front}。")
        lines.append(f"背面：{back}。")
        if visible_side or orientation or viewer_policy:
            lines.append(f"当前可见面：{visible_side or '必须按记录指定'}；朝向：{orientation or '默认看照片时正面朝手拿照片的角色，观众看到背面；只有明确展示给另一个角色时正面才朝接收者'}。")
        if viewer_policy:
            lines.append(viewer_policy)
        if position:
            lines.append(f"首帧位置：{position}。")
        lines.append(quantity)
        lines.append(flip)
        if motion:
            lines.append(motion)
    return lines


def prop_text_blob(prop_id: str, profile: dict[str, Any], contract: dict[str, Any]) -> tuple[str, str]:
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


def prop_contract_is_phone(prop_id: str, profile: dict[str, Any], contract: dict[str, Any]) -> bool:
    upper_id = str(prop_id or "").upper()
    display_text = " ".join(str(profile.get(key) or "") for key in ("display_name", "name"))
    return any(token in upper_id for token in PHONE_PROP_ID_TOKENS) or any(token in display_text for token in PHONE_PROP_DISPLAY_TOKENS)


def prop_contract_is_small_handheld(prop_id: str, profile: dict[str, Any], contract: dict[str, Any]) -> bool:
    if prop_contract_is_phone(prop_id, profile, contract) or prop_contract_is_photo(prop_id, profile, contract):
        return False
    if is_scene_modifier_prop_id(prop_id) or any(token in str(prop_id or "").upper() for token in LARGE_SCENE_PROP_ID_TOKENS):
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


def build_small_handheld_prop_constraint_lines(record: dict[str, Any]) -> list[str]:
    library = record_prop_library(record)
    lines: list[str] = []
    seen: set[str] = set()
    for contract in record_prop_contracts(record):
        prop_id = str(contract.get("prop_id") or "").strip()
        if not prop_id or prop_id in seen:
            continue
        profile = library.get(prop_id, {})
        if not prop_contract_is_small_handheld(prop_id, profile, contract):
            continue
        seen.add(prop_id)
        display = str(profile.get("display_name") or contract.get("display_name") or prop_id).strip()
        size = str(profile.get("size") or contract.get("size") or "").strip()
        count = str(profile.get("count") or contract.get("quantity_policy") or "").strip()
        position = str(contract.get("position") or "").strip()
        motion = str(contract.get("motion_policy") or profile.get("canonical_motion_policy") or "").strip()
        scale_policy = str(profile.get("scale_policy") or contract.get("scale_policy") or "").strip()
        visibility_policy = str(contract.get("visibility_policy") or profile.get("visibility_policy") or "").strip()
        fields = [
            f"{prop_id}（{display}）",
            f"尺寸:{size}" if size else "",
            f"数量:{count}" if count else "",
            f"首帧位置:{position}" if position else "",
            f"运动政策:{motion}" if motion else "",
            f"比例政策:{scale_policy}" if scale_policy else "",
            f"可见性政策:{visibility_policy}" if visibility_policy else "",
        ]
        lines.append("；".join(item for item in fields if item))
    return lines


def build_prohibition_rules(
    dialogue_lines: list[dict[str, Any]],
    narration_lines: list[dict[str, Any]],
    character_anchor: dict[str, Any],
    avoid_terms: list[str],
) -> list[str]:
    rules: list[str] = []
    visible_names = [
        str(node.get("name") or node.get("character_id") or "").strip()
        for node in collect_character_nodes(character_anchor)
    ]
    visible_names = unique_keep_order([name for name in visible_names if name])
    speakers = [str(line.get("speaker") or "").strip() for line in dialogue_lines if str(line.get("speaker") or "").strip()]
    unique_speakers = unique_keep_order(speakers)
    if len(unique_speakers) >= 2:
        for speaker in unique_speakers:
            others = [name for name in unique_speakers if name != speaker]
            if others:
                rules.append(f"不要让{'、'.join(others)}说{speaker}的台词。")
    elif len(unique_speakers) == 1:
        non_speakers = [
            str(node.get("name") or node.get("character_id") or "").strip()
            for node in collect_character_nodes(character_anchor)
            if str(node.get("name") or node.get("character_id") or "").strip() != unique_speakers[0]
        ]
        if non_speakers:
            rules.append(f"不要让{'、'.join(non_speakers)}说{unique_speakers[0]}的台词。")
            rules.append(f"{'、'.join(non_speakers)}保持闭嘴，不做说话口型。")
    if dialogue_lines:
        rules.extend(
            [
                "不要新增台词。",
                "不要省略台词。",
                "非说话人保持闭嘴。",
            ]
        )
        offscreen_lines = [
            line
            for line in dialogue_lines
            if normalize_dialogue_source(line.get("source"), line.get("text", ""), line.get("purpose", "")) == "offscreen"
        ]
        if offscreen_lines:
            rules.extend(
                [
                    "旁白只能是画外音/独立旁白音轨，不能变成角色对白。",
                    "旁白段落开始前画面必须先淡出或明显转暗，避免可见人物继续做口型。",
                    "人物不张口说旁白；旁白必须作为画外音处理，不要在画面里生成旁白字幕。",
                ]
            )
            if visible_names:
                rules.append(
                    f"旁白播放期间禁止把旁白分配给{'、'.join(visible_names)}；"
                    f"{'、'.join(visible_names)}嘴唇闭合、下颌静止、不做旁白口型同步。"
                )
    elif narration_lines:
        rules.extend(
            [
                "不要新增旁白。",
                "不要省略旁白。",
                "旁白只能是画外音/独立旁白音轨，不能变成角色对白。",
                "人物不张口说旁白；旁白必须作为画外音处理，不要在画面里生成旁白字幕。",
            ]
        )
        if visible_names:
            rules.append(
                f"禁止把旁白分配给{'、'.join(visible_names)}；"
                f"{'、'.join(visible_names)}全程闭嘴、嘴唇闭合、不做口型同步。"
            )
    if has_explicit_modern_ban(avoid_terms):
        rules.append("不要出现现代服装、现代建筑、现代道具。")
    return unique_keep_order(rules)


def build_language_lock_lines(record: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    record_policy = record.get("language_policy", {})
    dialogue_language = record.get("dialogue_language", {})
    profile_policy = profile.get("language_policy", {})
    policy: dict[str, Any] = {}
    for source in (DEFAULT_LANGUAGE_POLICY, profile_policy, record_policy, dialogue_language):
        if isinstance(source, dict):
            policy.update({k: v for k, v in source.items() if v not in (None, "", [])})

    spoken_language = str(policy.get("spoken_language") or DEFAULT_LANGUAGE_POLICY["spoken_language"]).strip()
    model_audio_language = str(policy.get("model_audio_language") or spoken_language).strip()
    voice_lock = str(policy.get("voice_language_lock") or DEFAULT_LANGUAGE_POLICY["voice_language_lock"]).strip()
    screen_lock = str(policy.get("screen_text_language_lock") or DEFAULT_LANGUAGE_POLICY["screen_text_language_lock"]).strip()
    signage_rule = str(policy.get("environment_signage_language") or DEFAULT_LANGUAGE_POLICY["environment_signage_language"]).strip()
    forbidden = ensure_list_str(policy.get("forbidden_spoken_languages"))

    lines = [
        f"Spoken audio language: {spoken_language} / Mandarin Chinese only.",
        f"Model-generated audio language: {model_audio_language}; all dialogue, narration, and voiceover must be Mandarin Chinese.",
        voice_lock,
        f"On-screen text policy: {screen_lock}",
        "No burned-in subtitles, no captions, no dialogue text, no title cards, no explanatory text, no random bottom text.",
        f"Environment signage rule: {signage_rule}; background signage may appear only as silent environment text, never as subtitles or dialogue captions.",
        "中文约束：所有对白、旁白、模型音频只使用普通话中文；画面内不要生成字幕或对白文字；不要生成日语、英语或中日混杂语音。",
    ]
    if forbidden:
        lines.append(f"Forbidden spoken languages: {', '.join(forbidden)}.")
    return unique_keep_order(lines)


def normalize_compare_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def choose_record_scalar(
    field: str,
    record_value: Any,
    keyframe_metadata: dict[str, Any],
    conflicts: list[dict[str, Any]],
    supplements: list[dict[str, Any]],
) -> str:
    record_text = str(record_value or "").strip()
    keyframe_text = str(keyframe_metadata.get(field) or "").strip()
    if record_text:
        if keyframe_text and normalize_compare_text(keyframe_text) != normalize_compare_text(record_text):
            conflicts.append(
                {
                    "field": field,
                    "record_value": record_text,
                    "keyframe_value": keyframe_text,
                    "selected": "record",
                }
            )
        return record_text
    if keyframe_text:
        supplements.append({"field": field, "source": "keyframe_prompt"})
    return keyframe_text


def choose_record_list(
    field: str,
    record_values: Any,
    keyframe_metadata: dict[str, Any],
    supplements: list[dict[str, Any]],
) -> list[str]:
    record_list = ensure_list_str(record_values)
    keyframe_list = ensure_list_str(keyframe_metadata.get(field))
    if keyframe_list and not record_list:
        supplements.append({"field": field, "source": "keyframe_prompt"})
    elif keyframe_list:
        extras = [item for item in keyframe_list if item not in record_list]
        if extras:
            supplements.append({"field": field, "source": "keyframe_prompt", "added": extras})
    return unique_keep_order(record_list + keyframe_list)


def build_scene_motion_contract_lines(record: dict[str, Any], movement: str) -> list[str]:
    contract = record.get("scene_motion_contract", {})
    if not isinstance(contract, dict):
        return []
    scene_mode = str(contract.get("scene_mode") or "").strip()
    policy = str(contract.get("description_policy") or "").strip()
    camera = str(contract.get("camera_motion_allowed") or "").strip()
    active_subjects = ensure_list_str(contract.get("active_subjects"))
    static_props = ensure_list_str(contract.get("static_props"))
    manipulated_props = ensure_list_str(contract.get("manipulated_props"))
    allowed_motion = ensure_list_str(contract.get("allowed_motion"))
    forbidden_motion = ensure_list_str(contract.get("forbidden_scene_motion"))

    lines: list[str] = []
    if scene_mode:
        lines.append(f"场景模式：{scene_mode}")
    if policy:
        lines.append(policy)
    if camera:
        if movement and movement not in camera:
            lines.append(f"镜头运动许可：{camera}；原镜头计划：{movement}")
        else:
            lines.append(f"镜头运动许可：{camera}")
    if static_props:
        lines.append(f"静态道具：{'、'.join(static_props)}")
    lines.append(f"可动主体：{'、'.join(active_subjects) if active_subjects else '无'}")
    lines.append(f"可动道具：{'、'.join(manipulated_props) if manipulated_props else '无'}")
    if allowed_motion:
        lines.append(f"允许运动：{'、'.join(allowed_motion)}")
    if forbidden_motion:
        lines.append(f"禁止场景运动：{'、'.join(forbidden_motion)}")
    if scene_mode == "static_establishing":
        lines.append("本镜头是静态空间建立镜头；房间、床、地毯、桌面和全部道具全程保持静止。")
    return unique_keep_order(lines)


def compact_character_context(char: dict[str, Any], record: dict[str, Any] | None = None) -> str:
    record = record or {}
    name = str(char.get("name") or char.get("character_id") or "角色").strip()
    char_id = str(char.get("character_id") or "").strip().upper()
    if "石川" in name or "ISHIKAWA" in char_id:
        return "石川：三十多岁刑警，旧深色西装，冷静敏锐"
    if "龙崎" in name or "RYUZAKI" in char_id:
        return "龙崎：四十出头银座竞争者，深色西装，冒汗慌乱"

    visual_anchor = str(char.get("visual_anchor") or "").strip()
    if character_has_age_body_overlay(record, name):
        visual_anchor = remove_age_body_lock_conflicts(visual_anchor)
    first_sentence = re.split(r"[。；;]", visual_anchor, maxsplit=1)[0].strip()
    parts = [part.strip() for part in re.split(r"[，,、]", first_sentence) if part.strip()]
    summary = "，".join(parts[:3]).strip()
    if len(summary) > 28:
        summary = summary[:28].rstrip("，,、；;。")
    return f"{name}：{summary}" if summary else f"{name}：容貌服饰稳定"


def build_novita_compact_context_line(
    scene_name: str,
    character_anchor: dict[str, Any],
    movement: str,
    record: dict[str, Any] | None = None,
) -> str:
    scene = scene_name or "现代东京悬疑空间"
    character_parts = [compact_character_context(char, record) for char in collect_character_nodes(character_anchor)]
    characters = "；".join(character_parts[:2])
    movement_text = movement or "按镜头计划"
    line = (
        f"{scene}，低饱和写实竖屏。{characters}。"
        f"音频仅普通话，画面内不生成字幕或底部文字。{movement_text}，只许人物动作，道具不增减漂移。"
    )
    if len(line) <= 150:
        return line
    shorter = (
        f"{scene}，低饱和写实竖屏。{characters}。"
        f"普通话音频，无画面字幕或底部文字。{movement_text}，道具不增减漂移。"
    )
    if len(shorter) <= 150:
        return shorter
    return shorter[:150].rstrip("，,、；;。") + "。"


def render_prompt_bundle(
    shot_id: str,
    record: dict[str, Any],
    profile: dict[str, Any],
    profile_load_downgrades: list[dict[str, Any]],
    enable_subtitle_hint: bool,
    duration_sec: float,
    keyframe_prompt_metadata: dict[str, Any],
) -> dict[str, Any]:
    assert_no_large_scene_props_for_screen(record, shot_id)
    prompt_render = record.get("prompt_render", {})
    scene_anchor = record.get("scene_anchor", {})
    shot_execution = record.get("shot_execution", {})
    continuity_rules = record.get("continuity_rules", {})
    character_anchor, character_filter_report = filter_character_anchor_for_shot(record)
    dialogue_language = record.get("dialogue_language", {})

    prefix = str(prompt_render.get("positive_prefix") or GLOBAL_PREFIX).strip()
    core = str(prompt_render.get("shot_positive_core") or "").strip()
    subtitle_hint = str(prompt_render.get("subtitle_overlay_hint") or "").strip()

    camera_plan = shot_execution.get("camera_plan", {})
    keyframe_conflicts: list[dict[str, Any]] = []
    keyframe_supplements: list[dict[str, Any]] = []
    shot_type = choose_record_scalar(
        "shot_type",
        camera_plan.get("shot_type"),
        keyframe_prompt_metadata,
        keyframe_conflicts,
        keyframe_supplements,
    )
    movement = choose_record_scalar(
        "movement",
        camera_plan.get("movement"),
        keyframe_prompt_metadata,
        keyframe_conflicts,
        keyframe_supplements,
    )
    framing_focus = choose_record_scalar(
        "framing_focus",
        camera_plan.get("framing_focus"),
        keyframe_prompt_metadata,
        keyframe_conflicts,
        keyframe_supplements,
    )
    action_intent = choose_record_scalar(
        "action_intent",
        shot_execution.get("action_intent"),
        keyframe_prompt_metadata,
        keyframe_conflicts,
        keyframe_supplements,
    )
    emotion_intent = choose_record_scalar(
        "emotion_intent",
        shot_execution.get("emotion_intent"),
        keyframe_prompt_metadata,
        keyframe_conflicts,
        keyframe_supplements,
    )

    scene_name = choose_record_scalar(
        "scene_name",
        scene_anchor.get("scene_name"),
        keyframe_prompt_metadata,
        keyframe_conflicts,
        keyframe_supplements,
    )
    must_elements = choose_record_list(
        "must_have_elements",
        scene_anchor.get("must_have_elements"),
        keyframe_prompt_metadata,
        keyframe_supplements,
    )
    props = choose_record_list(
        "prop_must_visible",
        scene_anchor.get("prop_must_visible"),
        keyframe_prompt_metadata,
        keyframe_supplements,
    )
    lighting_anchor = choose_record_scalar(
        "lighting_anchor",
        scene_anchor.get("lighting_anchor"),
        keyframe_prompt_metadata,
        keyframe_conflicts,
        keyframe_supplements,
    )
    continuity_items = (
        ensure_list_str(continuity_rules.get("character_state_transition"))
        + ensure_list_str(continuity_rules.get("scene_transition"))
        + ensure_list_str(continuity_rules.get("prop_continuity"))
    )
    scene_motion_contract = record.get("scene_motion_contract", {})
    scene_motion_forbidden = (
        ensure_list_str(scene_motion_contract.get("forbidden_scene_motion"))
        if isinstance(scene_motion_contract, dict)
        else []
    )
    dialogue_lines = normalize_spoken_lines(dialogue_language.get("dialogue_lines", []))
    narration_lines = normalize_spoken_lines(dialogue_language.get("narration_lines", []))

    character_nodes = collect_character_nodes(character_anchor)
    forbidden_drift: list[str] = []
    for char in character_nodes:
        forbidden_drift.extend(ensure_list_str(char.get("forbidden_drift")))
    forbidden_drift = unique_keep_order(forbidden_drift)
    avoid_terms = normalize_avoid_terms(
        ensure_list_str(prompt_render.get("negative_prompt")) + forbidden_drift + scene_motion_forbidden
    )
    character_role_lock_lines = build_character_role_lock_lines(character_anchor, record)
    dialogue_timeline_lines = build_dialogue_timeline_block(
        dialogue_lines=dialogue_lines,
        character_anchor=character_anchor,
        duration_sec=duration_sec,
    )
    narration_timeline_lines = (
        []
        if dialogue_timeline_lines
        else build_narration_timeline_block(
            narration_lines=narration_lines,
            duration_sec=duration_sec,
            character_anchor=character_anchor,
        )
    )
    hand_constraint_lines = build_hand_constraint_lines(
        shot_type=shot_type,
        framing_focus=framing_focus,
        action_intent=action_intent,
        core=core,
        props=props,
    )
    phone_prop_constraint_lines = build_phone_prop_constraint_lines(
        record=record,
        character_anchor=character_anchor,
        core=core,
        framing_focus=framing_focus,
        action_intent=action_intent,
        props=props,
        continuity_items=continuity_items,
    )
    photo_prop_constraint_lines = build_photo_prop_constraint_lines(record)
    small_handheld_prop_constraint_lines = build_small_handheld_prop_constraint_lines(record)
    visible_character_first_frame_lines = build_visible_character_first_frame_lines(record, dialogue_lines)
    visible_character_first_frame_review = visible_character_first_frame_policy_review(record)
    speaker_first_frame_lines = build_speaker_first_frame_self_check_lines(dialogue_lines)
    speaker_first_frame_review = speaker_first_frame_policy_review(record, dialogue_lines)
    speaker_face_visibility_lines = build_speaker_face_visibility_lines(record, dialogue_lines)
    dialogue_gaze_lines = build_dialogue_gaze_lines(record)
    prohibition_rules = build_prohibition_rules(
        dialogue_lines=dialogue_lines,
        narration_lines=narration_lines if narration_timeline_lines else [],
        character_anchor=character_anchor,
        avoid_terms=avoid_terms,
    )
    language_lock_lines = build_language_lock_lines(record=record, profile=profile)
    scene_motion_lines = build_scene_motion_contract_lines(record, movement)
    scene_overlay_lines = build_scene_overlay_lines(record)
    if record_uses_montage_keyframe_moment(record):
        scene_overlay_lines = []
    character_state_overlay_lines = build_character_state_overlay_lines(record)
    movement_boundary_lines = build_movement_boundary_lines(record)
    scene_mode = (
        str(scene_motion_contract.get("scene_mode") or "").strip()
        if isinstance(scene_motion_contract, dict)
        else ""
    )
    camera_motion_allowed = (
        str(scene_motion_contract.get("camera_motion_allowed") or "").strip()
        if isinstance(scene_motion_contract, dict)
        else ""
    )
    movement_for_prompt = (
        camera_motion_allowed
        if scene_mode == "static_establishing" and camera_motion_allowed
        else movement
    )
    if record_uses_montage_keyframe_moment(record) and str(record.get("keyframe_moment") or "").strip():
        action_intent = str(record.get("keyframe_moment") or "").strip()

    compact_context_line = ""
    if str(profile.get("provider") or "").strip().lower() == "novita":
        compact_context_line = build_novita_compact_context_line(
            scene_name=scene_name,
            character_anchor=character_anchor,
            movement=movement_for_prompt,
            record=record,
        )

    if compact_context_line:
        prompt_lines: list[str] = [compact_context_line]
    else:
        prompt_lines = [
            build_scene_header(
                prefix=prefix,
                scene_name=scene_name,
                must_elements=must_elements,
                shot_type=shot_type,
                lighting_anchor=lighting_anchor,
            )
        ]

    if compact_context_line and narration_timeline_lines:
        visible_names = [
            str(node.get("name") or node.get("character_id") or "").strip()
            for node in character_nodes
            if str(node.get("name") or node.get("character_id") or "").strip()
        ]
        visible_text = "、".join(unique_keep_order(visible_names))
        if visible_text:
            prompt_lines.append(
                f"音频角色：只有画外旁白音轨，不是{visible_text}对白；{visible_text}全程闭嘴无口型。"
            )
        else:
            prompt_lines.append("音频角色：只有画外旁白音轨，画面内无人开口或做口型。")

    if character_role_lock_lines and not compact_context_line:
        prompt_lines.append("")
        prompt_lines.append("角色锁定：")
        prompt_lines.extend(character_role_lock_lines)
    if language_lock_lines and not compact_context_line:
        prompt_lines.append("")
        prompt_lines.append("语言锁定：")
        prompt_lines.extend([f"- {line}" for line in language_lock_lines])
    if scene_motion_lines and not compact_context_line:
        prompt_lines.append("")
        prompt_lines.append("场景运动契约：")
        prompt_lines.extend([f"- {line}" for line in scene_motion_lines])
    if scene_overlay_lines:
        prompt_lines.append("")
        prompt_lines.append("场景修饰与大物件物理规则：")
        prompt_lines.extend([f"- {line}" for line in scene_overlay_lines])
    if core and not record_uses_montage_keyframe_moment(record):
        prompt_lines.append("")
        prompt_lines.append(f"画面主体：{core}")
    if character_state_overlay_lines:
        prompt_lines.append("")
        prompt_lines.append("角色身体状态附加信息：")
        prompt_lines.extend([f"- {line}" for line in character_state_overlay_lines])
    keyframe_moment = str(record.get("keyframe_moment") or "").strip()
    if keyframe_moment:
        prompt_lines.append("")
        prompt_lines.append("蒙太奇/跳时首帧选择：")
        prompt_lines.append(f"- {keyframe_moment}；只呈现这个单一瞬间，其他原文画面只作上下文，不进入本视频首帧。")
    if movement_for_prompt or framing_focus or action_intent or emotion_intent or props or continuity_items or movement_boundary_lines:
        prompt_lines.append("")
        prompt_lines.append("镜头与表演执行：")
        if movement_for_prompt:
            prompt_lines.append(f"- 运动：{movement_for_prompt}")
        if framing_focus:
            prompt_lines.append(f"- 构图焦点：{framing_focus}")
        if action_intent:
            prompt_lines.append(f"- 动作意图：{action_intent}")
        for line in movement_boundary_lines:
            prompt_lines.append(f"- 动作连续性边界：{line}")
        if emotion_intent:
            prompt_lines.append(f"- 情绪意图：{emotion_intent}")
        if props:
            prompt_lines.append(f"- 关键道具：{'、'.join(props)}")
        if continuity_items:
            prompt_lines.append(f"- 连续性：{'；'.join(unique_keep_order(continuity_items))}")
    if hand_constraint_lines:
        prompt_lines.append("")
        prompt_lines.append("手部约束：")
        prompt_lines.extend([f"- {line}" for line in hand_constraint_lines])
    if visible_character_first_frame_lines:
        prompt_lines.append("")
        prompt_lines.append("首帧人物脸部自查：")
        prompt_lines.extend([f"- {line}" for line in visible_character_first_frame_lines])
    if speaker_face_visibility_lines:
        prompt_lines.append("")
        prompt_lines.append("说话人脸部硬约束：")
        prompt_lines.extend([f"- {line}" for line in speaker_face_visibility_lines])
    if dialogue_gaze_lines:
        prompt_lines.append("")
        prompt_lines.append("对白视线关系：")
        prompt_lines.extend([f"- {line}" for line in dialogue_gaze_lines])
    if speaker_first_frame_lines:
        prompt_lines.append("")
        prompt_lines.append("说话人首帧自查：")
        prompt_lines.extend([f"- {line}" for line in speaker_first_frame_lines])
    if phone_prop_constraint_lines:
        prompt_lines.append("")
        prompt_lines.append("手机道具约束：")
        prompt_lines.extend([f"- {line}" for line in phone_prop_constraint_lines])
    if photo_prop_constraint_lines:
        prompt_lines.append("")
        prompt_lines.append("照片道具约束：")
        prompt_lines.extend([f"- {line}" for line in photo_prop_constraint_lines])
    if small_handheld_prop_constraint_lines:
        prompt_lines.append("")
        prompt_lines.append("小型手持道具约束：")
        prompt_lines.extend([f"- {line}" for line in small_handheld_prop_constraint_lines])

    if dialogue_timeline_lines:
        prompt_lines.append("")
        prompt_lines.append("台词与嘴型必须严格对应：")
        prompt_lines.extend([f"- {line}" for line in dialogue_timeline_lines])
    elif narration_timeline_lines:
        prompt_lines.append("")
        prompt_lines.append("旁白与画面必须严格对应：")
        prompt_lines.extend([f"- {line}" for line in narration_timeline_lines])
    elif enable_subtitle_hint and subtitle_hint:
        prompt_lines.append("")
        prompt_lines.append(f"后期字幕参考（不要画进视频帧）：{subtitle_hint}")

    if prohibition_rules:
        prompt_lines.append("")
        prompt_lines.append("禁止：")
        prompt_lines.extend([f"- {line}" for line in prohibition_rules])

    supports_negative = bool(profile.get("supports_negative_prompt"))
    downgrades: list[dict[str, Any]] = list(profile_load_downgrades)
    negative_prompt_text = ""
    if supports_negative:
        negative_prompt_text = ", ".join(avoid_terms)
    else:
        prompt_lines.append("")
        prompt_lines.append(build_positive_constraints_from_avoid(avoid_terms))
        if avoid_terms:
            downgrades.append(
                {
                    "type": "no_negative_field",
                    "detail": "avoid terms merged into positive constraints",
                }
            )

    prompt_text = "\n".join([p for p in prompt_lines if p is not None]).strip()
    prompt_text = replace_scene_modifier_ids(prompt_text, record)
    record_id = f"{record.get('record_header', {}).get('episode_id', 'EPXX')}_{shot_id}"

    mapping_summary = {
        "must": "full",
        "prefer": "full",
        "avoid": "full" if supports_negative else "downgraded_to_positive_constraints",
        "dialogue": "template_v2" if dialogue_timeline_lines else "none",
        "narration": (
            "suppressed_by_dialogue"
            if dialogue_lines and narration_lines
            else ("timeline_v1" if narration_timeline_lines else "none")
        ),
        "phone_prop": "holder_and_screen_orientation" if phone_prop_constraint_lines else "none",
        "small_handheld_prop": "scale_policy" if small_handheld_prop_constraint_lines else "none",
        "speaker_first_frame": "onscreen_speaker_not_back_to_audience"
        if speaker_first_frame_lines
        else "none",
        "visible_character_first_frame": "visible_characters_show_face"
        if visible_character_first_frame_lines
        else "none",
        "dialogue_gaze": "speaker_listener_mutual_eyeline" if dialogue_gaze_lines else "none",
        "continuity": "full",
        "scene_source": "record_priority_with_keyframe_fallback" if keyframe_prompt_metadata else "record_only",
        "context_compaction": "novita_150_char_context" if compact_context_line else "none",
        "scene_overlay": "full" if scene_overlay_lines else "none",
        "character_state_overlay": "shot_local" if character_state_overlay_lines else "none",
    }

    render_report = {
        "record_id": record_id,
        "model_profile_id": str(profile.get("profile_id", "")).strip() or DEFAULT_PROFILE_ID,
        "mapping_summary": mapping_summary,
        "downgrades": downgrades,
        "requires_manual_review": (not supports_negative) or bool(downgrades),
        "generated_at": datetime.now().isoformat(),
        "keyframe_prompt_path": str(keyframe_prompt_metadata.get("prompt_path") or ""),
        "keyframe_merge_policy": "record_fields_win; keyframe_prompt_only_fills_missing_or_adds_list_items",
        "keyframe_conflicts": keyframe_conflicts,
        "keyframe_supplements": keyframe_supplements,
        "character_filter": character_filter_report,
        "scene_motion_contract": scene_motion_contract if isinstance(scene_motion_contract, dict) else {},
        "visible_character_first_frame_policy": visible_character_first_frame_review,
        "speaker_first_frame_policy": speaker_first_frame_review,
        "prompt_compaction": {
            "provider": str(profile.get("provider") or "").strip(),
            "compact_context_line": compact_context_line,
            "compact_context_chars": len(compact_context_line),
        },
    }

    return {
        "prompt_text": prompt_text,
        "negative_prompt_text": negative_prompt_text,
        "render_report": render_report,
    }


def parse_resolution_value(resolution: str) -> int:
    m = re.match(r"^\s*(\d+)p", str(resolution))
    if not m:
        return -1
    try:
        return int(m.group(1))
    except ValueError:
        return -1


def select_ratio(desired: str, supported: list[str], downgrades: list[dict[str, Any]]) -> str:
    desired = str(desired or "").strip() or DEFAULT_RATIO
    supported_clean = [str(r).strip() for r in supported if str(r).strip()]
    if desired in supported_clean:
        return desired
    if "9:16" in supported_clean:
        selected = "9:16"
    elif supported_clean:
        selected = supported_clean[0]
    else:
        selected = DEFAULT_RATIO
    if selected != desired:
        downgrades.append(
            {
                "type": "unsupported_ratio",
                "detail": f"requested={desired}, selected={selected}",
            }
        )
    return selected


def select_resolution(
    desired: str, supported: list[str], downgrades: list[dict[str, Any]]
) -> str:
    desired = str(desired or "").strip() or DEFAULT_RESOLUTION
    supported_clean = [str(r).strip() for r in supported if str(r).strip()]
    if desired in supported_clean:
        return desired
    if not supported_clean:
        return desired

    desired_num = parse_resolution_value(desired)
    candidates = [
        (parse_resolution_value(res), res)
        for res in supported_clean
        if parse_resolution_value(res) > 0
    ]
    selected = supported_clean[0]
    if desired_num > 0 and candidates:
        lower_or_equal = sorted([c for c in candidates if c[0] <= desired_num], key=lambda x: x[0])
        if lower_or_equal:
            selected = lower_or_equal[-1][1]
        else:
            selected = sorted(candidates, key=lambda x: x[0])[0][1]
    if selected != desired:
        downgrades.append(
            {
                "type": "unsupported_resolution",
                "detail": f"requested={desired}, selected={selected}",
            }
        )
    return selected


def resolve_duration(
    record: dict[str, Any],
    profile: dict[str, Any],
    prompt_text: str,
    override_duration: float | None,
    duration_buffer_sec: float,
    downgrades: list[dict[str, Any]],
) -> float:
    if isinstance(override_duration, (int, float)) and not isinstance(override_duration, bool):
        base_requested = float(override_duration)
    else:
        global_settings = record.get("global_settings", {})
        raw = global_settings.get("duration_sec")
        parsed_raw = parse_optional_float(raw)
        if parsed_raw is not None:
            base_requested = float(parsed_raw)
        else:
            base_requested = float(estimate_duration_seconds(prompt_text))

    profile_min = int(profile.get("duration_min_sec", MIN_DURATION_SEC))
    profile_max = int(profile.get("duration_max_sec", MAX_DURATION_SEC))
    low = float(max(MIN_DURATION_SEC, profile_min))
    high = float(min(MAX_DURATION_SEC, profile_max))
    if high < low:
        high = low
    buffer_sec = max(0.0, float(duration_buffer_sec))
    requested = base_requested + buffer_sec
    rounded_requested = float(math.ceil(requested))
    selected = clamp_float(rounded_requested, low, high)
    if selected != rounded_requested:
        downgrades.append(
            {
                "type": "duration_clamped",
                "detail": (
                    f"requested={format_duration_value(rounded_requested)}, "
                    f"selected={format_duration_value(selected)}, "
                    f"range=[{format_duration_value(low)},{format_duration_value(high)}]"
                ),
            }
        )
    return int(selected)


def infer_camera_fixed_from_record(record: dict[str, Any]) -> bool | None:
    global_settings = record.get("global_settings", {})
    camera_fixed_raw = global_settings.get("camera_fixed")
    if isinstance(camera_fixed_raw, bool):
        return camera_fixed_raw

    shot_execution = record.get("shot_execution", {})
    camera_plan = shot_execution.get("camera_plan", {}) if isinstance(shot_execution, dict) else {}
    movement = str(camera_plan.get("movement") or "").strip() if isinstance(camera_plan, dict) else ""
    fixed_tokens = (
        "固定机位",
        "固定镜头",
        "静止机位",
        "锁定机位",
        "locked camera",
        "static camera",
        "fixed camera",
    )
    if any(token.lower() in movement.lower() for token in fixed_tokens):
        return True
    return None


def estimate_duration_prompt_basis(record: dict[str, Any]) -> str:
    prompt_render = record.get("prompt_render", {})
    dialogue_language = record.get("dialogue_language", {})
    core = str(prompt_render.get("shot_positive_core") or "").strip()
    dialogue_text = " ".join(
        [
            str(item.get("text") or "").strip()
            for item in dialogue_language.get("dialogue_lines", [])
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
    ).strip()
    return " ".join([part for part in [core, dialogue_text] if part]).strip()


def build_payload_preview(
    profile: dict[str, Any],
    prompt_text: str,
    negative_prompt_text: str,
    duration: float,
    resolution: str,
    ratio: str,
    generate_audio: bool,
    image: str,
    last_image: str,
    camera_fixed: bool | None,
    seed: int | None,
) -> dict[str, Any]:
    payload_fields = profile.get("payload_fields", {})
    pos_field = str(payload_fields.get("positive_prompt_field") or "prompt")
    neg_field = payload_fields.get("negative_prompt_field")
    duration_field = str(payload_fields.get("duration_field") or "duration")
    resolution_field = str(payload_fields.get("resolution_field") or "resolution")
    ratio_field = str(payload_fields.get("ratio_field") or "ratio")
    audio_field = payload_fields.get("audio_field")
    image_field = payload_fields.get("image_field")
    last_image_field = payload_fields.get("last_image_field")
    camera_fixed_field = payload_fields.get("camera_fixed_field")
    seed_field = payload_fields.get("seed_field")

    payload_defaults = profile.get("payload_defaults", {})
    payload: dict[str, Any] = (
        dict(payload_defaults) if isinstance(payload_defaults, dict) else {}
    )
    payload.update(
        {
            pos_field: prompt_text,
            duration_field: duration,
            resolution_field: resolution,
            ratio_field: ratio,
        }
    )
    if bool(profile.get("include_model_in_payload", True)):
        payload["model"] = str(profile.get("model") or MODEL_NAME)
    if audio_field:
        supports_audio = bool(profile.get("supports_audio_generation", True))
        payload[str(audio_field)] = bool(generate_audio and supports_audio)
    if isinstance(neg_field, str) and neg_field.strip() and negative_prompt_text.strip():
        payload[neg_field.strip()] = negative_prompt_text
    if isinstance(image_field, str) and image_field.strip():
        image_value = image.strip()
        if not image_value:
            raise RuntimeError("image-to-video payload requires non-empty image input.")
        payload[image_field.strip()] = image_value
    if (
        isinstance(last_image_field, str)
        and last_image_field.strip()
        and isinstance(last_image, str)
        and last_image.strip()
    ):
        payload[last_image_field.strip()] = last_image.strip()
    if isinstance(camera_fixed_field, str) and camera_fixed_field.strip() and isinstance(camera_fixed, bool):
        payload[camera_fixed_field.strip()] = camera_fixed
    if isinstance(seed_field, str) and seed_field.strip() and isinstance(seed, int):
        payload[seed_field.strip()] = seed

    return payload


def prepare_one_shot_from_record(
    shot_id: str,
    record: dict[str, Any],
    profile: dict[str, Any],
    profile_load_downgrades: list[dict[str, Any]],
    character_lock_catalog: dict[str, dict[str, Any]],
    character_lock_catalog_issues: list[dict[str, Any]],
    duration_overrides: dict[str, float],
    duration_buffer_sec: float,
    image_input_map: dict[str, Any],
    image_input_map_path: Path | None,
    cli_image_url: str,
    cli_last_image_url: str,
    keyframe_prompts_root: Path | None,
    project_root: Path,
    experiment_dir: Path,
    generate_audio: bool,
    enable_subtitle_hint: bool,
    execution_overlays: dict[str, Any],
    write_pending: bool,
) -> tuple[Path, dict[str, Any]]:
    shot_dir = experiment_dir / shot_id
    shot_dir.mkdir(parents=True, exist_ok=True)
    record = apply_execution_overlays(record, shot_id, execution_overlays)
    hydrated_record, lock_downgrades = hydrate_record_with_character_locks(
        record=record,
        lock_catalog=character_lock_catalog,
        lock_catalog_issues=character_lock_catalog_issues,
    )
    combined_downgrades = list(profile_load_downgrades) + list(lock_downgrades)
    duration_hint_basis = estimate_duration_prompt_basis(hydrated_record)
    duration = resolve_duration(
        record=hydrated_record,
        profile=profile,
        prompt_text=duration_hint_basis,
        override_duration=duration_overrides.get(shot_id),
        duration_buffer_sec=duration_buffer_sec,
        downgrades=combined_downgrades,
    )
    keyframe_prompt_metadata, _ = load_keyframe_prompt_metadata(
        shot_id=shot_id,
        image_input_map_path=image_input_map_path,
        keyframe_prompts_root=keyframe_prompts_root,
    )

    bundle = render_prompt_bundle(
        shot_id=shot_id,
        record=hydrated_record,
        profile=profile,
        profile_load_downgrades=combined_downgrades,
        enable_subtitle_hint=enable_subtitle_hint,
        duration_sec=duration,
        keyframe_prompt_metadata=keyframe_prompt_metadata,
    )
    prompt_text = str(bundle["prompt_text"])
    negative_prompt_text = str(bundle["negative_prompt_text"])
    assert_no_prohibited_cigarette_actions(shot_id, prompt_text)
    render_report = dict(bundle["render_report"])
    downgrades = list(render_report.get("downgrades", []))

    global_settings = hydrated_record.get("global_settings", {})
    supported_ratios = ensure_list_str(profile.get("supported_ratios"))
    supported_resolutions = ensure_list_str(profile.get("supported_resolutions"))

    ratio = select_ratio(
        desired=str(profile.get("default_ratio") or DEFAULT_RATIO),
        supported=supported_ratios,
        downgrades=downgrades,
    )
    resolution = select_resolution(
        desired=str(profile.get("default_resolution") or DEFAULT_RESOLUTION),
        supported=supported_resolutions,
        downgrades=downgrades,
    )
    image, last_image = resolve_image_inputs(
        shot_id=shot_id,
        record=hydrated_record,
        image_input_map=image_input_map,
        cli_image_url=cli_image_url,
        cli_last_image_url=cli_last_image_url,
    )
    image = resolve_image_ref_for_payload(image, project_root)
    last_image = resolve_image_ref_for_payload(last_image, project_root)
    camera_fixed = infer_camera_fixed_from_record(hydrated_record)
    seed_value = parse_optional_int(global_settings.get("seed"))
    payload_preview = build_payload_preview(
        profile=profile,
        prompt_text=prompt_text,
        negative_prompt_text=negative_prompt_text,
        duration=duration,
        resolution=resolution,
        ratio=ratio,
        generate_audio=generate_audio,
        image=image,
        last_image=last_image,
        camera_fixed=camera_fixed,
        seed=seed_value,
    )

    render_report["downgrades"] = downgrades
    speaker_first_frame_review = render_report.get("speaker_first_frame_policy", {})
    visible_character_first_frame_review = render_report.get("visible_character_first_frame_policy", {})
    render_report["requires_manual_review"] = (
        bool(downgrades)
        or (not bool(profile.get("supports_negative_prompt")))
        or bool(
            speaker_first_frame_review.get("requires_review")
            if isinstance(speaker_first_frame_review, dict)
            else False
        )
        or bool(
            visible_character_first_frame_review.get("requires_review")
            if isinstance(visible_character_first_frame_review, dict)
            else False
        )
    )
    render_report["resolved_generation"] = {
        "duration_sec": duration,
        "duration_buffer_sec": max(0.0, float(duration_buffer_sec)),
        "resolution": resolution,
        "ratio": ratio,
        "generate_audio": bool(payload_preview.get("generate_audio", generate_audio)),
        "image": image,
        "last_image": last_image,
        "camera_fixed": camera_fixed,
        "seed": seed_value,
    }

    (shot_dir / "prompt.final.txt").write_text(prompt_text + "\n", encoding="utf-8")
    (shot_dir / "prompt.txt").write_text(prompt_text + "\n", encoding="utf-8")
    (shot_dir / "negative_prompt.txt").write_text(
        (negative_prompt_text + "\n") if negative_prompt_text else "",
        encoding="utf-8",
    )
    (shot_dir / "duration_used.txt").write_text(f"{format_duration_value(duration)}\n", encoding="utf-8")
    (shot_dir / "image_used.txt").write_text((image + "\n") if image else "", encoding="utf-8")
    (shot_dir / "last_image_used.txt").write_text(
        (last_image + "\n") if last_image else "",
        encoding="utf-8",
    )
    write_json(shot_dir / "payload.preview.json", payload_preview)
    write_json(shot_dir / "request_payload.preview.json", payload_preview)
    write_json(shot_dir / "render_report.json", render_report)
    write_json(shot_dir / "record.snapshot.json", hydrated_record)
    if write_pending:
        (shot_dir / "output.pending.txt").write_text(
            "Run script without --prepare-only to generate actual output.mp4.\n",
            encoding="utf-8",
        )
    else:
        pending = shot_dir / "output.pending.txt"
        if pending.exists():
            pending.unlink()

    print(f"[{shot_id}] prepared (record+profile renderer) -> {shot_dir}")
    return shot_dir, payload_preview


def prepare_one_shot_legacy(
    shot: Shot,
    experiment_dir: Path,
    generate_audio: bool,
    duration_buffer_sec: float,
    write_pending: bool,
) -> tuple[Path, dict[str, Any]]:
    if not shot.prompt.strip():
        raise RuntimeError(
            f"{shot.shot_id} 未找到 record，且脚本内无该镜头的 legacy prompt，无法继续。"
        )

    shot_dir = experiment_dir / shot.shot_id
    shot_dir.mkdir(parents=True, exist_ok=True)

    full_prompt = f"{GLOBAL_PREFIX}，{shot.prompt}"
    shot_duration = clamp_float(
        float(estimate_duration_seconds(shot.prompt)) + max(0.0, float(duration_buffer_sec)),
        float(MIN_DURATION_SEC),
        float(MAX_DURATION_SEC),
    )
    (shot_dir / "prompt.txt").write_text(full_prompt + "\n", encoding="utf-8")
    (shot_dir / "prompt.final.txt").write_text(full_prompt + "\n", encoding="utf-8")
    (shot_dir / "negative_prompt.txt").write_text(NEGATIVE_PROMPT + "\n", encoding="utf-8")
    (shot_dir / "duration_used.txt").write_text(f"{format_duration_value(shot_duration)}\n", encoding="utf-8")

    payload_preview: dict[str, Any] = {
        "model": MODEL_NAME,
        "prompt": full_prompt,
        "duration": shot_duration,
        "resolution": DEFAULT_RESOLUTION,
        "ratio": DEFAULT_RATIO,
        "generate_audio": generate_audio,
        "web_search": False,
        "watermark": False,
        "return_last_frame": False,
    }
    write_json(shot_dir / "payload.preview.json", payload_preview)
    write_json(shot_dir / "request_payload.preview.json", payload_preview)
    write_json(
        shot_dir / "render_report.json",
        {
            "record_id": f"LEGACY_{shot.shot_id}",
            "model_profile_id": "legacy_seedance_direct",
            "mapping_summary": {
                "must": "partial",
                "prefer": "partial",
                "avoid": "unsupported",
                "dialogue": "partial",
                "continuity": "partial",
            },
            "downgrades": [
                {
                    "type": "legacy_fallback",
                    "detail": "record file missing; used hardcoded prompt",
                }
            ],
            "requires_manual_review": True,
            "generated_at": datetime.now().isoformat(),
        },
    )

    if write_pending:
        (shot_dir / "output.pending.txt").write_text(
            "Run script without --prepare-only to generate actual output.mp4.\n",
            encoding="utf-8",
        )
    else:
        pending = shot_dir / "output.pending.txt"
        if pending.exists():
            pending.unlink()

    print(f"[{shot.shot_id}] prepared (legacy fallback) -> {shot_dir}")
    return shot_dir, payload_preview


def run_one_shot_payload(
    provider: str,
    api_key: str,
    shot_id: str,
    shot_dir: Path,
    payload: dict[str, Any],
    poll_interval_sec: float,
    timeout_sec: int,
    max_retries: int,
    retry_wait_sec: float,
) -> None:
    total_retries = max(1, int(max_retries))
    fallback_wait = max(1, int(retry_wait_sec))
    last_error = ""

    for attempt in range(1, total_retries + 1):
        try:
            prediction_id, req_meta = post_generate_payload(
                provider=provider,
                api_key=api_key,
                payload=payload,
            )
            req_meta["attempt"] = attempt
            req_meta["provider"] = provider
            write_json(shot_dir / "generate_request_response.json", req_meta)

            final_result = poll_until_done(
                provider=provider,
                api_key=api_key,
                prediction_id=prediction_id,
                poll_interval_sec=poll_interval_sec,
                timeout_sec=timeout_sec,
            )
            write_json(shot_dir / "final_status.json", final_result)

            video_url = extract_output_url(provider=provider, result=final_result)
            (shot_dir / "output_url.txt").write_text(video_url + "\n", encoding="utf-8")

            output_file = shot_dir / "output.mp4"
            download_file(video_url, output_file)
            pending = shot_dir / "output.pending.txt"
            if pending.exists():
                pending.unlink()
            print(f"[{shot_id}] done -> {output_file}")
            return
        except Exception as exc:
            last_error = str(exc)
            retryable = is_retryable_api_error(last_error)
            if (not retryable) or (attempt >= total_retries):
                break
            wait_sec = parse_retry_after_seconds(last_error, default=fallback_wait)
            print(
                f"[WARN] {shot_id} attempt {attempt}/{total_retries} failed, retry in {wait_sec}s: {last_error}",
                file=sys.stderr,
            )
            time.sleep(wait_sec)

    raise RuntimeError(
        f"{shot_id} failed after {total_retries} attempts "
        f"(provider={provider or 'unknown'}): {last_error or 'unknown error'}"
    )


def assert_provider_payload(payload: dict[str, Any], profile: dict[str, Any], shot_id: str) -> None:
    provider = str(profile.get("provider", "")).strip().lower() or "unknown"
    payload_fields = profile.get("payload_fields", {})
    required = []
    if bool(profile.get("include_model_in_payload", True)):
        required.append("model")
    required.extend(
        [
            str(payload_fields.get("positive_prompt_field") or "prompt"),
            str(payload_fields.get("duration_field") or "duration"),
            str(payload_fields.get("resolution_field") or "resolution"),
            str(payload_fields.get("ratio_field") or "ratio"),
        ]
    )
    image_field = payload_fields.get("image_field")
    if isinstance(image_field, str) and image_field.strip():
        required.append(image_field.strip())

    missing = [k for k in required if (k not in payload) or (str(payload.get(k, "")).strip() == "")]
    if missing:
        raise RuntimeError(
            f"{shot_id} payload 缺少 {provider} 必填字段: {', '.join(missing)}。"
            "请检查 profile payload_fields 与 image 输入配置。"
        )


def parse_shot_id_set(value: str) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return set()
    return {
        part.strip().upper()
        for part in re.split(r"[,，\s]+", text)
        if part.strip()
    }


def should_run_phone_audio_repair(shot_id: str, repair_value: str, record: dict[str, Any] | None) -> bool:
    selected = parse_shot_id_set(repair_value)
    if not selected:
        return False
    if "ALL" not in selected and str(shot_id).strip().upper() not in selected:
        return False
    return is_phone_remote_listener_record(record or {})


def record_phone_review_text(record: dict[str, Any]) -> str:
    prompt_render = record.get("prompt_render", {})
    shot_execution = record.get("shot_execution", {})
    camera_plan = shot_execution.get("camera_plan", {}) if isinstance(shot_execution, dict) else {}
    first_frame = record.get("first_frame_contract", {})
    dialogue_blocking = record.get("dialogue_blocking", {})
    scene_anchor = record.get("scene_anchor", {})
    parts = [
        json.dumps(first_frame, ensure_ascii=False) if isinstance(first_frame, dict) else "",
        json.dumps(dialogue_blocking, ensure_ascii=False) if isinstance(dialogue_blocking, dict) else "",
        str(prompt_render.get("shot_positive_core") or "") if isinstance(prompt_render, dict) else "",
        str(camera_plan.get("shot_type") or "") if isinstance(camera_plan, dict) else "",
        str(camera_plan.get("framing_focus") or "") if isinstance(camera_plan, dict) else "",
        str(shot_execution.get("action_intent") or "") if isinstance(shot_execution, dict) else "",
        str(shot_execution.get("emotion_intent") or "") if isinstance(shot_execution, dict) else "",
        " ".join(ensure_list_str(scene_anchor.get("must_have_elements")))
        if isinstance(scene_anchor, dict)
        else "",
    ]
    return " ".join(part for part in parts if part).strip()


def payload_generate_audio_enabled(payload: dict[str, Any], profile: dict[str, Any]) -> bool:
    audio_field = payload_audio_field(profile)
    if not audio_field:
        return False
    return bool(payload.get(audio_field))


def phone_listener_visual_risk(record: dict[str, Any]) -> dict[str, Any]:
    text = record_phone_review_text(record)
    lowered = text.lower()
    hidden_terms = [
        term
        for term in (
            "嘴部完全不可见",
            "嘴部不可见",
            "画面不显示嘴",
            "不得露出嘴",
            "背侧",
            "背影",
            "侧后",
            "右后侧",
            "后侧",
            "遮挡嘴部",
            "挡住嘴部",
            "手机、右手和拍摄角度完全挡住嘴部",
            "mouth not visible",
            "mouth hidden",
            "from behind",
            "back view",
        )
        if term.lower() in lowered
    ]
    visible_mouth_terms = [
        term
        for term in (
            "正面",
            "正脸",
            "脸部",
            "嘴部",
            "嘴唇",
            "张口",
            "口型",
            "双人中近景",
            "中近景",
            "近景",
            "清楚入镜",
            "清楚可见",
            "front-facing",
            "visible mouth",
            "lip",
        )
        if term.lower() in lowered
    ]
    visible_names = visible_character_names_from_record(record)
    phone_lines = phone_dialogue_lines_from_record(record)
    listeners = silent_listener_names_from_record(record, phone_lines)
    multi_visible = len(visible_names) >= 2
    return {
        "review_text_chars": len(text),
        "visible_characters": visible_names,
        "phone_listeners": listeners,
        "mouth_hidden_terms_found": unique_keep_order(hidden_terms),
        "visible_mouth_or_front_terms_found": unique_keep_order(visible_mouth_terms),
        "multi_visible_characters": multi_visible,
        "mouth_visibility_risk": bool((visible_mouth_terms or multi_visible) and not hidden_terms),
    }


def extract_phone_lipsync_contact_sheet(source_video: Path, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_video),
        "-vf",
        "fps=1,scale=248:-1,tile=4x3",
        "-frames:v",
        "1",
        "-update",
        "1",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return {
        "path": str(output_path) if output_path.exists() else "",
        "created": output_path.exists(),
        "returncode": result.returncode,
        "stderr_tail": (result.stderr or "")[-1000:],
    }


def build_phone_lipsync_self_check(
    *,
    shot_id: str,
    shot_dir: Path,
    record: dict[str, Any],
    profile: dict[str, Any],
    payload_preview: dict[str, Any],
    output_path: Path | None,
    auto_repair_enabled: bool,
    manual_repair_requested: bool,
) -> dict[str, Any]:
    phone_remote = is_phone_remote_listener_record(record)
    phone_lines = phone_dialogue_lines_from_record(record)
    audio_enabled = payload_generate_audio_enabled(payload_preview, profile)
    visual_risk = phone_listener_visual_risk(record) if phone_remote else {}
    repair_recommended = bool(
        phone_remote
        and audio_enabled
        and visual_risk.get("mouth_visibility_risk")
    )
    contact_sheet: dict[str, Any] = {}
    if output_path is not None and output_path.exists() and phone_remote:
        contact_sheet = extract_phone_lipsync_contact_sheet(
            source_video=output_path,
            output_path=shot_dir / "phone_lipsync_contact_sheet.jpg",
        )

    return {
        "created_at": datetime.now().isoformat(),
        "shot_id": shot_id,
        "phone_remote_listener_candidate": phone_remote,
        "generate_audio": audio_enabled,
        "phone_dialogue_lines": [
            {
                "speaker": str(line.get("speaker") or "").strip(),
                "listener": dialogue_listener_name(line),
                "text": str(line.get("text") or "").strip(),
            }
            for line in phone_lines
        ],
        "visual_risk": visual_risk,
        "manual_repair_requested": manual_repair_requested,
        "auto_repair_enabled": auto_repair_enabled,
        "repair_recommended": repair_recommended,
        "repair_will_run": bool(manual_repair_requested or (auto_repair_enabled and repair_recommended)),
        "repair_reason": (
            "phone_remote_voice_with_generated_audio_and_visible_listener_mouth_risk"
            if repair_recommended
            else ""
        ),
        "contact_sheet": contact_sheet,
        "recommended_output_when_repaired": str(shot_dir / "output.phone_fixed.mp4"),
    }


def write_phone_lipsync_self_check(
    *,
    shot_id: str,
    shot_dir: Path,
    record: dict[str, Any],
    profile: dict[str, Any],
    payload_preview: dict[str, Any],
    output_path: Path | None,
    auto_repair_enabled: bool,
    manual_repair_requested: bool,
) -> dict[str, Any]:
    report = build_phone_lipsync_self_check(
        shot_id=shot_id,
        shot_dir=shot_dir,
        record=record,
        profile=profile,
        payload_preview=payload_preview,
        output_path=output_path,
        auto_repair_enabled=auto_repair_enabled,
        manual_repair_requested=manual_repair_requested,
    )
    if report.get("phone_remote_listener_candidate"):
        write_json(shot_dir / "phone_lipsync_self_check.json", report)
    return report


def narration_lines_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    dialogue_language = record.get("dialogue_language", {})
    raw_lines = (
        dialogue_language.get("narration_lines", [])
        if isinstance(dialogue_language, dict)
        else []
    )
    return normalize_spoken_lines(raw_lines)


def is_narration_only_model_audio_record(
    record: dict[str, Any],
    payload_preview: dict[str, Any],
    profile: dict[str, Any],
) -> bool:
    if not isinstance(record, dict) or not record:
        return False
    dialogue_language = record.get("dialogue_language", {})
    if not isinstance(dialogue_language, dict):
        return False
    dialogue_lines = normalize_spoken_lines(dialogue_language.get("dialogue_lines", []))
    narration_lines = narration_lines_from_record(record)
    return bool(
        narration_lines
        and not dialogue_lines
        and payload_generate_audio_enabled(payload_preview, profile)
    )


def extract_narration_candidate_contact_sheet(source_video: Path, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_video),
        "-vf",
        "fps=2,scale=248:-1,tile=4x3",
        "-frames:v",
        "1",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return {
        "path": str(output_path) if output_path.exists() else "",
        "created": output_path.exists(),
        "returncode": result.returncode,
        "stderr_tail": (result.stderr or "")[-1000:],
    }


def extract_narration_candidate_audio(source_video: Path, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return {
        "path": str(output_path) if output_path.exists() else "",
        "created": output_path.exists(),
        "returncode": result.returncode,
        "stderr_tail": (result.stderr or "")[-1000:],
    }


def transcribe_audio_with_openai(audio_path: Path) -> dict[str, Any]:
    if not audio_path.exists():
        return {"available": False, "reason": "audio_missing", "text": ""}
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return {"available": False, "reason": "OPENAI_API_KEY_missing", "text": ""}
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:
        return {"available": False, "reason": f"openai_import_failed: {exc}", "text": ""}
    try:
        client = OpenAI()
        with audio_path.open("rb") as audio_file:
            result = client.audio.transcriptions.create(
                model=os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"),
                file=audio_file,
                response_format="text",
                language="zh",
            )
        text = result if isinstance(result, str) else str(getattr(result, "text", result))
        return {"available": True, "reason": "", "text": text.strip()}
    except Exception as exc:
        return {"available": False, "reason": f"transcribe_failed: {exc}", "text": ""}


def normalize_cjk_for_review(value: Any) -> str:
    text = str(value or "")
    return re.sub(r"[\s，。！？!?,、：:；;\"'“”‘’（）()《》<>]", "", text)


def transcript_language_review(transcript: str, expected_lines: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = normalize_cjk_for_review(transcript)
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
    kana_chars = re.findall(r"[\u3040-\u30ff]", normalized)
    hangul_chars = re.findall(r"[\uac00-\ud7af]", normalized)
    latin_words = re.findall(r"[A-Za-z]{2,}", normalized)
    expected_text = "".join(
        normalize_cjk_for_review(line.get("text", "")) for line in expected_lines
    )
    expected_chars = set(re.findall(r"[\u4e00-\u9fff]", expected_text))
    transcript_chars = set(cjk_chars)
    overlap = len(expected_chars & transcript_chars)
    language_ok = bool(
        len(cjk_chars) >= 2
        and not kana_chars
        and not hangul_chars
        and len(latin_words) == 0
    )
    rough_text_ok = bool(not expected_chars or overlap >= max(1, min(3, len(expected_chars) // 2)))
    return {
        "transcript": transcript,
        "expected_text": expected_text,
        "cjk_char_count": len(cjk_chars),
        "kana_char_count": len(kana_chars),
        "hangul_char_count": len(hangul_chars),
        "latin_word_count": len(latin_words),
        "expected_cjk_overlap": overlap,
        "language_ok": language_ok,
        "rough_text_ok": rough_text_ok,
        "pass": bool(language_ok and rough_text_ok),
    }


def vision_review_contact_sheet(contact_sheet: Path, visible_names: list[str]) -> dict[str, Any]:
    if not contact_sheet.exists():
        return {"available": False, "reason": "contact_sheet_missing", "pass": None}
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return {"available": False, "reason": "OPENAI_API_KEY_missing", "pass": None}
    try:
        from openai import OpenAI  # type: ignore
    except Exception as exc:
        return {"available": False, "reason": f"openai_import_failed: {exc}", "pass": None}
    prompt = (
        "You are checking a contact sheet from a video shot with offscreen narration. "
        "Visible characters must not be speaking. Inspect whether any visible character appears "
        "to talk, mouth words, open their mouth for speech, or lip-sync to narration. "
        "Return JSON only with keys: visible_mouth_talking (boolean), severity "
        "('none','low','medium','high'), notes (short string). "
        f"Visible character names: {', '.join(visible_names) if visible_names else 'unknown'}."
    )
    try:
        client = OpenAI()
        data_url = encode_image_data_uri(contact_sheet)
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_VISION_QA_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        severity = str(parsed.get("severity") or "").strip().lower()
        visible_talking = bool(parsed.get("visible_mouth_talking"))
        passed = bool((not visible_talking) and severity not in {"medium", "high"})
        return {
            "available": True,
            "reason": "",
            "visible_mouth_talking": visible_talking,
            "severity": severity or "unknown",
            "notes": str(parsed.get("notes") or "").strip(),
            "pass": passed,
        }
    except Exception as exc:
        return {"available": False, "reason": f"vision_review_failed: {exc}", "pass": None}


def visible_character_names_from_record_for_narration(record: dict[str, Any]) -> list[str]:
    first_frame = record.get("first_frame_contract", {})
    names = ensure_list_str(first_frame.get("visible_characters")) if isinstance(first_frame, dict) else []
    if names:
        return names
    character_anchor = record.get("character_anchor", {})
    if isinstance(character_anchor, dict):
        return unique_keep_order(
            [
                str(node.get("name") or node.get("character_id") or "").strip()
                for node in collect_character_nodes(character_anchor)
                if str(node.get("name") or node.get("character_id") or "").strip()
            ]
        )
    return []


def score_narration_candidate(report: dict[str, Any]) -> int:
    score = 0
    if report.get("output_exists"):
        score += 10
    language_review = report.get("language_review", {})
    if language_review.get("pass"):
        score += 50
    elif language_review.get("language_ok"):
        score += 20
    else:
        score -= 80
    vision_review = report.get("vision_review", {})
    vision_pass = vision_review.get("pass")
    if vision_pass is True:
        score += 50
    elif vision_pass is False:
        score -= 100
    else:
        score -= 10
    return int(score)


def copy_generation_artifacts_to_candidate(shot_dir: Path, candidate_dir: Path) -> None:
    for name in (
        "prompt.final.txt",
        "prompt.txt",
        "payload.preview.json",
        "request_payload.preview.json",
        "render_report.json",
        "record.snapshot.json",
        "image_used.txt",
        "last_image_used.txt",
        "negative_prompt.txt",
        "duration_used.txt",
    ):
        copy_file_if_exists(shot_dir / name, candidate_dir / name)


def promote_narration_candidate(candidate_dir: Path, shot_dir: Path) -> None:
    for name in (
        "output.mp4",
        "output_url.txt",
        "final_status.json",
        "generate_request_response.json",
    ):
        copy_file_if_exists(candidate_dir / name, shot_dir / name)


def run_narration_candidate_loop(
    *,
    provider: str,
    api_key: str,
    shot_id: str,
    shot_dir: Path,
    record: dict[str, Any],
    profile: dict[str, Any],
    payload: dict[str, Any],
    poll_interval_sec: float,
    timeout_sec: int,
    max_retries: int,
    retry_wait_sec: float,
    candidate_attempts: int,
) -> dict[str, Any]:
    attempts = clamp_int(int(candidate_attempts), 1, 3)
    candidate_root = shot_dir / "narration_candidates"
    candidate_root.mkdir(parents=True, exist_ok=True)
    visible_names = visible_character_names_from_record_for_narration(record)
    expected_lines = narration_lines_from_record(record)
    reports: list[dict[str, Any]] = []

    for attempt in range(1, attempts + 1):
        candidate_dir = candidate_root / f"attempt_{attempt:02d}"
        if candidate_dir.exists():
            shutil.rmtree(candidate_dir)
        candidate_dir.mkdir(parents=True, exist_ok=True)
        copy_generation_artifacts_to_candidate(shot_dir, candidate_dir)
        print(f"[{shot_id}] narration candidate {attempt}/{attempts} -> {candidate_dir}")
        report: dict[str, Any] = {
            "attempt": attempt,
            "candidate_dir": str(candidate_dir),
            "created_at": datetime.now().isoformat(),
            "expected_narration": [str(line.get("text") or "").strip() for line in expected_lines],
            "visible_characters": visible_names,
        }
        try:
            run_one_shot_payload(
                provider=provider,
                api_key=api_key,
                shot_id=f"{shot_id}/narration_candidate_{attempt:02d}",
                shot_dir=candidate_dir,
                payload=payload,
                poll_interval_sec=poll_interval_sec,
                timeout_sec=timeout_sec,
                max_retries=max_retries,
                retry_wait_sec=retry_wait_sec,
            )
            output_path = candidate_dir / "output.mp4"
            report["output_exists"] = output_path.exists()
            contact_sheet = candidate_dir / "narration_lipsync_contact_sheet.jpg"
            report["contact_sheet"] = extract_narration_candidate_contact_sheet(
                source_video=output_path,
                output_path=contact_sheet,
            )
            audio_path = candidate_dir / "narration_audio.wav"
            report["audio_extract"] = extract_narration_candidate_audio(
                source_video=output_path,
                output_path=audio_path,
            )
            transcript = transcribe_audio_with_openai(audio_path)
            report["transcription"] = transcript
            report["language_review"] = transcript_language_review(
                str(transcript.get("text") or ""),
                expected_lines,
            )
            report["vision_review"] = vision_review_contact_sheet(contact_sheet, visible_names)
            report["score"] = score_narration_candidate(report)
        except Exception as exc:
            report["output_exists"] = False
            report["error"] = str(exc)
            report["score"] = -1000
            (candidate_dir / "error.txt").write_text(str(exc) + "\n", encoding="utf-8")
        reports.append(report)
        write_json(candidate_dir / "narration_candidate_report.json", report)
        if report.get("language_review", {}).get("pass") and report.get("vision_review", {}).get("pass") is True:
            break

    selected = max(reports, key=lambda item: int(item.get("score", -1000))) if reports else {}
    selected_dir = Path(str(selected.get("candidate_dir") or ""))
    if not selected or not selected_dir.exists() or not (selected_dir / "output.mp4").exists():
        raise RuntimeError(f"{shot_id} narration candidates failed; no usable output.mp4")

    promote_narration_candidate(selected_dir, shot_dir)
    final_report = {
        "created_at": datetime.now().isoformat(),
        "shot_id": shot_id,
        "mode": "default_seedance_narration_candidate_loop",
        "max_attempts": attempts,
        "selected_attempt": int(selected.get("attempt", 0)),
        "selected_candidate_dir": str(selected_dir),
        "selection_reason": (
            "first fully passing candidate"
            if selected.get("language_review", {}).get("pass") and selected.get("vision_review", {}).get("pass") is True
            else "best score after available attempts"
        ),
        "reports": reports,
        "selected_output": str(shot_dir / "output.mp4"),
        "requires_manual_review": any(
            report.get("vision_review", {}).get("pass") is None for report in reports
        ),
    }
    write_json(shot_dir / "narration_candidate_selection.json", final_report)
    print(
        f"[{shot_id}] narration selected attempt {final_report['selected_attempt']} "
        f"-> {shot_dir / 'output.mp4'}"
    )
    return final_report


def normalized_dialogue_lines_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    dialogue_language = record.get("dialogue_language", {})
    raw_lines = (
        dialogue_language.get("dialogue_lines", [])
        if isinstance(dialogue_language, dict)
        else []
    )
    return normalize_spoken_lines(raw_lines)


def phone_dialogue_lines_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        line
        for line in normalized_dialogue_lines_from_record(record)
        if normalize_dialogue_source(line.get("source"), line.get("text", ""), line.get("purpose", "")) == "phone"
    ]


def is_phone_remote_listener_record(record: dict[str, Any]) -> bool:
    phone_lines = phone_dialogue_lines_from_record(record)
    if phone_lines:
        return True
    dialogue_blocking = record.get("dialogue_blocking", {})
    if not isinstance(dialogue_blocking, dict):
        return False
    policy = str(dialogue_blocking.get("lip_sync_policy") or "").lower()
    priority = str(dialogue_blocking.get("speaker_visual_priority") or "").lower()
    return ("remote" in policy and "listener" in policy) or ("listener" in priority and "phone" in policy)


def visible_character_names_from_record(record: dict[str, Any]) -> list[str]:
    names: list[str] = []
    first_frame = record.get("first_frame_contract", {})
    if isinstance(first_frame, dict):
        names.extend(ensure_list_str(first_frame.get("visible_characters")))
        face_visibility = first_frame.get("character_face_visibility")
        if isinstance(face_visibility, dict):
            names.extend(str(key).strip() for key in face_visibility.keys() if str(key).strip())
    anchor = record.get("character_anchor", {})
    if isinstance(anchor, dict):
        for node in collect_character_nodes(anchor):
            name = str(node.get("name") or node.get("character_id") or "").strip()
            if name:
                names.append(name)
    return unique_keep_order(
        [
            name
            for name in names
            if name and name not in {"SCENE_ONLY", "场景主体", "环境主体", "none", "None", "无"}
        ]
    )


def silent_listener_names_from_record(record: dict[str, Any], phone_lines: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    dialogue_blocking = record.get("dialogue_blocking", {})
    if isinstance(dialogue_blocking, dict):
        names.extend(ensure_list_str(dialogue_blocking.get("silent_visible_characters")))
    for line in phone_lines:
        listener = dialogue_listener_name(line)
        if listener:
            names.append(listener)
    if not names:
        names.extend(visible_character_names_from_record(record))
    return unique_keep_order([expand_common_character_name(name) for name in names if name])


def payload_positive_prompt_field(profile: dict[str, Any]) -> str:
    payload_fields = profile.get("payload_fields", {})
    return str(payload_fields.get("positive_prompt_field") or "prompt")


def payload_audio_field(profile: dict[str, Any]) -> str:
    payload_fields = profile.get("payload_fields", {})
    return str(payload_fields.get("audio_field") or "").strip()


def payload_duration_value(payload: dict[str, Any], profile: dict[str, Any]) -> float:
    payload_fields = profile.get("payload_fields", {})
    duration_field = str(payload_fields.get("duration_field") or "duration")
    parsed_float = parse_optional_float(payload.get(duration_field))
    if parsed_float is not None:
        return float(parsed_float)
    return float(MAX_DURATION_SEC)


def phone_listener_no_audio_block(record: dict[str, Any], duration_sec: float) -> str:
    phone_lines = phone_dialogue_lines_from_record(record)
    listeners = silent_listener_names_from_record(record, phone_lines)
    visible_names = visible_character_names_from_record(record)
    listener_text = "、".join(listeners or visible_names or ["画面内接电话人"])
    visible_text = "、".join(visible_names or listeners or ["画面内人物"])
    timeline = estimate_dialogue_timeline(phone_lines, duration_sec) if phone_lines else []
    if timeline:
        first_start = float(timeline[0].get("start_sec", 0.5))
        last_end = float(timeline[-1].get("end_sec", max(1.0, float(duration_sec) - 0.5)))
    else:
        first_start = 0.5
        last_end = max(1.0, float(duration_sec) - 0.5)
    first_start = max(0.0, min(first_start, max(0.0, float(duration_sec) - 1.0)))
    max_listen_end = max(first_start + 0.8, float(duration_sec) - 0.5)
    last_end = max(first_start + 0.8, min(last_end, max_listen_end))
    last_end = min(last_end, float(duration_sec))

    return "\n".join(
        [
            "视频阶段声音策略：",
            "- 本镜头视频生成阶段不生成对白音频。",
            "- 画面中没有任何人说话，没有旁白，没有电话里传来的可听见台词。",
            "- 后期会加入电话远端语音；视频阶段只生成无声接电话画面。",
            "",
            "接电话动作时间轴：",
            f"- 0.0-{first_start:.1f}秒：{listener_text}已经把手机贴在耳边或正稳定接起电话，嘴唇闭合，进入认真听电话的状态。",
            f"- {first_start:.1f}-{last_end:.1f}秒：{listener_text}认真地听电话，一句话也没有说，闭着嘴，认真思考，不做任何说话口型。",
            f"- {last_end:.1f}-{float(duration_sec):.1f}秒：{listener_text}仍然手机贴耳，沉默吸收信息，保持闭嘴，只允许眼神、呼吸、眉头和握手机手指的细微反应。",
            "",
            "手机持续性约束：",
            f"- 手机屏幕朝内，贴近{listener_text}耳侧或脸侧，屏幕内容不朝向镜头。",
            "- 手机位置必须连续稳定，不要凭空离开耳边，不要变成看屏幕、刷屏或发短信。",
            "",
            "画面内嘴型约束：",
            f"- {visible_text}全程闭嘴；嘴唇闭合或自然静止，不能张口、不能对口型。",
            f"- {listener_text}的明确表演动作是：认真地听电话，一句话也没有说，闭着嘴，认真思考。",
            "- 如果画面内能看到嘴部，嘴部必须是静止的倾听状态；不要出现说话、念台词、唱歌或旁白口型。",
            "",
            "禁止：",
            f"- 不要让{visible_text}说电话远端角色的台词。",
            "- 不要新增台词。",
            "- 不要省略后期将加入的电话语音内容；视频阶段只负责无声接听表演。",
            "- 不要生成字幕、聊天界面、来电文字弹窗或额外屏幕内容。",
        ]
    )


def strip_phone_voice_phrases(prompt_text: str) -> str:
    text = prompt_text
    replacements = [
        (r"电话/手机听筒里传来[^。\n；;]+[。；;]?", "画面中没有任何人说话；"),
        (r"手机听筒里传来[^。\n；;]+[。；;]?", "画面中没有任何人说话；"),
        (r"(?<!没有)电话里传来[^。\n；;]+[。；;]?", "画面中没有任何人说话；"),
        (r"本镜头只承载[^。\n；;]*电话[^。\n；;]*[。；;]?", "本镜头只承载无声接电话反应；"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    text = text.replace("远端声音", "远端信息")
    text = text.replace("接收声音", "接收信息")
    return text


def build_phone_no_audio_prompt(prompt_text: str, record: dict[str, Any], duration_sec: float) -> str:
    block = phone_listener_no_audio_block(record, duration_sec)
    existing_no_audio_pattern = re.compile(
        r"\n视频阶段声音策略：\n.*?\n\n质量与连续性约束：",
        flags=re.DOTALL,
    )
    if existing_no_audio_pattern.search(prompt_text):
        return existing_no_audio_pattern.sub(
            "\n" + block + "\n\n质量与连续性约束：",
            prompt_text,
            count=1,
        )

    scrubbed = strip_phone_voice_phrases(prompt_text)
    pattern = re.compile(
        r"\n台词与嘴型必须严格对应：\n.*?\n\n质量与连续性约束：",
        flags=re.DOTALL,
    )
    if pattern.search(scrubbed):
        return pattern.sub("\n" + block + "\n\n质量与连续性约束：", scrubbed, count=1)
    marker = "\n质量与连续性约束："
    if marker in scrubbed:
        return scrubbed.replace(marker, "\n" + block + "\n" + marker, 1)
    return scrubbed.rstrip() + "\n\n" + block


def build_phone_no_audio_payload(
    *,
    payload_preview: dict[str, Any],
    profile: dict[str, Any],
    prompt_text: str,
) -> dict[str, Any]:
    payload = dict(payload_preview)
    payload[payload_positive_prompt_field(profile)] = prompt_text
    audio_field = payload_audio_field(profile)
    if audio_field:
        payload[audio_field] = False
    return payload


def run_subprocess_checked(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"命令失败: {' '.join(cmd)}\n{detail}")


def ffprobe_has_audio(path: Path) -> bool:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return False
    return bool(data.get("streams"))


def extract_phone_repair_audio(source_video: Path, audio_dir: Path) -> dict[str, str]:
    audio_dir.mkdir(parents=True, exist_ok=True)
    if not ffprobe_has_audio(source_video):
        raise RuntimeError(f"phone audio repair 需要原始 output.mp4 带音频: {source_video}")
    aac_path = audio_dir / "phone_audio_from_original.aac"
    wav_path = audio_dir / "phone_audio_from_original.wav"
    run_subprocess_checked(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-vn",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(aac_path),
        ]
    )
    run_subprocess_checked(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            str(wav_path),
        ]
    )
    return {"aac": str(aac_path), "wav": str(wav_path)}


def composite_phone_repair_video(no_audio_video: Path, audio_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_subprocess_checked(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(no_audio_video),
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-shortest",
            str(output_path),
        ]
    )


def write_phone_audio_repair_artifacts(
    *,
    shot_id: str,
    shot_dir: Path,
    record: dict[str, Any],
    profile: dict[str, Any],
    payload_preview: dict[str, Any],
    reason: str,
    prepare_only: bool,
) -> tuple[Path, dict[str, Any]]:
    repair_dir = shot_dir / "phone_audio_repair"
    repair_dir.mkdir(parents=True, exist_ok=True)
    duration_sec = payload_duration_value(payload_preview, profile)
    original_prompt = str(payload_preview.get(payload_positive_prompt_field(profile)) or "")
    repair_prompt = build_phone_no_audio_prompt(original_prompt, record, duration_sec)
    repair_payload = build_phone_no_audio_payload(
        payload_preview=payload_preview,
        profile=profile,
        prompt_text=repair_prompt,
    )
    assert_provider_payload(repair_payload, profile, shot_id)

    (repair_dir / "prompt.final.txt").write_text(repair_prompt + "\n", encoding="utf-8")
    (repair_dir / "prompt.txt").write_text(repair_prompt + "\n", encoding="utf-8")
    write_json(repair_dir / "payload.preview.json", repair_payload)
    write_json(repair_dir / "request_payload.preview.json", repair_payload)
    write_json(
        repair_dir / "phone_audio_repair_plan.json",
        {
            "created_at": datetime.now().isoformat(),
            "shot_id": shot_id,
            "reason": reason,
            "source_output": str(shot_dir / "output.mp4"),
            "mode": "rerun_video_without_dialogue_audio_then_composite_original_audio",
            "rerun_source_prompt": str(repair_dir / "prompt.final.txt"),
            "rerun_source_payload": str(repair_dir / "payload.preview.json"),
            "rerun_policy": "repair must regenerate from phone_audio_repair/prompt.final.txt with generate_audio=false; do not trust any previous output.phone_fixed.mp4",
            "phone_remote_listener_candidate": is_phone_remote_listener_record(record),
            "generate_audio": bool(repair_payload.get(payload_audio_field(profile), False)),
            "final_output": str(shot_dir / "output.phone_fixed.mp4"),
            "prepare_only": prepare_only,
        },
    )
    return repair_dir, repair_payload


def load_phone_audio_repair_payload_from_artifacts(
    *,
    repair_dir: Path,
    profile: dict[str, Any],
    shot_id: str,
) -> dict[str, Any]:
    prompt_path = repair_dir / "prompt.final.txt"
    payload_path = repair_dir / "payload.preview.json"
    if not prompt_path.exists():
        raise RuntimeError(f"phone audio repair 缺少无音频闭嘴 prompt: {prompt_path}")
    if not payload_path.exists():
        raise RuntimeError(f"phone audio repair 缺少 payload.preview.json: {payload_path}")
    repair_prompt = prompt_path.read_text(encoding="utf-8").strip()
    repair_payload = read_json(payload_path)
    if not isinstance(repair_payload, dict):
        raise RuntimeError(f"phone audio repair payload 不是 JSON object: {payload_path}")
    repair_payload[payload_positive_prompt_field(profile)] = repair_prompt
    audio_field = payload_audio_field(profile)
    if audio_field:
        repair_payload[audio_field] = False
    assert_provider_payload(repair_payload, profile, f"{shot_id}/phone_audio_repair")
    write_json(repair_dir / "request_payload.preview.json", repair_payload)
    return repair_payload


def write_phone_lipsync_review_hint(
    *,
    shot_id: str,
    shot_dir: Path,
    record: dict[str, Any],
    repair_requested: bool,
) -> None:
    if not is_phone_remote_listener_record(record):
        return
    phone_lines = phone_dialogue_lines_from_record(record)
    listeners = silent_listener_names_from_record(record, phone_lines)
    speakers = unique_keep_order(
        [
            str(line.get("speaker") or "").strip()
            for line in phone_lines
            if str(line.get("speaker") or "").strip()
        ]
    )
    write_json(
        shot_dir / "phone_lipsync_review.json",
        {
            "created_at": datetime.now().isoformat(),
            "shot_id": shot_id,
            "review_required": True,
            "risk": "phone_remote_voice_may_bind_to_visible_listener_mouth",
            "check_after_output_mp4": [
                "画面内接电话人是否闭嘴、没有节奏性口型",
                "电话远端台词是否没有被画面内接电话人开口承担",
                "手机是否在远端语音期间持续贴耳，屏幕朝内",
            ],
            "remote_speakers": speakers,
            "visible_listeners": listeners,
            "repair_requested_this_run": repair_requested,
            "repair_cli": f"--phone-audio-repair-shots {shot_id}",
            "repair_output": str(shot_dir / "output.phone_fixed.mp4"),
        },
    )


def run_phone_audio_repair(
    *,
    provider: str,
    api_key: str,
    shot_id: str,
    shot_dir: Path,
    record: dict[str, Any],
    profile: dict[str, Any],
    payload_preview: dict[str, Any],
    poll_interval_sec: float,
    timeout_sec: int,
    max_retries: int,
    retry_wait_sec: float,
    reason: str,
) -> Path:
    original_output = shot_dir / "output.mp4"
    if not original_output.exists():
        raise RuntimeError(f"phone audio repair 找不到原始 output.mp4: {original_output}")

    repair_dir, _ = write_phone_audio_repair_artifacts(
        shot_id=shot_id,
        shot_dir=shot_dir,
        record=record,
        profile=profile,
        payload_preview=payload_preview,
        reason=reason,
        prepare_only=False,
    )
    repair_payload = load_phone_audio_repair_payload_from_artifacts(
        repair_dir=repair_dir,
        profile=profile,
        shot_id=shot_id,
    )

    print(
        f"[{shot_id}] phone audio repair: rerun from phone_audio_repair/prompt.final.txt "
        f"with generate_audio=false -> {repair_dir}"
    )
    run_one_shot_payload(
        provider=provider,
        api_key=api_key,
        shot_id=f"{shot_id}/phone_audio_repair",
        shot_dir=repair_dir,
        payload=repair_payload,
        poll_interval_sec=poll_interval_sec,
        timeout_sec=timeout_sec,
        max_retries=max_retries,
        retry_wait_sec=retry_wait_sec,
    )

    no_audio_video = repair_dir / "output.mp4"
    audio_paths = extract_phone_repair_audio(original_output, repair_dir / "audio")
    final_output = shot_dir / "output.phone_fixed.mp4"
    composite_phone_repair_video(no_audio_video, Path(audio_paths["wav"]), final_output)
    write_json(
        repair_dir / "phone_audio_repair_report.json",
        {
            "created_at": datetime.now().isoformat(),
            "shot_id": shot_id,
            "reason": reason,
            "source_output": str(original_output),
            "rerun_source_prompt": str(repair_dir / "prompt.final.txt"),
            "rerun_source_payload": str(repair_dir / "payload.preview.json"),
            "rerun_policy": "always regenerate no-audio closed-mouth listener video from repair prompt; do not trust previous output.phone_fixed.mp4",
            "generate_audio": bool(repair_payload.get(payload_audio_field(profile), False)),
            "no_audio_video": str(no_audio_video),
            "extracted_audio": audio_paths,
            "final_output": str(final_output),
            "final_has_audio": ffprobe_has_audio(final_output),
        },
    )
    print(f"[{shot_id}] phone audio repair done -> {final_output}")
    return final_output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run provider-routed Seedance image-to-video API for selected shots."
    )
    parser.add_argument(
        "--experiment-name",
        default=datetime.now().strftime("exp_%Y%m%d_%H%M%S"),
        help="Experiment folder name under test/.",
    )
    parser.add_argument(
        "--shots",
        default="",
        help="Comma-separated shot ids, e.g. SH02,SH10. Empty means all default shots.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help=(
            "Only prepare test folders and render artifacts; do not call API. "
            "When record+profile files are available, renderer outputs prompt.final.txt, "
            "payload.preview.json and render_report.json."
        ),
    )
    parser.add_argument(
        "--model-audio",
        action="store_true",
        help=(
            "Enable model-generated audio track. "
            "Kept for compatibility; audio is ON by default."
        ),
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Force disable generate_audio (overrides --model-audio).",
    )
    parser.add_argument(
        "--enable-subtitle-hint",
        action="store_true",
        help=(
            "Include subtitle_overlay_hint from records into prompt text. "
            "Default is OFF (subtitle hint suppressed)."
        ),
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Polling interval in seconds.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Per-shot timeout in seconds.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=10,
        help="Max retries per single shot generation when API is rate-limited.",
    )
    parser.add_argument(
        "--retry-wait-sec",
        type=float,
        default=20.0,
        help="Fallback retry wait seconds when provider does not return retry-after.",
    )
    parser.add_argument(
        "--inter-shot-wait",
        type=float,
        default=3.0,
        help="Sleep seconds between consecutive shot generation requests in API mode.",
    )
    parser.add_argument(
        "--phone-audio-repair-shots",
        default="",
        help=(
            "Comma-separated shot ids, or ALL, to run the phone-listener fallback after normal generation. "
            "Only record-backed phone/remote-listener shots are repaired. The normal output.mp4 is preserved; "
            "the repaired composite is written as output.phone_fixed.mp4. Repair generation always reruns "
            "from phone_audio_repair/prompt.final.txt with generate_audio=false."
        ),
    )
    parser.add_argument(
        "--phone-audio-repair-reason",
        default="manual_lip_sync_failure_after_visual_qa",
        help="Reason string written into phone_audio_repair_report.json.",
    )
    parser.add_argument(
        "--auto-phone-audio-repair",
        dest="auto_phone_audio_repair",
        action="store_true",
        default=True,
        help=(
            "After each generated phone-listener shot, run deterministic lip-sync self-check. "
            "If generated phone audio is paired with a high-risk visible listener mouth, "
            "automatically rerun silent listener video and composite the original phone audio."
        ),
    )
    parser.add_argument(
        "--no-auto-phone-audio-repair",
        dest="auto_phone_audio_repair",
        action="store_false",
        help="Disable automatic phone-listener lip-sync self-check repair.",
    )
    parser.add_argument(
        "--auto-narration-candidates",
        dest="auto_narration_candidates",
        action="store_true",
        default=True,
        help=(
            "Default for narration-only model-audio shots: generate Seedance narration candidates, "
            "QA audio language and visible mouth/lip-sync risk, then promote the best attempt."
        ),
    )
    parser.add_argument(
        "--no-auto-narration-candidates",
        dest="auto_narration_candidates",
        action="store_false",
        help="Disable the default narration candidate loop.",
    )
    parser.add_argument(
        "--narration-candidate-attempts",
        type=int,
        default=DEFAULT_NARRATION_CANDIDATE_ATTEMPTS,
        help="Max Seedance attempts for narration-only model-audio shots (1-3, default: 3).",
    )
    parser.add_argument(
        "--records-dir",
        default=DEFAULT_RECORDS_DIR,
        help="Shot record directory, default points to organized records/.",
    )
    parser.add_argument(
        "--model-profiles",
        default=DEFAULT_PROFILE_FILE,
        help="Model capability profiles json file.",
    )
    parser.add_argument(
        "--model-profile-id",
        default=DEFAULT_PROFILE_ID,
        help="Single profile id (kept for compatibility).",
    )
    parser.add_argument(
        "--video-model",
        default="",
        choices=["", "atlas-seedance1.5", "novita-seedance1.5"],
        help=(
            "Macro I2V provider selector. Empty means VIDEO_MODEL env if set, "
            "otherwise --model-profile-id. Supported: atlas-seedance1.5, novita-seedance1.5."
        ),
    )
    parser.add_argument(
        "--character-lock-profiles",
        default=DEFAULT_CHARACTER_LOCK_FILE,
        help="Character lock profile catalog json file.",
    )
    parser.add_argument(
        "--profile-ids",
        default="",
        help=(
            "Comma-separated profile ids for batch prepare-only runs, "
            "e.g. seedance15_i2v_atlas,generic_t2v_with_negative_example"
        ),
    )
    parser.add_argument(
        "--image-url",
        default="",
        help=(
            "Default first-frame image URL for image-to-video profiles. "
            "Used when shot record and --image-input-map do not provide one."
        ),
    )
    parser.add_argument(
        "--last-image-url",
        default="",
        help=(
            "Default last-frame image URL for image-to-video profiles (optional). "
            "Used when shot record and --image-input-map do not provide one."
        ),
    )
    parser.add_argument(
        "--image-input-map",
        default="",
        help=(
            "Optional JSON map for per-shot image inputs. "
            "Format: {\"default\": {\"image\": \"...\", \"last_image\": \"...\"}, "
            "\"SH12\": {\"image\": \"...\", \"last_image\": \"...\"}}"
        ),
    )
    parser.add_argument(
        "--keyframe-prompts-root",
        default="",
        help=(
            "Optional keyframe experiment root containing <shot_id>/start/prompt.txt. "
            "If omitted, the script will try to infer it from --image-input-map."
        ),
    )
    parser.add_argument(
        "--duration-overrides",
        default="",
        help=(
            "Optional JSON map {\"SH01\": 5, \"SH02\": 6} to override per-shot duration_sec "
            "before profile clamp. Useful for dialogue-complete cuts."
        ),
    )
    parser.add_argument(
        "--execution-overlays",
        default="",
        help=(
            "Optional JSON execution-only prompt overlays. Supports default/* and per-shot "
            "entries with append_positive_core / negative_prompt fields; original records are not mutated."
        ),
    )
    parser.add_argument(
        "--duration-buffer-sec",
        type=float,
        default=DEFAULT_DURATION_BUFFER_SEC,
        help=(
            "Seconds added to the resolved shot duration budget before profile clamp. "
            "Default: 0.5."
        ),
    )
    return parser.parse_args()


def select_shots(shots_arg: str) -> list[Shot]:
    if not shots_arg.strip():
        return SHOTS

    requested = [s.strip().upper() for s in shots_arg.split(",") if s.strip()]
    available_map = {s.shot_id: s for s in SHOTS}
    dynamic_map: dict[str, Shot] = {}
    unknown: list[str] = []
    for shot_id in requested:
        if shot_id in available_map:
            continue
        if re.match(r"^SH\d{2}$", shot_id):
            dynamic_map[shot_id] = Shot(shot_id=shot_id, prompt="")
        else:
            unknown.append(shot_id)
    if unknown:
        allowed = ", ".join(sorted(available_map))
        raise ValueError(
            f"未知镜头格式: {', '.join(unknown)}。可选内置: {allowed}，"
            "或使用 SHxx 形式并提供对应 record。"
        )

    ordered_unique: list[Shot] = []
    seen: set[str] = set()
    for shot_id in requested:
        if shot_id not in seen:
            if shot_id in available_map:
                ordered_unique.append(available_map[shot_id])
            else:
                ordered_unique.append(dynamic_map[shot_id])
            seen.add(shot_id)
    return ordered_unique


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")
    generate_audio_enabled = not bool(args.no_audio)
    enable_subtitle_hint = bool(args.enable_subtitle_hint)
    image_input_map: dict[str, Any] = {}
    image_input_map_path: Path | None = None
    duration_overrides: dict[str, float] = {}
    execution_overlays: dict[str, Any] = {}
    execution_overlays_path: Path | None = None
    keyframe_prompts_root: Path | None = None
    if args.image_input_map.strip():
        image_input_map_path = (project_root / args.image_input_map).resolve()
        try:
            image_input_map = parse_image_input_map(image_input_map_path)
        except Exception as exc:
            print(f"[ERROR] image input map 加载失败: {exc}", file=sys.stderr)
            return 1
    if args.keyframe_prompts_root.strip():
        keyframe_prompts_root = (project_root / args.keyframe_prompts_root).resolve()
        if not keyframe_prompts_root.exists():
            print(
                f"[ERROR] keyframe prompts root 不存在: {keyframe_prompts_root}",
                file=sys.stderr,
            )
            return 1
    elif image_input_map_path is not None:
        inferred_root = image_input_map_path.parent.resolve()
        if inferred_root.exists():
            keyframe_prompts_root = inferred_root
    if args.duration_overrides.strip():
        duration_overrides_path = (project_root / args.duration_overrides).resolve()
        try:
            duration_overrides = load_duration_overrides(duration_overrides_path)
        except Exception as exc:
            print(f"[ERROR] duration overrides 加载失败: {exc}", file=sys.stderr)
            return 1
    if args.execution_overlays.strip():
        execution_overlays_path = (project_root / args.execution_overlays).resolve()
        try:
            execution_overlays = load_execution_overlays(execution_overlays_path)
        except Exception as exc:
            print(f"[ERROR] execution overlays 加载失败: {exc}", file=sys.stderr)
            return 1

    try:
        selected_shots = select_shots(args.shots)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    try:
        video_model = resolve_video_model(args.video_model)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    model_profile_id = args.model_profile_id
    if video_model and not args.profile_ids.strip():
        model_profile_id = profile_id_for_video_model(video_model)
    selected_profile_ids = parse_profile_ids(args.profile_ids, model_profile_id)
    if not args.prepare_only and len(selected_profile_ids) > 1:
        print("[ERROR] API 模式暂不支持多 profile 并行。请去掉 --profile-ids 或使用 --prepare-only。", file=sys.stderr)
        return 1

    experiment_dir = project_root / "test" / args.experiment_name
    experiment_dir.mkdir(parents=True, exist_ok=True)

    records_dir = project_root / args.records_dir
    record_file_map = discover_record_files(records_dir)

    profile_file = project_root / args.model_profiles
    profile_catalog, profile_catalog_issues = load_model_profiles_catalog(profile_file)
    character_lock_profile_file = project_root / args.character_lock_profiles
    character_lock_catalog, character_lock_catalog_issues = load_character_lock_catalog(
        character_lock_profile_file
    )
    selected_providers = unique_keep_order(
        [
            str(
                apply_video_model_profile_defaults(
                    resolve_model_profile(profile_id, profile_catalog, profile_catalog_issues)[0],
                    video_model,
                ).get("provider", "")
            ).strip().lower()
            or "unknown"
            for profile_id in selected_profile_ids
        ]
    )
    run_manifest_provider = selected_providers[0] if len(selected_providers) == 1 else "mixed"

    run_manifest = {
        "created_at": datetime.now().isoformat(),
        "mode": "prepare_only" if args.prepare_only else "api_generate",
        "shots": [s.shot_id for s in selected_shots],
        "records_dir": str(records_dir),
        "model_profile_file": str(profile_file),
        "character_lock_profile_file": str(character_lock_profile_file),
        "image_input_map": args.image_input_map,
        "resolved_image_input_map_path": str(image_input_map_path) if image_input_map_path else "",
        "keyframe_prompts_root": str(keyframe_prompts_root) if keyframe_prompts_root else "",
        "duration_overrides": args.duration_overrides,
        "execution_overlays": str(execution_overlays_path) if execution_overlays_path else "",
        "duration_buffer_sec": max(0.0, float(args.duration_buffer_sec)),
        "duration_payload_policy": "ceil buffered duration to integer seconds, then clamp to profile range",
        "default_image_url": str(args.image_url or "").strip(),
        "default_last_image_url": str(args.last_image_url or "").strip(),
        "generate_audio_enabled": generate_audio_enabled,
        "enable_subtitle_hint": enable_subtitle_hint,
        "phone_audio_repair": {
            "enabled_for": sorted(parse_shot_id_set(args.phone_audio_repair_shots)),
            "auto_enabled": bool(args.auto_phone_audio_repair),
            "reason": str(args.phone_audio_repair_reason or "").strip(),
            "output": "output.phone_fixed.mp4",
            "note": (
                "Manual or automatic fallback for phone-listener shots after lip-sync self-check catches "
                "visible listener mouth risk. Normal output.mp4 is preserved as the audio source. "
                "Repair requests always regenerate a no-audio listener video from "
                "phone_audio_repair/prompt.final.txt before compositing; previous output.phone_fixed.mp4 "
                "is not treated as authoritative."
            ),
        },
        "narration_candidate_policy": {
            "auto_enabled": bool(args.auto_narration_candidates),
            "max_attempts": clamp_int(int(args.narration_candidate_attempts), 1, 3),
            "applies_to": "record-backed shots with dialogue_lines=[] and narration_lines non-empty when generate_audio=true",
            "qa_outputs": [
                "narration_lipsync_contact_sheet.jpg",
                "narration_audio.wav",
                "narration_candidate_report.json",
                "narration_candidate_selection.json",
            ],
            "note": (
                "Default strategy for Seedance narration: generate a candidate, inspect model audio "
                "language by transcription when OPENAI_API_KEY is available, inspect visible mouth risk "
                "by vision QA when available, retry up to three attempts, and promote the best candidate."
            ),
        },
        "video_model": video_model or "",
        "selected_profile_ids": selected_profile_ids,
        "profile_catalog_issues": profile_catalog_issues,
        "character_lock_profile_catalog_issues": character_lock_catalog_issues,
        "multi_profile_layout": len(selected_profile_ids) > 1,
        "api_provider": run_manifest_provider,
        "note": "API mode uses rendered payload.preview.json as single source of truth.",
        "one_by_one_runtime": {
            "max_retries": int(args.max_retries),
            "retry_wait_sec": float(args.retry_wait_sec),
            "inter_shot_wait_sec": float(args.inter_shot_wait),
        },
    }
    write_json(experiment_dir / "run_manifest.json", run_manifest)
    phone_self_check_reports: list[dict[str, Any]] = []

    print(f"[INFO] experiment dir: {experiment_dir}")
    if not args.prepare_only:
        print(
            "[INFO] one-by-one mode: enabled "
            f"(max_retries={int(args.max_retries)}, retry_wait_sec={float(args.retry_wait_sec)}, "
            f"inter_shot_wait_sec={float(args.inter_shot_wait)})"
        )

    for profile_id in selected_profile_ids:
        profile, profile_load_downgrades = resolve_model_profile(
            profile_id=profile_id,
            catalog=profile_catalog,
            catalog_issues=profile_catalog_issues,
        )
        if video_model:
            profile = apply_video_model_profile_defaults(profile, video_model)

        profile_dir = experiment_dir / profile_id if len(selected_profile_ids) > 1 else experiment_dir
        profile_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            profile_dir / "profile_manifest.json",
            {
                "profile_id": profile_id,
                "resolved_profile_id": str(profile.get("profile_id", profile_id)),
                "provider": str(profile.get("provider", "")),
                "model": str(profile.get("model", "")),
                "video_model": video_model or "",
                "profile_load_downgrades": profile_load_downgrades,
                "character_lock_profiles_loaded": len(character_lock_catalog),
                "shots": [s.shot_id for s in selected_shots],
                "mode": "prepare_only" if args.prepare_only else "api_generate",
                "created_at": datetime.now().isoformat(),
            },
        )

        print(f"[INFO] profile: {profile_id} -> {profile_dir}")
        provider = str(profile.get("provider", "")).strip().lower()
        api_key = ""
        if not args.prepare_only:
            try:
                api_key = require_api_key(provider)
            except RuntimeError as exc:
                print(f"[ERROR] {exc}", file=sys.stderr)
                return 1

        for shot in selected_shots:
            shot_dir = profile_dir / shot.shot_id
            try:
                record_path = record_file_map.get(shot.shot_id)
                record_data: dict[str, Any] | None = None

                if record_path is not None:
                    try:
                        record_data = read_json(record_path)
                    except Exception as exc:
                        raise RuntimeError(f"record 解析失败 ({record_path}): {exc}") from exc

                    shot_dir, payload_preview = prepare_one_shot_from_record(
                        shot_id=shot.shot_id,
                        record=record_data,
                        profile=profile,
                        profile_load_downgrades=profile_load_downgrades,
                        character_lock_catalog=character_lock_catalog,
                        character_lock_catalog_issues=character_lock_catalog_issues,
                        duration_overrides=duration_overrides,
                        duration_buffer_sec=float(args.duration_buffer_sec),
                        image_input_map=image_input_map,
                        image_input_map_path=image_input_map_path,
                        cli_image_url=str(args.image_url or "").strip(),
                        cli_last_image_url=str(args.last_image_url or "").strip(),
                        keyframe_prompts_root=keyframe_prompts_root,
                        project_root=project_root,
                        experiment_dir=profile_dir,
                        generate_audio=generate_audio_enabled,
                        enable_subtitle_hint=enable_subtitle_hint,
                        execution_overlays=execution_overlays,
                        write_pending=args.prepare_only,
                    )
                else:
                    print(
                        f"[WARN] {shot.shot_id} 未找到 record，回退到 legacy prompt。",
                        file=sys.stderr,
                    )
                    shot_dir, payload_preview = prepare_one_shot_legacy(
                        shot=shot,
                        experiment_dir=profile_dir,
                        generate_audio=generate_audio_enabled,
                        duration_buffer_sec=float(args.duration_buffer_sec),
                        write_pending=args.prepare_only,
                    )

                repair_selected = parse_shot_id_set(args.phone_audio_repair_shots)
                manual_repair_requested_for_shot = bool(repair_selected) and (
                    "ALL" in repair_selected or shot.shot_id.upper() in repair_selected
                )
                initial_self_check = write_phone_lipsync_self_check(
                    shot_id=shot.shot_id,
                    shot_dir=shot_dir,
                    record=record_data or {},
                    profile=profile,
                    payload_preview=payload_preview,
                    output_path=None,
                    auto_repair_enabled=bool(args.auto_phone_audio_repair),
                    manual_repair_requested=manual_repair_requested_for_shot,
                )
                auto_repair_requested_for_shot = bool(
                    args.auto_phone_audio_repair and initial_self_check.get("repair_recommended")
                )
                repair_requested_for_shot = bool(
                    manual_repair_requested_for_shot or auto_repair_requested_for_shot
                )
                write_phone_lipsync_review_hint(
                    shot_id=shot.shot_id,
                    shot_dir=shot_dir,
                    record=record_data or {},
                    repair_requested=repair_requested_for_shot,
                )

                if args.prepare_only:
                    if initial_self_check.get("phone_remote_listener_candidate"):
                        phone_self_check_reports.append(
                            {
                                "profile_id": profile_id,
                                "shot_id": shot.shot_id,
                                "report_path": str(shot_dir / "phone_lipsync_self_check.json"),
                                "repair_recommended": bool(initial_self_check.get("repair_recommended")),
                                "repair_will_run": bool(initial_self_check.get("repair_will_run")),
                                "repair_reason": str(initial_self_check.get("repair_reason") or ""),
                            }
                        )
                    if repair_requested_for_shot and is_phone_remote_listener_record(record_data or {}):
                        write_phone_audio_repair_artifacts(
                            shot_id=shot.shot_id,
                            shot_dir=shot_dir,
                            record=record_data or {},
                            profile=profile,
                            payload_preview=payload_preview,
                            reason=str(args.phone_audio_repair_reason or "").strip()
                            or str(initial_self_check.get("repair_reason") or "").strip()
                            or "phone_lipsync_self_check_repair",
                            prepare_only=True,
                        )
                        print(
                            f"[{shot.shot_id}] prepared phone audio repair artifacts -> "
                            f"{shot_dir / 'phone_audio_repair'}"
                        )
                    elif repair_requested_for_shot:
                        print(
                            f"[WARN] {shot.shot_id} selected for phone audio repair, "
                            "but record does not look like a phone remote-listener shot; skipped.",
                            file=sys.stderr,
                        )
                    continue

                assert_provider_payload(payload_preview, profile, shot.shot_id)

                narration_candidate_mode = bool(
                    args.auto_narration_candidates
                    and is_narration_only_model_audio_record(
                        record=record_data or {},
                        payload_preview=payload_preview,
                        profile=profile,
                    )
                )
                if narration_candidate_mode:
                    run_narration_candidate_loop(
                        provider=provider,
                        api_key=api_key,
                        shot_id=shot.shot_id,
                        shot_dir=shot_dir,
                        record=record_data or {},
                        profile=profile,
                        payload=payload_preview,
                        poll_interval_sec=args.poll_interval,
                        timeout_sec=args.timeout,
                        max_retries=args.max_retries,
                        retry_wait_sec=args.retry_wait_sec,
                        candidate_attempts=int(args.narration_candidate_attempts),
                    )
                else:
                    run_one_shot_payload(
                        provider=provider,
                        api_key=api_key,
                        shot_id=shot.shot_id,
                        shot_dir=shot_dir,
                        payload=payload_preview,
                        poll_interval_sec=args.poll_interval,
                        timeout_sec=args.timeout,
                        max_retries=args.max_retries,
                        retry_wait_sec=args.retry_wait_sec,
                    )
                final_self_check = write_phone_lipsync_self_check(
                    shot_id=shot.shot_id,
                    shot_dir=shot_dir,
                    record=record_data or {},
                    profile=profile,
                    payload_preview=payload_preview,
                    output_path=shot_dir / "output.mp4",
                    auto_repair_enabled=bool(args.auto_phone_audio_repair),
                    manual_repair_requested=manual_repair_requested_for_shot,
                )
                if final_self_check.get("phone_remote_listener_candidate"):
                    phone_self_check_reports.append(
                        {
                            "profile_id": profile_id,
                            "shot_id": shot.shot_id,
                            "report_path": str(shot_dir / "phone_lipsync_self_check.json"),
                            "repair_recommended": bool(final_self_check.get("repair_recommended")),
                            "repair_will_run": bool(final_self_check.get("repair_will_run")),
                            "repair_reason": str(final_self_check.get("repair_reason") or ""),
                        }
                    )
                auto_repair_requested_for_shot = bool(
                    args.auto_phone_audio_repair and final_self_check.get("repair_recommended")
                )
                repair_requested_for_shot = bool(
                    manual_repair_requested_for_shot or auto_repair_requested_for_shot
                )
                if repair_requested_for_shot and not is_phone_remote_listener_record(record_data or {}):
                    print(
                        f"[WARN] {shot.shot_id} selected for phone audio repair, "
                        "but record does not look like a phone remote-listener shot; skipped.",
                        file=sys.stderr,
                    )
                if repair_requested_for_shot and is_phone_remote_listener_record(record_data or {}):
                    run_phone_audio_repair(
                        provider=provider,
                        api_key=api_key,
                        shot_id=shot.shot_id,
                        shot_dir=shot_dir,
                        record=record_data or {},
                        profile=profile,
                        payload_preview=payload_preview,
                        poll_interval_sec=args.poll_interval,
                        timeout_sec=args.timeout,
                        max_retries=args.max_retries,
                        retry_wait_sec=args.retry_wait_sec,
                        reason=str(args.phone_audio_repair_reason or "").strip()
                        or str(final_self_check.get("repair_reason") or "").strip()
                        or "phone_lipsync_self_check_repair",
                    )
                if float(args.inter_shot_wait) > 0:
                    time.sleep(float(args.inter_shot_wait))
            except Exception as exc:
                err_file = shot_dir / "error.txt"
                err_file.parent.mkdir(parents=True, exist_ok=True)
                err_file.write_text(str(exc) + "\n", encoding="utf-8")
                print(f"[ERROR] {profile_id}/{shot.shot_id}: {exc}", file=sys.stderr)
                if (not args.prepare_only) and float(args.inter_shot_wait) > 0:
                    time.sleep(float(args.inter_shot_wait))

    if phone_self_check_reports:
        write_json(
            experiment_dir / "phone_lipsync_self_check_summary.json",
            {
                "created_at": datetime.now().isoformat(),
                "auto_phone_audio_repair": bool(args.auto_phone_audio_repair),
                "reports": phone_self_check_reports,
            },
        )

    print("[INFO] finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
