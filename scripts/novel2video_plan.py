#!/usr/bin/env python3
"""Create a novel-to-video planning bundle under the novel folder.

The planner is intentionally data-first: it reads one novel markdown file,
builds a project bible, builds an episode plan, renders the legacy Markdown /
JSON artifacts that downstream scripts already consume, and runs lightweight QA
against the planned bundle.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

try:
    import requests
except Exception:  # pragma: no cover - requests is optional for llm fallback.
    requests = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
NOVEL_ROOT = REPO_ROOT / "novel"
TEMPLATE_ROOT = REPO_ROOT / "SampleChapter_项目文件整理版"
DEFAULT_MODEL = "bytedance/seedance-2.0/text-to-video"
DEFAULT_NEGATIVE_PROMPT = [
    "cartoon",
    "anime",
    "game-like rendering",
    "plastic skin",
    "setting-inconsistent clothing, architecture, or props",
    "over-beautification",
    "over-saturation",
    "deformed hands",
    "deformed face",
    "extra limbs",
    "watermark",
    "logo",
    "low definition",
    "severe noise",
    "flicker",
    "jump frames",
    "continuity break",
]
STATIC_PROP_NEGATIVE_PROMPT = [
    "appearing objects",
    "disappearing objects",
    "objects drifting",
    "sliding props",
    "objects popping into existence",
    "objects emerging from floor",
    "cups emerging from floor",
    "duplicate cups",
    "extra cups",
    "floating props",
    "morphing props",
]
STATIC_PROP_STABILITY_RULES = [
    "所有道具从第一帧开始已经存在，禁止新增、消失、漂移、滑动、弹出、从地面冒出",
    "视频中不要再增加道具",
]
SCENE_MOTION_FORBIDDEN = [
    "场景道具自行新增",
    "场景道具自行消失",
    "场景道具漂移",
    "场景道具滑动",
    "场景道具弹出",
    "场景道具从地面冒出",
    "非人物操纵的物体运动",
]
DEFAULT_LANGUAGE_POLICY = {
    "spoken_language": "zh-CN",
    "spoken_language_label": "普通话中文",
    "subtitle_language": "zh-CN",
    "subtitle_language_label": "简体中文字幕",
    "screen_text_language": "zh-CN",
    "model_audio_language": "zh-CN",
    "voice_language_lock": "Mandarin Chinese only. No Japanese, English, or mixed-language speech.",
    "screen_text_language_lock": "Simplified Chinese subtitles only.",
    "environment_signage_language": "ja-JP allowed only as silent background signage.",
    "forbidden_spoken_languages": ["ja-JP", "en-US"],
    "rules": [
        "所有角色对白、旁白、模型音频必须使用普通话中文。",
        "不得生成日语、英语或中日混杂的 spoken audio。",
        "屏幕字幕只使用简体中文。",
        "东京/银座环境可以出现日文招牌，但只能作为无声背景环境文字，不能成为对白、旁白或字幕。",
    ],
}

SAMPLE_CHAPTER_FORBIDDEN_DRIFT = [
    "武侠侠客感",
    "江湖疗伤",
    "包扎腿伤",
    "医女救治",
    "药碗",
    "毒药粉末",
    "神秘阴谋",
    "雪地误读",
    "骨灰误读",
    "成熟侠客或将军气质",
]

SAMPLE_CHAPTER_EP01_TRUTH = [
    "林辰是现代社畜灵魂，刚穿越到西汉长安城外的乞丐少年身体里。",
    "林辰此时核心困境是饥饿虚弱、快要饿死，不是战斗受伤。",
    "阿翠是清贫青梅，端来稀粥，守了林辰两天，是开局唯一善意。",
    "这碗粥是救命的稀粥，不是药，也不是疗伤仪式。",
    "林辰在溪边发现白色盐渍，意识到可以用现代知识提盐赚钱。",
    "集尾钩子是明天不讨饭、去做买卖赚第一笔钱。",
]

ENDING_HOOK_KEYWORDS = [
    "进城",
    "赚钱",
    "买",
    "卖",
    "查",
    "真相",
    "秘密",
    "明天",
    "今晚",
    "等着",
    "活路",
    "小樱",
    "记录",
    "对不上",
    "不一致",
    "嫌疑",
    "监控",
    "排除",
]
GENERIC_SHOT_PLACEHOLDERS = [
    "第2集核心场景",
    "人物目标亮相",
    "关系压力入场",
    "关键证据或道具出现",
    "第一次正面冲突",
    "主角被迫解释",
    "对方隐藏信息",
    "秘密被外化成行动",
    "情绪临界点",
    "新线索压近",
]
I2V_VAGUE_PROP_TERMS = [
    "散落",
    "散乱",
    "零散",
    "数个",
    "若干",
    "一些",
    "多个",
    "scattered",
    "several",
    "some",
    "a few",
]
I2V_NEGATIVE_SAFETY_TERMS = [
    "不出现裸露",
    "无裸露",
    "裸露",
    "性暗示",
    "情色",
    "色情",
    "sexual suggestion",
    "nudity",
]
I2V_COMPLEX_ACTION_TERMS = [
    "走向",
    "走去",
    "走进",
    "开门",
    "打开门",
    "推门",
    "推开",
    "接起",
    "拿起",
    "捡起",
    "递给",
    "递出",
    "放下",
    "摊开",
    "翻动",
    "打开",
    "转身",
    "站起",
]
I2V_PROP_DIMENSION_TERMS = [
    "cm",
    "厘米",
    "毫米",
    "mm",
    "米",
    "长",
    "宽",
    "高",
    "尺寸",
    "大小",
    "约",
    "x",
    "×",
]
I2V_PROP_APPEARANCE_TERMS = [
    "颜色",
    "色",
    "材质",
    "皮",
    "金属",
    "玻璃",
    "纸",
    "布",
    "丝",
    "木",
    "塑料",
    "棉",
    "绒",
]
I2V_PHONE_INWARD_TERMS = [
    "屏幕朝内",
    "屏幕面向持有者",
    "屏幕朝向持有者",
    "屏幕不朝向镜头",
    "屏幕内容不可见",
    "screen facing inward",
    "screen not visible",
    "screen content not visible",
]
KEYFRAME_STATIC_FRAME_GUARD = (
    "首帧静态构图约束：只生成一个连续完整的单一画面，只表现这一镜头的起始瞬间；"
    "不要拼贴、不要多格漫画、不要分屏、不要contact sheet、不要插入镜头、不要闪回画面、不要同图呈现多个时间点。"
)
KEYFRAME_STATIC_MOVEMENT = "固定机位或极轻微稳定镜头"
KEYFRAME_NEGATIVE_PROMPT = [
    "collage",
    "split screen",
    "multi-panel",
    "comic panels",
    "contact sheet",
    "storyboard layout",
]
KEYFRAME_TEMPORAL_SPLIT_RE = re.compile(r"[；;。.!！?？]\s*")
KEYFRAME_CLAUSE_SPLIT_RE = re.compile(r"[，,；;。.!！?？]\s*")
KEYFRAME_UNSAFE_FRAGMENT_TOKENS = (
    "随后",
    "之后",
    "然后",
    "最后",
    "最终",
    "转到",
    "转入",
    "进入后",
    "后段",
    "响起后",
    "回答后",
    "敲门声",
    "门外忽然",
    "猛地",
    "走向",
    "走去",
    "推门",
    "推开",
    "接起",
    "下滑",
    "听见",
    "听到",
    "传出",
    "插入",
    "闪回",
    "回忆近景",
    "回忆",
    "多个时间点",
    "分屏",
    "多格",
    "拼贴",
    "contact sheet",
)
KEYFRAME_UNSAFE_MOVEMENT_TOKENS = (
    "插入",
    "闪回",
    "转",
    "跟拍",
    "推进",
    "推近",
    "横移",
)
KEYFRAME_FIRST_FRAME_HINT_TOKENS = (
    "首帧",
    "静止",
    "坐",
    "站",
    "手袋",
    "照片",
    "桌面",
    "调查室",
    "门口",
    "走廊",
    "街道",
    "卧室",
    "可见",
)


@dataclass(frozen=True)
class ProjectPaths:
    out_dir: Path
    novel_dir: Path
    character_assets_dir: Path
    method_dir: Path
    template_dir: Path
    input_dir: Path
    structure_dir: Path
    script_dir: Path
    execution_dir: Path
    packaging_dir: Path
    records_dir: Path


@dataclass(frozen=True)
class ProjectSource:
    novel_path: str
    canonical_source_path: str
    project_name: str
    title: str
    text: str
    headings: list[tuple[int, str]]
    chapter_titles: list[str]
    source_excerpts: list[str]


@dataclass(frozen=True)
class Character:
    character_id: str
    lock_profile_id: str
    name: str
    visual_anchor: str
    persona_anchor: list[str]
    speech_style_anchor: list[str]


@dataclass(frozen=True)
class ProjectBible:
    project_name: str
    title: str
    platform: str
    setting: str
    core_selling_points: list[str]
    logline: str
    story_stages: list[str]
    episode_outlines: list[dict[str, Any]]
    relationships: list[str]
    visual_baseline: str
    language_policy: dict[str, Any]
    characters: list[Character]
    safety_note: str
    generation_notes: list[str]


@dataclass(frozen=True)
class EpisodePlan:
    episode_id: str
    episode_number: int
    episode_label: str
    title: str
    goal: str
    conflict: str
    emotions: list[str]
    hook: str
    source_basis: list[str]
    story_function: str


@dataclass(frozen=True)
class ShotPlan:
    shot_id: str
    priority: str
    intent: str
    duration_sec: int
    shot_type: str
    movement: str
    framing_focus: str
    action_intent: str
    emotion_intent: str
    scene_id: str
    scene_name: str
    dialogue: list[dict[str, Any]]
    narration: list[str]
    subtitle: list[str]
    positive_core: str
    source_basis: str = ""
    first_frame_contract: dict[str, Any] | None = None
    dialogue_blocking: dict[str, Any] | None = None
    i2v_contract: dict[str, Any] | None = None


@dataclass(frozen=True)
class ArtifactSpec:
    path: Path
    category: str
    scope: str
    dependencies: list[str]
    project_specific: bool


@dataclass(frozen=True)
class LLMRunResult:
    backend: str
    provider: str
    model: str
    dry_run: bool
    request_files: list[str]
    fallbacks: list[dict[str, str]]
    applied: bool = False


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def write_text(path: Path, content: str, overwrite: bool) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return True


def write_json(path: Path, data: dict[str, Any], overwrite: bool) -> bool:
    return write_text(path, json.dumps(data, ensure_ascii=False, indent=2), overwrite)


def slug_to_pascal(value: str) -> str:
    tokens = [token for token in re.split(r"[^A-Za-z0-9]+", value.strip()) if token]
    if not tokens:
        return "NovelProject"
    return "".join(token[:1].upper() + token[1:] for token in tokens)


def safe_filename_name(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", value.strip())
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned or "NovelProject"


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def project_paths(out_dir: Path, novel_dir: Path) -> ProjectPaths:
    return ProjectPaths(
        out_dir=out_dir,
        novel_dir=novel_dir,
        character_assets_dir=novel_dir / "assets" / "characters",
        method_dir=out_dir / "01_总方法论与项目底层文档",
        template_dir=out_dir / "02_模板与通用执行文档",
        input_dir=out_dir / "03_当前项目的原始输入文档",
        structure_dir=out_dir / "04_当前项目的诊断与结构设计文档",
        script_dir=out_dir / "05_当前项目的剧本与镜头层文档",
        execution_dir=out_dir / "06_当前项目的视觉与AI执行层文档",
        packaging_dir=out_dir / "07_当前项目的包装与生产任务单文档",
        records_dir=out_dir / "06_当前项目的视觉与AI执行层文档" / "records",
    )


def parse_markdown_headings(text: str) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            headings.append((len(match.group(1)), match.group(2).strip()))
    return headings


def excerpt(text: str, max_chars: int = 1000) -> str:
    compact = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "\n..."


def split_source_excerpts(text: str, max_items: int = 8) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    excerpts: list[str] = []
    for para in paragraphs:
        if len(para) < 40:
            continue
        excerpts.append(excerpt(para, 360))
        if len(excerpts) >= max_items:
            break
    if not excerpts and text.strip():
        excerpts.append(excerpt(text, 500))
    return excerpts


def detect_title(novel_path: Path, text: str) -> str:
    headings = parse_markdown_headings(text)
    for level, heading in headings:
        if level == 1:
            return heading.strip()
    for _, heading in headings:
        if "·" in heading:
            title = heading.split("·", 1)[1].strip()
            if title:
                return title
    for level, heading in headings:
        if level <= 3 and not re.match(r"^(第?[0-9一二三四五六七八九十]+[.、章]|第一卷)", heading):
            title = re.sub(r"^[一二三四五六七八九十0-9]+[.、]\s*", "", heading).strip()
            if title:
                return title
    return novel_path.stem


def extract_chapter_titles(headings: list[tuple[int, str]]) -> list[str]:
    titles: list[str] = []
    for level, heading in headings:
        if level > 3:
            continue
        clean = re.sub(r"^\s*第[一二三四五六七八九十百0-9]+[卷章][\s·：:、-]*", "", heading).strip()
        clean = re.sub(r"^\s*[0-9一二三四五六七八九十]+[.、]\s*", "", clean).strip()
        if clean and clean not in titles:
            titles.append(clean)
    return titles


def normalize_heading_title(value: str) -> str:
    clean = re.sub(r"^\s*#+\s*", "", value).strip()
    clean = re.sub(r"^\s*第[一二三四五六七八九十百0-9]+[卷章集][\s·：:、.-]*", "", clean).strip()
    clean = re.sub(r"^\s*[0-9一二三四五六七八九十]+[.、]\s*", "", clean).strip()
    return clean


def extract_markdown_section_by_title(text: str, title: str) -> str:
    target = normalize_heading_title(title)
    if not target:
        return ""
    lines = text.splitlines()
    starts: list[tuple[int, int, str]] = []
    for idx, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            starts.append((idx, len(match.group(1)), match.group(2).strip()))
    for pos, (idx, level, heading) in enumerate(starts):
        normalized = normalize_heading_title(heading)
        if target != normalized and target not in normalized and normalized not in target:
            continue
        end = len(lines)
        for next_idx, next_level, _ in starts[pos + 1 :]:
            if next_level <= level:
                end = next_idx
                break
        return "\n".join(lines[idx:end]).strip()
    return ""


def extract_episode_source_text(source: ProjectSource, episode_plan: EpisodePlan, max_chars: int = 16000) -> str:
    sections: list[str] = []
    candidates = [episode_plan.title, *episode_plan.source_basis]
    for candidate in candidates:
        section = extract_markdown_section_by_title(source.text, candidate)
        if section and section not in sections:
            sections.append(section)
    if not sections:
        number_pattern = rf"^\s*##+\s*{episode_plan.episode_number}[.、]\s+"
        lines = source.text.splitlines()
        for idx, line in enumerate(lines):
            if re.match(number_pattern, line):
                end = len(lines)
                for next_idx in range(idx + 1, len(lines)):
                    if re.match(r"^##+\s+", lines[next_idx]):
                        end = next_idx
                        break
                sections.append("\n".join(lines[idx:end]).strip())
                break
    if not sections:
        return excerpt(source.text, max_chars)
    return excerpt("\n\n".join(sections), max_chars)


def render_ep01_continuity_reference(source: ProjectSource, bible: ProjectBible, shot_count: int) -> str:
    ep01_plan = build_episode_plan(bible, "EP01")
    ep01_shots = build_shot_plan(source, bible, ep01_plan, min(shot_count, 13))
    rows = [
        "| 镜头 | 地点 | 人物/动作 | 画面重点 | 声音/字幕 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for shot in ep01_shots:
        dialogue = " / ".join(f"{d.get('speaker', '')}：{d.get('text', '')}" for d in shot.dialogue)
        audio = dialogue or " / ".join(shot.subtitle or shot.narration)
        rows.append(f"| {shot.shot_id} | {shot.scene_name} | {shot.action_intent} | {shot.framing_focus} | {audio} |")
    return "\n".join(rows)


def load_project_source(novel_path: Path, project_name: str, project_title: str) -> ProjectSource:
    text = read_text(novel_path)
    headings = parse_markdown_headings(text)
    title = project_title.strip() or detect_title(novel_path, text)
    return ProjectSource(
        novel_path=str(novel_path),
        canonical_source_path=str(novel_path),
        project_name=project_name,
        title=title,
        text=text,
        headings=headings,
        chapter_titles=extract_chapter_titles(headings),
        source_excerpts=split_source_excerpts(text),
    )


def is_sample_chapter_source(text: str) -> bool:
    return "林辰" in text and "阿翠" in text and ("盐渍" in text or "穿越乞丐" in text)


def detect_setting(text: str) -> str:
    if any(token in text for token in ("银座", "酒店", "警视厅", "刑警", "俱乐部")):
        return "现代日本都市悬疑，银座夜场与酒店空间，写实电影感"
    if is_sample_chapter_source(text):
        return "古代中国西汉长安城外，底层乞丐破庙与溪边求生，写实电影感"
    if any(token in text for token in ("王朝", "县令", "古代")):
        return "古代社会权力冲突，底层人物逆转命运，写实电影感"
    return "现代都市，现实主义短剧，写实电影感"


def detect_characters(text: str) -> list[Character]:
    ginza_names = [
        ("ISHIKAWA_DETECTIVE", "ISHIKAWA_DETECTIVE_LOCK_V1", "石川悠一", "三十多岁日本刑警，冷静克制，深色西装，眼神温和但洞察力强。别名：石川", ["冷静", "敏锐", "克制"], ["短句", "平静", "压迫感"]),
        ("KENICHI_MAIN", "KENICHI_MAIN_LOCK_V1", "田中健一", "普通上班族，疲惫西装，领带略松，神情可靠但藏着不安", ["依附", "迟疑", "保护欲"], ["克制", "口语化", "犹豫"]),
        ("MISAKI_FEMALE", "MISAKI_FEMALE_LOCK_V1", "佐藤美咲", "清纯年轻女性，旧礼服或灰色外套，眼神警觉，柔顺外表下有防备", ["隐忍", "警觉", "守护"], ["柔顺", "短句", "回避"]),
        ("AYAKA_VICTIM", "AYAKA_VICTIM_LOCK_V1", "佐藤彩花", "银座夜场女性，丝质礼服，茉莉香水感，温柔中带操控感", ["温柔", "神秘", "控制"], ["轻柔", "试探", "低语"]),
        ("SAKURA_CHILD", "SAKURA_CHILD_LOCK_V1", "佐藤樱子", "十四岁少女，佐藤彩花的女儿，校服或日常便服，眼神稚嫩不安但逐渐信任，非情色化安全呈现。别名：小樱、樱子", ["不安", "依赖", "新生希望"], ["轻声", "困惑", "短句"]),
        ("RYUZAKI_RIVAL", "RYUZAKI_RIVAL_LOCK_V1", "龙崎", "四十出头银座俱乐部竞争者，西装笔挺，额头易出汗，表面强势但被审讯压迫", ["急促", "自保", "商业算计"], ["辩解", "急促", "提高音量"]),
        ("YAMADA_ELDER", "YAMADA_ELDER_LOCK_V1", "山田老先生", "六十出头常客，头发花白，西装领口微敞，沙哑克制，面对匿名小说线索时慌乱。别名：山田", ["遮掩", "体面", "慌乱"], ["沙哑", "防御", "短句"]),
        ("ATO_DRIVER", "ATO_DRIVER_LOCK_V1", "阿彻", "银座周边徘徊的司机或关系人，便装外套，沉默紧张，行车记录与酒店周边影像相关", ["徘徊", "紧张", "边缘嫌疑"], ["含糊", "短句", "回避"]),
        ("TARO_STREAMER", "TARO_STREAMER_LOCK_V1", "太郎", "年轻直播者或熟人，休闲街头服装，随性外放，丝巾直播截图相关的重要排除对象", ["外放", "轻率", "自证"], ["口语", "快语速", "随意"]),
    ]
    if any(name in text for _, _, name, *_ in ginza_names):
        return [
            Character(cid, lock_id, name, visual, persona, speech)
            for cid, lock_id, name, visual, persona, speech in ginza_names
        ]

    if is_sample_chapter_source(text):
        return [
            Character(
                "LINCHEN_MAIN",
                "LINCHEN_MAIN_LOCK_V1",
                "林辰",
                "18-22岁消瘦古代乞丐少年，现代社畜灵魂刚穿越，破麻布衣，脏污瘦骨，饥饿虚弱但眼神会从懵转狠",
                ["嘴硬", "不认命", "护短", "现代知识翻盘"],
                ["毒舌口语", "短句", "现代吐槽感"],
            ),
            Character(
                "ACUI_FEMALE",
                "ACUI_FEMALE_LOCK_V1",
                "阿翠",
                "16-18岁清贫布衣少女，清秀瘦弱，端稀粥救人，温柔隐忍但坚强，不是医女或侠女",
                ["温柔", "隐忍", "守护", "唯一善意"],
                ["软糯", "短句", "担心克制"],
            ),
        ]

    candidates = re.findall(r"[\u4e00-\u9fff]{2,4}", text[:8000])
    stop_words = {"清晨", "酒店", "警方", "房间", "小说", "短剧", "第一", "第二", "第三", "目标", "冲突"}
    ranked: list[str] = []
    for name in candidates:
        if name in stop_words:
            continue
        if name not in ranked:
            ranked.append(name)
        if len(ranked) >= 4:
            break
    if not ranked:
        ranked = ["主角", "关键角色A", "关键角色B"]
    return [
        Character(
            character_id=f"CHAR_{idx:02d}",
            lock_profile_id=f"CHAR_{idx:02d}_LOCK_V1",
            name=name,
            visual_anchor=f"{name}，外形来自原文线索，写实短剧角色，服装符合故事时代与阶层",
            persona_anchor=["强目标", "关系压力", "情绪可读"],
            speech_style_anchor=["口语化", "短句", "信息直给"],
        )
        for idx, name in enumerate(ranked, start=1)
    ]


def known_character_by_name(characters: list[Character]) -> dict[str, Character]:
    known: dict[str, Character] = {}
    for character in characters:
        known[character.name] = character
        for alias in character_aliases(character):
            known.setdefault(alias, character)
    return known


def normalize_character_id(value: str, name: str, idx: int, used: set[str]) -> str:
    raw = str(value or "").strip().upper()
    cleaned = re.sub(r"[^A-Z0-9]+", "_", raw).strip("_")
    if not cleaned:
        cleaned = f"CHAR_{idx:02d}"
    if not cleaned.endswith(("_MAIN", "_FEMALE", "_DETECTIVE", "_VICTIM")) and not cleaned.startswith("CHAR_"):
        cleaned = cleaned[:48].strip("_") or f"CHAR_{idx:02d}"
    candidate = cleaned
    suffix = 2
    while candidate in used:
        candidate = f"{cleaned}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def build_llm_character_catalog_prompt(source: ProjectSource, initial_characters: list[Character], platform: str) -> str:
    return f"""你是小说短剧项目的全书角色统筹和 AI 视频角色资产规划师。

任务：基于全文抽取 `bible.characters` 应覆盖的长期连续性角色。小说原文是唯一事实源。

[PROJECT_CONTEXT]
- 项目名：{source.project_name}
- 标题：{source.title}
- 平台：{platform}

[CURRENT_HEURISTIC_CHARACTERS]
以下是当前启发式识别结果。可以保留、补全、修正，但不得因为已有列表而遗漏全文重要角色。
{llm_character_reference(initial_characters)}

[FULL_NOVEL_TEXT]
{excerpt(source.text, 60000)}

请只输出一个 JSON object，不要 Markdown 代码围栏。JSON schema:
{{
  "characters": [
    {{
      "character_id": "ASCII_UPPER_SNAKE_ID",
      "lock_profile_id": "ASCII_UPPER_SNAKE_ID_LOCK_V1",
      "name": "正式角色名",
      "aliases": ["别名", "短名"],
      "role_tier": "main|core_support|important_support|recurring_minor|ephemeral",
	      "include_in_bible": true,
	      "needs_reference_image": true,
	      "visual_anchor": "年龄、身份、职业/阶层、服装、脸部气质、稳定视觉锚点",
	      "appearance_profile": {{
	        "age_impression": "年龄观感",
	        "face_structure": "脸型骨相",
	        "facial_features": "五官特征",
	        "hair": "发型",
	        "body_posture": "体态/身高感",
	        "wardrobe_anchor": "服饰主锚点",
	        "color_material": "服饰颜色/材质",
	        "class_detail": "职业/阶层细节",
	        "default_expression": "表情默认值",
	        "contrast_with_others": "与同项目其他角色的差异",
	        "forbidden_drift": "禁止漂移"
	      }},
	      "persona_anchor": ["人格锚点"],
	      "speech_style_anchor": ["对白气质"],
	      "source_basis": "说明为什么这是全书长期角色"
    }}
  ],
  "ephemeral_characters": [
    {{"name": "服务员", "reason": "只作为场景功能人物，不进入主角色锁定资产"}}
  ],
  "merge_notes": ["别名合并、排除临时人物等说明"]
}}

