#!/usr/bin/env python3
"""Create shared character/scene/prop visual assets for novel and screen flows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import visual_asset_core as vac


REPO_ROOT = Path(__file__).resolve().parents[1]
EXECUTION_DIR_NAME = "06_当前项目的视觉与AI执行层文档"
DEFAULT_SIZE = "1024x1536"
DEFAULT_OUTPUT_FORMAT = "jpeg"
DEFAULT_OPENAI_IMAGE_QUALITY = "high"
DEFAULT_OPENAI_IMAGE_BACKGROUND = "opaque"
DEFAULT_OPENAI_OUTPUT_COMPRESSION = 92


def resolve_repo_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def extension_for_format(output_format: str) -> str:
    normalized = str(output_format or "").strip().lower()
    if normalized == "jpeg":
        return "jpg"
    if normalized in {"jpg", "png", "webp"}:
        return normalized
    raise RuntimeError(f"不支持的 output_format: {output_format}")


def load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return vac.read_json(path)
    except Exception:
        return {}


def write_prompt(path: Path, prompt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prompt.rstrip() + "\n", encoding="utf-8")


def character_key(node: dict[str, Any]) -> str:
    return str(node.get("character_id") or node.get("name") or node.get("lock_profile_id") or "").strip()


def character_profile_path(characters_dir: Path, character_id: str) -> Path:
    return characters_dir / f"{character_id}.profile.md"


def character_bible_path(characters_dir: Path, character_id: str) -> Path:
    return characters_dir / f"{character_id}.visual_bible.json"


def character_image_path(characters_dir: Path, character_id: str, output_ext: str) -> Path:
    return characters_dir / f"{character_id}.{output_ext}"


def image_response_path(out_path: Path, provider: str) -> Path:
    suffix = ".openai_response.json" if str(provider or "").strip().lower() == "openai" else ".grok_response.json"
    return out_path.with_suffix(suffix)


def profile_text_for_character(
    characters_dir: Path,
    character_id: str,
    node: dict[str, Any],
    lock_profile: dict[str, Any] | None,
) -> str:
    path = character_profile_path(characters_dir, character_id)
    if path.exists():
        return path.read_text(encoding="utf-8")
    lock_profile = lock_profile if isinstance(lock_profile, dict) else {}
    return "\n".join(
        [
            f"# {str(node.get('name') or character_id).strip()} 角色档案",
            "",
            "【基本身份背景】",
            str(lock_profile.get("visual_anchor") or node.get("visual_anchor") or ""),
            "",
            "【容貌】",
            str(lock_profile.get("visual_anchor") or node.get("visual_anchor") or ""),
            "",
            "【镜头功能】",
            "人格锚点：" + "、".join(str(x) for x in node.get("persona_anchor", []) if str(x).strip())
            if isinstance(node.get("persona_anchor"), list)
            else "",
        ]
    )


def build_llm_config(args: argparse.Namespace) -> vac.LLMConfig | None:
    if args.dry_run:
        return None
    api_key = vac.resolve_xai_api_key(args.xai_api_key)
    models = [m.strip() for m in args.llm_model.split(",") if m.strip()] or vac.DEFAULT_XAI_CHAT_MODELS
    return vac.LLMConfig(
        api_key=api_key,
        models=models,
        temperature=float(args.llm_temperature),
        timeout=max(30, int(args.timeout)),
        max_retries=max(0, int(args.max_retries)),
    )


def maybe_generate_image(
    *,
    prompt: str,
    out_path: Path,
    response_path: Path,
    args: argparse.Namespace,
    image_api_key: str,
    item: dict[str, Any],
    force_overwrite: bool = False,
) -> None:
    if out_path.exists() and not args.overwrite and not force_overwrite:
        item["status"] = "completed_existing"
        item["bytes"] = out_path.stat().st_size
        return
    if args.dry_run or args.skip_image_generation:
        item["status"] = "dry_run" if args.dry_run else "prompt_only"
        return
    provider = str(args.image_provider or "").strip().lower()
    if provider == "openai":
        result = vac.post_openai_image_generation(
            api_key=image_api_key,
            model=args.image_model,
            prompt=prompt,
            size=args.size,
            quality=args.image_quality,
            output_format=args.output_format,
            background=args.image_background,
            output_compression=int(args.output_compression),
            timeout=max(30, int(args.timeout)),
            max_retries=max(1, int(args.max_retries)),
        )
    elif provider == "grok":
        result = vac.post_xai_image_generation(
            api_key=image_api_key,
            model=args.image_model,
            prompt=prompt,
            size=args.size,
            timeout=max(30, int(args.timeout)),
            max_retries=max(1, int(args.max_retries)),
        )
    else:
        raise RuntimeError(f"不支持的 image provider: {args.image_provider}")
    image_bytes = vac.extract_image_bytes(result)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(image_bytes)
    vac.write_json(response_path, vac.summarize_image_response(result))
    item["status"] = "completed"
    item["bytes"] = len(image_bytes)


def character_visual_qa_enabled(args: argparse.Namespace) -> bool:
    return bool(args.enable_character_qa) and str(args.character_qa_provider or "").strip().lower() != "none"


def character_visual_qa_path(image_path: Path) -> Path:
    return image_path.with_suffix(".visual_qa.json")


def run_character_visual_qa(
    *,
    args: argparse.Namespace,
    image_path: Path,
    bible: dict[str, Any],
    contrast_bible: dict[str, Any],
    openai_api_key: str,
) -> dict[str, Any]:
    preflight = vac.local_character_image_preflight(image_path)
    reasons = list(preflight.get("errors", [])) if isinstance(preflight.get("errors"), list) else []
    if reasons:
        return {
            **vac.default_character_qa_report(
                character_id=str(bible.get("id") or ""),
                provider="local",
                model="preflight",
                status="failed",
                reasons=[str(x) for x in reasons],
            ),
            "local_preflight": preflight,
        }
    provider = str(args.character_qa_provider or "openai").strip().lower()
    if provider == "openai":
        report = vac.call_openai_character_visual_qa(
            api_key=openai_api_key,
            model=str(args.character_qa_model or vac.DEFAULT_OPENAI_CHARACTER_QA_MODEL),
            image_path=image_path,
            bible=bible,
            contrast_bible=contrast_bible,
            timeout=max(30, int(args.timeout)),
        )
        report["local_preflight"] = preflight
        return report
    if provider == "grok":
        return {
            **vac.default_character_qa_report(
                character_id=str(bible.get("id") or ""),
                provider="grok",
                model=str(args.character_qa_model or ""),
                status="skipped",
                reasons=[],
            ),
            "local_preflight": preflight,
            "note": "grok vision QA provider is reserved; local preflight passed",
        }
    return {
        **vac.default_character_qa_report(
            character_id=str(bible.get("id") or ""),
            provider=provider,
            model=str(args.character_qa_model or ""),
            status="skipped",
            reasons=[],
        ),
        "local_preflight": preflight,
    }


def process_characters(
    *,
    args: argparse.Namespace,
    project_root: Path,
    episode_root: Path,
    character_map_path: Path,
    output_ext: str,
    llm_config: vac.LLMConfig | None,
    image_api_key: str,
    project_style: dict[str, str],
    manifest: dict[str, Any],
) -> int:
    records_dir = episode_root / "records"
    lock_profiles = vac.load_lock_profiles(episode_root / "35_character_lock_profiles_v1.json")
    characters_dir = project_root / "assets" / "characters"
    character_map = load_json_if_exists(character_map_path)
    if not isinstance(character_map, dict):
        character_map = {}

    character_sources: list[dict[str, Any]] = []
    for node in vac.iter_character_nodes_from_records(records_dir):
        character_id = str(node.get("character_id") or node.get("name") or "").strip()
        if not character_id:
            continue
        lock_id = str(node.get("lock_profile_id") or "").strip()
        lock_profile = lock_profiles.get(lock_id) or lock_profiles.get(character_id) or lock_profiles.get(str(node.get("name") or ""))
        if not vac.character_needs_identity_asset(node, lock_profile):
            continue
        lock_profile = lock_profile if isinstance(lock_profile, dict) else {}
        name = str(node.get("name") or lock_profile.get("name") or character_id).strip()
        profile_text = profile_text_for_character(characters_dir, character_id, node, lock_profile)
        character_sources.append(
            {
                "character_id": character_id,
                "name": name,
                "lock_profile_id": lock_id,
                "visual_anchor": str(lock_profile.get("visual_anchor") or node.get("visual_anchor") or ""),
                "lock_profile": lock_profile,
                "record_anchor": node,
                "profile_text": profile_text,
                "project_style": project_style,
            }
        )

    contrast_bible_path = characters_dir / "character_contrast_bible.json"
    if contrast_bible_path.exists() and not args.force_character_contrast and not args.force_bible:
        contrast_bible = vac.read_json(contrast_bible_path)
        contrast_errors = vac.validate_character_contrast_bible(
            contrast_bible,
            [str(item.get("character_id") or "") for item in character_sources],
        )
        contrast_quality = {"mode": "existing", "valid": not contrast_errors, "errors": contrast_errors}
        if contrast_errors:
            contrast_bible, contrast_quality = vac.generate_character_contrast_bible(
                characters=character_sources,
                project_style=project_style,
                llm_config=llm_config,
                dry_run=bool(args.dry_run),
            )
            vac.write_json(contrast_bible_path, contrast_bible)
    else:
        contrast_bible, contrast_quality = vac.generate_character_contrast_bible(
            characters=character_sources,
            project_style=project_style,
            llm_config=llm_config,
            dry_run=bool(args.dry_run),
        )
        vac.write_json(contrast_bible_path, contrast_bible)

    openai_api_key = ""
    if character_visual_qa_enabled(args) and not args.dry_run and not args.skip_image_generation:
        if str(args.character_qa_provider or "").strip().lower() == "openai":
            openai_api_key = vac.resolve_openai_api_key(args.openai_api_key)

    failures = 0
    for source in character_sources:
        character_id = str(source.get("character_id") or "").strip()
        name = str(source.get("name") or character_id).strip()
        lock_id = str(source.get("lock_profile_id") or "").strip()
        lock_profile = source.get("lock_profile") if isinstance(source.get("lock_profile"), dict) else {}
        out_path = character_image_path(characters_dir, character_id, output_ext)
        prompt_path = out_path.with_suffix(".prompt.txt")
        bible_path = character_bible_path(characters_dir, character_id)
        qa_path = character_visual_qa_path(out_path)
        source = {**source, "contrast_bible": contrast_bible}
        try:
            if bible_path.exists() and not args.force_bible:
                bible = vac.normalize_character_bible_from_source(vac.read_json(bible_path), source)
                errors = vac.validate_character_bible(bible)
                quality = {"mode": "existing", "valid": not errors, "errors": errors}
                if errors:
                    heuristic = vac.normalize_character_bible_from_source(
                        vac.heuristic_character_bible(
                            character_id=character_id,
                            name=name,
                            profile_text=str(source.get("profile_text") or ""),
                            lock_profile=lock_profile,
                            visual_anchor=str(source["visual_anchor"]),
                            project_style=project_style,
                        ),
                        source,
                    )
                    bible, quality = vac.generate_bible_with_retries(
                        kind="character",
                        source=source,
                        heuristic=heuristic,
                        validate=vac.validate_character_bible,
                        llm_config=llm_config,
                        dry_run=bool(args.dry_run),
                    )
                vac.write_json(bible_path, bible)
            else:
                heuristic = vac.heuristic_character_bible(
                    character_id=character_id,
                    name=name,
                    profile_text=str(source.get("profile_text") or ""),
                    lock_profile=lock_profile,
                    visual_anchor=str(source["visual_anchor"]),
                    project_style=project_style,
                )
                heuristic = vac.normalize_character_bible_from_source(heuristic, source)
                bible, quality = vac.generate_bible_with_retries(
                    kind="character",
                    source=source,
                    heuristic=heuristic,
                    validate=vac.validate_character_bible,
                    llm_config=llm_config,
                    dry_run=bool(args.dry_run),
                )
                vac.write_json(bible_path, bible)

            for key in (character_id, name, lock_id):
                if key:
                    character_map.setdefault(key, rel(out_path))

            repair_prompts: list[str] = []
            qa_report: dict[str, Any] = {}
            image_status = "pending"
            max_qa_attempts = max(0, int(args.max_character_qa_retries))
            attempts_total = 1 + (max_qa_attempts if character_visual_qa_enabled(args) else 0)
            for attempt in range(1, attempts_total + 1):
                extra_prompt = args.extra_character_prompt
                if repair_prompts:
                    extra_prompt = "\n".join([extra_prompt, repair_prompts[-1]]).strip()
                prompt = vac.build_character_image_prompt(bible, extra_prompt)
                write_prompt(prompt_path, prompt)
                image_item = {"status": "pending"}
                maybe_generate_image(
                    prompt=prompt,
                    out_path=out_path,
                    response_path=image_response_path(out_path, args.image_provider),
                    args=args,
                    image_api_key=image_api_key,
                    item=image_item,
                    force_overwrite=bool(repair_prompts),
                )
                image_status = str(image_item.get("status") or "")
                if not character_visual_qa_enabled(args):
                    qa_report = vac.default_character_qa_report(
                        character_id=character_id,
                        provider="none",
                        model="",
                        status="skipped",
                        reasons=[],
                    )
                    vac.write_json(qa_path, qa_report)
                    break
                if args.dry_run or args.skip_image_generation:
                    qa_report = vac.default_character_qa_report(
                        character_id=character_id,
                        provider=str(args.character_qa_provider),
                        model=str(args.character_qa_model or vac.DEFAULT_OPENAI_CHARACTER_QA_MODEL),
                        status="planned",
                        reasons=[],
                    )
                    vac.write_json(qa_path, qa_report)
                    break
                qa_report = run_character_visual_qa(
                    args=args,
                    image_path=out_path,
                    bible=bible,
                    contrast_bible=contrast_bible,
                    openai_api_key=openai_api_key,
                )
                vac.write_json(qa_path, qa_report)
                if qa_report.get("status") in {"passed", "skipped"}:
                    break
                if attempt >= attempts_total:
                    break
                repair_prompts.append(vac.build_character_repair_prompt(qa_report))

            qa_status = str(qa_report.get("status") or "unknown")
            status = image_status
            if character_visual_qa_enabled(args) and qa_status == "failed":
                status = "failed_qa"
                failures += 1

            item = {
                "type": "character",
                "id": character_id,
                "name": name,
                "lock_profile_id": lock_id,
                "output_path": str(out_path),
                "prompt_path": str(prompt_path),
                "bible_path": str(bible_path),
                "contrast_bible_path": str(contrast_bible_path),
                "visual_qa_path": str(qa_path),
                "visual_qa_status": qa_status,
                "qa_attempts": int(qa_report.get("attempts") or len(repair_prompts) + 1),
                "repair_prompts": repair_prompts,
                "llm_model": bible.get("llm_model", ""),
                "quality_report": quality,
                "contrast_quality_report": contrast_quality,
                "status": status,
            }
            if out_path.exists():
                item["bytes"] = out_path.stat().st_size
            manifest["characters"][character_id] = item
            print(f"[{item['status'].upper()}] character {character_id}: {prompt_path}")
        except Exception as exc:
            failures += 1
            item = {
                "type": "character",
                "id": character_id,
                "name": name,
                "output_path": str(out_path),
                "prompt_path": str(prompt_path),
                "bible_path": str(bible_path),
                "contrast_bible_path": str(contrast_bible_path),
                "visual_qa_path": str(qa_path),
                "visual_qa_status": "failed",
                "qa_attempts": 0,
                "repair_prompts": [],
                "status": "failed",
                "error": str(exc),
            }
            manifest["characters"][character_id] = item
            print(f"[ERROR] character {character_id}: {exc}", file=sys.stderr)

    if manifest["characters"]:
        vac.write_json(character_map_path, character_map)
    return failures


def process_scenes(
    *,
    args: argparse.Namespace,
    episode_root: Path,
    visual_ref_root: Path,
    output_ext: str,
    llm_config: vac.LLMConfig | None,
    image_api_key: str,
    project_style: dict[str, str],
    manifest: dict[str, Any],
) -> int:
    failures = 0
    scene_detail = episode_root / "scene_detail.txt"
    for scene in vac.parse_scene_detail(scene_detail):
        filename = vac.sanitize_filename(scene["name"], scene["scene_id"])
        out_path = visual_ref_root / "scenes" / f"{filename}.{output_ext}"
        prompt_path = out_path.with_suffix(".prompt.txt")
        bible_path = out_path.with_suffix(".visual_bible.json")
        source = {**scene, "project_style": project_style}
        try:
            if bible_path.exists() and not args.force_bible:
                bible = vac.read_json(bible_path)
                errors = vac.validate_scene_bible(bible, project_style)
                quality = {"mode": "existing", "valid": not errors, "errors": errors}
            else:
                heuristic = vac.heuristic_scene_bible(scene=scene, project_style=project_style)
                bible, quality = vac.generate_bible_with_retries(
                    kind="scene",
                    source=source,
                    heuristic=heuristic,
                    validate=lambda b: vac.validate_scene_bible(b, project_style),
                    llm_config=llm_config,
                    dry_run=bool(args.dry_run),
                )
                vac.write_json(bible_path, bible)
            prompt = vac.build_scene_image_prompt(bible, args.extra_scene_prompt)
            write_prompt(prompt_path, prompt)
            item = {
                "type": "scene",
                "id": scene["scene_id"],
                "name": scene["name"],
                "output_path": str(out_path),
                "prompt_path": str(prompt_path),
                "bible_path": str(bible_path),
                "llm_model": bible.get("llm_model", ""),
                "quality_report": quality,
                "description": scene["description"],
                "source": {"scene_detail": str(scene_detail)},
                "status": "pending",
            }
            maybe_generate_image(
                prompt=prompt,
                out_path=out_path,
                response_path=image_response_path(out_path, args.image_provider),
                args=args,
                image_api_key=image_api_key,
                item=item,
            )
            manifest["scenes"][scene["name"]] = item
            print(f"[{item['status'].upper()}] scene {scene['name']}: {prompt_path}")
        except Exception as exc:
            failures += 1
            manifest["scenes"][scene["name"]] = {
                "type": "scene",
                "id": scene["scene_id"],
                "name": scene["name"],
                "output_path": str(out_path),
                "prompt_path": str(prompt_path),
                "bible_path": str(bible_path),
                "status": "failed",
                "error": str(exc),
            }
            print(f"[ERROR] scene {scene['name']}: {exc}", file=sys.stderr)
    return failures


def process_props(
    *,
    args: argparse.Namespace,
    episode_root: Path,
    visual_ref_root: Path,
    output_ext: str,
    llm_config: vac.LLMConfig | None,
    image_api_key: str,
    manifest: dict[str, Any],
) -> int:
    failures = 0
    records_dir = episode_root / "records"
    for prop_id, prop in vac.extract_props(records_dir).items():
        out_path = visual_ref_root / "props" / f"{vac.sanitize_filename(prop_id, 'prop')}.{output_ext}"
        prompt_path = out_path.with_suffix(".prompt.txt")
        bible_path = out_path.with_suffix(".visual_bible.json")
        try:
            if bible_path.exists() and not args.force_bible:
                bible = vac.normalize_prop_bible_from_source(vac.read_json(bible_path), prop)
                errors = vac.validate_prop_bible(bible, prop_id=prop_id)
                quality = {"mode": "existing", "valid": not errors, "errors": errors}
                if not errors:
                    vac.write_json(bible_path, bible)
            else:
                heuristic = vac.heuristic_prop_bible(prop=prop)
                bible, quality = vac.generate_bible_with_retries(
                    kind="prop",
                    source=prop,
                    heuristic=heuristic,
                    validate=lambda b: vac.validate_prop_bible(b, prop_id=prop_id),
                    llm_config=llm_config,
                    dry_run=bool(args.dry_run),
                )
                vac.write_json(bible_path, bible)
            prompt = vac.build_prop_image_prompt(bible, args.extra_prop_prompt)
            write_prompt(prompt_path, prompt)
            item = {
                "type": "prop",
                "id": prop_id,
                "name": str(prop.get("profile", {}).get("display_name") or prop_id),
                "aliases": prop.get("aliases", []),
                "reference_mode": str(bible.get("reference_mode") or "product"),
                "output_path": str(out_path),
                "prompt_path": str(prompt_path),
                "bible_path": str(bible_path),
                "llm_model": bible.get("llm_model", ""),
                "quality_report": quality,
                "profile": prop.get("profile", {}),
                "source": {
                    "records_dir": str(records_dir),
                    "shots": prop.get("shots", []),
                    "source_prop_ids": prop.get("source_prop_ids", []),
                },
                "status": "pending",
            }
            if isinstance(item["profile"], dict):
                for key in ("scale_policy", "reference_context_policy", "reference_mode"):
                    value = bible.get(key)
                    if value and not item["profile"].get(key):
                        item["profile"][key] = value
            maybe_generate_image(
                prompt=prompt,
                out_path=out_path,
                response_path=image_response_path(out_path, args.image_provider),
                args=args,
                image_api_key=image_api_key,
                item=item,
            )
            manifest["props"][prop_id] = item
            print(f"[{item['status'].upper()}] prop {prop_id}: {prompt_path}")
        except Exception as exc:
            failures += 1
            manifest["props"][prop_id] = {
                "type": "prop",
                "id": prop_id,
                "output_path": str(out_path),
                "prompt_path": str(prompt_path),
                "bible_path": str(bible_path),
                "status": "failed",
                "error": str(exc),
            }
            print(f"[ERROR] prop {prop_id}: {exc}", file=sys.stderr)
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create shared visual bibles, prompts, and assets.")
    parser.add_argument("--episode-root", required=True, help="Execution layer dir containing records/ and scene_detail.txt.")
    parser.add_argument("--project-root", required=True, help="Project root containing assets/ and character_image_map.json.")
    parser.add_argument("--character-image-map", required=True)
    parser.add_argument("--visual-ref-root", required=True)
    parser.add_argument("--asset-types", default="characters,scenes,props")
    parser.add_argument("--llm-provider", default="grok", choices=["grok"])
    parser.add_argument("--llm-model", default=",".join(vac.DEFAULT_XAI_CHAT_MODELS))
    parser.add_argument("--llm-temperature", type=float, default=0.55)
    parser.add_argument("--image-provider", default="openai", choices=["openai", "grok"])
    parser.add_argument("--image-model", default="", help="Defaults to gpt-image-1.5 for OpenAI, grok-imagine-image for Grok.")
    parser.add_argument("--image-quality", default=DEFAULT_OPENAI_IMAGE_QUALITY, choices=["low", "medium", "high"])
    parser.add_argument("--image-background", default=DEFAULT_OPENAI_IMAGE_BACKGROUND, choices=["opaque", "transparent", "auto"])
    parser.add_argument("--output-compression", type=int, default=DEFAULT_OPENAI_OUTPUT_COMPRESSION)
    parser.add_argument("--size", default=DEFAULT_SIZE)
    parser.add_argument("--output-format", default=DEFAULT_OUTPUT_FORMAT, choices=["jpeg", "jpg", "png", "webp"])
    parser.add_argument("--xai-api-key", default="")
    parser.add_argument("--openai-api-key", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--force-bible", action="store_true")
    parser.add_argument("--force-character-contrast", action="store_true")
    parser.add_argument("--skip-image-generation", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--enable-character-qa", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--character-qa-provider", default="openai", choices=["openai", "grok", "none"])
    parser.add_argument("--character-qa-model", default=vac.DEFAULT_OPENAI_CHARACTER_QA_MODEL)
    parser.add_argument("--max-character-qa-retries", type=int, default=2)
    parser.add_argument("--extra-character-prompt", default="")
    parser.add_argument("--extra-scene-prompt", default="")
    parser.add_argument("--extra-prop-prompt", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    vac.load_dotenv(REPO_ROOT / ".env")
    args.image_provider = str(args.image_provider or "openai").strip().lower()
    if not str(args.image_model or "").strip():
        args.image_model = vac.DEFAULT_OPENAI_IMAGE_MODEL if args.image_provider == "openai" else vac.DEFAULT_XAI_IMAGE_MODEL

    episode_root = resolve_repo_path(args.episode_root)
    project_root = resolve_repo_path(args.project_root)
    character_map = resolve_repo_path(args.character_image_map)
    visual_ref_root = resolve_repo_path(args.visual_ref_root)
    output_ext = extension_for_format(args.output_format)
    asset_types = vac.selected_values(args.asset_types.lower())

    scene_text = (episode_root / "scene_detail.txt").read_text(encoding="utf-8") if (episode_root / "scene_detail.txt").exists() else ""
    project_style = vac.infer_project_style(scene_text, str(project_root), str(episode_root))
    llm_config = build_llm_config(args)
    if args.dry_run or args.skip_image_generation:
        image_api_key = ""
    elif args.image_provider == "openai":
        image_api_key = vac.resolve_openai_api_key(args.openai_api_key)
    elif args.image_provider == "grok":
        image_api_key = vac.resolve_xai_api_key(args.xai_api_key)
    else:
        raise RuntimeError(f"不支持的 image provider: {args.image_provider}")
    existing_manifest = load_json_if_exists(visual_ref_root / "visual_reference_manifest.json")

    manifest: dict[str, Any] = {
        "created_at": datetime.now().isoformat(),
        "mode": "dry_run" if args.dry_run else "api_generate",
        "provider": args.image_provider,
        "llm_provider": args.llm_provider,
        "llm_models": [m.strip() for m in args.llm_model.split(",") if m.strip()],
        "image_provider": args.image_provider,
        "image_model": args.image_model,
        "character_qa": {
            "enabled": bool(args.enable_character_qa),
            "provider": args.character_qa_provider,
            "model": args.character_qa_model,
            "max_retries": int(args.max_character_qa_retries),
        },
        "size": args.size,
        "output_format": args.output_format,
        "episode_root": str(episode_root),
        "project_root": str(project_root),
        "character_image_map": str(character_map),
        "visual_ref_root": str(visual_ref_root),
        "project_style": project_style,
        "characters": existing_manifest.get("characters", {}) if "characters" not in asset_types and isinstance(existing_manifest.get("characters"), dict) else {},
        "scenes": existing_manifest.get("scenes", {}) if "scenes" not in asset_types and isinstance(existing_manifest.get("scenes"), dict) else {},
        "props": existing_manifest.get("props", {}) if "props" not in asset_types and isinstance(existing_manifest.get("props"), dict) else {},
    }

    print(f"[INFO] episode_root: {episode_root}")
    print(f"[INFO] project_root: {project_root}")
    print(f"[INFO] visual_ref_root: {visual_ref_root}")
    print(f"[INFO] mode: {manifest['mode']} llm=grok image={args.image_provider}/{args.image_model}")

    failures = 0
    if "characters" in asset_types:
        failures += process_characters(
            args=args,
            project_root=project_root,
            episode_root=episode_root,
            character_map_path=character_map,
            output_ext=output_ext,
            llm_config=llm_config,
            image_api_key=image_api_key,
            project_style=project_style,
            manifest=manifest,
        )
    if "scenes" in asset_types:
        failures += process_scenes(
            args=args,
            episode_root=episode_root,
            visual_ref_root=visual_ref_root,
            output_ext=output_ext,
            llm_config=llm_config,
            image_api_key=image_api_key,
            project_style=project_style,
            manifest=manifest,
        )
    if "props" in asset_types:
        failures += process_props(
            args=args,
            episode_root=episode_root,
            visual_ref_root=visual_ref_root,
            output_ext=output_ext,
            llm_config=llm_config,
            image_api_key=image_api_key,
            manifest=manifest,
        )

    manifest["status"] = "failed" if failures else "completed"
    manifest["counts"] = {
        "characters": len(manifest["characters"]),
        "scenes": len(manifest["scenes"]),
        "props": len(manifest["props"]),
        "failed": failures,
    }
    vac.write_json(visual_ref_root / "visual_reference_manifest.json", manifest)
    print(f"[INFO] manifest written: {visual_ref_root / 'visual_reference_manifest.json'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
