#!/usr/bin/env python3
"""Create shot-scoped costume variant reference assets.

This script writes a character costume variant profile, visual bible, and a
shot-scoped character_image_map override. It deliberately does not update the
canonical project character_image_map.json.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
AMBIGUOUS_WARDROBE_TOKENS = ("或", " or ", "/or/", "任选", "候选", "二选一")


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


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict[str, Any], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"exists, pass --overwrite to replace: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"exists, pass --overwrite to replace: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip()).strip("_").upper()
    return cleaned or "COSTUME_VARIANT"


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，\s]+", str(value or "")) if item.strip()]


def contains_ambiguous_wardrobe(text: str) -> bool:
    raw = f" {str(text or '').lower()} "
    return any(token in text or token in raw for token in AMBIGUOUS_WARDROBE_TOKENS)


def load_profiles(path: Path) -> list[dict[str, Any]]:
    payload = read_json_if_exists(path)
    profiles = payload.get("profiles")
    return [item for item in profiles if isinstance(item, dict)] if isinstance(profiles, list) else []


def alias_values(profile: dict[str, Any], *, include_anchor_tokens: bool = True) -> list[str]:
    values: list[str] = []
    for key in ("character_id", "lock_profile_id", "name"):
        text = str(profile.get(key) or "").strip()
        if text:
            values.append(text)
    alias_keys = ["aliases"]
    if include_anchor_tokens:
        alias_keys.append("appearance_anchor_tokens")
    for key in alias_keys:
        raw = profile.get(key)
        if isinstance(raw, list):
            values.extend(str(item).strip() for item in raw if str(item).strip())
    return list(dict.fromkeys(values))


def registry_profiles(project_root: Path) -> list[dict[str, Any]]:
    payload = read_json_if_exists(project_root / "character_registry.json")
    raw = payload.get("characters")
    if isinstance(raw, dict):
        profiles = []
        for character_id, item in raw.items():
            if not isinstance(item, dict):
                continue
            profile = dict(item)
            profile.setdefault("character_id", character_id)
            profiles.append(profile)
        return profiles
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def character_image_map_profiles(project_root: Path) -> list[dict[str, Any]]:
    image_map = read_json_if_exists(project_root / "character_image_map.json")
    profiles: list[dict[str, Any]] = []
    for key, value in image_map.items():
        key_text = str(key or "").strip()
        if key_text:
            profiles.append({"character_id": key_text, "name": key_text, "reference_image": value})
    return profiles


def find_base_profile(
    *,
    project_root: Path,
    episode_root: Path | None,
    character_id: str,
    character_name: str,
    lock_profile_id: str,
) -> dict[str, Any]:
    needles = {item for item in (character_id, character_name, lock_profile_id) if item}
    candidates: list[dict[str, Any]] = []
    if episode_root is not None:
        candidates.extend(load_profiles(episode_root / "35_character_lock_profiles_v1.json"))
    candidates.extend(registry_profiles(project_root))
    candidates.extend(character_image_map_profiles(project_root))

    for profile in candidates:
        aliases = set(alias_values(profile))
        if needles & aliases:
            return profile
    if character_id or character_name:
        return {
            "character_id": character_id,
            "name": character_name or character_id,
            "lock_profile_id": lock_profile_id,
        }
    raise ValueError("Unable to resolve base character; pass --character-id or --character-name.")


def image_ext(output_format: str) -> str:
    value = str(output_format or "jpeg").strip().lower()
    if value == "jpeg":
        return "jpg"
    if value in {"jpg", "png", "webp"}:
        return value
    raise ValueError(f"Unsupported output format: {output_format}")


def costume_colors(costume: str) -> str:
    colors = []
    for token in ("黑", "白", "灰", "粉", "红", "蓝", "藏青", "深色", "米白", "酒红", "珍珠白"):
        if token in costume:
            colors.append(token)
    return "、".join(dict.fromkeys(colors)) or "低饱和写实色彩，按固定服装描述执行"


def costume_materials(costume: str) -> str:
    materials = []
    for token in ("丝质", "丝绸", "棉", "针织", "羊毛", "皮革", "制服", "西装", "礼服", "披肩", "布料"):
        if token in costume:
            materials.append(token)
    return "、".join(dict.fromkeys(materials)) or "写实布料材质，按固定服装描述执行"


WARDROBE_DETAIL_TOKENS = (
    "服装",
    "衣",
    "外套",
    "礼服",
    "校服",
    "西装",
    "衬衫",
    "领带",
    "裙",
    "披肩",
    "丝绸",
    "丝质",
    "布料",
    "材质",
    "穿",
    "手袋",
)


def identity_anchor_without_wardrobe(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    clauses = [part.strip() for part in re.split(r"[。；;\n]", raw) if part.strip()]
    kept = [clause for clause in clauses if not any(token in clause for token in WARDROBE_DETAIL_TOKENS)]
    return "；".join(kept[:4]) or raw.split("。", 1)[0].strip()


def appearance_clause(text: str, tokens: tuple[str, ...], fallback: str) -> str:
    raw = str(text or "")
    detail = raw.split("容貌细节：", 1)[1] if "容貌细节：" in raw else raw
    clauses = [part.strip() for part in re.split(r"[；;。]", detail) if part.strip()]
    picked = [
        clause
        for clause in clauses
        if any(token in clause for token in tokens)
        and not any(token in clause for token in WARDROBE_DETAIL_TOKENS)
    ]
    return "；".join(picked[:3]) or fallback


def build_variant_bible(
    *,
    variant_id: str,
    base_profile: dict[str, Any],
    episode_id: str,
    costume_tag: str,
    costume: str,
    applies_to_shots: list[str],
    change_event: str,
) -> dict[str, Any]:
    name = str(base_profile.get("name") or base_profile.get("character_id") or variant_id).strip()
    base_character_id = str(base_profile.get("character_id") or "").strip()
    visual_anchor = str(base_profile.get("visual_anchor") or "").strip()
    appearance_lock = base_profile.get("appearance_lock_profile") if isinstance(base_profile.get("appearance_lock_profile"), dict) else {}
    face = str(
        appearance_lock.get("facial_features")
        or appearance_clause(visual_anchor, ("脸", "眼", "眉", "鼻", "唇", "五官"), f"{name}基础角色脸部特征")
    ).strip()
    hair = str(
        appearance_lock.get("hair_style_color")
        or appearance_clause(visual_anchor, ("发",), "沿用基础角色发型，保持连续")
    ).strip()
    skin = str(appearance_lock.get("skin_texture") or "真实皮肤纹理，低饱和自然肤色").strip()
    body = str(
        appearance_lock.get("body_shape")
        or appearance_lock.get("posture_gait")
        or appearance_clause(visual_anchor, ("身形", "体态", "肩", "站姿"), "沿用基础角色体态和年龄观感")
    ).strip()
    shot_text = "、".join(applies_to_shots)
    continuity = f"用于 {episode_id} {shot_text}，保持这一套服装"
    if change_event:
        continuity = f"{continuity}；换装事件：{change_event}"

    return {
        "version": 1,
        "asset_type": "character_costume_variant",
        "id": variant_id,
        "base_character_id": base_character_id,
        "base_lock_profile_id": str(base_profile.get("lock_profile_id") or "").strip(),
        "name": name,
        "episode_id": episode_id,
        "costume_tag": costume_tag,
        "applies_to_shots": applies_to_shots,
        "created_at": datetime.now().isoformat(),
        "source_policy": "record_is_source_of_truth; costume_variant_changes_wardrobe_only",
        "age_band": "沿用基础角色明确年龄段",
        "face_geometry": f"沿用{name}基础角色脸型骨相，不换脸",
        "hair_silhouette": hair,
        "body_frame": body,
        "wardrobe_signature": costume,
        "proportion_contract": "保持基础角色写实年龄比例和自然真人体态，不因换装改变年龄或身材。",
        "appearance": {
            "face_shape": f"必须保持{name}基础角色脸型，不换脸",
            "facial_features": face,
            "hair": hair,
            "skin": skin,
            "body": body,
            "expression": "表情符合当前剧情，但身份气质沿用基础角色",
        },
        "costume": {
            "fixed_outfit": costume,
            "colors": costume_colors(costume),
            "materials": costume_materials(costume),
            "wardrobe_continuity": continuity,
        },
        "portrait_prompt": (
            f"{name}同一人物，换装变体参考图，只改变服装不改变脸、年龄、发型、肤质或体态。"
            f"固定服装：{costume}。三分之二正面，脸部清晰，服装轮廓清楚，"
            "人物衣着完整，浅灰白色无缝摄影棚背景，不出现城市、酒店、酒吧、街道、房间、家具或可识别地点，"
            "朴素克制呈现，写实电影感，低饱和自然光影。"
        ),
        "distinction_anchors": [
            f"同一{name}身份",
            "只改变服装",
            "保持基础角色脸型、五官、发型、肤质和体态",
        ],
        "pairwise_forbidden_similarity": [
            "不要换脸",
            "不要变成年龄不同的人",
            "不要继承其他角色的脸型、发型或气质",
        ],
    }


def build_profile_md(variant_id: str, bible: dict[str, Any], base_profile: dict[str, Any]) -> str:
    identity_anchor = identity_anchor_without_wardrobe(str(base_profile.get("visual_anchor") or "").strip())
    return f"""# {variant_id}