硬性规则：
- 必须覆盖全书主角、核心配角、反复出现的重要嫌疑人/关系人；不要只看当前单集。
- `bible.characters` 只放需要跨镜头/跨集保持身份连续性的角色。
- 服务员、警员、女招待、经理、护士、邻居、客人、人群等临时功能角色必须放入 `ephemeral_characters`，不要设置 include_in_bible=true。
- 同一人物的别名必须合并，例如“小樱/樱子/佐藤樱子”只能生成一个角色。
- `character_id` 和 `lock_profile_id` 必须稳定、可作为文件名；已有启发式角色如果同名，应优先保留原 ID。
- 未成年人角色可以进入角色表，但 visual_anchor 必须非情色化，只描述年龄、校服/日常服、稚嫩不安等安全视觉锚点。
- `appearance_profile` 必须具体到脸型、五官、发型、体态、服饰颜色材质，并写明“与其他角色的区别”；不能只写漂亮、成熟、清纯、冷静这类抽象词。
"""


def normalize_llm_characters(payload: dict[str, Any], initial_characters: list[Character]) -> list[Character]:
    raw_characters = payload.get("characters")
    if not isinstance(raw_characters, list):
        raise ValueError("LLM character response missing characters list")

    known = known_character_by_name(initial_characters)
    used_ids: set[str] = set()
    normalized: list[Character] = []
    seen_names: set[str] = set()
    excluded_tiers = {"ephemeral", "temporary", "extra", "crowd", "background"}
    for idx, item in enumerate(raw_characters, start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("character") or "").strip()
        if not name:
            continue
        role_tier = str(item.get("role_tier") or "").strip().lower()
        include = item.get("include_in_bible", True)
        if include is False or role_tier in excluded_tiers:
            continue
        if name in seen_names:
            continue

        aliases = as_string_list(item.get("aliases"))
        known_match = known.get(name) or next((known.get(alias) for alias in aliases if known.get(alias)), None)
        if known_match is not None:
            character_id = known_match.character_id
            lock_profile_id = known_match.lock_profile_id
            used_ids.add(character_id)
        else:
            character_id = normalize_character_id(str(item.get("character_id") or ""), name, idx, used_ids)
            lock_profile_id = str(item.get("lock_profile_id") or "").strip().upper()
            lock_profile_id = re.sub(r"[^A-Z0-9]+", "_", lock_profile_id).strip("_")
            if not lock_profile_id:
                lock_profile_id = f"{character_id}_LOCK_V1"
            elif lock_profile_id in used_ids:
                lock_profile_id = f"{character_id}_LOCK_V1"

        visual_anchor = str(item.get("visual_anchor") or "").strip()
        if not visual_anchor and known_match is not None:
            visual_anchor = known_match.visual_anchor
        if not visual_anchor:
            visual_anchor = f"{name}，来自全文角色线索，写实短剧角色，服装和气质符合故事时代与阶层"
        clean_aliases = [alias for alias in dict.fromkeys(aliases) if alias and alias != name]
        if clean_aliases and "别名" not in visual_anchor:
            visual_anchor = f"{visual_anchor}。别名：{'、'.join(clean_aliases)}"
        appearance = item.get("appearance_profile")
        if isinstance(appearance, dict):
            appearance_parts = [
                str(appearance.get(key) or "").strip()
                for key in (
                    "face_structure",
                    "facial_features",
                    "hair",
                    "body_posture",
                    "wardrobe_anchor",
                    "color_material",
                    "contrast_with_others",
                )
                if str(appearance.get(key) or "").strip()
            ]
            if appearance_parts and "容貌细节" not in visual_anchor:
                visual_anchor = f"{visual_anchor}。容貌细节：{'；'.join(appearance_parts)}"

        persona_anchor = as_string_list(item.get("persona_anchor")) or (known_match.persona_anchor if known_match is not None else ["强目标", "关系压力", "情绪可读"])
        speech_style_anchor = as_string_list(item.get("speech_style_anchor")) or (known_match.speech_style_anchor if known_match is not None else ["口语化", "短句", "信息直给"])
        normalized.append(
            Character(
                character_id=character_id,
                lock_profile_id=lock_profile_id,
                name=name,
                visual_anchor=visual_anchor,
                persona_anchor=persona_anchor[:6],
                speech_style_anchor=speech_style_anchor[:6],
            )
        )
        seen_names.add(name)

    if not normalized:
        raise ValueError("LLM character response produced no bible characters")

    existing_names = {character.name for character in normalized}
    for character in initial_characters:
        if character.name not in existing_names:
            normalized.append(character)
    return normalized


def run_llm_character_catalog(
    args: argparse.Namespace,
    paths: ProjectPaths,
    source: ProjectSource,
    initial_characters: list[Character],
    overwrite: bool,
    dry_run: bool,
    request_files: list[str],
    fallbacks: list[dict[str, str]],
) -> list[Character]:
    if args.backend != "llm":
        return initial_characters

    llm_dir = paths.out_dir / "llm_requests"
    prompt = build_llm_character_catalog_prompt(source, initial_characters, args.platform)
    request = openai_responses_payload(
        args.llm_model,
        prompt,
        args.llm_reasoning_effort,
        args.llm_max_output_tokens,
    )
    request_path = llm_dir / "full_character_catalog.request.json"
    request_files.append(str(request_path))
    if dry_run:
        print(f"[DRY] write {request_path}")
    else:
        write_json(request_path, make_llm_task_request("full_character_catalog", request, args.llm_provider, args.llm_model), overwrite)

    if args.llm_dry_run or dry_run:
        reason = "llm-dry-run enabled; heuristic character catalog kept" if args.llm_dry_run else "dry-run enabled; heuristic character catalog kept"
        fallbacks.append({"task": "full_character_catalog", "reason": reason})
        return initial_characters
    if args.llm_provider != "openai":
        fallbacks.append({"task": "full_character_catalog", "reason": f"live provider {args.llm_provider} is not supported; heuristic character catalog kept"})
        return initial_characters
    api_key = os.getenv(args.llm_api_key_env, "").strip()
    if not api_key:
        fallbacks.append({"task": "full_character_catalog", "reason": f"{args.llm_api_key_env} is not set; heuristic character catalog kept"})
        return initial_characters
    if requests is None:
        fallbacks.append({"task": "full_character_catalog", "reason": "requests package unavailable; heuristic character catalog kept"})
        return initial_characters

    try:
        payload, raw = call_openai_json(request, api_key, args.llm_base_url, args.llm_timeout_sec)
        response_path = llm_dir / "full_character_catalog.response.json"
        write_json(response_path, {"parsed": payload, "raw": raw}, overwrite)
        characters = normalize_llm_characters(payload, initial_characters)
        print(f"[INFO] LLM character catalog applied: {args.llm_model} characters={len(characters)}")
        return characters
    except Exception as exc:
        fallbacks.append({"task": "full_character_catalog", "reason": f"live LLM character catalog failed: {exc}; heuristic character catalog kept"})
        print(f"[WARN] {fallbacks[-1]['reason']}", file=sys.stderr)
        return initial_characters


def build_core_selling_points(text: str) -> list[str]:
    if "银座" in text and "佐藤彩花" in text:
        return ["银座酒店命案", "丝巾疑点", "亲密关系成谜", "小樱托付钩子"]
    if is_sample_chapter_source(text):
        return ["穿越成乞丐", "开局快饿死", "青梅送粥救命", "现代知识提盐翻身"]
    return ["强开场钩子", "人物关系拉扯", "核心秘密", "集尾反转"]


def extract_numbered_chapter_titles(text: str) -> list[str]:
    titles: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s*##+\s*[0-9一二三四五六七八九十百]+[.、]\s*(.+?)\s*$", line)
        if not match:
            continue
        title = match.group(1).strip()
        if title and title not in titles:
            titles.append(title)
    return titles


def build_ginza_episode_outlines(source: ProjectSource) -> list[dict[str, Any]]:
    titles = [
        ("酒店的发现", "严格改编原文第1章，用酒店命案、丝巾疑点和前夜托付完成强开场。", "现场像自杀但细节指向他杀，健一隐瞒前夜低语。", ["惊惧", "不安", "追问"], "小樱是谁？为什么彩花要健一守护她？"),
        ("前夜的回响", "严格改编原文第2章，把健一与彩花的亲密关系和小樱托付推到台前。", "健一想相信彩花的温柔，却开始察觉这份亲密可能藏着操控。", ["怀疑", "依附", "不安"], "健一在抽屉深处发现小樱照片。"),
        ("嫌疑人的初现", "严格改编原文第3章，引入龙崎并制造第一次表层嫌疑误导。", "龙崎看似有动机，但证据无法闭环，健一和美咲的紧张反而更明显。", ["误判", "压迫", "反转"], "一枚旧名片把线索指向山田老先生。"),
        ("匿名的秘密", "严格改编原文第4章，让彩花手机里的匿名小说和旧关系浮出水面。", "石川追问小说与现实的重叠，美咲试图切断警方对家族秘密的追查。", ["紧张", "隐忍", "防备"], "匿名文本把彩花过去和小樱处境连在一起。"),
        ("徘徊的影子", "严格改编原文第5章，用出租车和酒店周边影像扩大嫌疑网络。", "阿彻的徘徊像跟踪，又像被人安排，警方难以判断真正指向。", ["疑惧", "监视感", "逼近"], "影像里出现美咲靠近邻室的侧影。"),
        ("照片的低语", "严格改编原文第6章，用照片和私物暴露姐妹之间的依赖与怨恨。", "美咲否认介入，照片却证明她早已知道姐姐计划。", ["悲伤", "怨恨", "隐秘"], "照片背面写着一个给小樱的承诺。"),
        ("丝巾的真相", "严格改编原文第7章，重新解释凶器并推翻自杀表象。", "鉴定结果让健一和美咲都无法继续隐藏。", ["寒意", "压迫", "真相逼近"], "丝巾上的细节指向熟悉彩花的人。"),
        ("私物的回音", "严格改编原文第8章，从彩花私物里提取情绪证据。", "遗物像在保护小樱，也像在操控健一。", ["迷恋", "醒悟", "不信任"], "健一发现自己可能只是彩花计划中的工具。"),
        ("指纹的指向", "严格改编原文第9章，让关键物证把嫌疑压到主角身上。", "指纹结果逼健一解释前夜所有细节。", ["恐惧", "羞耻", "防守"], "警方准备正式锁定健一。"),
        ("樱子的不安", "严格改编原文第10章，让小樱进入情绪中心并改写健一动机。", "健一想保护小樱，却越保护越像在替人遮罪。", ["父性", "不安", "责任"], "小樱说出彩花生前最后一次安排。"),
        ("姐妹的对峙", "严格改编原文第11章，让美咲和健一正面冲突。", "美咲既恨姐姐又复制姐姐的保护方式。", ["怨恨", "依赖", "崩裂"], "美咲承认她知道邻室发生过什么。"),
        ("证据的链锁", "严格改编原文第12章，把零散证据串成一条可追责链。", "石川越接近真相，越意识到逮捕会伤害小樱。", ["冷静", "犹豫", "道德压力"], "证据链绕回美咲。"),
        ("邻室的等待", "严格改编原文第13章，揭开邻室监听与等待的关键夜晚。", "美咲并非临时失控，而是在等待姐姐计划破裂。", ["窒息", "等待", "失控"], "邻室记录足以定案。"),
        ("崩坏的边缘", "严格改编原文第14章，让健一、美咲、小樱同时逼近崩溃。", "每个人都以保护为名做出伤害他人的选择。", ["崩溃", "牺牲", "撕裂"], "健一决定用伪自白换小樱脱身。"),
        ("留置所的独白", "严格改编原文第15章，进入健一内心并确认他的主动承担。", "他从被利用的男人变成想切断链条的保护者。", ["悔意", "觉醒", "承担"], "石川看出自白漏洞。"),
        ("DNA的觉醒", "严格改编原文第16章，让 DNA 真相触发健一的父性觉醒。", "血缘真相让健一从被动嫌疑人转为主动承担者。", ["震动", "父性", "决意"], "健一准备把自白推向更深处。"),
        ("自白的深层", "严格改编原文第17章，展开健一自白背后的真正动机。", "自白能救小樱，却也会遮蔽真正的伤口。", ["决绝", "压抑", "怀疑"], "石川开始怀疑这份自白并不完整。"),
        ("告白的泪水", "严格改编原文第18章，让美咲说出姐姐献身计划和自己的怨恨。", "法律真相与情感真相冲突，证据能抓人却修复不了被剥削的关系。", ["矛盾", "怜悯", "崩裂"], "小樱可能被同一条路吞没。"),
        ("守护的代价", "严格改编原文第19章，让美咲面对带小樱逃离的实际代价。", "美咲想保护小樱，却必须背负隐瞒、逃离和健一牺牲的重量。", ["克制", "愧疚", "守护"], "门外的脚步声让石川的选择悬在空气中。"),
        ("沉默的注视", "严格改编原文第20章，让石川面对执法与救济的取舍。", "依法定案会毁掉小樱，不定案会背叛证据。", ["克制", "恐惧", "抉择"], "石川选择沉默，放行这场灰色救济。"),
        ("新干线的牵手", "严格改编原文第21章，让美咲和小樱踏上离开银座的新干线。", "小樱仍牵挂母亲的世界，美咲必须把她带向新生。", ["不舍", "信任", "新生"], "列车启动，银座的影子在雾中后退。"),
        ("献身的终曲", "严格改编原文第22章，完成石川、健一、美咲和小樱的结局回收。", "真相被选择性埋藏，每个人都背着代价守护小樱。", ["余痛", "默许", "温柔"], "银座恢复平静，真正的夜晚留在每个人心里。"),
    ]
    chapter_titles = extract_numbered_chapter_titles(source.text)
    if len(chapter_titles) == len(titles):
        titles = [(chapter_title, goal, conflict, emotions, hook) for chapter_title, (_, goal, conflict, emotions, hook) in zip(chapter_titles, titles)]
    return [
        {
            "episode_number": idx,
            "title": title,
            "goal": goal,
            "conflict": conflict,
            "emotions": emotions,
            "hook": hook,
            "source_basis": [title],
            "story_function": "严格按原文单章改编，一章对应一集",
        }
        for idx, (title, goal, conflict, emotions, hook) in enumerate(titles, start=1)
    ]


def build_generic_episode_outlines(source: ProjectSource) -> list[dict[str, Any]]:
    basis = source.chapter_titles or [source.title]
    outlines: list[dict[str, Any]] = []
    for idx in range(1, 21):
        anchor = basis[min(len(basis) - 1, int((idx - 1) * len(basis) / 20))]
        next_anchor = basis[min(len(basis) - 1, int(idx * len(basis) / 20))]
        outlines.append(
            {
                "episode_number": idx,
                "title": anchor,
                "goal": f"把“{anchor}”中的核心事件短剧化，形成清晰的行动目标。",
                "conflict": f"主角推进目标时，被“{next_anchor}”相关人物或秘密阻挡。",
                "emotions": ["紧张", "拉扯", "追问"],
                "hook": f"新的证据或关系变化指向“{next_anchor}”。",
                "source_basis": [anchor, next_anchor] if next_anchor != anchor else [anchor],
                "story_function": "承接原文事件并放大单集追更点",
            }
        )
    return outlines


def build_sample_chapter_episode_outlines(source: ProjectSource) -> list[dict[str, Any]]:
    first_three = [
        (
            "穿越成乞丐，我开局快饿死了",
            "建立林辰现代社畜穿越成西汉乞丐的极惨开局，并让阿翠送粥成为唯一善意。",
            "林辰必须先活过今晚，饥饿虚弱与陌生古代环境压住他。",
            ["极惨", "震惊", "温暖", "觉醒"],
            "下一集，他要用一口破陶罐，赚到来到这个世界后的第一笔钱。",
            ["穿越乞丐街头"],
        ),
        (
            "集市初试现代知识",
            "让林辰把粗盐和肥皂拿到集市试卖，验证现代知识能换钱。",
            "村民怀疑新东西，赵霸手下盯上盐和肥皂。",
            ["爽感", "试探", "护短"],
            "赵霸率众逼近，盯上林辰的秘方。",
            ["集市初试现代知识"],
        ),
        (
            "打脸村霸赵霸",
            "让林辰用现代格斗和嘴硬人设第一次正面打脸村霸。",
            "赵霸想抢秘方，阿翠被卷入危险。",
            ["压迫", "反击", "扬眉吐气"],
            "赵霸余党夜里摸向林辰的新住处。",
            ["打脸村霸赵霸"],
        ),
    ]
    outlines: list[dict[str, Any]] = []
    for idx, (title, goal, conflict, emotions, hook, basis) in enumerate(first_three, start=1):
        outlines.append(
            {
                "episode_number": idx,
                "title": title,
                "goal": goal,
                "conflict": conflict,
                "emotions": emotions,
                "hook": hook,
                "source_basis": basis,
                "story_function": "底层求生、现代知识爽点与护短关系递进",
            }
        )
    basis = source.chapter_titles or [source.title]
    for idx in range(4, 21):
        anchor = basis[min(len(basis) - 1, int((idx - 1) * len(basis) / 20))]
        next_anchor = basis[min(len(basis) - 1, int(idx * len(basis) / 20))]
        outlines.append(
            {
                "episode_number": idx,
                "title": anchor,
                "goal": f"承接林辰靠现代知识翻身的主线，把“{anchor}”短剧化。",
                "conflict": f"底层逆袭推进时，被“{next_anchor}”相关阻力卡住。",
                "emotions": ["爽感", "压迫", "护短"],
                "hook": f"林辰的下一项现代手段指向“{next_anchor}”。",
                "source_basis": [anchor, next_anchor] if next_anchor != anchor else [anchor],
                "story_function": "承接原文事件并放大单集爽点",
            }
        )
    return outlines


def build_project_bible(source: ProjectSource, platform: str, characters: list[Character]) -> ProjectBible:
    setting = detect_setting(source.text)
    selling_points = build_core_selling_points(source.text)
    if "银座" in source.text and "佐藤彩花" in source.text:
        logline = "银座酒店命案把刑警、普通上班族和死者妹妹卷入同一张亲密关系网；他们必须在真相、保护和自我欺骗之间选择。"
        story_stages = [
            "开局用酒店命案和丝巾疑点建立犯罪悬疑。",
            "中段逐层排除表层嫌疑人，把小樱和彩花的献身计划推到中心。",
            "结尾让法律真相与救济冲突，完成隐藏温柔的情绪回收。",
        ]
        relationships = [
            "石川悠一是调查推进者，也是最终必须承担道德选择的人。",
            "田中健一从被彩花利用的常客，转为试图保护小樱的承担者。",
            "佐藤美咲既怨恨姐姐的控制，也继承了姐姐的保护执念。",
            "佐藤彩花以死后的遗物、回忆和证据持续影响所有人的选择。",
        ]
        episode_outlines = build_ginza_episode_outlines(source)
    elif is_sample_chapter_source(source.text):
        logline = "现代社畜林辰穿越成西汉长安城外快饿死的乞丐少年，在阿翠一碗稀粥救命后，靠盐渍和现代知识开启底层逆袭。"
        story_stages = [
            "开局用破庙、饥饿、穿越落差建立极惨求生困境。",
            "中段让阿翠送粥形成情感锚点，林辰的护短本能第一次立住。",
            "结尾用溪边盐渍和破陶罐抛出现代知识赚钱翻身的追更钩子。",
        ]
        relationships = [
            "林辰是现代灵魂穿越到乞丐身体的主角，从快饿死到主动找活路。",
            "阿翠是青梅和开局唯一善意，送来稀粥并守了林辰两天。",
            "两人的关系不是医患疗伤，而是底层互相救命与护短承诺。",
        ]
        episode_outlines = build_sample_chapter_episode_outlines(source)
    else:
        first = selling_points[0]
        logline = f"围绕“{first}”展开，主角在高压关系和连续反转中完成关键选择。"
        story_stages = [
            "开局用强事件和人物困境抓住观众。",
            "中段以证据、关系和误判持续升级冲突。",
            "结尾回收核心秘密，让主角做出不可逆选择。",
        ]
        relationships = [
            "主角线：从被动卷入到主动选择。",
            "秘密线：围绕关键道具、身份或承诺反复升级。",
            "对抗线：表层压力不断被排除，真正矛盾来自亲密关系内部。",
        ]
        episode_outlines = build_generic_episode_outlines(source)
    visual_baseline = f"{setting}，竖屏9:16，低饱和，真实光影，亲密关系用距离、眼神和手部动作表达。"
    return ProjectBible(
        project_name=source.project_name,
        title=source.title,
        platform=platform,
        setting=setting,
        core_selling_points=selling_points,
        logline=logline,
        story_stages=story_stages,
        episode_outlines=episode_outlines,
        relationships=relationships,
        visual_baseline=visual_baseline,
        language_policy=dict(DEFAULT_LANGUAGE_POLICY),
        characters=characters,
        safety_note="未成年人角色不得被情色化；亲密关系只保留悬疑、权力关系和情绪张力；画面提示词避免露骨性描写。",
        generation_notes=["heuristic project bible v1", "legacy output layout preserved"],
    )


def parse_episode_number(episode_id: str) -> int:
    match = re.search(r"(\d+)", episode_id)
    if not match:
        return 1
    return max(1, int(match.group(1)))


def build_episode_plan(bible: ProjectBible, episode_id: str) -> EpisodePlan:
    episode_number = parse_episode_number(episode_id)
    outline = bible.episode_outlines[min(len(bible.episode_outlines) - 1, episode_number - 1)]
    return EpisodePlan(
        episode_id=episode_id,
        episode_number=episode_number,
        episode_label=f"第{episode_number}集",
        title=str(outline["title"]),
        goal=str(outline["goal"]),
        conflict=str(outline["conflict"]),
        emotions=[str(item) for item in outline.get("emotions", [])],
        hook=str(outline["hook"]),
        source_basis=[str(item) for item in outline.get("source_basis", [])],
        story_function=str(outline.get("story_function", "推进剧情和情绪钩子")),
    )


def build_shot_plan(
    source: ProjectSource,
    bible: ProjectBible,
    episode_plan: EpisodePlan,
    shot_count: int,
) -> list[ShotPlan]:
    if episode_plan.episode_number == 1 and is_sample_chapter_source(source.text):
        base = [
            ("SH01", "P1", "破庙极惨环境", 4, "大全景", "缓慢推进", "破庙泥地残墙枯草", "建立寒冷破庙与濒死求生空间", "极惨压迫", "BROKEN_TEMPLE", "长安城外荒废破庙", [], [], [], "荒废破庙夜景，冷风灌入，潮湿泥地，残破土墙，枯草碎瓦，极度贫穷，第一秒传达穷冷惨"),
            ("SH02", "P0", "林辰濒死惊醒", 4, "近景特写", "弱手持", "林辰冷汗与惊醒眼神", "林辰在泥地上猛地睁眼，大口喘气，意识到这里不是出租屋", "震惊警觉", "BROKEN_TEMPLE", "长安城外荒废破庙", [{"speaker": "林辰", "text": "什么鬼……这不是我出租屋。", "purpose": "穿越落差"}], [], ["我穿越了。"], "18-22岁消瘦乞丐少年林辰躺在破庙泥地上猛然惊醒，额头冷汗，大口喘气，眼神从涣散到警觉，现代社畜穿越落差"),
            ("SH03", "P0", "乞丐身体惨状", 5, "手部与半身特写", "小幅平移", "瘦骨手臂与破麻布", "林辰低头确认自己瘦骨嶙峋、破麻布衣、脏污皮肤，饥饿感压顶", "饥饿虚弱", "BROKEN_TEMPLE", "长安城外荒废破庙", [], ["我穿越了？还穿成了一个乞丐？"], ["还穿成了一个快饿死的乞丐。"], "瘦骨嶙峋手臂，粗糙破麻布衣，脏污皮肤，饥饿虚弱发抖，破庙低光，强调乞丐身份而非侠客伤者"),
            ("SH04", "P1", "饿到差点倒", 5, "中景", "中景跟随", "扶墙起身与胃痛", "林辰扶着残墙艰难起身，胃里绞痛，差点摔倒", "硬撑不服", "BROKEN_TEMPLE", "长安城外荒废破庙", [{"speaker": "林辰", "text": "再饿下去，我今天真得死这儿。", "purpose": "生存危机"}], [], ["再饿一会儿，我今天就得死这儿。"], "消瘦乞丐少年扶破墙艰难起身，因饥饿胃痛险些跪倒，表情痛苦但嘴硬不认命，破庙泥地与缺口陶罐可见"),
            ("SH05", "P0", "阿翠端稀粥进门", 5, "中景到近景", "轻微推进", "阿翠端粥与蒸汽", "阿翠推开破庙木门，端着冒热气的稀粥小心走近", "寒夜温暖", "BROKEN_TEMPLE", "长安城外荒废破庙", [{"speaker": "阿翠", "text": "辰哥，你醒了？", "purpose": "唯一善意入场"}], [], ["辰哥，你醒了？"], "16-18岁清贫布衣少女阿翠推开破庙木门，端着一碗冒热气的稀粥进来，门外冷夜与门内微暖火光对比，她温柔隐忍但不是医女"),
            ("SH06", "P1", "递粥触手", 6, "双人近景", "轻微横移", "递粥时指尖轻触", "阿翠递稀粥，林辰警惕后接过，指尖碰到她冰冷的手", "微暖信任", "BROKEN_TEMPLE", "长安城外荒废破庙", [{"speaker": "阿翠", "text": "我熬了点粥，趁热喝。", "purpose": "救命粥"}, {"speaker": "林辰", "text": "你守了我多久？", "purpose": "确认关系"}, {"speaker": "阿翠", "text": "两天。", "purpose": "情感锚点"}], [], ["她守了我两天。"], "破庙火边双人近景，阿翠双手递稀粥，林辰接碗时指尖轻触，少年从防备转松动，女孩清贫温柔，粥蒸汽清楚"),
            ("SH07", "P0", "第一口粥救命", 5, "特写", "静态特写", "热粥蒸汽与吞咽", "林辰低头喝下第一口稀粥，呼吸稍微稳住", "活过来一点", "BROKEN_TEMPLE", "长安城外荒废破庙", [], ["这一口粥，算把我从鬼门关拽回来了。"], ["这一口粥，把我从鬼门关拽了回来。"], "热稀粥蒸汽极近特写，林辰低头喝第一口粥，喉结吞咽，火边微暖光映在苍白面部，这是救命粥不是药"),
            ("SH08", "P1", "护短承诺", 5, "双人中近景", "稳定近景", "阿翠掖破布与林辰眼神", "阿翠帮林辰掖好破布，林辰看着她，护短本能第一次出现", "保护欲", "BROKEN_TEMPLE", "长安城外荒废破庙", [{"speaker": "林辰", "text": "以后谁再让你受委屈，我弄死他。", "purpose": "护短关系"}], [], ["以后谁再让你受委屈，我弄死他。"], "阿翠蹲下替林辰掖好破布，林辰目光由疲惫转成保护欲和狠劲，破庙火边低光，情绪狠但不油腻"),
            ("SH09", "P1", "拖着身体到溪边", 5, "中景", "中景跟拍", "虚弱前行与溪水", "林辰缓过一点后拖着虚弱身体走到破庙外溪边寻找活路", "开始行动", "CREEK_BANK", "破庙外溪边", [], ["可光靠一碗粥，活不过明天。"], ["但光靠粥，活不过明天。"], "夜晚溪边，消瘦乞丐少年林辰拖着虚弱身体前行，脚踩湿泥碎石，溪水弱反光，风声与水声，开始寻找活路"),
            ("SH10", "P0", "发现溪边盐渍", 6, "手部特写", "微推进", "手指触碰白色盐渍", "林辰指腹抹过溪边石面和泥土上的白色盐渍，确认这是机会", "惊喜确认", "CREEK_BANK", "破庙外溪边", [{"speaker": "林辰", "text": "等等……盐渍？", "purpose": "翻盘机会"}], [], ["等等……盐渍？"], "溪边石头与湿泥上的白色盐渍清晰可辨，粗糙手指缓慢抹过盐渍，缺口陶罐在旁，发现现代知识赚钱机会，不是毒药、雪、骨灰或神秘粉末"),
            ("SH11", "P0", "眼神觉醒", 6, "面部近景", "轻微推进", "林辰眼神从虚弱转锐利", "林辰看着盐渍，脑子飞速运转，眼神从虚弱变锐利", "觉醒爽点", "CREEK_BANK", "破庙外溪边", [{"speaker": "林辰", "text": "有意思。", "purpose": "现代知识启动"}, {"speaker": "阿翠", "text": "辰哥，你看什么呢？", "purpose": "观众提问"}, {"speaker": "林辰", "text": "看活路。", "purpose": "明确盐渍意义"}], [], ["古人看不懂，但我懂。"], "溪边夜色面部近景，林辰由饥饿虚弱逐步聚焦，嘴角微微上扬，眼神变锐利，明确是发现盐渍活路的智商爽点"),
            ("SH12", "P1", "握陶罐决定赚钱", 6, "半身近景", "半身拉近", "破陶罐与望远眼神", "林辰握着缺口陶罐抬头看向长安方向，决定明天做买卖", "决心翻身", "CREEK_BANK", "破庙外溪边", [{"speaker": "林辰", "text": "阿翠，明天跟着我。", "purpose": "行动安排"}, {"speaker": "阿翠", "text": "做什么？", "purpose": "抛出钩子"}, {"speaker": "林辰", "text": "赚钱。", "purpose": "集尾爽点"}], [], ["明天，不讨饭，做买卖。"], "林辰右手紧握缺口破陶罐，低头看盐渍后缓慢抬头望向长安方向，虚弱但脊背挺起，决定用现代知识提盐赚钱"),
            ("SH13", "P0", "进城卖盐集尾台词钩子", 9, "双人半身近景到特写", "极慢推进", "阿翠疑问、林辰握陶罐、溪边盐渍与最终狠眼神", "阿翠问明天是否继续讨饭，林辰否定并说进城卖盐，用角色台词把下一集赚钱行动钩住", "追更钩子", "CREEK_BANK", "破庙外溪边", [{"speaker": "阿翠", "text": "我们明天还去讨饭吗？", "purpose": "观众代问未来"}, {"speaker": "林辰", "text": "不讨。", "purpose": "否定旧命运"}, {"speaker": "阿翠", "text": "那去哪？", "purpose": "递进悬念"}, {"speaker": "林辰", "text": "进城。", "purpose": "明确行动方向"}, {"speaker": "阿翠", "text": "做什么？", "purpose": "逼出爽点"}, {"speaker": "林辰", "text": "让他们花钱，买这把盐。", "purpose": "集尾商业钩子"}], [], ["阿翠：我们明天还去讨饭吗？", "林辰：不讨。", "阿翠：那去哪？", "林辰：进城。", "阿翠：做什么？", "林辰：让他们花钱，买这把盐。"], "破陶罐与溪边盐渍前景，阿翠困惑追问，林辰握紧缺口陶罐，最终说让他们花钱买这把盐，低饱和冷色，结尾必须是角色对白钩子而非旁白"),
        ]
        return [ShotPlan(*row) for row in base[:shot_count]]

    if episode_plan.episode_number == 1 and "银座" in source.text and "佐藤彩花" in source.text:
        base = [
            ("SH01", "P1", "酒店套房环境建立", 4, "大全景", "缓慢推进", "凌乱套房与清晨光线", "建立命案空间", "悬疑压迫", "HOTEL_ROOM", "银座高级酒店套房", [], ["清晨，银座酒店的套房里，昨夜的香水和威士忌还没有散。"], ["清晨，酒店套房出事了。"], "银座高级酒店套房清晨，落地窗冷光照进凌乱房间，床边散落酒杯与丝巾，写实悬疑电影感"),
            ("SH02", "P0", "服务员发现尸体", 4, "中景", "轻微手持", "服务员惊恐反应", "服务员推门后僵住并按下紧急按钮", "惊惧", "HOTEL_ROOM", "银座高级酒店套房", [], ["服务员推开门，整个人僵在门口。"], ["服务员发现了异常。"], "服务员推开高级酒店套房门后惊恐僵住，手指颤抖按下紧急按钮，冷色晨光，写实悬疑"),
            ("SH03", "P1", "刑警进入现场", 5, "中近景", "稳定推进", "石川戴手套检查现场", "石川进入房间检查尸体与丝巾", "冷静压迫", "HOTEL_ROOM", "银座高级酒店套房", [{"speaker": "石川悠一", "text": "看起来像自杀，但勒痕不对劲。", "purpose": "判断命案疑点"}], [], ["勒痕不对劲。"], "冷静日本刑警戴手套蹲下检查现场，床边浅粉色丝巾成为视觉焦点，酒店套房冷光，写实刑侦"),
            ("SH04", "P1", "丝巾勒痕特写", 5, "特写", "缓慢推近", "丝巾与杯沿唇印", "突出凶器疑点与现场细节", "不安", "HOTEL_ROOM", "银座高级酒店套房", [], ["丝巾太柔软，勒痕却太清晰。"], ["柔软的丝巾，留下了不该有的痕迹。"], "浅粉色丝巾特写，纤维微微变形，旁边半空威士忌杯带唇印，冷色微距悬疑质感"),
            ("SH05", "P0", "美咲赶到现场", 5, "中景", "跟拍", "美咲穿过人群", "美咲赶到并压住情绪", "爱恨交织", "HOTEL_CORRIDOR", "酒店走廊", [{"speaker": "佐藤美咲", "text": "姐姐……", "purpose": "情绪锚点"}], [], ["姐姐……"], "年轻女性佐藤美咲穿过酒店走廊人群，旧礼服外披外套，眼神震动又迅速克制，写实悬疑"),
            ("SH06", "P1", "美咲触碰姐姐手腕", 5, "近景", "静态压迫", "手腕与丝巾触感", "建立姐妹关系与隐藏秘密", "悲伤警觉", "HOTEL_ROOM", "银座高级酒店套房", [], ["她伸手碰到姐姐冰冷的手腕，眼神里不是单纯的悲伤。"], ["她在悲伤，也在防备。"], "美咲指尖轻触冰冷手腕，浅粉丝巾在画面边缘，表情悲伤中闪过警觉，低饱和写实"),
            ("SH07", "P1", "健一接受询问", 5, "中近景", "轻微横移", "疲惫西装与领带", "健一说自己昨晚见过彩花", "不安", "HOTEL_CORRIDOR", "酒店走廊", [{"speaker": "田中健一", "text": "我昨晚和她见过面，但没待太久。", "purpose": "嫌疑建立"}], [], ["他见过她，却不敢说完。"], "疲惫上班族田中健一站在酒店走廊接受询问，领带微歪，手指不安摩挲口袋，写实刑侦"),
            ("SH08", "P1", "前夜回忆闪回", 5, "近景", "柔慢推进", "彩花靠近健一", "闪回亲密托付前的温柔操控", "迷恋与疑虑", "FLASHBACK_ROOM", "前夜套房", [], ["前夜，她靠近他，温柔得像一场安排好的梦。"], ["前夜的温柔，开始变得可疑。"], "前夜酒店套房暖烛光闪回，彩花靠近健一，手指轻触领带，画面克制不露骨，心理悬疑氛围"),
            ("SH09", "P0", "彩花托付小樱", 5, "特写", "缓慢推近", "彩花低语与健一领带", "抛出小樱钩子", "温柔胁迫", "FLASHBACK_ROOM", "前夜套房", [{"speaker": "佐藤彩花", "text": "如果我消失了，你会守护小樱吗？", "purpose": "核心钩子"}], [], ["如果我消失了，你会守护小樱吗？"], "彩花低声托付，手指停在健一领带边缘，暖光与阴影交错，克制悬疑，不情色化"),
            ("SH10", "P1", "健一隐瞒不安", 5, "近景", "微手持", "健一避开目光", "健一选择隐瞒关键低语", "盲信裂开", "HOTEL_CORRIDOR", "酒店走廊", [{"speaker": "田中健一", "text": "没什么特别的。", "purpose": "隐瞒信息"}], [], ["他说没有特别的事。"], "田中健一避开刑警目光，手指摸向领带，表情疲惫又心虚，酒店走廊冷光，写实悬疑"),
            ("SH11", "P1", "美咲与健一擦肩", 5, "双人中景", "慢速交错", "两人短暂对视", "建立两人互相警觉", "秘密拉扯", "HOTEL_CORRIDOR", "酒店走廊", [], ["美咲和健一擦肩而过，谁都没有把真正的问题问出口。"], ["他们都知道，她留下了秘密。"], "美咲与健一在酒店走廊擦肩，短暂对视后各自移开，压抑悬疑，低饱和写实"),
            ("SH12", "P1", "警方宣布调查", 5, "大全景", "后退拉开", "警车与酒店大堂", "案件正式展开", "秩序下的混乱", "HOTEL_LOBBY", "酒店大堂", [], ["警笛散去，银座的白天恢复平静，夜里的秘密却开始发酵。"], ["调查，才刚开始。"], "高级酒店大堂外警车灯光闪烁，人群低声议论，银座街头冷色现实主义，悬疑短剧"),
            ("SH13", "P1", "健一离开酒店集尾台词钩子", 5, "近景特写", "缓慢推近", "健一摸向领带", "健一离开酒店时摸向领带，低声追问小樱是谁，用角色台词完成集尾追问钩子", "追问钩子", "GINZA_STREET", "银座街头", [{"speaker": "田中健一", "text": "小樱……到底是谁？", "purpose": "集尾秘密钩子"}], [], ["健一：小樱……到底是谁？"], "田中健一独自走出酒店，凉风吹动领带，他停步回头，银座街头冷光，结尾必须由健一说出小樱疑问而非旁白字幕"),
        ]
        return [ShotPlan(*row) for row in base[:shot_count]]

    intents = [
        f"{episode_plan.title}开场异常",
        "人物目标亮相",
        "关系压力入场",
        "关键证据或道具出现",
        "第一次正面冲突",
        "主角被迫解释",
        "对方隐藏信息",
        "秘密被外化成行动",
        "情绪临界点",
        "主角做出短期选择",
        "选择带来反噬",
        "新线索压近",
        f"{episode_plan.hook}",
    ]
    shots: list[ShotPlan] = []
    for idx, intent in enumerate(intents[:shot_count], start=1):
        shot_id = f"SH{idx:02d}"
        is_last = idx == shot_count
        duration = 6 if is_last else (4 if idx in (1, 2) else 5)
        scene_name = f"{episode_plan.episode_label}核心场景"
        primary_name = bible.characters[0].name if bible.characters else "主角"
        dialogue = [{"speaker": primary_name, "text": "明天，我亲自去找答案。", "purpose": "集尾行动钩子"}] if is_last else []
        narration = [] if is_last else [f"{episode_plan.episode_label}，{intent}。"]
        subtitle = [f"{primary_name}：明天，我亲自去找答案。"] if is_last else [intent]
        positive_core = f"{bible.setting}，{episode_plan.episode_label}{intent}，竖屏短剧，写实电影感，冲突信息直给"
        if is_last:
            positive_core += "，最后一镜必须用角色亲口说出的行动台词收尾，不使用旁白独白替代追更钩子"
        shots.append(
            ShotPlan(
                shot_id=shot_id,
                priority="P0" if idx in (1, 5, shot_count) else "P1",
                intent=intent,
                duration_sec=duration,
                shot_type="中景" if idx % 3 else "近景特写",
                movement="轻微手持" if idx % 2 else "缓慢推进",
                framing_focus=intent,
                action_intent=f"围绕“{episode_plan.goal}”推进：{intent}",
                emotion_intent="、".join(episode_plan.emotions) or "紧张追问",
                scene_id=f"EP{episode_plan.episode_number:02d}_CORE_SCENE",
                scene_name=scene_name,
                dialogue=dialogue,
                narration=narration,
                subtitle=subtitle,
                positive_core=positive_core,
            )
        )
    return shots


def md_header(project_name: str, title: str, doc_name: str) -> str:
    return f"# {project_name}{doc_name}\n\n> 项目标题：{title}\n\n"


def bullet_lines(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def character_lines(characters: list[Character]) -> str:
    return "\n".join(
        f"- {c.name}：{c.visual_anchor}；人格锚点：{'、'.join(c.persona_anchor)}；对白气质：{'、'.join(c.speech_style_anchor)}"
        for c in characters
    )


def render_diagnosis(source: ProjectSource, bible: ProjectBible) -> str:
    heading_lines = "\n".join(f"- H{level} {heading}" for level, heading in source.headings[:40]) or "- 未检测到明显章节标题"
    return md_header(source.project_name, source.title, "短剧适配诊断与骨架提取") + f"""## 一句话结论
