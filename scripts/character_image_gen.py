#!/usr/bin/env python3
"""Generate character reference portraits from character profile markdown files.

Profiles are expected at:
  novel/<novel_name>/assets/characters/*.profile.md

For each profile, the script creates a single-person vertical portrait and saves
it next to the profile as <CHARACTER_ID>.jpg by default.
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
import visual_asset_core as vac


REPO_ROOT = Path(__file__).resolve().parents[1]
ATLAS_GENERATE_IMAGE_URL = "https://api.atlascloud.ai/api/v1/model/generateImage"
ATLAS_POLL_URL_TMPL = "https://api.atlascloud.ai/api/v1/model/prediction/{prediction_id}"
OPENAI_IMAGE_GENERATIONS_URL = "https://api.openai.com/v1/images/generations"
XAI_IMAGE_GENERATIONS_URL = "https://api.x.ai/v1/images/generations"
XAI_IMAGE_EDITS_URL = "https://api.x.ai/v1/images/edits"
DEFAULT_IMAGE_MODEL = "openai"
DEFAULT_MODEL = "gpt-image-1.5"
DEFAULT_ATLAS_MODEL = "openai/gpt-image-2"
DEFAULT_XAI_MODEL = "grok-imagine-image"
DEFAULT_SIZE = "1024x1536"
DEFAULT_QUALITY = "high"
DEFAULT_OUTPUT_FORMAT = "jpeg"
DEFAULT_BACKGROUND = "opaque"


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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_repo_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def resolve_openai_api_key(cli_value: str) -> str:
    key = cli_value.strip() or os.getenv("OPENAI_API_KEY", "").strip()
    if key and key != "your_openai_api_key_here":
        return key
    raise RuntimeError(
        "OPENAI_API_KEY 未配置。请在 .env 填入真实 key，"
        "或通过 --openai-api-key 显式传入。"
    )


def resolve_atlas_api_key(cli_value: str) -> str:
    key = cli_value.strip() or os.getenv("ATLASCLOUD_API_KEY", "").strip()
    if key and key != "your_atlas_cloud_api_key_here":
        return key
    raise RuntimeError(
        "ATLASCLOUD_API_KEY 未配置。请在 .env 填入真实 key，"
        "或通过 --atlas-api-key 显式传入。"
    )


def resolve_xai_api_key(cli_value: str) -> str:
    key = cli_value.strip() or os.getenv("XAI_API_KEY", "").strip()
    if key and key != "your_xai_api_key_here":
        return key
    raise RuntimeError(
        "XAI_API_KEY 未配置。请在 .env 填入真实 key，"
        "或通过 --xai-api-key 显式传入。"
    )


def normalize_image_model(value: str) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "openai": "openai",
        "atlas": "atlas-openai",
        "atlas_openai": "atlas-openai",
        "atlas-openai": "atlas-openai",
        "grok": "grok",
        "xai": "grok",
    }
    if raw in aliases:
        return aliases[raw]
    raise ValueError(f"未知 IMAGE_MODEL: {value!r}。可选: openai, atlas-openai, grok")


def resolve_image_model(cli_value: str) -> str:
    return normalize_image_model(
        cli_value.strip() or os.getenv("IMAGE_MODEL", "").strip() or DEFAULT_IMAGE_MODEL
    )


def default_model_for_image_model(image_model: str) -> str:
    if image_model == "atlas-openai":
        return DEFAULT_ATLAS_MODEL
    if image_model == "grok":
        return DEFAULT_XAI_MODEL
    return DEFAULT_MODEL


def resolve_characters_dir(args: argparse.Namespace) -> Path:
    if args.characters_dir.strip():
        return resolve_repo_path(args.characters_dir)

    novel_name = args.novel.strip()
    if not novel_name:
        raise RuntimeError("请提供 --novel 小说目录名，或直接提供 --characters-dir。")
    novel_dir = REPO_ROOT / "novel" / novel_name

    candidates = [
        novel_dir / "assets" / "characters",
        novel_dir / "asset" / "characters",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def profile_id_from_path(path: Path) -> str:
    name = path.name
    if name.endswith(".profile.md"):
        return name[: -len(".profile.md")]
    return path.stem


def extract_character_name(profile_text: str, fallback: str) -> str:
    for raw_line in profile_text.splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            title = re.sub(r"\s*角色档案\s*$", "", title).strip()
            if title:
                return title
    match = re.search(r"角色叫([^，。,.\n]+)", profile_text)
    if match:
        return match.group(1).strip()
    return fallback


def selected_profile_ids(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def discover_profiles(characters_dir: Path, selected: set[str]) -> list[Path]:
    if not characters_dir.exists():
        raise RuntimeError(f"角色目录不存在: {characters_dir}")
    profiles = sorted(characters_dir.glob("*.profile.md"))
    if selected:
        filtered: list[Path] = []
        missing = set(selected)
        for path in profiles:
            character_id = profile_id_from_path(path)
            text = path.read_text(encoding="utf-8")
            character_name = extract_character_name(text, character_id)
            if character_id in selected or character_name in selected:
                filtered.append(path)
                missing.discard(character_id)
                missing.discard(character_name)
        if missing:
            raise RuntimeError(f"未找到指定角色 profile: {', '.join(sorted(missing))}")
        profiles = filtered
    if not profiles:
        raise RuntimeError(f"未找到 *.profile.md: {characters_dir}")
    return profiles


def extension_for_format(output_format: str) -> str:
    normalized = output_format.strip().lower()
    if normalized == "jpeg":
        return "jpg"
    if normalized in {"png", "webp"}:
        return normalized
    raise RuntimeError(f"不支持的 output_format: {output_format}")


def build_prompt(
    *,
    character_id: str,
    character_name: str,
    profile_text: str,
    extra_prompt: str,
) -> str:
    bible = vac.heuristic_character_bible(
        character_id=character_id,
        name=character_name,
        profile_text=profile_text,
        project_style=vac.infer_project_style(profile_text),
    )
    return vac.build_character_image_prompt(bible, extra_prompt)


def visual_bible_path_for_profile(profile_path: Path, character_id: str) -> Path:
    return profile_path.with_name(f"{character_id}.visual_bible.json")


def summarize_openai_response(result: dict[str, Any]) -> dict[str, Any]:
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
    elif isinstance(data, dict):
        safe_data = dict(data)
        outputs = safe_data.get("outputs")
        if isinstance(outputs, list):
            compact_outputs = []
            for item in outputs:
                if isinstance(item, dict):
                    safe_item = dict(item)
                    if "b64_json" in safe_item:
                        safe_item["b64_json"] = f"<base64 omitted; {len(str(safe_item.get('b64_json') or ''))} chars>"
                    compact_outputs.append(safe_item)
                elif isinstance(item, str) and len(item) > 500:
                    compact_outputs.append(f"<string omitted; {len(item)} chars>")
                else:
                    compact_outputs.append(item)
            safe_data["outputs"] = compact_outputs
        summary["data"] = safe_data
    return summary


def extract_image_bytes(result: dict[str, Any]) -> bytes:
    data = result.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"OpenAI 响应中没有图片 data: {result}")
    first = data[0]
    if not isinstance(first, dict):
        raise RuntimeError(f"OpenAI 图片 data 格式异常: {result}")

    b64 = str(first.get("b64_json") or "").strip()
    if b64:
        return base64.b64decode(b64)

    url = str(first.get("url") or "").strip()
    if url:
        response = requests.get(url, timeout=180)
        if response.status_code >= 400:
            raise RuntimeError(f"下载 OpenAI 图片失败: HTTP {response.status_code}, url={url}")
        return response.content

    raise RuntimeError(f"OpenAI 响应中没有 b64_json 或 url: {result}")


def retry_delay_seconds(result: dict[str, Any], default: int) -> int:
    message = json.dumps(result, ensure_ascii=False)
    match = re.search(r"retry after\s+(\d+)\s+seconds", message, re.IGNORECASE)
    if match:
        return max(1, int(match.group(1)))
    return max(1, default)


def parse_retry_after_seconds(message: str, default: int = 20) -> int:
    match = re.search(r"retry after\s+(\d+)\s+seconds", str(message), re.IGNORECASE)
    if match:
        return max(1, int(match.group(1)))
    return max(1, int(default))


def is_retryable_error(status_code: int, message: str) -> bool:
    if status_code in {408, 409, 429, 500, 502, 503, 504}:
        return True
    lowered = str(message).lower()
    return any(
        token in lowered
        for token in (
            "rate limit",
            "high demand",
            "retry after",
            "temporarily unavailable",
            "connection reset",
            "connection aborted",
            "timed out",
        )
    )


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
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
        "output_format": output_format,
        "background": background,
    }
    if output_format in {"jpeg", "webp"}:
        payload["output_compression"] = output_compression

    last_result: dict[str, Any] = {}
    total = max(1, max_retries)
    for attempt in range(1, total + 1):
        response = requests.post(
            OPENAI_IMAGE_GENERATIONS_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        result = safe_json(response)
        if response.status_code < 400:
            return result

        last_result = result
        retryable = response.status_code in {408, 409, 429, 500, 502, 503, 504}
        if not retryable or attempt >= total:
            raise RuntimeError(f"OpenAI 生图失败: HTTP {response.status_code} - {result}")
        delay = retry_delay_seconds(result, default=min(60, 5 * attempt))
        print(
            f"[WARN] OpenAI HTTP {response.status_code}; retry {attempt}/{total} after {delay}s",
            file=sys.stderr,
        )
        time.sleep(delay)

    raise RuntimeError(f"OpenAI 生图失败: {last_result}")


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

    last_result: dict[str, Any] = {}
    total = max(1, max_retries)
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


def encode_local_image_as_data_uri(path: Path) -> str:
    raw = path.read_bytes()
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


def post_xai_image_edit(
    *,
    api_key: str,
    model: str,
    prompt: str,
    image_ref: str,
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
        "image": {"url": image_ref},
        "aspect_ratio": aspect_ratio_from_size(size),
    }

    last_result: dict[str, Any] = {}
    total = max(1, max_retries)
    for attempt in range(1, total + 1):
        response = requests.post(
            XAI_IMAGE_EDITS_URL,
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
            raise RuntimeError(f"Grok image edit 失败: HTTP {response.status_code} - {result}")
        delay = retry_delay_seconds(result, default=min(60, 5 * attempt))
        print(
            f"[WARN] Grok edit HTTP {response.status_code}; retry {attempt}/{total} after {delay}s",
            file=sys.stderr,
        )
        time.sleep(delay)

    raise RuntimeError(f"Grok image edit 失败: {last_result}")


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


def post_atlas_image_generation(
    *,
    api_key: str,
    model: str,
    prompt: str,
    size: str,
    quality: str,
    output_format: str,
    timeout: int,
    max_retries: int,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload: dict[str, Any] = {
        "model": model,
        "enable_base64_output": True,
        "enable_sync_mode": False,
        "prompt": prompt,
        "quality": quality,
        "size": size,
        "output_format": output_format,
    }
    total = max(1, max_retries)
    last_error = ""
    for attempt in range(1, total + 1):
        try:
            response = requests.post(
                ATLAS_GENERATE_IMAGE_URL,
                headers=headers,
                json=payload,
                timeout=60,
            )
            result = safe_json(response)
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code} - {result}")
            prediction_id = str(result.get("data", {}).get("id") or "").strip()
            if not prediction_id:
                raise RuntimeError(f"未拿到 prediction id: {result}")

            poll_url = ATLAS_POLL_URL_TMPL.format(prediction_id=prediction_id)
            deadline = time.time() + max(60, timeout)
            while True:
                poll_response = requests.get(poll_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=60)
                poll_result = safe_json(poll_response)
                if poll_response.status_code >= 400:
                    raise RuntimeError(f"查询状态失败: HTTP {poll_response.status_code} - {poll_result}")
                status = str(poll_result.get("data", {}).get("status", "")).lower()
                if status in {"completed", "succeeded"}:
                    return poll_result
                if status == "failed":
                    raise RuntimeError(str(poll_result.get("data", {}).get("error") or "Generation failed"))
                if time.time() > deadline:
                    raise TimeoutError(f"轮询超时（>{timeout}s），最后状态: {status}, result={poll_result}")
                time.sleep(2)
        except Exception as exc:
            last_error = str(exc)
            if (not is_retryable_error(500, last_error)) or attempt >= total:
                break
            delay = parse_retry_after_seconds(last_error, default=min(60, 5 * attempt))
            print(
                f"[WARN] Atlas image attempt {attempt}/{total} failed, retry in {delay}s: {last_error}",
                file=sys.stderr,
            )
            time.sleep(delay)
    raise RuntimeError(f"Atlas 生图失败: {last_error or 'unknown error'}")


def extract_image_bytes_from_atlas(result: dict[str, Any]) -> bytes:
    data = result.get("data", {})
    outputs = data.get("outputs")
    if isinstance(outputs, list) and outputs:
        first = outputs[0]
        if isinstance(first, dict):
            b64 = str(first.get("b64_json") or "").strip()
            url = str(first.get("url") or "").strip()
            if b64:
                return base64.b64decode(b64)
            if url:
                response = requests.get(url, timeout=180)
                if response.status_code >= 400:
                    raise RuntimeError(f"下载 Atlas 图片失败: HTTP {response.status_code}, url={url}")
                return response.content
        if isinstance(first, str):
            if first.startswith("http://") or first.startswith("https://"):
                response = requests.get(first, timeout=180)
                if response.status_code >= 400:
                    raise RuntimeError(f"下载 Atlas 图片失败: HTTP {response.status_code}, url={first}")
                return response.content
            return base64.b64decode(first)
    output = str(data.get("output") or "").strip()
    if output.startswith("http://") or output.startswith("https://"):
        response = requests.get(output, timeout=180)
        if response.status_code >= 400:
            raise RuntimeError(f"下载 Atlas 图片失败: HTTP {response.status_code}, url={output}")
        return response.content
    if output:
        return base64.b64decode(output)
    raise RuntimeError(f"Atlas 响应中没有图片输出: {result}")


def write_generation_artifacts(
    *,
    out_path: Path,
    prompt: str,
    response_summary: dict[str, Any],
    manifest_item: dict[str, Any],
) -> None:
    out_path.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
    write_json(out_path.with_suffix(".openai_response.json"), response_summary)
    write_json(out_path.with_suffix(".manifest.json"), manifest_item)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate character reference images from novel/<name>/assets/characters/*.profile.md "
            "using IMAGE_MODEL-selected image API."
        )
    )
    parser.add_argument("--novel", default="", help="Novel folder name under novel/, e.g. ginza_night.")
    parser.add_argument(
        "--characters-dir",
        default="",
        help="Direct path to assets/characters. Overrides --novel.",
    )
    parser.add_argument(
        "--characters",
        default="",
        help="Comma-separated character IDs or names to generate. Empty means all profiles.",
    )
    parser.add_argument(
        "--image-model",
        default="",
        choices=["", "openai", "atlas-openai", "grok"],
        help="Macro image provider selector. Empty means IMAGE_MODEL env, then openai.",
    )
    parser.add_argument(
        "--model",
        default="",
        help=(
            "Provider-specific image model override. Defaults: "
            f"openai={DEFAULT_MODEL}, atlas-openai={DEFAULT_ATLAS_MODEL}, grok={DEFAULT_XAI_MODEL}."
        ),
    )
    parser.add_argument("--size", default=DEFAULT_SIZE, help=f"Image size, default {DEFAULT_SIZE}.")
    parser.add_argument(
        "--quality",
        default=DEFAULT_QUALITY,
        choices=["low", "medium", "high"],
        help=f"Image quality, default {DEFAULT_QUALITY}.",
    )
    parser.add_argument(
        "--output-format",
        default=DEFAULT_OUTPUT_FORMAT,
        choices=["jpeg", "png", "webp"],
        help=f"Output format, default {DEFAULT_OUTPUT_FORMAT}.",
    )
    parser.add_argument(
        "--background",
        default=DEFAULT_BACKGROUND,
        choices=["opaque", "transparent", "auto"],
        help=f"OpenAI background parameter, default {DEFAULT_BACKGROUND}. Prompt still asks for light gray.",
    )
    parser.add_argument(
        "--output-compression",
        type=int,
        default=92,
        help="JPEG/WebP output compression value passed to OpenAI, default 92.",
    )
    parser.add_argument(
        "--extra-prompt",
        default="",
        help="Optional extra prompt text appended to every character prompt.",
    )
    parser.add_argument("--openai-api-key", default="", help="Optional OPENAI_API_KEY override.")
    parser.add_argument("--atlas-api-key", default="", help="Optional ATLASCLOUD_API_KEY override.")
    parser.add_argument("--xai-api-key", default="", help="Optional XAI_API_KEY override.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing character images.")
    parser.add_argument("--dry-run", action="store_true", help="Write prompts/manifests without API calls.")
    parser.add_argument("--timeout", type=int, default=300, help="HTTP timeout seconds, default 300.")
    parser.add_argument("--max-retries", type=int, default=3, help="OpenAI retry attempts, default 3.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(REPO_ROOT / ".env")

    characters_dir = resolve_characters_dir(args)
    profiles = discover_profiles(characters_dir, selected_profile_ids(args.characters))
    output_ext = extension_for_format(args.output_format)
    if args.background == "transparent" and args.output_format == "jpeg":
        raise RuntimeError("transparent background requires --output-format png or webp.")
    image_model = resolve_image_model(args.image_model)
    model = args.model.strip() or default_model_for_image_model(image_model)
    api_key = ""
    if not args.dry_run:
        if image_model == "openai":
            api_key = resolve_openai_api_key(args.openai_api_key)
        elif image_model == "atlas-openai":
            api_key = resolve_atlas_api_key(args.atlas_api_key)
        elif image_model == "grok":
            api_key = resolve_xai_api_key(args.xai_api_key)
        else:
            raise RuntimeError(f"未知 IMAGE_MODEL: {image_model}")

    run_manifest: dict[str, Any] = {
        "created_at": datetime.now().isoformat(),
        "characters_dir": str(characters_dir),
        "image_model": image_model,
        "model": model,
        "size": args.size,
        "quality": args.quality,
        "output_format": args.output_format,
        "background": args.background,
        "dry_run": bool(args.dry_run),
        "items": [],
    }

    print(f"[INFO] characters_dir: {characters_dir}")
    print(f"[INFO] profiles: {len(profiles)}")
    print(f"[INFO] image_model: {image_model} ({model})")

    failures = 0
    for profile_path in profiles:
        character_id = profile_id_from_path(profile_path)
        profile_text = profile_path.read_text(encoding="utf-8")
        character_name = extract_character_name(profile_text, character_id)
        out_path = profile_path.with_name(f"{character_id}.{output_ext}")
        bible_path = visual_bible_path_for_profile(profile_path, character_id)
        if bible_path.exists():
            prompt = vac.build_character_image_prompt(vac.read_json(bible_path), args.extra_prompt)
        else:
            prompt = build_prompt(
                character_id=character_id,
                character_name=character_name,
                profile_text=profile_text,
                extra_prompt=args.extra_prompt,
            )
        item: dict[str, Any] = {
            "character_id": character_id,
            "character_name": character_name,
            "profile_path": str(profile_path),
            "output_path": str(out_path),
            "bible_path": str(bible_path) if bible_path.exists() else "",
            "image_model": image_model,
            "model": model,
            "status": "pending",
        }

        if out_path.exists() and not args.overwrite:
            item["status"] = "skipped_existing"
            out_path.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
            write_json(out_path.with_suffix(".manifest.json"), item)
            run_manifest["items"].append(item)
            print(f"[SKIP] {character_id}: exists ({out_path})")
            continue

        if args.dry_run:
            item["status"] = "dry_run"
            out_path.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
            write_json(out_path.with_suffix(".manifest.json"), item)
            run_manifest["items"].append(item)
            print(f"[DRY] {character_id}: prompt written")
            continue

        try:
            print(f"[INFO] generating {character_id} -> {out_path}")
            if image_model == "openai":
                result = post_openai_image_generation(
                    api_key=api_key,
                    model=model,
                    prompt=prompt,
                    size=args.size,
                    quality=args.quality,
                    output_format=args.output_format,
                    background=args.background,
                    output_compression=max(0, min(100, int(args.output_compression))),
                    timeout=max(30, int(args.timeout)),
                    max_retries=max(1, int(args.max_retries)),
                )
                image_bytes = extract_image_bytes(result)
            elif image_model == "atlas-openai":
                result = post_atlas_image_generation(
                    api_key=api_key,
                    model=model,
                    prompt=prompt,
                    size=args.size,
                    quality=args.quality,
                    output_format=args.output_format,
                    timeout=max(30, int(args.timeout)),
                    max_retries=max(1, int(args.max_retries)),
                )
                image_bytes = extract_image_bytes_from_atlas(result)
            elif image_model == "grok":
                if out_path.exists():
                    item["generation_mode"] = "image_edit"
                    result = post_xai_image_edit(
                        api_key=api_key,
                        model=model,
                        prompt=prompt,
                        image_ref=encode_local_image_as_data_uri(out_path),
                        size=args.size,
                        timeout=max(30, int(args.timeout)),
                        max_retries=max(1, int(args.max_retries)),
                    )
                else:
                    item["generation_mode"] = "text_to_image_bootstrap"
                    result = post_xai_image_generation(
                        api_key=api_key,
                        model=model,
                        prompt=prompt,
                        size=args.size,
                        timeout=max(30, int(args.timeout)),
                        max_retries=max(1, int(args.max_retries)),
                    )
                image_bytes = extract_image_bytes(result)
            else:
                raise RuntimeError(f"未知 IMAGE_MODEL: {image_model}")
            out_path.write_bytes(image_bytes)
            item["status"] = "completed"
            item["bytes"] = len(image_bytes)
            write_generation_artifacts(
                out_path=out_path,
                prompt=prompt,
                response_summary=summarize_openai_response(result),
                manifest_item=item,
            )
            print(f"[OK] {character_id}: {out_path}")
        except Exception as exc:
            failures += 1
            item["status"] = "failed"
            item["error"] = str(exc)
            write_json(out_path.with_suffix(".manifest.json"), item)
            print(f"[ERROR] {character_id}: {exc}", file=sys.stderr)
        run_manifest["items"].append(item)

    run_manifest["status"] = "failed" if failures else "completed"
    run_manifest_path = characters_dir / "character_image_gen_manifest.json"
    write_json(run_manifest_path, run_manifest)
    print(f"[INFO] manifest: {run_manifest_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
