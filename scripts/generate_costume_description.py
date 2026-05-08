#!/usr/bin/env python3
"""Generate production-grade costume descriptions from fixed outfit facts.

This utility is intentionally deterministic. It expands a short, record-backed
costume fact into a stable Chinese description block suitable for costume
variant reference images.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


AMBIGUOUS_TOKENS = ("或", "或者", "任选", "候选", "二选一", " or ", " either ")


@dataclass
class CostumeSpec:
    title: str
    costume: str
    character: str = ""
    role: str = ""
    scene_context: str = ""
    mood: str = ""
    materials: str = ""
    colors: str = ""
    patterns: str = ""
    motif: str = ""
    silhouette: str = ""
    accessories: str = ""
    footwear: str = ""
    styling: str = ""
    avoid: str = ""


def clean(value: Any) -> str:
    return str(value or "").strip()


def unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def has_ambiguous_choice(text: str) -> bool:
    lowered = f" {text.lower()} "
    return any(token in text or token in lowered for token in AMBIGUOUS_TOKENS)


def split_items(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[、,，;；]+", value) if item.strip()]


def contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def infer_colors(costume: str) -> str:
    palette: list[str] = []
    color_map = [
        ("酒红", "酒红"),
        ("玫瑰", "暗玫瑰红"),
        ("藏青", "藏青"),
        ("深灰", "深灰"),
        ("黑灰", "黑灰"),
        ("旧银", "旧银灰"),
        ("黑色", "低调黑"),
        ("白色", "白"),
        ("珍珠", "低光泽珍珠白"),
        ("米", "米白"),
        ("灰", "烟灰"),
        ("红", "低饱和红"),
        ("蓝", "深蓝"),
    ]
    for token, label in color_map:
        if token in costume:
            palette.append(label)
    return "、".join(unique(palette)) or "低饱和主色、暗灰、旧白"


def infer_materials(costume: str) -> str:
    materials: list[str] = []
    material_map = [
        ("丝质", "低光泽丝缎"),
        ("丝绸", "旧丝绸混纺"),
        ("礼服", "柔软礼服内衬"),
        ("外套", "磨旧薄呢或旧羊毛"),
        ("校服", "制服呢料"),
        ("衬衫", "白色棉质衬衫布"),
        ("棉", "高支棉府绸"),
        ("皮革", "低光泽磨旧皮革"),
        ("手袋", "旧皮革配件"),
        ("领带", "低光泽织纹丝质混纺"),
        ("西装", "哑光通勤羊毛混纺"),
        ("平底鞋", "哑光皮革鞋面"),
    ]
    for token, label in material_map:
        if token in costume:
            materials.append(label)
    return "、".join(unique(materials)) or "写实布料、平整内衬、低光泽纤维"


def infer_patterns(costume: str) -> str:
    if contains_any(costume, ("校服", "制服")):
        return "素面制服布料，可带极细制服织纹"
    if contains_any(costume, ("旧", "姐姐")):
        return "轻微旧织纹、微皱布面和局部磨损形成层次"
    if contains_any(costume, ("丝质", "丝绸", "礼服")):
        return "无大面积花纹，以丝缎自然光泽和细密织纹呈现层次"
    if contains_any(costume, ("西装", "衬衫", "领带")):
        return "哑光通勤织纹，领带可有极细低光泽纹理"
    return "素面低饱和纹理，避免夸张图案"


def infer_motif(costume: str, mood: str) -> str:
    if contains_any(costume, ("校服", "制服")):
        return "学生制服结构和整洁日常感"
    if contains_any(costume, ("旧", "姐姐")):
        return "旧衣物痕迹、记忆继承和压抑守护感"
    if contains_any(costume, ("酒红", "丝质", "礼服")):
        return "银座夜场旧梦感与烛光反射"
    if contains_any(costume, ("西装", "领带")):
        return "普通通勤疲惫感与被反复触碰的领带记忆"
    return clean(mood) or "角色当集剧情气质和写实服装稳定性"


def infer_silhouette(costume: str) -> str:
    if contains_any(costume, ("校服", "制服")):
        return "标准学生制服轮廓，领口端正，比例清洁自然"
    if contains_any(costume, ("旧礼服", "短外套")):
        return "修长旧礼服叠加短外套，肩线略窄，整体收敛"
    if contains_any(costume, ("丝质礼服", "酒红")):
        return "成熟优雅的夜场礼服轮廓，腰线轻收，下摆自然垂顺"
    if contains_any(costume, ("西装", "通勤")):
        return "普通通勤西装轮廓，肩部略疲惫，领带略松"
    return "上身轮廓清楚，服装层次稳定，动作时不变形"


def infer_accessories(costume: str) -> str:
    accessories: list[str] = []
    if "耳钉" in costume or "珠饰" in costume:
        accessories.append("低光泽珠饰耳钉")
    if "手袋" in costume:
        accessories.append("黑色旧皮革短提手手袋")
    if "领带" in costume:
        accessories.append("深色低光泽领带")
    if "校服" in costume:
        accessories.append("哑光纽扣和朴素学生配件")
    return "、".join(unique(accessories)) or "低调配件，不抢服装主体"


def infer_footwear(costume: str) -> str:
    if "平底鞋" in costume:
        return "低调黑色平底鞋"
    if "皮鞋" in costume:
        return "普通黑色商务皮鞋"
    if contains_any(costume, ("校服", "制服")):
        return "黑色学生皮鞋或简单深色平底鞋"
    if contains_any(costume, ("礼服", "酒红")):
        return "低调黑色或酒红色细跟鞋"
    return "与主色一致的低调鞋履"


def infer_styling(costume: str, character: str) -> str:
    if contains_any(costume, ("校服", "制服")):
        return "朴素学生发型，自然直发、齐肩发或低马尾，不搭配浓妆"
    if "佐藤彩花" in character or contains_any(costume, ("酒红", "丝质礼服")):
        return "柔顺深色长发，精致但不过浓的妆容"
    if "佐藤美咲" in character or contains_any(costume, ("旧礼服", "短外套")):
        return "自然深色中长发，表情警觉克制，妆容极淡"
    return "发型和妆容沿用角色身份锚点，保持写实自然"


def infer_avoid(costume: str) -> str:
    avoid = ["候选服装", "二选一服饰", "角色年龄与脸型漂移"]
    if contains_any(costume, ("校服", "制服")):
        avoid.extend(["成人化呈现", "夜场材质", "浓妆"])
    if contains_any(costume, ("旧礼服", "短外套")):
        avoid.extend(["崭新舞台感", "华丽新礼服", "明亮表演服"])
    if contains_any(costume, ("酒红", "丝质礼服")):
        avoid.extend(["暴露化处理", "夸张亮片", "其他颜色礼服"])
    return "、".join(unique(avoid))


def pattern_sentence(patterns: str) -> str:
    value = clean(patterns)
    if value.startswith("无大面积花纹，以"):
        return f"衣身不依赖大面积图案，主要通过{value.removeprefix('无大面积花纹，以')}建立视觉层次"
    return f"衣身通过{value}建立视觉层次"


def complete_spec(raw: dict[str, Any]) -> CostumeSpec:
    spec = CostumeSpec(
        title=clean(raw.get("title")),
        costume=clean(raw.get("costume") or raw.get("fixed_outfit")),
        character=clean(raw.get("character") or raw.get("name")),
        role=clean(raw.get("role")),
        scene_context=clean(raw.get("scene_context") or raw.get("context")),
        mood=clean(raw.get("mood")),
        materials=clean(raw.get("materials")),
        colors=clean(raw.get("colors")),
        patterns=clean(raw.get("patterns")),
        motif=clean(raw.get("motif") or raw.get("pattern_theme")),
        silhouette=clean(raw.get("silhouette")),
        accessories=clean(raw.get("accessories")),
        footwear=clean(raw.get("footwear")),
        styling=clean(raw.get("styling")),
        avoid=clean(raw.get("avoid")),
    )
    if not spec.costume:
        raise ValueError("Missing required costume/fixed_outfit.")
    if has_ambiguous_choice(spec.costume):
        raise ValueError(f"Ambiguous costume choices are not allowed: {spec.costume}")
    if not spec.title:
        base = spec.character or "角色"
        cue = split_items(spec.costume)[0] if split_items(spec.costume) else "固定服装"
        spec.title = f"{base}·{cue}"
    spec.materials = spec.materials or infer_materials(spec.costume)
    spec.colors = spec.colors or infer_colors(spec.costume)
    spec.patterns = spec.patterns or infer_patterns(spec.costume)
    spec.motif = spec.motif or infer_motif(spec.costume, spec.mood)
    spec.silhouette = spec.silhouette or infer_silhouette(spec.costume)
    spec.accessories = spec.accessories or infer_accessories(spec.costume)
    spec.footwear = spec.footwear or infer_footwear(spec.costume)
    spec.styling = spec.styling or infer_styling(spec.costume, spec.character)
    spec.avoid = spec.avoid or infer_avoid(spec.costume)
    return spec


def render_description(spec: CostumeSpec) -> str:
    context = f"，用于{spec.scene_context}" if spec.scene_context else ""
    role = f"，贴合{spec.role}" if spec.role else ""
    mood = spec.mood or "低饱和写实电影感"
    return "\n".join(
        [
            f"**{spec.title}**",
            f"材质：{spec.materials}；颜色：{spec.colors}；花纹：{spec.patterns}；图案：{spec.motif}。",
            (
                f"这套{spec.title}以{spec.materials}作为主要材质，配色围绕{spec.colors}展开{context}{role}。"
                f"服装核心必须固定为：{spec.costume}。整体表面避免过度闪耀，布面在写实光线下呈现细腻层次，"
                f"让角色在近景、半身和膝上构图中都能保持清晰稳定的服饰识别。{pattern_sentence(spec.patterns)}，"
                f"领口、袖口、下摆和开合位置保持规整，缝线、边缘、纽扣或扣件都应低调耐看，不抢人物脸部。"
                f"整体版型强调{spec.silhouette}，动作时服装只产生自然褶皱和轻微垂坠，不改变主轮廓。"
                f"穿着触感上，内衬平整服帖，外层材质有真实厚薄和重量，接触皮肤处细滑不扎，"
                f"行走、转身或抬手时既有包裹感也保留自然活动余量。配件建议使用{spec.accessories}，"
                f"鞋履选择{spec.footwear}，发型与妆容保持{spec.styling}。整体气质是{mood}，"
                f"生成参考图时必须保持衣着完整、角色身份稳定、服装细节可见；避免{spec.avoid}。"
            ),
        ]
    )


def read_batch(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        if isinstance(data.get("costumes"), list):
            return [item for item in data["costumes"] if isinstance(item, dict)]
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    raise ValueError("Batch input must be a JSON object, object with costumes[], or list.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", default="", help="Optional JSON file for one or more costume specs.")
    parser.add_argument("--output", default="", help="Optional markdown output path.")
    parser.add_argument("--title", default="")
    parser.add_argument("--costume", default="", help="Required unless --input-json is used.")
    parser.add_argument("--character", default="")
    parser.add_argument("--role", default="")
    parser.add_argument("--scene-context", default="")
    parser.add_argument("--mood", default="")
    parser.add_argument("--materials", default="")
    parser.add_argument("--colors", default="")
    parser.add_argument("--patterns", default="")
    parser.add_argument("--motif", default="")
    parser.add_argument("--silhouette", default="")
    parser.add_argument("--accessories", default="")
    parser.add_argument("--footwear", default="")
    parser.add_argument("--styling", default="")
    parser.add_argument("--avoid", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.input_json:
        specs = [complete_spec(item) for item in read_batch(Path(args.input_json))]
    else:
        specs = [
            complete_spec(
                {
                    "title": args.title,
                    "costume": args.costume,
                    "character": args.character,
                    "role": args.role,
                    "scene_context": args.scene_context,
                    "mood": args.mood,
                    "materials": args.materials,
                    "colors": args.colors,
                    "patterns": args.patterns,
                    "motif": args.motif,
                    "silhouette": args.silhouette,
                    "accessories": args.accessories,
                    "footwear": args.footwear,
                    "styling": args.styling,
                    "avoid": args.avoid,
                }
            )
        ]
    output = "\n\n".join(render_description(spec) for spec in specs).rstrip() + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