适合进入短剧立项草案池。改编重点是把原文叙述压缩成“强事件 + 强关系 + 集尾钩子”的竖屏短剧结构。

## 题材与情绪
- 题材判断：{bible.setting}
- 平台目标：{bible.platform}
- 核心卖点：
{bullet_lines(bible.core_selling_points)}

## 原文结构线索
{heading_lines}

## 核心人物初筛
{character_lines(bible.characters)}

## 改编约束
{bible.safety_note}

## 结构判断
- 开场需要在前3秒交代异常或强情绪。
- 每集需要一个明确动作目标、一个外化冲突和一个可追问钩子。
- 道具、地点和角色状态必须在 records 与视觉锁定文件中保持一致。

## 原文摘录
```text
{excerpt(source.text, 1400)}
```
"""


def render_series_outline(source: ProjectSource, bible: ProjectBible) -> str:
    return md_header(source.project_name, source.title, "短剧总纲") + f"""## Logline
{bible.logline}

## 故事总纲
{bullet_lines(bible.story_stages)}

## 起量策略
- 第1集：用事件现场、核心疑点和第一个秘密托付完成钩子。
- 第2集：把第1集留下的关系和秘密对象推到台前。
- 第3集：排除一个表层答案，同时暴露更深层的人物关系。

## 中段升级方式
- 每2-3集排除一个表层答案。
- 每次排除都暴露一条更危险的人物关系。
- 保持核心道具、地点和秘密对象连续出现。

## 大结局情绪回收
让主角完成从被动卷入到主动选择的转变，同时让核心秘密得到情绪性兑现。
"""


def render_first_three(source: ProjectSource, bible: ProjectBible) -> str:
    blocks: list[str] = []
    for outline in bible.episode_outlines[:3]:
        emotions = "、".join(str(item) for item in outline.get("emotions", []))
        blocks.append(
            f"## 第{outline['episode_number']}集：{outline['title']}\n"
            f"- 本集目标：{outline['goal']}\n"
            f"- 冲突：{outline['conflict']}\n"
            f"- 情绪点：{emotions}\n"
            f"- 集尾钩子：{outline['hook']}\n"
        )
    return md_header(source.project_name, source.title, "前3集分集设计") + "\n".join(blocks)


def render_episode_outlines(source: ProjectSource, bible: ProjectBible) -> str:
    rows = []
    for outline in bible.episode_outlines:
        emotions = "、".join(str(item) for item in outline.get("emotions", []))
        basis = "、".join(str(item) for item in outline.get("source_basis", []))
        rows.append(
            f"- 第{outline['episode_number']}集《{outline['title']}》：目标：{outline['goal']}；"
            f"冲突：{outline['conflict']}；情绪点：{emotions}；集尾钩子：{outline['hook']}；原文依据：{basis}。"
        )
    return md_header(source.project_name, source.title, f"{len(bible.episode_outlines)}集分集大纲") + "\n".join(rows) + "\n"


def render_twenty_episodes(source: ProjectSource, bible: ProjectBible) -> str:
    return render_episode_outlines(source, bible)


def render_character_cards(source: ProjectSource, bible: ProjectBible) -> str:
    return md_header(source.project_name, source.title, "人物关系与角色卡") + f"""## 核心角色
{character_lines(bible.characters)}

## 关系结构
{bullet_lines(bible.relationships)}

## 角色锁定原则
- 每个角色在所有集数中保持年龄、职业身份、脸型气质和服装时代感稳定。
- 关系变化通过动作、眼神、沉默和信息差呈现。
- records 中的 `lock_profile_id` 必须能在 `35_character_lock_profiles_v1.json` 找到。
"""


def render_episode_script(source: ProjectSource, episode_plan: EpisodePlan, shots: list[ShotPlan]) -> str:
    blocks = []
    for shot in shots:
        dialogue = "; ".join(f"{d['speaker']}：{d['text']}" for d in shot.dialogue) if shot.dialogue else "缺对白，需改写为角色对白"
        source_line = f"- 原文依据：{shot.source_basis}\n" if shot.source_basis else ""
        blocks.append(
            f"## 场景{shot.shot_id}\n"
            f"- 地点：{shot.scene_name}\n"
            f"- 动作：{shot.action_intent}\n"
            f"- 对白：{dialogue}\n"
            f"- 情绪重点：{shot.emotion_intent}\n"
            f"{source_line}"
        )
    return md_header(source.project_name, source.title, f"{episode_plan.episode_label}剧本") + "\n".join(blocks)


def episode_character_ids(shots: list[ShotPlan], characters: list[Character]) -> list[str]:
    used: list[str] = []
    joined_shots = "\n".join(
        s.positive_core + " " + s.scene_name + " " + s.action_intent + " " + " ".join(d.get("speaker", "") for d in s.dialogue)
        for s in shots
    )
    for character in characters:
        if character.name in joined_shots or character.character_id in joined_shots:
            used.append(character.character_id)
    return used or [c.character_id for c in characters]


def load_character_asset_info(character_assets_dir: Path, character: Character, setting: str) -> dict[str, str]:
    payload = read_json_if_exists(character_assets_dir / f"{character.character_id}.info.json")
    fallback = build_character_info_payload(setting, character)
    merged: dict[str, str] = {}
    for key, value in fallback.items():
        merged[key] = str(payload.get(key) or value or "")
    return merged


def render_screenplay(
    source: ProjectSource,
    bible: ProjectBible,
    episode_plan: EpisodePlan,
    shots: list[ShotPlan],
    character_assets_dir: Path,
) -> str:
    total_duration = sum(s.duration_sec for s in shots)
    used_ids = set(episode_character_ids(shots, bible.characters))
    character_blocks: list[str] = []
    for character in bible.characters:
        if character.character_id not in used_ids:
            continue
        info = load_character_asset_info(character_assets_dir, character, bible.setting)
        character_blocks.append(
            f"### {info['name']} / {info['character_id']}\n"
            f"- 年龄/身份：{info['age']}；{info['tagline']}\n"
            f"- 活动空间：{info['location']}\n"
            f"- 人物功能：{info['profile']}\n"
            f"- 人格锚点：{info['persona_anchor']}\n"
            f"- 台词气质：{info['speech_style_anchor']}\n"
        )

    shot_blocks: list[str] = []
    for idx, shot in enumerate(shots, start=1):
        dialogue_lines = [f"{d['speaker']}：{d['text']}" for d in shot.dialogue]
        dialogue = "\n".join(f"- {line}" for line in dialogue_lines) if dialogue_lines else "- 缺对白，需改写为角色对白。"
        narration_text = " / ".join(shot.narration) if shot.narration else "无独立旁白。"
        subtitle = " / ".join(shot.subtitle or shot.narration) or shot.intent
        next_hint = shots[idx].intent if idx < len(shots) else "切入下集或片尾追问"
        shot_blocks.append(
            f"## {shot.shot_id} {shot.intent}\n"
            f"- 时长：{shot.duration_sec}s\n"
            f"- 地点：{shot.scene_name}\n"
            f"- 景别/运动：{shot.shot_type} / {shot.movement}\n"
            f"- 画面：{shot.positive_core}\n"
            f"- 人物调度：{shot.action_intent}\n"
            f"- 情绪节奏：{shot.emotion_intent}\n"
            f"- 旁白+屏幕字幕：\n"
            f"  - 旁白：{narration_text}\n"
            f"  - 屏幕字幕：{subtitle}\n"
            f"- 对白：\n{dialogue}\n"
            f"- 声音设计：低频环境音铺底，人物对白清晰靠前，旁白只作为例外兜底，转场处保留短促停顿。\n"
            f"- 转场：切入“{next_hint}”。\n"
        )

    return md_header(source.project_name, source.title, f"{episode_plan.episode_label}完整成片剧本") + f"""## 本集信息
- 集数：{episode_plan.episode_label}
- 标题：{episode_plan.title}
- 预计总时长：约{total_duration}秒
- 本集目标：{episode_plan.goal}
- 核心冲突：{episode_plan.conflict}
- 情绪主轴：{'、'.join(episode_plan.emotions)}
- 集尾钩子：{episode_plan.hook}
- 原文依据：{'、'.join(episode_plan.source_basis)}

## 本集语言锁定
- 对白/旁白/模型音频：{bible.language_policy['spoken_language_label']} only。
- 屏幕字幕：{bible.language_policy['subtitle_language_label']} only。
- 环境文字：东京/银座场景允许日文招牌，但只能作为无声背景环境文字。
- 禁止：日语对白、英语对白、中日混杂语音、非中文字幕。

## 本集出场人物
{chr(10).join(character_blocks)}

## 成片剧本
{chr(10).join(shot_blocks)}
"""


def render_shot_script(source: ProjectSource, episode_plan: EpisodePlan, shots: list[ShotPlan]) -> str:
    rows = "\n".join(
        f"| {s.shot_id} | {s.shot_type} | {s.movement} | {s.duration_sec}s | {s.framing_focus} | {' / '.join(s.subtitle or s.narration)} |"
        for s in shots
    )
    return md_header(source.project_name, source.title, f"{episode_plan.episode_label}镜头脚本") + f"""| 镜头 | 景别 | 运动 | 时长 | 画面重点 | 声音/字幕 |
| --- | --- | --- | --- | --- | --- |
{rows}
"""


def render_subtitles(source: ProjectSource, episode_plan: EpisodePlan, shots: list[ShotPlan]) -> str:
    lines = "\n".join(f"- {s.shot_id}：{' / '.join(s.subtitle or s.narration) or s.intent}" for s in shots)
    return md_header(source.project_name, source.title, f"{episode_plan.episode_label}旁白字幕稿") + lines + "\n"


def render_visual_style(source: ProjectSource, bible: ProjectBible) -> str:
    return md_header(source.project_name, source.title, "视觉风格与分镜方案") + f"""## 视觉基调
{bible.visual_baseline}

## 分镜原则
- 前3秒必须交代事件或强情绪。
- 关键道具和人物表情优先给近景/特写。
- 亲密关系用距离、眼神、手部动作表达，不做露骨呈现。
"""


def truth_prompt_prefix(source: ProjectSource, episode_plan: EpisodePlan, shot: ShotPlan) -> str:
    contract = build_story_truth_contract(source.text, episode_plan, shot)
    if not contract:
        return ""
    shot_truth = contract.get("shot_truth", {})
    truth_check = str(contract.get("truth_check") or "").strip()
    forbidden = "、".join(str(item) for item in contract.get("must_not_drift", []) if str(item).strip())
    if isinstance(shot_truth, dict):
        must_show = "、".join(str(item) for item in shot_truth.get("must_show", []) if str(item).strip())
    else:
        must_show = ""
    return f"故事事实：{contract['premise']}，本镜头必须表达：{truth_check}，必须看见：{must_show}，禁止误读：{forbidden}"


def unique_nonempty(items: list[str]) -> list[str]:
    return list(dict.fromkeys([item.strip() for item in items if item and item.strip()]))


def normalize_static_scene_core(shot: ShotPlan) -> str:
    core = shot.positive_core.strip()
    context = shot_character_text(shot)
    has_cup = any(token in context for token in ("酒杯", "杯子", "玻璃杯"))
    has_scarf = "丝巾" in context
    if has_cup and has_scarf:
        fixed = "床边地毯上只有一只倒放的玻璃杯和一条静止的丝巾，没有其他杯子或玻璃器皿"
        replacements = [
            "床边散落酒杯与丝巾",
            "床边散落着酒杯与丝巾",
            "床边散落玻璃杯与丝巾",
            "床边散落着玻璃杯与丝巾",
        ]
        for old in replacements:
            core = core.replace(old, fixed)
        core = re.sub(r"散落的?酒杯", "一只倒放的玻璃杯", core)
    elif has_cup:
        core = re.sub(r"散落的?酒杯", "只有一只倒放的玻璃杯", core)
        if "只有一只" not in core and "一只" not in core:
            core = f"{core}，画面中只有一只玻璃杯"
    if has_scarf and "静止" not in core and "丝巾" in core:
        core = core.replace("丝巾", "静止的丝巾", 1)
    return core


def infer_manipulated_props(shot: ShotPlan) -> list[str]:
    text = f"{shot.action_intent} {shot.positive_core} {' '.join(shot.subtitle)}"
    specs = [
        (("按钮",), ("按", "按下", "触碰"), "紧急按钮"),
        (("门", "房门"), ("推开", "打开", "关上"), "房门"),
        (("手机",), ("拿", "握", "递", "看"), "手机"),
        (("碗", "稀粥"), ("端", "递", "接", "喝"), "碗"),
        (("陶罐",), ("握", "拿", "举"), "缺口陶罐"),
        (("盐渍",), ("触碰", "指", "看"), "溪边盐渍"),
    ]
    props: list[str] = []
    for prop_tokens, action_tokens, label in specs:
        if any(prop in text for prop in prop_tokens) and any(action in text for action in action_tokens):
            props.append(label)
    return unique_nonempty(props)


def build_static_prop_stability_contract(shot: ShotPlan) -> dict[str, list[str] | str]:
    context = " ".join(
        [
            shot.positive_core,
            shot.framing_focus,
            shot.action_intent,
            shot.scene_name,
        ]
    )
    has_cup = any(token in context for token in ("酒杯", "杯子", "玻璃杯"))
    has_scarf = "丝巾" in context
    if not (has_cup or has_scarf):
        return {
            "must_have_elements": [],
            "prop_must_visible": [],
            "positive_suffix": "",
            "negative_prompt": [],
            "prop_continuity": [],
            "qa_rules": [],
        }

    visible_props: list[str] = []
    continuity_rules = list(STATIC_PROP_STABILITY_RULES)
    qa_rules = ["首帧必须清楚交代关键道具，视频中不新增道具"]
    if has_cup and has_scarf:
        visible_props.append("床边地毯上从第一帧开始固定可见一只倒下的玻璃酒杯和一条丝巾")
        continuity_rules.append("酒杯数量固定为一只，位置、形状、朝向全程保持不变，不生成额外杯子")
        qa_rules.append("酒杯数量固定为一只，不能在后半段冒出第二只酒杯")
    elif has_cup:
        visible_props.append("从第一帧开始固定可见一只玻璃酒杯")
        continuity_rules.append("酒杯数量固定为一只，位置、形状、朝向全程保持不变，不生成额外杯子")
        qa_rules.append("酒杯数量固定为一只，不能在后半段冒出第二只酒杯")
    elif has_scarf:
        visible_props.append("从第一帧开始固定可见一条丝巾")
        continuity_rules.append("丝巾数量和位置全程保持不变，不新增额外丝巾")

    return {
        "must_have_elements": ["关键道具首帧清晰交代"],
        "prop_must_visible": visible_props,
        "positive_suffix": "视频中不要再增加道具，所有道具全程静止",
        "negative_prompt": STATIC_PROP_NEGATIVE_PROMPT,
        "prop_continuity": continuity_rules,
        "qa_rules": qa_rules,
    }


def build_scene_motion_contract(
    shot: ShotPlan,
    active_characters: list[Character] | None = None,
    static_props: list[str] | None = None,
) -> dict[str, Any]:
    active_subjects = unique_nonempty([character.name for character in (active_characters or [])])
    manipulated_props = infer_manipulated_props(shot)
    prop_contract = build_static_prop_stability_contract(shot)
    contract_static_props = unique_nonempty(
        (static_props or []) + [str(item) for item in prop_contract.get("prop_must_visible", [])]
    )
    scene_mode = (
        "static_establishing"
        if not active_subjects and not manipulated_props
        else "character_action_in_static_scene"
    )
    camera_motion_allowed = (
        "固定机位或极轻微稳定推镜，不改变道具相对位置"
        if scene_mode == "static_establishing"
        else "按镜头计划执行，场景道具不得因摄影机运动自行改变数量、位置或形状"
    )
    allowed_motion = ["摄影机运动"] if scene_mode == "static_establishing" else ["人物动作", "人物直接操纵的物体运动", "摄影机运动"]
    if scene_mode == "static_establishing":
        allowed_motion.append("房间光影的轻微自然变化")
    return {
        "scene_mode": scene_mode,
        "description_policy": "场景只写静态状态；能动的只允许人物和人物直接操纵的物体",
        "camera_motion_allowed": camera_motion_allowed,
        "active_subjects": active_subjects,
        "static_props": contract_static_props,
        "manipulated_props": manipulated_props,
        "allowed_motion": allowed_motion,
        "forbidden_scene_motion": SCENE_MOTION_FORBIDDEN,
    }


KNOWN_PROP_PROFILES: list[tuple[tuple[str, ...], str, dict[str, str]]] = [
    (
        ("丝巾",),
        "AYAKA_LIGHT_BLUE_SCARF",
        {
            "display_name": "彩花的浅蓝丝巾",
            "count": "1条",
            "size": "约120cm x 18cm，薄长条布料",
            "color": "浅蓝色，低饱和",
            "material": "柔软丝质或仿丝布料，微弱反光",
            "structure": "长条形围巾，两端自然垂落，无明显图案",
            "canonical_motion_policy": "除非角色明确拿起，否则全程静止，不自行滑动、漂移或变形",
        },
    ),
    (
        ("旧手袋", "手袋"),
        "AYAKA_OLD_HANDBAG",
        {
            "display_name": "彩花的旧手袋",
            "count": "1个",
            "size": "约28cm x 20cm x 10cm",
            "color": "旧深棕色或黑褐色",
            "material": "磨旧皮革",
            "structure": "软质手提包，顶部开口，短手柄",
            "canonical_motion_policy": "除非角色明确拿起，否则固定在首帧位置，不自行开合或移动",
        },
    ),
    (
        ("化妆品盒", "化妆盒"),
        "AYAKA_COSMETIC_BOX",
        {
            "display_name": "彩花的化妆品盒",
            "count": "1个",
            "size": "约16cm x 10cm x 4cm",
            "color": "旧玫瑰色或暗粉色",
            "material": "硬质塑料或薄金属外壳",
            "structure": "小型矩形翻盖盒，边角圆钝",
            "canonical_motion_policy": "除非角色明确拿起，否则首帧到结尾保持同一位置和朝向",
        },
    ),
    (
        ("樱子照片", "校服照片", "照片"),
        "SAKURA_SCHOOL_PHOTO",
        {
            "display_name": "佐藤樱子的校服照片",
            "count": "1张",
            "size": "约10cm x 15cm，薄纸照片",
            "color": "低饱和照片色调，白色细边",
            "material": "相纸",
            "structure": "单张矩形照片，平整薄片",
            "canonical_motion_policy": "除非角色明确拿起或翻面，否则平放静止，不新增照片副本",
        },
    ),
    (
        ("手机", "电话", "来电", "听筒"),
        "KENICHI_SMARTPHONE",
        {
            "display_name": "田中健一的智能手机",
            "count": "1部",
            "size": "约15cm x 7cm x 0.8cm",
            "color": "黑色或深灰色",
            "material": "玻璃屏幕与金属边框",
            "structure": "薄矩形智能手机，窄边框，侧面保持轻薄",
            "canonical_motion_policy": "由持有人手持或放置，不能自行漂移、换手或变厚",
        },
    ),
    (
        ("领带",),
        "KENICHI_TIE",
        {
            "display_name": "田中健一的深色领带",
            "count": "1条",
            "size": "约145cm x 8cm，薄布料",
            "color": "深灰色或深蓝黑色",
            "material": "哑光织物",
            "structure": "窄长领带，系在衬衫领口或松开垂落",
            "canonical_motion_policy": "随人物身体轻微运动，不自行飘动或复制",
        },
    ),
    (
        ("纸袋",),
        "MISAKI_PAPER_BAG",
        {
            "display_name": "佐藤美咲的纸袋",
            "count": "1个",
            "size": "约24cm x 32cm x 10cm",
            "color": "低饱和牛皮纸色",
            "material": "厚纸",
            "structure": "竖向矩形手提纸袋，双纸绳提手",
            "canonical_motion_policy": "由佐藤美咲手持或放置，位置和数量保持稳定",
        },
    ),
]


def build_auto_i2v_contract(shot: ShotPlan) -> dict[str, Any]:
    text = " ".join([shot.framing_focus, shot.action_intent, shot.positive_core, " ".join(shot.subtitle)])
    prop_library: dict[str, dict[str, str]] = {}
    prop_contract: list[dict[str, Any]] = []
    for tokens, prop_id, profile in KNOWN_PROP_PROFILES:
        if not any(token in text for token in tokens):
            continue
        prop_library[prop_id] = dict(profile)
        contract: dict[str, Any] = {
            "prop_id": prop_id,
            "position": shot.framing_focus,
            "first_frame_visible": "首帧" in text or "可见" in text,
            "motion_policy": profile["canonical_motion_policy"],
            "controlled_by": "none",
        }
        if prop_id == "KENICHI_SMARTPHONE" and any(
            normalize_dialogue_source(line.get("source"), line.get("text", ""), line.get("purpose", "")) == "phone"
            for line in shot.dialogue
            if isinstance(line, dict)
        ):
            listeners = phone_dialogue_listeners(shot.dialogue)
            contract["controlled_by"] = listeners[0] if listeners else "onscreen listener"
            contract["screen_orientation"] = "screen facing inward toward holder"
            contract["screen_content_visible"] = False
        prop_contract.append(contract)

    onscreen_speakers = onscreen_dialogue_speakers(shot.dialogue)
    phone_lines = [
        line
        for line in shot.dialogue
        if isinstance(line, dict)
        and normalize_dialogue_source(line.get("source"), line.get("text", ""), line.get("purpose", "")) == "phone"
    ]
    if shot.dialogue:
        shot_task = "dialogue"
    elif prop_contract:
        shot_task = "prop_display"
    else:
        shot_task = "action"
    risk_level = "high" if len(onscreen_speakers) >= 2 or (phone_lines and onscreen_speakers) else "low"
    phone_contract: dict[str, Any] = {}
    if phone_lines:
        listeners = phone_dialogue_listeners(shot.dialogue)
        phone_contract = {
            "holder": listeners[0] if listeners else "onscreen listener",
            "screen_orientation": "screen facing inward toward holder",
            "screen_content_visible": False,
            "listener_lip_policy": "listener stays silent with no lip movement while remote voice speaks",
        }
    return {
        "shot_task": shot_task,
        "risk_level": risk_level,
        "risk_notes": "",
        "prop_library": prop_library,
        "prop_contract": prop_contract,
        "phone_contract": phone_contract,
    }


def merge_i2v_contract(auto_contract: dict[str, Any], llm_contract: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(llm_contract, dict):
        return auto_contract
    merged = dict(auto_contract)
    merged.update({key: value for key, value in llm_contract.items() if value not in (None, "", [], {})})
    auto_library = auto_contract.get("prop_library") if isinstance(auto_contract.get("prop_library"), dict) else {}
    llm_library = llm_contract.get("prop_library") if isinstance(llm_contract.get("prop_library"), dict) else {}
    merged["prop_library"] = {**auto_library, **llm_library}
    auto_props = auto_contract.get("prop_contract") if isinstance(auto_contract.get("prop_contract"), list) else []
    llm_props = llm_contract.get("prop_contract") if isinstance(llm_contract.get("prop_contract"), list) else []
    merged["prop_contract"] = auto_props + llm_props
    auto_phone = auto_contract.get("phone_contract") if isinstance(auto_contract.get("phone_contract"), dict) else {}
    llm_phone = llm_contract.get("phone_contract") if isinstance(llm_contract.get("phone_contract"), dict) else {}
    merged["phone_contract"] = {**auto_phone, **llm_phone}
    return merged


def build_auto_dialogue_blocking(shot: ShotPlan) -> dict[str, Any]:
    if not shot.dialogue:
        return {
            "active_speaker": "",
            "first_speaker": "",
            "speaker_visual_priority": "no_dialogue",
            "silent_visible_characters": [],
            "lip_sync_policy": "no_dialogue",
        }
    first = shot.dialogue[0] if isinstance(shot.dialogue[0], dict) else {}
    first_speaker = str(first.get("speaker") or "")
    source = normalize_dialogue_source(first.get("source"), first.get("text", ""), first.get("purpose", ""))
    onscreen = onscreen_dialogue_speakers(shot.dialogue)
    if source == "phone":
        listeners = phone_dialogue_listeners(shot.dialogue)
        return {
            "active_speaker": first_speaker,
            "first_speaker": first_speaker,
            "speaker_visual_priority": "listener_visible",
            "silent_visible_characters": listeners,
            "lip_sync_policy": "remote_voice_listener_silent",
        }
    active = first_speaker or (onscreen[0] if onscreen else "")
    return {
        "active_speaker": active,
        "first_speaker": active,
        "speaker_visual_priority": "center_face",
        "silent_visible_characters": [name for name in onscreen if name != active],
        "lip_sync_policy": "single_active_speaker",
    }


def build_auto_first_frame_contract(shot: ShotPlan, prop_contract: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "location": shot.scene_name,
        "visual_center": shot.framing_focus,
        "visible_characters": visible_dialogue_characters(shot),
        "character_positions": {},
        "key_props": [str(item.get("prop_id") or "") for item in prop_contract if isinstance(item, dict) and item.get("prop_id")],
        "speaking_state": (shot.dialogue[0].get("speaker") if shot.dialogue and isinstance(shot.dialogue[0], dict) else "no dialogue"),
        "camera_motion_allowed": shot.movement,
    }


def shot_positive_core_with_static_props(shot: ShotPlan) -> str:
    prop_contract = build_static_prop_stability_contract(shot)
    core = normalize_static_scene_core(shot)
    positive_suffix = str(prop_contract.get("positive_suffix") or "").strip()
    if positive_suffix and positive_suffix not in core:
        return f"{core}，{positive_suffix}"
    return core


def shot_prompt_core_with_truth(source: ProjectSource, episode_plan: EpisodePlan, shot: ShotPlan) -> str:
    truth_prefix = truth_prompt_prefix(source, episode_plan, shot)
    positive_core = shot_positive_core_with_static_props(shot)
    if truth_prefix:
        return f"{truth_prefix}，{positive_core}"
    return positive_core


def negative_prompt_with_truth(source: ProjectSource, episode_plan: EpisodePlan, shot: ShotPlan) -> list[str]:
    contract = build_story_truth_contract(source.text, episode_plan, shot)
    prop_contract = build_static_prop_stability_contract(shot)
    return list(
        dict.fromkeys(
            DEFAULT_NEGATIVE_PROMPT
            + [str(item) for item in contract.get("must_not_drift", [])]
            + [str(item) for item in prop_contract.get("negative_prompt", [])]
        )
    )


def keyframe_has_temporal_risk(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token.lower() in lowered for token in KEYFRAME_UNSAFE_FRAGMENT_TOKENS)


def clean_keyframe_fragment(fragment: str) -> str:
    text = str(fragment or "").strip(" ，,；;。.\n\t")
    text = text.replace("。，", "。").replace("；，", "；")
    text = text.replace("首帧后段可见", "首帧可见")
    text = text.replace("首帧进入后静止", "首帧静止")
    text = text.replace("进入后静止", "静止")
    text = text.replace("贴近田中健一耳侧", "与田中健一保持克制社交距离低声说话")
    text = text.replace("贴近健一耳侧", "与健一保持克制社交距离低声说话")
    text = text.replace("低语", "低声说话")
    text = text.replace("领带松开垂在他的胸前", "领带略松并清楚可见")
    text = text.replace("松开领带垂在胸前", "领带略松并清楚可见")
    text = re.sub(r"贴近([^，,；;。]+?)耳侧", r"与\1保持克制社交距离低声说话", text)
    text = re.sub(r"被临时警员带入后", "", text)
    return text.strip(" ，,；;。.\n\t")


def sanitize_keyframe_static_text(text: str, fallback: str = "") -> str:
    raw = str(text or "").strip()
    if not raw:
        return fallback
    raw = clean_keyframe_fragment(raw)
    unsafe_positions = [
        raw.find(token) for token in KEYFRAME_UNSAFE_FRAGMENT_TOKENS
        if token in raw and raw.find(token) > 0
    ]
    if unsafe_positions:
        raw = clean_keyframe_fragment(raw[:min(unsafe_positions)])

    candidates: list[str] = []
    for sentence in KEYFRAME_TEMPORAL_SPLIT_RE.split(raw):
        sentence = clean_keyframe_fragment(sentence)
        if not sentence:
            continue
        for clause in KEYFRAME_CLAUSE_SPLIT_RE.split(sentence):
            clause = clean_keyframe_fragment(clause)
            if not clause:
                continue
            if keyframe_has_temporal_risk(clause):
                continue
            candidates.append(clause)

    hinted = [
        item for item in candidates
        if any(token in item for token in KEYFRAME_FIRST_FRAME_HINT_TOKENS)
    ]
    selected = hinted or candidates
    if not selected:
        return fallback or clean_keyframe_fragment(raw)
    return "，".join(selected[:5])


def sanitize_keyframe_movement(movement: str) -> str:
    text = str(movement or "").strip()
    if not text:
        return KEYFRAME_STATIC_MOVEMENT
    if any(token in text for token in KEYFRAME_UNSAFE_MOVEMENT_TOKENS):
        return KEYFRAME_STATIC_MOVEMENT
    return text


def sanitize_keyframe_scene_name(scene_name: str, risk_detected: bool) -> str:
    text = str(scene_name or "").strip()
    if not risk_detected:
        return text
    parts = [part.strip() for part in re.split(r"[至到与]", text, maxsplit=1) if part.strip()]
    return parts[0] if parts else text


def build_keyframe_static_anchor(shot: ShotPlan) -> dict[str, Any]:
    risk_detected = any(
        keyframe_has_temporal_risk(value)
        for value in (
            shot.scene_name,
            shot.movement,
            shot.framing_focus,
            shot.action_intent,
            shot.positive_core,
        )
    )
    scene_name = sanitize_keyframe_scene_name(shot.scene_name, risk_detected)
    movement = sanitize_keyframe_movement(shot.movement)
    framing_focus = sanitize_keyframe_static_text(shot.framing_focus, fallback=shot.positive_core)
    positive_core = sanitize_keyframe_static_text(shot.positive_core, fallback=framing_focus)
    visibility_contract = dialogue_visibility_contract(shot)
    if visibility_contract:
        if framing_focus and "对白可见人物契约" not in framing_focus and "电话/画外声音契约" not in framing_focus:
            framing_focus = f"{framing_focus} {visibility_contract}"
        if positive_core and "对白可见人物契约" not in positive_core and "电话/画外声音契约" not in positive_core:
            positive_core = f"{positive_core} {visibility_contract}"
    if positive_core:
        positive_core = f"{positive_core}，{KEYFRAME_STATIC_FRAME_GUARD}"
    else:
        positive_core = KEYFRAME_STATIC_FRAME_GUARD
    return {
        "policy": "single_static_start_frame",
        "risk_detected": risk_detected,
        "scene_name": scene_name,
        "movement": movement,
        "framing_focus": framing_focus,
        "action_intent": f"只表现起始帧的静态状态：{framing_focus}" if framing_focus else "只表现起始帧的静态状态",
        "positive_core": positive_core,
        "negative_prompt": KEYFRAME_NEGATIVE_PROMPT,
    }


def render_ai_prompt_pack(source: ProjectSource, bible: ProjectBible, episode_plan: EpisodePlan, shots: list[ShotPlan]) -> str:
    language_lock = "所有角色对白、旁白和模型音频只使用普通话中文；屏幕字幕只使用简体中文；日文只允许作为无声环境招牌，不得成为对白或字幕"
    return md_header(source.project_name, source.title, f"{episode_plan.episode_label}AI生成提示词包") + "\n".join(
        f"## {s.shot_id} {s.intent}\n正向提示词：{bible.setting}，{language_lock}，{shot_prompt_core_with_truth(source, episode_plan, s)}\n负向提示词：{', '.join(negative_prompt_with_truth(source, episode_plan, s))}\n"
        for s in shots
    )


def render_character_visual_pack(source: ProjectSource, bible: ProjectBible) -> str:
    return md_header(source.project_name, source.title, "角色统一视觉设定包") + "\n".join(
        f"## {c.name}\n- ID：{c.character_id}\n- 视觉锚点：{c.visual_anchor}\n- 禁止漂移：年龄、服装、时代感、脸型、气质不得跳变。\n"
        for c in bible.characters
    )


def render_character_poster_pack(source: ProjectSource, bible: ProjectBible) -> str:
    return md_header(source.project_name, source.title, "角色海报提示词包") + "\n".join(
        f"## {c.name}\n{bible.setting}，{c.visual_anchor}，半身角色海报，正面或三分之二侧脸，低饱和写实电影感。\n"
        for c in bible.characters
    )


def render_cover_title_pack(source: ProjectSource, bible: ProjectBible, episode_plan: EpisodePlan) -> str:
    anchors = bible.core_selling_points
    titles = [
        f"{anchors[0]}，他发现真相不对劲",
        f"一条丝巾，牵出银座最危险的秘密",
        f"她死在酒店，却把小樱托付给他",
        f"看似自杀的现场，藏着亲密关系的谎言",
        f"刑警一句话，让所有人开始害怕",
        f"姐姐死后，妹妹先防备的不是凶手",
        f"前夜的温柔，第二天变成证据",
        f"他只隐瞒一句话，却被卷进命案",
        f"酒店套房里的秘密，指向一个孩子",
        f"{episode_plan.hook}",
    ]
    cover = anchors + [episode_plan.hook]
    return md_header(source.project_name, source.title, f"{episode_plan.episode_label}封面标题测试包") + "\n".join(
        f"- 标题{i}：{title}" for i, title in enumerate(titles, start=1)
    ) + "\n\n" + "\n".join(f"- 封面文案{i}：{item}" for i, item in enumerate(cover[:5], start=1)) + "\n"


def render_character_output_list(source: ProjectSource, bible: ProjectBible, episode_plan: EpisodePlan) -> str:
    return md_header(source.project_name, source.title, f"{episode_plan.episode_label}角色出图清单") + "\n".join(
        f"- {c.character_id} / {c.name}：{c.visual_anchor}" for c in bible.characters
    ) + "\n"


def render_scene_output_list(source: ProjectSource, episode_plan: EpisodePlan, shots: list[ShotPlan]) -> str:
    return md_header(source.project_name, source.title, f"{episode_plan.episode_label}场景出图清单") + "\n".join(
        f"- {s.scene_id} / {s.scene_name}：{shot_prompt_core_with_truth(source, episode_plan, s)}" for s in shots
    ) + "\n"


def build_scene_detail_body(scene_name: str, setting: str) -> str:
    name = str(scene_name or "未命名场景").strip()
    setting_text = str(setting or "写实电影空间").strip()
    if "客厅" in name:
        return (
            f"该客厅以{setting_text}为视觉基线，空间开阔但陈设克制，低矮茶几、深色沙发、木质地板和浅灰墙面构成稳定层次。"
            "窗帘过滤自然光，在地面和家具边缘形成柔和斑驳光影；空气保持清洁微凉，远处城市低频声被墙面与织物吸收。"
            "地面材质有细微反光，织物、皮革与木纹触感区分清楚，整体空间适合作为室内固定场景的稳定背景。"
        )
    if any(token in name for token in ("门口", "玄关", "走廊", "门厅")):
        return (
            f"该入口空间延续{setting_text}的低饱和写实风格，狭长动线由门板、墙面、地垫和侧柜形成清楚的前后层次。"
            "门框边缘与墙面阴影提供明确空间边界，顶灯或廊灯投下稳定光区，地面反射轻微而不过曝。"
            "材质以木门、金属门把、石材或复合地面为主，声音呈短促回响，适合作为入户、离场和通讯打断等转场镜头的地点基础。"
        )
    if "酒店" in name or "套房" in name:
        return (
            f"该酒店室内空间采用{setting_text}的都市酒店质感，厚重窗帘、床铺、地毯、玻璃杯具与金属灯具形成高密度室内层次。"
            "冷色窗光与暖色床头灯交叠，织物褶皱、玻璃反光和地毯纹理保持清晰；空气中有香水、酒精和空调冷气的混合感。"
            "空间尺度紧凑而精致，适合固定道具、证据细节和调查镜头保持统一的材质与光影连续性。"
        )
    if any(token in name for token in ("警视厅", "警署", "调查室", "审讯室")):
        return (
            f"该都市刑侦空间以{setting_text}为基准，桌椅、文件柜、百叶窗、冷白顶灯和灰色墙面构成硬朗秩序。"
            "光线方向明确，桌面反光受控，文件纸张、金属柜门和塑料椅面有可辨材质差异；空间回声短促干燥。"
            "整体尺度偏紧，背景信息保持简洁，适合询问、证据展示和电话信息传递时维持稳定空间识别。"
        )
    if any(token in name for token in ("街", "巷", "银座", "户外", "路口")):
        return (
            f"该城市外景呈现{setting_text}的空间秩序，街面铺装、玻璃橱窗、路灯、招牌和远处车流构成纵深层次。"
            "环境光受霓虹、店面灯和天光共同影响，地面可能带有轻微湿润反光；空气中混合冷风、车流声与城市低频噪声。"
            "背景招牌只作为无声环境文字存在，空间适合建立地点、转场和外部环境压力，保持纯地点识别功能。"
        )
    return (
        f"该地点遵循{setting_text}的写实电影美术风格，空间结构、主材质、光源方向和背景层次保持统一。"
        "墙面、地面、家具或固定装置形成清楚的前中后景关系，光影稳定不过度戏剧化，声音环境保持低频真实。"
        "该地点作为可复用基础场景，只记录建筑、陈设、材质、光线、温度和声音等地点信息。"
    )


def build_scene_detail_map(shots: list[ShotPlan], setting: str) -> dict[str, str]:
    scene_names = unique_nonempty([shot.scene_name for shot in shots])
    return {scene_name: build_scene_detail_body(scene_name, setting) for scene_name in scene_names}


def render_scene_detail_txt(scene_detail_map: dict[str, str]) -> str:
    blocks: list[str] = []
    for scene_name, detail in scene_detail_map.items():
        blocks.append(f"【{scene_name}】\n{detail.strip()}")
    return "\n\n".join(blocks).strip() + "\n"


def render_seedance_table(source: ProjectSource, episode_plan: EpisodePlan, shots: list[ShotPlan]) -> str:
    rows = "\n".join(f"| {s.shot_id} | {s.priority} | {s.duration_sec}s | {s.intent} | {shot_prompt_core_with_truth(source, episode_plan, s)} |" for s in shots)
    return md_header(source.project_name, source.title, f"{episode_plan.episode_label}Seedance2.0逐镜头执行表") + f"""| 镜头 | 优先级 | 时长 | 意图 | prompt核心 |
