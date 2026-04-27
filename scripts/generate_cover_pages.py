#!/usr/bin/env python3
"""Generate reusable vertical cover pages for a planned novel-to-video project.

The script uses the planner output as the source of truth for episode count,
generates or reuses one no-text base image, then renders deterministic local
Chinese title/subtitle/episode-number layers.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import shutil
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except Exception as exc:  # pragma: no cover - import guard for CLI users.
    raise RuntimeError("Pillow is required. Install project requirements first.") from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAI_IMAGE_EDITS_URL = "https://api.openai.com/v1/images/edits"
DEFAULT_MODEL = "gpt-image-1.5"
DEFAULT_SIZE = "auto"
DEFAULT_QUALITY = "high"
DEFAULT_OUTPUT_FORMAT = "png"
DEFAULT_INPUT_FIDELITY = "high"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_path(value: str | None, base_dir: Path) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {"raw_text": response.text}
    return data if isinstance(data, dict) else {"raw": data}


def resolve_openai_api_key(cli_value: str) -> str:
    key = cli_value.strip() or os.getenv("OPENAI_API_KEY", "").strip()
    if key and key != "your_openai_api_key_here":
        return key
    raise RuntimeError(
        "OPENAI_API_KEY 未配置。请在 .env 填入真实 key，"
        "或通过 --openai-api-key 显式传入。"
    )


def materialize_image_ref(value: str, index: int, temp_dir: Path) -> tuple[Path, str]:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        response = requests.get(value, timeout=180)
        if response.status_code >= 400:
            raise RuntimeError(f"下载参考图失败: HTTP {response.status_code}, url={value}")
        raw = response.content
        mime_type = str(response.headers.get("Content-Type") or "").split(";")[0].strip()
        if not mime_type:
            mime_type = mimetypes.guess_type(parsed.path)[0] or "application/octet-stream"
    else:
        path = Path(value).expanduser()
        if not path.exists():
            raise RuntimeError(f"参考图不存在: {value}")
        raw = path.read_bytes()
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    suffix = mimetypes.guess_extension(mime_type) or ".png"
    out_path = temp_dir / f"input_{index:02d}{suffix}"
    out_path.write_bytes(raw)
    return out_path, mime_type


def extract_openai_image_bytes(result: dict[str, Any]) -> bytes:
    data = result.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"未从 OpenAI 响应中解析到图片输出: {result}")
    first = data[0]
    if not isinstance(first, dict):
        raise RuntimeError(f"未从 OpenAI 响应中解析到图片输出: {result}")
    b64 = str(first.get("b64_json") or "").strip()
    if b64:
        return base64.b64decode(b64)
    url = str(first.get("url") or "").strip()
    if not url:
        raise RuntimeError(f"未从 OpenAI 响应中解析到图片输出: {result}")
    response = requests.get(url, timeout=180)
    if response.status_code >= 400:
        raise RuntimeError(f"下载 OpenAI 输出图失败: HTTP {response.status_code}, url={url}")
    return response.content


def post_openai_image_edit(
    *,
    api_key: str,
    model: str,
    prompt: str,
    image_refs: list[str],
    input_fidelity: str,
    output_format: str,
    quality: str,
    size: str,
) -> dict[str, Any]:
    if not image_refs:
        raise RuntimeError("OpenAI cover generation requires at least one reference image.")

    headers = {"Authorization": f"Bearer {api_key}"}
    with tempfile.TemporaryDirectory(prefix="cover_openai_") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        prepared = [materialize_image_ref(ref, idx, temp_dir) for idx, ref in enumerate(image_refs, 1)]
        data: dict[str, str] = {
            "model": model,
            "prompt": prompt,
            "quality": quality,
            "size": size,
            "output_format": output_format,
        }
        if model.strip().lower().startswith("gpt-image-1"):
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
        raise RuntimeError(f"OpenAI 封面底图生成失败: HTTP {response.status_code} - {result}")
    return result


def find_project_bible(plan_dir: Path) -> Path:
    direct = plan_dir / "04_当前项目的诊断与结构设计文档" / "project_bible_v1.json"
    if direct.exists():
        return direct
    matches = sorted(plan_dir.glob("**/project_bible_v1.json"))
    if not matches:
        raise RuntimeError(f"未找到 project_bible_v1.json: {plan_dir}")
    return matches[0]


def infer_episode_count(project_bible: dict[str, Any]) -> int:
    outlines = project_bible.get("episode_outlines")
    if not isinstance(outlines, list) or not outlines:
        raise RuntimeError("project_bible_v1.json 缺少 episode_outlines，无法推断集数。")
    numbers: list[int] = []
    for idx, item in enumerate(outlines, start=1):
        if isinstance(item, dict):
            try:
                numbers.append(int(item.get("episode_number") or idx))
            except Exception:
                numbers.append(idx)
        else:
            numbers.append(idx)
    return max(numbers)


def default_config(project_bible: dict[str, Any]) -> dict[str, Any]:
    selling_points = project_bible.get("core_selling_points")
    title = str(project_bible.get("title") or project_bible.get("project_name") or "短剧封面")
    subtitle = "，".join(str(x) for x in selling_points[:2]) if isinstance(selling_points, list) else ""
    return {
        "title": title,
        "subtitle": subtitle,
        "output_dir": "assets/cover_page",
        "base_image_path": "assets/covers/cover_base_no_text.png",
        "output_size": [941, 1672],
        "openai": {
            "model": DEFAULT_MODEL,
            "size": DEFAULT_SIZE,
            "quality": DEFAULT_QUALITY,
            "output_format": DEFAULT_OUTPUT_FORMAT,
            "input_fidelity": DEFAULT_INPUT_FIDELITY,
        },
        "reference_images": [],
        "base_prompt": (
            "Create a vertical 9:16 short-drama cover background with no text, "
            "leaving dark negative space at the top for title text and at the bottom for episode number."
        ),
        "font": {
            "family": "Songti SC",
            "path": "/System/Library/Fonts/Supplemental/Songti.ttc",
            "index": 1,
        },
        "layout": {},
    }


def merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = value
    return result


def cover_canvas(base_image: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    target_w, target_h = target_size
    img = base_image.convert("RGBA")
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    resized = img.resize((round(src_w * scale), round(src_h * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def color_tuple(value: list[int] | tuple[int, ...] | None, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if not value:
        return fallback
    items = [int(x) for x in value]
    if len(items) == 3:
        items.append(255)
    if len(items) != 4:
        return fallback
    return tuple(max(0, min(255, x)) for x in items)  # type: ignore[return-value]


def add_readability_gradients(img: Image.Image, layout: dict[str, Any]) -> Image.Image:
    w, h = img.size
    title_alpha = int(layout.get("top_gradient_alpha", 150))
    bottom_alpha = int(layout.get("bottom_gradient_alpha", 185))
    top_extent = float(layout.get("top_gradient_extent", 0.28))
    bottom_start = float(layout.get("bottom_gradient_start", 0.62))

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pix = overlay.load()
    for y in range(h):
        alpha = 0
        if y < int(h * top_extent):
            t = 1 - y / max(1, h * top_extent)
            alpha = max(alpha, int(title_alpha * (t**1.4)))
        if y > int(h * bottom_start):
            t = (y - h * bottom_start) / max(1, h * (1 - bottom_start))
            alpha = max(alpha, int(bottom_alpha * (t**1.25)))
        if alpha:
            for x in range(w):
                pix[x, y] = (0, 0, 0, alpha)
    return Image.alpha_composite(img, overlay)


def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    font_index: int,
    target_width: int,
    start_size: int,
    min_size: int,
) -> tuple[ImageFont.FreeTypeFont, int]:
    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(font_path, size=size, index=font_index)
        stroke = max(2, size // 28)
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
        if bbox[2] - bbox[0] <= target_width:
            return font, size
        size -= 2
    return ImageFont.truetype(font_path, size=min_size, index=font_index), min_size


def draw_centered_text(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    stroke_fill: tuple[int, int, int, int],
    stroke_width: int,
    shadow: dict[str, Any] | None,
) -> None:
    w, h = img.size
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    text_w = bbox[2] - bbox[0]
    x = (w - text_w) // 2
    if shadow is None or shadow.get("enabled", True):
        dx = int((shadow or {}).get("dx", 4))
        dy = int((shadow or {}).get("dy", 6))
        blur = float((shadow or {}).get("blur", 3))
        alpha = int((shadow or {}).get("alpha", 190))
        shadow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow_layer)
        sd.text(
            (x + dx, y + dy),
            text,
            font=font,
            fill=(0, 0, 0, alpha),
            stroke_width=stroke_width + 1,
            stroke_fill=(0, 0, 0, min(255, alpha)),
        )
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur))
        img.alpha_composite(shadow_layer)
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)


def render_title_layers(base_image: Image.Image, config: dict[str, Any]) -> Image.Image:
    img = base_image.copy().convert("RGBA")
    layout = config.get("layout") if isinstance(config.get("layout"), dict) else {}
    img = add_readability_gradients(img, layout)
    draw = ImageDraw.Draw(img)
    w, h = img.size

    font_cfg = config.get("font") if isinstance(config.get("font"), dict) else {}
    font_path = str(font_cfg.get("path") or "/System/Library/Fonts/Supplemental/Songti.ttc")
    font_index = int(font_cfg.get("index", 1))

    title_cfg = layout.get("title") if isinstance(layout.get("title"), dict) else {}
    subtitle_cfg = layout.get("subtitle") if isinstance(layout.get("subtitle"), dict) else {}

    title = str(config.get("title") or "").strip()
    if title:
        title_font, title_size = fit_font(
            draw,
            title,
            font_path,
            font_index,
            int(w * float(title_cfg.get("max_width_frac", 0.86))),
            int(title_cfg.get("font_size", 160)),
            int(title_cfg.get("min_font_size", 118)),
        )
        draw_centered_text(
            img,
            draw,
            title,
            int(h * float(title_cfg.get("y_frac", 0.075))),
            title_font,
            color_tuple(title_cfg.get("fill"), (248, 247, 238, 255)),
            color_tuple(title_cfg.get("stroke_fill"), (22, 25, 32, 235)),
            int(title_cfg.get("stroke_width", max(4, title_size // 24))),
            title_cfg.get("shadow") if isinstance(title_cfg.get("shadow"), dict) else None,
        )

        accent = layout.get("title_accent")
        if isinstance(accent, dict) and accent.get("enabled", True):
            line_w = int(w * float(accent.get("width_frac", 0.48)))
            line_y = int(h * float(accent.get("y_frac", 0.205)))
            line_x = (w - line_w) // 2
            line_h = int(accent.get("height", 5))
            draw.rectangle(
                (line_x, line_y, line_x + line_w, line_y + line_h),
                fill=color_tuple(accent.get("fill"), (205, 179, 126, 210)),
            )

    subtitle = str(config.get("subtitle") or "").strip()
    if subtitle:
        subtitle_font, subtitle_size = fit_font(
            draw,
            subtitle,
            font_path,
            font_index,
            int(w * float(subtitle_cfg.get("max_width_frac", 0.88))),
            int(subtitle_cfg.get("font_size", 58)),
            int(subtitle_cfg.get("min_font_size", 42)),
        )
        draw_centered_text(
            img,
            draw,
            subtitle,
            int(h * float(subtitle_cfg.get("y_frac", 0.765))),
            subtitle_font,
            color_tuple(subtitle_cfg.get("fill"), (255, 255, 255, 245)),
            color_tuple(subtitle_cfg.get("stroke_fill"), (10, 12, 18, 235)),
            int(subtitle_cfg.get("stroke_width", max(2, subtitle_size // 20))),
            subtitle_cfg.get("shadow") if isinstance(subtitle_cfg.get("shadow"), dict) else None,
        )
    return img


def add_episode_number(img: Image.Image, number: int, config: dict[str, Any]) -> Image.Image:
    out = img.copy().convert("RGBA")
    draw = ImageDraw.Draw(out)
    w, h = out.size

    layout = config.get("layout") if isinstance(config.get("layout"), dict) else {}
    number_cfg = layout.get("episode_number") if isinstance(layout.get("episode_number"), dict) else {}
    font_cfg = config.get("font") if isinstance(config.get("font"), dict) else {}
    font_path = str(font_cfg.get("path") or "/System/Library/Fonts/Supplemental/Songti.ttc")
    font_index = int(font_cfg.get("index", 1))
    text_format = str(number_cfg.get("format") or "{number}")
    text = text_format.format(number=number, number02=f"{number:02d}")

    overlay_alpha = int(number_cfg.get("bottom_gradient_alpha", 95))
    start_frac = float(number_cfg.get("bottom_gradient_start", 0.86))
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pix = overlay.load()
    start_y = int(h * start_frac)
    for y in range(start_y, h):
        t = (y - start_y) / max(1, h - start_y)
        alpha = int(overlay_alpha * (t**1.1))
        for x in range(w):
            pix[x, y] = (0, 0, 0, alpha)
    out = Image.alpha_composite(out, overlay)
    draw = ImageDraw.Draw(out)

    font = ImageFont.truetype(font_path, size=int(number_cfg.get("font_size", 168)), index=font_index)
    stroke_width = int(number_cfg.get("stroke_width", 5))
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    text_w = bbox[2] - bbox[0]
    x = (w - text_w) // 2
    y = int(h * float(number_cfg.get("y_frac", 0.875)))

    shadow = number_cfg.get("shadow") if isinstance(number_cfg.get("shadow"), dict) else {}
    if shadow.get("enabled", True):
        dx = int(shadow.get("dx", 5))
        dy = int(shadow.get("dy", 7))
        blur = float(shadow.get("blur", 4))
        alpha = int(shadow.get("alpha", 210))
        shadow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow_layer)
        sd.text(
            (x + dx, y + dy),
            text,
            font=font,
            fill=(0, 0, 0, alpha),
            stroke_width=stroke_width + 2,
            stroke_fill=(0, 0, 0, min(255, alpha)),
        )
        out.alpha_composite(shadow_layer.filter(ImageFilter.GaussianBlur(blur)))

    draw.text(
        (x, y),
        text,
        font=font,
        fill=color_tuple(number_cfg.get("fill"), (245, 232, 196, 255)),
        stroke_width=stroke_width,
        stroke_fill=color_tuple(number_cfg.get("stroke_fill"), (12, 14, 20, 240)),
    )
    return out


def save_rgb(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(path, quality=96)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate no-number and numbered short-drama cover pages.")
    parser.add_argument("--plan-dir", required=True, help="novel2video_plan.py output directory.")
    parser.add_argument("--project-dir", default="", help="Project directory. Defaults to parent of --plan-dir.")
    parser.add_argument("--config", default="", help="Cover config JSON. Defaults to <project-dir>/assets/cover_config.json when present.")
    parser.add_argument("--out-dir", default="", help="Override output directory for final cover images.")
    parser.add_argument("--base-image", default="", help="Use this no-text base image instead of configured/generated cache.")
    parser.add_argument("--regenerate-base", action="store_true", help="Force OpenAI API regeneration of the no-text base image.")
    parser.add_argument("--episode-count", type=int, default=0, help="Override planner-inferred episode count.")
    parser.add_argument("--openai-api-key", default="", help="Optional OPENAI_API_KEY override.")
    parser.add_argument("--model", default="", help="OpenAI image model override.")
    parser.add_argument("--size", default="", help="OpenAI Images API size override, e.g. auto.")
    parser.add_argument("--quality", default="", help="OpenAI Images API quality override.")
    parser.add_argument("--dry-run", action="store_true", help="Print resolved plan without API calls or image writes.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    load_env_file(REPO_ROOT / ".env")
    plan_dir = Path(args.plan_dir).expanduser().resolve()
    if not plan_dir.exists():
        raise RuntimeError(f"--plan-dir 不存在: {plan_dir}")
    project_dir = Path(args.project_dir).expanduser().resolve() if args.project_dir else plan_dir.parent.resolve()

    bible_path = find_project_bible(plan_dir)
    bible = read_json(bible_path)
    episode_count = args.episode_count or infer_episode_count(bible)

    config_path = Path(args.config).expanduser().resolve() if args.config else project_dir / "assets" / "cover_config.json"
    cfg = default_config(bible)
    if config_path.exists():
        cfg = merge_config(cfg, read_json(config_path))

    openai_cfg = cfg.get("openai") if isinstance(cfg.get("openai"), dict) else {}
    if args.model:
        openai_cfg["model"] = args.model
    if args.size:
        openai_cfg["size"] = args.size
    if args.quality:
        openai_cfg["quality"] = args.quality
    cfg["openai"] = openai_cfg

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else resolve_path(str(cfg.get("output_dir")), project_dir)
    if out_dir is None:
        out_dir = project_dir / "assets" / "cover_page"
    base_cache = resolve_path(str(cfg.get("base_image_path")), project_dir)
    if base_cache is None:
        base_cache = project_dir / "assets" / "covers" / "cover_base_no_text.png"
    base_input = Path(args.base_image).expanduser().resolve() if args.base_image else base_cache

    output_size = cfg.get("output_size") if isinstance(cfg.get("output_size"), list) else [941, 1672]
    if len(output_size) != 2:
        raise RuntimeError("cover_config.json output_size must be [width, height].")
    target_size = (int(output_size[0]), int(output_size[1]))

    print(f"[INFO] plan_dir: {plan_dir}")
    print(f"[INFO] project_bible: {bible_path}")
    print(f"[INFO] episode_count: {episode_count}")
    print(f"[INFO] output_dir: {out_dir}")
    print(f"[INFO] base_image: {base_input}")
    print(f"[INFO] openai_model: {openai_cfg.get('model') or DEFAULT_MODEL}")

    if args.dry_run:
        print("[INFO] dry-run only; no API calls or image files written.")
        return 0

    if args.regenerate_base or not base_input.exists():
        image_refs: list[str] = []
        for item in cfg.get("reference_images") or []:
            if isinstance(item, dict):
                value = str(item.get("path") or item.get("url") or "").strip()
            else:
                value = str(item).strip()
            if value:
                resolved = resolve_path(value, project_dir)
                image_refs.append(str(resolved if resolved else value))
        if not image_refs:
            raise RuntimeError("缺少 reference_images，无法用 OpenAI 生成封面底图。")
        api_key = resolve_openai_api_key(args.openai_api_key)
        print("[INFO] generating no-text base image with OpenAI...")
        result = post_openai_image_edit(
            api_key=api_key,
            model=str(openai_cfg.get("model") or DEFAULT_MODEL),
            prompt=str(cfg.get("base_prompt") or ""),
            image_refs=image_refs,
            input_fidelity=str(openai_cfg.get("input_fidelity") or DEFAULT_INPUT_FIDELITY),
            output_format=str(openai_cfg.get("output_format") or DEFAULT_OUTPUT_FORMAT),
            quality=str(openai_cfg.get("quality") or DEFAULT_QUALITY),
            size=str(openai_cfg.get("size") or DEFAULT_SIZE),
        )
        base_cache.parent.mkdir(parents=True, exist_ok=True)
        base_cache.write_bytes(extract_openai_image_bytes(result))
        write_json(base_cache.with_suffix(".openai_response.json"), result)
        base_input = base_cache
    elif args.base_image and base_input != base_cache:
        base_cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_input, base_cache)
        base_input = base_cache

    base = cover_canvas(Image.open(base_input), target_size)
    cover_no_number = render_title_layers(base, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)

    no_number_path = out_dir / "ginza_night_cover_no_number.png"
    project_name = str(bible.get("project_name") or "project").lower()
    if project_name and project_name != "ginzanight":
        no_number_path = out_dir / f"{project_name}_cover_no_number.png"
    save_rgb(cover_no_number, no_number_path)

    generated = [str(no_number_path)]
    for number in range(1, episode_count + 1):
        numbered = add_episode_number(cover_no_number, number, cfg)
        if project_name == "ginzanight":
            out_path = out_dir / f"ginza_night_cover_{number:02d}.png"
        else:
            out_path = out_dir / f"{project_name}_cover_{number:02d}.png"
        save_rgb(numbered, out_path)
        generated.append(str(out_path))

    manifest = {
        "source": "scripts/generate_cover_pages.py",
        "plan_dir": str(plan_dir),
        "project_bible": str(bible_path),
        "episode_count": episode_count,
        "base_image": str(base_input),
        "target_size": list(target_size),
        "title": cfg.get("title"),
        "subtitle": cfg.get("subtitle"),
        "generated_files": generated,
    }
    write_json(out_dir / "cover_generation_manifest.json", manifest)
    print(f"[INFO] generated {len(generated)} cover images")
    print(f"[INFO] manifest: {out_dir / 'cover_generation_manifest.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
