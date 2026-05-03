#!/usr/bin/env python3
"""Create a video planning bundle from an existing screen script.

This planner treats the screen script as the source of truth. It parses the
episode title, scene blocks, visual beats, dialogue, music cues, and hooks, then
normalizes them into the same bundle shape consumed by the existing director,
keyframe, Seedance, assembly, and QA scripts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import novel2video_plan as n2v
import character_location_tracker as clt
import source_selection_planner as ssp

try:
    import requests
except Exception:  # pragma: no cover - optional live semantic pass dependency.
    requests = None


REPO_ROOT = Path(__file__).resolve().parents[1]
SCREEN_ROOT = REPO_ROOT / "screen_script"
DEFAULT_MAX_SHOTS = 18
XAI_CHAT_COMPLETIONS_URL = "https://api.x.ai/v1/chat/completions"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_GROK_SEMANTIC_MODELS = ["grok-4-fast-reasoning", "grok-3-fast", "grok-3"]
DEFAULT_OPENAI_SEMANTIC_MODEL = "gpt-4.1-mini"


KNOWN_CHARACTER_SPECS: dict[str, tuple[str, str, str, list[str], list[str]]] = {
    "沈念歌": (
        "SHEN_NIANGE_MAIN",
        "SHEN_NIANGE_MAIN_LOCK_V1",
        "26岁年轻母亲，清瘦坚韧，低马尾，洗得发白的白色短袖T恤，眼神温柔但警惕，衣着朴素干净",
        ["隐忍", "护子", "自尊", "警觉"],
        ["克制", "短句", "先压住情绪再开口"],
    ),
    "沈知予": (
        "SHEN_ZHIYU_CHILD",
        "SHEN_ZHIYU_CHILD_LOCK_V1",
        "4岁半小男孩，蓝色牛仔背带裤，小虎牙，眼睛像陆景琛，聪明认真，非情色化儿童角色。别名：予予",
        ["天真", "聪明", "想找爸爸", "保护妈妈"],
        ["奶声奶气", "认真", "童言直给"],
    ),
    "予予": (
        "SHEN_ZHIYU_CHILD",
        "SHEN_ZHIYU_CHILD_LOCK_V1",
        "4岁半小男孩，蓝色牛仔背带裤，小虎牙，眼睛像陆景琛，聪明认真，非情色化儿童角色。别名：沈知予、予予",
        ["天真", "聪明", "想找爸爸", "保护妈妈"],
        ["奶声奶气", "认真", "童言直给"],
    ),
    "陆景琛": (
        "LU_JINGCHEN_MAIN",
        "LU_JINGCHEN_MAIN_LOCK_V1",
        "30岁左右集团总裁，深灰色定制西装，冷峻五官，剑眉深眼窝，克制强势",
        ["冷静", "掌控欲", "被亲子真相震动", "压住情绪"],
        ["低沉", "短句", "命令式"],
    ),
    "赵一鸣": (
        "ZHAO_YIMING_ASSISTANT",
        "ZHAO_YIMING_ASSISTANT_LOCK_V1",
        "30岁左右总裁秘书，藏青色职业西装，手持黑色平板电脑，反应快，谨慎观察陆景琛情绪",
        ["执行力", "谨慎", "职业化"],
        ["简短", "汇报式", "小心翼翼"],
    ),
    "林雨薇": (
        "LIN_YUWEI_RIVAL",
        "LIN_YUWEI_RIVAL_LOCK_V1",
        "年轻女性，晚礼服或精致日常装，笑容甜美但眼神有算计",
        ["伪善", "嫉妒", "设计他人"],
        ["甜腻", "试探", "装无辜"],
    ),
    "苏晚": (
        "SU_WAN_FRIEND",
        "SU_WAN_FRIEND_LOCK_V1",
        "沈念歌朋友，年轻职场女性，亲切直爽，日常通勤装，表情热心",
        ["义气", "八卦", "保护朋友"],
        ["轻快", "直白", "关心"],
    ),
    "周雅琳": (
        "ZHOU_YALIN_MANAGER",
        "ZHOU_YALIN_MANAGER_LOCK_V1",
        "行政主管，精致职业装，眼神挑剔，姿态有职场压迫感",
        ["挑剔", "势利", "控制下属"],
        ["挑刺", "冷淡", "命令式"],
    ),
}

EPHEMERAL_TOKENS = (
    "服务员",
    "侍者",
    "保安",
    "前台",
    "老师",
    "医生",
    "护士",
    "管家",
    "风衣妈妈",
    "闺蜜",
    "小男孩",
    "高管",
    "助理",
    "保镖",
    "同事",
    "西装男人",
    "部门经理",
    "人群",
    "客人",
    "路人",
)

EPHEMERAL_GROUP_TOKENS = ("人群", "客人", "路人", "围观")

IMPORTANT_PROP_KEYWORDS = {
    "按钮": "BUTTON_01",
    "果汁": "JUICE_CUPS_02",
    "杯子": "CUP_01",
    "杯": "CUP_01",
    "DNA报告": "DNA_REPORT_01",
    "报告": "DOCUMENT_REPORT_01",
    "简报": "DOCUMENT_REPORT_01",
    "电脑屏幕": "COMPUTER_SCREEN_01",
    "牛皮纸信封": "KRAFT_ENVELOPE_01",
    "信封": "KRAFT_ENVELOPE_01",
    "手机": "SMARTPHONE_01",
    "验孕棒": "PREGNANCY_TEST_STICK_01",
    "照片": "PHOTO_01",
    "画": "CHILD_DRAWING_01",
    "全家福": "FAMILY_DRAWING_01",
    "文件": "DOCUMENT_01",
    "档案袋": "DOCUMENT_FILE_01",
    "档案": "DOCUMENT_FILE_01",
    "入职通知书": "DOCUMENT_NOTICE_01",
    "挂号单": "HOSPITAL_REGISTRATION_SLIP_01",
    "饼干": "COOKIE_PACK_01",
    "儿童餐": "KIDS_MEAL_01",
    "炸鸡": "FRIED_CHICKEN_01",
    "咖啡": "COFFEE_CUP_01",
    "平板": "TABLET_01",
}

PROP_HANDOFF_ACTION_KEYWORDS = (
    "接过",
    "递给",
    "递来",
    "递出",
    "递",
    "交给",
    "拿过",
    "拿起",
    "拿着",
    "端起",
    "端着",
    "喝",
    "饮",
    "放下",
)

PROP_HANDOFF_GENERIC_REPLACEMENTS = {
    "JUICE_CUPS_02": {"CUP_01"},
}

PROP_HANDOFF_STATE_DEFAULTS = {
    "JUICE_CUPS_02": "果汁杯中有浅橙色或透明果汁，不是空杯",
}

PROP_HANDOFF_PROMPT_REWRITES = {
    "JUICE_CUPS_02": "果汁杯，杯中果汁可见，不是空杯",
}

LARGE_SCENE_ELEMENT_KEYWORDS = {
    "公交车": "停靠公交车",
    "车门": "打开的公交车门",
    "医院大门": "医院入口大门",
    "VIP区门": "VIP区大门",
    "金色的门": "VIP区金色大门",
    "大门": "建筑大门",
    "房门": "房门结构",
    "门": "门/入口结构",
    "车": "车辆环境元素",
    "沙发": "固定家具沙发",
    "柜台": "固定服务柜台",
    "楼梯": "建筑楼梯",
    "电梯门": "电梯门结构",
}

LARGE_SCENE_PROP_ID_TOKENS = ("DOOR_PANEL", "VEHICLE_DOOR", "BUS", "CAR_DOOR", "ELEVATOR_DOOR")
LARGE_SCENE_ELEMENT_TEXT_TOKENS = ("门", "车", "公交车", "大门", "车门", "房门", "电梯门", "柜台", "沙发", "楼梯")

EPHEMERAL_CHARACTER_SPECS: dict[str, tuple[str, str]] = {
    "服务员": ("EXTRA_WAITER", "酒店或宴会服务员，整洁制服，普通工作人员气质"),
    "侍者": ("EXTRA_WAITER", "酒店或宴会服务员，整洁制服，普通工作人员气质"),
    "保安": ("EXTRA_SECURITY", "现代写字楼或医院保安，深色制服，维持秩序"),
    "前台": ("EXTRA_FRONT_DESK", "现代公司前台，职业套装，礼貌但势利或疏离"),
    "老师": ("EXTRA_TEACHER", "幼儿园老师，简洁职业装，亲和但紧张"),
    "医生": ("EXTRA_DOCTOR", "医院医生，白大褂，职业化表达"),
    "护士": ("EXTRA_NURSE", "医院护士，浅色制服，职业化表达"),
    "管家": ("EXTRA_HOUSEKEEPER", "豪门管家或酒店管理者，深色正装，克制疏离"),
    "风衣妈妈": ("EXTRA_PARENT", "幼儿园家长，精致风衣，带阶层优越感"),
    "小男孩": ("EXTRA_CHILD", "幼儿园小男孩，普通儿童日常服，非情色化安全呈现"),
    "西装男人": ("EXTRA_BUSINESSMAN", "写字楼临时商务男士，深色西装，只作为电梯或会议环境功能人物"),
    "部门经理": ("EXTRA_DEPARTMENT_MANAGER", "会议室临时部门经理，深色商务装，只作为汇报功能人物"),
    "闺蜜": ("EXTRA_FRIEND_PARENT", "幼儿园家长的临时闺蜜，现代都市日常精致穿搭，只作为旁侧听众或短暂反应人物"),
}

BACKGROUND_GROUP_LISTENER_TOKENS = (
    "大家",
    "众人",
    "人群",
    "围观",
    "路人",
    "孩子们",
    "小朋友们",
    "全班孩子",
    "同学们",
    "家长们",
    "其他家长",
    "同班家长",
    "宾客",
    "客人们",
    "all in room",
    "everyone in room",
    "all_children_and_parents",
    "all_children",
    "all_parents",
    "class_group",
    "children_group",
    "parents_group",
    "background_group",
    "classmates",
)


@dataclass
class ScriptLine:
    line_no: int
    kind: str
    text: str
    scene_name: str = ""
    scene_id: str = ""
    shot_type: str = ""
    speaker: str = ""
    performance: str = ""


@dataclass
class ParsedScript:
    script_path: Path
    episode_id: str
    episode_number: int
    title: str
    keywords: list[str]
    selling_point: str
    recap: str
    hook: str
    preview: str
    lines: list[ScriptLine] = field(default_factory=list)
    scene_names: list[str] = field(default_factory=list)


@dataclass
class ShotDraft:
    shot_id: str
    scene_name: str
    scene_id: str
    shot_type: str
    visual_texts: list[str]
    dialogue: list[dict[str, Any]]
    music: list[str]
    line_start: int
    line_end: int
    source_excerpt: str
    parent_scene_name: str = ""
    parent_scene_id: str = ""
    shot_context_excerpt: str = ""
    shot_location_basis: str = ""
    shot_location_excerpt: str = ""
    shot_location_candidates: list[dict[str, str]] = field(default_factory=list)
    selection_plan: dict[str, Any] = field(default_factory=dict)


def parse_episode_token(token: str) -> int:
    match = re.fullmatch(r"(?:EP)?(\d{1,3})", token.strip().upper())
    if not match:
        raise ValueError(f"invalid episode token: {token!r}")
    return int(match.group(1))


def episode_id_from_number(number: int) -> str:
    return f"EP{number:02d}"


def safe_slug(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", str(value or "").strip())
    text = re.sub(r"\s+", "_", text).strip("._ ")
    return text or fallback


def screen_project_root(script_path: Path, script_dir_arg: str = "") -> Path:
    if script_dir_arg.strip():
        script_dir = resolve_repo_path(script_dir_arg)
        if script_dir.name in {"归档", "archive", "archives"}:
            return script_dir.parent
        return script_dir
    parent = script_path.parent
    if parent.name in {"归档", "archive", "archives"}:
        return parent.parent
    return parent


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


def split_meta_list(value: str) -> list[str]:
    value = re.sub(r"[>*`#]", "", value).strip()
    value = re.sub(r"^本集[^：:]*[：:]\s*", "", value).strip()
    parts = [item.strip(" ，,、") for item in re.split(r"[、,，/|]", value) if item.strip(" ，,、")]
    return parts or ([value] if value else [])


def normalize_scene_name(raw: str) -> str:
    text = re.sub(r"\s+", "", raw.strip())
    text = text.replace("外景·", "").replace("内景·", "")
    return text or "未命名场景"


LOCAL_SCENE_RULES: tuple[tuple[str, str, str, int], ...] = (
    ("档案室", "三十二楼档案室·日", "records_room", 98),
    ("灰色的格子间", "三十二楼行政部办公区·日", "admin_office", 97),
    ("行政部。一片灰色", "三十二楼行政部办公区·日", "admin_office", 96),
    ("档案柜", "三十二楼行政部办公区·日", "admin_office", 94),
    ("幼儿园面试", "幼儿园教室（面试现场）", "kindergarten_interview", 100),
    ("教室门口", "幼儿园教室门口", "kindergarten_classroom", 95),
    ("幼儿园教室", "幼儿园教室", "kindergarten_classroom", 94),
    ("幼儿园门口", "幼儿园门口", "kindergarten_gate", 93),
    ("幼儿园对面", "幼儿园对面黑色轿车内/车旁", "black_car_near_kindergarten", 99),
    ("黑色轿车", "幼儿园对面黑色轿车内/车旁", "black_car_near_kindergarten", 99),
    ("驾驶座", "黑色轿车驾驶座", "black_car_driver_seat", 98),
    ("公交车门", "公交车门口/上车处", "bus_boarding", 96),
    ("上了车", "公交车门口/上车处", "bus_boarding", 95),
    ("上车", "公交车门口/上车处", "bus_boarding", 94),
    ("公交车来了", "幼儿园门口/路边公交站", "bus_stop_exterior", 93),
    ("公交车停靠", "幼儿园门口/路边公交站", "bus_stop_exterior", 92),
    ("坐公交车", "公交车内", "bus_interior", 90),
    ("公交车内", "公交车内", "bus_interior", 89),
    ("车上", "公交车内", "bus_interior", 86),
    ("菜市场", "菜市场·清晨", "market", 80),
    ("妇幼保健院门口", "某小城市妇幼保健院门口·日", "hospital_gate", 78),
    ("医院门口", "医院门口", "hospital_gate", 76),
    ("大堂", "大堂", "lobby", 72),
    ("会议室", "会议室", "conference_room", 70),
    ("电梯", "电梯内", "elevator", 68),
    ("出租屋", "出租屋·深夜", "rental_room", 60),
)


GENERIC_PARENT_SCENE_TOKENS = ("蒙太奇", "不同城市辗转", "快速剪辑")


def parent_scene_is_generic(scene_name: str) -> bool:
    text = str(scene_name or "")
    return any(token in text for token in GENERIC_PARENT_SCENE_TOKENS)


def local_scene_candidates_for_line(line: ScriptLine) -> list[dict[str, str]]:
    text = str(line.text or "").strip()
    if not text:
        return []
    candidates: list[dict[str, str]] = []
    for token, scene_name, scene_class, priority in LOCAL_SCENE_RULES:
        if token not in text:
            continue
        if token == "电梯" and any(skip in text for skip in ("电梯的方向", "专用电梯", "普通的员工电梯", "金色电梯", "电梯门")):
            continue
        scene = scene_name
        if token == "菜市场" and "清晨" not in text:
            scene = "菜市场"
        if token == "出租屋" and "深夜" not in text:
            scene = "出租屋"
        candidates.append(
            {
                "scene_name": scene,
                "scene_class": scene_class,
                "basis": f"line {line.line_no}",
                "excerpt": text,
                "priority": str(priority),
            }
        )
    return candidates


def best_single_local_scene(candidates: list[dict[str, str]], allow_tie_break: bool) -> dict[str, str] | None:
    if not candidates:
        return None
    by_class = {str(item.get("scene_class") or "") for item in candidates if str(item.get("scene_class") or "")}
    if len(by_class) > 1 and not allow_tie_break:
        return None
    return sorted(candidates, key=lambda item: int(item.get("priority") or 0), reverse=True)[0]


def parse_dialogue(line: str) -> tuple[str, str, str] | None:
    match = re.match(r"^\*\*(.+?)\*\*(?:（(.+?)）)?\s*[：:]\s*[\"“]?(.+?)[\"”]?\s*$", line.strip())
    if not match:
        return None
    speaker = match.group(1).strip()
    performance = (match.group(2) or "").strip()
    text = match.group(3).strip().strip("\"“”")
    if not speaker or not text:
        return None
    return speaker, performance, text


def strip_visual_prefix(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text.startswith("△"):
        return None
    text = text.lstrip("△").strip()
    shot_type = ""
    match = re.match(r"^（(.+?)）\s*(.+)$", text)
    if match:
        shot_type = match.group(1).strip()
        text = match.group(2).strip()
    return shot_type, text


def parse_script(path: Path, episode_id: str) -> ParsedScript:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    episode_number = parse_episode_token(episode_id)
    title = path.stem
    keywords: list[str] = []
    selling_point = ""
    recap = ""
    hook = ""
    preview = ""
    current_scene = ""
    current_scene_id = ""
    parsed_lines: list[ScriptLine] = []
    scene_names: list[str] = []

    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# "):
            title = re.sub(r"^#\s*", "", line).strip()
            title = re.sub(r"^第[一二三四五六七八九十百0-9]+集[：:]\s*", "", title).strip() or title
            continue
        if "本集关键词" in line:
            keywords = split_meta_list(line)
            continue
        if "本集爽点" in line:
            selling_point = re.sub(r"^>\s*本集爽点[：:]\s*", "", line).strip()
            continue
        if "前情提要" in line:
            recap = re.sub(r"^>\s*前情提要[：:]\s*", "", line).strip()
            continue
        if "本集钩子" in line:
            hook = re.sub(r"^>\s*[🎣\s]*本集钩子[：:]\s*", "", line).strip()
            continue
        if "下集预告" in line:
            preview = re.sub(r"^>\s*[📺\s]*下集预告[：:]\s*", "", line).strip()
            continue
        scene_match = re.match(r"^\*\*场景[：:]\*\*\s*(.+)$", line)
        if scene_match:
            current_scene = normalize_scene_name(scene_match.group(1))
            current_scene_id = safe_slug(current_scene, f"SCENE_{len(scene_names) + 1:02d}")
            if current_scene not in scene_names:
                scene_names.append(current_scene)
            parsed_lines.append(ScriptLine(idx, "scene", current_scene, current_scene, current_scene_id))
            continue
        if line.startswith("♪"):
            parsed_lines.append(ScriptLine(idx, "music", line.lstrip("♪").strip(), current_scene, current_scene_id))
            continue
        visual = strip_visual_prefix(line)
        if visual is not None:
            shot_type, visual_text = visual
            if visual_text:
                parsed_lines.append(ScriptLine(idx, "visual", visual_text, current_scene, current_scene_id, shot_type=shot_type))
            continue
        dialogue = parse_dialogue(line)
        if dialogue is not None:
            speaker, performance, dialogue_text = dialogue
            parsed_lines.append(
                ScriptLine(idx, "dialogue", dialogue_text, current_scene, current_scene_id, speaker=speaker, performance=performance)
            )
            continue
        if not line.startswith(("---", "##", ">")) and current_scene:
            parsed_lines.append(ScriptLine(idx, "visual", line, current_scene, current_scene_id))

    return ParsedScript(
        script_path=path,
        episode_id=episode_id,
        episode_number=episode_number,
        title=title,
        keywords=keywords,
        selling_point=selling_point,
        recap=recap,
        hook=hook,
        preview=preview,
        lines=parsed_lines,
        scene_names=scene_names,
    )


def line_excerpt(script_path: Path, start: int, end: int) -> str:
    lines = script_path.read_text(encoding="utf-8").splitlines()
    start_idx = max(0, start - 1)
    end_idx = min(len(lines), end)
    return "\n".join(lines[start_idx:end_idx]).strip()


def line_context_excerpt(script_path: Path, start: int, end: int, before: int = 6, after: int = 6) -> str:
    lines = script_path.read_text(encoding="utf-8").splitlines()
    start_idx = max(0, start - 1 - before)
    end_idx = min(len(lines), end + after)
    return "\n".join(lines[start_idx:end_idx]).strip()


def numbered_line_context(script_path: Path, start: int, end: int, before: int, after: int) -> str:
    lines = script_path.read_text(encoding="utf-8").splitlines()
    start_line = max(1, start - before)
    end_line = min(len(lines), end + after)
    return "\n".join(f"{idx}: {lines[idx - 1]}" for idx in range(start_line, end_line + 1)).strip()


def load_dotenv(path: Path) -> None:
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


def sanitize_prompt_text(text: str) -> str:
    replacements = {
        "背影": "侧前方可见脸部的停顿姿态",
        "远去身影": "侧前方可见脸部的离开姿态",
        "背对": "面部转向画面外侧",
        "后侧": "背景远端",
        "背后": "背景方向",
        "照片里的": "旧影像中的",
        "照片里": "旧影像中",
        "打开电脑": "看着电脑",
        "散落": "分开放置",
        "散乱": "有序摆放",
        "零散": "少量固定",
        "若干": "固定数量",
        "几个": "固定数量",
    }
    cleaned = str(text or "").strip()
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"「.+?」", "不可读文字块", cleaned)
    cleaned = re.sub(r"\".+?\"", "不可读文字块", cleaned)
    return cleaned


def sanitize_semantic_quality(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for key, item in value.items():
        out[key] = sanitize_prompt_text(item) if isinstance(item, str) else item
    return out


def dialogue_source(text: str, performance: str) -> str:
    combined = f"{text} {performance}"
    if any(token in combined for token in ("画外音", "旁白", "voiceover", "voice-over")):
        return "voiceover"
    if any(token in combined for token in ("电话里", "语音", "电话那头", "手机里", "听筒里")):
        return "phone"
    if any(token in combined for token in ("广播", "门外传来", "门外响起", "画外声")):
        return "offscreen"
    return "onscreen"


def selection_policy_text(selection_plan: dict[str, Any] | None) -> str:
    if not isinstance(selection_plan, dict):
        return ""
    values: list[str] = []
    for key in ("dialogue_policy", "keyframe_moment", "summary", "story_function"):
        values.append(str(selection_plan.get(key) or ""))
    for key in ("i2v_risk_notes", "key_props", "must_include_evidence"):
        raw = selection_plan.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
    return " ".join(values)


def selection_marks_phone_remote(selection_plan: dict[str, Any] | None) -> bool:
    text = selection_policy_text(selection_plan).lower()
    return any(token in text for token in ("offscreen", "far-end", "remote", "远端", "画外", "不显示"))


def selection_keyframe_moment(selection_plan: dict[str, Any] | None) -> str:
    if not isinstance(selection_plan, dict):
        return ""
    return str(selection_plan.get("keyframe_moment") or "").strip()


def source_text_indicates_environment_photo(text: str) -> bool:
    return clt.source_text_indicates_environment_photo(text)


def prop_profile_or_id_is_photo(prop_id: Any, profile: Any = None, contract: Any = None) -> bool:
    profile_dict = profile if isinstance(profile, dict) else {}
    contract_dict = contract if isinstance(contract, dict) else {}
    text = " ".join(
        str(value or "")
        for value in [
            prop_id,
            profile_dict.get("display_name"),
            profile_dict.get("structure"),
            profile_dict.get("front_description"),
            profile_dict.get("back_description"),
            contract_dict.get("front_description"),
            contract_dict.get("back_description"),
        ]
    )
    return any(token in text for token in ("PHOTO", "照片", "相片", "photo", "photograph", "相纸"))


def add_environment_photo_scene_overlay(data: dict[str, Any]) -> None:
    first_frame = data.setdefault("first_frame_contract", {})
    if not isinstance(first_frame, dict):
        return
    scene_overlay = first_frame.setdefault("scene_overlay", {})
    if not isinstance(scene_overlay, dict):
        scene_overlay = {}
        first_frame["scene_overlay"] = scene_overlay
    required = scene_overlay.setdefault("required_elements", [])
    if isinstance(required, list) and "墙面或荣誉墙上的固定照片" not in required:
        required.append("墙面或荣誉墙上的固定照片")
    rules = scene_overlay.setdefault("physical_rules", [])
    if isinstance(rules, list):
        rule = "荣誉墙/墙上照片是环境陈设，不得变成人物手持照片或可移动纸张道具"
        if rule not in rules:
            rules.append(rule)


def scrub_handheld_photo_props_for_environment_context(data: dict[str, Any], raw_text: str) -> None:
    """Keep honor-wall photos as scene facts, not movable handheld photo props."""
    if not isinstance(data, dict) or not source_text_indicates_environment_photo(raw_text):
        return
    add_environment_photo_scene_overlay(data)
    i2v = data.get("i2v_contract")
    if not isinstance(i2v, dict):
        return
    library = i2v.get("prop_library") if isinstance(i2v.get("prop_library"), dict) else {}
    contracts = i2v.get("prop_contract") if isinstance(i2v.get("prop_contract"), list) else []
    remove_ids: set[str] = set()
    for contract in contracts:
        if not isinstance(contract, dict):
            continue
        prop_id = str(contract.get("prop_id") or "").strip()
        if not prop_id or prop_id.startswith("ENVIRONMENT_MOUNTED_PHOTO"):
            continue
        profile = library.get(prop_id, {}) if isinstance(library, dict) else {}
        if prop_profile_or_id_is_photo(prop_id, profile, contract):
            remove_ids.add(prop_id)
    for prop_id, profile in list(library.items()) if isinstance(library, dict) else []:
        if str(prop_id).startswith("ENVIRONMENT_MOUNTED_PHOTO"):
            continue
        if prop_profile_or_id_is_photo(prop_id, profile, {}):
            remove_ids.add(str(prop_id))
    if not remove_ids:
        return
    if isinstance(library, dict):
        i2v["prop_library"] = {
            prop_id: profile
            for prop_id, profile in library.items()
            if str(prop_id) not in remove_ids
        }
    i2v["prop_contract"] = [
        contract
        for contract in contracts
        if not (isinstance(contract, dict) and str(contract.get("prop_id") or "").strip() in remove_ids)
    ]
    first_frame = data.get("first_frame_contract")
    if isinstance(first_frame, dict) and isinstance(first_frame.get("key_props"), list):
        first_frame["key_props"] = [
            item
            for item in first_frame.get("key_props", [])
            if str(item or "").strip() not in remove_ids and not prop_profile_or_id_is_photo(item)
        ]
    source_trace = data.setdefault("source_trace", {})
    if isinstance(source_trace, dict):
        warnings = source_trace.setdefault("planning_warnings", [])
        if isinstance(warnings, list):
            warnings.append(
                {
                    "issue": "environment_photo_handheld_prop_removed",
                    "removed_prop_ids": sorted(remove_ids),
                    "policy": "wall/honor-board photos remain scene overlay, not handheld prop_contract",
                }
            )


def tracker_character_location_for_scene(location_state: dict[str, Any]) -> str:
    if not isinstance(location_state, dict):
        return ""
    locations = location_state.get("character_locations")
    if not isinstance(locations, dict):
        return ""
    visible_locations: list[str] = []
    for state in locations.values():
        if not isinstance(state, dict):
            continue
        if clt.normalize_visibility(state.get("visibility")) not in {"visible", "inherited"}:
            continue
        location = str(state.get("location") or "").strip()
        if location and location not in visible_locations:
            visible_locations.append(location)
    if len(visible_locations) == 1:
        return visible_locations[0]
    return ""


def tracker_location_more_specific(candidate: str, current: str) -> bool:
    cand = str(candidate or "").strip()
    cur = str(current or "").strip()
    if not cand:
        return False
    if not cur:
        return True
    if cand == cur:
        return False
    if any(token in cand for token in ("黑色轿车", "驾驶座", "车内")) and not any(token in cur for token in ("黑色轿车", "驾驶座", "车内")):
        return True
    specific_tokens = ("黑色轿车", "驾驶座", "车内", "公交车", "车门", "上车", "荣誉墙", "走廊")
    generic_tokens = ("幼儿园门口", "门口", "路边", "傍晚", "梧桐树下")
    return any(token in cand for token in specific_tokens) and any(token in cur for token in generic_tokens)


def normalize_selected_key_prop(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw in IMPORTANT_PROP_KEYWORDS:
        return IMPORTANT_PROP_KEYWORDS[raw]
    normalized = normalize_semantic_prop_id(raw)
    if normalized:
        return normalized
    for keyword, prop_id in IMPORTANT_PROP_KEYWORDS.items():
        if keyword in raw:
            return prop_id
    return raw


def draft_combined_text(draft: ShotDraft, context_text: str = "") -> str:
    dialogue_text = " ".join(
        f"{item.get('speaker', '')} {item.get('performance', '')} {item.get('text', '')}"
        for item in draft.dialogue
        if isinstance(item, dict)
    )
    return " ".join([draft.source_excerpt, " ".join(draft.visual_texts), dialogue_text, context_text])


def is_document_screen_detail_text(text: str) -> bool:
    raw = str(text or "")
    if not raw:
        return False
    return (
        ("屏幕上是一份简报" in raw)
        or ("（特写）屏幕" in raw and "简报" in raw)
        or ("电脑屏幕上是" in raw and any(token in raw for token in ("简报", "报告", "邮件")))
    )


def is_document_screen_detail_draft(draft: ShotDraft, context_text: str = "") -> bool:
    if draft.dialogue:
        return False
    return is_document_screen_detail_text(draft_combined_text(draft, context_text))


def phone_speaker_can_be_visible(draft: ShotDraft, context_text: str = "") -> bool:
    text = draft_combined_text(draft, context_text)
    return any(token in text for token in ("视频通话", "屏幕里", "屏幕中", "画面上出现", "监控截图"))


def remote_phone_speakers(draft: ShotDraft, context_text: str = "") -> set[str]:
    if phone_speaker_can_be_visible(draft, context_text):
        return set()
    return {
        str(item.get("speaker") or "").strip()
        for item in draft.dialogue
        if isinstance(item, dict)
        and str(item.get("source") or "onscreen") == "phone"
        and str(item.get("speaker") or "").strip()
    }


def phone_remote_name(name: str) -> str:
    return f"{name}（电话远端）" if name and "电话" not in name and "远端" not in name else name


def base_remote_name(name: str) -> str:
    return re.sub(r"[（(].*?(电话|远端|画外).*?[）)]", "", str(name or "")).strip()


def is_phone_reply_context(item: dict[str, Any], draft: ShotDraft, context_text: str = "") -> bool:
    if str(item.get("source") or "onscreen") != "onscreen":
        return False
    local_text = " ".join(
        [
            str(item.get("performance") or ""),
            str(item.get("text") or ""),
            draft.source_excerpt,
            " ".join(draft.visual_texts),
        ]
    )
    local_onscreen_child_action = any(
        token in local_text
        for token in (
            "予予伸手",
            "予予抬头",
            "小手摸",
            "抓蜡烛",
            "摸了摸她的脸",
            "牵住",
            "抱住",
        )
    )
    if local_onscreen_child_action:
        return False
    return any(token in local_text for token in ("对着手机", "回手机", "回复语音", "听到儿子的声音", "手机里", "语音"))


def infer_phone_reply_remote_listener(item: dict[str, Any], context_text: str = "") -> str:
    speaker = str(item.get("speaker") or "").strip()
    text = " ".join([str(item.get("text") or ""), str(item.get("performance") or ""), context_text])
    if speaker == "沈念歌" and any(token in text for token in ("予予", "儿子", "妈咪", "下班就回去")):
        return "沈知予"
    if speaker == "沈知予" and any(token in text for token in ("妈咪", "妈妈")):
        return "沈念歌"
    return ""


def dialogue_listener(scene_text: str, speaker: str) -> str:
    candidates = ["沈念歌", "陆景琛", "沈知予", "赵一鸣", "苏晚", "林雨薇", "周雅琳"]
    for name in candidates:
        if name != speaker and name in scene_text:
            return name
    return ""


def explicit_listener_from_performance(performance: str, speaker: str = "") -> str:
    text = str(performance or "").strip()
    if not text or not any(token in text for token in ("对", "看向", "朝", "冲", "问")):
        return ""
    candidates = list(KNOWN_CHARACTER_SPECS) + list(EPHEMERAL_TOKENS) + list(BACKGROUND_GROUP_LISTENER_TOKENS)
    for name in sorted(dict.fromkeys(candidates), key=len, reverse=True):
        if name and name != speaker and name in text:
            return name
    return ""


def build_shot_drafts(parsed: ParsedScript, max_shots: int) -> list[ShotDraft]:
    events = [line for line in parsed.lines if line.kind in {"visual", "dialogue", "music"}]
    scene_context: dict[str, str] = {}
    for line in parsed.lines:
        if line.scene_name and line.kind in {"visual", "dialogue"}:
            scene_context.setdefault(line.scene_name, "")
            if len(scene_context[line.scene_name]) < 1200:
                scene_context[line.scene_name] += " " + line.text

    drafts: list[ShotDraft] = []
    pending_visuals: list[ScriptLine] = []
    pending_music: list[str] = []

    def draft_location_from_lines(
        lines: list[ScriptLine],
        parent_scene_name: str,
        allow_tie_break: bool,
    ) -> tuple[str, str, str, str, list[dict[str, str]]]:
        candidates: list[dict[str, str]] = []
        for item in lines:
            candidates.extend(local_scene_candidates_for_line(item))
        best = best_single_local_scene(candidates, allow_tie_break=allow_tie_break)
        if not best:
            return parent_scene_name, safe_slug(parent_scene_name, "SCENE"), "", "", candidates
        scene_name = str(best.get("scene_name") or parent_scene_name).strip() or parent_scene_name
        return (
            scene_name,
            safe_slug(scene_name, safe_slug(parent_scene_name, "SCENE")),
            str(best.get("basis") or "").strip(),
            str(best.get("excerpt") or "").strip(),
            candidates,
        )

    def adjacent_visual_context(event_index: int, event: ScriptLine) -> list[ScriptLine]:
        lines: list[ScriptLine] = []
        cursor = event_index - 1
        while cursor >= 0:
            candidate = events[cursor]
            if candidate.scene_id != event.scene_id or candidate.kind != "visual":
                break
            lines.insert(0, candidate)
            if "【画面" in candidate.text:
                break
            cursor -= 1
        return lines

    def flush_visuals() -> None:
        nonlocal pending_visuals, pending_music
        if not pending_visuals:
            return
        first = pending_visuals[0]
        last = pending_visuals[-1]
        text = " ".join(item.text for item in pending_visuals)
        parent_scene_name = first.scene_name or "未命名场景"
        scene_name, scene_id, location_basis, location_excerpt, location_candidates = draft_location_from_lines(
            pending_visuals,
            parent_scene_name,
            allow_tie_break=False,
        )
        drafts.append(
            ShotDraft(
                shot_id="",
                scene_name=scene_name,
                scene_id=scene_id or first.scene_id or safe_slug(first.scene_name, "SCENE"),
                shot_type=first.shot_type or "中景",
                visual_texts=[text],
                dialogue=[],
                music=list(pending_music),
                line_start=first.line_no,
                line_end=last.line_no,
                source_excerpt=line_excerpt(parsed.script_path, first.line_no, last.line_no),
                parent_scene_name=parent_scene_name,
                parent_scene_id=first.scene_id or safe_slug(parent_scene_name, "SCENE"),
                shot_context_excerpt=line_context_excerpt(parsed.script_path, first.line_no, last.line_no, before=2, after=2),
                shot_location_basis=location_basis,
                shot_location_excerpt=location_excerpt,
                shot_location_candidates=location_candidates,
            )
        )
        pending_visuals = []
        pending_music = []

    for event_index, event in enumerate(events):
        if event.kind == "music":
            pending_music.append(event.text)
            continue
        if event.kind == "visual":
            pending_visuals.append(event)
            if len(pending_visuals) >= 2 or any(token in event.text for token in ("特写", "报告", "照片", "手机", "推开", "闯", "站起")):
                flush_visuals()
            continue
        if event.kind == "dialogue":
            flush_visuals()
            source = dialogue_source(event.text, event.performance)
            listener = dialogue_listener(scene_context.get(event.scene_name, ""), event.speaker) if source in {"phone", "offscreen"} else ""
            dialogue = {
                "speaker": event.speaker,
                "text": event.text,
                "source": source,
                "purpose": "推进原剧本对白",
                "performance": event.performance,
            }
            if listener:
                dialogue["listener"] = listener
            if source == "phone":
                listener_text = listener or "画面内听者"
                visual = (
                    f"{listener_text}正在听手机语音，手机首帧可见，屏幕朝向持有者，屏幕内容不可见；"
                    f"{event.speaker}是电话远端声音，不作为画面内实体人物出现"
                )
            else:
                visual = f"{event.speaker}正面或三分之二侧脸可见，表情和眼神承接原剧本对白"
            if event.performance:
                visual += f"，表演状态：{event.performance}"
            parent_scene_name = event.scene_name or "未命名场景"
            context_lines = adjacent_visual_context(event_index, event)
            scene_name, scene_id, location_basis, location_excerpt, location_candidates = draft_location_from_lines(
                context_lines,
                parent_scene_name,
                allow_tie_break=True,
            )
            drafts.append(
                ShotDraft(
                    shot_id="",
                    scene_name=scene_name,
                    scene_id=scene_id or event.scene_id or safe_slug(event.scene_name, "SCENE"),
                    shot_type="近景",
                    visual_texts=[visual],
                    dialogue=[dialogue],
                    music=list(pending_music),
                    line_start=event.line_no,
                    line_end=event.line_no,
                    source_excerpt=line_excerpt(parsed.script_path, event.line_no, event.line_no),
                    parent_scene_name=parent_scene_name,
                    parent_scene_id=event.scene_id or safe_slug(parent_scene_name, "SCENE"),
                    shot_context_excerpt=line_context_excerpt(parsed.script_path, event.line_no, event.line_no, before=4, after=4),
                    shot_location_basis=location_basis,
                    shot_location_excerpt=location_excerpt,
                    shot_location_candidates=location_candidates,
                )
            )
            pending_music = []
    flush_visuals()
    drafts = merge_thin_drafts_into_previous(drafts, parsed.script_path)

    if len(drafts) > max_shots:
        drafts = select_representative_drafts(drafts, max_shots)
    for idx, draft in enumerate(drafts, start=1):
        draft.shot_id = f"SH{idx:02d}"
    return drafts


def dialogue_visual_text_for_event(
    event: ScriptLine,
    scene_context: str,
    *,
    force_phone_remote: bool = False,
) -> tuple[str, dict[str, Any]]:
    source = "phone" if force_phone_remote else dialogue_source(event.text, event.performance)
    listener = "" if force_phone_remote else (dialogue_listener(scene_context, event.speaker) if source in {"phone", "offscreen"} else "")
    dialogue = {
        "speaker": event.speaker,
        "text": event.text,
        "source": source,
        "purpose": "推进原剧本对白",
        "performance": event.performance,
    }
    if listener:
        dialogue["listener"] = listener
    if source == "phone":
        listener_text = listener or "画面内听者"
        visual = (
            f"{listener_text}正在听手机语音，手机首帧可见，屏幕朝向持有者，屏幕内容不可见；"
            f"{event.speaker}是电话远端声音，不作为画面内实体人物出现"
        )
    else:
        visual = f"{event.speaker}正面或三分之二侧脸可见，表情和眼神承接原剧本对白"
    if event.performance:
        visual += f"，表演状态：{event.performance}"
    return visual, dialogue


def build_shot_drafts_from_selection_payload(parsed: ParsedScript, payload: dict[str, Any], max_shots: int, source_label: str = "selection payload") -> list[ShotDraft]:
    rows = payload.get("selected_shots") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"shot selection plan has no selected_shots: {source_label}")

    scene_context: dict[str, str] = {}
    for line in parsed.lines:
        if line.scene_name and line.kind in {"visual", "dialogue"}:
            scene_context.setdefault(line.scene_name, "")
            if len(scene_context[line.scene_name]) < 1200:
                scene_context[line.scene_name] += " " + line.text
    source_units = source_units_from_screen_script(parsed)
    unit_lookup = {unit.unit_id: unit for unit in source_units}

    drafts: list[ShotDraft] = []
    for row in rows[:max_shots]:
        if not isinstance(row, dict):
            continue
        raw_range = row.get("line_range") or row.get("source_range")
        if not (
            isinstance(raw_range, list)
            and len(raw_range) == 2
            and all(isinstance(item, int) for item in raw_range)
        ):
            raise ValueError(f"invalid line_range in shot selection plan: {row}")
        line_start, line_end = int(raw_range[0]), int(raw_range[1])
        if line_start <= 0 or line_end < line_start:
            raise ValueError(f"invalid line_range in shot selection plan: {row}")
        unit_ids = [str(item).strip() for item in row.get("source_unit_ids", []) if str(item).strip()] if isinstance(row.get("source_unit_ids"), list) else []
        unit_ranges = [
            (unit_lookup[unit_id].line_start, unit_lookup[unit_id].line_end)
            for unit_id in unit_ids
            if unit_id in unit_lookup
        ]
        executable_lines_from_units = {
            line.line_no
            for start, end in unit_ranges
            for line in parsed.lines
            if start <= line.line_no <= end and line.kind in {"visual", "dialogue", "music"}
        }
        if executable_lines_from_units:
            events = [
                line
                for line in parsed.lines
                if line.line_no in executable_lines_from_units and line.kind in {"visual", "dialogue", "music"}
            ]
            line_start = min(line.line_no for line in events)
            line_end = max(line.line_no for line in events)
        else:
            events = [
                line
                for line in parsed.lines
                if line_start <= line.line_no <= line_end and line.kind in {"visual", "dialogue", "music"}
            ]
        if not events:
            raise ValueError(f"line_range contains no executable screen events: {line_start}-{line_end}")
        first_event = events[0]
        parent_scene_name = first_event.scene_name or "未命名场景"
        scene_lines = [line for line in events if line.kind == "visual"]
        candidates: list[dict[str, str]] = []
        for item in scene_lines:
            candidates.extend(local_scene_candidates_for_line(item))
        best = best_single_local_scene(candidates, allow_tie_break=True)
        if best:
            scene_name = str(best.get("scene_name") or parent_scene_name).strip() or parent_scene_name
            location_basis = str(best.get("basis") or "").strip()
            location_excerpt = str(best.get("excerpt") or "").strip()
        else:
            scene_name = parent_scene_name
            location_basis = ""
            location_excerpt = ""

        visual_texts: list[str] = []
        dialogue: list[dict[str, Any]] = []
        music: list[str] = []
        shot_type = ""
        selection_plan_meta = {
            key: row.get(key)
            for key in (
                "source_unit_ids",
                "source_range",
                "summary",
                "story_function",
                "selection_reason",
                "merge_reason",
                "keyframe_moment",
                "must_include_evidence",
                "dialogue_policy",
                "key_props",
                "i2v_risk_notes",
                "omitted_unit_ids",
            )
            if key in row
        }
        force_phone_remote = selection_marks_phone_remote(selection_plan_meta)
        for event in events:
            if event.kind == "visual":
                if event.text:
                    visual_texts.append(event.text)
                if event.shot_type and not shot_type:
                    shot_type = event.shot_type
            elif event.kind == "dialogue":
                visual, dialogue_item = dialogue_visual_text_for_event(
                    event,
                    scene_context.get(event.scene_name, ""),
                    force_phone_remote=force_phone_remote,
                )
                visual_texts.append(visual)
                dialogue.append(dialogue_item)
            elif event.kind == "music" and event.text:
                music.append(event.text)
        if not visual_texts:
            visual_texts = [str(row.get("summary") or "").strip() or line_excerpt(parsed.script_path, line_start, line_end)]
        keyframe = selection_keyframe_moment(selection_plan_meta)
        if keyframe and keyframe not in " ".join(visual_texts):
            visual_texts.insert(0, f"首帧关键瞬间：{keyframe}")
        drafts.append(
            ShotDraft(
                shot_id="",
                scene_name=scene_name,
                scene_id=safe_slug(scene_name, first_event.scene_id or "SCENE"),
                shot_type=shot_type or ("近景" if dialogue else "中景"),
                visual_texts=visual_texts,
                dialogue=dialogue,
                music=music,
                line_start=line_start,
                line_end=line_end,
                source_excerpt=line_excerpt(parsed.script_path, line_start, line_end),
                parent_scene_name=parent_scene_name,
                parent_scene_id=first_event.scene_id or safe_slug(parent_scene_name, "SCENE"),
                shot_context_excerpt=line_context_excerpt(parsed.script_path, line_start, line_end, before=4, after=4),
                shot_location_basis=location_basis,
                shot_location_excerpt=location_excerpt,
                shot_location_candidates=candidates,
                selection_plan=selection_plan_meta,
            )
        )

    for idx, draft in enumerate(drafts, start=1):
        draft.shot_id = f"SH{idx:02d}"
    return drafts


def build_shot_drafts_from_selection_plan(parsed: ParsedScript, plan_path: Path, max_shots: int) -> list[ShotDraft]:
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    return build_shot_drafts_from_selection_payload(parsed, payload, max_shots, str(plan_path))


def source_units_from_screen_script(parsed: ParsedScript) -> list[ssp.SourceUnit]:
    units: list[ssp.SourceUnit] = []
    for idx, line in enumerate(parsed.lines, start=1):
        if line.kind not in {"scene", "visual", "dialogue", "music"}:
            continue
        text = line.text
        if line.kind == "dialogue" and line.speaker:
            text = f"{line.speaker}: {line.text}"
        units.append(
            ssp.SourceUnit(
                unit_id=f"U{idx:04d}",
                index=idx,
                source_type="screen",
                kind=line.kind,
                text=text,
                scene_name=line.scene_name,
                speaker=line.speaker,
                line_start=line.line_no,
                line_end=line.line_no,
                metadata={"shot_type": line.shot_type, "performance": line.performance},
            )
        )
    return units


def selection_plan_from_screen_drafts(parsed: ParsedScript, drafts: list[ShotDraft], mode: str = "rule") -> ssp.SelectionPlan:
    units = source_units_from_screen_script(parsed)
    selected: list[ssp.SelectedShot] = []
    for draft in drafts:
        unit_ids = [
            unit.unit_id
            for unit in units
            if draft.line_start <= unit.line_start <= draft.line_end and unit.kind in {"visual", "dialogue", "music"}
        ]
        text = " ".join(draft.visual_texts + [item.get("text", "") for item in draft.dialogue])
        selected.append(
            ssp.SelectedShot(
                shot_id=draft.shot_id,
                source_unit_ids=unit_ids,
                source_range=[draft.line_start, draft.line_end],
                summary=ssp.compact_text(" ".join(draft.visual_texts) or draft.source_excerpt, 220),
                scene_name=draft.scene_name,
                story_function="screen_rule_selection",
                selection_reason="built-in screen heuristic selected this source range",
                merge_reason="built-in screen heuristic merged adjacent executable lines",
                keyframe_moment=ssp.compact_text(" ".join(draft.visual_texts[:1]) or draft.source_excerpt, 180),
                must_include_evidence=[draft.source_excerpt],
                dialogue_policy="preserve exact dialogue from selected source lines",
                key_props=ssp.detected_key_props(text + " " + draft.source_excerpt),
                i2v_risk_notes=[],
                omitted_unit_ids=[],
                is_montage="【画面" in draft.source_excerpt or "蒙太奇" in draft.source_excerpt,
            )
        )
    return ssp.SelectionPlan(mode=mode, source_type="screen", episode_id=parsed.episode_id, title=parsed.title, selected_shots=selected, omitted_units=[])


def attach_selection_plan_to_screen_drafts(drafts: list[ShotDraft], plan: ssp.SelectionPlan) -> list[ShotDraft]:
    by_range = {(shot.source_range[0], shot.source_range[1]): shot for shot in plan.selected_shots}
    for draft in drafts:
        shot = by_range.get((draft.line_start, draft.line_end))
        if shot:
            draft.selection_plan = ssp.to_jsonable(shot)
    return drafts


def screen_selection_provider_config(args: argparse.Namespace, mode: str) -> tuple[str, str, str, str]:
    backend = str(args.selection_backend or "auto").strip().lower()
    if backend == "openai":
        return "openai", args.selection_model.strip() or args.openai_selection_model, "OPENAI_API_KEY", "https://api.openai.com/v1"
    model = args.selection_model.strip() or args.semantic_model.strip() or DEFAULT_GROK_SEMANTIC_MODELS[0]
    return "grok", model, "XAI_API_KEY", "https://api.x.ai/v1"


def should_fail_fast_selection(args: argparse.Namespace) -> bool:
    if str(args.selection_mode or "").strip() == "rule":
        return False
    return bool(args.strict_selection_mode) or not bool(getattr(args, "allow_selection_fallback", False))


def selection_qa_has_high_findings(qa: ssp.SelectionQAReport | None) -> bool:
    if qa is None:
        return False
    return any(item.get("severity") == "high" for item in qa.findings)


def plan_payload_from_selection_plan(plan: ssp.SelectionPlan) -> dict[str, Any]:
    return {
        "selected_shots": [
            {
                **ssp.to_jsonable(shot),
                "line_range": shot.source_range,
            }
            for shot in plan.selected_shots
        ],
        "omitted_units": plan.omitted_units,
        "mode": plan.mode,
        "source_type": plan.source_type,
        "episode_id": plan.episode_id,
        "title": plan.title,
    }


def write_selection_artifacts(
    paths: n2v.ProjectPaths,
    plan: ssp.SelectionPlan | None,
    qa: ssp.SelectionQAReport | None,
    args: argparse.Namespace,
) -> None:
    if plan is not None:
        ssp.write_json(paths.out_dir / "source_selection_plan.json", plan, args.overwrite, args.dry_run)
    if qa is not None:
        ssp.write_json(paths.out_dir / "source_selection_qa_report.json", qa, args.overwrite, args.dry_run)


def run_screen_source_selection(
    args: argparse.Namespace,
    parsed: ParsedScript,
    bible: n2v.ProjectBible,
    paths: n2v.ProjectPaths,
    max_shots: int,
) -> tuple[list[ShotDraft], ssp.SelectionPlan | None, ssp.SelectionQAReport | None, list[dict[str, str]]]:
    fallbacks: list[dict[str, str]] = []
    rule_drafts = build_shot_drafts(parsed, max_shots)
    rule_plan = selection_plan_from_screen_drafts(parsed, rule_drafts, "rule")
    rule_qa = ssp.qa_selection_plan(rule_plan, source_units_from_screen_script(parsed))

    if args.selection_mode == "rule":
        write_selection_artifacts(paths, rule_plan, rule_qa, args)
        return attach_selection_plan_to_screen_drafts(rule_drafts, rule_plan), rule_plan, rule_qa, fallbacks

    units = source_units_from_screen_script(parsed)
    characters = [{"name": c.name, "character_id": c.character_id, "aliases": [c.name, c.character_id, c.lock_profile_id]} for c in bible.characters]

    def run_one(mode: str) -> tuple[ssp.SelectionPlan | None, ssp.SelectionQAReport | None]:
        provider, model, api_env, base_url = screen_selection_provider_config(args, mode)
        return ssp.run_llm_selection(
            mode=mode,
            source_type="screen",
            episode_id=parsed.episode_id,
            title=parsed.title,
            units=units,
            max_shots=max_shots,
            characters=characters,
            out_dir=paths.out_dir,
            provider=provider,
            model=model,
            api_key_env=api_env,
            base_url=base_url,
            timeout_sec=args.selection_timeout_sec,
            retry_count=args.selection_retry_count,
            retry_wait_sec=args.selection_retry_wait_sec,
            max_output_tokens=args.selection_max_output_tokens,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )[:2]

    selected_plan: ssp.SelectionPlan | None = None
    selected_qa: ssp.SelectionQAReport | None = None
    no_rules_plan: ssp.SelectionPlan | None = None
    rules_plan: ssp.SelectionPlan | None = None
    try:
        if args.selection_mode == "llm-no-rules":
            selected_plan, selected_qa = run_one("llm-no-rules")
        elif args.selection_mode == "llm-rules":
            selected_plan, selected_qa = run_one("llm-rules")
        elif args.selection_mode == "compare":
            no_rules_plan, _ = run_one("llm-no-rules")
            rules_plan, selected_qa = run_one("llm-rules")
            selected_plan = rules_plan
            ssp.write_text(paths.out_dir / "source_selection_compare.md", ssp.render_compare_markdown(rule_plan, no_rules_plan, rules_plan), args.overwrite, args.dry_run)
    except Exception as exc:
        if should_fail_fast_selection(args):
            raise
        fallbacks.append({"task": "source_selection", "reason": f"{args.selection_mode} failed; fell back to rule mode: {str(exc)[:240]}"})
        selected_plan, selected_qa = rule_plan, rule_qa

    if selected_plan is None:
        if should_fail_fast_selection(args) and not args.dry_run:
            raise RuntimeError(f"{args.selection_mode} did not produce a live source selection plan")
        selected_plan, selected_qa = rule_plan, rule_qa
        if args.selection_mode != "compare":
            fallbacks.append({"task": "source_selection", "reason": f"{args.selection_mode} did not produce a live plan; using rule plan"})
    write_selection_artifacts(paths, selected_plan, selected_qa, args)
    if selection_qa_has_high_findings(selected_qa) and should_fail_fast_selection(args) and not args.dry_run:
        high = [item for item in (selected_qa.findings if selected_qa else []) if item.get("severity") == "high"]
        raise RuntimeError(f"{args.selection_mode} source selection QA failed with high findings: {high[:5]}")
    drafts = build_shot_drafts_from_selection_payload(parsed, plan_payload_from_selection_plan(selected_plan), max_shots, "source_selection_plan")
    return drafts, selected_plan, selected_qa, fallbacks


def draft_score(draft: ShotDraft) -> int:
    text = " ".join(draft.visual_texts + [d.get("text", "") for d in draft.dialogue])
    score = 1
    if draft.dialogue:
        score += 4
    for token in ("爸爸", "DNA", "安排", "查", "99.99", "秘密", "手术费", "陆景琛", "沈念歌", "沈知予"):
        if token in text:
            score += 2
    if any(token in text for token in IMPORTANT_PROP_KEYWORDS):
        score += 1
    return score


THIN_SHOT_TRANSITION_TOKENS = (
    "画面暗下",
    "画面渐黑",
    "画面一黑",
    "黑场",
    "淡出",
    "切黑",
    "转场",
)


def is_transition_only_text(text: str) -> bool:
    cleaned = sanitize_prompt_text(text).strip()
    if not cleaned:
        return False
    compact = re.sub(r"[\s。！？!?,，、；;：:——…]+", "", cleaned)
    transition_compacts = {
        re.sub(r"[\s。！？!?,，、；;：:——…]+", "", token)
        for token in THIN_SHOT_TRANSITION_TOKENS
    }
    return compact in transition_compacts or any(token in cleaned for token in THIN_SHOT_TRANSITION_TOKENS)


def draft_is_montage(draft: ShotDraft) -> bool:
    text = f"{draft.scene_name} {draft.source_excerpt} {' '.join(draft.visual_texts)}"
    return "蒙太奇" in text or "快速剪辑" in text or "【画面" in text


def draft_has_explicit_narration(draft: ShotDraft) -> bool:
    text = " ".join(draft.visual_texts + [draft.source_excerpt or ""])
    return any(token in text for token in ("旁白", "画外音", "画外旁白", "VO", "V.O."))


def is_offscreen_listener_name(name: str) -> bool:
    return any(token in str(name or "") for token in ("电话", "画外", "另一端", "远端"))


def is_background_group_listener_name(name: str) -> bool:
    text = str(name or "").strip().lower()
    if not text:
        return False
    return any(token in text for token in BACKGROUND_GROUP_LISTENER_TOKENS)


def hard_visible_character_names(names: list[str]) -> list[str]:
    return [
        name
        for name in dict.fromkeys(str(item or "").strip() for item in names)
        if name and not is_background_group_listener_name(name)
    ]


def evidence_supported_visible_names(names: list[str], draft: ShotDraft, context_text: str) -> list[str]:
    if is_document_screen_detail_draft(draft, context_text):
        return []
    evidence_text = " ".join(
        draft.visual_texts
        + [draft.source_excerpt, context_text]
        + [
            str(item.get("text") or "") + " " + str(item.get("performance") or "")
            for item in draft.dialogue
            if isinstance(item, dict)
        ]
    )
    speakers = {
        str(item.get("speaker") or "").strip()
        for item in draft.dialogue
        if isinstance(item, dict) and str(item.get("speaker") or "").strip()
    }
    visible_evidence_aliases = {
        "沈知予": ("沈知予", "予予", "孩子", "儿子", "宝宝", "婴儿", "小男孩"),
        "沈念歌": ("沈念歌", "妈咪", "妈妈", "母亲"),
        "陆景琛": ("陆景琛", "陆总", "那个男人", "西装男人", "叔叔"),
    }
    remote_speakers = remote_phone_speakers(draft, context_text)
    return [
        name
        for name in hard_visible_character_names(names)
        if name not in remote_speakers
        and (
            name in speakers
            or name in evidence_text
            or any(alias and alias in evidence_text for alias in visible_evidence_aliases.get(name, ()))
        )
    ]


def is_thin_shot_draft(draft: ShotDraft) -> bool:
    if draft.dialogue:
        return False
    text = sanitize_prompt_text(" ".join(draft.visual_texts)).strip()
    if not text:
        return True
    compact = re.sub(r"[\s。！？!?,，、；;：:——…]+", "", text)
    if any(token in text for token in THIN_SHOT_TRANSITION_TOKENS):
        return True
    content_tokens = (
        "陆景琛",
        "沈念歌",
        "沈知予",
        "赵一鸣",
        "DNA",
        "报告",
        "手机",
        "照片",
        "门",
        "车",
        "医院",
        "眼神",
    )
    return len(compact) <= 8 and not any(token in text for token in content_tokens)


def merge_thin_drafts_into_previous(drafts: list[ShotDraft], script_path: Path) -> list[ShotDraft]:
    merged: list[ShotDraft] = []
    for draft in drafts:
        if is_thin_shot_draft(draft) and merged:
            previous = merged[-1]
            transition_text = sanitize_prompt_text(" ".join(draft.visual_texts)).strip()
            if transition_text:
                previous.visual_texts.append(f"结尾转场：{transition_text}")
            for music in draft.music:
                if music not in previous.music:
                    previous.music.append(music)
            previous.line_end = max(previous.line_end, draft.line_end)
            previous.source_excerpt = line_excerpt(script_path, previous.line_start, previous.line_end)
            continue
        merged.append(draft)
    return merged


def select_representative_drafts(drafts: list[ShotDraft], max_shots: int) -> list[ShotDraft]:
    if len(drafts) <= max_shots:
        return drafts
    last_content_index = next(
        (idx for idx in range(len(drafts) - 1, -1, -1) if not is_thin_shot_draft(drafts[idx])),
        len(drafts) - 1,
    )
    required_indices: set[int] = {0, last_content_index}
    seen_scenes: set[str] = set()
    for idx, draft in enumerate(drafts):
        scene_key = draft.parent_scene_name or draft.scene_name
        if scene_key not in seen_scenes:
            required_indices.add(idx)
            seen_scenes.add(scene_key)
    ranked = sorted(range(len(drafts)), key=lambda i: (draft_score(drafts[i]), -i), reverse=True)
    for idx in ranked:
        required_indices.add(idx)
        if len(required_indices) >= max_shots:
            break
    selected = sorted(required_indices)
    selected = selected[:max_shots]
    return merge_omitted_setup_dialogues_into_selected_drafts(drafts, selected)


SETUP_DIALOGUE_TOKENS = (
    "沈小姐",
    "先生",
    "小姐",
    "等等",
    "等一下",
    "站住",
    "回来",
    "不能",
    "需要",
    "补充",
    "可是",
    "为什么",
    "怎么",
    "吗",
    "？",
    "?",
    "——",
)

SETUP_VISUAL_TOKENS = (
    "追出来",
    "追上",
    "叫住",
    "喊住",
    "拦住",
    "跑出来",
    "走过来",
    "冲出来",
)


def is_setup_dialogue_for_selected_response(previous: ShotDraft, current: ShotDraft) -> bool:
    if not previous.dialogue or not current.dialogue:
        return False
    if previous.parent_scene_id != current.parent_scene_id:
        return False
    if current.line_start - previous.line_end > 3:
        return False
    previous_speaker = str(previous.dialogue[-1].get("speaker") or "").strip()
    current_speaker = str(current.dialogue[0].get("speaker") or "").strip()
    if not previous_speaker or not current_speaker or previous_speaker == current_speaker:
        return False
    previous_text = " ".join(
        [
            str(previous.dialogue[-1].get("text") or ""),
            str(previous.dialogue[-1].get("performance") or ""),
            " ".join(previous.visual_texts),
        ]
    )
    current_text = " ".join(
        [
            str(current.dialogue[0].get("text") or ""),
            str(current.dialogue[0].get("performance") or ""),
        ]
    )
    if not text_has_any_token(previous_text, SETUP_DIALOGUE_TOKENS):
        return False
    compact_current = re.sub(r"[\s，。！？!?,、：:；;\"'“”‘’]", "", current_text)
    return len(compact_current) <= 24 or text_has_any_token(current_text, ("头也没回", "停下脚步", "声音平静", "冷冷", "回答"))


def setup_visual_from_prior_drafts(drafts: list[ShotDraft], previous_index: int) -> str:
    cursor = previous_index - 1
    while cursor >= 0:
        candidate = drafts[cursor]
        if candidate.dialogue or candidate.parent_scene_id != drafts[previous_index].parent_scene_id:
            break
        text = sanitize_prompt_text(" ".join(candidate.visual_texts)).strip()
        if text_has_any_token(text, SETUP_VISUAL_TOKENS):
            segments = [
                segment.strip(" ，。；;:")
                for segment in re.split(r"[。！？!?]\s*|结尾转场：", text)
                if segment.strip()
            ]
            for segment in reversed(segments):
                if text_has_any_token(segment, SETUP_VISUAL_TOKENS):
                    return f"前置动作：{segment}"
            return f"前置动作：{text}"
        if drafts[previous_index].line_start - candidate.line_end > 3:
            break
        cursor -= 1
    return ""


def merge_omitted_setup_dialogues_into_selected_drafts(
    drafts: list[ShotDraft],
    selected_indices: list[int],
) -> list[ShotDraft]:
    selected_set = set(selected_indices)
    merged: list[ShotDraft] = []
    for idx in selected_indices:
        draft = drafts[idx]
        previous_idx = idx - 1
        if (
            previous_idx >= 0
            and previous_idx not in selected_set
            and is_setup_dialogue_for_selected_response(drafts[previous_idx], draft)
        ):
            previous = drafts[previous_idx]
            setup_visual = setup_visual_from_prior_drafts(drafts, previous_idx)
            visual_texts = list(draft.visual_texts)
            if setup_visual and setup_visual not in visual_texts:
                visual_texts.insert(0, setup_visual)
            previous_dialogue = [dict(item) for item in previous.dialogue]
            current_dialogue = [dict(item) for item in draft.dialogue]
            if previous_dialogue and current_dialogue:
                previous_dialogue[-1].setdefault("listener", str(current_dialogue[0].get("speaker") or "").strip())
            merged.append(
                replace(
                    draft,
                    visual_texts=visual_texts,
                    dialogue=previous_dialogue + current_dialogue,
                    line_start=previous.line_start,
                    source_excerpt=f"{previous.source_excerpt}\n\n{draft.source_excerpt}".strip(),
                    shot_context_excerpt=draft.shot_context_excerpt or previous.shot_context_excerpt,
                )
            )
            continue
        merged.append(draft)
    return merged


def extract_speakers(paths: list[Path]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            dialogue = parse_dialogue(line)
            if dialogue is not None:
                speaker, _, _ = dialogue
                counter[speaker] += 1
    return counter


def is_ephemeral_name(name: str) -> bool:
    return any(token in name for token in EPHEMERAL_TOKENS)


def ephemeral_lock_profile_id(character_id: str, name: str) -> str:
    if any(token in name for token in EPHEMERAL_GROUP_TOKENS):
        return ""
    cid = str(character_id or "").strip()
    return f"{cid}_LOCK_V1" if cid else ""


def should_enable_ephemeral_lock(character: n2v.Character, characters: list[n2v.Character]) -> bool:
    if character in characters:
        return True
    character_id = str(character.character_id or "").strip()
    if not character_id.startswith("EXTRA_"):
        return False
    if any(token in character.name for token in EPHEMERAL_GROUP_TOKENS):
        return False
    return bool(str(character.lock_profile_id or "").strip())


def ephemeral_character_from_name(name: str) -> n2v.Character:
    raw_name = str(name or "").strip()
    for token, (cid, visual) in EPHEMERAL_CHARACTER_SPECS.items():
        if raw_name == cid:
            return n2v.Character(
                cid,
                ephemeral_lock_profile_id(cid, token),
                token,
                visual,
                ["场景功能", "临时反应"],
                ["短句", "职业化"],
            )
    for token, (cid, visual) in EPHEMERAL_CHARACTER_SPECS.items():
        if token in name:
            return n2v.Character(
                cid,
                ephemeral_lock_profile_id(cid, name),
                name,
                visual,
                ["场景功能", "临时反应"],
                ["短句", "职业化"],
            )
    cid = "EXTRA_" + re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
    if cid == "EXTRA_":
        cid = "EXTRA_TEMP"
    return n2v.Character(
        cid,
        ephemeral_lock_profile_id(cid, name),
        name,
        f"{name}，现代都市短剧临时功能人物，只服务本镜头叙事，不使用主角身份锁定",
        ["场景功能"],
        ["短句"],
    )


def character_from_name(name: str, idx: int, used_ids: set[str]) -> n2v.Character:
    if name in KNOWN_CHARACTER_SPECS:
        cid, lock_id, visual, persona, speech = KNOWN_CHARACTER_SPECS[name]
        if cid in used_ids:
            return n2v.Character(cid, lock_id, name, visual, persona, speech)
        used_ids.add(cid)
        return n2v.Character(cid, lock_id, name, visual, persona, speech)
    cid = f"CHAR_{idx:02d}"
    while cid in used_ids:
        idx += 1
        cid = f"CHAR_{idx:02d}"
    used_ids.add(cid)
    return n2v.Character(
        cid,
        f"{cid}_LOCK_V1",
        name,
        f"{name}，现代都市短剧角色，外形以原剧本身份、服装和场景描述为准，脸部稳定可辨",
        ["关系压力", "情绪可读", "目标明确"],
        ["口语化", "短句", "信息直给"],
    )


def build_characters(script_files: list[Path], current: ParsedScript) -> list[n2v.Character]:
    speaker_counts = extract_speakers(script_files)
    text = "\n".join(path.read_text(encoding="utf-8") for path in script_files)
    for known in KNOWN_CHARACTER_SPECS:
        if known in text:
            speaker_counts.setdefault(known, 1)
    used_ids: set[str] = set()
    characters: list[n2v.Character] = []
    found_known = [name for name in KNOWN_CHARACTER_SPECS if name in text]
    ordered_names = found_known + [name for name, _ in speaker_counts.most_common(24) if name not in found_known]
    for idx, name in enumerate(ordered_names, start=1):
        character = ephemeral_character_from_name(name) if is_ephemeral_name(name) else character_from_name(name, idx, used_ids)
        if character.name not in {item.name for item in characters} and character.character_id not in {item.character_id for item in characters}:
            characters.append(character)
    if not characters:
        characters.append(character_from_name("主角", 1, used_ids))
    return characters


def build_bible(
    source: n2v.ProjectSource,
    parsed: ParsedScript,
    all_scripts: list[ParsedScript],
    platform: str,
    characters: list[n2v.Character],
) -> n2v.ProjectBible:
    outlines: list[dict[str, Any]] = []
    for item in all_scripts:
        outlines.append(
            {
                "episode_number": item.episode_number,
                "title": item.title,
                "goal": item.hook or item.selling_point or "按原剧本推进本集核心冲突",
                "conflict": item.recap or item.selling_point or "亲子身份、阶层压力与旧事秘密持续升级",
                "emotions": item.keywords or ["相遇", "试探", "反转"],
                "hook": item.hook or item.preview or "下一集继续揭开关系秘密",
                "source_basis": [Path(item.script_path).name],
                "story_function": "screen_script_source_episode",
            }
        )
    if not outlines:
        outlines.append(
            {
                "episode_number": parsed.episode_number,
                "title": parsed.title,
                "goal": parsed.hook or "按原剧本推进本集核心冲突",
                "conflict": parsed.recap or "亲子身份与旧事秘密持续升级",
                "emotions": parsed.keywords or ["相遇", "试探", "反转"],
                "hook": parsed.hook or parsed.preview or "下一集继续揭开关系秘密",
                "source_basis": [Path(parsed.script_path).name],
                "story_function": "screen_script_source_episode",
            }
        )
    setting = "现代中国滨海市都市短剧，医院、集团大厦、幼儿园、公寓等现实空间，写实电影感"
    selling = parsed.keywords or ["萌宝", "总裁", "亲子身份", "旧事秘密"]
    return n2v.ProjectBible(
        project_name=source.project_name,
        title=source.title,
        platform=platform,
        setting=setting,
        core_selling_points=selling,
        logline="年轻母亲带着聪明萌宝回到滨海市，冷面总裁在一次次相遇中发现亲子真相和四年前旧事。",
        story_stages=[
            "开局用萌宝误闯和身份相似制造强钩子。",
            "中段用职场重逢、调查和亲子线索持续升级。",
            "结尾用DNA、旧案或匿名资助推进下一集悬念。",
        ],
        episode_outlines=sorted(outlines, key=lambda item: int(item.get("episode_number") or 0)),
        relationships=[
            "沈念歌是独自养育孩子的母亲，核心目标是保护沈知予。",
            "陆景琛是掌控型总裁，面对亲子真相时从冷静转向被震动。",
            "沈知予是亲子身份钩子的主动推动者，用童言童行直击秘密。",
            "赵一鸣承担调查和执行功能，帮助陆景琛把线索落地。",
        ],
        visual_baseline=f"{setting}，竖屏9:16，低饱和，真实光影，人物脸部和眼神优先。",
        language_policy=dict(n2v.DEFAULT_LANGUAGE_POLICY),
        characters=characters,
        safety_note="儿童角色只做亲情和剧情表达，不做任何情色化呈现；文件、报告、短信等文字证据交给字幕或旁白表达。",
        generation_notes=["screen2video faithful conversion", "screen script is the source of truth"],
    )


def build_episode_plan(parsed: ParsedScript) -> n2v.EpisodePlan:
    return n2v.EpisodePlan(
        episode_id=parsed.episode_id,
        episode_number=parsed.episode_number,
        episode_label=f"第{parsed.episode_number}集",
        title=parsed.title,
        goal=parsed.hook or parsed.selling_point or "忠实呈现原剧本本集核心事件",
        conflict=parsed.recap or parsed.selling_point or "亲子身份与旧事秘密持续升级",
        emotions=parsed.keywords or ["相遇", "试探", "反转"],
        hook=parsed.hook or parsed.preview or "下一集继续推进关系秘密",
        source_basis=[str(parsed.script_path)],
        story_function="screen_script_source_episode",
    )


def build_semantic_probe_prompt(
    parsed: ParsedScript,
    drafts: list[ShotDraft],
    characters: list[n2v.Character],
    context_before: int,
    context_after: int,
) -> str:
    aliases = character_alias_table(characters)
    character_rows = [
        {
            "name": character.name,
            "character_id": character.character_id,
            "aliases": [alias for alias, target in aliases.items() if target == character.name and alias != character.name][:8],
        }
        for character in characters
    ]
    items: list[dict[str, Any]] = []
    previous_key_props: list[str] = []
    previous_shot_id = ""
    for draft in drafts:
        prop_seed_text = sanitize_prompt_text(" ".join(draft.visual_texts)) + " " + sanitize_prompt_text(draft.source_excerpt)
        _, detected_key_props = prop_contracts_for_text(prop_seed_text)
        items.append(
            {
                "shot_id": draft.shot_id,
                "scene_name": draft.scene_name,
                "line_range": [draft.line_start, draft.line_end],
                "source_excerpt": draft.source_excerpt,
                "detected_key_props": detected_key_props,
                "previous_shot": previous_shot_id,
                "previous_shot_key_props": previous_key_props,
                "nearby_context": numbered_line_context(
                    parsed.script_path,
                    draft.line_start,
                    draft.line_end,
                    before=context_before,
                    after=context_after,
                ),
                "rule_output": {
                    "visual_texts": draft.visual_texts,
                    "dialogue": draft.dialogue,
                    "music": draft.music,
                },
            }
        )
        previous_key_props = detected_key_props
        previous_shot_id = draft.shot_id
    payload = {
        "episode_id": parsed.episode_id,
        "title": parsed.title,
        "characters": character_rows,
        "shots": items,
    }
    return (
        "你是短剧 screen script planning semantic annotator。只做忠实结构化标注，不重写剧情、不改台词、不重排事件。\n"
        "\n"
        "必须区分这些字段：\n"
        "- speaker: 谁说话。\n"
        "- listener/addressee: 话说给谁听。\n"
        "- action_targets: 动作作用在谁身上。\n"
        "- visible_characters: 首帧前景必须出现的人物，按画面关系排序。\n"
        "- foreground_cardinality: 首帧 exactly 几个人。\n"
        "- music_cues: 原文音乐提示，只能作为配乐/情绪。\n"
        "- narration_lines: 只有原文明确旁白/画外旁白时才填；音乐提示不能填这里。\n"
        "- prop_handoffs: 只标注“上一 shot 的某个具体道具被递给/接过/继续持有/喝/放下并延续到当前 shot”的关系。\n"
        "- character_state_overlays: 逐 shot 判断会影响画面的身体可视状态；没有就返回空数组。\n"
        "- shot_local_location: 可选。只有当当前 shot 附近原文明确写出比 scene_name 更具体的地点时才填，例如“幼儿园面试/教室门口/公交车/菜市场”。\n"
        "- location_evidence: 可选但必须和 shot_local_location 同时出现，写明 nearby_context line 或 source line 与逐字证据。\n"
        "\n"
        "判断规则：\n"
        "- 不允许改对白 exact_text；exact_text 必须来自输入 dialogue。\n"
        "- 父级 scene_name 只是默认地点；蒙太奇/快速剪辑中的【画面X】局部地点优先。不要把幼儿园面试、公交车、菜市场等局部画面静默改回父级出租屋。\n"
        "- 如果一个人拉住孩子、抱住孩子或牵住孩子，同时对第三者说“对不起/小孩子不懂事/走错/马上走”，孩子通常是 action_target，不是 listener。\n"
        "- 如果场景上下文已经建立某个角色在场，即使当前行用“那个男人/叔叔/陆总/西装男人”指代，也要映射到角色表中的姓名。\n"
        "- scene-only 或 visual-only shot 不要凭空生成 narration。\n"
        "- voiceover/旁白/画外音默认不是画面内被听见的远端声音，不要因此生成 listener/addressee；只有电话、语音、广播、门外声、画外声等明确被画面内角色听见的声音才需要 listener。\n"
        "- prop_handoffs 的 prop_id 必须来自 previous_shot_key_props，不能发明新道具 ID；如果当前 shot 只写“杯子/喝了一口”，但上一 shot 明确是果汁杯，应该标注该具体道具传递。\n"
        "- 只有同一连续场景、相邻 shot、且当前 shot 有接过/递给/拿起/端起/喝/放下等动作时才标注 prop_handoffs；换场、跳时、梦境、回忆断点不要继承。\n"
        "- character_state_overlays 只描述身体/生理/年龄阶段/健康/疲惫/伤病/醉酒/产前产后/明显狼狈等会影响画面的可视状态；不要输出纯心理状态，心理只能作为表演辅助。\n"
        "- 疲惫、病弱、伤病、醉酒等状态如果由原文动作/姿态/时间/照护负担支持，并且会改变角色外观或姿态，也要输出；例如深夜/凌晨仍抱孩子工作、撑腰行走、虚弱扶墙、带伤行动等。\n"
        "- character_state_overlays 必须有 source_basis 和 evidence_quote；source_basis 必须写成具体文件/行号或输入 line_range/nearby_context 行号，不要只写 source_excerpt/nearby_context 这类泛称。\n"
        "- 证据可来自当前 shot 或 nearby_context，但身体阶段必须贴合本 shot/keyframe_moment 的可见瞬间；附近上下文只能补证据，不能把后面/前面的身体阶段提前或滞后套到当前首帧。\n"
        "- 不要把“肚子已经很大/撑腰走路”等当前孕期画面标成 postpartum；只有当前镜头证据明确产后、刚生完、抱着新生儿、产后恢复等，才能写 postpartum。\n"
        "- character_state_overlays 的 state_id 由你根据原文生成短 snake_case，不使用固定枚举；scope 固定为 shot_local。\n"
        "- 如果身体状态依赖关键实物证据（例如验孕棒、婴儿、绷带、拐杖、药瓶、酒瓶、医疗器械等），写入 key_props；若该物件不属于选定 keyframe_moment，可在 visible_constraints/negative_constraints 中说明不要强行拼贴。\n"
        "- 如果蒙太奇或跳时镜头包含多个时间点，允许输出 keyframe_moment 指定首帧只取哪一个单一瞬间，避免把多个时间点拼贴在一张图里。\n"
        "- 如果儿童年龄阶段或身体状态与全局角色锁描述冲突，输出 shot-local overlay 和 negative_constraints，只在本 shot 覆盖年龄/身形/身体状态，不改身份连续性。\n"
        "\n"
        "返回严格 JSON：{\"shots\":[...]}\n"
        "每个 shot 字段：shot_id, visible_characters, foreground_cardinality, dialogue_annotations, prop_handoffs, character_state_overlays, keyframe_moment, shot_local_location, location_evidence, music_cues, narration_lines, planning_errors_in_current_rule_output, confidence, reasoning_brief。\n"
        "dialogue_annotations 每项字段：speaker, exact_text, listener, action_targets, gaze_rule。\n"
        "prop_handoffs 每项字段：from_shot, to_shot, prop_id, handoff_type, from_holder, to_holder, source_evidence, current_state, confidence。\n"
        "character_state_overlays 每项字段：character, state_id, source_basis, evidence_quote, body_state, visible_constraints, negative_constraints, key_props, scope。\n"
        "\n"
        "输入：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def normalize_semantic_prop_id(value: Any) -> str:
    return re.sub(r"[^A-Z0-9_]", "", str(value or "").strip().upper())


def normalize_semantic_prop_handoffs(row: dict[str, Any], aliases: dict[str, str], shot_id: str) -> list[dict[str, Any]]:
    handoffs: list[dict[str, Any]] = []
    raw_items = row.get("prop_handoffs")
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        return handoffs
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        prop_id = normalize_semantic_prop_id(item.get("prop_id"))
        from_shot = str(item.get("from_shot") or "").strip().upper()
        to_shot = str(item.get("to_shot") or shot_id).strip().upper()
        if not prop_id or to_shot != shot_id:
            continue
        handoffs.append(
            {
                "from_shot": from_shot,
                "to_shot": to_shot,
                "prop_id": prop_id,
                "handoff_type": str(item.get("handoff_type") or "").strip(),
                "from_holder": normalize_semantic_name(str(item.get("from_holder") or ""), aliases),
                "to_holder": normalize_semantic_name(str(item.get("to_holder") or ""), aliases),
                "source_evidence": str(item.get("source_evidence") or "").strip(),
                "current_state": str(item.get("current_state") or "").strip(),
                "confidence": str(item.get("confidence") or "").strip(),
            }
        )
    return handoffs


def semantic_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def normalize_state_id(value: Any, fallback: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    return text or fallback


def normalize_semantic_character_state_overlays(
    row: dict[str, Any],
    aliases: dict[str, str],
    shot_id: str,
) -> list[dict[str, Any]]:
    raw_items = row.get("character_state_overlays")
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        return []
    overlays: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        character = normalize_semantic_name(str(item.get("character") or item.get("name") or ""), aliases)
        if not character:
            continue
        body_state = str(item.get("body_state") or item.get("state") or item.get("visible_state") or "").strip()
        visible_constraints = semantic_text_list(item.get("visible_constraints") or item.get("visual_constraints"))
        negative_constraints = semantic_text_list(item.get("negative_constraints") or item.get("must_not"))
        key_props = semantic_text_list(item.get("key_props") or item.get("props"))
        source_basis = str(item.get("source_basis") or "").strip()
        evidence_quote = str(item.get("evidence_quote") or item.get("source_evidence") or "").strip()
        if not (body_state or visible_constraints or negative_constraints or key_props):
            continue
        overlays.append(
            {
                "character": character,
                "state_id": normalize_state_id(item.get("state_id"), f"{shot_id.lower()}_state_{index}"),
                "source_basis": source_basis,
                "evidence_quote": evidence_quote,
                "body_state": body_state,
                "visible_constraints": visible_constraints,
                "negative_constraints": negative_constraints,
                "key_props": key_props,
                "scope": "shot_local",
                **({"keyframe_moment": str(item.get("keyframe_moment") or "").strip()} if str(item.get("keyframe_moment") or "").strip() else {}),
            }
        )
    return overlays


def normalize_semantic_location_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lower = text.lower()
    aliases = {
        "kindergarten interview": "幼儿园教室（面试现场）",
        "kindergarten classroom": "幼儿园教室",
        "classroom doorway": "幼儿园教室门口",
        "bus interior": "公交车内",
        "market": "菜市场",
    }
    for token, replacement in aliases.items():
        if token in lower:
            return replacement
    return normalize_scene_name(text)


def semantic_location_evidence_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(item or "").strip() for item in value.values() if str(item or "").strip())
    if isinstance(value, list):
        return " ".join(semantic_location_evidence_text(item) for item in value)
    return str(value or "").strip()


def normalize_semantic_location_override(row: dict[str, Any], draft: ShotDraft) -> dict[str, str]:
    location = normalize_semantic_location_text(
        row.get("shot_local_location")
        or row.get("scene_name_override")
        or row.get("location_override")
        or row.get("resolved_scene_name")
    )
    if not location:
        return {}
    raw_evidence = (
        row.get("location_evidence")
        or row.get("shot_local_location_evidence")
        or row.get("location_source_evidence")
        or row.get("scene_name_evidence")
    )
    evidence_text = semantic_location_evidence_text(raw_evidence)
    if not evidence_text:
        return {}
    support_text = f"{evidence_text} {draft.shot_context_excerpt} {draft.source_excerpt}"
    if not any(token in support_text for token, _, _, _ in LOCAL_SCENE_RULES):
        return {}
    basis = ""
    excerpt = evidence_text
    if isinstance(raw_evidence, dict):
        basis = str(raw_evidence.get("source_basis") or raw_evidence.get("basis") or raw_evidence.get("line") or "").strip()
        excerpt = str(raw_evidence.get("evidence_quote") or raw_evidence.get("quote") or raw_evidence.get("excerpt") or evidence_text).strip()
    return {
        "shot_local_location": location,
        "location_basis": basis or "semantic_location_evidence",
        "location_excerpt": excerpt,
    }


def normalize_semantic_narration_lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    for item in value:
        if isinstance(item, dict):
            raw = item.get("exact_text") or item.get("text") or item.get("line") or item.get("content") or ""
        else:
            raw = item
        text = str(raw).strip()
        if not text or "音乐提示" in text or is_transition_only_text(text):
            continue
        lines.append(text)
    return lines


def group_visible_character_state_overlays(
    overlays: Any,
    visible_names: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(overlays, list) or not overlays:
        return {}
    visible = set(visible_names)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in overlays:
        if not isinstance(item, dict):
            continue
        character = str(item.get("character") or "").strip()
        if not character or character not in visible:
            continue
        clean = {
            key: value
            for key, value in item.items()
            if key != "character" and value not in ("", [], {}, None)
        }
        clean["scope"] = "shot_local"
        grouped.setdefault(character, []).append(clean)
    return grouped


def repair_character_state_overlay_source_fidelity(item: dict[str, Any]) -> None:
    combined = " ".join(
        [
            str(item.get("state_id") or ""),
            str(item.get("body_state") or ""),
            str(item.get("evidence_quote") or ""),
        ]
    )
    evidence = str(item.get("evidence_quote") or "")
    claims_postpartum = any(token in combined.lower() for token in ("postpartum", "post-delivery")) or "产后" in combined
    has_postpartum_evidence = any(token in evidence for token in ("产后", "生完", "生产后", "新生儿", "婴儿", "抱着孩子", "抱着婴儿", "出生"))
    has_late_pregnancy_evidence = any(token in evidence for token in ("肚子已经很大", "孕", "怀孕", "大肚子", "撑着腰"))
    if claims_postpartum and has_late_pregnancy_evidence and not has_postpartum_evidence:
        item["state_id"] = "late_pregnancy"
        item["body_state"] = "孕晚期，腹部明显隆起，独自撑腰走出医院门口"
    claims_late_pregnancy = str(item.get("state_id") or "").strip() == "late_pregnancy" or "孕晚期" in str(item.get("body_state") or "")
    if claims_late_pregnancy and has_late_pregnancy_evidence:
        visible_constraints = semantic_text_list(item.get("visible_constraints"))
        visible_constraints = [
            rule
            for rule in visible_constraints
            if not any(token in rule for token in ("腹部平坦", "无孕肚", "抱着婴儿", "抱婴儿", "新生儿"))
        ]
        for rule in ("腹部明显隆起", "撑腰步态", "独自拎着编织袋"):
            if rule not in visible_constraints:
                visible_constraints.append(rule)
        item["visible_constraints"] = visible_constraints
        negative_constraints = semantic_text_list(item.get("negative_constraints"))
        negative_constraints = [
            rule
            for rule in negative_constraints
            if not any(token in rule for token in ("无孕肚", "恢复初期", "恢复状态"))
        ]
        for rule in ("不要产后恢复状态", "不要抱婴儿，除非当前镜头原文明确写明"):
            if rule not in negative_constraints:
                negative_constraints.append(rule)
        item["negative_constraints"] = negative_constraints
        key_props = [
            prop
            for prop in semantic_text_list(item.get("key_props"))
            if not any(token in prop.lower() for token in ("newborn", "baby", "infant", "婴儿", "新生儿"))
        ]
        item["key_props"] = key_props
        keyframe_moment = str(item.get("keyframe_moment") or "").strip()
        if keyframe_moment and any(token in keyframe_moment for token in ("抱着婴儿", "抱婴儿", "新生儿", "孩子")) and not has_postpartum_evidence:
            item["keyframe_moment"] = "中景走出医院门，撑腰拎编织袋"
        if claims_postpartum and not has_postpartum_evidence:
            item["semantic_fidelity_repair"] = "postpartum label removed because evidence only supports late pregnancy in this shot moment"
        else:
            item.setdefault("semantic_fidelity_repair", "late pregnancy constraints aligned to source evidence")
    evidence_key_props = semantic_text_list(item.get("key_props"))
    if "验孕棒" in evidence and "验孕棒" not in evidence_key_props:
        evidence_key_props.append("验孕棒")
        item["key_props"] = evidence_key_props


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

STATE_CONSTRAINT_SPLIT_RE = re.compile(r"\s*(?:[,，;；/、]|\band\b|\bwith\b)\s*", re.IGNORECASE)


def split_state_constraint_fragments(rule: str) -> list[str]:
    fragments = [item.strip() for item in STATE_CONSTRAINT_SPLIT_RE.split(str(rule or "")) if item.strip()]
    return fragments or ([str(rule).strip()] if str(rule or "").strip() else [])


def is_back_view_constraint_fragment(fragment: str) -> bool:
    lowered = fragment.lower()
    return any(token in lowered for token in BACK_VIEW_CONSTRAINT_TOKENS)


def normalize_state_constraint_fragment(fragment: str) -> str:
    text = str(fragment or "").strip()
    lowered = text.lower()
    child_hold_tokens = (
        "holding child",
        "holding a child",
        "holding baby",
        "holding a baby",
        "holding infant",
        "holding an infant",
    )
    child_carry_tokens = (
        "carrying child",
        "carrying a child",
        "carrying baby",
        "carrying a baby",
        "carrying infant",
        "carrying an infant",
    )
    if any(token in lowered for token in child_hold_tokens):
        if any(token in lowered for token in ("stop", "stopped", "paused")):
            return "停下脚步时怀中抱着孩子，孩子首帧可见且不得消失"
        if any(token in lowered for token in ("walk", "walking", "away", "leaving")):
            return "行走/离开时怀中抱着孩子，孩子首帧可见且不得消失"
        return "怀中抱着孩子，孩子首帧可见且不得消失"
    if any(token in lowered for token in child_carry_tokens):
        return "抱着孩子移动，孩子首帧可见且不得消失"
    return text


def repair_character_state_overlay_face_visibility(item: dict[str, Any]) -> None:
    visible_constraints = semantic_text_list(item.get("visible_constraints"))
    if not any(any(token in rule.lower() for token in BACK_VIEW_CONSTRAINT_TOKENS) for rule in visible_constraints):
        return
    repaired_constraints: list[str] = []
    for rule in visible_constraints:
        for fragment in split_state_constraint_fragments(rule):
            if is_back_view_constraint_fragment(fragment):
                continue
            normalized = normalize_state_constraint_fragment(fragment)
            if normalized and normalized not in repaired_constraints:
                repaired_constraints.append(normalized)
    face_visible_rule = "行走/离开姿态可见，但首帧仍需正侧脸或三分之二侧脸可辨认"
    if face_visible_rule not in repaired_constraints:
        repaired_constraints.append(face_visible_rule)
    item["visible_constraints"] = repaired_constraints

    negative_constraints = semantic_text_list(item.get("negative_constraints"))
    for rule in ("不得只有背影或后脑作为主体", "不得让说话人的脸和嘴不可辨认"):
        if rule not in negative_constraints:
            negative_constraints.append(rule)
    item["negative_constraints"] = negative_constraints
    item["face_visibility_repair"] = "back-view state constraint softened because visible shot subjects must keep face and mouth identifiable"


def character_state_overlay_prompt_text(character_state_overlay: dict[str, Any]) -> str:
    entries: list[str] = []
    for character, raw_items in character_state_overlay.items():
        items = raw_items if isinstance(raw_items, list) else [raw_items]
        state_parts: list[str] = []
        negative_parts: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            for value in semantic_text_list(item.get("visible_constraints")):
                normalized = normalize_state_constraint_fragment(value)
                if normalized and normalized not in state_parts:
                    state_parts.append(normalized)
            for value in semantic_text_list(item.get("key_props")):
                if value and f"关键状态物：{value}" not in state_parts:
                    state_parts.append(f"关键状态物：{value}")
            for value in semantic_text_list(item.get("negative_constraints")):
                if value and value not in negative_parts:
                    negative_parts.append(value)
        if not state_parts and not negative_parts:
            continue
        text = f"{character}状态连续锁：" + "；".join(state_parts)
        if negative_parts:
            text += "；" + "；".join(negative_parts)
        entries.append(text)
    return " ".join(entries)


def normalize_semantic_annotations(payload: dict[str, Any], drafts: list[ShotDraft], characters: list[n2v.Character]) -> dict[str, dict[str, Any]]:
    aliases = character_alias_table(characters)
    draft_by_id = {draft.shot_id: draft for draft in drafts}
    annotations: dict[str, dict[str, Any]] = {}
    rows = payload.get("shots") if isinstance(payload.get("shots"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        shot_id = str(row.get("shot_id") or "").strip().upper()
        draft = draft_by_id.get(shot_id)
        if not draft:
            continue
        dialogue_by_text = {str(item.get("text") or "").strip(): item for item in draft.dialogue}
        dialogue_annotations: list[dict[str, Any]] = []
        for item in row.get("dialogue_annotations", []) if isinstance(row.get("dialogue_annotations"), list) else []:
            if not isinstance(item, dict):
                continue
            exact_text = str(item.get("exact_text") or item.get("line") or item.get("text") or "").strip()
            if exact_text not in dialogue_by_text:
                continue
            original = dialogue_by_text[exact_text]
            speaker = normalize_semantic_name(str(item.get("speaker") or original.get("speaker") or ""), aliases)
            if speaker != str(original.get("speaker") or "").strip():
                continue
            listener = normalize_semantic_name(str(item.get("listener") or item.get("addressee") or item.get("listener/addressee") or ""), aliases)
            action_targets = normalize_semantic_name_list(item.get("action_targets") or item.get("action_target") or [], aliases)
            dialogue_annotations.append(
                {
                    "speaker": speaker,
                    "exact_text": exact_text,
                    "listener": listener,
                    "action_targets": action_targets,
                    "gaze_rule": str(item.get("gaze_rule") or "").strip(),
                }
            )
        visible = normalize_semantic_name_list(row.get("visible_characters"), aliases)
        annotations[shot_id] = {
            "visible_characters": visible,
            "dialogue_annotations": dialogue_annotations,
            "prop_handoffs": normalize_semantic_prop_handoffs(row, aliases, shot_id),
            "character_state_overlays": normalize_semantic_character_state_overlays(row, aliases, shot_id),
            "keyframe_moment": str(row.get("keyframe_moment") or "").strip(),
            "location_override": normalize_semantic_location_override(row, draft),
            "music_cues": [str(item).strip() for item in row.get("music_cues", []) if str(item).strip()]
            if isinstance(row.get("music_cues"), list)
            else [],
            "narration_lines": normalize_semantic_narration_lines(row.get("narration_lines")),
            "quality": {
                "confidence": row.get("confidence"),
                "reasoning_brief": str(row.get("reasoning_brief") or "").strip(),
                "planning_errors_in_current_rule_output": str(row.get("planning_errors_in_current_rule_output") or "").strip(),
            },
        }
    return annotations


def semantic_provider_candidates(args: argparse.Namespace) -> list[tuple[str, str, str, str]]:
    backend = str(getattr(args, "semantic_backend", "auto") or "auto").strip().lower()
    candidates: list[tuple[str, str, str, str]] = []
    if backend in {"none", "heuristic"}:
        return []
    if backend in {"auto", "grok", "xai"}:
        models = [str(getattr(args, "semantic_model", "") or "").strip()] if str(getattr(args, "semantic_model", "") or "").strip() else DEFAULT_GROK_SEMANTIC_MODELS
        for model in models:
            candidates.append(("grok", model, "XAI_API_KEY", "https://api.x.ai/v1"))
    if backend in {"auto", "openai"}:
        model = str(getattr(args, "openai_semantic_model", "") or "").strip() or DEFAULT_OPENAI_SEMANTIC_MODEL
        candidates.append(("openai", model, "OPENAI_API_KEY", "https://api.openai.com/v1"))
    return candidates


def run_screen_semantic_pass(
    args: argparse.Namespace,
    parsed: ParsedScript,
    drafts: list[ShotDraft],
    characters: list[n2v.Character],
    out_dir: Path,
) -> tuple[dict[str, dict[str, Any]], n2v.LLMRunResult]:
    backend = str(getattr(args, "semantic_backend", "auto") or "auto").strip().lower()
    if backend in {"none", "heuristic"}:
        return {}, n2v.LLMRunResult("screen_script_semantic", backend, "none", bool(args.dry_run), [], [], False)
    llm_dir = out_dir / "llm_requests"
    request_path = llm_dir / "screen_semantic_annotation.request.json"
    response_path = llm_dir / "screen_semantic_annotation.response.json"
    prompt = build_semantic_probe_prompt(
        parsed=parsed,
        drafts=drafts,
        characters=characters,
        context_before=max(1, int(getattr(args, "semantic_context_before", 40))),
        context_after=max(1, int(getattr(args, "semantic_context_after", 16))),
    )
    request_files = [str(request_path)]
    fallbacks: list[dict[str, str]] = []
    if args.dry_run:
        return {}, n2v.LLMRunResult("screen_script_semantic", backend, "dry-run", True, request_files, [{"task": "screen_semantic_annotation", "reason": "dry-run enabled; heuristic semantics kept"}], False)
    if requests is None:
        return {}, n2v.LLMRunResult("screen_script_semantic", backend, "none", False, request_files, [{"task": "screen_semantic_annotation", "reason": "requests package unavailable; heuristic semantics kept"}], False)

    llm_dir.mkdir(parents=True, exist_ok=True)
    last_error = ""
    for provider, model, key_env, base_url in semantic_provider_candidates(args):
        api_key = os.getenv(key_env, "").strip()
        if not api_key:
            fallbacks.append({"task": "screen_semantic_annotation", "reason": f"{key_env} is not set; skipped {provider}"})
            continue
        request = n2v.openai_responses_payload(model, prompt, "none", int(getattr(args, "semantic_max_output_tokens", 12000)))
        n2v.write_json(request_path, n2v.make_llm_task_request("screen_semantic_annotation", request, provider, model), args.overwrite)
        try:
            payload, raw = n2v.call_openai_json_with_retries(
                request,
                api_key,
                base_url,
                int(getattr(args, "semantic_timeout_sec", 180)),
                int(getattr(args, "semantic_retry_count", 2)),
                int(getattr(args, "semantic_retry_wait_sec", 8)),
            )
            annotations = normalize_semantic_annotations(payload, drafts, characters)
            if not annotations:
                raise RuntimeError("semantic response produced no usable annotations")
            n2v.write_json(response_path, {"provider": provider, "model": model, "parsed": payload, "raw": raw}, args.overwrite)
            print(f"[INFO] screen semantic annotation applied: {provider}/{model} shots={len(annotations)}")
            return annotations, n2v.LLMRunResult("screen_script_semantic", provider, model, False, request_files, fallbacks, True)
        except Exception as exc:
            last_error = str(exc)
            fallbacks.append({"task": "screen_semantic_annotation", "reason": f"{provider}/{model} failed: {last_error[:240]}"})
            print(f"[WARN] screen semantic annotation failed with {provider}/{model}: {last_error[:240]}", file=sys.stderr)
            if int(getattr(args, "semantic_retry_wait_sec", 8)) > 0:
                time.sleep(min(2, int(getattr(args, "semantic_retry_wait_sec", 8))))
    fallbacks.append({"task": "screen_semantic_annotation", "reason": "all semantic providers failed; heuristic semantics kept"})
    return {}, n2v.LLMRunResult("screen_script_semantic", backend, "none", False, request_files, fallbacks, False)


def should_run_character_location_tracking(args: argparse.Namespace) -> bool:
    return not bool(getattr(args, "no_character_location_tracking", False))


def should_fail_fast_location_tracking(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "strict_location_tracking", False)) or not bool(getattr(args, "dry_run", False))


def screen_location_tracker_inputs(
    parsed: ParsedScript,
    drafts: list[ShotDraft],
    semantic_annotations: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    previous: dict[str, Any] = {}
    for draft in drafts:
        row = {
            "shot_id": draft.shot_id,
            "scene_name": draft.scene_name,
            "parent_scene_name": draft.parent_scene_name,
            "source_excerpt": draft.source_excerpt,
            "context_excerpt": draft.shot_context_excerpt or line_context_excerpt(parsed.script_path, draft.line_start, draft.line_end),
            "visual_texts": draft.visual_texts,
            "dialogue": draft.dialogue,
            "selection_plan": draft.selection_plan,
            "semantic_annotation": semantic_annotations.get(draft.shot_id, {}),
            "previous_state": previous,
        }
        rows.append(row)
        previous = {
            "shot_id": draft.shot_id,
            "scene_name": draft.scene_name,
            "source_excerpt": ssp.compact_text(draft.source_excerpt, 400),
            "selection_plan": draft.selection_plan,
        }
    return rows


def run_screen_character_location_tracking(
    args: argparse.Namespace,
    parsed: ParsedScript,
    drafts: list[ShotDraft],
    semantic_annotations: dict[str, dict[str, Any]],
    characters: list[n2v.Character],
    out_dir: Path,
) -> tuple[dict[str, dict[str, Any]], clt.LocationQAReport | None, list[dict[str, str]]]:
    if not should_run_character_location_tracking(args):
        return {}, None, [{"task": "character_location_tracker", "reason": "disabled by --no-character-location-tracking"}]
    rows = screen_location_tracker_inputs(parsed, drafts, semantic_annotations)
    character_payload = [{"name": c.name, "character_id": c.character_id, "aliases": [c.name, c.character_id, c.lock_profile_id]} for c in characters]
    fallbacks: list[dict[str, str]] = []
    if args.dry_run:
        provider, model, key_env, base_url = (semantic_provider_candidates(args) or [("dry-run", "dry-run", "", "")])[0]
        trace, qa, meta = clt.run_llm_tracking(
            source_type="screen",
            episode_id=parsed.episode_id,
            title=parsed.title,
            shots=rows,
            characters=character_payload,
            out_dir=out_dir,
            provider=provider,
            model=model,
            api_key_env=key_env,
            base_url=base_url or "https://api.openai.com/v1",
            timeout_sec=int(getattr(args, "semantic_timeout_sec", 180)),
            retry_count=int(getattr(args, "semantic_retry_count", 2)),
            retry_wait_sec=int(getattr(args, "semantic_retry_wait_sec", 8)),
            max_output_tokens=int(getattr(args, "semantic_max_output_tokens", 12000)),
            overwrite=args.overwrite,
            dry_run=True,
        )
        fallbacks.append({"task": "character_location_tracker", "reason": f"dry-run request only: {meta.get('request_path', '')}"})
        return trace, qa, fallbacks
    last_error = ""
    for provider, model, key_env, base_url in semantic_provider_candidates(args):
        if not os.getenv(key_env, "").strip():
            fallbacks.append({"task": "character_location_tracker", "reason": f"{key_env} is not set; skipped {provider}"})
            continue
        try:
            trace, qa, _ = clt.run_llm_tracking(
                source_type="screen",
                episode_id=parsed.episode_id,
                title=parsed.title,
                shots=rows,
                characters=character_payload,
                out_dir=out_dir,
                provider=provider,
                model=model,
                api_key_env=key_env,
                base_url=base_url,
                timeout_sec=int(getattr(args, "semantic_timeout_sec", 180)),
                retry_count=int(getattr(args, "semantic_retry_count", 2)),
                retry_wait_sec=int(getattr(args, "semantic_retry_wait_sec", 8)),
                max_output_tokens=int(getattr(args, "semantic_max_output_tokens", 12000)),
                overwrite=args.overwrite,
                dry_run=False,
            )
            if qa and not qa.passed and should_fail_fast_location_tracking(args):
                high = [item for item in qa.findings if item.get("severity") == "high"]
                raise RuntimeError(f"character location tracker QA failed: {high[:5]}")
            print(f"[INFO] character location tracker applied: {provider}/{model} shots={len(trace)}")
            return trace, qa, fallbacks
        except Exception as exc:
            last_error = str(exc)
            fallbacks.append({"task": "character_location_tracker", "reason": f"{provider}/{model} failed: {last_error[:240]}"})
            if should_fail_fast_location_tracking(args):
                raise
    if should_fail_fast_location_tracking(args):
        raise RuntimeError(f"character location tracker failed: {last_error or 'no provider available'}")
    return {}, None, fallbacks


def append_unique_name(names: list[str], name: str) -> None:
    clean = str(name or "").strip()
    if clean and clean not in names:
        names.append(clean)


def character_alias_table(characters: list[n2v.Character]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for character in characters:
        aliases[character.name] = character.name
        aliases[character.character_id] = character.name
        aliases[character.lock_profile_id] = character.name
        for alias in n2v.character_aliases(character):
            aliases[str(alias)] = character.name
    aliases.update(
        {
            "予予": "沈知予",
            "妈咪": "沈念歌",
            "妈妈": "沈念歌",
            "那个男人": "陆景琛",
            "西装男人": "陆景琛",
            "叔叔": "陆景琛",
            "陆总": "陆景琛",
        }
    )
    return {key: value for key, value in aliases.items() if key and value}


def normalize_semantic_name(value: str, aliases: dict[str, str]) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text in aliases:
        return aliases[text]
    for alias, name in aliases.items():
        if alias and alias in text:
            return name
    return text


def normalize_semantic_name_list(values: Any, aliases: dict[str, str]) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    names: list[str] = []
    for value in values:
        name = normalize_semantic_name(str(value), aliases)
        append_unique_name(names, name)
    return names


def semantic_character_target_names(values: Any, aliases: dict[str, str]) -> list[str]:
    names = normalize_semantic_name_list(values, aliases)
    return [
        name
        for name in names
        if name in KNOWN_CHARACTER_SPECS or is_ephemeral_name(name)
    ]


def infer_relationship_visible_names(
    names: list[str],
    draft: ShotDraft,
    local_text: str,
    context_text: str,
) -> None:
    local = str(local_text or "")
    context = str(context_text or "")
    combined = f"{local} {context}"
    present = set(names)

    mother_child_local_tokens = (
        "妈咪",
        "妈妈",
        "予予",
        "儿子",
        "小男孩",
        "孩子",
        "母子",
        "背带",
        "牵住他",
        "牵着",
        "拉住予予",
        "拉了拉沈念歌的手",
        "帮他整理",
        "摸了摸他的头",
        "抱着",
        "怀里",
        "靠在她",
        "靠着她",
        "被拖走",
        "回头冲",
        "仰头看她",
        "偷偷哭",
    )
    mother_child_context_tokens = (
        "母子",
        "妈咪",
        "予予",
        "儿子",
        "孩子",
        "靠在她怀里",
        "牵着予予",
        "门口的台阶",
    )
    has_local_mother_child = any(token in local for token in mother_child_local_tokens)
    has_context_mother_child = any(token in context for token in mother_child_context_tokens)
    if {"沈念歌", "沈知予"} & present and (has_local_mother_child or has_context_mother_child):
        if "沈知予" in present or "予予" in combined or "儿子" in combined or "孩子" in combined or "小男孩" in combined:
            append_unique_name(names, "沈念歌")
            append_unique_name(names, "沈知予")
        elif "沈念歌" in present and any(token in combined for token in ("妈咪", "妈妈", "予予")):
            append_unique_name(names, "沈知予")

    if "沈知予" in set(names) and any(token in local for token in ("叔叔", "爸爸", "长得和你", "一模一样")):
        if draft.scene_name and "VIP" in draft.scene_name or any(token in context for token in ("陆景琛", "那个男人", "陆总")):
            append_unique_name(names, "陆景琛")
    if not names and any(token in local for token in ("一个男人", "那个男人", "西装男人")):
        if any(token in context for token in ("这是陆景琛", "陆景琛", "陆总")):
            append_unique_name(names, "陆景琛")
        else:
            append_unique_name(names, "西装男人")


def blurred_visual_shot_uses_unnamed_figures(draft: ShotDraft) -> bool:
    if draft.dialogue:
        return False
    text = f"{' '.join(draft.visual_texts)} {draft.source_excerpt}"
    return "模糊" in text and any(token in text for token in ("身影", "人影", "轮廓"))


def unnamed_blurred_figure_foreground_count(text: str) -> int:
    raw = str(text or "")
    if "模糊" not in raw or not any(token in raw for token in ("身影", "人影", "轮廓")):
        return 0
    if "两个人" in raw or "两个模糊" in raw or "两个身影" in raw:
        return 2
    return 0


def explicit_character_names_in_shot_text(
    draft: ShotDraft,
    characters: list[n2v.Character],
) -> set[str]:
    text = f"{' '.join(draft.visual_texts)} {draft.source_excerpt}"
    names: set[str] = set()
    for character in characters:
        if character.name and character.name in text:
            names.add(character.name)
    return names


def visible_names_for_draft(
    draft: ShotDraft,
    characters: list[n2v.Character],
    context_text: str = "",
) -> list[str]:
    names: list[str] = []
    local_parts: list[str] = []
    for line in draft.dialogue:
        source = str(line.get("source") or "onscreen")
        local_parts.append(str(line.get("text") or ""))
        if source == "onscreen":
            append_unique_name(names, str(line.get("speaker") or ""))
        elif line.get("listener"):
            append_unique_name(names, str(line.get("listener") or ""))
    visual_text = " ".join(draft.visual_texts)
    local_parts.append(visual_text)
    local_parts.append(draft.source_excerpt)
    documentish = any(token in f"{visual_text} {draft.source_excerpt}" for token in ("简报", "报告", "电脑屏幕", "通讯录", "文件抬头"))
    for character in characters:
        if any(alias in visual_text for alias in n2v.character_aliases(character)):
            if documentish and character.name in {"沈念歌", "沈知予"}:
                continue
            append_unique_name(names, character.name)
    local_text = " ".join(local_parts)
    if not names and not draft.dialogue:
        if "她" in local_text and "沈念歌" in context_text:
            append_unique_name(names, "沈念歌")
        elif "他" in local_text and (
            any(token in context_text for token in ("陆景琛", "陆总", "总裁办公室"))
            or "总裁办公室" in draft.scene_name
        ):
            append_unique_name(names, "陆景琛")
    infer_relationship_visible_names(names, draft, local_text, context_text)
    return hard_visible_character_names(names)


def featured_character_for_draft(draft: ShotDraft, visible_names: list[str]) -> str:
    for line in draft.dialogue:
        source = str(line.get("source") or "onscreen")
        if source == "onscreen":
            speaker = str(line.get("speaker") or "").strip()
            if speaker in visible_names:
                return speaker
        listener = str(line.get("listener") or "").strip()
        if listener in visible_names:
            return listener
    return visible_names[0] if visible_names else ""


def infer_onscreen_dialogue_listener(
    speaker: str,
    dialogue_text: str,
    performance: str,
    visible_names: list[str],
    context_text: str,
) -> str:
    """Infer who the speaker addresses without rewriting story events."""
    speaker = str(speaker or "").strip()
    text = f"{dialogue_text} {performance}".strip()
    context = str(context_text or "")
    visible = set(visible_names)
    if not speaker:
        return ""
    if "自言自语" in performance or "自言自语" in text:
        return ""

    if speaker == "沈知予":
        if "陆景琛" in visible and any(token in text for token in ("叔叔", "爸爸", "你", "和你", "一模一样")):
            return "陆景琛"
        if "沈念歌" in visible and any(token in text for token in ("妈咪", "妈妈", "你", "手术费", "偷偷哭", "叔叔是不是")):
            return "沈念歌"
        for candidate in ("陆景琛", "沈念歌"):
            if candidate in visible:
                return candidate

    if speaker == "沈念歌":
        if "爸" in text and any(token in context for token in ("拨了一个号码", "掏出手机", "电话")):
            return "父亲（电话）"
        if "陆景琛" in visible and any(token in text + context for token in ("陆总", "对不起", "走错", "马上就走", "四目相对")):
            return "陆景琛"
        if "沈知予" in visible and any(token in text + context for token in ("予予", "妈咪", "小蝴蝶", "鸡腿", "挂号", "不需要任何人", "摸了摸他的头", "牵住他的手")):
            return "沈知予"
        for candidate in ("沈知予", "陆景琛"):
            if candidate in visible:
                return candidate

    if speaker == "陆景琛":
        if "赵一鸣" in visible or any(token in context for token in ("赵一鸣", "陆总", "凑过来", "电话那头")):
            return "赵一鸣"
        if "沈念歌" in visible and any(token in text + context for token in ("你", "四目相对", "盯着她")):
            return "沈念歌"
        for candidate in ("赵一鸣", "沈念歌", "沈知予"):
            if candidate in visible:
                return candidate

    if speaker == "赵一鸣":
        if "陆景琛" in visible or "陆总" in text or any(token in context for token in ("陆景琛", "陆总", "电话那头")):
            return "陆景琛"
        for candidate in ("陆景琛", "沈知予", "沈念歌"):
            if candidate in visible:
                return candidate

    other_visible = [name for name in visible_names if name and name != speaker]
    return other_visible[0] if len(other_visible) == 1 else ""


NO_LOOK_BACK_TOKENS = (
    "头也没回",
    "没回头",
    "不回头",
    "没有回头",
    "背对",
    "背向",
    "侧背",
)


MOVE_AWAY_TOKENS = (
    "继续走",
    "边走",
    "往前走",
    "走开",
    "走远",
    "离开",
    "走出去",
    "转身就走",
    "转身离开",
    "头也没回",
    "没回头",
)


STOP_OR_CONTINUE_DIALOGUE_TOKENS = (
    "停下脚步",
    "停住",
    "停了下来",
    "站住",
    "回头",
    "转过头",
    "转过身",
    "继续说",
    "又说",
    "再说",
)


def text_has_any_token(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def dialogue_no_look_back_override(item: dict[str, Any], context_text: str) -> bool:
    combined = " ".join(
        [
            str(item.get("performance") or ""),
            str(item.get("semantic_gaze_rule") or ""),
            str(item.get("text") or ""),
        ]
    )
    return text_has_any_token(combined, NO_LOOK_BACK_TOKENS)


def dialogue_speaker_matching_tokens(draft: ShotDraft, tokens: tuple[str, ...]) -> str:
    for item in draft.dialogue:
        combined = " ".join(
            [
                str(item.get("speaker") or ""),
                str(item.get("text") or ""),
                str(item.get("performance") or ""),
                str(item.get("semantic_gaze_rule") or ""),
            ]
        )
        if text_has_any_token(combined, tokens):
            return str(item.get("speaker") or "").strip()
    return ""


def same_primary_dialogue_speaker(current: ShotDraft, next_draft: ShotDraft) -> str:
    current_speaker = dialogue_speaker_matching_tokens(current, MOVE_AWAY_TOKENS + NO_LOOK_BACK_TOKENS)
    next_speaker = dialogue_speaker_matching_tokens(next_draft, STOP_OR_CONTINUE_DIALOGUE_TOKENS)
    if not current_speaker and current.dialogue:
        current_speaker = str(current.dialogue[0].get("speaker") or "").strip()
    if not next_speaker and next_draft.dialogue:
        next_speaker = str(next_draft.dialogue[0].get("speaker") or "").strip()
    return current_speaker if current_speaker and current_speaker == next_speaker else ""


def draft_resolved_scene_name(
    draft: ShotDraft,
    semantic_annotations: dict[str, dict[str, Any]],
) -> str:
    semantic = semantic_annotations.get(draft.shot_id, {})
    location_override = semantic.get("location_override") if isinstance(semantic.get("location_override"), dict) else {}
    return str(location_override.get("shot_local_location") or draft.scene_name or "").strip()


def build_adjacent_movement_boundary(
    *,
    draft: ShotDraft,
    next_draft: ShotDraft | None,
    semantic_annotations: dict[str, dict[str, Any]],
    resolved_scene_name: str,
    prompt_text: str,
    keyframe_moment: str,
    character_state_overlay: dict[str, Any],
) -> dict[str, Any]:
    if next_draft is None:
        return {}
    character = same_primary_dialogue_speaker(draft, next_draft)
    if not character:
        return {}
    next_scene_name = draft_resolved_scene_name(next_draft, semantic_annotations)
    same_scene = bool(resolved_scene_name and next_scene_name and resolved_scene_name == next_scene_name)
    same_parent_scene = bool(draft.parent_scene_name and draft.parent_scene_name == next_draft.parent_scene_name)
    if not (same_scene or same_parent_scene):
        return {}

    overlay_text_parts: list[str] = []
    for raw_items in character_state_overlay.values():
        items = raw_items if isinstance(raw_items, list) else [raw_items]
        for item in items:
            if isinstance(item, dict):
                overlay_text_parts.extend(
                    [
                        str(item.get("evidence_quote") or ""),
                        str(item.get("body_state") or ""),
                        str(item.get("keyframe_moment") or ""),
                    ]
                )
    current_text = " ".join(
        [
            draft.source_excerpt,
            " ".join(draft.visual_texts),
            prompt_text,
            keyframe_moment,
            " ".join(overlay_text_parts),
        ]
    )
    next_text = " ".join(
        [
            next_draft.source_excerpt,
            " ".join(next_draft.visual_texts),
        ]
    )
    if not text_has_any_token(current_text, MOVE_AWAY_TOKENS):
        return {}
    if not (text_has_any_token(next_text, STOP_OR_CONTINUE_DIALOGUE_TOKENS) or next_draft.dialogue):
        return {}

    return {
        "policy": "adjacent_shot_motion_continuity",
        "character": character,
        "source_action": "保留本镜头原文移动/离开意图",
        "allowed_motion": f"{character}可以继续走或边走边说，但只允许小幅横向/斜向位移、一两步以内；镜头从侧面或侧前方看见脸和嘴",
        "forbidden_motion": f"{character}不得走远、不得出画、不得消失、不得变成远处背影，不要让听话人被彻底甩在画外",
        "end_state": f"{character}仍在画面内，步伐放慢或即将停下",
        "next_shot_bridge": f"为下一镜{next_draft.shot_id}中同一角色停下脚步或继续对话保留自然首帧衔接",
    }


def build_dialogue_addressing_contract(
    dialogue: list[dict[str, Any]],
    visible_names: list[str],
    context_text: str,
) -> dict[str, Any]:
    if not dialogue:
        return {}
    entries: list[dict[str, Any]] = []
    for item in dialogue:
        source = str(item.get("source") or "onscreen")
        speaker = str(item.get("speaker") or "").strip()
        if not speaker or source in {"offscreen", "voiceover"}:
            continue
        listener = str(item.get("listener") or "").strip()
        if listener == speaker:
            listener = ""
            item["listener"] = ""
        if not listener and source == "onscreen":
            listener = infer_onscreen_dialogue_listener(
                speaker=speaker,
                dialogue_text=str(item.get("text") or ""),
                performance=str(item.get("performance") or ""),
                visible_names=visible_names,
                context_text=context_text,
            )
            if listener:
                item["listener"] = listener
        if source == "phone":
            listener_text = listener or "画面内听者"
            gaze_target = "手机、通话方向或画外通话对象方向"
            policy = "phone_call_not_camera"
            rule = (
                f"{listener_text}听手机语音或电话远端声音时看向手机、通话方向或画外声音方向，"
                f"{speaker}是电话远端声音，不作为画面内实体人物出现，不直视镜头当作对观众说话"
            )
        elif listener and dialogue_no_look_back_override(item, context_text):
            target_visibility = "onscreen" if listener in visible_names else "offscreen"
            gaze_target = "不回头；保持行进方向，不看听话人"
            policy = "source_action_no_look_back_overrides_mutual_eyeline"
            if target_visibility == "onscreen":
                rule = (
                    f"原文动作优先：{speaker}说话时头也没回，不看向{listener}的脸部或眼睛；"
                    f"{listener}可以看向{speaker}或追随{speaker}方向；"
                    "构图必须从说话人侧面或侧前方取景，让说话人的侧脸/三分之二侧脸和嘴部对观众可辨认；"
                    "说话人可以保持身体朝行进方向、不回看听话人，但不得从背后拍、不得以后脑或背部作为主体；"
                    "脸部可见只服务观众识别和口型，不表示角色眼神看向听话人，也不能改成两人正面对视"
                )
            else:
                rule = (
                    f"原文动作优先：{speaker}说话时头也没回，不看向画外{listener}；"
                    "保持行进方向，镜头从侧面或侧前方取景，脸部和嘴部对观众可辨认；"
                    "不得从背后拍、不得以后脑或背部作为主体，也不能改成回头对视"
                )
        elif listener:
            target_visibility = "onscreen" if listener in visible_names else "offscreen"
            gaze_target = f"{listener}的脸部或眼睛" if target_visibility == "onscreen" else f"画外{listener}所在方向"
            policy = "mutual_speaker_listener_eyeline"
            if target_visibility == "onscreen":
                composition_rule = (
                    "构图采用侧面对话 two-shot：相机站在两人视线轴的侧面，"
                    "能直接看到双方脸部表情，尤其清楚看到说话人的脸和嘴；"
                    f"{speaker}以正脸、三分之二侧脸或清晰侧脸对着{listener}，"
                    f"{listener}以侧脸或三分之二侧脸回应；如果只能优先一方，优先看见说话人{speaker}的脸和嘴"
                )
                if speaker == "沈知予" and listener == "沈念歌":
                    composition_rule = (
                        "构图采用孩子说话人的侧前方视角：相机在沈知予前侧或侧前方，镜头高度接近孩子眼平；"
                        "沈知予必须露出脸、眼睛和嘴，抬头看沈念歌；沈念歌蹲在对面，以侧脸或三分之二侧脸回应；"
                        "前景主体必须呈现沈知予脸部表情，不能只呈现衣服轮廓或头发轮廓"
                    )
                rule = (
                    f"{speaker}说话时看向{listener}的脸部或眼睛；"
                    f"{listener}作为听话人也看着{speaker}或保持对{speaker}的清晰反应；"
                    "允许两人三分之二侧脸让观众看清表情，但眼神不能直视镜头/观众；"
                    f"{composition_rule}"
                )
            else:
                rule = f"{speaker}说话时看向画外的{listener}方向；脸部对观众可辨认，但眼神不能直视镜头/观众"
        else:
            gaze_target = "情境内目标方向"
            policy = "contextual_gaze_no_direct_camera"
            rule = f"{speaker}说话时看向情境内目标方向；除非剧本明确直视镜头，否则不要把台词说给观众"
        entries.append(
            {
                "speaker": speaker,
                "listener": listener,
                "source": source,
                "gaze_target": gaze_target,
                "listener_gaze_target": ""
                if source == "phone"
                else (f"{speaker}的脸部或眼睛" if listener and listener in visible_names else ""),
                "eye_contact_policy": policy,
                "rule": rule,
            }
        )
    if not entries:
        return {}
    return {
        "entries": entries,
        "global_rule": "对白表演优先服务角色关系；脸部可见表示五官对观众可辨认，不表示眼神看镜头或看观众。",
    }


def dialogue_addressing_text(contract: dict[str, Any]) -> str:
    if not isinstance(contract, dict) or not contract:
        return ""
    parts: list[str] = []
    entries = contract.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                rule = str(entry.get("rule") or "").strip()
                if rule:
                    parts.append(rule)
    global_rule = str(contract.get("global_rule") or "").strip()
    if global_rule:
        parts.append(global_rule)
    return " ".join(dict.fromkeys(parts)).strip()


def prop_contracts_for_text(text: str) -> tuple[dict[str, Any], list[str]]:
    library: dict[str, Any] = {}
    contracts: list[dict[str, Any]] = []
    visible_props: list[str] = []
    for keyword, prop_id in IMPORTANT_PROP_KEYWORDS.items():
        if keyword not in text:
            continue
        if keyword == "照片" and source_text_indicates_environment_photo(text):
            library["ENVIRONMENT_MOUNTED_PHOTO_01"] = {
                "display_name": "荣誉墙/墙上照片",
                "count": "环境陈设",
                "size": "墙面相框或照片展示区",
                "material": "相框、墙面或展板",
                "structure": "固定在墙面/荣誉墙上的照片展示，不是手持纸张",
            }
            continue
        if keyword == "画" and not any(token in text for token in ("儿童画", "图画", "画纸", "画着", "画上", "那幅画", "这幅画", "一幅画")):
            continue
        if prop_id in library:
            continue
        is_photo = "PHOTO" in prop_id or "DRAWING" in prop_id or keyword in {"照片", "画", "全家福"}
        is_phone = "SMARTPHONE" in prop_id or keyword == "手机"
        is_document = any(token in prop_id for token in ("REPORT", "DOCUMENT", "ENVELOPE", "SLIP", "SCREEN"))
        if is_photo:
            profile = {
                "display_name": keyword,
                "count": "1张",
                "size": "约10厘米 x 15厘米",
                "color": "白色纸张与儿童彩笔线条" if "DRAWING" in prop_id else "白色相纸",
                "material": "纸质",
                "structure": "单张平面纸张，有正面和背面",
                "front_description": "正面为不可读图像或儿童画轮廓，不要求生成清晰文字",
                "back_description": "背面为空白纸面",
            }
            contract = {
                "prop_id": prop_id,
                "position": "首帧在持有者手中或桌面视觉中心",
                "first_frame_visible": True,
                "motion_policy": "只随持有者手部轻微移动，不新增副本，不做面向切换",
                "controlled_by": "visible_character",
                "current_visible_side": "正面/front 可见；背面/back 为空白纸面但当前不可见",
                "orientation_to_camera": "默认看照片规则：正面朝持有者或观看者；若展示给镜头，只呈现不可读图像块，背面不展示",
                "quantity_policy": f"只允许这一张 {prop_id}，不得生成额外纸张副本",
                "flip_policy": "不做面向切换",
            }
        elif is_phone:
            profile = {
                "display_name": keyword,
                "count": "1部",
                "size": "约15厘米长、7厘米宽",
                "color": "深色玻璃屏幕与金属边框",
                "material": "玻璃和金属",
                "structure": "现代智能手机",
            }
            contract = {
                "prop_id": prop_id,
                "position": "首帧由角色手持，靠近耳边或胸前",
                "first_frame_visible": True,
                "motion_policy": "只随手部轻微移动，屏幕朝向持有者，屏幕内容不可见",
                "controlled_by": "visible_character",
                "quantity_policy": f"只允许这一部 {prop_id}",
            }
        elif is_document:
            profile = {
                "display_name": keyword,
                "count": "1块" if "SCREEN" in prop_id else "1份",
                "size": "办公电脑屏幕尺寸" if "SCREEN" in prop_id else "A4纸或标准信封尺寸",
                "color": "低亮度电子屏幕与模糊界面块" if "SCREEN" in prop_id else "白色纸张或牛皮纸色",
                "material": "玻璃屏幕" if "SCREEN" in prop_id else "纸质",
                "structure": "固定电脑屏幕，界面只有不可读排版块，不生成可读姓名、机构名或页眉"
                if "SCREEN" in prop_id
                else "单份文件，表面只有模糊排版块，不生成可读姓名、机构名或页眉",
            }
            contract = {
                "prop_id": prop_id,
                "position": "首帧固定在办公桌电脑位置，位于视觉中心附近"
                if "SCREEN" in prop_id
                else "首帧在桌面、手中或文件夹上，位于视觉中心附近",
                "first_frame_visible": True,
                "motion_policy": "屏幕固定不漂移，界面保持不可读排版块，不生成清晰文字"
                if "SCREEN" in prop_id
                else "只允许被角色拿起、放下或轻触，不新增副本，表面文字保持不可读排版块",
                "controlled_by": "none" if "SCREEN" in prop_id else "visible_character",
                "quantity_policy": f"只允许这一份 {prop_id}",
            }
        elif prop_id == "PREGNANCY_TEST_STICK_01":
            profile = {
                "display_name": keyword,
                "count": "1根",
                "size": "约12厘米长、2厘米宽、0.8厘米厚，手掌内的小型塑料测试条",
                "color": "白色塑料外壳，检测窗口内两条红线可辨但不通过放大道具实现",
                "material": "塑料",
                "structure": "手持小型验孕棒，检测窗口朝向角色或镜头；长度不超过成人手掌宽度的约1.5倍，宽度约一根手指宽",
                "reference_mode": "scale_context",
                "scale_policy": "验孕棒只占画面很小面积，不得像遥控器、体温计、手机或大号牌子一样巨大；红线可辨但不能通过放大道具实现",
                "reference_context_policy": "使用与人物中景镜头相近的摄影距离，允许手掌、手指、前臂、膝盖、床沿或桌面作为比例锚点，不生成清晰陌生人脸",
            }
            contract = {
                "prop_id": prop_id,
                "position": "首帧由沈念歌手持，检测窗口可见或半可见",
                "first_frame_visible": True,
                "motion_policy": "只随沈念歌手部轻微移动，不新增副本，不漂浮，不自行移动",
                "controlled_by": "沈念歌",
                "quantity_policy": f"只允许这一根 {prop_id}",
                "visibility_policy": "检测窗口中的两条红线是剧情核心证据，必须可辨但不要生成额外文字；不得把验孕棒放大成前景大物件或占据主画面",
            }
        else:
            if prop_id == "JUICE_CUPS_02":
                profile = {
                    "display_name": keyword,
                    "count": "2杯" if "两杯" in text else "1杯",
                    "size": "每杯约12厘米高、7厘米宽",
                    "color": "浅橙色或透明果汁色",
                    "material": "玻璃杯与液体",
                    "structure": "稳定放置的饮料杯，杯口和杯身清晰",
                }
                contract = {
                    "prop_id": prop_id,
                    "position": "首帧由角色手持或放在桌面固定位置",
                    "first_frame_visible": True,
                    "motion_policy": "只随持有者手部轻微移动，不新增杯子，不改变数量",
                    "controlled_by": "visible_character",
                    "quantity_policy": f"只允许{profile['count']} {prop_id}",
                }
                library[prop_id] = profile
                contracts.append(contract)
                visible_props.append(prop_id)
                continue
            profile = {
                "display_name": keyword,
                "count": "1件",
                "size": "手持或桌面小道具尺寸",
                "color": "符合现实材质的低饱和颜色",
                "material": "现实材质",
                "structure": "固定位置可见道具",
                "reference_mode": "scale_context",
                "scale_policy": f"{keyword}只占画面很小面积，以成人手掌、手指、身体局部或桌面/床沿作为比例锚点；不得像遥控器、手机、长尺、大号牌子或玩具一样巨大；剧情细节可辨但不能通过放大道具实现",
                "reference_context_policy": f"{keyword} reference 使用与人物中景镜头相近的摄影距离，允许手掌、手指、前臂、膝盖、床沿或桌面作为比例锚点，不生成清晰陌生人脸",
            }
            contract = {
                "prop_id": prop_id,
                "position": "首帧在角色手边或桌面固定位置",
                "first_frame_visible": True,
                "motion_policy": "保持固定或随角色手部轻微移动，不新增副本",
                "controlled_by": "visible_character",
                "quantity_policy": f"只允许这一件 {prop_id}",
                "visibility_policy": f"{keyword}必须按剧情可辨，但不得通过放大成前景大物来表现；人物脸、动作和情绪仍是主体",
            }
        library[prop_id] = profile
        contracts.append(contract)
        visible_props.append(prop_id)
    return {"prop_library": library, "prop_contract": contracts}, visible_props


def shot_plan_key_props(shot: n2v.ShotPlan | None) -> list[str]:
    if shot is None or not isinstance(shot.first_frame_contract, dict):
        return []
    return [
        normalize_semantic_prop_id(item)
        for item in shot.first_frame_contract.get("key_props", [])
        if normalize_semantic_prop_id(item)
    ]


def shot_plan_prop_library(shot: n2v.ShotPlan | None) -> dict[str, dict[str, Any]]:
    if shot is None or not isinstance(shot.i2v_contract, dict):
        return {}
    library = shot.i2v_contract.get("prop_library")
    if not isinstance(library, dict):
        return {}
    return {
        normalize_semantic_prop_id(key): dict(value)
        for key, value in library.items()
        if normalize_semantic_prop_id(key) and isinstance(value, dict)
    }


def shot_plan_prop_contract(shot: n2v.ShotPlan | None, prop_id: str) -> dict[str, Any]:
    if shot is None or not isinstance(shot.i2v_contract, dict):
        return {}
    contracts = shot.i2v_contract.get("prop_contract")
    if not isinstance(contracts, list):
        return {}
    for item in contracts:
        if isinstance(item, dict) and normalize_semantic_prop_id(item.get("prop_id")) == prop_id:
            return dict(item)
    return {}


def current_text_supports_handoff(text: str) -> bool:
    return any(keyword in text for keyword in PROP_HANDOFF_ACTION_KEYWORDS)


def upgrade_generic_handoff_prop_id(prop_id: str, previous_props: set[str]) -> str:
    for specific_prop_id, generic_ids in PROP_HANDOFF_GENERIC_REPLACEMENTS.items():
        if prop_id in generic_ids and specific_prop_id in previous_props:
            return specific_prop_id
    return prop_id


def merge_semantic_prop_handoffs(
    *,
    semantic: dict[str, Any],
    draft: ShotDraft,
    previous_shot: n2v.ShotPlan | None,
    prop_contract: dict[str, Any],
    key_props: list[str],
    prompt_text: str,
    prop_seed_text: str,
) -> tuple[dict[str, Any], list[str], str, list[dict[str, Any]]]:
    handoffs = semantic.get("prop_handoffs")
    if not isinstance(handoffs, list) or not handoffs or previous_shot is None:
        return prop_contract, key_props, prompt_text, []
    previous_shot_id = str(previous_shot.shot_id or "").strip().upper()
    previous_props = set(shot_plan_key_props(previous_shot))
    previous_library = shot_plan_prop_library(previous_shot)
    current_text = f"{prompt_text} {prop_seed_text} {draft.source_excerpt}"
    if not current_text_supports_handoff(current_text):
        return prop_contract, key_props, prompt_text, []

    library = prop_contract.setdefault("prop_library", {})
    contracts = prop_contract.setdefault("prop_contract", [])
    if not isinstance(library, dict):
        library = {}
        prop_contract["prop_library"] = library
    if not isinstance(contracts, list):
        contracts = []
        prop_contract["prop_contract"] = contracts

    applied: list[dict[str, Any]] = []
    for raw_handoff in handoffs:
        if not isinstance(raw_handoff, dict):
            continue
        raw_prop_id = normalize_semantic_prop_id(raw_handoff.get("prop_id"))
        prop_id = upgrade_generic_handoff_prop_id(raw_prop_id, previous_props)
        from_shot = str(raw_handoff.get("from_shot") or previous_shot_id).strip().upper()
        to_shot = str(raw_handoff.get("to_shot") or draft.shot_id).strip().upper()
        if not prop_id or from_shot != previous_shot_id or to_shot != draft.shot_id:
            continue
        if prop_id not in previous_props and prop_id not in previous_library:
            continue

        replacements = PROP_HANDOFF_GENERIC_REPLACEMENTS.get(prop_id, set())
        if replacements and not any(item in key_props for item in replacements) and prop_id not in key_props:
            continue

        key_props = [item for item in key_props if item not in replacements and item != prop_id]
        key_props.insert(0, prop_id)
        for replacement in replacements:
            library.pop(replacement, None)
        contracts = [
            item
            for item in contracts
            if not (
                isinstance(item, dict)
                and normalize_semantic_prop_id(item.get("prop_id")) in replacements | {prop_id}
            )
        ]

        current_state = str(raw_handoff.get("current_state") or PROP_HANDOFF_STATE_DEFAULTS.get(prop_id, "")).strip()
        default_state = PROP_HANDOFF_STATE_DEFAULTS.get(prop_id, "")
        if default_state and not any(token in current_state for token in ("果汁", "液体", "空杯")):
            current_state = f"{current_state}；{default_state}" if current_state else default_state
        profile = dict(previous_library.get(prop_id) or {})
        if current_state:
            profile["current_state"] = current_state
        if prop_id == "JUICE_CUPS_02":
            profile.setdefault("display_name", "果汁")
            profile["count"] = "1杯"
            profile.setdefault("color", "浅橙色或透明果汁色")
            profile.setdefault("material", "玻璃杯与液体")
            prompt_text = prompt_text.replace("接过杯子", "接过果汁杯").replace("端起杯子", "端起果汁杯")
        library[prop_id] = profile

        inherited_contract = shot_plan_prop_contract(previous_shot, prop_id)
        to_holder = str(raw_handoff.get("to_holder") or "").strip()
        from_holder = str(raw_handoff.get("from_holder") or "").strip()
        contract = {
            **inherited_contract,
            "prop_id": prop_id,
            "position": f"首帧由{to_holder}接过或手持" if to_holder else "首帧由当前角色接过或手持",
            "first_frame_visible": True,
            "motion_policy": f"只随{to_holder or '持有者'}手部轻微移动；不得变成空杯，不新增杯子",
            "controlled_by": to_holder or inherited_contract.get("controlled_by") or "visible_character",
            "quantity_policy": f"只允许这一件从{from_shot}传入的 {prop_id}",
        }
        if current_state:
            contract["state"] = current_state
        contracts.append(contract)
        prop_contract["prop_contract"] = contracts

        prompt_rewrite = PROP_HANDOFF_PROMPT_REWRITES.get(prop_id)
        if prompt_rewrite and prompt_rewrite not in prompt_text:
            holder_text = to_holder or "当前角色"
            source_text = f"{from_holder}递来的" if from_holder else "上一镜头传入的"
            prompt_text = f"{prompt_text}，延续上一镜头道具：{holder_text}接过{source_text}{prompt_rewrite}"
        applied.append(
            {
                "from_shot": from_shot,
                "to_shot": to_shot,
                "prop_id": prop_id,
                "handoff_type": str(raw_handoff.get("handoff_type") or "").strip(),
                "from_holder": from_holder,
                "to_holder": to_holder,
                "source_evidence": str(raw_handoff.get("source_evidence") or "").strip(),
                "current_state": current_state,
                "confidence": str(raw_handoff.get("confidence") or "").strip(),
                "validation": "accepted_previous_shot_prop_handoff",
            }
        )

    if applied:
        prop_contract["semantic_prop_handoffs"] = applied
        prop_contract["prop_handoff_policy"] = "semantic handoff accepted only after previous-shot prop and current action validation"
    return prop_contract, key_props, prompt_text, applied


def scene_overlay_for_text(text: str, visible_names: list[str]) -> dict[str, Any]:
    required: list[str] = []
    physical_rules: list[str] = []
    background_policies: list[str] = []
    foreground_count = len(visible_names) if visible_names else 0
    foreground_characters = list(visible_names)
    raw = str(text or "")
    blurred_count = unnamed_blurred_figure_foreground_count(raw)
    bus_gone = any(token in raw for token in ("消失", "驶远", "开走", "离开", "后视镜里", "后视镜中"))
    if blurred_count:
        foreground_count = max(foreground_count, blurred_count)
        while len(foreground_characters) < foreground_count:
            foreground_characters.append("被子裹着的模糊身影")
        physical_rules.append("未点名人物只按原文呈现为被子裹着的模糊身影，不赋予具体身份")
    if "大床" in raw:
        required.append("一张大床")
    if any(token in raw for token in ("绿萝", "小盆绿萝", "盆栽")):
        required.append("桌上一小盆绿萝")
        physical_rules.extend(
            [
                "绿萝是小公寓桌面静态陈设，不作为剧情道具被人物拿起或操纵",
                "绿萝花盆底部始终贴合桌面，全程不漂浮、不滑动、不旋转、不新增副本",
            ]
        )
    for keyword, label in LARGE_SCENE_ELEMENT_KEYWORDS.items():
        if keyword in raw:
            if keyword == "公交车" and bus_gone:
                continue
            if keyword == "门" and any(specific in raw for specific in ("车门", "大门", "房门", "电梯门", "门口")):
                continue
            if keyword == "车" and any(specific in raw for specific in ("公交车", "车门")):
                continue
            required.append(label)
    if "公交车" in raw and not bus_gone:
        required.append("路边停靠一辆公交车")
    if "公交车" in raw and bus_gone:
        physical_rules.append("公交车只作为后视镜或远处离开的背景线索，不得生成路边静止等候的公交车辆")
    if "车门" in raw and ("公交车" in raw or "车上" in raw):
        required.append("公交车车门打开")
        physical_rules.extend(
            [
                "公交车门固定在公交车车身上，不脱离车体",
                "公交车门不得漂浮、不得作为独立门板出现、不得被人物拖动",
            ]
        )
    elif "车门" in raw:
        physical_rules.append("车门必须固定在对应车辆车身上，不脱离车体、不漂浮、不被人物拖动")
    if any(token in raw for token in ("车上", "跳下来", "走下", "上车", "上了车", "公交车门")):
        physical_rules.append("人物脚部必须接触公交车台阶或地面，不悬空，不从车门后凭空冒出")
    if source_text_indicates_environment_photo(raw):
        required.append("墙面或荣誉墙上的固定照片")
        physical_rules.append("荣誉墙/墙上照片是环境陈设，不得变成人物手持照片或可移动纸张道具")
    if (
        not is_document_screen_detail_text(raw)
        and {"沈念歌", "沈知予"}.issubset(set(visible_names))
        and ("牵" in raw or "儿子" in raw or "车上" in raw)
    ):
        physical_rules.append("沈念歌牵着沈知予，两人作为前景主体同时稳定可见")
    if "门口人流" in raw or "人流穿梭" in raw or "路人" in raw or "人群" in raw:
        physical_rules.append("背景允许远处路人/人流，但不得新增第三个前景主体人物")
    group_mentions = [token for token in BACKGROUND_GROUP_LISTENER_TOKENS if token in raw]
    if group_mentions:
        background_policies.append(
            "群体听众/围观者只作为背景反应层呈现，不进入首帧前景主体人数，不要求逐个脸部锁定"
        )

    overlay = {
        "required_elements": list(dict.fromkeys(item for item in required if item)),
        "physical_rules": list(dict.fromkeys(item for item in physical_rules if item)),
        "foreground_character_count": foreground_count,
        "foreground_characters": foreground_characters,
        "background_character_policy": "；".join(
            dict.fromkeys(
                (
                    ["背景允许远处路人/人流，但不得新增第三个前景主体人物"] if foreground_count >= 2 else []
                )
                + background_policies
            )
        ),
    }
    return {key: value for key, value in overlay.items() if value not in ("", [], 0)}


def scene_overlay_text(scene_overlay: dict[str, Any]) -> str:
    if not isinstance(scene_overlay, dict) or not scene_overlay:
        return ""
    parts: list[str] = []
    required = scene_overlay.get("required_elements")
    if isinstance(required, list) and required:
        parts.append("场景修饰：" + "、".join(str(item) for item in required if str(item).strip()))
    rules = scene_overlay.get("physical_rules")
    if isinstance(rules, list) and rules:
        parts.append("物理规则：" + "；".join(str(item) for item in rules if str(item).strip()))
    foreground = scene_overlay.get("foreground_characters")
    count = scene_overlay.get("foreground_character_count")
    if isinstance(foreground, list) and foreground and count:
        parts.append(f"首帧前景主体人物数量 exactly {count}：" + "、".join(str(item) for item in foreground if str(item).strip()))
    policy = str(scene_overlay.get("background_character_policy") or "").strip()
    if policy:
        parts.append(policy)
    return " ".join(parts).strip()


def prop_seed_text_for_draft(draft: ShotDraft, prompt_text: str, has_phone_line: bool) -> str:
    if has_phone_line:
        return f"{prompt_text} 手机"
    return f"{prompt_text} {sanitize_prompt_text(draft.source_excerpt)}"


def should_inherit_previous_local_scene(draft: ShotDraft, context_text: str) -> bool:
    text = draft_combined_text(draft, context_text)
    if any(token in text for token in ("行政部", "周主管", "档案柜", "入职表")):
        return True
    if any(token in text for token in ("手机", "语音", "儿子的声音", "档案室", "整理文件")):
        return True
    return False


def shot_costume_override_for_text(text: str, visible_names: list[str]) -> str:
    if "沈念歌" not in visible_names:
        return ""
    raw = str(text or "")
    items: list[str] = []
    if "白衬衫" in raw:
        items.append("白衬衫")
    if "黑色西裤" in raw:
        items.append("黑色西裤")
    if "头发盘起来" in raw:
        items.append("头发盘起来")
    if not items:
        return ""
    return "沈念歌本镜头服装按原文：" + "、".join(dict.fromkeys(items))


def build_shots(
    parsed: ParsedScript,
    characters: list[n2v.Character],
    max_shots: int,
    semantic_annotations: dict[str, dict[str, Any]] | None = None,
) -> list[n2v.ShotPlan]:
    drafts = build_shot_drafts(parsed, max_shots)
    return build_shots_from_drafts(parsed, characters, drafts, semantic_annotations)


def build_shots_from_drafts(
    parsed: ParsedScript,
    characters: list[n2v.Character],
    drafts: list[ShotDraft],
    semantic_annotations: dict[str, dict[str, Any]] | None = None,
    character_location_trace: dict[str, dict[str, Any]] | None = None,
) -> list[n2v.ShotPlan]:
    semantic_annotations = semantic_annotations or {}
    character_location_trace = character_location_trace or {}
    shots: list[n2v.ShotPlan] = []
    last_local_scene_by_parent: dict[str, dict[str, str]] = {}
    active_phone_remote = ""
    active_phone_listener = ""
    episode_text = parsed.script_path.read_text(encoding="utf-8")
    for draft_index, draft in enumerate(drafts):
        semantic = semantic_annotations.get(draft.shot_id, {})
        location_state = character_location_trace.get(draft.shot_id, {})
        location_override = semantic.get("location_override") if isinstance(semantic.get("location_override"), dict) else {}
        context_text = line_context_excerpt(parsed.script_path, draft.line_start, draft.line_end)
        resolved_scene_name = str(location_override.get("shot_local_location") or draft.scene_name or "未命名场景").strip()
        parent_scene_name = str(draft.parent_scene_name or draft.scene_name or "").strip()
        shot_location_basis = str(location_override.get("location_basis") or draft.shot_location_basis or "").strip()
        shot_location_excerpt = str(location_override.get("location_excerpt") or draft.shot_location_excerpt or "").strip()
        if (
            parent_scene_name
            and resolved_scene_name == parent_scene_name
            and not shot_location_basis
            and (should_inherit_previous_local_scene(draft, context_text) or bool(active_phone_remote))
        ):
            inherited = last_local_scene_by_parent.get(parent_scene_name)
            if inherited:
                resolved_scene_name = inherited.get("scene_name", resolved_scene_name)
                shot_location_basis = inherited.get("basis", "")
                shot_location_excerpt = inherited.get("excerpt", "")
        tracker_location = str(location_state.get("shot_location") or "").strip() if isinstance(location_state, dict) else ""
        if tracker_location and (
            not str(location_override.get("shot_local_location") or "").strip()
            or tracker_location_more_specific(tracker_location, resolved_scene_name)
        ):
            resolved_scene_name = tracker_location
            shot_location_basis = str(location_state.get("source_basis") or shot_location_basis or "character_location_tracker").strip()
            shot_location_excerpt = str(location_state.get("continuity_action") or shot_location_excerpt or "").strip()
        tracker_character_location = tracker_character_location_for_scene(location_state)
        if tracker_location_more_specific(tracker_character_location, resolved_scene_name):
            resolved_scene_name = tracker_character_location
            shot_location_basis = str(location_state.get("source_basis") or shot_location_basis or "character_location_tracker.character_locations").strip()
            shot_location_excerpt = str(location_state.get("continuity_action") or shot_location_excerpt or tracker_character_location).strip()
        resolved_scene_id = safe_slug(resolved_scene_name, draft.scene_id or "SCENE")
        prompt_text = sanitize_prompt_text(" ".join(draft.visual_texts))
        keyframe_from_selection = sanitize_prompt_text(selection_keyframe_moment(draft.selection_plan))
        if keyframe_from_selection and keyframe_from_selection not in prompt_text:
            prompt_text = f"首帧关键瞬间：{keyframe_from_selection}；{prompt_text}"
        semantic_has_visible = "visible_characters" in semantic
        semantic_visible = semantic.get("visible_characters") if isinstance(semantic.get("visible_characters"), list) else []
        if is_document_screen_detail_draft(draft, context_text):
            semantic_visible = []
        if semantic_visible and blurred_visual_shot_uses_unnamed_figures(draft):
            explicit_names = explicit_character_names_in_shot_text(draft, characters)
            semantic_visible = [name for name in semantic_visible if name in explicit_names]
        semantic_visible = evidence_supported_visible_names(semantic_visible, draft, context_text)
        visible_names = semantic_visible if semantic_has_visible else visible_names_for_draft(draft, characters, context_text=context_text)
        tracker_visible = clt.visible_character_names(location_state) if isinstance(location_state, dict) else []
        tracker_offscreen = clt.offscreen_character_names(location_state) if isinstance(location_state, dict) else set()
        for name in tracker_visible:
            append_unique_name(visible_names, name)
        if tracker_offscreen:
            visible_names = [name for name in visible_names if name not in tracker_offscreen]
        environment_photo_context = source_text_indicates_environment_photo(draft_combined_text(draft, context_text))
        if environment_photo_context and not any(str(item.get("speaker") or "").strip() == "陆景琛" for item in draft.dialogue):
            visible_names = [name for name in visible_names if name != "陆景琛"]
        if is_document_screen_detail_draft(draft, context_text):
            visible_names = []
        featured_character = featured_character_for_draft(draft, visible_names)
        has_phone_line = any(item.get("source") == "phone" for item in draft.dialogue)
        prop_seed_text = prop_seed_text_for_draft(draft, prompt_text, has_phone_line)
        if not draft.dialogue:
            if "刻意绕开" in prompt_text and "金色专用电梯" in context_text and "档案袋" in context_text:
                prompt_text = (
                    "沈念歌抱着一摞档案袋走在三十二楼走廊上，尽头是金色专用电梯；"
                    + prompt_text
                )
                prop_seed_text = f"{prop_seed_text} 档案袋"
        elif "接过文件" in context_text and "谢谢陆总" in draft.source_excerpt and "接过陆景琛递来的文件" not in prompt_text:
            prompt_text += "，沈念歌刚接过陆景琛递来的文件，手里有文件"
            prop_seed_text = f"{prop_seed_text} 文件"
        prop_contract, key_props = prop_contracts_for_text(prop_seed_text)
        selected_key_props = [
            normalize_selected_key_prop(item)
            for item in draft.selection_plan.get("key_props", [])
            if isinstance(draft.selection_plan, dict) and normalize_selected_key_prop(item)
        ]
        for prop_id in selected_key_props:
            if environment_photo_context and ("PHOTO" in prop_id.upper() or "照片" in prop_id):
                continue
            if prop_id.startswith("ENVIRONMENT_MOUNTED_PHOTO"):
                continue
            if is_large_scene_element_text(prop_id):
                continue
            if prop_id not in key_props and not any(token in prop_id.upper() for token in LARGE_SCENE_PROP_ID_TOKENS):
                key_props.append(prop_id)
        prop_contract, key_props, prompt_text, applied_prop_handoffs = merge_semantic_prop_handoffs(
            semantic=semantic,
            draft=draft,
            previous_shot=shots[-1] if shots else None,
            prop_contract=prop_contract,
            key_props=key_props,
            prompt_text=prompt_text,
            prop_seed_text=prop_seed_text,
        )
        scene_overlay = scene_overlay_for_text(prop_seed_text, visible_names)
        overlay_prompt = scene_overlay_text(scene_overlay)
        if any("SMARTPHONE" in prop_id for prop_id in key_props):
            prompt_text += "，一部手机首帧可见，屏幕朝向持有者，屏幕内容不可见"
            prop_contract.setdefault("phone_contract", {})
            prop_contract["phone_contract"].update(
                {
                    "screen_orientation": "screen facing inward toward holder",
                    "screen_content_visible": False,
                }
            )
        dialogue = []
        selection_remote_phone = selection_marks_phone_remote(draft.selection_plan)
        for item in draft.dialogue:
            normalized = dict(item)
            for semantic_dialogue in semantic.get("dialogue_annotations", []) if isinstance(semantic.get("dialogue_annotations"), list) else []:
                if str(semantic_dialogue.get("exact_text") or "").strip() == str(normalized.get("text") or "").strip():
                    listener = str(semantic_dialogue.get("listener") or "").strip()
                    if listener:
                        normalized["listener"] = listener
                    action_targets = semantic_dialogue.get("action_targets")
                    filtered_targets = semantic_character_target_names(action_targets, character_alias_table(characters))
                    if filtered_targets:
                        normalized["action_targets"] = filtered_targets
                    gaze_rule = str(semantic_dialogue.get("gaze_rule") or "").strip()
                    if gaze_rule:
                        normalized["semantic_gaze_rule"] = gaze_rule
            if normalized.get("source") == "phone" and normalized.get("listener"):
                normalized["purpose"] = "远端声音，画面内听者保持沉默"
            explicit_listener = explicit_listener_from_performance(
                str(normalized.get("performance") or ""),
                str(normalized.get("speaker") or "").strip(),
            )
            if explicit_listener:
                normalized["listener"] = explicit_listener
            if environment_photo_context and str(normalized.get("listener") or "").strip() == "陆景琛":
                if "沈念歌" in visible_names or any(token in str(normalized.get("text") or "") for token in ("妈咪", "妈妈", "她")):
                    normalized["listener"] = "沈念歌"
            speaker = str(normalized.get("speaker") or "").strip()
            if selection_remote_phone:
                normalized["source"] = "phone"
                normalized["purpose"] = "电话远端声音，画面内听者保持沉默"
                if not normalized.get("listener") and active_phone_listener:
                    normalized["listener"] = active_phone_listener
            elif (
                active_phone_remote
                and str(normalized.get("source") or "onscreen") == "onscreen"
                and speaker
                and speaker != active_phone_remote
                and any(token in f"{context_text} {prompt_text}" for token in ("电话", "手机", "语音", "听筒", "对着手机", "接听"))
            ):
                normalized["listener"] = phone_remote_name(active_phone_remote)
                normalized["purpose"] = "现场人物对手机回复远端语音，远端人物不入镜"
            if is_phone_reply_context(normalized, draft, context_text):
                listener = str(normalized.get("listener") or "").strip()
                if not listener:
                    listener = infer_phone_reply_remote_listener(normalized, context_text)
                if listener:
                    normalized["listener"] = phone_remote_name(listener)
                    normalized["purpose"] = "对手机回复远端语音，远端人物不入镜"
            dialogue.append(normalized)
        for item in dialogue:
            if item.get("source") == "phone":
                active_phone_remote = str(item.get("speaker") or active_phone_remote or "").strip()
                if str(item.get("listener") or "").strip():
                    active_phone_listener = base_remote_name(str(item.get("listener") or "").strip()) or str(item.get("listener") or "").strip()
            elif is_offscreen_listener_name(str(item.get("listener") or "")):
                active_phone_listener = str(item.get("speaker") or active_phone_listener or "").strip()
        remote_names = set(remote_phone_speakers(draft, context_text))
        for item in dialogue:
            listener_name = str(item.get("listener") or "").strip()
            if is_offscreen_listener_name(listener_name):
                base = base_remote_name(listener_name)
                if base:
                    remote_names.add(base)
        if remote_names:
            visible_names = [name for name in visible_names if name not in remote_names]
        for item in dialogue:
            speaker = str(item.get("speaker") or "").strip()
            source = str(item.get("source") or "onscreen")
            listener = str(item.get("listener") or "").strip()
            if (
                source == "onscreen"
                and listener
                and listener != speaker
                and not is_offscreen_listener_name(listener)
                and not is_background_group_listener_name(listener)
            ):
                append_unique_name(visible_names, listener)
            action_targets = item.get("action_targets")
            if isinstance(action_targets, list):
                for target in action_targets:
                    target_name = str(target or "").strip()
                    if (
                        target_name
                        and target_name != speaker
                        and not is_offscreen_listener_name(target_name)
                        and not is_background_group_listener_name(target_name)
                    ):
                        append_unique_name(visible_names, target_name)
        visible_names = hard_visible_character_names(visible_names)
        if environment_photo_context and not any(str(item.get("speaker") or "").strip() == "陆景琛" for item in dialogue):
            visible_names = [name for name in visible_names if name != "陆景琛"]
        featured_character = featured_character_for_draft(draft, visible_names)
        character_state_overlay = group_visible_character_state_overlays(
            semantic.get("character_state_overlays"),
            visible_names,
        )
        for overlay_items in character_state_overlay.values():
            for overlay_item in overlay_items:
                source_basis = str(overlay_item.get("source_basis") or "").strip()
                if source_basis in {"source_excerpt", "nearby_context", "current_shot", "shot"}:
                    overlay_item["source_basis"] = f"{parsed.script_path}:{draft.line_start}-{draft.line_end}"
                elif source_basis.startswith("line_range"):
                    overlay_item["source_basis"] = f"{parsed.script_path}:{draft.line_start}-{draft.line_end}"
                elif source_basis.startswith("nearby_context line"):
                    line_numbers = re.findall(r"\d+", source_basis)
                    if line_numbers:
                        overlay_item["source_basis"] = f"{parsed.script_path}:{line_numbers[0]}-{line_numbers[-1]}"
                repair_character_state_overlay_source_fidelity(overlay_item)
                repair_character_state_overlay_face_visibility(overlay_item)
                overlay_text = " ".join(
                    [
                        str(overlay_item.get("state_id") or ""),
                        str(overlay_item.get("body_state") or ""),
                        str(overlay_item.get("evidence_quote") or ""),
                    ]
                )
                if any(token in overlay_text.lower() for token in ("pregnant", "pregnancy")) or any(token in overlay_text for token in ("怀孕", "妊娠", "早孕")):
                    key_props_for_state = semantic_text_list(overlay_item.get("key_props"))
                    if "验孕棒" in context_text and "验孕棒" not in key_props_for_state:
                        key_props_for_state.append("验孕棒")
                    if key_props_for_state:
                        overlay_item["key_props"] = key_props_for_state
        keyframe_moment = sanitize_prompt_text(str(semantic.get("keyframe_moment") or "").strip())
        for overlay_items in character_state_overlay.values():
            for overlay_item in overlay_items:
                item_moment = sanitize_prompt_text(str(overlay_item.get("keyframe_moment") or "").strip())
                if item_moment and not keyframe_moment:
                    keyframe_moment = item_moment
                if (
                    str(overlay_item.get("state_id") or "") == "late_pregnancy"
                    and any(token in keyframe_moment for token in ("抱着婴儿", "抱婴儿", "新生儿", "孩子"))
                    and not any(token in str(overlay_item.get("evidence_quote") or "") for token in ("产后", "婴儿", "新生儿", "抱着孩子", "出生"))
                ):
                    keyframe_moment = item_moment or "中景走出医院门，撑腰拎编织袋"
        movement_boundary = build_adjacent_movement_boundary(
            draft=draft,
            next_draft=drafts[draft_index + 1] if draft_index + 1 < len(drafts) else None,
            semantic_annotations=semantic_annotations,
            resolved_scene_name=resolved_scene_name,
            prompt_text=prompt_text,
            keyframe_moment=keyframe_moment,
            character_state_overlay=character_state_overlay,
        )
        scene_overlay_seed_text = keyframe_moment if keyframe_moment and draft_is_montage(draft) else prop_seed_text
        scene_overlay = scene_overlay_for_text(scene_overlay_seed_text, visible_names)
        overlay_prompt = scene_overlay_text(scene_overlay)
        phone_listener = ""
        for item in dialogue:
            if item.get("source") == "phone":
                phone_listener = str(item.get("listener") or "")
                if not phone_listener:
                    candidates = [name for name in visible_names if name != str(item.get("speaker") or "")]
                    phone_listener = candidates[0] if candidates else "画面内听者"
                    item["listener"] = phone_listener
        if phone_listener:
            prompt_text = re.sub(r"(沈念歌|陆景琛|沈知予|赵一鸣|苏晚|林雨薇|周雅琳|画面内听者)正在听手机语音", f"{phone_listener}正在听手机语音", prompt_text)
            if not is_offscreen_listener_name(phone_listener) and not is_background_group_listener_name(phone_listener):
                append_unique_name(visible_names, phone_listener)
                visible_names = hard_visible_character_names(visible_names)
                featured_character = featured_character_for_draft(draft, visible_names)
        is_last_shot = draft_index == len(drafts) - 1
        dialogue_addressing = build_dialogue_addressing_contract(dialogue, visible_names, context_text)
        dialogue_gaze_text = dialogue_addressing_text(dialogue_addressing)
        if dialogue_gaze_text:
            prompt_text += f"，对白视线关系：{dialogue_gaze_text}"
        costume_override = shot_costume_override_for_text(f"{context_text} {episode_text}", visible_names)
        if costume_override and costume_override not in prompt_text:
            prompt_text += f"，{costume_override}"
        dialogue_blocking: dict[str, Any] | None = None
        if phone_listener:
            dialogue_blocking = {
                "active_speaker": str(dialogue[0].get("speaker") or ""),
                "visible_listener": phone_listener,
                "lip_sync_policy": "remote_voice_listener_silent",
                "listener_action_contract": f"{phone_listener}认真地听电话，一句话也没有说，闭着嘴，认真思考，只用眼神、眉头、呼吸和握手机手指表现反应",
                "dialogue_addressing": dialogue_addressing,
                "gaze_contract": dialogue_addressing,
            }
            prompt_text += f"，{dialogue_blocking['listener_action_contract']}"
            prop_contract["phone_contract"] = {
                "listener": phone_listener,
                "screen_orientation": "screen facing inward toward holder",
                "screen_content_visible": False,
                "listener_lip_policy": "remote_voice_listener_silent",
                "listener_action_contract": dialogue_blocking["listener_action_contract"],
            }
        if is_last_shot and not dialogue:
            dialogue_blocking = {
                "active_speaker": "",
                "first_speaker": "",
                "speaker_visual_priority": "no_dialogue",
                "lip_sync_policy": "no_dialogue",
                "listener_action_contract": "",
            }
            prop_contract["shot_task"] = "reaction"
            prop_contract["episode_hook_context"] = parsed.hook or parsed.preview or ""
        elif dialogue and not phone_listener:
            dialogue_blocking = {
                "active_speaker": str(dialogue[0].get("speaker") or ""),
                "first_speaker": str(dialogue[0].get("speaker") or ""),
                "speaker_visual_priority": "speaker_face_and_mouth_visible",
                "lip_sync_policy": "onscreen_speaker_only",
                "silent_visible_characters": [name for name in visible_names if name != str(dialogue[0].get("speaker") or "")],
                "dialogue_addressing": dialogue_addressing,
                "gaze_contract": dialogue_addressing,
            }

        face_visibility = {
            name: f"{name}首帧正脸、三分之二侧脸或清晰侧脸可见，脸部五官对观众可辨认；眼神方向遵守对白视线关系，不默认看镜头"
            for name in visible_names
        }
        onscreen_speakers = [
            str(item.get("speaker") or "").strip()
            for item in dialogue
            if str(item.get("source") or "onscreen") == "onscreen" and str(item.get("speaker") or "").strip()
        ]
        speaker_face_visibility = {
            name: (
                f"{name}是画面内说话人，keyframe/首帧必须看见{name}的脸和嘴；"
                "必须是正脸、三分之二侧脸或清晰侧脸；说话人脸部、眼睛和嘴部必须清楚无遮挡，并占主视觉；"
                "相机必须在说话人前侧或侧前方45度，不能从说话人背后拍；如果双方脸部可见性冲突，优先保证说话人的脸和嘴可见"
            )
            for name in dict.fromkeys(onscreen_speakers)
        }
        first_frame_contract = {
            "location": resolved_scene_name,
            "visual_center": visible_names[0] if visible_names else (key_props[0] if key_props else resolved_scene_name),
            "featured_character": featured_character,
            "visible_characters": visible_names,
            "foreground_character_cardinality": {
                "mode": "exactly",
                "count": len(visible_names),
                "names": visible_names,
                "focus": featured_character,
                "source": "screen_script_relationship_inference",
            }
            if visible_names
            else {
                "mode": "exactly",
                "count": 0,
                "names": [],
                "focus": "",
                "source": "screen_script_scene_only",
            },
            "character_positions": {name: "画面中近景位置，脸部清晰可见" for name in visible_names},
            "character_face_visibility": face_visibility,
            "speaker_face_visibility": speaker_face_visibility,
            "dialogue_addressing": dialogue_addressing,
            "gaze_contract": dialogue_addressing,
            "key_props": key_props,
            "prop_handoffs": applied_prop_handoffs,
            "scene_overlay": scene_overlay,
            "music_cues": semantic.get("music_cues", draft.music) if isinstance(semantic.get("music_cues", draft.music), list) else draft.music,
            "semantic_quality": sanitize_semantic_quality(semantic.get("quality")),
            "speaking_state": "single_active_speaker" if dialogue else "no_dialogue_visual_beat",
            "camera_motion_allowed": "轻微推近或稳定手持，不改变首帧主体关系",
            "source_context_excerpt": draft.shot_context_excerpt,
            "parent_scene_name": parent_scene_name,
            "shot_location_candidates": draft.shot_location_candidates,
        }
        if isinstance(location_state, dict) and location_state:
            first_frame_contract["character_location_state"] = location_state
            first_frame_contract["location_tracker_confidence"] = str(location_state.get("confidence") or "").strip()
            first_frame_contract["location_tracker_warnings"] = location_state.get("warnings", [])
        if draft.selection_plan:
            first_frame_contract["selection_plan"] = draft.selection_plan
        if costume_override:
            first_frame_contract["costume_modifiers"] = [costume_override]
        if shot_location_basis or shot_location_excerpt:
            source_basis = (
                f"{parsed.script_path}:{shot_location_basis.replace('line ', '').strip()}"
                if shot_location_basis.startswith("line ")
                else shot_location_basis
            )
            first_frame_contract["shot_location_evidence"] = {
                "parent_scene_name": parent_scene_name,
                "resolved_scene_name": resolved_scene_name,
                "source_basis": source_basis,
                "evidence_quote": shot_location_excerpt,
                "policy": "shot-local location evidence overrides parent scene when specific and source-supported",
            }
        if character_state_overlay:
            first_frame_contract["character_state_overlay"] = character_state_overlay
        if keyframe_moment:
            first_frame_contract["keyframe_moment"] = keyframe_moment
        if movement_boundary:
            first_frame_contract["movement_boundary"] = movement_boundary
        subtitle = [str(item.get("text") or "") for item in dialogue]
        narration: list[str] = normalize_semantic_narration_lines(semantic.get("narration_lines"))
        if not draft_has_explicit_narration(draft):
            narration = []
        subject_visibility = "人物脸部可见" if visible_names else "关键道具或场景主体清楚"
        positive_core = (
            f"忠实还原原剧本镜头：{prompt_text}。"
            f"首帧主体清楚，{subject_visibility}，场景为{resolved_scene_name}。"
        )
        if key_props:
            positive_core += " 关键道具：" + "、".join(key_props) + "首帧可见并保持数量稳定。"
        if isinstance(location_state, dict) and location_state.get("continuity_action"):
            positive_core += f" 角色地点连续性：{location_state.get('continuity_action')}。"
        state_overlay_prompt = character_state_overlay_prompt_text(character_state_overlay)
        if state_overlay_prompt:
            positive_core += " " + state_overlay_prompt
        if overlay_prompt:
            positive_core += " " + overlay_prompt
        shots.append(
            n2v.ShotPlan(
                shot_id=draft.shot_id,
                priority="high" if draft.dialogue or draft.shot_id in {"SH01"} else "medium",
                intent=prompt_text[:80],
                duration_sec=6 if is_last_shot and dialogue else (5 if dialogue else 4),
                shot_type=draft.shot_type or "中景",
                movement="轻微推近" if dialogue else "稳定镜头",
                framing_focus=(visible_names[0] if visible_names else prompt_text[:24]) + "，首帧脸部或道具清晰",
                action_intent=prompt_text[:120],
                emotion_intent="、".join(parsed.keywords[:3]) if parsed.keywords else "紧张、克制、反转",
                scene_id=resolved_scene_id,
                scene_name=resolved_scene_name,
                dialogue=dialogue,
                narration=narration,
                subtitle=subtitle,
                positive_core=positive_core,
                source_basis=f"{parsed.script_path}:{draft.line_start}-{draft.line_end}",
                source_excerpt=draft.source_excerpt,
                first_frame_contract=first_frame_contract,
                dialogue_blocking=dialogue_blocking,
                i2v_contract=prop_contract
                if (prop_contract.get("prop_contract") or prop_contract.get("phone_contract") or prop_contract.get("shot_task"))
                else None,
            )
        )
        if parent_scene_name and resolved_scene_name != parent_scene_name:
            last_local_scene_by_parent[parent_scene_name] = {
                "scene_name": resolved_scene_name,
                "basis": shot_location_basis,
                "excerpt": shot_location_excerpt,
            }
    return shots


def script_file_for_episode(script_dir: Path, episode_id: str) -> Path:
    ep_num = parse_episode_token(episode_id)
    candidates = [
        script_dir / f"ep{ep_num:03d}.md",
        script_dir / f"ep{ep_num:02d}.md",
        script_dir / f"EP{ep_num:03d}.md",
        script_dir / f"EP{ep_num:02d}.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    matches = sorted(script_dir.glob(f"*{ep_num:03d}*.md")) + sorted(script_dir.glob(f"*{ep_num:02d}*.md"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"script file not found for {episode_id} under {script_dir}")


def discover_all_scripts(script_path: Path, script_dir_arg: str) -> list[Path]:
    if script_dir_arg.strip():
        script_dir = resolve_repo_path(script_dir_arg)
    else:
        script_dir = script_path.parent
    files = sorted(path for path in script_dir.glob("*.md") if path.is_file())
    return files or [script_path]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a screen-script-to-video planning bundle.")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--script-file", default="", help="One episode screen script markdown.")
    source_group.add_argument("--script-dir", default="", help="Directory containing epXXX.md screen scripts.")
    parser.add_argument("--episode", default="EP01", help="Episode id used with --script-dir, default EP01.")
    parser.add_argument("--project-name", default="", help="Project name. Defaults to screen script parent name.")
    parser.add_argument("--project-title", default="", help="Human project title. Defaults to episode title.")
    parser.add_argument("--platform", default="douyin")
    parser.add_argument("--backend", default="screen_script", help=argparse.SUPPRESS)
    parser.add_argument("--semantic-backend", choices=["auto", "grok", "openai", "heuristic", "none"], default="auto", help="Semantic annotation backend for speaker/listener/action-target/cardinality. auto is Grok-first with OpenAI fallback.")
    parser.add_argument("--semantic-model", default="", help="Grok semantic model override. Default tries grok-4-fast-reasoning, grok-3-fast, grok-3.")
    parser.add_argument("--openai-semantic-model", default=DEFAULT_OPENAI_SEMANTIC_MODEL, help="OpenAI fallback semantic model.")
    parser.add_argument("--semantic-context-before", type=int, default=40)
    parser.add_argument("--semantic-context-after", type=int, default=16)
    parser.add_argument("--semantic-max-output-tokens", type=int, default=12000)
    parser.add_argument("--semantic-timeout-sec", type=int, default=180)
    parser.add_argument("--semantic-retry-count", type=int, default=2)
    parser.add_argument("--semantic-retry-wait-sec", type=int, default=8)
    parser.add_argument("--no-character-location-tracking", action="store_true", help="Disable the LLM character location continuity tracker.")
    parser.add_argument("--strict-location-tracking", action="store_true", help="Fail when character location tracking has blocking findings. Production/non-dry-run is strict by default.")
    parser.add_argument("--out", default="", help="Output dir. Relative paths resolve under screen_script/.")
    parser.add_argument("--max-shots", type=int, default=DEFAULT_MAX_SHOTS)
    parser.add_argument(
        "--shot-selection-plan",
        default="",
        help="Optional JSON with selected_shots[].line_range to override built-in shot splitting/selection.",
    )
    parser.add_argument(
        "--selection-mode",
        choices=["rule", "llm-rules", "llm-no-rules", "compare"],
        default="llm-rules",
        help="Source parsing/selection/merging mode. Defaults to llm-rules; use rule only for explicit offline/legacy fallback runs.",
    )
    parser.add_argument("--strict-selection-mode", action="store_true", help="Fail instead of falling back to rule mode when live LLM source selection fails.")
    parser.add_argument(
        "--allow-selection-fallback",
        action="store_true",
        help="Allow live LLM source selection failure to fall back to rule mode. Default is fail-fast for non-rule selection modes.",
    )
    parser.add_argument("--selection-backend", choices=["auto", "grok", "openai"], default="auto")
    parser.add_argument("--selection-model", default="", help="LLM model for source selection. Defaults to semantic model or provider default.")
    parser.add_argument("--openai-selection-model", default=DEFAULT_OPENAI_SEMANTIC_MODEL)
    parser.add_argument("--selection-max-output-tokens", type=int, default=16000)
    parser.add_argument("--selection-timeout-sec", type=int, default=240)
    parser.add_argument("--selection-retry-count", type=int, default=2)
    parser.add_argument("--selection-retry-wait-sec", type=int, default=8)
    parser.add_argument("--character-image-ext", default="jpg")
    parser.add_argument("--no-character-map-aliases", action="store_true")
    parser.add_argument("--qa-strict", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def resolve_inputs(args: argparse.Namespace) -> tuple[Path, Path, str, Path, str]:
    episode_id = args.episode.strip().upper() or "EP01"
    if args.script_file.strip():
        script_path = resolve_repo_path(args.script_file)
        episode_match = re.search(r"ep(\d{1,3})", script_path.stem, flags=re.IGNORECASE)
        if episode_match and args.episode == "EP01":
            episode_id = episode_id_from_number(int(episode_match.group(1)))
    else:
        script_dir = resolve_repo_path(args.script_dir)
        script_path = script_file_for_episode(script_dir, episode_id)
    if not script_path.exists():
        raise FileNotFoundError(f"script file not found: {script_path}")
    if script_path.suffix.lower() != ".md":
        raise ValueError(f"script file must be markdown: {script_path}")
    project_root = screen_project_root(script_path, args.script_dir)
    project_name = n2v.safe_filename_name(args.project_name.strip() or n2v.slug_to_pascal(project_root.name))
    if args.out.strip():
        out_dir = Path(args.out).expanduser()
        if not out_dir.is_absolute():
            out_dir = (SCREEN_ROOT / out_dir).resolve()
        else:
            out_dir = out_dir.resolve()
    else:
        out_dir = (project_root / f"{project_name}_{episode_id}_fullrun_v1").resolve()
    return script_path, project_root, project_name, out_dir, episode_id


def build_source(script_path: Path, project_name: str, project_title: str, parsed: ParsedScript) -> n2v.ProjectSource:
    text = script_path.read_text(encoding="utf-8")
    headings = n2v.parse_markdown_headings(text)
    return n2v.ProjectSource(
        novel_path=str(script_path),
        canonical_source_path=str(script_path),
        project_name=project_name,
        title=project_title.strip() or parsed.title,
        text=text,
        headings=headings,
        chapter_titles=[parsed.title],
        source_excerpts=n2v.split_source_excerpts(text),
    )


def anchor_node_for_name(name: str, characters: list[n2v.Character]) -> dict[str, Any] | None:
    matched = n2v.find_character_by_name(characters, name) or n2v.infer_ephemeral_character_by_name(name)
    if matched is None and (is_ephemeral_name(name) or str(name or "").strip().startswith("EXTRA_")):
        matched = ephemeral_character_from_name(name)
    if matched is None:
        return None
    node = n2v.character_to_anchor_node(matched, lock_enabled=should_enable_ephemeral_lock(matched, characters))
    node["must_appear_in_shot"] = True
    return node


def sync_character_anchor_with_first_frame(data: dict[str, Any], characters: list[n2v.Character]) -> None:
    first_frame = data.get("first_frame_contract")
    if not isinstance(first_frame, dict):
        return
    visible_names = [
        str(item).strip()
        for item in first_frame.get("visible_characters", [])
        if str(item).strip()
    ]
    if not visible_names:
        return
    anchor = data.setdefault("character_anchor", {})
    if not isinstance(anchor, dict):
        anchor = {}
        data["character_anchor"] = anchor
    primary = anchor.get("primary") if isinstance(anchor.get("primary"), dict) else {}
    secondary = anchor.get("secondary") if isinstance(anchor.get("secondary"), list) else []
    nodes = [primary] if primary else []
    nodes.extend([item for item in secondary if isinstance(item, dict)])
    existing_names = {
        str(node.get("name") or node.get("character_id") or "").strip()
        for node in nodes
    }
    existing_ids = {
        str(node.get("character_id") or "").strip()
        for node in nodes
    }

    if not primary or str(primary.get("character_id") or "") == "SCENE_ONLY":
        new_primary = anchor_node_for_name(visible_names[0], characters)
        if new_primary:
            anchor["primary"] = new_primary
            primary = new_primary
            existing_names.add(str(new_primary.get("name") or "").strip())
            existing_ids.add(str(new_primary.get("character_id") or "").strip())

    new_secondary = [item for item in secondary if isinstance(item, dict)]
    for name in visible_names:
        node = anchor_node_for_name(name, characters)
        if not node:
            continue
        node_name = str(node.get("name") or "").strip()
        node_id = str(node.get("character_id") or "").strip()
        primary_name = str((anchor.get("primary") or {}).get("name") or "").strip() if isinstance(anchor.get("primary"), dict) else ""
        primary_id = str((anchor.get("primary") or {}).get("character_id") or "").strip() if isinstance(anchor.get("primary"), dict) else ""
        if node_name == primary_name or node_id == primary_id:
            anchor["primary"]["must_appear_in_shot"] = True
            continue
        existing_match = None
        for existing in new_secondary:
            existing_name = str(existing.get("name") or "").strip()
            existing_id = str(existing.get("character_id") or "").strip()
            if node_name == existing_name or node_id == existing_id:
                existing_match = existing
                break
        if existing_match is not None:
            existing_match["must_appear_in_shot"] = True
            continue
        if node_name in existing_names or node_id in existing_ids:
            continue
        new_secondary.append(node)
        existing_names.add(node_name)
        existing_ids.add(node_id)
    anchor["secondary"] = new_secondary


def is_large_scene_element_text(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return any(token in text for token in LARGE_SCENE_ELEMENT_TEXT_TOKENS)


def scrub_large_scene_elements_from_motion_contract(data: dict[str, Any]) -> None:
    contract = data.get("scene_motion_contract")
    if not isinstance(contract, dict):
        return
    for key in ("static_props", "manipulated_props"):
        items = contract.get(key)
        if isinstance(items, list):
            contract[key] = [
                item
                for item in items
                if not is_large_scene_element_text(str(item))
            ]


def screen_record_findings(path: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    shot_id = str(data.get("record_header", {}).get("shot_id") or path.stem).strip()
    source_trace = data.get("source_trace") if isinstance(data.get("source_trace"), dict) else {}
    scene_anchor = data.get("scene_anchor") if isinstance(data.get("scene_anchor"), dict) else {}
    first_frame_for_location = data.get("first_frame_contract") if isinstance(data.get("first_frame_contract"), dict) else {}
    final_scene = str(scene_anchor.get("scene_name") or first_frame_for_location.get("location") or "").strip()
    parent_scene = str(source_trace.get("parent_scene_name") or first_frame_for_location.get("parent_scene_name") or "").strip()
    location_candidates = source_trace.get("shot_location_candidates")
    if isinstance(location_candidates, list) and parent_scene_is_generic(parent_scene) and final_scene == parent_scene:
        clean_candidates = [
            item
            for item in location_candidates
            if isinstance(item, dict) and str(item.get("scene_name") or "").strip()
        ]
        candidate_names = list(dict.fromkeys(str(item.get("scene_name") or "").strip() for item in clean_candidates))
        if len(candidate_names) == 1:
            first_candidate = clean_candidates[0]
            findings.append(
                {
                    "severity": "high",
                    "issue": "shot_local_scene_not_applied",
                    "path": str(path),
                    "affected_shot_id": shot_id,
                    "parent_scene": parent_scene,
                    "detected_local_scene": candidate_names[0],
                    "evidence_line": str(first_candidate.get("basis") or "").strip(),
                    "message": "蒙太奇/快速剪辑中的单一局部地点必须覆盖父级场景，不能静默沿用父级出租屋/蒙太奇地点。",
                }
            )
        elif len(candidate_names) > 1:
            findings.append(
                {
                    "severity": "medium",
                    "issue": "multiple_shot_local_scenes_need_keyframe_moment",
                    "path": str(path),
                    "affected_shot_id": shot_id,
                    "parent_scene": parent_scene,
                    "detected_local_scene": candidate_names,
                    "evidence_line": " / ".join(str(item.get("basis") or "").strip() for item in clean_candidates if str(item.get("basis") or "").strip()),
                    "message": "同一镜头检测到多个局部地点；允许保留父级蒙太奇场景，但 keyframe_moment 应选择单一瞬间，避免首帧拼贴多地点。",
                }
            )
    i2v = data.get("i2v_contract") if isinstance(data.get("i2v_contract"), dict) else {}
    prop_ids: list[str] = []
    library = i2v.get("prop_library") if isinstance(i2v, dict) else {}
    if isinstance(library, dict):
        prop_ids.extend(str(key) for key in library.keys())
    contracts = i2v.get("prop_contract") if isinstance(i2v, dict) else []
    if isinstance(contracts, list):
        prop_ids.extend(str(item.get("prop_id") or "") for item in contracts if isinstance(item, dict))
    large_props = [
        prop_id
        for prop_id in dict.fromkeys(prop_ids)
        if any(token in prop_id.upper() for token in LARGE_SCENE_PROP_ID_TOKENS)
    ]
    for prop_id in large_props:
        findings.append(
            {
                "severity": "high",
                "issue": "large_scene_element_in_prop_contract",
                "path": str(path),
                "prop_id": prop_id,
                "message": "门、车、公交车门等大物件必须进入 scene_overlay，不能进入 prop_library/prop_contract/key_props。",
            }
        )

    first_frame = data.get("first_frame_contract") if isinstance(data.get("first_frame_contract"), dict) else {}
    visible = [
        str(item).strip()
        for item in first_frame.get("visible_characters", [])
        if str(item).strip()
    ]
    key_props = [
        str(item).strip()
        for item in first_frame.get("key_props", [])
        if str(item).strip()
    ]
    bad_key_props = [
        prop_id
        for prop_id in key_props
        if any(token in prop_id.upper() for token in LARGE_SCENE_PROP_ID_TOKENS)
    ]
    for prop_id in bad_key_props:
        findings.append(
            {
                "severity": "high",
                "issue": "large_scene_element_in_key_props",
                "path": str(path),
                "prop_id": prop_id,
            }
        )
    motion_contract = data.get("scene_motion_contract") if isinstance(data.get("scene_motion_contract"), dict) else {}
    for key in ("static_props", "manipulated_props"):
        values = motion_contract.get(key) if isinstance(motion_contract, dict) else []
        if not isinstance(values, list):
            continue
        bad_values = [str(item).strip() for item in values if is_large_scene_element_text(str(item))]
        if bad_values:
            findings.append(
                {
                    "severity": "high",
                    "issue": "large_scene_element_in_scene_motion_props",
                    "path": str(path),
                    "field": key,
                    "values": bad_values,
                    "message": "门、车、公交车门等大物件不能作为 static_props/manipulated_props 输出，应进入 scene_overlay。",
                }
            )
    anchor = data.get("character_anchor") if isinstance(data.get("character_anchor"), dict) else {}
    anchored_names: list[str] = []
    primary = anchor.get("primary") if isinstance(anchor, dict) else {}
    if isinstance(primary, dict):
        anchored_names.append(str(primary.get("name") or primary.get("character_id") or "").strip())
    secondary = anchor.get("secondary") if isinstance(anchor, dict) else []
    if isinstance(secondary, list):
        anchored_names.extend(str(item.get("name") or item.get("character_id") or "").strip() for item in secondary if isinstance(item, dict))
    missing = [name for name in visible if name and name not in anchored_names]
    if missing:
        findings.append(
            {
                "severity": "high",
                "issue": "visible_character_missing_from_character_anchor",
                "path": str(path),
                "characters": missing,
            }
        )
    overlay = data.get("character_state_overlay")
    if isinstance(overlay, dict):
        for character, raw_items in overlay.items():
            items = raw_items if isinstance(raw_items, list) else [raw_items]
            if str(character or "").strip() not in visible:
                findings.append(
                    {
                        "severity": "high",
                        "issue": "character_state_overlay_character_not_visible",
                        "path": str(path),
                        "character": str(character or "").strip(),
                        "message": "character_state_overlay 默认只允许映射到本 shot 可见人物。",
                    }
                )
            for index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    findings.append(
                        {
                            "severity": "high",
                            "issue": "invalid_character_state_overlay_item",
                            "path": str(path),
                            "character": str(character or "").strip(),
                            "index": index,
                        }
                    )
                    continue
                missing_fields = [
                    field
                    for field in ("source_basis", "evidence_quote")
                    if not str(item.get(field) or "").strip()
                ]
                if missing_fields:
                    findings.append(
                        {
                            "severity": "high",
                            "issue": "character_state_overlay_missing_evidence",
                            "path": str(path),
                            "character": str(character or "").strip(),
                            "index": index,
                            "missing_fields": missing_fields,
                            "message": "身体状态 overlay 必须有 source_basis 和 evidence_quote，不能凭空延续到无证据 shot。",
                        }
                    )
                if not str(item.get("body_state") or "").strip() and not semantic_text_list(item.get("visible_constraints")):
                    findings.append(
                        {
                            "severity": "high",
                            "issue": "character_state_overlay_missing_visible_state",
                            "path": str(path),
                            "character": str(character or "").strip(),
                            "index": index,
                        }
                    )
                if str(item.get("scope") or "").strip() != "shot_local":
                    findings.append(
                        {
                            "severity": "high",
                            "issue": "character_state_overlay_not_shot_local",
                            "path": str(path),
                            "character": str(character or "").strip(),
                            "index": index,
                        }
                    )
    dialogue_language = data.get("dialogue_language") if isinstance(data.get("dialogue_language"), dict) else {}
    dialogue_lines = dialogue_language.get("dialogue_lines") if isinstance(dialogue_language.get("dialogue_lines"), list) else []
    first_frame = data.get("first_frame_contract") if isinstance(data.get("first_frame_contract"), dict) else {}
    visible_names = [
        str(item).strip()
        for item in first_frame.get("visible_characters", [])
        if str(item).strip()
    ] if isinstance(first_frame, dict) else []
    for item in dialogue_lines:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        if source == "voiceover" and str(item.get("listener") or "").strip():
            findings.append(
                {
                    "severity": "high",
                    "issue": "voiceover_dialogue_has_listener",
                    "path": str(path),
                    "speaker": str(item.get("speaker") or "").strip(),
                    "listener": str(item.get("listener") or "").strip(),
                    "message": "voiceover/画外音默认不生成画面内 listener；只有电话、广播、门外声等远端声音才需要 listener。",
                }
            )
        if source == "phone":
            speaker = str(item.get("speaker") or "").strip()
            if speaker and speaker in visible_names:
                findings.append(
                    {
                        "severity": "high",
                        "issue": "phone_remote_speaker_marked_visible",
                        "path": str(path),
                        "speaker": speaker,
                        "message": "电话/语音远端说话人默认不能进入首帧 visible_characters；除非原文明确视频通话或屏幕内可见。",
                    }
                )
        listener = str(item.get("listener") or "").strip()
        if listener and is_offscreen_listener_name(listener):
            base = base_remote_name(listener)
            if base and base in visible_names:
                findings.append(
                    {
                        "severity": "high",
                        "issue": "remote_listener_marked_visible",
                        "path": str(path),
                        "listener": listener,
                        "message": "对手机/远端对象说话时，远端 listener 不能被加入首帧前景人物。",
                    }
                )
    excerpt = str(source_trace.get("shot_source_excerpt") or "")
    if is_document_screen_detail_text(excerpt) and visible_names:
        findings.append(
            {
                "severity": "high",
                "issue": "document_screen_text_created_visible_characters",
                "path": str(path),
                "visible_characters": visible_names,
                "message": "屏幕简报/报告特写中的姓名、儿子、年龄只是文档内容，不能触发真实人物入镜。",
            }
        )
    return findings


def extend_screen_plan_qa(
    qa_report: dict[str, Any],
    json_specs: list[tuple[n2v.ArtifactSpec, dict[str, Any]]],
) -> dict[str, Any]:
    findings = list(qa_report.get("findings", [])) if isinstance(qa_report.get("findings"), list) else []
    for spec, data in json_specs:
        if spec.category == "record":
            findings.extend(screen_record_findings(spec.path, data))
    qa_report["findings"] = findings
    qa_report["pass"] = not any(str(item.get("severity") or "").lower() == "high" for item in findings if isinstance(item, dict))
    return qa_report


def augment_lock_profiles_from_records(json_specs: list[tuple[n2v.ArtifactSpec, dict[str, Any]]]) -> None:
    """Add missing episode-local locks for record anchors without overriding existing profiles."""
    lock_doc: dict[str, Any] | None = None
    record_docs: list[dict[str, Any]] = []
    for spec, data in json_specs:
        if spec.path.name == "35_character_lock_profiles_v1.json" and isinstance(data, dict):
            lock_doc = data
        elif spec.category == "record" and isinstance(data, dict):
            record_docs.append(data)
    if not isinstance(lock_doc, dict):
        return
    profiles = lock_doc.setdefault("profiles", [])
    if not isinstance(profiles, list):
        profiles = []
        lock_doc["profiles"] = profiles
    existing: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        for key in ("lock_profile_id", "character_id", "name"):
            value = str(profile.get(key) or "").strip()
            if value:
                existing.add(value)
    for record in record_docs:
        anchor = record.get("character_anchor") if isinstance(record.get("character_anchor"), dict) else {}
        nodes: list[Any] = []
        if isinstance(anchor.get("primary"), dict):
            nodes.append(anchor.get("primary"))
        secondary = anchor.get("secondary")
        if isinstance(secondary, list):
            nodes.extend(secondary)
        for node in nodes:
            if not isinstance(node, dict):
                continue
            lock_id = str(node.get("lock_profile_id") or "").strip()
            character_id = str(node.get("character_id") or "").strip()
            name = str(node.get("name") or character_id).strip()
            if not lock_id or lock_id in existing or character_id in existing or name in existing:
                continue
            visual_anchor = str(node.get("visual_anchor") or "").strip()
            profile = {
                "lock_profile_id": lock_id,
                "character_id": character_id,
                "name": name,
                "visual_anchor": visual_anchor,
                "forbidden_drift": ["年龄漂移", "脸型漂移", "服装时代错误", "时代/地域感错误", "过度美颜"],
                "appearance_anchor_tokens": [token for token in (name, visual_anchor) if token],
                "source": "record_anchor_auto_added",
            }
            profiles.append(profile)
            for value in (lock_id, character_id, name):
                if value:
                    existing.add(value)


def patch_screen_record(
    data: dict[str, Any],
    parsed: ParsedScript,
    draft: n2v.ShotPlan,
    characters: list[n2v.Character],
) -> dict[str, Any]:
    data["record_header"]["author"] = "screen2video_plan.py"
    data["record_header"]["status"] = "screen_script_draft_plan"
    source_trace = data.setdefault("source_trace", {})
    source_trace.update(
        {
            "source_type": "screen_script",
            "script_file": str(parsed.script_path),
            "screen_script_is_source_of_truth": True,
            "shot_source_basis": draft.source_basis,
            "shot_source_excerpt": draft.source_excerpt,
            "conversion_policy": "faithful_normalization_no_story_rewrite",
        }
    )
    data["project_meta"]["source_type"] = "screen_script"
    first_frame_contract = data.get("first_frame_contract") if isinstance(data.get("first_frame_contract"), dict) else {}
    if isinstance(first_frame_contract, dict):
        draft_first_frame = getattr(draft, "first_frame_contract", None)
        if isinstance(draft_first_frame, dict):
            for key in ("key_props", "prop_handoffs", "scene_overlay", "music_cues"):
                value = draft_first_frame.get(key)
                if value and not first_frame_contract.get(key):
                    first_frame_contract[key] = value
        context_excerpt = str(first_frame_contract.get("source_context_excerpt") or "").strip()
        parent_scene_name = str(first_frame_contract.get("parent_scene_name") or "").strip()
        location_candidates = first_frame_contract.get("shot_location_candidates")
        if context_excerpt:
            source_trace["shot_context_excerpt"] = context_excerpt
        if parent_scene_name:
            source_trace["parent_scene_name"] = parent_scene_name
        if isinstance(location_candidates, list) and location_candidates:
            source_trace["shot_location_candidates"] = location_candidates
        location_evidence = first_frame_contract.get("shot_location_evidence")
        if isinstance(location_evidence, dict) and location_evidence:
            source_trace["shot_location_basis"] = str(location_evidence.get("source_basis") or "").strip()
            source_trace["shot_location_excerpt"] = str(location_evidence.get("evidence_quote") or "").strip()
            source_trace["shot_location_policy"] = str(location_evidence.get("policy") or "").strip()
        for helper_key in ("source_context_excerpt", "parent_scene_name", "shot_location_candidates", "shot_location_evidence"):
            first_frame_contract.pop(helper_key, None)
        selection_plan = first_frame_contract.pop("selection_plan", None)
        if isinstance(selection_plan, dict) and selection_plan:
            source_trace["selection_plan"] = selection_plan
        location_state = first_frame_contract.pop("character_location_state", None)
        if isinstance(location_state, dict) and location_state:
            source_trace["character_location_state"] = location_state
            source_trace["location_tracker_basis"] = str(location_state.get("source_basis") or "").strip()
            source_trace["location_tracker_confidence"] = str(first_frame_contract.pop("location_tracker_confidence", "") or location_state.get("confidence") or "").strip()
            warnings = first_frame_contract.pop("location_tracker_warnings", None)
            source_trace["location_tracker_warnings"] = warnings if isinstance(warnings, list) else location_state.get("warnings", [])
        else:
            first_frame_contract.pop("location_tracker_confidence", None)
            first_frame_contract.pop("location_tracker_warnings", None)
    state_overlay = first_frame_contract.pop("character_state_overlay", None) if isinstance(first_frame_contract, dict) else None
    if isinstance(state_overlay, dict) and state_overlay:
        data["character_state_overlay"] = state_overlay
    keyframe_moment = first_frame_contract.pop("keyframe_moment", "") if isinstance(first_frame_contract, dict) else ""
    if str(keyframe_moment or "").strip():
        data["keyframe_moment"] = str(keyframe_moment).strip()
        static_anchor = data.setdefault("keyframe_static_anchor", {})
        if isinstance(static_anchor, dict):
            static_anchor["keyframe_moment"] = str(keyframe_moment).strip()
    movement_boundary = first_frame_contract.pop("movement_boundary", None) if isinstance(first_frame_contract, dict) else None
    if isinstance(movement_boundary, dict) and movement_boundary:
        shot_execution = data.setdefault("shot_execution", {})
        if isinstance(shot_execution, dict):
            shot_execution["movement_boundary"] = movement_boundary
        continuity_rules = data.setdefault("continuity_rules", {})
        if isinstance(continuity_rules, dict):
            movement_continuity = continuity_rules.setdefault("movement_continuity", [])
            if not isinstance(movement_continuity, list):
                movement_continuity = []
                continuity_rules["movement_continuity"] = movement_continuity
            for key in ("end_state", "next_shot_bridge"):
                value = str(movement_boundary.get(key) or "").strip()
                if value and value not in movement_continuity:
                    movement_continuity.append(value)
    i2v_contract = data.get("i2v_contract") if isinstance(data.get("i2v_contract"), dict) else {}
    draft_i2v_contract = getattr(draft, "i2v_contract", None)
    if isinstance(draft_i2v_contract, dict):
        if not isinstance(i2v_contract, dict):
            i2v_contract = {}
            data["i2v_contract"] = i2v_contract
        if draft_i2v_contract.get("prop_library") and not i2v_contract.get("prop_library"):
            i2v_contract["prop_library"] = draft_i2v_contract.get("prop_library")
        if draft_i2v_contract.get("prop_contract") and not i2v_contract.get("prop_contract"):
            i2v_contract["prop_contract"] = draft_i2v_contract.get("prop_contract")
        if draft_i2v_contract.get("phone_contract") and not i2v_contract.get("phone_contract"):
            i2v_contract["phone_contract"] = draft_i2v_contract.get("phone_contract")
        for key in ("shot_task", "risk_level", "risk_notes", "episode_hook_context"):
            if draft_i2v_contract.get(key) and not i2v_contract.get(key):
                i2v_contract[key] = draft_i2v_contract.get(key)
    if isinstance(i2v_contract, dict):
        library = i2v_contract.get("prop_library")
        if isinstance(library, dict) and "SMARTPHONE_01" in library and "KENICHI_SMARTPHONE" in library:
            library.pop("KENICHI_SMARTPHONE", None)
        contracts = i2v_contract.get("prop_contract")
        if isinstance(contracts, list) and "SMARTPHONE_01" in (first_frame_contract.get("key_props") or []):
            i2v_contract["prop_contract"] = [
                item
                for item in contracts
                if not (isinstance(item, dict) and normalize_semantic_prop_id(item.get("prop_id")) == "KENICHI_SMARTPHONE")
            ]
    handoffs = i2v_contract.get("semantic_prop_handoffs") if isinstance(i2v_contract, dict) else []
    if isinstance(handoffs, list) and handoffs:
        continuity = data.setdefault("continuity_rules", {}).setdefault("prop_continuity", [])
        if not isinstance(continuity, list):
            continuity = []
            data.setdefault("continuity_rules", {})["prop_continuity"] = continuity
        scene_anchor = data.setdefault("scene_anchor", {})
        if not isinstance(scene_anchor, dict):
            scene_anchor = {}
            data["scene_anchor"] = scene_anchor
        scene_props = scene_anchor.setdefault("prop_must_visible", [])
        if not isinstance(scene_props, list):
            scene_props = []
            scene_anchor["prop_must_visible"] = scene_props
        first_frame = data.setdefault("first_frame_contract", {})
        if isinstance(first_frame, dict):
            first_frame["prop_handoffs"] = handoffs
        for item in handoffs:
            if not isinstance(item, dict):
                continue
            prop_id = normalize_semantic_prop_id(item.get("prop_id"))
            if prop_id and prop_id not in scene_props:
                scene_props.append(prop_id)
            to_holder = str(item.get("to_holder") or "当前角色").strip()
            from_shot = str(item.get("from_shot") or "上一镜头").strip()
            current_state = str(item.get("current_state") or PROP_HANDOFF_STATE_DEFAULTS.get(prop_id, "")).strip()
            rule = f"{prop_id}继承自{from_shot}并由{to_holder}继续持有/使用"
            if current_state:
                rule += f"；{current_state}"
            if rule not in continuity:
                continuity.append(rule)
    sync_character_anchor_with_first_frame(data, characters)
    scrub_large_scene_elements_from_motion_contract(data)
    scrub_handheld_photo_props_for_environment_context(
        data,
        " ".join(
            [
                str(getattr(draft, "source_excerpt", "") or ""),
                str(getattr(draft, "positive_core", "") or ""),
                str(getattr(draft, "action_intent", "") or ""),
                str(source_trace.get("shot_context_excerpt") or "") if isinstance(source_trace, dict) else "",
            ]
        ),
    )
    return data


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    args = parse_args()
    try:
        script_path, project_root, project_name, out_dir, episode_id = resolve_inputs(args)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    parsed = parse_script(script_path, episode_id)
    all_script_paths = discover_all_scripts(script_path, args.script_dir)
    all_parsed = []
    for path in all_script_paths:
        match = re.search(r"ep(\d{1,3})", path.stem, flags=re.IGNORECASE)
        item_episode_id = episode_id_from_number(int(match.group(1))) if match else episode_id
        all_parsed.append(parse_script(path, item_episode_id))

    source = build_source(script_path, project_name, args.project_title, parsed)
    characters = build_characters(all_script_paths, parsed)
    bible = build_bible(source, parsed, all_parsed, args.platform, characters)
    episode_plan = build_episode_plan(parsed)
    max_shots = max(1, min(50, int(args.max_shots)))
    paths = n2v.project_paths(out_dir, project_root)
    selection_fallbacks: list[dict[str, str]] = []
    selection_plan: ssp.SelectionPlan | None = None
    selection_qa: ssp.SelectionQAReport | None = None
    if args.shot_selection_plan.strip():
        selection_plan_path = resolve_repo_path(args.shot_selection_plan)
        payload = json.loads(selection_plan_path.read_text(encoding="utf-8"))
        units = source_units_from_screen_script(parsed)
        selection_plan = ssp.normalize_selection_plan(
            payload,
            units=units,
            mode="shot-selection-plan",
            source_type="screen",
            episode_id=parsed.episode_id,
            title=parsed.title,
            max_shots=max_shots,
        )
        selection_qa = ssp.qa_selection_plan(selection_plan, units)
        write_selection_artifacts(paths, selection_plan, selection_qa, args)
        if selection_qa_has_high_findings(selection_qa) and not args.dry_run:
            high = [item for item in selection_qa.findings if item.get("severity") == "high"]
            raise RuntimeError(f"explicit shot selection plan QA failed with high findings: {high[:5]}")
        drafts = build_shot_drafts_from_selection_payload(parsed, plan_payload_from_selection_plan(selection_plan), max_shots, str(selection_plan_path))
        selection_fallbacks.append({"task": "source_selection", "reason": f"explicit --shot-selection-plan used: {selection_plan_path}"})
    else:
        drafts, selection_plan, selection_qa, selection_fallbacks = run_screen_source_selection(args, parsed, bible, paths, max_shots)
    semantic_annotations, semantic_llm_result = run_screen_semantic_pass(args, parsed, drafts, bible.characters, paths.out_dir)
    character_location_trace, location_qa, location_fallbacks = run_screen_character_location_tracking(
        args,
        parsed,
        drafts,
        semantic_annotations,
        bible.characters,
        paths.out_dir,
    )
    shots = build_shots_from_drafts(parsed, bible.characters, drafts, semantic_annotations, character_location_trace)

    print(f"[INFO] script: {script_path}")
    print(f"[INFO] output: {out_dir}")
    print(f"[INFO] project: {project_name} / {source.title} / {episode_id}")
    print(f"[INFO] scenes: {len(parsed.scene_names)} shots: {len(shots)} characters: {len(bible.characters)}")
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
    written.extend(n2v.copy_common_docs(paths, args.overwrite, args.dry_run))
    text_specs, json_specs = n2v.render_artifacts(paths, source, bible, episode_plan, shots, args)
    patched_json_specs: list[tuple[n2v.ArtifactSpec, dict[str, Any]]] = []
    shots_by_id = {shot.shot_id: shot for shot in shots}
    for spec, data in json_specs:
        if spec.category == "record":
            shot_id = str(data.get("record_header", {}).get("shot_id") or "")
            data = patch_screen_record(data, parsed, shots_by_id.get(shot_id, shots[0]), bible.characters)
        elif spec.path.name == "character_image_map.json":
            data.setdefault("", "")
        patched_json_specs.append((spec, data))
    augment_lock_profiles_from_records(patched_json_specs)
    llm_result = n2v.LLMRunResult(
        "screen_script_semantic" if semantic_llm_result.applied else "screen_script",
        semantic_llm_result.provider,
        semantic_llm_result.model,
        args.dry_run,
        semantic_llm_result.request_files,
        semantic_llm_result.fallbacks + selection_fallbacks + location_fallbacks,
        True,
    )
    qa_report = n2v.run_plan_qa(source, bible, episode_plan, shots, text_specs, patched_json_specs, llm_result, len(shots))
    qa_report = extend_screen_plan_qa(qa_report, patched_json_specs)
    patched_json_specs.append((n2v.artifact(paths.out_dir / "plan_qa_report.json", "qa", "project", ["ScreenScript", "ShotPlan"], True), qa_report))

    for spec, content in text_specs:
        if args.dry_run:
            print(f"[DRY] write {spec.path}")
            written.append(str(spec.path))
        elif n2v.write_text(spec.path, content, args.overwrite):
            written.append(str(spec.path))
    for spec, data in patched_json_specs:
        if args.dry_run:
            print(f"[DRY] write {spec.path}")
            written.append(str(spec.path))
        elif n2v.write_json(spec.path, data, args.overwrite):
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
