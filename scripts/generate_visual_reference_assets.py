#!/usr/bin/env python3
"""Generate reusable scene and prop reference assets for keyframe/I2V prompts.

The script reads scene_detail.txt and shot records, writes per-asset prompts and
a manifest, and can optionally call Grok image generation to create the images.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
XAI_IMAGE_GENERATIONS_URL = "https://api.x.ai/v1/images/generations"
DEFAULT_XAI_MODEL = "grok-imagine-image"
DEFAULT_SIZE = "1024x1536"
DEFAULT_OUTPUT_FORMAT = "jpeg"
DEFAULT_EPISODE_ROOT = (
    "novel/ginza_night/GinzaNight_EP06_new_flow_openai_v1/"
    "06_当前项目的视觉与AI执行层文档"
)
DEFAULT_OUTPUT_ROOT = "novel/ginza_night/assets/visual_refs"

PROP_ALIAS_OVERRIDES = {
    "AYAKA_LIGHT_BLUE_SCARF": "AYAKA_LIGHT_BLUE_SILK_SCARF_01",
    "AYAKA_COSMETIC_BOX": "AYAKA_COSMETIC_BOX_01",
    "AYAKA_OLD_HANDBAG": "AYAKA_OLD_HANDBAG_01",
    "KENICHI_SMARTPHONE": "KENICHI_SMARTPHONE_01",
    "MISAKI_PAPER_BAG": "MISAKI_PAPER_BAG_01",
    "SAKURA_SCHOOL_PHOTO": "SAKURA_PHOTO_01",
}


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


def safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {"raw_text": response.text}
    return data if isinstance(data, dict) else {"raw": data}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_repo_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def resolve_xai_api_key(cli_value: str) -> str:
    key = cli_value.strip() or os.getenv("XAI_API_KEY", "").strip()
    if key and key != "your_xai_api_key_here":
        return key
    raise RuntimeError(
        "XAI_API_KEY 未配置。请在 .env 填入真实 key，"
        "或通过 --xai-api-key 显式传入。"
    )


def extension_for_format(output_format: str) -> str:
    normalized = output_format.strip().lower()
    if normalized == "jpeg":
        return "jpg"
    if normalized in {"jpg", "png", "webp"}:
        return normalized
    raise RuntimeError(f"不支持的 output_format: {output_format}")


def sanitize_filename(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", str(value or "").strip())
    text = re.sub(r"\s+", "_", text).strip("._ ")
    return text or fallback


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
            scenes.append({"scene_id": sanitize_filename(name, f"scene_{idx + 1:02d}"), "name": name, "description": description})
    return scenes


def iter_record_paths(records_dir: Path) -> list[Path]:
    if not records_dir.exists():
        raise FileNotFoundError(f"records dir not found: {records_dir}")
    return sorted(records_dir.glob("*.json"))


def canonical_prop_id(prop_id: str, all_prop_ids: set[str]) -> str:
    if prop_id in PROP_ALIAS_OVERRIDES and PROP_ALIAS_OVERRIDES[prop_id] in all_prop_ids:
        return PROP_ALIAS_OVERRIDES[prop_id]
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
                if not isinstance(item, dict):
                    continue
                prop_id = str(item.get("prop_id") or "").strip()
                if prop_id:
                    raw_contracts.setdefault(prop_id, []).append(item)

    all_prop_ids = set(raw_profiles) | set(raw_contracts)
    props: dict[str, dict[str, Any]] = {}
    for prop_id in sorted(all_prop_ids):
        canonical = canonical_prop_id(prop_id, all_prop_ids)
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


def build_scene_prompt(scene: dict[str, str], extra_prompt: str) -> str:
    extra = f"\n补充要求：{extra_prompt.strip()}" if extra_prompt.strip() else ""
    return f"""根据下面的场景设定，生成一张可复用的 AI 短剧场景 reference image。

场景名：{scene["name"]}

场景设定：
{scene["description"].strip()}