| --- | --- | --- | --- | --- |
{rows}
"""


def render_final_prompt_pack(source: ProjectSource, bible: ProjectBible, episode_plan: EpisodePlan, shots: list[ShotPlan]) -> str:
    language_lock = "Spoken audio language: Mandarin Chinese only. No Japanese, English, or mixed-language speech. Simplified Chinese subtitles only. Japanese signage is allowed only as silent background environment text."
    return md_header(source.project_name, source.title, f"{episode_plan.episode_label}Seedance2.0最终提示词包") + "\n".join(
        f"## {s.shot_id}\n{language_lock}\n{bible.setting}，{shot_prompt_core_with_truth(source, episode_plan, s)}\n" for s in shots
    )


def render_field_mapping(source: ProjectSource, episode_plan: EpisodePlan) -> str:
    return md_header(source.project_name, source.title, "提示词字段映射研究") + f"""## 字段映射
- project_meta：来自短剧总纲、分集大纲、{episode_plan.episode_label}封面标题测试包。
- emotion_arc：来自适配诊断、{episode_plan.episode_label}镜头脚本。
- character_anchor：来自人物关系与角色卡、角色统一视觉设定包。
- scene_anchor：来自视觉风格与分镜方案、场景出图清单。
- shot_execution：来自{episode_plan.episode_label}镜头脚本和Seedance逐镜头执行表。
- dialogue_language：来自{episode_plan.episode_label}剧本和旁白字幕稿。
- language_policy：来自 project_bible_v1.json，并复制进每个 records/EPxx_SHxx_record.json，由 run_seedance_test.py 注入最终 prompt。
"""


def render_video_director_runbook(
    source: ProjectSource,
    paths: ProjectPaths,
    episode_plan: EpisodePlan,
    shots: list[ShotPlan],
) -> str:
    shots_arg = ",".join(s.shot_id for s in shots)
    bundle_rel = paths.out_dir.relative_to(REPO_ROOT)
    prefix = f"{source.project_name.lower()}_{episode_plan.episode_id.lower()}_director"
    return md_header(source.project_name, source.title, f"{episode_plan.episode_label}视频导演准备运行手册") + f"""## 目标
把 planning bundle 推进到视频生成前的导演准备状态：

```text
language plan -> start keyframes -> image input map
```

本手册不生成视频，不调用 `run_seedance_test.py`，只准备下一阶段视频生成所需的 `duration_overrides.json` 和 `image_input_map.json`。

## 一键命令
```bash
python3 scripts/run_novel_video_director.py \\
  --bundle {bundle_rel} \\
  --episode {episode_plan.episode_id} \\
  --experiment-prefix {prefix} \\
  --provider openai \\
  --allow-data-uri-from-local \\
  --shots {shots_arg}
```

## 安全预检命令
```bash
python3 scripts/run_novel_video_director.py \\
  --bundle {bundle_rel} \\
  --episode {episode_plan.episode_id} \\
  --experiment-prefix {prefix}_check \\
  --provider openai \\
  --allow-data-uri-from-local \\
  --prepare-only \\
  --shots {shots_arg}
```

## 默认策略
- keyframe phase 固定为 `start`。
- 默认不生成 end frame。
- `image_input_map.json` 允许只有 `image` 字段，不强制 `last_image`。
- 角色参考图来自 `{paths.novel_dir.relative_to(REPO_ROOT) / 'character_image_map.json'}`。

## 主要输出
```text
test/{prefix}_language/language/duration_overrides.json
test/{prefix}_language/language/language_plan.json
test/{prefix}_keyframes/keyframe_manifest.json
test/{prefix}_keyframes/image_input_map.json
test/{prefix}_director_manifest.json
```
"""


def character_image_filename(character: Character, image_ext: str) -> str:
    ext = image_ext.strip().lower().lstrip(".") or "jpg"
    if ext == "jpeg":
        ext = "jpg"
    return f"{character.character_id}.{ext}"


def infer_character_gender(character: Character) -> str:
    seed = f"{character.character_id} {character.name} {character.visual_anchor}".lower()
    if any(token in seed for token in ("female", "woman", "美咲", "彩花", "女性", "女人", "少女")):
        return "female"
    return "male"


def infer_character_age(character: Character) -> str:
    text = character.visual_anchor
    for pattern in (r"\d+\s*[-~到至]\s*\d+\s*岁", r"\d+\s*岁", r"[二三四五六七八九十]+十多岁"):
        match = re.search(pattern, text)
        if match:
            return match.group(0).replace(" ", "")
    if character.character_id == "KENICHI_MAIN":
        return "四十岁左右"
    if character.character_id == "MISAKI_FEMALE":
        return "二十多岁"
    if character.character_id == "AYAKA_VICTIM":
        return "三十多岁"
    if character.character_id == "SAKURA_CHILD":
        return "十四岁"
    if character.character_id == "RYUZAKI_RIVAL":
        return "四十出头"
    if character.character_id == "YAMADA_ELDER":
        return "六十出头"
    return "三十多岁"


def infer_character_location(setting: str, character: Character) -> str:
    known = {
        "ISHIKAWA_DETECTIVE": "东京警视厅、银座酒店案发现场",
        "KENICHI_MAIN": "东京公司、银座酒店与个人公寓",
        "MISAKI_FEMALE": "银座俱乐部、酒店走廊与家族私密空间",
        "AYAKA_VICTIM": "银座俱乐部、高级酒店套房与回忆闪回空间",
        "SAKURA_CHILD": "佐藤家客厅、东京站与新干线车厢",
        "RYUZAKI_RIVAL": "警视厅调查室、银座俱乐部周边",
        "YAMADA_ELDER": "警视厅调查室、医院证明相关空间",
        "ATO_DRIVER": "银座街角、出租车或行车记录相关空间",
        "TARO_STREAMER": "直播截图、银座夜场外围空间",
    }
    return known.get(character.character_id, setting.split("，", 1)[0])


def build_character_profile_text(character: Character) -> str:
    known_profiles = {
        "ISHIKAWA_DETECTIVE": "警视厅刑警，负责佐藤彩花死亡案。说话平静，观察细致，擅长用温和语气施压。",
        "KENICHI_MAIN": "普通上班族，也是佐藤彩花的常客之一。被“小樱托付”卷入案件，承担观众代入和情绪摇摆功能。",
        "MISAKI_FEMALE": "佐藤彩花的妹妹，表面柔顺清纯，实际警觉克制，试图保护家族秘密和小樱。",
        "AYAKA_VICTIM": "银座夜场女性，死亡事件的核心人物。她主要通过回忆、遗物和他人口供出现。",
        "SAKURA_CHILD": "佐藤彩花的女儿，也是全书救济选择的核心对象。她以小樱、樱子等别名出现，必须安全、非情色化呈现。",
        "RYUZAKI_RIVAL": "俱乐部竞争者和早期嫌疑人，用商业纠葛制造误导，后续被证据排除。",
        "YAMADA_ELDER": "与匿名小说和旧名片相关的年长常客，负责把调查引向彩花过去的人际链条。",
        "ATO_DRIVER": "酒店周边徘徊线索中的重要关系人，承担中段嫌疑扩散和排除功能。",
        "TARO_STREAMER": "丝巾直播截图相关的重要排除对象，用于补全证据链条。",
    }
    return known_profiles.get(
        character.character_id,
        f"{character.name}是短剧中的关键角色，视觉锚点为：{character.visual_anchor}。",
    )


def build_character_appearance_profile(character: Character) -> dict[str, str]:
    known: dict[str, dict[str, str]] = {
        "ISHIKAWA_DETECTIVE": {
            "age_impression": "三十多岁，成熟但不显老",
            "face_structure": "偏长脸，窄下颌，脸部线条干净克制",
            "facial_features": "眼尾略下压，目光温和但有审视感，鼻梁清晰，嘴角少表情",
            "hair": "短黑发，整齐后梳或自然侧分，不凌乱",
            "body_posture": "身形偏瘦挺拔，肩背平直，动作节制",
            "wardrobe_anchor": "深色旧西装、白衬衫、低调领带，刑警便装感",
            "color_material": "炭黑、深灰、冷白，哑光羊毛西装质感",
            "class_detail": "警视厅刑警，袖口略旧但干净，职业感强",
            "default_expression": "平静、温和、压迫感藏在眼神里",
            "contrast_with_others": "不要像田中健一；石川更瘦、更规整、更冷静，脸型更长，西装更像刑警制服化便装",
            "forbidden_drift": "不要圆脸、不要疲惫上班族感、不要松垮领带、不要年轻偶像感",
        },
        "KENICHI_MAIN": {
            "age_impression": "四十岁左右，普通中年上班族",
            "face_structure": "脸型更圆钝或略宽，下颌不锋利，生活感明显",
            "facial_features": "眼下疲惫，眉间有压力纹，五官普通可靠，不精英化",
            "hair": "短黑发略乱，发际线自然，像刚下班未整理",
            "body_posture": "肩背略塌，站姿有疲惫感，手部常显局促",
            "wardrobe_anchor": "灰色或深蓝商务西装，衬衫略皱，领带略松",
            "color_material": "灰蓝、暗灰、旧白，普通通勤面料",
            "class_detail": "公司职员，衣着合格但没有权力感或刑警感",
            "default_expression": "可靠但迟疑，眼神藏着不安和愧疚",
            "contrast_with_others": "不要像石川悠一；健一更普通、更疲惫、更圆钝，领带和肩背状态更松",
            "forbidden_drift": "不要刑警气质、不要精英冷峻、不要过度英俊、不要夜场成熟感",
        },
        "MISAKI_FEMALE": {
            "age_impression": "二十多岁，年轻但经历压力",
            "face_structure": "鹅蛋脸或小瓜子脸，下巴柔和，脸部轮廓比彩花更清淡",
            "facial_features": "低垂眼，眼神警觉回避，妆容淡，唇色自然",
            "hair": "黑色中长直发或低马尾，发型素净，不做成熟卷发",
            "body_posture": "肩颈紧绷，站姿克制，手指常有防备性收紧",
            "wardrobe_anchor": "灰色外套、素色连衣裙，偶尔姐姐旧礼服但穿出拘谨感",
            "color_material": "灰、米白、暗粉，棉呢或旧丝绸，低调不闪耀",
            "class_detail": "银座俱乐部后台与家族照护之间的人，素净、警觉、压抑",
            "default_expression": "柔顺表面下有防备，目光常避开正视",
            "contrast_with_others": "不要像佐藤彩花；美咲更年轻、更素净、更紧绷，妆发更淡，缺少夜场掌控感",
            "forbidden_drift": "不要成熟艳丽、不要浓妆、不要长卷发夜场女王感、不要未成年化",
        },
        "AYAKA_VICTIM": {
            "age_impression": "三十多岁，成熟银座夜场女性",
            "face_structure": "脸部线条更成熟柔媚，颧骨和下颌比美咲更有存在感",
            "facial_features": "眼神温柔但带计算感，妆容精致克制，唇线清晰",
            "hair": "深色长卷发或精心打理的波浪发，发丝有光泽",
            "body_posture": "姿态柔软、肩颈放松，动作有职业化的亲近感但保持得体",
            "wardrobe_anchor": "丝质礼服、披肩或细腻外套，夜场职业精致感",
            "color_material": "浅粉、酒红、珍珠白，丝绸和柔光材质",
            "class_detail": "银座夜场女性，精致、会经营距离与情绪",
            "default_expression": "温柔微笑中带试探和控制",
            "contrast_with_others": "不要像佐藤美咲；彩花更成熟、更精致、更会掌控关系，发型是长卷发而不是素直发",
            "forbidden_drift": "不要少女化、不要素净后台感、不要校服感、不要露骨或情色姿态",
        },
        "SAKURA_CHILD": {
            "age_impression": "十四岁，明确未成年少女",
            "face_structure": "圆脸或小鹅蛋脸，脸颊仍有稚嫩感",
            "facial_features": "眼睛清澈但不安，五官未成人化，妆容为无妆",
            "hair": "黑色学生短发、齐肩发或低马尾，发型简单",
            "body_posture": "身形瘦小，肩膀窄，坐姿和站姿都有不安的收缩感",
            "wardrobe_anchor": "日本学生校服、针织开衫或简单日常外套",
            "color_material": "藏青、白、浅灰，棉布和针织材质",
            "class_detail": "被保护的孩子，家庭创伤中的希望线",
            "default_expression": "困惑、依赖、轻微畏惧，逐渐建立信任",
            "contrast_with_others": "必须明显不同于美咲和彩花；樱子是未成年人，脸更圆、体态更小、服装是校服或日常学生装",
            "forbidden_drift": "禁止成人化、禁止夜场服饰、禁止浓妆、禁止性感姿态、禁止像美咲或彩花",
        },
        "RYUZAKI_RIVAL": {
            "age_impression": "四十出头，银座生意场中年男性",
            "face_structure": "宽脸或方脸，下颌厚重，脸部比石川更有压迫和油滑感",
            "facial_features": "额头易出汗，眼睛眯起，嘴角紧张，表情防御",
            "hair": "短发油亮后梳，商务感强但略显紧绷",
            "body_posture": "肩宽，坐姿前倾，手指交叠显焦躁",
            "wardrobe_anchor": "笔挺深色商务西装，衬衫和领带更商业化",
            "color_material": "黑、深酒红、亮面皮鞋，西装面料略有光泽",
            "class_detail": "俱乐部竞争者，生意人而非刑警或普通职员",
            "default_expression": "强作镇定、急于辩解",
            "contrast_with_others": "不要像石川或健一；龙崎更宽脸、更商业、更油亮紧张，西装更昂贵但更浮",
            "forbidden_drift": "不要刑警冷静感、不要普通上班族疲惫感、不要老年常客感",
        },
        "YAMADA_ELDER": {
            "age_impression": "六十出头，年长男性",
            "face_structure": "瘦长老年脸，脸颊略塌，皱纹清楚",
            "facial_features": "眼神躲闪，鼻梁和法令纹明显，嘴唇偏薄",
            "hair": "花白短发，略稀疏，整理但不时髦",
            "body_posture": "肩背微弯，双手平放或轻叩膝盖，动作慢",
            "wardrobe_anchor": "旧式西装，领口微敞，衬衫略松",
            "color_material": "深棕、灰黑、旧白，老派羊毛或混纺面料",
            "class_detail": "年长常客，体面但虚弱，和医院证明、匿名小说线索相关",
            "default_expression": "强作镇定，沙哑防御",
            "contrast_with_others": "不要像龙崎；山田更老、更瘦、更虚弱，衣着老派，不是生意场强势男人",
            "forbidden_drift": "不要年轻化、不要油亮商务、不要刑警感、不要黑社会感",
        },
        "ATO_DRIVER": {
            "age_impression": "三十多岁到四十岁，边缘关系人",
            "face_structure": "窄脸或瘦削脸，颧骨略明显",
            "facial_features": "眼神游移，胡茬淡，神情疲惫紧张",
            "hair": "短发自然凌乱，帽檐压痕或风吹感",
            "body_posture": "身体略前缩，站姿不稳定，像随时想离开",
            "wardrobe_anchor": "深色便装外套、旧衬衫或司机夹克",
            "color_material": "黑、藏青、灰，耐磨布料和旧皮革",
            "class_detail": "酒店周边徘徊线索中的司机/关系人，城市边缘感",
            "default_expression": "沉默、回避、紧张",
            "contrast_with_others": "不要像健一；阿彻更瘦削、更边缘、更街头，服装不是正式西装",
            "forbidden_drift": "不要商务精英、不要刑警、不要夜场老板感",
        },
        "TARO_STREAMER": {
            "age_impression": "二十多岁到三十岁，年轻外放男性",
            "face_structure": "年轻圆脸或短下巴，表情更松散",
            "facial_features": "眼神外放，笑容随意，五官比其他男性更年轻",
            "hair": "短发带造型或轻微染色，休闲感",
            "body_posture": "站姿放松，肩膀松，动作更大",
            "wardrobe_anchor": "街头休闲外套、T恤、直播者日常装",
            "color_material": "黑白对比、亮色小面积点缀，棉质和尼龙材质",
            "class_detail": "直播截图相关人物，年轻、随意、社交媒体感",
            "default_expression": "轻率、外放、自证时有点慌",
            "contrast_with_others": "不要像龙崎或健一；太郎更年轻、更休闲、更街头，不穿正式西装",
            "forbidden_drift": "不要中年商务、不要刑警、不要老年常客感",
        },
    }
    if character.character_id in known:
        return known[character.character_id]

    return {
        "age_impression": infer_character_age(character),
        "face_structure": "脸型骨相必须与同项目其他角色区分，避免复用默认美型脸",
        "facial_features": character.visual_anchor,
        "hair": "发型必须来自角色身份和时代，不与同项目同性别角色重复",
        "body_posture": "体态和站姿体现职业、阶层和心理状态",
        "wardrobe_anchor": "服装主锚点符合角色身份、职业和故事环境",
        "color_material": "服饰颜色和材质应稳定，并与其他角色形成区分",
        "class_detail": character.visual_anchor,
        "default_expression": "表情符合人格锚点：" + "、".join(character.persona_anchor),
        "contrast_with_others": "必须和同项目其他角色在脸型、发型、体态、服装颜色材质上明显不同",
        "forbidden_drift": "不要复用同项目其他角色的脸型、发型、服装模板；不要年龄漂移或职业漂移",
    }


def render_appearance_profile(profile: dict[str, str]) -> str:
    labels = [
        ("age_impression", "年龄观感"),
        ("face_structure", "脸型骨相"),
        ("facial_features", "五官特征"),
        ("hair", "发型"),
        ("body_posture", "体态/身高感"),
        ("wardrobe_anchor", "服饰主锚点"),
        ("color_material", "服饰颜色/材质"),
        ("class_detail", "职业/阶层细节"),
        ("default_expression", "表情默认值"),
        ("contrast_with_others", "与其他角色的区别"),
        ("forbidden_drift", "禁止漂移"),
    ]
    return "\n".join(f"{label}：{profile.get(key, '').strip()}" for key, label in labels if profile.get(key, "").strip())


def build_character_info_payload(setting: str, character: Character) -> dict[str, Any]:
    appearance_profile = build_character_appearance_profile(character)
    return {
        "character_id": character.character_id,
        "lock_profile_id": character.lock_profile_id,
        "name": character.name,
        "age": infer_character_age(character),
        "gender": infer_character_gender(character),
        "location": infer_character_location(setting, character),
        "tagline": character.visual_anchor,
        "profile": build_character_profile_text(character),
        "persona_anchor": "、".join(character.persona_anchor),
        "speech_style_anchor": "、".join(character.speech_style_anchor),
        "appearance_profile": appearance_profile,
    }


def build_character_profile_md(setting: str, character: Character) -> str:
    payload = build_character_info_payload(setting, character)
    return f"""# {character.name} 角色档案

【基本身份背景】
角色叫{payload['name']}，{payload['age']}，主要活动在{payload['location']}，{payload['tagline']}。
{payload['profile']}

【容貌】
形象定位标签：{payload['tagline']}。
{render_appearance_profile(payload['appearance_profile'])}

【镜头功能】
人格锚点：{payload['persona_anchor']}。
对白气质：{payload['speech_style_anchor']}。
"""


def build_character_reference_prompt(setting: str, character: Character, image_ext: str, profile_md: str) -> str:
    profile_for_prompt = "\n".join(line for line in profile_md.splitlines() if not line.startswith("# ")).strip()
    return f"""# {character.name} 角色参考图提示词

## 目标文件
`{character_image_filename(character, image_ext)}`

## 角色结构信息
{profile_for_prompt}

## 正向提示词
{setting}，单人角色参考图，严格遵守上方【基本身份背景】和【容貌】，尤其锁定脸型骨相、五官特征、发型、体态、服饰颜色材质和“与其他角色的区别”，半身到膝上构图，三分之二正面，真实人像摄影质感，低饱和写实电影感，自然皮肤纹理，清晰面部特征，服装符合角色身份和故事环境，背景简洁不抢主体。同项目角色不得复用相同脸型、发型、体态或服装模板。

## 负向提示词
cartoon, anime, game-like rendering, plastic skin, over-beautification, over-saturation, deformed hands, deformed face, extra limbs, watermark, logo, inconsistent age, inconsistent costume, eroticized pose