角色：{bible.get("name", variant_id)}
用途：{bible.get("episode_id", "")} 服装变体参考图。
基础角色：{bible.get("base_character_id", "")}

【身份规则】
这是基础角色的 costume variant reference。必须沿用基础角色身份、脸型、五官、发型、肤质、年龄和体态，只改变服装。

【基础身份锚点】
{identity_anchor}

【固定服装】
{bible.get("costume", {}).get("fixed_outfit", "")}

【适用镜头】
{"、".join(str(x) for x in bible.get("applies_to_shots", []) if str(x).strip())}
"""


def build_scoped_image_map(
    *,
    base_profile: dict[str, Any],
    variant_image_rel: str,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key in alias_values(base_profile, include_anchor_tokens=False):
        mapping[key] = variant_image_rel
    return mapping


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, help="Project root containing assets/characters and character_image_map.json.")
    parser.add_argument("--episode-root", default="", help="Execution dir containing records and 35_character_lock_profiles_v1.json.")
    parser.add_argument("--character-id", default="", help="Base character_id, e.g. MISAKI_FEMALE.")
    parser.add_argument("--character-name", default="", help="Base character display name, e.g. 佐藤美咲.")
    parser.add_argument("--lock-profile-id", default="", help="Base lock_profile_id if known.")
    parser.add_argument("--episode-id", required=True, help="Episode id, e.g. EP02.")
    parser.add_argument("--costume-tag", required=True, help="Stable tag for this outfit, e.g. OLD_PINK_DRESS.")
    parser.add_argument("--costume", required=True, help="Single fixed costume description.")
    parser.add_argument("--applies-to-shots", required=True, help="Comma/space separated shot ids.")
    parser.add_argument("--change-event", default="", help="Optional shot-level costume change event.")
    parser.add_argument("--output-format", default="jpeg", choices=["jpeg", "jpg", "png", "webp"])
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if contains_ambiguous_wardrobe(args.costume):
        raise ValueError("Costume description contains ambiguous wardrobe choices such as 或/or/候选/二选一.")

    project_root = resolve_repo_path(args.project_root)
    episode_root = resolve_repo_path(args.episode_root) if str(args.episode_root or "").strip() else None
    characters_dir = project_root / "assets" / "characters"
    characters_dir.mkdir(parents=True, exist_ok=True)

    base_profile = find_base_profile(
        project_root=project_root,
        episode_root=episode_root,
        character_id=str(args.character_id or "").strip(),
        character_name=str(args.character_name or "").strip(),
        lock_profile_id=str(args.lock_profile_id or "").strip(),
    )
    base_character_id = str(base_profile.get("character_id") or args.character_id or args.character_name).strip()
    variant_id = safe_id(f"{base_character_id}_{args.episode_id}_{args.costume_tag}")
    shots = [safe_id(item) for item in split_csv(args.applies_to_shots)]
    ext = image_ext(args.output_format)

    bible = build_variant_bible(
        variant_id=variant_id,
        base_profile=base_profile,
        episode_id=str(args.episode_id).strip().upper(),
        costume_tag=safe_id(args.costume_tag),
        costume=str(args.costume).strip(),
        applies_to_shots=shots,
        change_event=str(args.change_event or "").strip(),
    )

    profile_path = characters_dir / f"{variant_id}.profile.md"
    bible_path = characters_dir / f"{variant_id}.visual_bible.json"
    image_path = characters_dir / f"{variant_id}.{ext}"
    maps_dir = characters_dir / "costume_variant_maps"
    shot_part = "_".join(shots) if shots else "SHOTS"
    scoped_map_path = maps_dir / f"character_image_map_{variant_id}_{shot_part}.json"

    write_text(profile_path, build_profile_md(variant_id, bible, base_profile), overwrite=bool(args.overwrite))
    write_json(bible_path, bible, overwrite=bool(args.overwrite))
    write_json(
        scoped_map_path,
        build_scoped_image_map(base_profile=base_profile, variant_image_rel=rel(image_path)),
        overwrite=bool(args.overwrite),
    )

    manifest = {
        "created_at": datetime.now().isoformat(),
        "variant_id": variant_id,
        "base_character": {
            "character_id": base_profile.get("character_id", ""),
            "name": base_profile.get("name", ""),
            "lock_profile_id": base_profile.get("lock_profile_id", ""),
        },
        "episode_id": bible["episode_id"],
        "applies_to_shots": shots,
        "profile_path": rel(profile_path),
        "visual_bible_path": rel(bible_path),
        "expected_image_path": rel(image_path),
        "shot_scoped_character_image_map": rel(scoped_map_path),
        "generate_command": (
            "python3 scripts/character_image_gen.py "
            f"--characters-dir {rel(characters_dir)} "
            f"--characters {variant_id} "
            "--image-model grok "
            f"--output-format {args.output_format} --quality high --overwrite"
        ),
    }
    manifest_path = characters_dir / f"{variant_id}.costume_variant_manifest.json"
    write_json(manifest_path, manifest, overwrite=bool(args.overwrite))

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