硬性画面要求：
- 只生成空场景，不出现任何人物、人体局部、倒影人物、照片人物或背景人群。
- 竖屏 9:16，写实电影感，低饱和，真实光影，现代日本都市悬疑质感。
- 画面是稳定的 establishing reference plate，空间结构、墙面、地板、家具位置清晰可复用。
- 不要生成剧情动作，不要戏剧化烟雾、夸张霓虹、强烈镜头畸变或过度装饰。
- 画面内没有字幕、标题、镜头编号、水印、logo、说明文字、海报字。
- 如果出现环境文字，只能是极小且自然的背景标识，不要成为画面主体。
- 保持材质清楚：木纹、织物、皮革、玻璃、墙面各自可辨。
- 不要拼贴、不要分屏、不要多格漫画、不要contact sheet。{extra}
"""


def prop_is_photo(prop_id: str, profile: dict[str, Any]) -> bool:
    combined = " ".join(
        str(profile.get(key) or "")
        for key in ("display_name", "structure", "material", "front_description", "back_description")
    )
    combined = f"{prop_id} {combined}".lower()
    return any(token in combined for token in ("photo", "照片", "相片"))


def extract_photo_side_description(profile: dict[str, Any], side: str, fallback: str) -> str:
    explicit_key = f"{side}_description"
    explicit = str(profile.get(explicit_key) or "").strip()
    if explicit:
        return explicit

    combined = "；".join(
        str(profile.get(key) or "").strip()
        for key in ("structure", "color", "display_name")
        if str(profile.get(key) or "").strip()
    )
    if side == "front":
        patterns = [
            r"正面[是为:]?([^；。]+)",
            r"照片正面[是为:]?([^；。]+)",
        ]
    else:
        patterns = [
            r"背面[是为:]?([^；。]+)",
            r"照片背面[是为:]?([^；。]+)",
        ]
    for pattern in patterns:
        match = re.search(pattern, combined)
        if match:
            return match.group(1).strip(" ，,：:")
    return fallback


def build_prop_prompt(prop: dict[str, Any], extra_prompt: str) -> str:
    profile = prop.get("profile", {}) if isinstance(prop.get("profile"), dict) else {}
    prop_id = str(prop.get("prop_id") or "").strip()
    display = str(profile.get("display_name") or prop_id).strip()
    contract_text = compact_prop_contracts(prop.get("contracts", []))
    fields = [
        ("数量", profile.get("count")),
        ("尺寸", profile.get("size")),
        ("颜色", profile.get("color")),
        ("材质", profile.get("material")),
        ("结构", profile.get("structure")),
        ("默认运动政策", profile.get("canonical_motion_policy")),
    ]
    field_text = "\n".join(f"- {label}: {value}" for label, value in fields if str(value or "").strip())
    if contract_text:
        field_text += f"\n- 镜头使用约束: {contract_text}"
    if prop.get("aliases"):
        field_text += f"\n- 同物 alias: {', '.join(prop['aliases'])}"
    extra = f"\n补充要求：{extra_prompt.strip()}" if extra_prompt.strip() else ""

    phone_rules = ""
    if any(token in prop_id.upper() for token in ("SMARTPHONE", "PHONE")) or "手机" in display:
        phone_rules = """
手机特殊要求：
- 本资产生成通用手机道具：屏幕完全黑屏或深色反光待机状态。
- 屏幕上不要出现任何可读文字、来电界面、联系人姓名、数字、图标、通知、聊天界面或照片。
- 手机保持轻薄直板轮廓，黑色机身和深色保护壳清晰可见。
"""

    photo_rules = ""
    if prop_is_photo(prop_id, profile):
        front = extract_photo_side_description(profile, "front", "按道具设定中的照片正面内容")
        back = extract_photo_side_description(profile, "back", "按道具设定中的照片背面内容")
        photo_rules = f"""
照片特殊要求：
- 本资产生成照片正面版本：单张照片正面朝向镜头，正面内容为：{front}
- 背面设定为：{back}
- 本图只展示正面，不要同时展示背面；如果后续需要背面 reference，应单独生成背面版本。
- 只允许这一张照片，不出现照片堆、散落照片、额外照片或拼贴对比图。
"""

    return f"""根据下面的道具设定，生成一张可复用的 AI 短剧道具 reference image。

道具 ID：{prop_id}
道具名：{display}