## 出图要求
- 只生成一个角色，不要多人同框。
- 角色年龄、脸型、发型、体态、气质、服装必须贴合【容貌】逐项锚点。
- 必须让该角色和同项目同性别角色在轮廓、发型、服饰和姿态上可一眼区分。
- 用作 I2V 参考图，脸部和服装要清晰稳定。
- 不要添加文字、logo、水印或海报标题。
"""


def build_character_image_map(
    characters: list[Character],
    character_assets_dir: Path,
    image_ext: str,
    include_aliases: bool,
) -> dict[str, str]:
    image_map: dict[str, str] = {}
    for character in characters:
        image_ref = str(character_assets_dir / character_image_filename(character, image_ext))
        keys = [character.character_id]
        if include_aliases:
            keys.extend([character.name, character.lock_profile_id, *character_aliases(character)])
        for key in keys:
            if key.strip():
                image_map[key] = image_ref
    return image_map


def build_character_reference_readme(
    project_name: str,
    characters: list[Character],
    character_assets_dir: Path,
    map_path: Path,
    image_ext: str,
) -> str:
    rows = "\n".join(
        f"| {c.character_id} | {c.name} | `{character_assets_dir / character_image_filename(c, image_ext)}` | `{c.character_id}.info.json` | `{c.character_id}.profile.md` | `{c.character_id}.prompt.md` |"
        for c in characters
    )
    return f"""# {project_name} 角色参考图准备清单

这些文件用于 I2V 关键帧流程。`character_image_map.json` 已经指向固定图片路径，但实际图片需要先生成并放到对应位置。

| character_id | 角色 | 目标图片 | 结构数据 | 角色档案 | 出图提示词 |
| --- | --- | --- | --- | --- | --- |
{rows}

## character_image_map
`{map_path}`
"""


def build_prompt_schema(project_name: str, episode_id: str) -> dict[str, Any]:
    project_slug = project_name.lower()
    return {
        "schema_id": f"{project_slug}_prompt_schema_v1",
        "version": "1.0.0-draft",
        "status": "draft_spec_only",
        "scope": f"{episode_id}, generated by novel2video_plan.py",
        "global_constraints": {
            "video_ratio": "9:16",
            "video_resolution": "480p",
            "duration_range_seconds": [4, 5],
            "negative_prompt_baseline": DEFAULT_NEGATIVE_PROMPT,
        },
        "field_groups": {
            "project_meta": {"required": ["project_id", "episode_id", "platform_target", "core_selling_points"]},
            "language_policy": {"required": ["spoken_language", "subtitle_language", "voice_language_lock", "screen_text_language_lock"]},
            "emotion_arc": {"required": ["primary_emotions", "secondary_emotions", "hook_targets"]},
            "character_anchor": {"required": ["character_id", "name", "visual_anchor", "persona_anchor"]},
            "scene_anchor": {"required": ["scene_id", "scene_name", "scene_detail_ref", "scene_detail_key", "scene_detail", "must_have_elements", "lighting_anchor"]},
            "shot_execution": {"required": ["camera_plan", "action_intent", "emotion_intent"]},
            "scene_motion_contract": {"required": ["scene_mode", "description_policy", "camera_motion_allowed", "active_subjects", "static_props", "manipulated_props", "forbidden_scene_motion"]},
            "dialogue_language": {"required": ["dialogue_lines", "narration_lines", "subtitle_compact_lines"]},
            "prompt_render": {"required": ["positive_prefix", "shot_positive_core", "negative_prompt"]},
        },
    }


def build_record_template(project_name: str, episode_id: str, platform: str) -> dict[str, Any]:
    return {
        "template_id": f"{project_name.lower()}_prompt_record_template_v1",
        "template_version": "1.0.0-draft",
        "usage": {"purpose": "Per-shot prompt record template generated by novel2video_plan.py.", "mode": "draft"},
        "record_header": {
            "project_id": f"{project_name}_{episode_id}",
            "episode_id": episode_id,
            "experiment_id": "exp_YYYYMMDD_HHMMSS",
            "shot_id": "SH01",
            "author": "",
            "created_at": "",
            "updated_at": "",
            "status": "draft",
        },
        "global_settings": {
            "model": DEFAULT_MODEL,
            "ratio": "9:16",
            "resolution": "480p",
            "duration_sec": 4,
            "duration_policy": "estimated_from_prompt_but_not_more_than_5_seconds",
            "generate_audio": True,
        },
        "project_meta": {"platform_target": platform, "core_selling_points": []},
        "language_policy": dict(DEFAULT_LANGUAGE_POLICY),
        "emotion_arc": {"primary_emotions": [], "secondary_emotions": [], "hook_targets": {}},
        "character_anchor": {"primary": {}, "secondary": []},
        "scene_anchor": {
            "scene_id": "",
            "scene_name": "",
            "scene_detail_ref": "scene_detail.txt",
            "scene_detail_key": "",
            "scene_detail": "",
            "must_have_elements": [],
            "prop_must_visible": [],
            "lighting_anchor": "",
        },
        "shot_execution": {"camera_plan": {}, "action_intent": "", "emotion_intent": ""},
        "scene_motion_contract": {
            "scene_mode": "static_establishing",
            "description_policy": "场景只写静态状态；能动的只允许人物和人物直接操纵的物体",
            "camera_motion_allowed": "固定机位或极轻微稳定推镜，不改变道具相对位置",
            "active_subjects": [],
            "static_props": [],
            "manipulated_props": [],
            "allowed_motion": [],
            "forbidden_scene_motion": SCENE_MOTION_FORBIDDEN,
        },
        "dialogue_language": {
            "spoken_language": DEFAULT_LANGUAGE_POLICY["spoken_language"],
            "subtitle_language": DEFAULT_LANGUAGE_POLICY["subtitle_language"],
            "model_audio_language": DEFAULT_LANGUAGE_POLICY["model_audio_language"],
            "voice_language_lock": DEFAULT_LANGUAGE_POLICY["voice_language_lock"],
            "screen_text_language_lock": DEFAULT_LANGUAGE_POLICY["screen_text_language_lock"],
            "dialogue_lines": [],
            "narration_lines": [],
            "subtitle_compact_lines": [],
            "dialogue_style_rules": [],
        },
        "prompt_render": {"positive_prefix": "", "shot_positive_core": "", "dialogue_overlay_hint": "", "subtitle_overlay_hint": "", "negative_prompt": DEFAULT_NEGATIVE_PROMPT},
    }


def build_manifest(project_name: str, title: str, episode_plan: EpisodePlan, shots: list[ShotPlan], platform: str, core_selling_points: list[str]) -> dict[str, Any]:
    episode_id = episode_plan.episode_id
    project_id = f"{project_name}_{episode_id}"
    episode_label = episode_plan.episode_label
    return {
        "manifest_id": f"{project_name.lower()}_{episode_id.lower()}_prompt_episode_manifest_v1",
        "manifest_version": "1.0.0-draft",
        "status": "draft_plan",
        "linked_specs": {
            "prompt_schema": {"file": "27_prompt_schema_v1.json", "schema_id": f"{project_name.lower()}_prompt_schema_v1"},
            "shot_record_template": {"file": "28_prompt_record_template_v1.json", "template_id": f"{project_name.lower()}_prompt_record_template_v1"},
        },
        "project": {
            "project_id": project_id,
            "episode_id": episode_id,
            "title": title,
            "episode_title": episode_plan.title,
            "platform_target": platform,
            "core_selling_points": core_selling_points,
        },
        "global_settings": {
            "model": DEFAULT_MODEL,
            "ratio": "9:16",
            "resolution": "480p",
            "duration_range_seconds": [4, 5],
            "generate_audio": True,
            "style_baseline": "realistic cinematic, low saturation, grounded lighting",
            "language_policy": dict(DEFAULT_LANGUAGE_POLICY),
        },
        "shot_registry": {
            "total_shots": len(shots),
            "shots": [
                {
                    "shot_id": s.shot_id,
                    "enabled": True,
                    "priority": s.priority,
                    "intent": s.intent,
                    "record_ref": f"records/{episode_id}_{s.shot_id}_record.json",
                    "duration_target_sec": s.duration_sec,
                    "qa_gate": "pending",
                }
                for s in shots
            ],
        },
        "language_binding_plan": {
            "dialogue_source": f"15_{project_name}{episode_label}镜头脚本.md",
            "narration_source": f"16_{project_name}{episode_label}旁白字幕稿.md",
            "subtitle_source": f"16_{project_name}{episode_label}旁白字幕稿.md",
            "spoken_language": DEFAULT_LANGUAGE_POLICY["spoken_language"],
            "subtitle_language": DEFAULT_LANGUAGE_POLICY["subtitle_language"],
            "model_audio_language": DEFAULT_LANGUAGE_POLICY["model_audio_language"],
        },
    }


def build_character_lock_profiles(project_name: str, characters: list[Character]) -> dict[str, Any]:
    return {
        "profiles_id": f"{project_name.lower()}_character_lock_profiles_v1",
        "version": "1.0.0-draft",
        "status": "draft",
        "profiles": [
            {
                "lock_profile_id": c.lock_profile_id,
                "character_id": c.character_id,
                "name": c.name,
                "visual_anchor": c.visual_anchor,
                "forbidden_drift": ["年龄漂移", "脸型漂移", "服装时代错误", "时代/地域感错误", "过度美颜"],
                "appearance_anchor_tokens": [c.name, c.visual_anchor],
            }
            for c in characters
        ],
    }


def build_model_profiles(project_name: str) -> dict[str, Any]:
    return {
        "profiles_id": f"{project_name.lower()}_model_capability_profiles_v1",
        "version": "1.0.0-draft",
        "status": "spec_only",
        "profiles": [
            {
                "profile_id": "seedance15_i2v_atlas",
                "provider": "atlascloud",
                "model": "bytedance/seedance-v1.5-pro/image-to-video",
                "supports_negative_prompt": False,
                "supports_audio_generation": True,
                "duration_min_sec": 4,
                "duration_max_sec": 12,
                "supported_resolutions": ["480p", "720p", "1080p"],
                "supported_ratios": ["9:16"],
                "language_policy": dict(DEFAULT_LANGUAGE_POLICY),
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
            },
            {
                "profile_id": "seedance2_text2video_atlas",
                "provider": "atlascloud",
                "model": DEFAULT_MODEL,
                "supports_negative_prompt": False,
                "supports_audio_generation": True,
                "duration_min_sec": 4,
                "duration_max_sec": 15,
                "supported_resolutions": ["480p", "720p", "1080p"],
                "supported_ratios": ["adaptive", "9:16"],
                "language_policy": dict(DEFAULT_LANGUAGE_POLICY),
                "payload_fields": {
                    "positive_prompt_field": "prompt",
                    "negative_prompt_field": None,
                    "duration_field": "duration",
                    "resolution_field": "resolution",
                    "ratio_field": "aspect_ratio",
                    "audio_field": "generate_audio",
                },
            }
        ],
    }


def sample_chapter_shot_truth(shot: ShotPlan) -> dict[str, Any]:
    per_shot: dict[str, dict[str, list[str] | str]] = {
        "SH01": {
            "must_show": ["荒废破庙", "潮湿泥地", "残破土墙", "枯草碎瓦"],
            "must_convey": "林辰醒来前的生存环境极惨，穷冷破败。",
            "props": ["破庙", "泥地", "枯草碎瓦"],
        },
        "SH02": {
            "must_show": ["林辰猛然睁眼", "冷汗", "大口喘气", "破庙冷光"],
            "must_convey": "现代社畜林辰在陌生古代破庙中濒死惊醒。",
            "props": ["破庙泥地"],
        },
        "SH03": {
            "must_show": ["瘦骨手臂", "破麻布衣", "脏污皮肤", "虚弱发抖"],
            "must_convey": "林辰穿成快饿死的乞丐少年，不是侠客伤者。",
            "props": ["破麻布衣"],
        },
        "SH04": {
            "must_show": ["扶墙起身", "胃痛虚弱", "差点摔倒", "缺口陶罐"],
            "must_convey": "生存危机来自饥饿，林辰硬撑着找活路。",
            "props": ["缺口陶罐", "残破土墙"],
        },
        "SH05": {
            "must_show": ["阿翠", "布衣", "稀粥", "粥蒸汽", "破庙木门"],
            "must_convey": "阿翠端来的是救命稀粥，她是唯一善意，不是医女。",
            "props": ["稀粥", "碗", "粥蒸汽"],
        },
        "SH06": {
            "must_show": ["阿翠递稀粥", "林辰接碗", "指尖轻触", "双人近景"],
            "must_convey": "阿翠守了两天，林辰从防备转向信任。",
            "props": ["稀粥", "碗"],
        },
        "SH07": {
            "must_show": ["热粥蒸汽", "林辰喝粥", "吞咽", "火边微暖光"],
            "must_convey": "第一口稀粥把林辰从快饿死的边缘拉回来。",
            "props": ["稀粥", "碗", "粥蒸汽"],
        },
        "SH08": {
            "must_show": ["阿翠掖破布", "林辰看阿翠", "破布", "火边低光"],
            "must_convey": "林辰的护短承诺第一次成立。",
            "props": ["破布"],
        },
        "SH09": {
            "must_show": ["溪边夜色", "林辰虚弱前行", "湿泥碎石", "溪水反光"],
            "must_convey": "林辰意识到只靠粥活不过明天，开始主动寻找活路。",
            "props": ["溪水", "湿泥"],
        },
        "SH10": {
            "must_show": ["溪边白色盐渍", "手指触碰盐渍", "石面湿泥", "缺口陶罐"],
            "must_convey": "白色物质必须被理解为盐渍，是现代知识赚钱机会。",
            "props": ["溪边盐渍", "缺口陶罐"],
        },
        "SH11": {
            "must_show": ["林辰面部近景", "眼神由弱转锐利", "溪边夜色", "盐渍方向"],
            "must_convey": "林辰认出盐渍，脑子开始高速运转。",
            "props": ["溪边盐渍"],
        },
        "SH12": {
            "must_show": ["林辰握缺口陶罐", "看向长安方向", "溪边盐渍", "阿翠在旁"],
            "must_convey": "林辰决定明天不讨饭，靠提盐做买卖。",
            "props": ["缺口陶罐", "溪边盐渍"],
        },
        "SH13": {
            "must_show": ["阿翠追问", "林辰握缺口陶罐", "溪边盐渍", "林辰说买这把盐"],
            "must_convey": "集尾钩子必须由阿翠和林辰的对话完成：明天不讨饭，进城让人花钱买盐。",
            "props": ["缺口陶罐", "溪边盐渍"],
        },
    }
    fallback = {"must_show": [], "must_convey": shot.intent, "props": []}
    return per_shot.get(shot.shot_id, fallback)


def build_story_truth_contract(source_text: str, episode_plan: EpisodePlan, shot: ShotPlan) -> dict[str, Any]:
    if episode_plan.episode_number == 1 and is_sample_chapter_source(source_text):
        shot_truth = sample_chapter_shot_truth(shot)
        return {
            "contract_id": "sample_chapter_ep01_truth_v1",
            "premise": "现代社畜林辰穿越成西汉长安城外快饿死的乞丐少年。",
            "episode_truth": SAMPLE_CHAPTER_EP01_TRUTH,
            "shot_truth": shot_truth,
            "must_not_drift": SAMPLE_CHAPTER_FORBIDDEN_DRIFT,
            "truth_check": str(shot_truth.get("must_convey") or shot.intent),
        }
    return {}


def is_episode_ending_hook_shot(shot: ShotPlan) -> bool:
    text = " ".join([shot.shot_id, shot.intent, shot.action_intent, shot.positive_core, " ".join(shot.subtitle)])
    return any(term in text for term in ("集尾", "追更", "钩子", "下一集"))


def estimate_dialogue_duration_sec(dialogue_lines: list[dict[str, Any]]) -> int:
    total_chars = sum(len(str(line.get("text", "")).strip()) for line in dialogue_lines)
    line_pause = max(0, len(dialogue_lines) - 1) * 0.35
    return max(4, int(round(total_chars / 6.0 + line_pause + 0.8)))


def validate_episode_ending_hook_record(data: dict[str, Any], path: str, findings: list[dict[str, Any]]) -> None:
    global_settings = data.get("global_settings", {}) if isinstance(data, dict) else {}
    dialogue_language = data.get("dialogue_language", {}) if isinstance(data, dict) else {}
    shot_execution = data.get("shot_execution", {}) if isinstance(data, dict) else {}
    prompt_render = data.get("prompt_render", {}) if isinstance(data, dict) else {}
    dialogue_lines = dialogue_language.get("dialogue_lines", []) if isinstance(dialogue_language, dict) else []
    narration_lines = dialogue_language.get("narration_lines", []) if isinstance(dialogue_language, dict) else []
    subtitle_lines = dialogue_language.get("subtitle_compact_lines", []) if isinstance(dialogue_language, dict) else []
    if not isinstance(dialogue_lines, list):
        dialogue_lines = []
    if not isinstance(narration_lines, list):
        narration_lines = []
    if not isinstance(subtitle_lines, list):
        subtitle_lines = []
    dialogue_text = " ".join(str(line.get("text", "")) for line in dialogue_lines if isinstance(line, dict))
    subtitle_text = " ".join(str(item) for item in subtitle_lines)
    prompt_text = str(prompt_render.get("shot_positive_core", "")) if isinstance(prompt_render, dict) else ""
    action_text = str(shot_execution.get("action_intent", "")) if isinstance(shot_execution, dict) else ""

    if not dialogue_lines:
        findings.append({"severity": "high", "issue": "ending_hook_missing_dialogue", "path": path})
    if narration_lines and not dialogue_lines:
        findings.append({"severity": "high", "issue": "ending_hook_narration_only", "path": path})
    if "下一集" in subtitle_text and not dialogue_lines:
        findings.append({"severity": "high", "issue": "ending_hook_subtitle_only", "path": path})
    if dialogue_lines and not any(keyword in dialogue_text for keyword in ENDING_HOOK_KEYWORDS):
        findings.append({"severity": "medium", "issue": "ending_dialogue_lacks_action_or_mystery_hook", "path": path})
    if dialogue_lines and "旁白" not in prompt_text and "角色" not in prompt_text and "台词" not in prompt_text and "对白" not in prompt_text:
        findings.append({"severity": "medium", "issue": "ending_prompt_lacks_dialogue_hook_instruction", "path": path})
    if dialogue_lines:
        duration = int(global_settings.get("duration_sec", 0) or 0) if isinstance(global_settings, dict) else 0
        required = estimate_dialogue_duration_sec(dialogue_lines)
        if duration < required:
            findings.append({"severity": "high", "issue": "ending_dialogue_duration_too_short", "path": path, "duration": duration, "required_min": required})
    if not any(term in action_text + prompt_text + subtitle_text for term in ("集尾", "追更", "钩子", "下一集")):
        findings.append({"severity": "medium", "issue": "ending_hook_not_marked_as_episode_hook", "path": path})


def record_character_anchor_names(data: dict[str, Any]) -> list[str]:
    anchor = data.get("character_anchor", {}) if isinstance(data, dict) else {}
    if not isinstance(anchor, dict):
        return []
    nodes: list[dict[str, Any]] = []
    primary = anchor.get("primary")
    if isinstance(primary, dict):
        nodes.append(primary)
    secondary = anchor.get("secondary")
    if isinstance(secondary, list):
        nodes.extend(item for item in secondary if isinstance(item, dict))
    names: list[str] = []
    for node in nodes:
        for key in ("name", "character_id"):
            value = str(node.get(key) or "").strip()
            if value:
                names.append(value)
                if len(value) >= 3:
                    names.append(value[-2:])
        aliases = node.get("aliases")
        if isinstance(aliases, list):
            names.extend(str(alias).strip() for alias in aliases if str(alias).strip())
        visual_anchor = str(node.get("visual_anchor") or "")
        match = re.search(r"别名[:：]\s*([^。；;\n]+)", visual_anchor)
        if match:
            names.extend(item.strip() for item in re.split(r"[、,，/／\s]+", match.group(1)) if item.strip())
    return unique_names(names)


def record_name_in_anchor(name: str, anchor_names: list[str]) -> bool:
    normalized = str(name or "").strip()
    return any(alias and (alias == normalized or alias in normalized or normalized in alias) for alias in anchor_names)


def record_keyframe_text(data: dict[str, Any]) -> str:
    keyframe = data.get("keyframe_static_anchor", {}) if isinstance(data, dict) else {}
    if not isinstance(keyframe, dict):
        return ""
    return " ".join(
        str(keyframe.get(key) or "")
        for key in ("framing_focus", "action_intent", "positive_core")
    )


def record_visual_prompt_text(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    prompt_render = data.get("prompt_render", {})
    shot_execution = data.get("shot_execution", {})
    camera_plan = shot_execution.get("camera_plan", {}) if isinstance(shot_execution, dict) else {}
    scene_anchor = data.get("scene_anchor", {})
    continuity_rules = data.get("continuity_rules", {})
    keyframe = data.get("keyframe_static_anchor", {})
    parts: list[str] = []
    if isinstance(prompt_render, dict):
        parts.extend(
            [
                str(prompt_render.get("positive_prefix") or ""),
                str(prompt_render.get("shot_positive_core") or ""),
            ]
        )
    if isinstance(camera_plan, dict):
        parts.extend(
            [
                str(camera_plan.get("shot_type") or ""),
                str(camera_plan.get("movement") or ""),
                str(camera_plan.get("framing_focus") or ""),
            ]
        )
    if isinstance(shot_execution, dict):
        parts.extend(
            [
                str(shot_execution.get("action_intent") or ""),
                str(shot_execution.get("emotion_intent") or ""),
            ]
        )
    if isinstance(scene_anchor, dict):
        parts.extend(str(item) for item in scene_anchor.get("must_have_elements", []) if str(item).strip())
        parts.extend(str(item) for item in scene_anchor.get("prop_must_visible", []) if str(item).strip())
    if isinstance(continuity_rules, dict):
        for key in ("character_state_transition", "scene_transition", "prop_continuity"):
            parts.extend(str(item) for item in continuity_rules.get(key, []) if str(item).strip())
    if isinstance(keyframe, dict):
        parts.extend(
            [
                str(keyframe.get("framing_focus") or ""),
                str(keyframe.get("action_intent") or ""),
                str(keyframe.get("positive_core") or ""),
            ]
        )
    return " ".join(part for part in parts if part).strip()


def record_primary_visual_text(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    prompt_render = data.get("prompt_render", {})
    shot_execution = data.get("shot_execution", {})
    camera_plan = shot_execution.get("camera_plan", {}) if isinstance(shot_execution, dict) else {}
    scene_anchor = data.get("scene_anchor", {})
    parts: list[str] = []
    if isinstance(prompt_render, dict):
        parts.extend(
            [
                str(prompt_render.get("positive_prefix") or ""),
                str(prompt_render.get("shot_positive_core") or ""),
            ]
        )
    if isinstance(camera_plan, dict):
        parts.extend(str(camera_plan.get(key) or "") for key in ("shot_type", "movement", "framing_focus"))
    if isinstance(shot_execution, dict):
        parts.extend(str(shot_execution.get(key) or "") for key in ("action_intent", "emotion_intent"))
    if isinstance(scene_anchor, dict):
        parts.extend(str(item) for item in scene_anchor.get("prop_must_visible", []) if str(item).strip())
    return " ".join(part for part in parts if part).strip()


def record_scene_prop_text(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    scene_anchor = data.get("scene_anchor", {})
    scene_motion_contract = data.get("scene_motion_contract", {})
    i2v_contract = data.get("i2v_contract", {})
    parts: list[str] = []
    if isinstance(scene_anchor, dict):
        parts.extend(str(item) for item in scene_anchor.get("prop_must_visible", []) if str(item).strip())
    if isinstance(scene_motion_contract, dict):
        parts.extend(str(item) for item in scene_motion_contract.get("static_props", []) if str(item).strip())
        parts.extend(str(item) for item in scene_motion_contract.get("manipulated_props", []) if str(item).strip())
    if isinstance(i2v_contract, dict):
        prop_contract = i2v_contract.get("prop_contract") or data.get("prop_contract")
        if isinstance(prop_contract, list):
            for item in prop_contract:
                if isinstance(item, dict):
                    parts.extend(str(item.get(key) or "") for key in ("prop_id", "name", "size", "color", "material", "structure", "position", "motion_policy"))
                else:
                    parts.append(str(item))
    return " ".join(part for part in parts if part).strip()


def record_has_prop_library_or_contract(data: dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    if isinstance(data.get("prop_library"), dict) and data.get("prop_library"):
        return True
    if isinstance(data.get("prop_contract"), list) and data.get("prop_contract"):
        return True
    i2v_contract = data.get("i2v_contract", {})
    if isinstance(i2v_contract, dict):
        return bool(i2v_contract.get("prop_library") or i2v_contract.get("prop_contract"))
    return False


def record_mentions_phone(text: str, dialogue_lines: list[dict[str, Any]]) -> bool:
    if any(source == "phone" for source in [normalize_dialogue_source(line.get("source"), line.get("text", ""), line.get("purpose", "")) for line in dialogue_lines if isinstance(line, dict)]):
        return True
    return any(token in text for token in ("手机", "智能手机", "听筒", "来电", "接起电话", "正在通话", "电话里", "电话中", "电话通话", "smartphone", "phone call"))


def validate_i2v_prompt_design_record(data: dict[str, Any], path: str, findings: list[dict[str, Any]]) -> None:
    if not isinstance(data, dict):
        return
    visual_text = record_visual_prompt_text(data)
    primary_visual_text = record_primary_visual_text(data)
    prop_text = record_scene_prop_text(data)
    dialogue_language = data.get("dialogue_language", {})
    dialogue_lines = dialogue_language.get("dialogue_lines", []) if isinstance(dialogue_language, dict) else []
    if not isinstance(dialogue_lines, list):
        dialogue_lines = []
    dialogue_lines = [line for line in dialogue_lines if isinstance(line, dict)]

    onscreen_speakers = unique_names(
        [
            str(line.get("speaker") or "")
            for line in dialogue_lines
            if normalize_dialogue_source(line.get("source"), line.get("text", ""), line.get("purpose", "")) == "onscreen"
        ]
    )
    phone_lines = [
        line
        for line in dialogue_lines
        if normalize_dialogue_source(line.get("source"), line.get("text", ""), line.get("purpose", "")) == "phone"
    ]

    if len(onscreen_speakers) >= 2:
        findings.append(
            {
                "severity": "high",
                "issue": "i2v_multiple_active_onscreen_speakers",
                "path": path,
                "speakers": onscreen_speakers,
                "rule_ref": "docs/I2V_prompt_design_rules.md#dialogue-policy",
            }
        )

    if dialogue_lines and any(term in visual_text for term in I2V_COMPLEX_ACTION_TERMS) and prop_text:
        findings.append(
            {
                "severity": "medium",
                "issue": "i2v_dialogue_action_prop_overload",
                "path": path,
                "rule_ref": "docs/I2V_prompt_design_rules.md#one-shot-one-task",
            }
        )

    vague_terms = [term for term in I2V_VAGUE_PROP_TERMS if term in f"{primary_visual_text} {prop_text}"]
    if vague_terms:
        findings.append(
            {
                "severity": "high",
                "issue": "i2v_vague_static_prop_description",
                "path": path,
                "terms": vague_terms,
                "rule_ref": "docs/I2V_prompt_design_rules.md#prop-policy",
            }
        )

    if prop_text and not record_has_prop_library_or_contract(data):
        has_dimension = any(term in prop_text for term in I2V_PROP_DIMENSION_TERMS)
        has_appearance = any(term in prop_text for term in I2V_PROP_APPEARANCE_TERMS)
        if not (has_dimension and has_appearance):
            findings.append(
                {
                    "severity": "medium",
                    "issue": "i2v_prop_canonical_profile_missing",
                    "path": path,
                    "detail": "important props should define/reuse size, color, material, and structure",
                    "rule_ref": "docs/I2V_prompt_design_rules.md#prop-library-rule",
                }
            )

    safety_terms = [term for term in I2V_NEGATIVE_SAFETY_TERMS if term in visual_text]
    if safety_terms:
        findings.append(
            {
                "severity": "high",
                "issue": "i2v_negative_safety_terms_in_visual_prompt",
                "path": path,
                "terms": safety_terms,
                "rule_ref": "docs/I2V_prompt_design_rules.md#safety-wording",
            }
        )

    if phone_lines and onscreen_speakers:
        findings.append(
            {
                "severity": "high",
                "issue": "i2v_phone_remote_and_onscreen_reply_in_same_shot",
                "path": path,
                "phone_speakers": unique_names([str(line.get("speaker") or "") for line in phone_lines]),
                "onscreen_speakers": onscreen_speakers,
                "rule_ref": "docs/I2V_prompt_design_rules.md#phone-dialogue",
            }
        )

    if phone_lines:
        listener_names = unique_names([dialogue_listener_name(line) for line in phone_lines])
        listener_text = " ".join(listener_names)
        silent_contract_terms = ("无口型", "不做口型", "不替", "闭嘴", "保持沉默", "只做倾听", "listening silently", "no lip movement")
        if not any(term in visual_text for term in silent_contract_terms):
            findings.append(
                {
                    "severity": "medium",
                    "issue": "i2v_phone_listener_silence_contract_missing",
                    "path": path,
                    "listeners": listener_names,
                    "rule_ref": "docs/I2V_prompt_design_rules.md#phone-dialogue",
                }
            )
        if listener_text and not any(listener in visual_text for listener in listener_names):
            findings.append(
                {
                    "severity": "high",
                    "issue": "i2v_phone_listener_not_in_visual_contract",
                    "path": path,
                    "listeners": listener_names,
                    "rule_ref": "docs/I2V_prompt_design_rules.md#phone-dialogue",
                }
            )

    if record_mentions_phone(primary_visual_text, dialogue_lines) and not any(term in visual_text for term in I2V_PHONE_INWARD_TERMS):
        findings.append(
            {
                "severity": "medium",
                "issue": "i2v_phone_screen_orientation_missing",
                "path": path,
                "detail": "phone-call shots should normally specify screen facing inward and screen content not visible",
                "rule_ref": "docs/I2V_prompt_design_rules.md#phone-prop-orientation",
            }
        )


def validate_dialogue_visibility_record(data: dict[str, Any], path: str, findings: list[dict[str, Any]]) -> None:
    dialogue_language = data.get("dialogue_language", {}) if isinstance(data, dict) else {}
    if not isinstance(dialogue_language, dict):
        findings.append({"severity": "high", "issue": "dialogue_language_missing", "path": path})
        return
    dialogue_lines = dialogue_language.get("dialogue_lines", [])
    narration_lines = dialogue_language.get("narration_lines", [])
    if not isinstance(dialogue_lines, list):
        dialogue_lines = []
    if not isinstance(narration_lines, list):
        narration_lines = []
    dialogue_blocking = data.get("dialogue_blocking", {}) if isinstance(data, dict) else {}
    i2v_contract = data.get("i2v_contract", {}) if isinstance(data, dict) else {}
    shot_task = str(i2v_contract.get("shot_task") or "").strip() if isinstance(i2v_contract, dict) else ""
    lip_sync_policy = str(dialogue_blocking.get("lip_sync_policy") or "").strip() if isinstance(dialogue_blocking, dict) else ""
    no_dialogue_i2v_task = shot_task in {"prop_display", "establishing", "reaction", "action", "transition"} and lip_sync_policy == "no_dialogue"

    if not dialogue_lines and not no_dialogue_i2v_task:
        findings.append({"severity": "high", "issue": "shot_missing_dialogue", "path": path})
    if narration_lines and not dialogue_lines and not no_dialogue_i2v_task:
        findings.append({"severity": "high", "issue": "narration_only_shot", "path": path})

    anchor_names = record_character_anchor_names(data)
    keyframe_text = record_keyframe_text(data)
    onscreen_speakers: list[str] = []
    phone_missing_listener: list[str] = []
    phone_listeners: list[str] = []
    for line in dialogue_lines:
        if not isinstance(line, dict):
            continue
        speaker = str(line.get("speaker") or "").strip()
        source = normalize_dialogue_source(line.get("source"), line.get("text", ""), line.get("purpose", ""))
        listener = dialogue_listener_name(line)
        if source == "phone":
            if not listener:
                phone_missing_listener.append(speaker or "unknown")
            else:
                phone_listeners.append(listener)
        elif source == "onscreen" and speaker:
            onscreen_speakers.append(speaker)

    for speaker in unique_names(onscreen_speakers):
        if not record_name_in_anchor(speaker, anchor_names):
            findings.append({"severity": "high", "issue": "onscreen_dialogue_speaker_not_in_character_anchor", "path": path, "speaker": speaker})
        if keyframe_text and speaker not in keyframe_text:
            findings.append({"severity": "high", "issue": "onscreen_dialogue_speaker_not_in_keyframe_anchor", "path": path, "speaker": speaker})
    if len(unique_names(onscreen_speakers)) >= 2:
        missing = [speaker for speaker in unique_names(onscreen_speakers) if speaker not in keyframe_text]
        if missing:
            findings.append({"severity": "high", "issue": "two_speaker_dialogue_missing_visible_character", "path": path, "missing": missing})
    for speaker in phone_missing_listener:
        findings.append({"severity": "high", "issue": "phone_dialogue_missing_listener", "path": path, "speaker": speaker})
    for listener in unique_names(phone_listeners):
        if not record_name_in_anchor(listener, anchor_names):
            findings.append({"severity": "high", "issue": "phone_listener_not_in_character_anchor", "path": path, "listener": listener})
        if keyframe_text and listener not in keyframe_text:
            findings.append({"severity": "high", "issue": "phone_listener_not_in_keyframe_anchor", "path": path, "listener": listener})


def shot_character_text(shot: ShotPlan) -> str:
    dialogue_speakers = " ".join(str(line.get("speaker", "")) for line in shot.dialogue)
    dialogue_text = " ".join(str(line.get("text", "")) for line in shot.dialogue)
    return " ".join(
        [
            shot.intent,
            shot.framing_focus,
            shot.action_intent,
            shot.positive_core,
            shot.scene_name,
            dialogue_speakers,
            dialogue_text,
        ]
    )


def strip_nonvisual_character_mentions(text: str) -> str:
    stripped = text
    stripped = re.sub(r"[^，。；;,.]*?(?:电话声|电话|声音|传出|提到|说|回答|问|对白|台词)[^，。；;,.]*", "", stripped)
    stripped = re.sub(r"[^，。；;,.]*?(?:笔录|记录|名字|照片|合影|屏幕文字|表格)[^，。；;,.]*", "", stripped)
    return stripped


def shot_visual_character_text(shot: ShotPlan) -> str:
    primary_visual = strip_nonvisual_character_mentions(
        " ".join([shot.framing_focus, shot.scene_name])
    )
    if primary_visual.strip():
        return primary_visual
    return strip_nonvisual_character_mentions(
        " ".join([shot.positive_core, shot.action_intent, shot.intent])
    )


def character_aliases(character: Character) -> list[str]:
    aliases = [character.name, character.character_id]
    if len(character.name) >= 3:
        short = character.name[-2:]
        if short not in {"先生", "女士", "小姐", "警员", "人群"}:
            aliases.append(short)
    match = re.search(r"别名[:：]\s*([^。；;\n]+)", character.visual_anchor)
    if match:
        aliases.extend(item.strip() for item in re.split(r"[、,，/／\s]+", match.group(1)) if item.strip())
    return [alias for alias in dict.fromkeys(aliases) if alias]


def character_is_named_in_shot(character: Character, shot_text: str, speaker_names: list[str]) -> bool:
    aliases = character_aliases(character)
    return any(alias and (alias in speaker_names or alias in shot_text) for alias in aliases)


def find_character_by_name(characters: list[Character], name: str) -> Character | None:
    normalized = str(name or "").strip()
    if not normalized:
        return None
    for character in characters:
        for alias in character_aliases(character):
            if alias and (alias == normalized or alias in normalized or normalized in alias):
                return character
    return None


def infer_ephemeral_character_by_name(name: str) -> Character | None:
    normalized = str(name or "").strip()
    if any(token in normalized for token in ("服务员", "侍者", "酒店员工")):
        return Character(
            "EXTRA_WAITER",
            "",
            "服务员",
            "银座高级酒店服务员，整洁制服，普通工作人员气质，反应真实不过度戏剧化",
            ["紧张", "职业化"],
            ["短促", "慌张"],
        )
    if any(token in normalized for token in ("警员", "警方", "刑警同事")):
        return Character(
            "EXTRA_POLICE",
            "",
            "警员",
            "日本都市刑侦现场警员，深色制服或便装外套，维持秩序",
            ["克制", "执行"],
            ["简短"],
        )
    if any(token in normalized for token in ("人群", "路人", "客人", "围观")):
        return Character(
            "EXTRA_CROWD",
            "",
            "背景人群",
            "银座酒店或街头背景人群，低调真实，只作为环境反应存在",
            ["压低声音", "克制"],
            ["背景反应"],
        )
    return None


def infer_ephemeral_character(shot: ShotPlan) -> Character | None:
    text = shot_character_text(shot)
    ephemeral_specs = [
        (
            ("服务员", "侍者", "酒店员工"),
            Character(
                "EXTRA_WAITER",
                "",
                "服务员",
                "银座高级酒店服务员，整洁制服，普通工作人员气质，反应真实不过度戏剧化",
                ["紧张", "职业化"],
                ["短促", "慌张"],
            ),
        ),
        (
            ("警员", "警方", "警车", "刑警同事"),
            Character(
                "EXTRA_POLICE",
                "",
                "警员",
                "日本都市刑侦现场警员，深色制服或便装外套，维持秩序",
                ["克制", "执行"],
                ["简短"],
            ),
        ),
        (
            ("人群", "路人", "客人", "围观"),
            Character(
                "EXTRA_CROWD",
                "",
                "背景人群",
                "银座酒店或街头背景人群，低调真实，只作为环境反应存在",
                ["压低声音", "克制"],
                ["背景反应"],
            ),
        ),
    ]
    for tokens, character in ephemeral_specs:
        if any(token in text for token in tokens):
            return character
    return None


def character_to_anchor_node(character: Character, *, lock_enabled: bool) -> dict[str, Any]:
    return {
        "character_id": character.character_id,
        "name": character.name,
        "lock_profile_id": character.lock_profile_id,
        "lock_prompt_enabled": lock_enabled and bool(character.lock_profile_id),
        "visual_anchor": character.visual_anchor,
        "persona_anchor": character.persona_anchor,
        "speech_style_anchor": character.speech_style_anchor,
    }


def resolve_shot_characters(characters: list[Character], shot: ShotPlan) -> tuple[Character | None, list[Character]]:
    visible_names = visible_dialogue_characters(shot)
    forced: list[Character] = []
    for name in visible_names:
        matched = find_character_by_name(characters, name) or infer_ephemeral_character_by_name(name)
        if matched is not None and matched.character_id not in {item.character_id for item in forced}:
            forced.append(matched)

    speaker_names = visible_names
    shot_text = shot_visual_character_text(shot)
    named = [
        character
        for character in characters
        if character_is_named_in_shot(character, shot_text, speaker_names)
    ]
    if forced:
        merged = list(forced)
        for character in named:
            if character.character_id not in {item.character_id for item in merged}:
                merged.append(character)
        return merged[0], merged[1:]

    if not named:
        shot_text = strip_nonvisual_character_mentions(
            " ".join([shot.positive_core, shot.scene_name])
        )
        named = [
            character
            for character in characters
            if character_is_named_in_shot(character, shot_text, speaker_names)
        ]
    if not named:
        shot_text = strip_nonvisual_character_mentions(
            " ".join([shot.action_intent, shot.intent, shot.scene_name])
        )
        named = [
            character
            for character in characters
            if character_is_named_in_shot(character, shot_text, speaker_names)
        ]
    if named:
        return named[0], named[1:]

    ephemeral = infer_ephemeral_character(shot)
    if ephemeral is not None:
        return ephemeral, []

    return None, []


def build_record(
    project_id: str,
    episode_plan: EpisodePlan,
    platform: str,
    setting: str,
    core_selling_points: list[str],
    language_policy: dict[str, Any],
    source_text: str,
    characters: list[Character],
    shot: ShotPlan,
    experiment_id: str,
    scene_detail_ref: str = "scene_detail.txt",
    scene_detail_text: str = "",
) -> dict[str, Any]:
    primary, secondary = resolve_shot_characters(characters, shot)
    primary_anchor = (
        character_to_anchor_node(primary, lock_enabled=primary in characters)
        if primary is not None
        else {
            "character_id": "SCENE_ONLY",
            "name": "场景主体",
            "lock_profile_id": "",
            "lock_prompt_enabled": False,
            "visual_anchor": "本镜头以空间、道具或群体反应为主体，不强制出现系列主角",
            "persona_anchor": ["环境叙事"],
            "speech_style_anchor": [],
        }
    )
    story_truth_contract = build_story_truth_contract(source_text, episode_plan, shot)
    shot_truth = story_truth_contract.get("shot_truth", {}) if story_truth_contract else {}
    truth_must_show = [str(item) for item in shot_truth.get("must_show", [])] if isinstance(shot_truth, dict) else []
    truth_props = [str(item) for item in shot_truth.get("props", [])] if isinstance(shot_truth, dict) else []
    truth_forbidden = [str(item) for item in story_truth_contract.get("must_not_drift", [])] if story_truth_contract else []
    truth_check = str(story_truth_contract.get("truth_check", "")).strip() if story_truth_contract else ""
    prop_stability = build_static_prop_stability_contract(shot)
    must_have_elements = list(
        dict.fromkeys(
            ["符合故事时代", "关键道具可见", "真实光影", "低饱和"]
            + truth_must_show
            + [str(item) for item in prop_stability.get("must_have_elements", [])]
        )
    )
    prop_must_visible = list(
        dict.fromkeys(
            truth_props
            + [str(item) for item in prop_stability.get("prop_must_visible", [])]
        )
    )
    active_characters = [c for c in [primary, *secondary] if c is not None]
    scene_motion_contract = build_scene_motion_contract(
        shot=shot,
        active_characters=active_characters,
        static_props=prop_must_visible,
    )
    i2v_contract = merge_i2v_contract(build_auto_i2v_contract(shot), shot.i2v_contract)
    dialogue_blocking = shot.dialogue_blocking if isinstance(shot.dialogue_blocking, dict) else build_auto_dialogue_blocking(shot)
    auto_first_frame = build_auto_first_frame_contract(
        shot,
        i2v_contract.get("prop_contract", []) if isinstance(i2v_contract.get("prop_contract"), list) else [],
    )
    first_frame_contract = shot.first_frame_contract if isinstance(shot.first_frame_contract, dict) else auto_first_frame
    negative_prompt = list(
        dict.fromkeys(
            DEFAULT_NEGATIVE_PROMPT
            + truth_forbidden
            + [str(item) for item in prop_stability.get("negative_prompt", [])]
        )
    )
    truth_prompt_lines: list[str] = []
    if story_truth_contract:
        truth_prompt_lines = [
            f"故事事实：{story_truth_contract['premise']}",
            f"本镜头必须表达：{truth_check}",
            "禁止误读：" + "、".join(truth_forbidden),
        ]
    positive_core = shot_positive_core_with_static_props(shot)
    shot_positive_core = "，".join([*truth_prompt_lines, positive_core]) if truth_prompt_lines else positive_core
    visibility_contract = dialogue_visibility_contract(shot)
    if visibility_contract and "对白可见人物契约" not in shot_positive_core and "电话/画外声音契约" not in shot_positive_core:
        shot_positive_core = f"{shot_positive_core} {visibility_contract}"
    duration_policy = "dialogue_complete_episode_hook" if is_episode_ending_hook_shot(shot) and shot.dialogue else "estimated_from_prompt_but_not_more_than_5_seconds"
    return {
        "record_header": {
            "project_id": project_id,
            "episode_id": episode_plan.episode_id,
            "episode_number": episode_plan.episode_number,
            "experiment_id": experiment_id,
            "shot_id": shot.shot_id,
            "author": "novel2video_plan.py",
            "created_at": date.today().isoformat(),
            "updated_at": date.today().isoformat(),
            "status": "draft_plan",
        },
        "global_settings": {
            "model": DEFAULT_MODEL,
            "ratio": "9:16",
            "resolution": "480p",
            "duration_sec": shot.duration_sec,
            "duration_policy": duration_policy,
            "generate_audio": True,
        },
        "project_meta": {
            "platform_target": platform,
            "core_selling_points": core_selling_points,
            "episode_title": episode_plan.title,
            "episode_hook": episode_plan.hook,
        },
        "language_policy": dict(language_policy),
        "emotion_arc": {
            "primary_emotions": episode_plan.emotions or ["悬疑", "压迫", "追问"],
            "secondary_emotions": ["保护欲", "不信任", "关系拉扯"],
            "hook_targets": {
                "first_15s": "强事件或异常入场",
                "first_45s": "核心疑点明确",
                "last_10s": episode_plan.hook,
            },
        },
        "character_anchor": {
            "primary": primary_anchor,
            "secondary": [
                character_to_anchor_node(c, lock_enabled=True)
                for c in secondary
            ],
        },
        "scene_anchor": {
            "scene_id": shot.scene_id,
            "scene_name": shot.scene_name,
            "scene_detail_ref": scene_detail_ref,
            "scene_detail_key": shot.scene_name,
            "scene_detail": scene_detail_text,
            "must_have_elements": must_have_elements,
            "prop_must_visible": prop_must_visible,
            "lighting_anchor": "写实电影光，低饱和，情绪明确",
        },
        "shot_execution": {
            "camera_plan": {"shot_type": shot.shot_type, "movement": shot.movement, "framing_focus": shot.framing_focus},
            "action_intent": shot.action_intent,
            "emotion_intent": shot.emotion_intent,
        },
        "scene_motion_contract": scene_motion_contract,
        "first_frame_contract": first_frame_contract,
        "dialogue_blocking": dialogue_blocking,
        "i2v_contract": i2v_contract,
        "dialogue_language": {
            "spoken_language": language_policy.get("spoken_language", DEFAULT_LANGUAGE_POLICY["spoken_language"]),
            "spoken_language_label": language_policy.get("spoken_language_label", DEFAULT_LANGUAGE_POLICY["spoken_language_label"]),
            "subtitle_language": language_policy.get("subtitle_language", DEFAULT_LANGUAGE_POLICY["subtitle_language"]),
            "subtitle_language_label": language_policy.get("subtitle_language_label", DEFAULT_LANGUAGE_POLICY["subtitle_language_label"]),
            "model_audio_language": language_policy.get("model_audio_language", DEFAULT_LANGUAGE_POLICY["model_audio_language"]),
            "voice_language_lock": language_policy.get("voice_language_lock", DEFAULT_LANGUAGE_POLICY["voice_language_lock"]),
            "screen_text_language_lock": language_policy.get("screen_text_language_lock", DEFAULT_LANGUAGE_POLICY["screen_text_language_lock"]),
            "environment_signage_language": language_policy.get("environment_signage_language", DEFAULT_LANGUAGE_POLICY["environment_signage_language"]),
            "forbidden_spoken_languages": language_policy.get("forbidden_spoken_languages", DEFAULT_LANGUAGE_POLICY["forbidden_spoken_languages"]),
            "dialogue_lines": shot.dialogue,
            "narration_lines": shot.narration,
            "subtitle_compact_lines": shot.subtitle,
            "dialogue_style_rules": [
                "口语化",
                "短句",
                "信息直给",
                "避免小说朗读腔",
                "所有对白和旁白只使用普通话中文",
                "不要生成日语、英语或中日混杂语音",
            ],
        },
        "prompt_render": {
            "positive_prefix": (
                f"{setting}，竖屏短剧，写实电影感，低饱和，真实光影，角色一致性稳定，"
                "所有角色对白、旁白和模型音频只使用普通话中文，屏幕字幕只使用简体中文"
            ),
            "shot_positive_core": shot_positive_core,
            "dialogue_overlay_hint": "；".join(f"{d['speaker']}：{d['text']}" for d in shot.dialogue),
            "subtitle_overlay_hint": " / ".join(shot.subtitle),
            "negative_prompt": negative_prompt,
        },
        "keyframe_static_anchor": build_keyframe_static_anchor(shot),
        "continuity_rules": {
            "character_state_transition": [shot.emotion_intent],
            "scene_transition": [f"{shot.scene_name}连续性稳定"],
            "prop_continuity": list(
                dict.fromkeys(
                    ["关键道具、服装、时代感保持一致"]
                    + [f"{prop}必须保持清晰可辨且不被误读" for prop in prop_must_visible]
                    + [str(item) for item in prop_stability.get("prop_continuity", [])]
                    + [f"禁止{item}" for item in scene_motion_contract.get("forbidden_scene_motion", [])]
                )
            ),
        },
        "qa_rules": {
            "visual_checks": list(
                dict.fromkeys(
                    ["角色不串脸", "时代/地域感正确", "无明显闪烁变形", "不出现露骨化表达"]
                    + [f"必须看出：{item}" for item in truth_must_show]
                    + [str(item) for item in prop_stability.get("qa_rules", [])]
                    + ([f"故事事实检查：{truth_check}"] if truth_check else [])
                )
            ),
            "language_checks": ["台词与动作一致", "字幕短句化", "对白/旁白/模型音频只使用普通话中文", "屏幕字幕只使用简体中文", "日文只允许作为无声环境招牌"],
            "rhythm_checks": ["镜头信息在前1-2秒成立"],
            "pass_fail": {"status": "pending", "failed_reasons": []},
        },
        "artifacts": {
            "prompt_txt_path": f"test/{experiment_id}/{shot.shot_id}/prompt.txt",
            "negative_prompt_txt_path": f"test/{experiment_id}/{shot.shot_id}/negative_prompt.txt",
            "duration_used_txt_path": f"test/{experiment_id}/{shot.shot_id}/duration_used.txt",
            "request_payload_preview_path": f"test/{experiment_id}/{shot.shot_id}/request_payload.preview.json",
            "final_status_path": f"test/{experiment_id}/{shot.shot_id}/final_status.json",
            "output_url_path": f"test/{experiment_id}/{shot.shot_id}/output_url.txt",
            "output_video_path": f"test/{experiment_id}/{shot.shot_id}/output.mp4",
        },
        "source_trace": {
            "episode_goal": episode_plan.goal,
            "source_basis": episode_plan.source_basis,
            "shot_source_basis": shot.source_basis,
            "story_truth_contract": story_truth_contract,
        },
        "ab_experiment": {"variant_id": "A", "variant_notes": "auto draft plan", "compared_with": "", "result_summary": ""},
        "postmortem": {"quality_score": {"face_consistency": 0, "scene_consistency": 0, "emotion_delivery": 0, "dialogue_alignment": 0, "overall": 0}, "issues": [], "root_causes": [], "next_actions": []},
    }


def build_index(project_name: str, episode_plan: EpisodePlan, episode_outline_count: int = 20) -> str:
    label = episode_plan.episode_label
    return f"""# {project_name} 项目文件目录

