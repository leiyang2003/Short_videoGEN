#!/usr/bin/env python3
"""Run Seedance 2.0 (Atlas Cloud API) for SH02/SH05/SH10 test shots.

Outputs are stored at:
  test/<experiment_name>/<shot_id>/
or in multi-profile mode:
  test/<experiment_name>/<profile_id>/<shot_id>/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

API_BASE = "https://api.atlascloud.ai/api/v1/model"
GENERATE_URL = f"{API_BASE}/generateVideo"
POLL_URL_TMPL = f"{API_BASE}/prediction/{{prediction_id}}"
MODEL_NAME = "bytedance/seedance-2.0/text-to-video"
DEFAULT_RESOLUTION = "480p"
DEFAULT_RATIO = "9:16"
MIN_DURATION_SEC = 4  # Atlas Seedance duration lower bound
MAX_DURATION_SEC = 5  # User requirement: do not exceed 5 seconds
DEFAULT_PROFILE_ID = "seedance2_text2video_atlas"
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
    "古代中国西汉背景，竖屏短剧，写实电影感，低饱和，冷硬底色，泥土感，"
    "真实光影，角色一致性稳定，24fps，9:16"
)

NEGATIVE_PROMPT = (
    "卡通, 二次元, 游戏建模感, 塑料皮肤, 现代服装, 现代建筑, 现代道具, "
    "过度磨皮, 过饱和, 畸形手指, 手部崩坏, 面部扭曲, 多余肢体, 水印, logo, "
    "低清晰度, 严重噪点, 闪烁, 频繁跳帧, 穿帮"
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


def require_api_key() -> str:
    key = os.getenv("ATLASCLOUD_API_KEY", "").strip()
    if not key or key == "your_atlas_cloud_api_key_here":
        raise RuntimeError(
            "ATLASCLOUD_API_KEY 未配置。请在 .env 填入真实 key，"
            "或在环境变量中导出 ATLASCLOUD_API_KEY。"
        )
    return key


def safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        return response.json()
    except Exception:
        return {"raw_text": response.text}


def post_generate_payload(api_key: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    response = requests.post(GENERATE_URL, headers=headers, json=payload, timeout=60)
    result = safe_json(response)
    if response.status_code >= 400:
        raise RuntimeError(f"生成请求失败: HTTP {response.status_code} - {result}")
    try:
        prediction_id = result["data"]["id"]
    except Exception as exc:
        raise RuntimeError(f"未拿到 prediction id: {result}") from exc
    return prediction_id, {"payload": payload, "response": result}


def extract_output_url(result: dict[str, Any]) -> str:
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


def poll_until_done(
    api_key: str,
    prediction_id: str,
    poll_interval_sec: float,
    timeout_sec: int,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"}
    poll_url = POLL_URL_TMPL.format(prediction_id=prediction_id)
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


def download_file(url: str, out_file: Path) -> None:
    with requests.get(url, stream=True, timeout=180) as resp:
        if resp.status_code >= 400:
            raise RuntimeError(f"下载失败: HTTP {resp.status_code}, url={url}")
        with out_file.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def build_positive_constraints_from_avoid(avoid_terms: list[str]) -> str:
    base = (
        "质量与连续性约束：保持写实电影质感与真实皮肤纹理；人物脸部和手部解剖结构稳定；"
        "全程古代西汉语境，不出现现代服装、现代建筑或现代道具；画面干净，无水印与logo；"
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


def render_prompt_bundle(
    shot_id: str,
    record: dict[str, Any],
    profile: dict[str, Any],
    profile_load_downgrades: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt_render = record.get("prompt_render", {})
    scene_anchor = record.get("scene_anchor", {})
    shot_execution = record.get("shot_execution", {})
    continuity_rules = record.get("continuity_rules", {})
    character_anchor = record.get("character_anchor", {})

    prefix = str(prompt_render.get("positive_prefix") or GLOBAL_PREFIX).strip()
    core = str(prompt_render.get("shot_positive_core") or "").strip()
    dialogue_hint = str(prompt_render.get("dialogue_overlay_hint") or "").strip()
    subtitle_hint = str(prompt_render.get("subtitle_overlay_hint") or "").strip()

    camera_plan = shot_execution.get("camera_plan", {})
    camera_desc = "，".join(
        unique_keep_order(
            [
                str(camera_plan.get("shot_type", "")).strip(),
                str(camera_plan.get("movement", "")).strip(),
                str(camera_plan.get("framing_focus", "")).strip(),
            ]
        )
    )
    action_intent = str(shot_execution.get("action_intent", "")).strip()
    emotion_intent = str(shot_execution.get("emotion_intent", "")).strip()

    must_elements = ensure_list_str(scene_anchor.get("must_have_elements"))
    props = ensure_list_str(scene_anchor.get("prop_must_visible"))
    continuity_items = (
        ensure_list_str(continuity_rules.get("character_state_transition"))
        + ensure_list_str(continuity_rules.get("scene_transition"))
        + ensure_list_str(continuity_rules.get("prop_continuity"))
    )

    character_nodes = collect_character_nodes(character_anchor)
    forbidden_drift: list[str] = []
    for char in character_nodes:
        forbidden_drift.extend(ensure_list_str(char.get("forbidden_drift")))
    forbidden_drift = unique_keep_order(forbidden_drift)
    avoid_terms = unique_keep_order(
        ensure_list_str(prompt_render.get("negative_prompt")) + forbidden_drift
    )
    character_lock_phrases = build_character_lock_phrases(character_anchor)

    parts: list[str] = [prefix]
    if core:
        parts.append(core)
    if character_lock_phrases:
        parts.append(f"角色容貌服饰锁定：{'；'.join(character_lock_phrases)}")
    if camera_desc:
        parts.append(f"镜头执行：{camera_desc}")
    if action_intent:
        parts.append(f"动作意图：{action_intent}")
    if emotion_intent:
        parts.append(f"情绪意图：{emotion_intent}")
    if must_elements:
        parts.append(f"场景必须出现：{'、'.join(must_elements)}")
    if props:
        parts.append(f"关键道具可见：{'、'.join(props)}")
    if dialogue_hint:
        parts.append(dialogue_hint)
    if subtitle_hint:
        parts.append(subtitle_hint)
    if continuity_items:
        parts.append(f"连续性要求：{'；'.join(unique_keep_order(continuity_items))}")

    supports_negative = bool(profile.get("supports_negative_prompt"))
    downgrades: list[dict[str, Any]] = list(profile_load_downgrades)
    negative_prompt_text = ""
    if supports_negative:
        negative_prompt_text = ", ".join(avoid_terms)
    else:
        parts.append(build_positive_constraints_from_avoid(avoid_terms))
        if avoid_terms:
            downgrades.append(
                {
                    "type": "no_negative_field",
                    "detail": "avoid terms merged into positive constraints",
                }
            )

    prompt_text = "；".join([p for p in parts if p]).strip("；").strip()
    record_id = f"{record.get('record_header', {}).get('episode_id', 'EPXX')}_{shot_id}"

    mapping_summary = {
        "must": "full",
        "prefer": "full",
        "avoid": "full" if supports_negative else "downgraded_to_positive_constraints",
        "dialogue": "full",
        "continuity": "full",
    }

    render_report = {
        "record_id": record_id,
        "model_profile_id": str(profile.get("profile_id", "")).strip() or DEFAULT_PROFILE_ID,
        "mapping_summary": mapping_summary,
        "downgrades": downgrades,
        "requires_manual_review": (not supports_negative) or bool(downgrades),
        "generated_at": datetime.now().isoformat(),
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
    downgrades: list[dict[str, Any]],
) -> int:
    global_settings = record.get("global_settings", {})
    raw = global_settings.get("duration_sec")
    if isinstance(raw, int):
        requested = raw
    else:
        requested = estimate_duration_seconds(prompt_text)

    profile_min = int(profile.get("duration_min_sec", MIN_DURATION_SEC))
    profile_max = int(profile.get("duration_max_sec", MAX_DURATION_SEC))
    low = max(MIN_DURATION_SEC, profile_min)
    high = min(MAX_DURATION_SEC, profile_max)
    if high < low:
        high = low
    selected = clamp_int(requested, low, high)
    if selected != requested:
        downgrades.append(
            {
                "type": "duration_clamped",
                "detail": f"requested={requested}, selected={selected}, range=[{low},{high}]",
            }
        )
    return selected


def build_payload_preview(
    profile: dict[str, Any],
    prompt_text: str,
    negative_prompt_text: str,
    duration: int,
    resolution: str,
    ratio: str,
    generate_audio: bool,
) -> dict[str, Any]:
    payload_fields = profile.get("payload_fields", {})
    pos_field = str(payload_fields.get("positive_prompt_field") or "prompt")
    neg_field = payload_fields.get("negative_prompt_field")
    duration_field = str(payload_fields.get("duration_field") or "duration")
    resolution_field = str(payload_fields.get("resolution_field") or "resolution")
    ratio_field = str(payload_fields.get("ratio_field") or "ratio")
    audio_field = payload_fields.get("audio_field")

    payload: dict[str, Any] = {
        "model": str(profile.get("model") or MODEL_NAME),
        pos_field: prompt_text,
        duration_field: duration,
        resolution_field: resolution,
        ratio_field: ratio,
    }
    if audio_field:
        supports_audio = bool(profile.get("supports_audio_generation", True))
        payload[str(audio_field)] = bool(generate_audio and supports_audio)
    if isinstance(neg_field, str) and neg_field.strip() and negative_prompt_text.strip():
        payload[neg_field.strip()] = negative_prompt_text

    if str(profile.get("provider", "")).strip().lower() == "atlascloud":
        payload["web_search"] = False
        payload["watermark"] = False
        payload["return_last_frame"] = False

    return payload


def prepare_one_shot_from_record(
    shot_id: str,
    record: dict[str, Any],
    profile: dict[str, Any],
    profile_load_downgrades: list[dict[str, Any]],
    character_lock_catalog: dict[str, dict[str, Any]],
    character_lock_catalog_issues: list[dict[str, Any]],
    experiment_dir: Path,
    generate_audio: bool,
    write_pending: bool,
) -> tuple[Path, dict[str, Any]]:
    shot_dir = experiment_dir / shot_id
    shot_dir.mkdir(parents=True, exist_ok=True)
    hydrated_record, lock_downgrades = hydrate_record_with_character_locks(
        record=record,
        lock_catalog=character_lock_catalog,
        lock_catalog_issues=character_lock_catalog_issues,
    )
    combined_downgrades = list(profile_load_downgrades) + list(lock_downgrades)

    bundle = render_prompt_bundle(
        shot_id=shot_id,
        record=hydrated_record,
        profile=profile,
        profile_load_downgrades=combined_downgrades,
    )
    prompt_text = str(bundle["prompt_text"])
    negative_prompt_text = str(bundle["negative_prompt_text"])
    render_report = dict(bundle["render_report"])
    downgrades = list(render_report.get("downgrades", []))

    global_settings = hydrated_record.get("global_settings", {})
    supported_ratios = ensure_list_str(profile.get("supported_ratios"))
    supported_resolutions = ensure_list_str(profile.get("supported_resolutions"))

    ratio = select_ratio(
        desired=str(global_settings.get("ratio", DEFAULT_RATIO)),
        supported=supported_ratios,
        downgrades=downgrades,
    )
    resolution = select_resolution(
        desired=str(global_settings.get("resolution", DEFAULT_RESOLUTION)),
        supported=supported_resolutions,
        downgrades=downgrades,
    )
    duration = resolve_duration(
        record=hydrated_record,
        profile=profile,
        prompt_text=prompt_text,
        downgrades=downgrades,
    )
    payload_preview = build_payload_preview(
        profile=profile,
        prompt_text=prompt_text,
        negative_prompt_text=negative_prompt_text,
        duration=duration,
        resolution=resolution,
        ratio=ratio,
        generate_audio=generate_audio,
    )

    render_report["downgrades"] = downgrades
    render_report["requires_manual_review"] = bool(downgrades) or (
        not bool(profile.get("supports_negative_prompt"))
    )
    render_report["resolved_generation"] = {
        "duration_sec": duration,
        "resolution": resolution,
        "ratio": ratio,
        "generate_audio": bool(payload_preview.get("generate_audio", generate_audio)),
    }

    (shot_dir / "prompt.final.txt").write_text(prompt_text + "\n", encoding="utf-8")
    (shot_dir / "prompt.txt").write_text(prompt_text + "\n", encoding="utf-8")
    (shot_dir / "negative_prompt.txt").write_text(
        (negative_prompt_text + "\n") if negative_prompt_text else "",
        encoding="utf-8",
    )
    (shot_dir / "duration_used.txt").write_text(f"{duration}\n", encoding="utf-8")
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
    write_pending: bool,
) -> tuple[Path, dict[str, Any]]:
    if not shot.prompt.strip():
        raise RuntimeError(
            f"{shot.shot_id} 未找到 record，且脚本内无该镜头的 legacy prompt，无法继续。"
        )

    shot_dir = experiment_dir / shot.shot_id
    shot_dir.mkdir(parents=True, exist_ok=True)

    full_prompt = f"{GLOBAL_PREFIX}，{shot.prompt}"
    shot_duration = estimate_duration_seconds(shot.prompt)
    (shot_dir / "prompt.txt").write_text(full_prompt + "\n", encoding="utf-8")
    (shot_dir / "prompt.final.txt").write_text(full_prompt + "\n", encoding="utf-8")
    (shot_dir / "negative_prompt.txt").write_text(NEGATIVE_PROMPT + "\n", encoding="utf-8")
    (shot_dir / "duration_used.txt").write_text(f"{shot_duration}\n", encoding="utf-8")

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
    api_key: str,
    shot_id: str,
    shot_dir: Path,
    payload: dict[str, Any],
    poll_interval_sec: float,
    timeout_sec: int,
) -> None:
    prediction_id, req_meta = post_generate_payload(api_key=api_key, payload=payload)
    write_json(shot_dir / "generate_request_response.json", req_meta)

    final_result = poll_until_done(
        api_key=api_key,
        prediction_id=prediction_id,
        poll_interval_sec=poll_interval_sec,
        timeout_sec=timeout_sec,
    )
    write_json(shot_dir / "final_status.json", final_result)

    video_url = extract_output_url(final_result)
    (shot_dir / "output_url.txt").write_text(video_url + "\n", encoding="utf-8")

    output_file = shot_dir / "output.mp4"
    download_file(video_url, output_file)
    pending = shot_dir / "output.pending.txt"
    if pending.exists():
        pending.unlink()
    print(f"[{shot_id}] done -> {output_file}")


def assert_atlas_payload(payload: dict[str, Any], shot_id: str) -> None:
    required = ["model", "prompt", "duration", "resolution", "ratio"]
    missing = [k for k in required if k not in payload]
    if missing:
        raise RuntimeError(
            f"{shot_id} payload 缺少 Atlas 必填字段: {', '.join(missing)}。"
            "请在 API 模式使用 atlascloud profile。"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Atlas Cloud Seedance 2.0 API for SH02/SH05/SH10 test shots."
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
        "--no-audio",
        action="store_true",
        help="Disable generate_audio.",
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
        "--character-lock-profiles",
        default=DEFAULT_CHARACTER_LOCK_FILE,
        help="Character lock profile catalog json file.",
    )
    parser.add_argument(
        "--profile-ids",
        default="",
        help=(
            "Comma-separated profile ids for batch prepare-only runs, "
            "e.g. seedance2_text2video_atlas,generic_t2v_with_negative_example"
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

    try:
        selected_shots = select_shots(args.shots)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    selected_profile_ids = parse_profile_ids(args.profile_ids, args.model_profile_id)
    if not args.prepare_only and len(selected_profile_ids) > 1:
        print("[ERROR] API 模式暂不支持多 profile 并行。请去掉 --profile-ids 或使用 --prepare-only。", file=sys.stderr)
        return 1

    api_key = ""
    if not args.prepare_only:
        try:
            api_key = require_api_key()
        except RuntimeError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
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

    run_manifest = {
        "created_at": datetime.now().isoformat(),
        "mode": "prepare_only" if args.prepare_only else "api_generate",
        "shots": [s.shot_id for s in selected_shots],
        "records_dir": str(records_dir),
        "model_profile_file": str(profile_file),
        "character_lock_profile_file": str(character_lock_profile_file),
        "selected_profile_ids": selected_profile_ids,
        "profile_catalog_issues": profile_catalog_issues,
        "character_lock_profile_catalog_issues": character_lock_catalog_issues,
        "multi_profile_layout": len(selected_profile_ids) > 1,
        "api_provider": "atlascloud",
        "note": "API mode uses rendered payload.preview.json as single source of truth.",
    }
    write_json(experiment_dir / "run_manifest.json", run_manifest)

    print(f"[INFO] experiment dir: {experiment_dir}")

    for profile_id in selected_profile_ids:
        profile, profile_load_downgrades = resolve_model_profile(
            profile_id=profile_id,
            catalog=profile_catalog,
            catalog_issues=profile_catalog_issues,
        )

        profile_dir = experiment_dir / profile_id if len(selected_profile_ids) > 1 else experiment_dir
        profile_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            profile_dir / "profile_manifest.json",
            {
                "profile_id": profile_id,
                "resolved_profile_id": str(profile.get("profile_id", profile_id)),
                "provider": str(profile.get("provider", "")),
                "model": str(profile.get("model", "")),
                "profile_load_downgrades": profile_load_downgrades,
                "character_lock_profiles_loaded": len(character_lock_catalog),
                "shots": [s.shot_id for s in selected_shots],
                "mode": "prepare_only" if args.prepare_only else "api_generate",
                "created_at": datetime.now().isoformat(),
            },
        )

        print(f"[INFO] profile: {profile_id} -> {profile_dir}")

        for shot in selected_shots:
            shot_dir = profile_dir / shot.shot_id
            try:
                record_path = record_file_map.get(shot.shot_id)

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
                        experiment_dir=profile_dir,
                        generate_audio=not args.no_audio,
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
                        generate_audio=not args.no_audio,
                        write_pending=args.prepare_only,
                    )

                if args.prepare_only:
                    continue

                provider = str(profile.get("provider", "")).strip().lower()
                if provider != "atlascloud":
                    raise RuntimeError(
                        f"API 模式仅支持 atlascloud profile，当前 profile={profile_id}, provider={provider or 'unknown'}"
                    )
                assert_atlas_payload(payload_preview, shot.shot_id)

                run_one_shot_payload(
                    api_key=api_key,
                    shot_id=shot.shot_id,
                    shot_dir=shot_dir,
                    payload=payload_preview,
                    poll_interval_sec=args.poll_interval,
                    timeout_sec=args.timeout,
                )
            except Exception as exc:
                err_file = shot_dir / "error.txt"
                err_file.parent.mkdir(parents=True, exist_ok=True)
                err_file.write_text(str(exc) + "\n", encoding="utf-8")
                print(f"[ERROR] {profile_id}/{shot.shot_id}: {exc}", file=sys.stderr)

    print("[INFO] finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