道具设定：
{field_text}
{photo_rules}
{phone_rules}
硬性画面要求：
- 画面中只出现这一个道具，不出现人物、手、身体局部、其他道具、包装盒堆叠或背景杂物。
- 道具居中，完整可见，形状、厚度、边缘、材质和颜色清晰。
- 使用干净中性浅灰背景或简单摄影台，写实产品摄影感，低饱和，自然柔和阴影。
- 严格遵守数量：只生成 1 个或 1 条或 1 张，除非设定明确写多个。
- 不要添加文字标签、logo、水印、说明文字、尺寸标尺、拼贴、多视角分屏。
- 不要把道具改成相近但不同的物品；不要增加随机花纹、屏幕内容或无关装饰。
- 竖屏 9:16，reference asset 用途，朴素、清楚、可复用。{extra}
"""


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
        for token in (
            "rate limit",
            "retry after",
            "temporarily unavailable",
            "connection reset",
            "timed out",
        )
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
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "aspect_ratio": aspect_ratio_from_size(size),
    }
    total = max(1, max_retries)
    last_result: dict[str, Any] = {}
    for attempt in range(1, total + 1):
        response = requests.post(
            XAI_IMAGE_GENERATIONS_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        result = safe_json(response)
        if response.status_code < 400:
            return result
        last_result = result
        retryable = is_retryable_error(response.status_code, json.dumps(result, ensure_ascii=False))
        if not retryable or attempt >= total:
            raise RuntimeError(f"Grok 生图失败: HTTP {response.status_code} - {result}")
        delay = retry_delay_seconds(result, default=min(60, 5 * attempt))
        print(
            f"[WARN] Grok HTTP {response.status_code}; retry {attempt}/{total} after {delay}s",
            file=sys.stderr,
        )
        time.sleep(delay)
    raise RuntimeError(f"Grok 生图失败: {last_result}")


def summarize_response(result: dict[str, Any]) -> dict[str, Any]:
    summary = dict(result)
    data = summary.get("data")
    if isinstance(data, list):
        compact = []
        for item in data:
            if not isinstance(item, dict):
                compact.append(item)
                continue
            safe_item = dict(item)
            if "b64_json" in safe_item:
                safe_item["b64_json"] = f"<base64 omitted; {len(str(safe_item.get('b64_json') or ''))} chars>"
            compact.append(safe_item)
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
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


def selected_values(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def write_prompt(path: Path, prompt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt, encoding="utf-8")


def build_asset_item(
    *,
    asset_type: str,
    asset_id: str,
    name: str,
    prompt: str,
    out_path: Path,
    prompt_path: Path,
    source: dict[str, Any],
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": asset_type,
        "id": asset_id,
        "name": name,
        "aliases": aliases or [],
        "_prompt": prompt,
        "prompt_path": str(prompt_path),
        "output_path": str(out_path),
        "prompt_chars": len(prompt),
        "source": source,
        "status": "pending",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Grok scene and prop reference assets from scene_detail.txt and records."
    )
    parser.add_argument("--episode-root", default=DEFAULT_EPISODE_ROOT)
    parser.add_argument("--scene-detail", default="", help="Override scene_detail.txt path.")
    parser.add_argument("--records-dir", default="", help="Override records dir path.")
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--asset-types", default="scenes,props", help="Comma-separated: scenes,props.")
    parser.add_argument("--scenes", default="", help="Comma-separated scene names/ids to include.")
    parser.add_argument("--props", default="", help="Comma-separated prop ids to include.")
    parser.add_argument("--model", default=DEFAULT_XAI_MODEL)
    parser.add_argument("--size", default=DEFAULT_SIZE)
    parser.add_argument("--output-format", default=DEFAULT_OUTPUT_FORMAT, choices=["jpeg", "jpg", "png", "webp"])
    parser.add_argument("--extra-scene-prompt", default="")
    parser.add_argument("--extra-prop-prompt", default="")
    parser.add_argument("--xai-api-key", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-retries", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(REPO_ROOT / ".env")

    episode_root = resolve_repo_path(args.episode_root)
    scene_detail = resolve_repo_path(args.scene_detail) if args.scene_detail.strip() else episode_root / "scene_detail.txt"
    records_dir = resolve_repo_path(args.records_dir) if args.records_dir.strip() else episode_root / "records"
    output_root = resolve_repo_path(args.output_root)
    output_ext = extension_for_format(args.output_format)
    asset_types = selected_values(args.asset_types.lower())
    selected_scenes = selected_values(args.scenes)
    selected_props = selected_values(args.props)

    api_key = "" if args.dry_run else resolve_xai_api_key(args.xai_api_key)
    manifest: dict[str, Any] = {
        "created_at": datetime.now().isoformat(),
        "mode": "dry_run" if args.dry_run else "api_generate",
        "provider": "grok",
        "model": args.model,
        "size": args.size,
        "output_format": args.output_format,
        "episode_root": str(episode_root),
        "scene_detail": str(scene_detail),
        "records_dir": str(records_dir),
        "output_root": str(output_root),
        "scenes": {},
        "props": {},
    }

    print(f"[INFO] output_root: {output_root}")
    print(f"[INFO] mode: {manifest['mode']}")
    print(f"[INFO] provider: grok ({args.model})")

    items: list[dict[str, Any]] = []
    if "scenes" in asset_types:
        for scene in parse_scene_detail(scene_detail):
            if selected_scenes and scene["name"] not in selected_scenes and scene["scene_id"] not in selected_scenes:
                continue
            filename = sanitize_filename(scene["name"], scene["scene_id"])
            out_path = output_root / "scenes" / f"{filename}.{output_ext}"
            prompt_path = out_path.with_suffix(".prompt.txt")
            prompt = build_scene_prompt(scene, args.extra_scene_prompt)
            item = build_asset_item(
                asset_type="scene",
                asset_id=scene["scene_id"],
                name=scene["name"],
                prompt=prompt,
                out_path=out_path,
                prompt_path=prompt_path,
                source={"scene_detail": str(scene_detail)},
            )
            item["description"] = scene["description"]
            items.append(item)

    if "props" in asset_types:
        for prop_id, prop in extract_props(records_dir).items():
            aliases = list(prop.get("aliases", []))
            include_ids = {prop_id, *aliases, *prop.get("source_prop_ids", [])}
            if selected_props and not (selected_props & include_ids):
                continue
            out_path = output_root / "props" / f"{sanitize_filename(prop_id, 'prop')}.{output_ext}"
            prompt_path = out_path.with_suffix(".prompt.txt")
            prompt = build_prop_prompt(prop, args.extra_prop_prompt)
            item = build_asset_item(
                asset_type="prop",
                asset_id=prop_id,
                name=str(prop.get("profile", {}).get("display_name") or prop_id),
                prompt=prompt,
                out_path=out_path,
                prompt_path=prompt_path,
                source={
                    "records_dir": str(records_dir),
                    "shots": prop.get("shots", []),
                    "source_prop_ids": prop.get("source_prop_ids", []),
                },
                aliases=aliases,
            )
            item["profile"] = prop.get("profile", {})
            items.append(item)

    failures = 0
    for item in items:
        out_path = Path(item["output_path"])
        prompt_path = Path(item["prompt_path"])
        prompt = str(item.pop("_prompt"))
        write_prompt(prompt_path, prompt)
        item["prompt_chars"] = len(prompt)

        if item["type"] == "scene":
            manifest["scenes"][item["name"]] = item
        else:
            manifest["props"][item["id"]] = item

        if out_path.exists() and not args.overwrite:
            item["status"] = "completed_existing"
            item["bytes"] = out_path.stat().st_size
            print(f"[SKIP] {item['type']} {item['id']}: exists")
            continue
        if args.dry_run:
            item["status"] = "dry_run"
            print(f"[DRY] {item['type']} {item['id']}: prompt written")
            continue

        try:
            print(f"[INFO] generating {item['type']} {item['id']} -> {out_path}")
            result = post_xai_image_generation(
                api_key=api_key,
                model=args.model,
                prompt=prompt,
                size=args.size,
                timeout=max(30, int(args.timeout)),
                max_retries=max(1, int(args.max_retries)),
            )
            image_bytes = extract_image_bytes(result)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(image_bytes)
            write_json(out_path.with_suffix(".grok_response.json"), summarize_response(result))
            item["status"] = "completed"
            item["bytes"] = len(image_bytes)
            print(f"[OK] {item['type']} {item['id']}: {out_path}")
        except Exception as exc:
            failures += 1
            item["status"] = "failed"
            item["error"] = str(exc)
            print(f"[ERROR] {item['type']} {item['id']}: {exc}", file=sys.stderr)

    manifest["status"] = "failed" if failures else "completed"
    manifest["counts"] = {
        "scenes": len(manifest["scenes"]),
        "props": len(manifest["props"]),
        "failed": failures,
    }
    write_json(output_root / "visual_reference_manifest.json", manifest)
    print(f"[INFO] manifest written: {output_root / 'visual_reference_manifest.json'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