## 01_总方法论与项目底层文档
- 01_AI短剧生成手册.md
- 02_爆款题材库.md
- 03_小说转AI短剧工作流.md
- 04_Log.md
- 05_当前文件清单.md

## 02_模板与通用执行文档
- 06_小说短剧骨架卡模板.md
- 07_小说改编成短剧的提示词模板.md

## 03_当前项目的原始输入文档
- 08_{project_name}.md

## 04_当前项目的诊断与结构设计文档
- project_bible_v1.json
- 09_{project_name}短剧适配诊断与骨架提取.md
- 10_{project_name}短剧总纲.md
- 11_{project_name}前3集分集设计.md
- 12_{project_name}{episode_outline_count}集分集大纲.md
- 13_{project_name}人物关系与角色卡.md

## 05_当前项目的剧本与镜头层文档
- episode_plan_{episode_plan.episode_id}_v1.json
- 14_{project_name}{label}剧本.md
- 14A_{project_name}{label}完整成片剧本.md
- 15_{project_name}{label}镜头脚本.md
- 16_{project_name}{label}旁白字幕稿.md

## 06_当前项目的视觉与AI执行层文档
- 17_{project_name}视觉风格与分镜方案.md
- 18_{project_name}{label}AI生成提示词包.md
- 19_{project_name}角色统一视觉设定包.md
- 20_{project_name}角色海报提示词包.md
- 24_{project_name}{label}Seedance2.0逐镜头执行表.md
- 25_{project_name}{label}Seedance2.0最终提示词包.md
- 26_{project_name}提示词字段映射研究.md
- 27_prompt_schema_v1.json
- 28_prompt_record_template_v1.json
- 29_prompt_episode_manifest_v1.json
- 30_model_capability_profiles_v1.json
- 31_prompt_adapter_interface_v1.md
- 35_character_lock_profiles_v1.json
- records/

## 07_当前项目的包装与生产任务单文档
- 21_{project_name}{label}封面标题测试包.md
- 22_{project_name}{label}角色出图清单.md
- 23_{project_name}{label}场景出图清单.md
- 24A_{project_name}{label}视频导演准备运行手册.md

## 质量报告
- plan_qa_report.json
"""


def build_current_file_list(source: ProjectSource, out_dir: Path, map_path: Path) -> str:
    return f"""# 当前文件清单

## 项目
- 项目名：{source.project_name}
- 标题：{source.title}
- 根目录：{out_dir}
- 原文源头：{source.canonical_source_path}
- 角色图映射：{map_path}

## 说明
本目录由 `scripts/novel2video_plan.py` 生成，用于把 novel 原文整理成可继续进入短剧生产的计划包。

## 下一步
1. 检查 `project_bible_v1.json` 与 `episode_plan_*.json`。
2. 检查 09-26 的剧作、镜头、视觉和提示词内容。
3. 使用 `assets/characters/*.prompt.md` 生成角色参考图，并保存到对应 `.jpg` 路径。
4. 检查 `plan_qa_report.json` 后，运行 keyframe、image_input_map、语言计划和 Seedance 相关脚本。
"""


def build_log(source: ProjectSource, backend: str) -> str:
    return f"""# Log

## {date.today().isoformat()}
- 使用 `scripts/novel2video_plan.py` 从 `{source.novel_path}` 生成 `{source.project_name}` 短剧项目计划包。
- 生成方式：{backend}。
- 当前版本为数据驱动草案生成：project bible、episode plan、Markdown 草案、prompt specs、episode manifest、records JSON 已创建。
"""


def build_adapter_interface(project_name: str) -> str:
    return f"""# {project_name} prompt adapter interface v1

## 目标
把 `records/*.json` 渲染成下游视频生成脚本可用的 prompt、duration、dialogue/subtitle 输入。

## 约定
- `record_header.shot_id` 是镜头唯一 ID。
- `prompt_render.positive_prefix` + `prompt_render.shot_positive_core` 组成正向提示词。
- `prompt_render.negative_prompt` 是通用负向约束。
- `dialogue_language` 供语言计划、TTS、字幕流程消费。
"""


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    return value


def copy_common_docs(paths: ProjectPaths, overwrite: bool, dry_run: bool) -> list[str]:
    copied: list[str] = []
    mapping = [
        (TEMPLATE_ROOT / "01_总方法论与项目底层文档" / "01_AI短剧生成手册.md", paths.method_dir / "01_AI短剧生成手册.md"),
        (TEMPLATE_ROOT / "01_总方法论与项目底层文档" / "02_爆款题材库.md", paths.method_dir / "02_爆款题材库.md"),
        (TEMPLATE_ROOT / "01_总方法论与项目底层文档" / "03_小说转AI短剧工作流.md", paths.method_dir / "03_小说转AI短剧工作流.md"),
        (TEMPLATE_ROOT / "02_模板与通用执行文档" / "06_小说短剧骨架卡模板.md", paths.template_dir / "06_小说短剧骨架卡模板.md"),
        (TEMPLATE_ROOT / "02_模板与通用执行文档" / "07_小说改编成短剧的提示词模板.md", paths.template_dir / "07_小说改编成短剧的提示词模板.md"),
    ]
    for src, dest in mapping:
        if not src.exists():
            continue
        if dest.exists() and not overwrite:
            continue
        copied.append(str(dest))
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    return copied


def make_llm_task_request(task: str, payload: dict[str, Any], provider: str, model: str) -> dict[str, Any]:
    return {
        "task": task,
        "provider": provider,
        "model": model,
        "response_contract": "Return one valid JSON object only. Preserve existing keys unless explicitly refining text fields.",
        "input": payload,
    }


def i2v_prompt_design_reference() -> str:
    doc = read_text_if_exists(REPO_ROOT / "docs" / "I2V_prompt_design_rules.md").strip()
    if not doc:
        return "I2V prompt design rules document is missing; still enforce one-shot-one-task, single active speaker, stable props, and clear first frame."
    # Keep live LLM calls compact. The full document is the canonical local reference;
    # LLM calls receive this executable digest to avoid truncating examples mid-sentence.
    return """Canonical source: docs/I2V_prompt_design_rules.md

Core rules to execute:
1. Record is the source of truth; prompt.final.txt is compiled from structured fields.
2. One shot has one primary task: dialogue, reaction, action, prop_display, establishing, or transition.
3. Default dialogue rule: one active speaker per shot. Two visible people are allowed only if one is active and all others are silent with no lip movement.
4. If two onscreen people need to speak, split into A speaks / B reaction / B speaks / A reaction.
5. If two people are visible in first frame, define first speaker and make active speaker's face the visual center, or define an over-the-shoulder viewpoint with the speaking face centered.
6. Phone dialogue: remote phone voice and onscreen reply must be separate shots. While remote voice speaks, onscreen listener is visible, listening silently, no lip movement; remote caller is not visible.
7. Phone prop default: one smartphone held by listener near ear or chest, screen facing inward toward holder, screen content not visible to camera.
8. Every shot needs first_frame_contract: location, visual_center, visible_characters, character_positions, key_props, speaking_state, camera_motion_allowed.
9. First frame must be one stable state, not multiple locations, time jumps, flashbacks, or a whole action chain.
10. Important props must use prop_id. First appearance defines count, size, color, material, structure, first-frame position, visibility, motion policy, and controller.
11. Repeated props must reuse the same prop_id and canonical profile. Do not invent new size, color, material, or structure for the same prop.
12. Avoid vague prop quantity terms: 散落, 散乱, 数个, 若干, 一些, 多个, scattered, several, some, a few.
13. Dialogue shots should avoid walking, prop handoff, large gestures, and complex physical actions.
14. Action shots should avoid speech unless the motion is tiny and the speaker remains visually stable.
15. Scene detail text is pure environment only: architecture, fixed furniture, materials, light, sound, temperature. No people, names, dialogue, actions, or emotion arcs.
16. Use positive safety wording: 人物衣着完整，保持日常社交距离，朴素克制呈现.
17. Do not output negative safety terms: 不出现裸露, 裸露, 性暗示, 情色, 色情, nudity, sexual suggestion.

Required structured fields for each shot:
- first_frame_contract
- dialogue_blocking
- i2v_contract.shot_task
- i2v_contract.prop_library
- i2v_contract.prop_contract
- i2v_contract.phone_contract when phone/call exists
"""


def shot_reference_payload(shot: ShotPlan) -> dict[str, Any]:
    return {
        "shot_id": shot.shot_id,
        "duration_sec": shot.duration_sec,
        "priority": shot.priority,
        "scene_name": shot.scene_name,
        "shot_type": shot.shot_type,
        "framing_focus": shot.framing_focus,
        "action_intent": shot.action_intent,
        "dialogue": shot.dialogue,
        "source_basis": shot.source_basis,
    }


def llm_character_reference(characters: list[Character]) -> str:
    rows = [
        "| character_id | lock_profile_id | name | aliases | visual_anchor |",
        "| --- | --- | --- | --- | --- |",
    ]
    for character in characters:
        rows.append(
            "| "
            + " | ".join(
                [
                    character.character_id,
                    character.lock_profile_id,
                    character.name,
                    "、".join(character_aliases(character)),
                    character.visual_anchor,
                ]
            )
            + " |"
        )
    return "\n".join(rows)


def build_llm_fact_prompt(
    source: ProjectSource,
    bible: ProjectBible,
    episode_plan: EpisodePlan,
    shot_count: int,
) -> str:
    ep_source = extract_episode_source_text(source, episode_plan)
    ep01_reference = render_ep01_continuity_reference(source, bible, shot_count)
    i2v_reference = i2v_prompt_design_reference()
    return f"""你是短剧改编编剧和 AI 视频分镜导演。

你的任务不是写剧本，而是先从小说原文中抽取“{episode_plan.episode_label}可拍摄剧情事实表”。
必须忠实于小说原文。小说原文是最高优先级。第一集信息只用于连续性，不得覆盖本集原文。

[PROJECT_CONTEXT]
- 项目名：{source.project_name}
- 项目标题：{source.title}
- 平台：{bible.platform}
- 时代/地点/风格：{bible.setting}
- 视觉基线：{bible.visual_baseline}
- 语言：普通话中文角色对白优先，尽量不用旁白；简体中文字幕。

[CHARACTER_ASSETS]
{llm_character_reference(bible.characters)}

[I2V_PROMPT_DESIGN_RULES]
{i2v_reference}

[EP01_CONTINUITY]
以下内容只用于承接人物关系、空间风格、角色资产和上一集钩子；不得复制第一集镜头。
{ep01_reference}

[EPISODE_PLAN]
{json.dumps(to_jsonable(episode_plan), ensure_ascii=False, indent=2)}

[EPISODE_SOURCE_NOVEL]
{ep_source}

请只输出一个 JSON object，不要 Markdown 代码围栏。JSON schema:
{{
  "fact_table": [
    {{
      "index": 1,
      "source_basis": "小说中的具体情节依据",
      "story_fact": "可拍摄剧情事实",
      "characters": ["人物名"],
      "location": "具体地点",
      "key_action": "具体视觉动作",
      "key_props": ["道具"],
      "emotion_function": "情绪功能",
      "must_include": true
    }}
  ],
  "scene_catalog": [
    {{"scene_name": "具体场景", "scene_function": "场景功能", "characters": ["可出现人物"], "props": ["可出现道具"], "ep01_continuity": "与第一集的连续性"}}
  ],
  "prop_catalog": [
    {{"prop_id": "稳定英文ID", "prop": "道具", "first_shot_suggestion": "SHxx", "story_function": "剧情功能", "needs_closeup": true, "canonical_profile": {{"count": "数量", "size": "长宽高或大致尺寸", "color": "颜色", "material": "材质", "structure": "形状结构", "canonical_motion_policy": "默认运动策略"}}, "motion_policy": "数量、位置、首帧可见性、是否静止"}}
  ],
  "character_plan": [
    {{"character": "人物名", "episode_function": "本集功能", "suggested_shots": ["SHxx"], "use_character_asset": true, "notes": "注意事项"}}
  ],
  "repetition_risks": ["最容易拍重复的风险与规避方式"]
}}

硬性要求：
- “source_basis”必须引用本集小说中的具体情节，不要泛泛写“前夜回响”。
- “story_fact”和“key_action”必须是可拍摄事件，不要写抽象主题。
- 如果是心理活动，必须转成外化动作或对白。
- prop_catalog 中所有重要道具第一次出现必须定义 size / color / material / structure / canonical_motion_policy。
- 如果本集包含电话或手机通话，事实表必须区分远端声音、画面内听者、听者何时沉默、何时回复。
- 必须覆盖本集集尾钩子：{episode_plan.hook}
"""


def build_llm_shot_prompt(
    source: ProjectSource,
    bible: ProjectBible,
    episode_plan: EpisodePlan,
    heuristic_shots: list[ShotPlan],
    fact_payload: dict[str, Any],
    shot_count: int,
) -> str:
    ep_source = extract_episode_source_text(source, episode_plan)
    ep01_reference = render_ep01_continuity_reference(source, bible, shot_count)
    i2v_reference = i2v_prompt_design_reference()
    format_example_script = render_episode_script(source, build_episode_plan(bible, "EP01"), build_shot_plan(source, bible, build_episode_plan(bible, "EP01"), min(shot_count, 13)))
    format_example_shots = render_shot_script(source, build_episode_plan(bible, "EP01"), build_shot_plan(source, bible, build_episode_plan(bible, "EP01"), min(shot_count, 13)))
    heuristic_reference = [
        {
            "shot_id": shot.shot_id,
            "duration_sec": shot.duration_sec,
            "priority": shot.priority,
        }
        for shot in heuristic_shots
    ]
    return f"""你是竖屏短剧《{source.project_name}》的编剧、分镜导演和 AI 视频生产规划师。

你的任务是基于本集小说原文和剧情事实表，生成可以直接进入 AI 视频生产 pipeline 的 {shot_count} 个镜头。
必须严格遵守以下优先级：
1. EPISODE_SOURCE_NOVEL 是剧情事实最高优先级。
2. FACT_PAYLOAD 是镜头设计依据。
3. EP01_CONTINUITY 只用于承接人物关系、空间风格、角色资产和上一集钩子，不得复制第一集镜头。
4. OUTPUT_FORMAT_EXAMPLES 只学习格式，不学习内容。
5. 不得使用泛化占位词，例如“第2集核心场景”“人物目标亮相”“关系压力入场”“情绪临界点”。

[PROJECT_CONTEXT]
- 项目名：{source.project_name}
- 项目标题：{source.title}
- 平台：{bible.platform}
- 时代/地点/风格：{bible.setting}
- 视觉基线：{bible.visual_baseline}
- 语言：普通话中文角色对白优先，尽量不用旁白；简体中文字幕。

[CHARACTER_ASSETS]
{llm_character_reference(bible.characters)}

[I2V_PROMPT_DESIGN_RULES]
{i2v_reference}

[EP01_CONTINUITY]
{ep01_reference}

[EPISODE_PLAN]
{json.dumps(to_jsonable(episode_plan), ensure_ascii=False, indent=2)}

[EPISODE_SOURCE_NOVEL]
{ep_source}

[FACT_PAYLOAD]
{json.dumps(fact_payload, ensure_ascii=False, indent=2)}

[SHOT_SKELETON]
{json.dumps(heuristic_reference, ensure_ascii=False, indent=2)}

[OUTPUT_FORMAT_EXAMPLES]
剧本格式示例，只学习格式：
{format_example_script}

镜头脚本格式示例，只学习格式：
{format_example_shots}

请只输出一个 JSON object，不要 Markdown 代码围栏。JSON schema:
{{
  "episode_script_md": "# {source.project_name}{episode_plan.episode_label}剧本...",
  "shot_script_md": "# {source.project_name}{episode_plan.episode_label}镜头脚本...",
  "shots": [
    {{
      "shot_id": "SH01",
      "priority": "P0",
      "intent": "具体镜头意图",
      "duration_sec": 4,
      "shot_type": "大全景/中景/近景/特写/双人中景等",
      "movement": "固定机位/缓慢推进/轻微手持/跟拍/横移等",
      "framing_focus": "具体画面重点",
      "action_intent": "具体人物动作，不用抽象主题",
      "emotion_intent": "情绪重点",
      "scene_id": "EP02_具体英文或拼音场景ID",
      "scene_name": "具体地点",
      "dialogue": [{{"speaker": "角色名", "text": "普通话中文台词", "purpose": "台词功能", "source": "onscreen/phone/offscreen", "listener": "电话或画外声的接收者，可为空"}}],
      "narration": [],
      "subtitle": ["简体中文字幕"],
      "positive_core": "可直接用于视频生成的正向画面核心，必须包含具体地点、人物、动作、关键道具、现代银座写实悬疑风格",
      "first_frame_contract": {{
        "location": "单一地点",
        "visual_center": "首帧视觉中心",
        "visible_characters": ["首帧可见人物"],
        "character_positions": {{"人物名": "画面位置"}},
        "key_props": ["prop_id 或道具名"],
        "speaking_state": "谁在说/谁沉默/远端声音是否存在",
        "camera_motion_allowed": "固定机位/极轻微稳定推镜等"
      }},
      "dialogue_blocking": {{
        "active_speaker": "本镜头唯一主动说话人；如果是电话远端声音则写远端说话人",
        "first_speaker": "第一句归属",
        "speaker_visual_priority": "center_face/listener_visible/prop_closeup",
        "silent_visible_characters": ["画面中可见但保持沉默无口型的人"],
        "lip_sync_policy": "single_active_speaker/remote_voice_listener_silent/no_dialogue"
      }},
      "i2v_contract": {{
        "shot_task": "dialogue/reaction/action/prop_display/establishing/transition",
        "risk_level": "low/medium/high",
        "risk_notes": "如果违反一镜一任务或多人说话，说明原因",
        "prop_library": {{
          "PROP_ID": {{"display_name": "道具名", "count": "数量", "size": "尺寸", "color": "颜色", "material": "材质", "structure": "结构", "canonical_motion_policy": "稳定策略"}}
        }},
        "prop_contract": [
          {{"prop_id": "PROP_ID", "position": "本镜头首帧位置", "first_frame_visible": true, "motion_policy": "本镜头运动策略", "controlled_by": "人物名或none"}}
        ],
        "phone_contract": {{"holder": "持有人", "screen_orientation": "screen facing inward toward holder", "screen_content_visible": false}}
      }},
      "source_basis": "本镜头对应的小说具体情节依据"
    }}
  ],
  "fact_trace": [
    {{"shot_id": "SH01", "source_basis": "小说依据", "location": "地点", "characters": ["人物"], "action": "动作", "props": ["道具"]}}
  ],
  "qa_report": [
    {{"check": "是否避免相邻重复", "result": "pass/fail", "notes": "说明"}}
  ]
}}

硬性要求：
- 固定输出 {shot_count} 个镜头，编号 SH01-SH{shot_count:02d}。
- SH01-SH02 时长 4s；SH03-SH{shot_count - 1:02d} 时长 5s；SH{shot_count:02d} 时长 6s。
- 每个镜头必须有明确地点、人物、动作、道具或视觉重点。
- 每个镜头默认必须至少有一条角色对白；优先把信息改写成画面中角色说话，不要用旁白推进。
- `narration` 默认输出空数组；只有小说事实完全无法自然对白化时才允许使用旁白，并在 qa_report 说明原因。
- 严格执行一镜一口：默认每个镜头最多一个 onscreen 主动说话人；两人对话必须拆成“说话/反应/说话/反应”。不要让一个镜头内两个画面人物轮流说话。
- `dialogue[].source` 默认用 `onscreen`；画面内说话人必须出现在该镜头 keyframe 首帧。
- 如果一个镜头只有一个 `onscreen` 说话人，`framing_focus` 和 `positive_core` 的首帧必须包含这个人。
- 如果同一剧情需要两个 onscreen 角色说话，必须拆成相邻镜头；当前镜头只保留一个 active_speaker，其他可见人物写入 silent_visible_characters 且 no lip movement。
- 如果是电话、手机、听筒、对讲机或画外声音，必须把 `source` 写为 `phone` 或 `offscreen`，并填写 `listener`；听远端声音的镜头里 listener 必须沉默无口型；listener 回复时必须另起一个 onscreen speaking shot。
- 电话通话默认手机屏幕朝内、面向持有人，屏幕内容不可见；只有剧情必须展示屏幕时才允许可见，并要写清楚内容。
- 每个镜头可以有视频动作过程，但 `framing_focus` 和 `positive_core` 的第一句必须能单独作为一张静态首帧；不要把街道到走廊、抽屉到门口、调查室到闪回等多个地点或多个时间点并列塞进同一句首帧描述。
- 闪回、插入特写、听到某词后的反应、随后/最后发生的动作可以写在 `action_intent`，但必须让首帧状态在 `framing_focus` 中清楚、单一、可截图。
- 相邻镜头不能使用完全相同的“地点 + 人物 + 动作”组合。
- 如果相邻镜头地点和人物相同，动作、景别、道具、情绪功能至少要变化两项。
- 每个镜头必须能追溯到 EPISODE_SOURCE_NOVEL 或 FACT_PAYLOAD。
- 场景空镜不能错误继承主角 character asset。
- 临时人物如警员、服务员、路人，只能作为临时人物，不要绑定主角资产。
- 现代银座/东京悬疑项目，不得出现古代、古装、年代错置元素。
- 道具如果重要，必须写清楚数量、大小/长宽高、颜色、材质、结构、位置、是否首帧可见、是否静止；后续镜头复用同一 prop_id 和 canonical profile。
- 禁止使用“散落、散乱、数个、若干、一些、多个”等不定量道具描述。
- 使用正向安全措辞，例如“人物衣着完整，保持日常社交距离，朴素克制呈现”；不要输出“不出现裸露、性暗示、情色”等负向安全词。
- 集尾最后一个镜头必须落到“{episode_plan.hook}”。

禁止输出以下泛化表达作为 intent、action_intent、framing_focus 或 positive_core：
“人物目标亮相”、“关系压力入场”、“关键证据或道具出现”、“第一次正面冲突”、“主角被迫解释”、“对方隐藏信息”、“秘密被外化成行动”、“情绪临界点”、“新线索压近”、“第2集核心场景”。
"""


def build_llm_single_shot_prompt(
    source: ProjectSource,
    bible: ProjectBible,
    episode_plan: EpisodePlan,
    heuristic_shots: list[ShotPlan],
    fact_payload: dict[str, Any],
    target_index: int,
    prior_shots: list[ShotPlan],
) -> str:
    ep_source = extract_episode_source_text(source, episode_plan)
    i2v_reference = i2v_prompt_design_reference()
    target_shot = heuristic_shots[target_index - 1]
    target_shot_id = f"SH{target_index:02d}"
    immediate_previous = prior_shots[-1] if prior_shots else None
    previous_label = immediate_previous.shot_id if immediate_previous else "NONE"
    immediate_previous_payload = shot_reference_payload(immediate_previous) if immediate_previous else {}
    previous_reference = [shot_reference_payload(shot) for shot in prior_shots[-4:]]
    next_reference = (
        shot_reference_payload(heuristic_shots[target_index])
        if target_index < len(heuristic_shots)
        else {}
    )
    return f"""你是竖屏短剧《{source.project_name}》的单镜头 AI 视频生产规划师。

你的任务是只生成 {episode_plan.episode_label} 的一个镜头：{target_shot_id}。
不要生成其它镜头。不要写整集剧本。不要输出 Markdown 代码围栏。

必须严格遵守以下优先级：
1. EPISODE_SOURCE_NOVEL 是剧情事实最高优先级。
2. FACT_PAYLOAD 是镜头设计依据。
3. IMMEDIATE_PREVIOUS_SHOT 是上一镜头；RECENT_ACCEPTED_SHOTS 是最近几个已经通过的前序镜头，只用于连续性和避免重复。
4. TARGET_SHOT_SKELETON 只给镜头编号、时长和大致位置；可以重写内容以符合小说事实和 I2V 规则。
5. I2V_PROMPT_DESIGN_RULES 必须执行，尤其是一镜一口、电话拆分、首帧稳定、道具库一致性。

[PROJECT_CONTEXT]
- 项目名：{source.project_name}
- 项目标题：{source.title}
- 平台：{bible.platform}
- 时代/地点/风格：{bible.setting}
- 视觉基线：{bible.visual_baseline}
- 语言：普通话中文角色对白优先，尽量不用旁白；简体中文字幕。

[CHARACTER_ASSETS]
{llm_character_reference(bible.characters)}

[I2V_PROMPT_DESIGN_RULES]
{i2v_reference}

[EPISODE_PLAN]
{json.dumps(to_jsonable(episode_plan), ensure_ascii=False, indent=2)}

[EPISODE_SOURCE_NOVEL]
{ep_source}

[FACT_PAYLOAD]
{json.dumps(fact_payload, ensure_ascii=False, indent=2)}

[IMMEDIATE_PREVIOUS_SHOT_{previous_label}]
{json.dumps(immediate_previous_payload, ensure_ascii=False, indent=2)}

[RECENT_ACCEPTED_SHOTS]
{json.dumps(previous_reference, ensure_ascii=False, indent=2)}

[TARGET_SHOT_SKELETON]
{json.dumps(shot_reference_payload(target_shot), ensure_ascii=False, indent=2)}

[NEXT_SHOT_HINT]
{json.dumps(next_reference, ensure_ascii=False, indent=2)}

请只输出一个 JSON object。JSON schema:
{{
  "shots": [
    {{
      "shot_id": "{target_shot_id}",
      "priority": "P0/P1",
      "intent": "具体镜头意图",
      "duration_sec": {target_shot.duration_sec},
      "shot_type": "大全景/中景/近景/特写/双人中景等",
      "movement": "固定机位/缓慢推进/轻微手持/跟拍/横移等",
      "framing_focus": "首帧可截图的具体画面重点",
      "action_intent": "本镜头视频过程，只保留一个主要任务",
      "emotion_intent": "可见情绪重点",
      "scene_id": "EP{episode_plan.episode_number:02d}_具体场景ID",
      "scene_name": "具体地点",
      "dialogue": [{{"speaker": "角色名", "text": "普通话中文台词", "purpose": "台词功能", "source": "onscreen/phone/offscreen", "listener": "电话或画外声的接收者，可为空"}}],
      "narration": [],
      "subtitle": ["简体中文字幕"],
      "positive_core": "可直接用于视频生成的正向画面核心，第一句必须是单一稳定首帧",
      "first_frame_contract": {{
        "location": "单一地点",
        "visual_center": "首帧视觉中心",
        "visible_characters": ["首帧可见人物"],
        "character_positions": {{"人物名": "画面位置"}},
        "key_props": ["prop_id 或道具名"],
        "speaking_state": "谁在说/谁沉默/远端声音是否存在",
        "camera_motion_allowed": "固定机位/极轻微稳定推镜等"
      }},
      "dialogue_blocking": {{
        "active_speaker": "本镜头唯一主动说话人；如果是电话远端声音则写远端说话人",
        "first_speaker": "第一句归属",
        "speaker_visual_priority": "center_face/listener_visible/prop_closeup",
        "silent_visible_characters": ["画面中可见但保持沉默无口型的人"],
        "lip_sync_policy": "single_active_speaker/remote_voice_listener_silent/no_dialogue"
      }},
      "i2v_contract": {{
        "shot_task": "dialogue/reaction/action/prop_display/establishing/transition",
        "risk_level": "low/medium/high",
        "risk_notes": "如果存在风险，说明原因",
        "prop_library": {{
          "PROP_ID": {{"display_name": "道具名", "count": "数量", "size": "尺寸", "color": "颜色", "material": "材质", "structure": "结构", "canonical_motion_policy": "稳定策略"}}
        }},
        "prop_contract": [
          {{"prop_id": "PROP_ID", "position": "本镜头首帧位置", "first_frame_visible": true, "motion_policy": "本镜头运动策略", "controlled_by": "人物名或none"}}
        ],
        "phone_contract": {{"holder": "持有人", "screen_orientation": "screen facing inward toward holder", "screen_content_visible": false}}
      }},
      "source_basis": "本镜头对应的小说具体情节依据"
    }}
  ],
  "qa_report": [
    {{"check": "I2V rule self-check", "result": "pass/fail", "notes": "说明"}}
  ]
}}

硬性要求：
- 只输出 {target_shot_id} 一个镜头，`shots` 数组长度必须为 1。
- `shot_id` 必须等于 "{target_shot_id}"，`duration_sec` 必须等于 {target_shot.duration_sec}。
- 默认每个镜头最多一个 onscreen 主动说话人；不能让两个画面人物轮流说话。
- 如果是远端电话声音，listener 必须可见并沉默无口型；listener 回复必须放在另一个镜头。
- 电话通话默认手机屏幕朝内、面向持有人，屏幕内容不可见。
- 重要道具必须写 prop_id，并在第一次出现时定义 count / size / color / material / structure / canonical_motion_policy。
- 后续镜头若复用道具，沿用 FACT_PAYLOAD、IMMEDIATE_PREVIOUS_SHOT 或 RECENT_ACCEPTED_SHOTS 中的 prop_id 和描述，不要改尺寸、颜色、材质、结构。
- 如果 IMMEDIATE_PREVIOUS_SHOT_{previous_label} 不为空，必须保持同一场景、人物状态、道具位置和电话状态的连续性；不要重复上一镜已经完成的信息功能。
- 禁止使用“散落、散乱、数个、若干、一些、多个”等不定量道具描述。
- 使用正向安全措辞：人物衣着完整，保持日常社交距离，朴素克制呈现。
- 不要输出“不出现裸露、性暗示、情色、色情”等负向安全词。
- `framing_focus` 和 `positive_core` 第一句必须是单一稳定首帧，不要混入多个地点、多个时间点或完整动作链。
- 每个镜头必须能追溯到 EPISODE_SOURCE_NOVEL 或 FACT_PAYLOAD。
- 如果 {target_shot_id} 是最后一个镜头，必须落到“{episode_plan.hook}”。
"""


def openai_responses_payload(model: str, prompt: str, reasoning_effort: str, max_output_tokens: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": "You are a precise short-drama planning engine. Return one valid JSON object only.",
                    }
                ],
            },
            {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
        ],
        "max_output_tokens": max_output_tokens,
        "text": {"format": {"type": "json_object"}},
    }
    if reasoning_effort != "none":
        payload["reasoning"] = {"effort": reasoning_effort}
    return payload


def extract_openai_output_text(response: dict[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    chunks: list[str] = []
    for item in response.get("output", []) if isinstance(response.get("output"), list) else []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
            if not isinstance(content, dict):
                continue
            text = content.get("text") or content.get("output_text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()


def parse_llm_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("LLM response is not a JSON object")
    return payload


def call_openai_json(
    payload: dict[str, Any],
    api_key: str,
    base_url: str,
    timeout_sec: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if requests is None:
        raise RuntimeError("requests package unavailable")
    response = requests.post(
        base_url.rstrip("/") + "/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout_sec,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI Responses API failed {response.status_code}: {response.text[:1000]}")
    raw = response.json()
    text = extract_openai_output_text(raw)
    if not text:
        raise RuntimeError("OpenAI response did not contain output text")
    return parse_llm_json(text), raw


def write_llm_request_preview(
    path: Path,
    task: str,
    request: dict[str, Any],
    args: argparse.Namespace,
    overwrite: bool,
    dry_run: bool,
) -> None:
    if dry_run:
        print(f"[DRY] write {path}")
        return
    write_json(path, make_llm_task_request(task, request, args.llm_provider, args.llm_model), overwrite)


def as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


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


def as_dialogue_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    lines: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker") or "").strip()
        text = str(item.get("text") or "").strip()
        if not speaker or not text:
            continue
        purpose = str(item.get("purpose") or "剧情信息").strip()
        source = normalize_dialogue_source(item.get("source"), text=text, purpose=purpose)
        line: dict[str, Any] = {
            "speaker": speaker,
            "text": text,
            "purpose": purpose,
            "source": source,
            "requires_keyframe_presence": source == "onscreen",
        }
        listener = dialogue_listener_name(item)
        if listener:
            line["listener"] = listener
        lines.append(line)
    return lines


def unique_names(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(str(v).strip() for v in values if str(v).strip()) if value]


def onscreen_dialogue_speakers(dialogue: list[dict[str, Any]]) -> list[str]:
    return unique_names(
        [
            str(line.get("speaker") or "")
            for line in dialogue
            if normalize_dialogue_source(line.get("source"), line.get("text", ""), line.get("purpose", "")) == "onscreen"
        ]
    )


def phone_dialogue_listeners(dialogue: list[dict[str, Any]]) -> list[str]:
    return unique_names(
        [
            dialogue_listener_name(line)
            for line in dialogue
            if normalize_dialogue_source(line.get("source"), line.get("text", ""), line.get("purpose", "")) == "phone"
        ]
    )


def visible_dialogue_characters(shot: ShotPlan) -> list[str]:
    return unique_names(onscreen_dialogue_speakers(shot.dialogue) + phone_dialogue_listeners(shot.dialogue))


def phone_dialogue_missing_listener(dialogue: list[dict[str, Any]]) -> list[str]:
    return [
        str(line.get("speaker") or "").strip()
        for line in dialogue
        if normalize_dialogue_source(line.get("source"), line.get("text", ""), line.get("purpose", "")) == "phone"
        and not dialogue_listener_name(line)
    ]


def dialogue_visibility_contract(shot: ShotPlan) -> str:
    onscreen = onscreen_dialogue_speakers(shot.dialogue)
    listeners = phone_dialogue_listeners(shot.dialogue)
    return dialogue_visibility_contract_for_names(onscreen, listeners)


def dialogue_visibility_contract_for_names(onscreen: list[str], listeners: list[str]) -> str:
    parts: list[str] = []
    if len(onscreen) == 1:
        parts.append(f"对白可见人物契约：{onscreen[0]}是画面内说话人，首帧必须清楚入镜。")
    elif len(onscreen) >= 2:
        parts.append(f"对白可见人物契约：{'、'.join(onscreen)}是画面内说话人，首帧必须同时清楚入镜。")
    if listeners:
        parts.append(f"电话/画外声音契约：{'、'.join(listeners)}是听电话/接收声音的人，首帧必须清楚入镜并呈现听电话或倾听动作；远端说话人不强制入镜。")
    return "".join(parts)


def sanitize_sensitive_intimacy_text(value: str) -> str:
    text = value
    replacements = {
        "彩花把额头贴近健一胸口": "彩花站在健一身旁保持克制距离",
        "彩花靠在健一胸前": "彩花站在健一身旁",
        "靠在健一胸前": "站在健一身旁",
        "贴近健一耳侧": "抬眼低声说话",
        "额头贴近": "微微低头靠近但保持社交距离",
        "右手环上彩花腰侧": "右手停在身侧，点头答应",
        "手环上她的腰": "手停在身侧并点头答应",
        "环住她的腰": "手停在身侧并点头答应",
        "健一迟疑后环住她的腰": "健一迟疑后点头答应",
        "呼吸交融": "低声对话",
        "温热的鼻息": "压低声音",
        "呼吸变重": "神情变得迟疑",
        "肩带微微滑落": "丝质礼服的肩线在烛光下保持完整得体",
        "肩带的滑落": "丝质礼服的低光纹理",
        "身体的轻微颤动": "手指的轻微停顿",
        "身体": "姿态",
        "画面亲密但压抑": "画面克制而压抑",
        "亲密": "克制关系",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if any(token in text for token in ("领带", "彩花", "健一")) and "衣着完整" not in text:
        text = f"{text}，人物衣着完整，保持日常社交距离，朴素克制呈现"
    return text


def scene_id_from_name(episode_plan: EpisodePlan, scene_name: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", scene_name)
    suffix = "_".join(token.upper() for token in tokens[:4])
    if not suffix:
        suffix = f"SCENE_{sum(ord(ch) for ch in scene_name) % 10000:04d}"
    return f"EP{episode_plan.episode_number:02d}_{suffix}"


def normalize_llm_shots(
    payload: dict[str, Any],
    episode_plan: EpisodePlan,
    bible: ProjectBible,
    shot_count: int,
    start_index: int = 1,
    total_shot_count: int | None = None,
) -> list[ShotPlan]:
    raw_shots = payload.get("shots")
    if not isinstance(raw_shots, list):
        raise ValueError("LLM response missing shots list")
    raw_shots = [item for item in raw_shots if isinstance(item, dict)]
    if len(raw_shots) != shot_count:
        raise ValueError(f"LLM response shot count mismatch: expected {shot_count}, got {len(raw_shots)}")

    total = total_shot_count or shot_count
    shots: list[ShotPlan] = []
    for offset, item in enumerate(raw_shots):
        idx = start_index + offset
        if not isinstance(item, dict):
            raise ValueError(f"shot {idx} is not an object")
        shot_id = f"SH{idx:02d}"
        supplied_id = str(item.get("shot_id") or shot_id).strip().upper()
        if supplied_id != shot_id:
            raise ValueError(f"shot id mismatch at {idx}: expected {shot_id}, got {supplied_id}")
        duration = 6 if idx == total else (4 if idx in (1, 2) else 5)
        dialogue = as_dialogue_list(item.get("dialogue"))
        narration = as_string_list(item.get("narration"))
        if dialogue:
            narration = []
        subtitle = as_string_list(item.get("subtitle")) or [d["text"] for d in dialogue] or narration
        intent = str(item.get("intent") or item.get("framing_focus") or f"{episode_plan.title}{shot_id}").strip()
        scene_name = str(item.get("scene_name") or item.get("location") or f"{episode_plan.episode_label}具体场景").strip()
        action_intent = str(item.get("action_intent") or item.get("action") or intent).strip()
        framing_focus = str(item.get("framing_focus") or intent).strip()
        positive_core = str(item.get("positive_core") or "").strip()
        if not positive_core:
            positive_core = f"{bible.setting}，{scene_name}，{action_intent}，{framing_focus}，竖屏短剧，写实电影感"
        action_intent = sanitize_sensitive_intimacy_text(action_intent)
        framing_focus = sanitize_sensitive_intimacy_text(framing_focus)
        positive_core = sanitize_sensitive_intimacy_text(positive_core)
        onscreen = onscreen_dialogue_speakers(dialogue)
        listeners = phone_dialogue_listeners(dialogue)
        visibility_contract = dialogue_visibility_contract_for_names(onscreen, listeners)
        if visibility_contract:
            if "对白可见人物契约" not in framing_focus and "电话/画外声音契约" not in framing_focus:
                framing_focus = f"{framing_focus} {visibility_contract}"
            if "对白可见人物契约" not in positive_core and "电话/画外声音契约" not in positive_core:
                positive_core = f"{positive_core} {visibility_contract}"
        if idx == shot_count and dialogue:
            hook_instruction = "集尾钩子必须由角色对白完成，保留完整台词，不使用旁白替代"
            if "集尾" not in action_intent and "钩子" not in action_intent:
                action_intent = f"{action_intent}，{hook_instruction}"
            if "台词" not in positive_core and "对白" not in positive_core:
                positive_core = f"{positive_core}，{hook_instruction}"
        scene_id = str(item.get("scene_id") or "").strip() or scene_id_from_name(episode_plan, scene_name)
        first_frame_contract = item.get("first_frame_contract") if isinstance(item.get("first_frame_contract"), dict) else None
        dialogue_blocking = item.get("dialogue_blocking") if isinstance(item.get("dialogue_blocking"), dict) else None
        i2v_contract = item.get("i2v_contract") if isinstance(item.get("i2v_contract"), dict) else None
        shots.append(
            ShotPlan(
                shot_id=shot_id,
                priority=str(item.get("priority") or ("P0" if idx in (1, 5, shot_count) else "P1")).strip(),
                intent=intent,
                duration_sec=duration,
                shot_type=str(item.get("shot_type") or ("中景" if idx % 3 else "近景特写")).strip(),
                movement=str(item.get("movement") or ("轻微手持" if idx % 2 else "缓慢推进")).strip(),
                framing_focus=framing_focus,
                action_intent=action_intent,
                emotion_intent=str(item.get("emotion_intent") or "悬疑追问").strip(),
                scene_id=scene_id,
                scene_name=scene_name,
                dialogue=dialogue,
                narration=narration,
                subtitle=subtitle,
                positive_core=positive_core,
                source_basis=str(item.get("source_basis") or "").strip(),
                first_frame_contract=first_frame_contract,
                dialogue_blocking=dialogue_blocking,
                i2v_contract=i2v_contract,
            )
        )
    return shots


def run_per_shot_planning(
    args: argparse.Namespace,
    llm_dir: Path,
    source: ProjectSource,
    bible: ProjectBible,
    episode_plan: EpisodePlan,
    heuristic_shots: list[ShotPlan],
    fact_payload: dict[str, Any],
    api_key: str,
    overwrite: bool,
    dry_run: bool,
) -> tuple[list[ShotPlan], list[str]]:
    request_files: list[str] = []
    planned_shots: list[ShotPlan] = []
    if str(getattr(args, "llm_only_shot", "") or "").strip():
        only = str(args.llm_only_shot).strip().upper()
        match = re.fullmatch(r"SH(\d{1,3})", only)
        if not match:
            raise ValueError(f"--llm-only-shot must look like SH01, got {args.llm_only_shot!r}")
        target_indices = [int(match.group(1))]
    else:
        target_indices = list(range(1, len(heuristic_shots) + 1))
    for idx in target_indices:
        if idx < 1 or idx > len(heuristic_shots):
            raise ValueError(f"--llm-only-shot is outside planned shot range 1-{len(heuristic_shots)}")
        target = heuristic_shots[idx - 1]
        prior_context = list(planned_shots)
        if not prior_context and idx > 1:
            for prev_idx in range(1, idx):
                prev_response_path = llm_dir / f"SH{prev_idx:02d}.response.json"
                if prev_response_path.exists():
                    prev_payload = read_json_if_exists(prev_response_path).get("parsed", {})
                    try:
                        prior_context.extend(
                            normalize_llm_shots(
                                prev_payload,
                                episode_plan,
                                bible,
                                1,
                                start_index=prev_idx,
                                total_shot_count=len(heuristic_shots),
                            )
                        )
                    except Exception:
                        prior_context.append(heuristic_shots[prev_idx - 1])
                else:
                    prior_context.append(heuristic_shots[prev_idx - 1])
        prompt = build_llm_single_shot_prompt(
            source,
            bible,
            episode_plan,
            heuristic_shots,
            fact_payload,
            idx,
            prior_context,
        )
        request = openai_responses_payload(
            args.llm_model,
            prompt,
            args.llm_reasoning_effort,
            args.llm_max_output_tokens,
        )
        request_path = llm_dir / f"{target.shot_id}.request.json"
        request_files.append(str(request_path))
        write_llm_request_preview(request_path, f"episode_single_shot_{target.shot_id}", request, args, overwrite, dry_run)
        if args.llm_dry_run or dry_run:
            continue
        payload, raw = call_openai_json(request, api_key, args.llm_base_url, args.llm_timeout_sec)
        response_path = llm_dir / f"{target.shot_id}.response.json"
        write_json(response_path, {"parsed": payload, "raw": raw}, overwrite)
        planned = normalize_llm_shots(
            payload,
            episode_plan,
            bible,
            1,
            start_index=idx,
            total_shot_count=len(heuristic_shots),
        )
        planned_shots.extend(planned)
        print(f"[INFO] LLM single-shot planner applied: {args.llm_model} {target.shot_id}")
    return planned_shots, request_files


def run_llm_backend(
    args: argparse.Namespace,
    paths: ProjectPaths,
    source: ProjectSource,
    bible: ProjectBible,
    episode_plan: EpisodePlan,
    shots: list[ShotPlan],
    overwrite: bool,
    dry_run: bool,
    initial_request_files: list[str] | None = None,
    initial_fallbacks: list[dict[str, str]] | None = None,
) -> tuple[EpisodePlan, list[ShotPlan], LLMRunResult]:
    if args.backend != "llm":
        return episode_plan, shots, LLMRunResult(args.backend, args.llm_provider, args.llm_model, bool(args.llm_dry_run), [], [], False)

    llm_dir = paths.out_dir / "llm_requests"
    request_files: list[str] = list(initial_request_files or [])
    fallbacks: list[dict[str, str]] = list(initial_fallbacks or [])
    fact_prompt = build_llm_fact_prompt(source, bible, episode_plan, len(shots))
    fact_request = openai_responses_payload(
        args.llm_model,
        fact_prompt,
        args.llm_reasoning_effort,
        args.llm_max_output_tokens,
    )
    fact_request_path = llm_dir / "episode_fact_table.request.json"
    request_files.append(str(fact_request_path))
    if dry_run:
        print(f"[DRY] write {fact_request_path}")
    else:
        write_json(fact_request_path, make_llm_task_request("episode_fact_table", fact_request, args.llm_provider, args.llm_model), overwrite)

    if args.llm_dry_run or dry_run:
        placeholder_fact = {"fact_table": "LLM fact table will be inserted here after step 1."}
        if args.llm_shot_mode == "per-shot":
            _, shot_request_files = run_per_shot_planning(
                args,
                llm_dir,
                source,
                bible,
                episode_plan,
                shots,
                placeholder_fact,
                "",
                overwrite,
                dry_run,
            )
            request_files.extend(shot_request_files)
        else:
            shot_prompt = build_llm_shot_prompt(
                source,
                bible,
                episode_plan,
                shots,
                placeholder_fact,
                len(shots),
            )
            shot_request = openai_responses_payload(
                args.llm_model,
                shot_prompt,
                args.llm_reasoning_effort,
                args.llm_max_output_tokens,
            )
            shot_request_path = llm_dir / "episode_script_and_shots.request.json"
            request_files.append(str(shot_request_path))
            write_llm_request_preview(shot_request_path, "episode_script_and_shots", shot_request, args, overwrite, dry_run)
        reason = "llm-dry-run enabled; heuristic output kept" if args.llm_dry_run else "dry-run enabled; heuristic output kept"
        fallbacks.append({"task": "all", "reason": reason})
        return episode_plan, shots, LLMRunResult(args.backend, args.llm_provider, args.llm_model, True, request_files, fallbacks, False)

    if args.llm_provider != "openai":
        fallbacks.append({"task": "all", "reason": f"live provider {args.llm_provider} is not supported; heuristic output kept"})
        return episode_plan, shots, LLMRunResult(args.backend, args.llm_provider, args.llm_model, False, request_files, fallbacks, False)

    api_key = os.getenv(args.llm_api_key_env, "").strip()
    if not api_key:
        fallbacks.append({"task": "all", "reason": f"{args.llm_api_key_env} is not set; heuristic output kept"})
        return episode_plan, shots, LLMRunResult(args.backend, args.llm_provider, args.llm_model, False, request_files, fallbacks, False)
    elif requests is None:
        fallbacks.append({"task": "all", "reason": "requests package unavailable; heuristic output kept"})
        return episode_plan, shots, LLMRunResult(args.backend, args.llm_provider, args.llm_model, False, request_files, fallbacks, False)

    try:
        fact_payload, fact_raw = call_openai_json(fact_request, api_key, args.llm_base_url, args.llm_timeout_sec)
        fact_response_path = llm_dir / "episode_fact_table.response.json"
        if not dry_run:
            write_json(fact_response_path, {"parsed": fact_payload, "raw": fact_raw}, overwrite)

        if args.llm_shot_mode == "per-shot":
            llm_shots, shot_request_files = run_per_shot_planning(
                args,
                llm_dir,
                source,
                bible,
                episode_plan,
                shots,
                fact_payload,
                api_key,
                overwrite,
                dry_run,
            )
            request_files.extend(shot_request_files)
            print(f"[INFO] LLM per-shot episode planner applied: {args.llm_model} shots={len(llm_shots)}")
            return episode_plan, llm_shots, LLMRunResult(args.backend, args.llm_provider, args.llm_model, False, request_files, [], True)

        shot_prompt = build_llm_shot_prompt(source, bible, episode_plan, shots, fact_payload, len(shots))
        shot_request = openai_responses_payload(
            args.llm_model,
            shot_prompt,
            args.llm_reasoning_effort,
            args.llm_max_output_tokens,
        )
        shot_request_path = llm_dir / "episode_script_and_shots.request.json"
        request_files.append(str(shot_request_path))
        if not dry_run:
            write_json(shot_request_path, make_llm_task_request("episode_script_and_shots", shot_request, args.llm_provider, args.llm_model), overwrite)

        shot_payload, shot_raw = call_openai_json(shot_request, api_key, args.llm_base_url, args.llm_timeout_sec)
        shot_response_path = llm_dir / "episode_script_and_shots.response.json"
        if not dry_run:
            write_json(shot_response_path, {"parsed": shot_payload, "raw": shot_raw}, overwrite)

        llm_shots = normalize_llm_shots(shot_payload, episode_plan, bible, len(shots))
        print(f"[INFO] LLM episode planner applied: {args.llm_model} shots={len(llm_shots)}")
        return episode_plan, llm_shots, LLMRunResult(args.backend, args.llm_provider, args.llm_model, False, request_files, [], True)
    except Exception as exc:
        fallbacks.append({"task": "all", "reason": f"live LLM planning failed: {exc}; heuristic output kept"})
        print(f"[WARN] {fallbacks[-1]['reason']}", file=sys.stderr)
        return episode_plan, shots, LLMRunResult(args.backend, args.llm_provider, args.llm_model, False, request_files, fallbacks, False)


def artifact(path: Path, category: str, scope: str, deps: list[str], project_specific: bool) -> ArtifactSpec:
    return ArtifactSpec(path=path, category=category, scope=scope, dependencies=deps, project_specific=project_specific)


def render_artifacts(
    paths: ProjectPaths,
    source: ProjectSource,
    bible: ProjectBible,
    episode_plan: EpisodePlan,
    shots: list[ShotPlan],
    args: argparse.Namespace,
) -> tuple[list[tuple[ArtifactSpec, str]], list[tuple[ArtifactSpec, dict[str, Any]]]]:
    pn = source.project_name
    label = episode_plan.episode_label
    scene_detail_ref = "scene_detail.txt"
    scene_detail_map = build_scene_detail_map(shots, bible.setting)
    text_specs: list[tuple[ArtifactSpec, str]] = [
        (artifact(paths.out_dir / "00_目录清单.md", "index", "project", ["ProjectBible", "EpisodePlan"], True), build_index(pn, episode_plan, len(bible.episode_outlines))),
        (artifact(paths.method_dir / "04_Log.md", "log", "project", ["ProjectSource"], True), build_log(source, args.backend)),
        (artifact(paths.method_dir / "05_当前文件清单.md", "inventory", "project", ["ProjectSource"], True), build_current_file_list(source, paths.out_dir, paths.novel_dir / "character_image_map.json")),
        (artifact(paths.input_dir / f"08_{pn}.md", "source_snapshot", "project", ["ProjectSource"], True), source.text),
        (artifact(paths.structure_dir / f"09_{pn}短剧适配诊断与骨架提取.md", "diagnosis", "project", ["ProjectBible"], True), render_diagnosis(source, bible)),
        (artifact(paths.structure_dir / f"10_{pn}短剧总纲.md", "series_outline", "project", ["ProjectBible"], True), render_series_outline(source, bible)),
        (artifact(paths.structure_dir / f"11_{pn}前3集分集设计.md", "episode_outline", "project", ["ProjectBible"], True), render_first_three(source, bible)),
        (artifact(paths.structure_dir / f"12_{pn}{len(bible.episode_outlines)}集分集大纲.md", "episode_outline", "project", ["ProjectBible"], True), render_episode_outlines(source, bible)),
        (artifact(paths.structure_dir / f"13_{pn}人物关系与角色卡.md", "character_cards", "project", ["ProjectBible"], True), render_character_cards(source, bible)),
        (artifact(paths.script_dir / f"14_{pn}{label}剧本.md", "script", "episode", ["EpisodePlan", "ShotPlan"], True), render_episode_script(source, episode_plan, shots)),
        (artifact(paths.script_dir / f"14A_{pn}{label}完整成片剧本.md", "screenplay", "episode", ["EpisodePlan", "ShotPlan", "CharacterAssets"], True), render_screenplay(source, bible, episode_plan, shots, paths.character_assets_dir)),
        (artifact(paths.script_dir / f"15_{pn}{label}镜头脚本.md", "shot_script", "episode", ["EpisodePlan", "ShotPlan"], True), render_shot_script(source, episode_plan, shots)),
        (artifact(paths.script_dir / f"16_{pn}{label}旁白字幕稿.md", "subtitles", "episode", ["EpisodePlan", "ShotPlan"], True), render_subtitles(source, episode_plan, shots)),
        (artifact(paths.execution_dir / f"17_{pn}视觉风格与分镜方案.md", "visual_style", "project", ["ProjectBible"], True), render_visual_style(source, bible)),
        (artifact(paths.execution_dir / f"18_{pn}{label}AI生成提示词包.md", "prompt_pack", "episode", ["ShotPlan"], True), render_ai_prompt_pack(source, bible, episode_plan, shots)),
        (artifact(paths.execution_dir / f"19_{pn}角色统一视觉设定包.md", "character_visual", "project", ["ProjectBible"], True), render_character_visual_pack(source, bible)),
        (artifact(paths.execution_dir / f"20_{pn}角色海报提示词包.md", "character_prompt", "project", ["ProjectBible"], True), render_character_poster_pack(source, bible)),
        (artifact(paths.packaging_dir / f"21_{pn}{label}封面标题测试包.md", "packaging", "episode", ["EpisodePlan"], True), render_cover_title_pack(source, bible, episode_plan)),
        (artifact(paths.packaging_dir / f"22_{pn}{label}角色出图清单.md", "packaging", "episode", ["ProjectBible"], True), render_character_output_list(source, bible, episode_plan)),
        (artifact(paths.packaging_dir / f"23_{pn}{label}场景出图清单.md", "packaging", "episode", ["ShotPlan"], True), render_scene_output_list(source, episode_plan, shots)),
        (artifact(paths.packaging_dir / f"24A_{pn}{label}视频导演准备运行手册.md", "director_runbook", "episode", ["EpisodePlan", "ShotPlan"], True), render_video_director_runbook(source, paths, episode_plan, shots)),
        (artifact(paths.execution_dir / f"24_{pn}{label}Seedance2.0逐镜头执行表.md", "execution", "episode", ["ShotPlan"], True), render_seedance_table(source, episode_plan, shots)),
        (artifact(paths.execution_dir / f"25_{pn}{label}Seedance2.0最终提示词包.md", "execution", "episode", ["ShotPlan"], True), render_final_prompt_pack(source, bible, episode_plan, shots)),
        (artifact(paths.execution_dir / f"26_{pn}提示词字段映射研究.md", "mapping", "project", ["ProjectBible", "EpisodePlan"], True), render_field_mapping(source, episode_plan)),
        (artifact(paths.execution_dir / "31_prompt_adapter_interface_v1.md", "adapter", "project", ["RecordSchema"], True), build_adapter_interface(pn)),
        (artifact(paths.execution_dir / scene_detail_ref, "scene_detail", "episode", ["ShotPlan", "ProjectBible"], True), render_scene_detail_txt(scene_detail_map)),
        (artifact(paths.character_assets_dir / "README.md", "character_assets", "project", ["ProjectBible"], True), build_character_reference_readme(pn, bible.characters, paths.character_assets_dir, paths.novel_dir / "character_image_map.json", args.character_image_ext)),
    ]
    for character in bible.characters:
        profile = build_character_profile_md(bible.setting, character)
        text_specs.append((artifact(paths.character_assets_dir / f"{character.character_id}.prompt.md", "character_assets", "project", ["ProjectBible"], True), build_character_reference_prompt(bible.setting, character, args.character_image_ext, profile)))
        text_specs.append((artifact(paths.character_assets_dir / f"{character.character_id}.profile.md", "character_assets", "project", ["ProjectBible"], True), profile))

    project_id = f"{pn}_{episode_plan.episode_id}"
    experiment_id = f"exp_{pn.lower()}_{episode_plan.episode_id.lower()}_draft"
    json_specs: list[tuple[ArtifactSpec, dict[str, Any]]] = [
        (artifact(paths.structure_dir / "project_bible_v1.json", "intermediate", "project", ["ProjectBible"], True), to_jsonable(bible)),
        (artifact(paths.script_dir / f"episode_plan_{episode_plan.episode_id}_v1.json", "intermediate", "episode", ["EpisodePlan"], True), to_jsonable(episode_plan)),
        (artifact(paths.execution_dir / "27_prompt_schema_v1.json", "schema", "project", ["RecordSchema"], True), build_prompt_schema(pn, episode_plan.episode_id)),
        (artifact(paths.execution_dir / "28_prompt_record_template_v1.json", "schema", "project", ["RecordSchema"], True), build_record_template(pn, episode_plan.episode_id, args.platform)),
        (artifact(paths.execution_dir / "29_prompt_episode_manifest_v1.json", "manifest", "episode", ["ShotPlan"], True), build_manifest(pn, source.title, episode_plan, shots, args.platform, bible.core_selling_points)),
        (artifact(paths.execution_dir / "30_model_capability_profiles_v1.json", "schema", "project", ["ModelProfile"], True), build_model_profiles(pn)),
        (artifact(paths.execution_dir / "35_character_lock_profiles_v1.json", "character_lock", "project", ["ProjectBible"], True), build_character_lock_profiles(pn, bible.characters)),
        (artifact(paths.novel_dir / "character_image_map.json", "character_assets", "project", ["ProjectBible"], True), build_character_image_map(bible.characters, paths.character_assets_dir, args.character_image_ext, include_aliases=not args.no_character_map_aliases)),
    ]
    for character in bible.characters:
        json_specs.append((artifact(paths.character_assets_dir / f"{character.character_id}.info.json", "character_assets", "project", ["ProjectBible"], True), build_character_info_payload(bible.setting, character)))
    for shot in shots:
        json_specs.append(
            (
                artifact(paths.records_dir / f"{episode_plan.episode_id}_{shot.shot_id}_record.json", "record", "episode", ["EpisodePlan", "ShotPlan"], True),
                build_record(
                    project_id,
                    episode_plan,
                    args.platform,
                    bible.setting,
                    bible.core_selling_points,
                    bible.language_policy,
                    source.text,
                    bible.characters,
                    shot,
                    experiment_id,
                    scene_detail_ref,
                    scene_detail_map.get(shot.scene_name, ""),
                ),
            )
        )
    return text_specs, json_specs


def project_specific_contents(
    text_specs: list[tuple[ArtifactSpec, str]],
    json_specs: list[tuple[ArtifactSpec, dict[str, Any]]],
) -> dict[str, str]:
    contents: dict[str, str] = {}
    for spec, content in text_specs:
        if spec.project_specific:
            contents[str(spec.path)] = content
    for spec, data in json_specs:
        if spec.project_specific:
            contents[str(spec.path)] = json.dumps(data, ensure_ascii=False, indent=2)
    return contents


def run_plan_qa(
    source: ProjectSource,
    bible: ProjectBible,
    episode_plan: EpisodePlan,
    shots: list[ShotPlan],
    text_specs: list[tuple[ArtifactSpec, str]],
    json_specs: list[tuple[ArtifactSpec, dict[str, Any]]],
    llm_result: LLMRunResult,
    expected_episode_shot_count: int | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    contents = project_specific_contents(text_specs, json_specs)
    residual_terms = ["SampleChapter", "穿越", "乞丐", "破庙", "县令"]
    placeholder_patterns = ["待精修", "目标 / 冲突 / 情绪点", "TODO", "TBD"]
    source_text = source.text

    for path, content in contents.items():
        for term in residual_terms:
            if term in source_text or term in source.project_name or term in source.title or term in source.novel_path:
                continue
            if term in content:
                findings.append({"severity": "high", "issue": "residual_sample_content", "path": path, "term": term})
        for pattern in placeholder_patterns:
            if pattern in content:
                findings.append({"severity": "high", "issue": "placeholder_content", "path": path, "pattern": pattern})

    if episode_plan.episode_number != 1:
        for spec, content in text_specs:
            if spec.scope == "episode" and ("第1集" in spec.path.name or "第1集" in content):
                findings.append({"severity": "high", "issue": "episode_label_mismatch", "path": str(spec.path), "expected": episode_plan.episode_label})

    episode_outline_count = len(bible.episode_outlines)
    expected_episode_outline_count = len(extract_numbered_chapter_titles(source.text)) if "银座" in source.text and "佐藤彩花" in source.text else episode_outline_count
    if expected_episode_outline_count and episode_outline_count != expected_episode_outline_count:
        findings.append({"severity": "high", "issue": "episode_outline_count", "count": episode_outline_count, "expected": expected_episode_outline_count})

    record_required = {
        "record_header",
        "global_settings",
        "project_meta",
        "language_policy",
        "emotion_arc",
        "character_anchor",
        "scene_anchor",
        "shot_execution",
        "scene_motion_contract",
        "dialogue_language",
        "prompt_render",
        "continuity_rules",
        "qa_rules",
        "artifacts",
    }
    record_count = 0
    last_shot_id = f"SH{int(expected_episode_shot_count or len(shots)):02d}" if shots else ""
    for shot in shots:
        combined = " ".join(
            [
                shot.intent,
                shot.scene_name,
                shot.framing_focus,
                shot.action_intent,
                shot.positive_core,
            ]
        )
        for placeholder in GENERIC_SHOT_PLACEHOLDERS:
            if placeholder in combined:
                findings.append(
                    {
                        "severity": "high",
                        "issue": "generic_shot_placeholder",
                        "shot_id": shot.shot_id,
                        "placeholder": placeholder,
                    }
                )
        if llm_result.applied and not shot.source_basis:
            findings.append({"severity": "medium", "issue": "llm_shot_missing_source_basis", "shot_id": shot.shot_id})

    for spec, data in json_specs:
        if spec.category != "record":
            continue
        record_count += 1
        shot_id = str(data.get("record_header", {}).get("shot_id", "")).strip().upper() if isinstance(data, dict) else ""
        missing = sorted(record_required - set(data.keys()))
        if missing:
            findings.append({"severity": "high", "issue": "record_missing_required_fields", "path": str(spec.path), "missing": missing})
        language_policy = data.get("language_policy", {}) if isinstance(data, dict) else {}
        dialogue_language = data.get("dialogue_language", {}) if isinstance(data, dict) else {}
        if not isinstance(language_policy, dict) or language_policy.get("spoken_language") != DEFAULT_LANGUAGE_POLICY["spoken_language"]:
            findings.append({"severity": "high", "issue": "language_policy_missing_or_wrong", "path": str(spec.path), "expected": DEFAULT_LANGUAGE_POLICY["spoken_language"]})
        if not isinstance(dialogue_language, dict) or dialogue_language.get("voice_language_lock") != DEFAULT_LANGUAGE_POLICY["voice_language_lock"]:
            findings.append({"severity": "high", "issue": "voice_language_lock_missing_or_wrong", "path": str(spec.path)})
        validate_dialogue_visibility_record(data, str(spec.path), findings)
        validate_i2v_prompt_design_record(data, str(spec.path), findings)
        scene_anchor = data.get("scene_anchor", {}) if isinstance(data, dict) else {}
        if isinstance(scene_anchor, dict):
            scene_detail = str(scene_anchor.get("scene_detail") or "").strip()
            if not scene_anchor.get("scene_detail_ref") or not scene_anchor.get("scene_detail_key") or not scene_detail:
                findings.append({"severity": "high", "issue": "scene_detail_missing_from_record", "path": str(spec.path)})
            else:
                for character in bible.characters:
                    if character.name and character.name in scene_detail:
                        findings.append({"severity": "high", "issue": "scene_detail_contains_character_name", "path": str(spec.path), "character": character.name})
                for term in ("对白", "台词", "情绪", "关系推进", "角色动作"):
                    if term in scene_detail:
                        findings.append({"severity": "medium", "issue": "scene_detail_contains_non_environment_term", "path": str(spec.path), "term": term})
        if shot_id == last_shot_id:
            validate_episode_ending_hook_record(data, str(spec.path), findings)
        if episode_plan.episode_number == 1 and is_sample_chapter_source(source.text):
            source_trace = data.get("source_trace", {}) if isinstance(data, dict) else {}
            truth_contract = source_trace.get("story_truth_contract", {}) if isinstance(source_trace, dict) else {}
            if not truth_contract:
                findings.append({"severity": "high", "issue": "missing_story_truth_contract", "path": str(spec.path)})
            scene_anchor = data.get("scene_anchor", {}) if isinstance(data, dict) else {}
            prompt_render = data.get("prompt_render", {}) if isinstance(data, dict) else {}
            prop_must_visible = scene_anchor.get("prop_must_visible", []) if isinstance(scene_anchor, dict) else []
            must_have = scene_anchor.get("must_have_elements", []) if isinstance(scene_anchor, dict) else []
            prompt_text = str(prompt_render.get("shot_positive_core", "")) if isinstance(prompt_render, dict) else ""
            if shot_id in {"SH05", "SH06", "SH07"}:
                if "稀粥" not in prop_must_visible:
                    findings.append({"severity": "high", "issue": "missing_required_story_prop", "path": str(spec.path), "prop": "稀粥"})
                positive_subject = prompt_text.split("禁止误读：", 1)[0]
                if "药" in positive_subject and "不是药" not in prompt_text:
                    findings.append({"severity": "high", "issue": "medicine_drift_risk", "path": str(spec.path)})
            if shot_id in {"SH10", "SH11", "SH12", "SH13"}:
                if "溪边盐渍" not in prop_must_visible:
                    findings.append({"severity": "high", "issue": "missing_required_story_prop", "path": str(spec.path), "prop": "溪边盐渍"})
                if "盐渍" not in prompt_text:
                    findings.append({"severity": "high", "issue": "missing_salt_truth_in_prompt", "path": str(spec.path)})
            if shot_id in {"SH02", "SH03", "SH04"}:
                if not any("饥饿" in str(item) or "快饿死" in str(item) for item in must_have + [prompt_text]):
                    findings.append({"severity": "medium", "issue": "missing_hunger_state_anchor", "path": str(spec.path)})
            forbidden_prompt_terms = ["武侠侠客感", "江湖疗伤", "包扎腿伤", "毒药粉末"]
            negative_terms = prompt_render.get("negative_prompt", []) if isinstance(prompt_render, dict) else []
            for term in forbidden_prompt_terms:
                if term not in negative_terms:
                    findings.append({"severity": "medium", "issue": "missing_forbidden_drift_term", "path": str(spec.path), "term": term})
    if record_count != len(shots):
        findings.append({"severity": "high", "issue": "record_count_mismatch", "records": record_count, "shots": len(shots)})

    image_map = next((data for spec, data in json_specs if spec.path.name == "character_image_map.json"), {})
    for character in bible.characters:
        for key in (character.character_id, character.name, character.lock_profile_id):
            if key not in image_map:
                findings.append({"severity": "medium", "issue": "character_image_map_missing_key", "key": key})

    if llm_result.fallbacks:
        for fallback in llm_result.fallbacks:
            findings.append({"severity": "info", "issue": "llm_fallback", **fallback})

    blocking = [item for item in findings if item.get("severity") in {"high", "medium"}]
    return {
        "created_at": date.today().isoformat(),
        "project": source.project_name,
        "episode_id": episode_plan.episode_id,
        "checks": {
            "project_specific_files": len(contents),
            "episode_outline_count": episode_outline_count,
            "expected_episode_outline_count": expected_episode_outline_count,
            "shot_count": len(shots),
            "record_count": record_count,
            "llm_backend": llm_result.backend,
            "llm_applied": llm_result.applied,
            "llm_request_files": llm_result.request_files,
        },
        "findings": findings,
        "pass": len(blocking) == 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a novel-to-video planning bundle under novel/.")
    parser.add_argument("--novel", required=True, help="Path to source novel markdown.")
    parser.add_argument("--project-name", default="", help="Project name, e.g. GinzaNight. Defaults to novel parent/file stem.")
    parser.add_argument("--project-title", default="", help="Human title. Defaults to first markdown heading or filename.")
    parser.add_argument("--episode", default="EP01", help="Episode id, default EP01.")
    parser.add_argument("--shots", type=int, default=13, help="Number of episode shots to draft.")
    parser.add_argument("--platform", default="douyin", help="Platform target, default douyin.")
    parser.add_argument("--out", default="", help="Output dir under novel/. Absolute path is allowed only if still under novel/.")
    parser.add_argument("--character-image-ext", default="jpg", help="Expected character reference image extension, default jpg.")
    parser.add_argument("--no-character-map-aliases", action="store_true", help="Only map character_id keys. By default name and lock_profile_id aliases are included too.")
    parser.add_argument("--backend", choices=["heuristic", "llm"], default="heuristic", help="Generation backend. heuristic is offline and default.")
    parser.add_argument("--llm-provider", default="openai", help="LLM provider name for request previews.")
    parser.add_argument("--llm-model", default="gpt-5.5", help="LLM model name for request previews/live planning.")
    parser.add_argument("--llm-api-key-env", default="OPENAI_API_KEY", help="Environment variable name for LLM API key.")
    parser.add_argument("--llm-base-url", default="https://api.openai.com/v1", help="OpenAI-compatible API base URL for live LLM planning.")
    parser.add_argument("--llm-reasoning-effort", default="high", choices=["none", "low", "medium", "high", "xhigh"], help="Reasoning effort for OpenAI Responses API.")
    parser.add_argument("--llm-max-output-tokens", type=int, default=20000, help="Max output tokens per LLM planning step.")
    parser.add_argument("--llm-timeout-sec", type=int, default=240, help="HTTP timeout per LLM planning step.")
    parser.add_argument("--llm-shot-mode", choices=["per-shot", "episode"], default="per-shot", help="LLM shot payload mode. per-shot calls the model once for each SHxx and passes SH(n-1) into SHn.")
    parser.add_argument("--llm-only-shot", default="", help="With --llm-shot-mode per-shot, generate only one shot such as SH01. SHn still receives SH(n-1) context when available.")
    parser.add_argument("--llm-dry-run", action="store_true", help="Only write LLM request previews; keep heuristic output.")
    parser.add_argument("--qa-strict", action="store_true", help="Return non-zero when planning QA has blocking findings.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing generated files.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned output without writing files.")
    return parser.parse_args()


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, str]:
    novel_path = Path(args.novel).expanduser()
    if not novel_path.is_absolute():
        novel_path = (REPO_ROOT / novel_path).resolve()
    else:
        novel_path = novel_path.resolve()
    if not novel_path.exists():
        raise FileNotFoundError(f"novel not found: {novel_path}")
    if novel_path.suffix.lower() != ".md":
        raise ValueError(f"novel must be a markdown file: {novel_path}")
    if not is_relative_to(novel_path, NOVEL_ROOT.resolve()):
        raise ValueError(f"novel must live under {NOVEL_ROOT}: {novel_path}")

    project_name = safe_filename_name(args.project_name.strip() or slug_to_pascal(novel_path.parent.name or novel_path.stem))
    if args.out.strip():
        out_dir = Path(args.out).expanduser()
        if not out_dir.is_absolute():
            out_dir = (NOVEL_ROOT / out_dir).resolve()
        else:
            out_dir = out_dir.resolve()
    else:
        out_dir = (novel_path.parent / f"{project_name}_项目文件整理版").resolve()
    if not is_relative_to(out_dir, NOVEL_ROOT.resolve()):
        raise ValueError(f"output dir must stay under {NOVEL_ROOT}: {out_dir}")
    return novel_path, out_dir, project_name


def main() -> int:
    args = parse_args()
    try:
        novel_path, out_dir, project_name = resolve_paths(args)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    source = load_project_source(novel_path, project_name, args.project_title)
    paths = project_paths(out_dir, novel_path.parent.resolve())
    initial_characters = detect_characters(source.text)
    llm_request_files: list[str] = []
    llm_fallbacks: list[dict[str, str]] = []
    characters = run_llm_character_catalog(
        args,
        paths,
        source,
        initial_characters,
        args.overwrite,
        args.dry_run,
        llm_request_files,
        llm_fallbacks,
    )
    bible = build_project_bible(source, args.platform, characters)
    episode_id = args.episode.strip().upper() or "EP01"
    episode_plan = build_episode_plan(bible, episode_id)
    shot_count = max(1, min(50, int(args.shots)))
    shots = build_shot_plan(source, bible, episode_plan, shot_count)

    print(f"[INFO] novel: {novel_path}")
    print(f"[INFO] output: {out_dir}")
    print(f"[INFO] project: {project_name} / {source.title} / {episode_plan.episode_id}")
    print(f"[INFO] backend: {args.backend}")
    if args.dry_run:
        print("[INFO] dry-run only; no files will be written.")

    for directory in (
        paths.method_dir,
        paths.template_dir,
        paths.input_dir,
        paths.structure_dir,
        paths.script_dir,
        paths.execution_dir,
        paths.packaging_dir,
        paths.records_dir,
        paths.character_assets_dir,
    ):
        if not args.dry_run:
            directory.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    written.extend(copy_common_docs(paths, args.overwrite, args.dry_run))

    episode_plan, shots, llm_result = run_llm_backend(
        args,
        paths,
        source,
        bible,
        episode_plan,
        shots,
        args.overwrite,
        args.dry_run,
        llm_request_files,
        llm_fallbacks,
    )
    text_specs, json_specs = render_artifacts(paths, source, bible, episode_plan, shots, args)
    qa_report = run_plan_qa(source, bible, episode_plan, shots, text_specs, json_specs, llm_result, shot_count)
    json_specs.append((artifact(paths.out_dir / "plan_qa_report.json", "qa", "project", ["ProjectBible", "EpisodePlan", "ShotPlan"], True), qa_report))

    for spec, content in text_specs:
        if args.dry_run:
            print(f"[DRY] write {spec.path}")
            written.append(str(spec.path))
        elif write_text(spec.path, content, args.overwrite):
            written.append(str(spec.path))

    for spec, data in json_specs:
        if args.dry_run:
            print(f"[DRY] write {spec.path}")
            written.append(str(spec.path))
        elif write_json(spec.path, data, args.overwrite):
            written.append(str(spec.path))

    print(f"[INFO] planned/written files: {len(written)}")
    print(f"[INFO] planning QA pass: {qa_report['pass']} findings={len(qa_report['findings'])}")
    if not args.dry_run:
        print(f"[INFO] done: {out_dir}")
    if args.qa_strict and not qa_report["pass"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
