from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import signal
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field


REPO_ROOT = Path(__file__).resolve().parents[2]
NOVEL_ROOT = REPO_ROOT / "novel"
SCREEN_SCRIPT_ROOT = REPO_ROOT / "screen_script"
TEST_ROOT = REPO_ROOT / "test"
WEBUI_STATE = REPO_ROOT / "webui" / ".state"
DB_PATH = WEBUI_STATE / "webui.sqlite3"
LOG_ROOT = WEBUI_STATE / "logs"
ARCHIVE_ROOT = WEBUI_STATE / "archive"
REVIEW_ROOT = TEST_ROOT / "webui_review_runs"
CACHE_ROOT = WEBUI_STATE / "cache"
EXECUTION_DIR_NAME = "06_当前项目的视觉与AI执行层文档"

PIPELINE_STEPS = [
    "novel2video_plan",
    "character_image_gen",
    "generate_cover_pages",
    "run_novel_video_director",
    "run_seedance_test",
    "assemble_episode",
    "qa_episode_sync",
]

API_STEPS = {
    "character_image_gen": "openai_image",
    "generate_cover_pages": "openai_image",
    "run_novel_video_director": "openai_image",
    "run_seedance_test": "seedance_video",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_\-\u4e00-\u9fff]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_-")
    return value or "project"


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value.strip())
    value = re.sub(r"\s+", "_", value)
    return value or "Project"


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def resolve_repo_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def ensure_under_repo(path: Path) -> Path:
    path = path.resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"path escapes repo: {path}") from exc
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                create table if not exists projects (
                  id integer primary key autoincrement,
                  name text not null,
                  slug text not null unique,
                  novel_path text not null,
                  project_dir text not null,
                  plan_bundle_path text default '',
                  created_at text not null,
                  updated_at text not null
                );
                create table if not exists episodes (
                  id integer primary key autoincrement,
                  project_id integer not null,
                  episode_id text not null,
                  title text default '',
                  status text default 'not_started',
                  updated_at text not null,
                  unique(project_id, episode_id)
                );
                create table if not exists shots (
                  id integer primary key autoincrement,
                  project_id integer not null,
                  episode_id text not null,
                  shot_id text not null,
                  record_path text not null,
                  status text default 'not_started',
                  updated_at text not null,
                  unique(project_id, episode_id, shot_id)
                );
                create table if not exists jobs (
                  id integer primary key autoincrement,
                  project_id integer not null,
                  step text not null,
                  scope text not null,
                  episode_id text default 'EP01',
                  shots text default '',
                  status text not null,
                  command_json text not null,
                  log_path text not null,
                  output_manifest text default '',
                  returncode integer,
                  dry_run integer default 0,
                  created_at text not null,
                  started_at text,
                  ended_at text
                );
                create table if not exists assets (
                  id integer primary key autoincrement,
                  project_id integer not null,
                  asset_type text not null,
                  episode_id text default '',
                  shot_id text default '',
                  label text not null,
                  canonical_path text not null,
                  prompt_path text default '',
                  status text default 'ready',
                  stale integer default 0,
                  updated_at text not null,
                  unique(project_id, canonical_path)
                );
                create table if not exists review_runs (
                  id integer primary key autoincrement,
                  asset_id integer not null,
                  project_id integer not null,
                  status text not null,
                  prompt_override text default '',
                  base_prompt_path text default '',
                  final_prompt_path text default '',
                  output_path text not null,
                  run_dir text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create table if not exists artifact_runs (
                  id integer primary key autoincrement,
                  project_id integer not null,
                  episode_id text default '',
                  run_name text not null,
                  run_type text not null,
                  run_dir text not null,
                  manifest_path text default '',
                  records_dir text default '',
                  keyframe_prompts_root text default '',
                  mtime text default '',
                  updated_at text not null,
                  unique(project_id, run_type, run_dir)
                );
                create table if not exists artifact_candidates (
                  id integer primary key autoincrement,
                  project_id integer not null,
                  episode_id text not null,
                  shot_id text not null,
                  media_type text not null,
                  path text not null,
                  run_id integer,
                  run_name text not null,
                  prompt_path text default '',
                  payload_path text default '',
                  manifest_path text default '',
                  source_kind text default '',
                  status text default 'ready',
                  mtime text default '',
                  metadata_json text default '',
                  updated_at text not null,
                  unique(project_id, media_type, path)
                );
                create table if not exists artifact_selections (
                  project_id integer not null,
                  episode_id text not null,
                  shot_id text not null,
                  media_type text not null,
                  candidate_path text not null,
                  updated_at text not null,
                  unique(project_id, episode_id, shot_id, media_type)
                );
                """
            )

    def one(self, sql: str, args: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(sql, args).fetchone()

    def all(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(sql, args).fetchall()

    def execute(self, sql: str, args: tuple[Any, ...] = ()) -> int:
        with self.connect() as conn:
            cur = conn.execute(sql, args)
            conn.commit()
            return int(cur.lastrowid)

    def update(self, sql: str, args: tuple[Any, ...] = ()) -> None:
        with self.connect() as conn:
            conn.execute(sql, args)
            conn.commit()


db = Database(DB_PATH)
running_processes: dict[int, asyncio.subprocess.Process] = {}
provider_locks = {
    "openai_image": asyncio.Semaphore(1),
    "seedance_video": asyncio.Semaphore(1),
}


class JobRequest(BaseModel):
    project_id: int
    step: str
    scope: str = Field(default="episode", pattern="^(project|episode|shot)$")
    episode_id: str = "EP01"
    shots: list[str] = Field(default_factory=list)
    dry_run: bool = False
    prepare_only: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class ReviewRunRequest(BaseModel):
    prompt_override: str = ""


class AssetPromptSaveRequest(BaseModel):
    image_path: str
    prompt: str


class ArtifactSelectionRequest(BaseModel):
    episode_id: str
    shot_id: str
    media_type: str = Field(pattern="^(keyframe|clip)$")
    candidate_id: int | None = None
    reset: bool = False


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def project_by_id(project_id: int) -> dict[str, Any]:
    row = db.one("select * from projects where id = ?", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail="project not found")
    return dict(row)


def first_existing_markdown(root: Path, preferred: list[str] | None = None) -> Path:
    for name in preferred or []:
        candidate = root / name
        if candidate.exists() and candidate.suffix.lower() == ".md":
            return candidate
    direct = sorted(root.glob("*.md"))
    if direct:
        return direct[0]
    nested = sorted(root.glob("*/*.md"))
    if nested:
        return nested[0]
    fallback = root / "README.md"
    return fallback


def screen_script_project_markers(root: Path) -> bool:
    return (root / "assets").is_dir() or (root / "归档").is_dir() or any(root.glob("*.md"))


def screen_script_display_name(root: Path) -> str:
    if root.resolve() == SCREEN_SCRIPT_ROOT.resolve():
        return "ScreenScript"
    parts = [part for part in re.split(r"[_\-\s]+", root.name) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or safe_name(root.name)


def iter_screen_script_project_roots() -> list[Path]:
    if not SCREEN_SCRIPT_ROOT.exists():
        return []
    roots: list[Path] = []
    if screen_script_project_markers(SCREEN_SCRIPT_ROOT):
        roots.append(SCREEN_SCRIPT_ROOT)
    for child in sorted(SCREEN_SCRIPT_ROOT.iterdir()):
        if child.name.startswith(".") or not child.is_dir():
            continue
        if screen_script_project_markers(child):
            roots.append(child)
    return roots


def upsert_project_catalog_entry(name: str, slug: str, project_dir: Path, novel_path: Path) -> None:
    existing = db.one("select id from projects where slug=?", (slug,))
    plan_bundle = discover_plan_bundle(project_dir, name)
    if existing:
        db.update(
            "update projects set name=?, novel_path=?, project_dir=?, plan_bundle_path=?, updated_at=? where id=?",
            (name, str(novel_path), str(project_dir), str(plan_bundle), now_iso(), existing["id"]),
        )
        return
    db.execute(
        """
        insert into projects(name, slug, novel_path, project_dir, plan_bundle_path, created_at, updated_at)
        values(?, ?, ?, ?, ?, ?, ?)
        """,
        (name, slug, str(novel_path), str(project_dir), str(plan_bundle), now_iso(), now_iso()),
    )


def ensure_catalog_projects() -> None:
    for root in iter_screen_script_project_roots():
        name = screen_script_display_name(root)
        slug = "screen_script" if root.resolve() == SCREEN_SCRIPT_ROOT.resolve() else slugify(root.name)
        upsert_project_catalog_entry(
            name,
            slug,
            root,
            first_existing_markdown(root, ["归档/ep001.md"]),
        )
    if NOVEL_ROOT.exists():
        for root in sorted(path for path in NOVEL_ROOT.iterdir() if path.is_dir() and (path / "assets").exists()):
            if root.name == "ginza_night":
                name = "GinzaNight"
                preferred = ["ginza_night.md"]
            elif root.name == "sample_chapter":
                name = "SampleChapter"
                preferred = ["SampleChapter.md"]
            else:
                name = safe_name(root.name)
                preferred = [f"{root.name}.md"]
            upsert_project_catalog_entry(name, slugify(root.name), root, first_existing_markdown(root, preferred))


def is_catalog_project(row: dict[str, Any]) -> bool:
    project_dir = Path(row["project_dir"]).resolve()
    if project_dir == SCREEN_SCRIPT_ROOT.resolve():
        return True
    try:
        project_dir.relative_to(SCREEN_SCRIPT_ROOT.resolve())
    except ValueError:
        pass
    else:
        return project_dir.parent.resolve() == SCREEN_SCRIPT_ROOT.resolve() and screen_script_project_markers(project_dir)
    try:
        project_dir.relative_to(NOVEL_ROOT.resolve())
    except ValueError:
        return False
    return project_dir.parent.resolve() == NOVEL_ROOT.resolve() and (project_dir / "assets").exists()


def execution_dir(project: dict[str, Any]) -> Path:
    bundle = Path(project.get("plan_bundle_path") or "")
    return bundle / EXECUTION_DIR_NAME


def records_dir(project: dict[str, Any]) -> Path:
    return execution_dir(project) / "records"


def discover_plan_bundle(project_dir: Path, project_name: str) -> Path:
    if (project_dir / EXECUTION_DIR_NAME).exists():
        return project_dir.resolve()
    candidates = sorted(project_dir.glob("*_webui_plan"))
    if candidates:
        return candidates[-1].resolve()
    candidates = sorted(project_dir.glob("*_项目文件整理版"))
    if candidates:
        return candidates[-1].resolve()
    return (project_dir / f"{safe_name(project_name)}_webui_plan").resolve()


def project_plan_bundles(project: dict[str, Any]) -> list[Path]:
    primary = Path(project.get("plan_bundle_path") or "")
    project_dir = Path(project["project_dir"])
    bundles: list[Path] = []
    if primary.exists() and (primary / EXECUTION_DIR_NAME).exists():
        bundles.append(primary.resolve())
    if (project_dir / EXECUTION_DIR_NAME).exists():
        bundles.append(project_dir.resolve())
    if (project_dir / "assets").exists():
        for candidate in sorted(project_dir.iterdir()):
            if candidate.is_dir() and (candidate / EXECUTION_DIR_NAME).exists():
                bundles.append(candidate.resolve())
    deduped: list[Path] = []
    seen: set[Path] = set()
    for bundle in bundles:
        if bundle in seen:
            continue
        seen.add(bundle)
        deduped.append(bundle)
    return deduped


def infer_episode_id_from_record(path: Path) -> str:
    match = re.match(r"(EP\d+)_SH\d+_record\.json$", path.name, re.IGNORECASE)
    return match.group(1).upper() if match else "EP01"


def sync_project_index(project_id: int) -> None:
    project = project_by_id(project_id)
    plan_bundle = Path(project.get("plan_bundle_path") or "")
    if not plan_bundle.exists():
        guessed = discover_plan_bundle(Path(project["project_dir"]), project["name"])
        if guessed.exists():
            plan_bundle = guessed
            db.update(
                "update projects set plan_bundle_path = ?, updated_at = ? where id = ?",
                (str(plan_bundle), now_iso(), project_id),
            )

    for bundle_index, bundle in enumerate(project_plan_bundles(project)):
        rec_dir = bundle / EXECUTION_DIR_NAME / "records"
        for record in sorted(rec_dir.glob("EP*_SH*_record.json")):
            episode_id = infer_episode_id_from_record(record)
            shot_match = re.search(r"(SH\d+)", record.name, re.IGNORECASE)
            shot_id = shot_match.group(1).upper() if shot_match else record.stem
            db.execute(
                """
                insert into episodes(project_id, episode_id, title, status, updated_at)
                values(?, ?, ?, 'ready', ?)
                on conflict(project_id, episode_id) do update set status='ready', updated_at=excluded.updated_at
                """,
                (project_id, episode_id, f"{project['name']} {episode_id}", now_iso()),
            )
            if bundle_index == 0:
                db.execute(
                    """
                    insert into shots(project_id, episode_id, shot_id, record_path, status, updated_at)
                    values(?, ?, ?, ?, 'ready', ?)
                    on conflict(project_id, episode_id, shot_id) do update set
                      record_path=excluded.record_path, status='ready', updated_at=excluded.updated_at
                    """,
                    (project_id, episode_id, shot_id, str(record), now_iso()),
                )
            else:
                db.execute(
                    """
                    insert into shots(project_id, episode_id, shot_id, record_path, status, updated_at)
                    values(?, ?, ?, ?, 'ready', ?)
                    on conflict(project_id, episode_id, shot_id) do nothing
                    """,
                    (project_id, episode_id, shot_id, str(record), now_iso()),
                )

    scan_assets(project_id)
    scan_artifacts(project_id)


def upsert_asset(
    project_id: int,
    asset_type: str,
    path: Path,
    label: str,
    episode_id: str = "",
    shot_id: str = "",
    prompt_path: Path | None = None,
    stale: int = 0,
) -> None:
    if not path.exists() or not path.is_file():
        return
    db.execute(
        """
        insert into assets(project_id, asset_type, episode_id, shot_id, label, canonical_path, prompt_path, status, stale, updated_at)
        values(?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)
        on conflict(project_id, canonical_path) do update set
          asset_type=excluded.asset_type,
          episode_id=excluded.episode_id,
          shot_id=excluded.shot_id,
          label=excluded.label,
          prompt_path=excluded.prompt_path,
          stale=excluded.stale,
          updated_at=excluded.updated_at
        """,
        (
            project_id,
            asset_type,
            episode_id,
            shot_id,
            label,
            str(path),
            str(prompt_path or ""),
            int(stale),
            now_iso(),
        ),
    )


def normalized_token(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())


def infer_episode_id_from_text(value: str) -> str:
    match = re.search(r"ep\s*0*(\d+)", value, re.IGNORECASE)
    if match:
        return f"EP{int(match.group(1)):02d}"
    return ""


def infer_episode_id_from_records_dir(path: Path) -> str:
    try:
        for record in sorted(path.glob("EP*_SH*_record.json")):
            return infer_episode_id_from_record(record)
    except Exception:
        pass
    return ""


def project_aliases(project: dict[str, Any]) -> set[str]:
    values = {
        str(project.get("slug") or ""),
        str(project.get("name") or ""),
        Path(str(project.get("project_dir") or "")).name,
        Path(str(project.get("novel_path") or "")).stem,
        Path(str(project.get("plan_bundle_path") or "")).name,
    }
    aliases: set[str] = set()
    generic = {"novel", "screen_script", "test", "assets", "characters"}
    for value in values:
        slug = slugify(value)
        compact = normalized_token(value)
        for alias in (slug, normalized_token(slug), compact):
            if len(alias) >= 5 and alias not in generic:
                aliases.add(alias)
    return aliases


def manifest_records_match_project(project: dict[str, Any], data: dict[str, Any]) -> bool:
    raw_records_dir = str(data.get("records_dir") or "").strip()
    if not raw_records_dir:
        return False
    candidate = resolve_repo_path(raw_records_dir)
    project_records = records_dir(project).resolve()
    plan_bundle = Path(project.get("plan_bundle_path") or "").resolve()
    try:
        if candidate.resolve() == project_records:
            return True
        candidate.resolve().relative_to(project_records)
        return True
    except Exception:
        pass
    if plan_bundle.exists():
        try:
            candidate.resolve().relative_to(plan_bundle)
            return True
        except Exception:
            pass
    return False


def test_output_matches_project(project: dict[str, Any], path: Path, data: dict[str, Any] | None = None) -> bool:
    if data and manifest_records_match_project(project, data):
        return True
    haystack = normalized_token(" ".join(path.parts[-3:]))
    return any(alias in haystack for alias in project_aliases(project))


def manifest_episode_id(path: Path, data: dict[str, Any]) -> str:
    raw_records_dir = str(data.get("records_dir") or "").strip()
    if raw_records_dir:
        records_path = resolve_repo_path(raw_records_dir)
        episode_id = infer_episode_id_from_records_dir(records_path)
        if episode_id:
            return episode_id
    return infer_episode_id_from_text(path.as_posix()) or "EP01"


def path_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return ""


def data_uri_to_file(data_uri: str, out_path: Path) -> Path | None:
    match = re.match(r"data:(image/[a-zA-Z0-9.+-]+);base64,(.+)", data_uri, re.DOTALL)
    if not match:
        return None
    mime = match.group(1).lower()
    ext = ".jpg" if mime in {"image/jpeg", "image/jpg"} else ".png" if mime == "image/png" else ".webp" if mime == "image/webp" else ".img"
    out_path = out_path.with_suffix(ext)
    try:
        raw = base64.b64decode(match.group(2), validate=False)
    except Exception:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not out_path.exists() or out_path.stat().st_size != len(raw):
        out_path.write_bytes(raw)
    return out_path


def image_input_data_uri(image_input_map: Path, shot_id: str) -> str:
    if not image_input_map.exists():
        return ""
    try:
        data = read_json(image_input_map)
    except Exception:
        return ""
    entry = data.get(shot_id) if isinstance(data, dict) else None
    if isinstance(entry, str) and entry.startswith("data:image/"):
        return entry
    if isinstance(entry, dict):
        value = str(entry.get("image") or entry.get("url") or "")
        if value.startswith("data:image/"):
            return value
    return ""


def materialize_run_keyframe(run_dir: Path, run_data: dict[str, Any], shot_id: str) -> tuple[Path | None, Path | None]:
    image_map_raw = str(run_data.get("resolved_image_input_map_path") or run_data.get("image_input_map") or "").strip()
    if not image_map_raw:
        return None, None
    image_map = resolve_repo_path(image_map_raw)
    data_uri = image_input_data_uri(image_map, shot_id)
    if not data_uri:
        payload = run_dir / shot_id / "payload.preview.json"
        try:
            payload_data = read_json(payload) if payload.exists() else {}
        except Exception:
            payload_data = {}
        value = str(payload_data.get("image") or "")
        data_uri = value if value.startswith("data:image/") else ""
    if not data_uri:
        return None, None
    out = CACHE_ROOT / "keyframes" / run_dir.name / shot_id / "start" / "start"
    output = data_uri_to_file(data_uri, out)
    prompts_root = str(run_data.get("keyframe_prompts_root") or "").strip()
    prompt = resolve_repo_path(prompts_root) / shot_id / "start" / "prompt.txt" if prompts_root else None
    return output, prompt if prompt and prompt.exists() else None


def upsert_artifact_run(
    project_id: int,
    episode_id: str,
    run_type: str,
    run_dir: Path,
    manifest_path: Path | None = None,
    data: dict[str, Any] | None = None,
) -> int:
    data = data or {}
    run_dir = run_dir.resolve()
    manifest_path = manifest_path.resolve() if manifest_path and manifest_path.exists() else None
    records = str(data.get("records_dir") or "")
    prompts_root = str(data.get("keyframe_prompts_root") or "")
    db.execute(
        """
        insert into artifact_runs(project_id, episode_id, run_name, run_type, run_dir, manifest_path, records_dir, keyframe_prompts_root, mtime, updated_at)
        values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(project_id, run_type, run_dir) do update set
          episode_id=excluded.episode_id,
          run_name=excluded.run_name,
          manifest_path=excluded.manifest_path,
          records_dir=excluded.records_dir,
          keyframe_prompts_root=excluded.keyframe_prompts_root,
          mtime=excluded.mtime,
          updated_at=excluded.updated_at
        """,
        (
            project_id,
            episode_id,
            run_dir.name,
            run_type,
            str(run_dir),
            str(manifest_path or ""),
            records,
            prompts_root,
            path_mtime(manifest_path or run_dir),
            now_iso(),
        ),
    )
    row = db.one("select id from artifact_runs where project_id=? and run_type=? and run_dir=?", (project_id, run_type, str(run_dir)))
    return int(row["id"]) if row else 0


def upsert_artifact_candidate(
    project_id: int,
    episode_id: str,
    shot_id: str,
    media_type: str,
    path: Path,
    run_id: int,
    run_name: str,
    prompt_path: Path | None = None,
    payload_path: Path | None = None,
    manifest_path: Path | None = None,
    source_kind: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    if not path.exists() or not path.is_file():
        return
    db.execute(
        """
        insert into artifact_candidates(project_id, episode_id, shot_id, media_type, path, run_id, run_name, prompt_path, payload_path, manifest_path, source_kind, status, mtime, metadata_json, updated_at)
        values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?)
        on conflict(project_id, media_type, path) do update set
          episode_id=excluded.episode_id,
          shot_id=excluded.shot_id,
          run_id=excluded.run_id,
          run_name=excluded.run_name,
          prompt_path=excluded.prompt_path,
          payload_path=excluded.payload_path,
          manifest_path=excluded.manifest_path,
          source_kind=excluded.source_kind,
          status=excluded.status,
          mtime=excluded.mtime,
          metadata_json=excluded.metadata_json,
          updated_at=excluded.updated_at
        """,
        (
            project_id,
            episode_id.upper(),
            shot_id.upper(),
            media_type,
            str(path.resolve()),
            run_id,
            run_name,
            str(prompt_path.resolve()) if prompt_path and prompt_path.exists() else "",
            str(payload_path.resolve()) if payload_path and payload_path.exists() else "",
            str(manifest_path.resolve()) if manifest_path and manifest_path.exists() else "",
            source_kind,
            path_mtime(path),
            json.dumps(metadata or {}, ensure_ascii=False),
            now_iso(),
        ),
    )


def artifact_candidate_dict(candidate: dict[str, Any], selected_source: str = "") -> dict[str, Any]:
    return {
        "candidate_id": candidate["id"],
        "asset_id": candidate["id"],
        "asset_type": "keyframe" if candidate["media_type"] == "keyframe" else "video_clip",
        "media_type": candidate["media_type"],
        "label": f"{candidate['shot_id']} {candidate['media_type']}",
        "path": candidate["path"],
        "prompt_path": candidate.get("prompt_path") or "",
        "payload_path": candidate.get("payload_path") or "",
        "manifest_path": candidate.get("manifest_path") or "",
        "run_name": candidate.get("run_name") or "",
        "mtime": candidate.get("mtime") or "",
        "status": candidate.get("status") or "ready",
        "stale": 0,
        "source_kind": candidate.get("source_kind") or "",
        "selected_source": selected_source,
    }


def candidate_dict(asset: dict[str, Any], payload_path: Path | None = None) -> dict[str, Any]:
    canonical = Path(asset["canonical_path"])
    run_dir = canonical.parent.parent if asset["asset_type"] == "video_clip" else canonical.parent.parent.parent
    if not run_dir.exists():
        run_dir = canonical.parent
    payload = payload_path or canonical.parent / "payload.preview.json"
    return {
        "asset_id": asset["id"],
        "asset_type": asset["asset_type"],
        "label": asset["label"],
        "path": asset["canonical_path"],
        "prompt_path": asset.get("prompt_path") or "",
        "payload_path": str(payload) if payload.exists() else "",
        "run_name": run_dir.name,
        "mtime": path_mtime(canonical),
        "status": "stale" if asset.get("stale") else asset.get("status", "ready"),
        "stale": int(asset.get("stale") or 0),
    }


def keyframe_outputs_from_manifest(data: dict[str, Any]) -> list[tuple[str, str, Path, Path | None]]:
    outputs: list[tuple[str, str, Path, Path | None]] = []
    seen: set[Path] = set()

    def add(shot_id: str, phase: str, value: str, prompt_value: str = "") -> None:
        if not value or value.startswith("data:"):
            return
        path = resolve_repo_path(value)
        if path in seen or not path.exists() or not path.is_file():
            return
        seen.add(path)
        prompt = resolve_repo_path(prompt_value) if prompt_value else path.parent / "prompt.txt"
        outputs.append((shot_id.upper(), phase, path, prompt if prompt.exists() else None))

    items = data.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            shot_id = str(item.get("shot_id") or "").upper()
            if not shot_id:
                continue
            prompt_value = str(item.get("prompt_path") or "").strip()
            for key in ("output_path", "output_file", "image_path", "path"):
                add(shot_id, "keyframe", str(item.get(key) or "").strip(), prompt_value)

    shots_result = data.get("shots_result")
    if isinstance(shots_result, dict):
        for shot_id, result in shots_result.items():
            if not isinstance(result, dict):
                continue
            for phase, phase_data in result.items():
                if not isinstance(phase_data, dict):
                    continue
                prompt_value = str(phase_data.get("prompt_path") or "").strip()
                for key in ("output_file", "output_path", "image_path", "path"):
                    add(str(shot_id), str(phase), str(phase_data.get(key) or "").strip(), prompt_value)
    return outputs


def scan_assets(project_id: int) -> None:
    project = project_by_id(project_id)
    project_dir = Path(project["project_dir"])
    characters_dir = project_dir / "assets" / "characters"
    for image in sorted([*characters_dir.glob("*.jpg"), *characters_dir.glob("*.png"), *characters_dir.glob("*.webp")]):
        if image.name.endswith(".openai_response.json"):
            continue
        prompt = image.with_suffix(".prompt.txt")
        profile_prompt = image.with_suffix(".prompt.md")
        upsert_asset(
            project_id,
            "character_image",
            image,
            image.stem,
            prompt_path=prompt if prompt.exists() else profile_prompt if profile_prompt.exists() else None,
        )

    cover_dir = project_dir / "assets" / "cover_page"
    for image in sorted(cover_dir.glob("*.png")):
        upsert_asset(project_id, "cover_page", image, image.stem)

    db.update(
        "delete from assets where project_id=? and asset_type in ('keyframe', 'video_clip', 'assembled_episode')",
        (project_id,),
    )

    for video in sorted([*TEST_ROOT.glob("*assembl*/episode_*.mp4"), *TEST_ROOT.glob("*assembly*/episode_*.mp4")]):
        if not test_output_matches_project(project, video.parent):
            continue
        ep_match = re.search(r"(EP\d+)", video.name, re.IGNORECASE)
        episode_id = ep_match.group(1).upper() if ep_match else infer_episode_id_from_text(video.parent.name)
        upsert_asset(project_id, "assembled_episode", video, video.stem, episode_id)


def scan_artifacts(project_id: int) -> None:
    project = project_by_id(project_id)
    db.update("delete from artifact_candidates where project_id=?", (project_id,))
    db.update("delete from artifact_runs where project_id=?", (project_id,))

    for manifest in sorted(TEST_ROOT.glob("*keyframe*/keyframe_manifest.json")):
        try:
            data = read_json(manifest)
        except Exception:
            continue
        if not test_output_matches_project(project, manifest.parent, data):
            continue
        episode_id = manifest_episode_id(manifest, data)
        run_id = upsert_artifact_run(project_id, episode_id, "keyframe", manifest.parent, manifest, data)
        for shot_id, phase, output, prompt in keyframe_outputs_from_manifest(data):
            payload = output.parent / "payload.preview.json"
            upsert_artifact_candidate(
                project_id,
                episode_id,
                shot_id,
                "keyframe",
                output,
                run_id,
                manifest.parent.name,
                prompt,
                payload if payload.exists() else None,
                manifest,
                "keyframe_manifest",
                {"phase": phase},
            )

    for clip in sorted(TEST_ROOT.glob("*seedance*/SH*/output.mp4")):
        run_dir = clip.parent.parent
        run_manifest = run_dir / "run_manifest.json"
        run_data: dict[str, Any] = {}
        if run_manifest.exists():
            try:
                run_data = read_json(run_manifest)
            except Exception:
                run_data = {}
        if not test_output_matches_project(project, run_dir, run_data):
            continue
        shot_id = clip.parent.name.upper()
        episode_id = manifest_episode_id(run_dir, run_data)
        run_id = upsert_artifact_run(project_id, episode_id, "clip", run_dir, run_manifest if run_manifest.exists() else None, run_data)
        prompt = clip.parent / "prompt.final.txt"
        payload = clip.parent / "payload.preview.json"
        upsert_artifact_candidate(
            project_id,
            episode_id,
            shot_id,
            "clip",
            clip,
            run_id,
            run_dir.name,
            prompt if prompt.exists() else None,
            payload if payload.exists() else None,
            run_manifest if run_manifest.exists() else None,
            "output_file",
            {"manifest_shots": run_data.get("shots") if isinstance(run_data.get("shots"), list) else []},
        )
        keyframe, keyframe_prompt = materialize_run_keyframe(run_dir, run_data, shot_id)
        if keyframe:
            upsert_artifact_candidate(
                project_id,
                episode_id,
                shot_id,
                "keyframe",
                keyframe,
                run_id,
                run_dir.name,
                keyframe_prompt,
                payload if payload.exists() else None,
                run_manifest if run_manifest.exists() else None,
                "image_input_map",
            )


def record_summary(record_path: Path) -> dict[str, Any]:
    result = {
        "summary": "",
        "source_excerpt": "",
        "location": "",
        "characters": [],
        "props": [],
        "status": "missing",
    }
    if not record_path.exists():
        return result
    try:
        data = read_json(record_path)
    except Exception:
        result["status"] = "unreadable"
        return result
    source = data.get("source_trace") if isinstance(data.get("source_trace"), dict) else {}
    selection = source.get("selection_plan") if isinstance(source.get("selection_plan"), dict) else {}
    shot_execution = data.get("shot_execution") if isinstance(data.get("shot_execution"), dict) else {}
    first_frame = data.get("first_frame_contract") if isinstance(data.get("first_frame_contract"), dict) else {}
    header = data.get("record_header") if isinstance(data.get("record_header"), dict) else {}
    summary = str(selection.get("summary") or shot_execution.get("action_intent") or data.get("keyframe_moment") or "")
    source_excerpt = str(source.get("shot_source_excerpt") or source.get("shot_context_excerpt") or "")
    visible = first_frame.get("visible_characters") if isinstance(first_frame.get("visible_characters"), list) else []
    props = first_frame.get("key_props") if isinstance(first_frame.get("key_props"), list) else []
    result.update(
        {
            "summary": summary,
            "source_excerpt": source_excerpt,
            "location": str(first_frame.get("location") or source.get("parent_scene_name") or ""),
            "characters": [str(item) for item in visible[:8]],
            "props": [str(item) for item in props[:8]],
            "status": str(header.get("status") or "ready"),
        }
    )
    return result


def linked_assets_for_record(project_id: int, record_info: dict[str, Any]) -> list[dict[str, Any]]:
    terms = {normalized_token(str(v)) for key in ("characters", "props", "location") for v in (record_info.get(key) if isinstance(record_info.get(key), list) else [record_info.get(key)]) if v}
    if not terms:
        return []
    rows = db.all(
        """
        select * from assets
        where project_id=? and asset_type in ('character_image', 'cover_page')
        order by asset_type, label
        """,
        (project_id,),
    )
    linked = []
    for row in rows:
        asset = dict(row)
        label = normalized_token(asset["label"])
        if any(term and (term in label or label in term) for term in terms):
            linked.append({"asset_type": asset["asset_type"], "label": asset["label"], "path": asset["canonical_path"]})
    return linked[:10]


def artifact_rows(project_id: int, episode_id: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in db.all(
            """
            select * from artifact_candidates
            where project_id=? and episode_id=?
            order by media_type, shot_id, mtime desc, id desc
            """,
            (project_id, episode_id),
        )
    ]


def artifact_selection_path(project_id: int, episode_id: str, shot_id: str, media_type: str) -> str:
    row = db.one(
        """
        select candidate_path from artifact_selections
        where project_id=? and episode_id=? and shot_id=? and media_type=?
        """,
        (project_id, episode_id, shot_id, media_type),
    )
    return str(row["candidate_path"]) if row else ""


def default_candidate(
    candidates: list[dict[str, Any]],
    media_type: str,
    paired_run_name: str = "",
) -> dict[str, Any] | None:
    if media_type == "keyframe" and paired_run_name:
        paired = next((candidate for candidate in candidates if candidate["run_name"] == paired_run_name), None)
        if paired:
            return paired
    return candidates[0] if candidates else None


def selected_candidate(
    candidates: list[dict[str, Any]],
    selected_path: str,
    default_row: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str]:
    if selected_path:
        selected = next((candidate for candidate in candidates if candidate["path"] == selected_path), None)
        if selected:
            return selected, "user"
    return (default_row, "default") if default_row else (None, "")


def build_shot_board(project_id: int, episode_id: str) -> dict[str, Any]:
    project = project_by_id(project_id)
    episode_id = episode_id.upper()
    sync_project_index(project_id)
    shots = [dict(r) for r in db.all("select * from shots where project_id=? and episode_id=? order by shot_id", (project_id, episode_id))]
    by_shot: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for candidate in artifact_rows(project_id, episode_id):
        shot_id = str(candidate.get("shot_id") or "").upper()
        if not shot_id:
            continue
        entry = by_shot.setdefault(shot_id, {"keyframes": [], "video_clips": []})
        if candidate["media_type"] == "keyframe":
            entry["keyframes"].append(candidate)
        elif candidate["media_type"] == "clip":
            entry["video_clips"].append(candidate)

    rows = []
    for shot in shots:
        shot_id = shot["shot_id"]
        record_path = Path(shot["record_path"])
        info = record_summary(record_path)
        media = by_shot.get(shot_id, {"keyframes": [], "video_clips": []})
        media["keyframes"].sort(key=lambda item: (item.get("mtime") or "", item.get("id") or 0), reverse=True)
        media["video_clips"].sort(key=lambda item: (item.get("mtime") or "", item.get("id") or 0), reverse=True)
        selected_clip_path = artifact_selection_path(project_id, episode_id, shot_id, "clip")
        selected_keyframe_path = artifact_selection_path(project_id, episode_id, shot_id, "keyframe")
        default_video_row = default_candidate(media["video_clips"], "clip")
        default_keyframe_row = default_candidate(
            media["keyframes"],
            "keyframe",
            str(default_video_row.get("run_name") or "") if default_video_row else "",
        )
        selected_video_row, video_source = selected_candidate(media["video_clips"], selected_clip_path, default_video_row)
        selected_keyframe_default = default_candidate(
            media["keyframes"],
            "keyframe",
            str(selected_video_row.get("run_name") or "") if selected_video_row else "",
        )
        selected_keyframe_row, keyframe_source = selected_candidate(media["keyframes"], selected_keyframe_path, selected_keyframe_default)
        keyframe_candidates = [artifact_candidate_dict(item, "user" if item["path"] == selected_keyframe_path else "") for item in media["keyframes"]]
        clip_candidates = [artifact_candidate_dict(item, "user" if item["path"] == selected_clip_path else "") for item in media["video_clips"]]
        default_keyframe = artifact_candidate_dict(default_keyframe_row, "default") if default_keyframe_row else None
        default_video = artifact_candidate_dict(default_video_row, "default") if default_video_row else None
        selected_keyframe = artifact_candidate_dict(selected_keyframe_row, keyframe_source) if selected_keyframe_row else None
        selected_video = artifact_candidate_dict(selected_video_row, video_source) if selected_video_row else None
        rows.append(
            {
                "shot_id": shot_id,
                "episode_id": shot["episode_id"],
                "record_path": shot["record_path"],
                "record_status": info["status"],
                "summary": info["summary"],
                "source_excerpt": info["source_excerpt"],
                "location": info["location"],
                "characters": info["characters"],
                "props": info["props"],
                "keyframes": keyframe_candidates,
                "video_clips": clip_candidates,
                "keyframe_candidates": keyframe_candidates,
                "clip_candidates": clip_candidates,
                "default_keyframe": default_keyframe,
                "default_video": default_video,
                "selected_keyframe": selected_keyframe,
                "selected_clip": selected_video,
                "linked_assets": linked_assets_for_record(project_id, info),
                "qa": [],
            }
        )

    counts = {
        "shots": len(rows),
        "keyframes": sum(1 for row in rows if row["keyframes"]),
        "clips": sum(1 for row in rows if row["video_clips"]),
        "missing_keyframes": sum(1 for row in rows if not row["keyframes"]),
        "missing_clips": sum(1 for row in rows if not row["video_clips"]),
        "stale": sum(1 for row in rows for item in [*row["keyframes"], *row["video_clips"]] if item["stale"]),
    }
    runs = []
    for job in db.all("select * from jobs where project_id=? and episode_id=? order by id desc limit 12", (project_id, episode_id)):
        runs.append(dict(job))
    return {"project": project, "episode_id": episode_id, "counts": counts, "shots": rows, "runs": runs}


def latest_job(project_id: int, step: str, episode_id: str = "EP01") -> dict[str, Any] | None:
    row = db.one(
        "select * from jobs where project_id = ? and step = ? and episode_id = ? order by id desc limit 1",
        (project_id, step, episode_id),
    )
    return row_dict(row)


def latest_director_outputs(project: dict[str, Any], episode_id: str) -> dict[str, str]:
    prefix = f"webui_{project['slug']}_{episode_id.lower()}_"
    manifests = sorted(TEST_ROOT.glob(f"{prefix}*_director_manifest.json"), key=lambda p: p.stat().st_mtime)
    for path in reversed(manifests):
        try:
            data = read_json(path)
            outputs = data.get("outputs")
            if isinstance(outputs, dict):
                return {str(k): str(v) for k, v in outputs.items()}
        except Exception:
            continue
    return {}


def latest_seedance_dir(project: dict[str, Any], episode_id: str) -> Path | None:
    dirs = [p for p in TEST_ROOT.glob(f"webui_{project['slug']}_{episode_id.lower()}_seedance_*") if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def latest_assembly_dir(project: dict[str, Any], episode_id: str) -> Path | None:
    dirs = [p for p in TEST_ROOT.glob(f"webui_{project['slug']}_{episode_id.lower()}_assembled_*") if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def create_concat_file(project: dict[str, Any], episode_id: str, shots: list[str]) -> Path:
    seedance_dir = latest_seedance_dir(project, episode_id)
    if not seedance_dir:
        raise HTTPException(status_code=400, detail="no Seedance output directory found")
    shot_filter = {s.upper() for s in shots if s.strip()}
    clips = []
    for clip in sorted(seedance_dir.glob("SH*/output.mp4")):
        if shot_filter and clip.parent.name.upper() not in shot_filter:
            continue
        clips.append(clip.resolve())
    if not clips:
        raise HTTPException(status_code=400, detail="no output.mp4 clips found for assembly")
    concat = seedance_dir / f"concat_{episode_id}_{int(time.time())}.txt"
    concat.write_text("".join(f"file '{clip}'\n" for clip in clips), encoding="utf-8")
    return concat


def build_command(req: JobRequest, project: dict[str, Any], ts: str) -> tuple[list[str], str]:
    step = req.step
    if step not in PIPELINE_STEPS:
        raise HTTPException(status_code=400, detail=f"unknown step: {step}")

    episode_id = (req.episode_id or "EP01").upper()
    shots_arg = ",".join(s.upper() for s in req.shots if s.strip())
    py = sys.executable
    project_dir = Path(project["project_dir"])
    bundle = Path(project.get("plan_bundle_path") or discover_plan_bundle(project_dir, project["name"]))
    exec_dir = bundle / EXECUTION_DIR_NAME
    rec_dir = exec_dir / "records"
    name_safe = safe_name(project["name"])

    if step == "novel2video_plan":
        out_rel = f"{project['slug']}/{name_safe}_webui_plan"
        cmd = [
            py,
            "scripts/novel2video_plan.py",
            "--novel",
            rel(Path(project["novel_path"])),
            "--project-name",
            project["name"],
            "--episode",
            episode_id,
            "--shots",
            str(int(req.params.get("shot_count") or 13)),
            "--out",
            out_rel,
            "--backend",
            "llm",
            "--overwrite",
        ]
        if req.dry_run:
            cmd.append("--dry-run")
        return cmd, str(NOVEL_ROOT / out_rel)

    if not bundle.exists() and step != "novel2video_plan":
        raise HTTPException(status_code=400, detail="plan bundle not found; run novel2video_plan first")

    if step == "character_image_gen":
        cmd = [py, "scripts/character_image_gen.py", "--novel", project["slug"]]
        if req.dry_run:
            cmd.append("--dry-run")
        if req.params.get("overwrite"):
            cmd.append("--overwrite")
        if shots_arg:
            # Character step does not use shots; keep scope visible in logs only.
            pass
        return cmd, str(project_dir / "assets" / "characters" / "character_image_gen_manifest.json")

    if step == "generate_cover_pages":
        cmd = [py, "scripts/generate_cover_pages.py", "--plan-dir", str(bundle)]
        if req.dry_run:
            cmd.append("--dry-run")
        if req.params.get("regenerate_base"):
            cmd.append("--regenerate-base")
        return cmd, str(project_dir / "assets" / "cover_page" / "cover_generation_manifest.json")

    if step == "run_novel_video_director":
        prefix = f"webui_{project['slug']}_{episode_id.lower()}_{ts}"
        cmd = [
            py,
            "scripts/run_novel_video_director.py",
            "--bundle",
            str(bundle),
            "--episode",
            episode_id,
            "--experiment-prefix",
            prefix,
        ]
        if shots_arg:
            cmd.extend(["--shots", shots_arg])
        if req.prepare_only:
            cmd.append("--prepare-only")
        if req.dry_run:
            cmd.append("--dry-run")
        if req.params.get("provider"):
            cmd.extend(["--provider", str(req.params["provider"])])
        if req.params.get("default_image"):
            cmd.extend(["--default-image", str(req.params["default_image"])])
        return cmd, str(TEST_ROOT / f"{prefix}_director_manifest.json")

    if step == "run_seedance_test":
        outputs = latest_director_outputs(project, episode_id)
        experiment = f"webui_{project['slug']}_{episode_id.lower()}_seedance_{ts}"
        cmd = [
            py,
            "scripts/run_seedance_test.py",
            "--experiment-name",
            experiment,
            "--records-dir",
            rel(rec_dir),
            "--model-profiles",
            rel(exec_dir / "30_model_capability_profiles_v1.json"),
            "--character-lock-profiles",
            rel(exec_dir / "35_character_lock_profiles_v1.json"),
        ]
        if outputs.get("image_input_map"):
            cmd.extend(["--image-input-map", rel(resolve_repo_path(outputs["image_input_map"]))])
        if outputs.get("duration_overrides"):
            cmd.extend(["--duration-overrides", rel(resolve_repo_path(outputs["duration_overrides"]))])
        if shots_arg:
            cmd.extend(["--shots", shots_arg])
        if req.prepare_only or req.dry_run:
            cmd.append("--prepare-only")
        if req.params.get("model_profile_id"):
            cmd.extend(["--model-profile-id", str(req.params["model_profile_id"])])
        return cmd, str(TEST_ROOT / experiment / "run_manifest.json")

    if step == "assemble_episode":
        concat = create_concat_file(project, episode_id, req.shots)
        outputs = latest_director_outputs(project, episode_id)
        out_dir = TEST_ROOT / f"webui_{project['slug']}_{episode_id.lower()}_assembled_{ts}"
        out_path = out_dir / f"episode_{episode_id}.mp4"
        cmd = [
            py,
            "scripts/assemble_episode.py",
            "--concat-file",
            rel(concat),
            "--out",
            rel(out_path),
            "--episode",
            episode_id,
            "--audio-policy",
            str(req.params.get("audio_policy") or "keep"),
        ]
        if outputs.get("image_input_map"):
            cmd.extend(["--image-input-map", rel(resolve_repo_path(outputs["image_input_map"]))])
        cover_dir = project_dir / "assets" / "cover_page"
        if cover_dir.exists() and not req.params.get("no_cover_page"):
            cmd.extend(["--cover-page-dir", rel(cover_dir)])
        return cmd, str(out_dir / "assembly_report.json")

    if step == "qa_episode_sync":
        director = latest_director_outputs(project, episode_id)
        seedance = latest_seedance_dir(project, episode_id)
        assembly = latest_assembly_dir(project, episode_id)
        if not director or not seedance or not assembly:
            raise HTTPException(status_code=400, detail="director, seedance, and assembly outputs are required for QA")
        concat_candidates = sorted(seedance.glob(f"concat_{episode_id}_*.txt"), key=lambda p: p.stat().st_mtime)
        if not concat_candidates:
            raise HTTPException(status_code=400, detail="concat file not found")
        out_path = assembly / "qa_sync_report.json"
        cmd = [
            py,
            "scripts/qa_episode_sync.py",
            "--language-plan",
            rel(resolve_repo_path(director["language_plan"])),
            "--concat-file",
            rel(concat_candidates[-1]),
            "--out",
            rel(out_path),
        ]
        if director.get("image_input_map"):
            cmd.extend(["--image-input-map", rel(resolve_repo_path(director["image_input_map"]))])
        assembly_report = assembly / "assembly_report.json"
        if assembly_report.exists():
            cmd.extend(["--assembly-report", rel(assembly_report)])
        return cmd, str(out_path)

    raise HTTPException(status_code=400, detail=f"unhandled step: {step}")


async def run_job(job_id: int, project_id: int, cmd: list[str], log_path: Path, output_manifest: str, dry_run: bool, provider: str | None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def append(line: str) -> None:
        with log_path.open("a", encoding="utf-8") as fp:
            fp.write(line.rstrip("\n") + "\n")

    db.update("update jobs set status='running', started_at=? where id=?", (now_iso(), job_id))
    append(f"[{now_iso()}] [WEBUI] job {job_id} starting")
    append("[CMD] " + " ".join(cmd))

    if dry_run:
        append(f"[{now_iso()}] [WEBUI] dry run completed; command was not executed")
        db.update(
            "update jobs set status='completed', returncode=0, ended_at=? where id=?",
            (now_iso(), job_id),
        )
        return

    lock = provider_locks.get(provider or "")
    try:
        if lock:
            append(f"[{now_iso()}] [WEBUI] waiting for provider lane: {provider}")
            await lock.acquire()
            append(f"[{now_iso()}] [WEBUI] acquired provider lane: {provider}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        running_processes[job_id] = proc
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            append(line.decode("utf-8", errors="replace").rstrip())
        code = await proc.wait()
        status = "completed" if code == 0 else "failed"
        append(f"[{now_iso()}] [WEBUI] job ended with code {code}")
        db.update(
            "update jobs set status=?, returncode=?, ended_at=?, output_manifest=? where id=?",
            (status, code, now_iso(), output_manifest if Path(output_manifest).exists() else "", job_id),
        )
        if code == 0:
            try:
                sync_project_index(project_id)
            except Exception as exc:
                append(f"[{now_iso()}] [WEBUI] index sync warning: {exc}")
    except asyncio.CancelledError:
        append(f"[{now_iso()}] [WEBUI] job canceled")
        db.update("update jobs set status='canceled', ended_at=? where id=?", (now_iso(), job_id))
    except Exception as exc:
        append(f"[{now_iso()}] [WEBUI] job failed: {exc}")
        db.update("update jobs set status='failed', ended_at=? where id=?", (now_iso(), job_id))
    finally:
        running_processes.pop(job_id, None)
        if lock:
            lock.release()


app = FastAPI(title="Short_videoGEN WebUI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5176", "http://127.0.0.1:5176"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "repo": str(REPO_ROOT), "db": str(DB_PATH)}


@app.get("/api/projects")
def list_projects() -> dict[str, Any]:
    ensure_catalog_projects()
    rows = [dict(r) for r in db.all("select * from projects order by name")]
    return {"projects": [row for row in rows if is_catalog_project(row)]}


@app.post("/api/projects")
async def create_project(
    name: str = Form(default=""),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if not file.filename.lower().endswith(".md"):
        raise HTTPException(status_code=400, detail="please upload a markdown .md file")
    raw_name = name.strip() or Path(file.filename).stem
    slug = slugify(raw_name)
    if db.one("select id from projects where slug = ?", (slug,)):
        slug = f"{slug}_{int(time.time())}"
    project_dir = NOVEL_ROOT / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    novel_path = project_dir / safe_name(file.filename)
    if novel_path.exists():
        novel_path = project_dir / f"{novel_path.stem}_{int(time.time())}{novel_path.suffix}"
    novel_path.write_bytes(await file.read())
    plan_bundle = discover_plan_bundle(project_dir, raw_name)
    project_id = db.execute(
        """
        insert into projects(name, slug, novel_path, project_dir, plan_bundle_path, created_at, updated_at)
        values(?, ?, ?, ?, ?, ?, ?)
        """,
        (raw_name, slug, str(novel_path), str(project_dir), str(plan_bundle), now_iso(), now_iso()),
    )
    sync_project_index(project_id)
    return {"project": project_by_id(project_id)}


@app.post("/api/projects/import")
def import_project(novel_path: str = Form(...), name: str = Form(default="")) -> dict[str, Any]:
    path = ensure_under_repo(resolve_repo_path(novel_path))
    if not path.exists() or path.suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="novel_path must point to an existing .md file under the repo")
    raw_name = name.strip() or path.parent.name or path.stem
    slug = slugify(path.parent.name or raw_name)
    project_dir = path.parent.resolve()
    plan_bundle = discover_plan_bundle(project_dir, raw_name)
    existing = db.one("select * from projects where slug = ?", (slug,))
    if existing:
        db.update(
            "update projects set name=?, novel_path=?, project_dir=?, plan_bundle_path=?, updated_at=? where id=?",
            (raw_name, str(path), str(project_dir), str(plan_bundle), now_iso(), existing["id"]),
        )
        project_id = int(existing["id"])
    else:
        project_id = db.execute(
            """
            insert into projects(name, slug, novel_path, project_dir, plan_bundle_path, created_at, updated_at)
            values(?, ?, ?, ?, ?, ?, ?)
            """,
            (raw_name, slug, str(path), str(project_dir), str(plan_bundle), now_iso(), now_iso()),
        )
    sync_project_index(project_id)
    return {"project": project_by_id(project_id)}


@app.get("/api/projects/{project_id}")
def get_project(project_id: int, episode_id: str = "EP01") -> dict[str, Any]:
    sync_project_index(project_id)
    project = project_by_id(project_id)
    episode_id = episode_id.upper()
    episodes = [dict(r) for r in db.all("select * from episodes where project_id=? order by episode_id", (project_id,))]
    shots = [dict(r) for r in db.all("select * from shots where project_id=? and episode_id=? order by shot_id", (project_id, episode_id))]
    assets = [dict(r) for r in db.all("select * from assets where project_id=? order by asset_type, episode_id, shot_id, label", (project_id,))]
    jobs = [dict(r) for r in db.all("select * from jobs where project_id=? order by id desc limit 30", (project_id,))]
    pipeline = []
    for step in PIPELINE_STEPS:
        job = latest_job(project_id, step, episode_id)
        status = job["status"] if job else ("ready" if step == "novel2video_plan" else "not_started")
        pipeline.append({"step": step, "status": status, "job": job})
    return {
        "project": project,
        "episodes": episodes,
        "shots": shots,
        "assets": assets,
        "jobs": jobs,
        "pipeline": pipeline,
    }


@app.get("/api/projects/{project_id}/shot-board")
def get_shot_board(project_id: int, episode_id: str = "EP01") -> dict[str, Any]:
    return build_shot_board(project_id, episode_id)


@app.put("/api/projects/{project_id}/artifact-selection")
def set_artifact_selection(project_id: int, req: ArtifactSelectionRequest) -> dict[str, Any]:
    episode_id = req.episode_id.upper()
    shot_id = req.shot_id.upper()
    media_type = req.media_type
    if req.reset:
        db.update(
            """
            delete from artifact_selections
            where project_id=? and episode_id=? and shot_id=? and media_type=?
            """,
            (project_id, episode_id, shot_id, media_type),
        )
        return {"selected": False}
    if req.candidate_id is None:
        raise HTTPException(status_code=400, detail="candidate_id is required unless reset=true")
    row = db.one(
        """
        select * from artifact_candidates
        where id=? and project_id=? and episode_id=? and shot_id=? and media_type=?
        """,
        (req.candidate_id, project_id, episode_id, shot_id, media_type),
    )
    if not row:
        raise HTTPException(status_code=404, detail="artifact candidate not found for this shot")
    candidate = dict(row)
    db.execute(
        """
        insert into artifact_selections(project_id, episode_id, shot_id, media_type, candidate_path, updated_at)
        values(?, ?, ?, ?, ?, ?)
        on conflict(project_id, episode_id, shot_id, media_type) do update set
          candidate_path=excluded.candidate_path,
          updated_at=excluded.updated_at
        """,
        (project_id, episode_id, shot_id, media_type, candidate["path"], now_iso()),
    )
    return {"selected": True, "candidate": artifact_candidate_dict(candidate, "user")}


@app.post("/api/jobs")
async def create_job(req: JobRequest) -> dict[str, Any]:
    project = project_by_id(req.project_id)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    cmd, output_manifest = build_command(req, project, ts)
    log_path = LOG_ROOT / f"job_{project['slug']}_{req.step}_{ts}.log"
    job_id = db.execute(
        """
        insert into jobs(project_id, step, scope, episode_id, shots, status, command_json, log_path, output_manifest, dry_run, created_at)
        values(?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)
        """,
        (
            req.project_id,
            req.step,
            req.scope,
            req.episode_id.upper(),
            ",".join(req.shots),
            json.dumps(cmd, ensure_ascii=False),
            str(log_path),
            output_manifest,
            int(req.dry_run),
            now_iso(),
        ),
    )
    asyncio.create_task(run_job(job_id, req.project_id, cmd, log_path, output_manifest, req.dry_run, API_STEPS.get(req.step)))
    return {"job": dict(db.one("select * from jobs where id=?", (job_id,)))}


@app.post("/api/jobs/{job_id}/stop")
async def stop_job(job_id: int) -> dict[str, Any]:
    proc = running_processes.get(job_id)
    if not proc:
        db.update("update jobs set status='canceled', ended_at=? where id=? and status in ('queued','running')", (now_iso(), job_id))
        return {"stopped": False}
    try:
        proc.send_signal(signal.SIGTERM)
    except ProcessLookupError:
        pass
    db.update("update jobs set status='canceled', ended_at=? where id=?", (now_iso(), job_id))
    return {"stopped": True}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: int) -> StreamingResponse:
    row = db.one("select * from jobs where id=?", (job_id,))
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    log_path = Path(row["log_path"])

    async def stream():
        offset = 0
        while True:
            if log_path.exists():
                text = log_path.read_text(encoding="utf-8", errors="replace")
                if len(text) > offset:
                    chunk = text[offset:]
                    offset = len(text)
                    for line in chunk.splitlines():
                        yield f"data: {json.dumps({'line': line}, ensure_ascii=False)}\n\n"
            latest = db.one("select status from jobs where id=?", (job_id,))
            if latest and latest["status"] in {"completed", "failed", "canceled"}:
                yield f"data: {json.dumps({'done': True, 'status': latest['status']})}\n\n"
                break
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int) -> dict[str, Any]:
    row = db.one("select * from jobs where id=?", (job_id,))
    if not row:
        raise HTTPException(status_code=404, detail="job not found")
    data = dict(row)
    log_path = Path(data["log_path"])
    data["log_tail"] = log_path.read_text(encoding="utf-8", errors="replace")[-12000:] if log_path.exists() else ""
    return {"job": data}


@app.get("/api/assets")
def list_assets(
    project_id: int,
    episode_id: str = "",
    shot_id: str = "",
    asset_type: str = "",
) -> dict[str, Any]:
    sync_project_index(project_id)
    clauses = ["project_id=?"]
    args: list[Any] = [project_id]
    if episode_id:
        clauses.append("episode_id=?")
        args.append(episode_id.upper())
    if shot_id:
        clauses.append("shot_id=?")
        args.append(shot_id.upper())
    if asset_type:
        clauses.append("asset_type=?")
        args.append(asset_type)
    rows = db.all(f"select * from assets where {' and '.join(clauses)} order by asset_type, episode_id, shot_id, label", tuple(args))
    return {"assets": [dict(r) for r in rows]}


def read_prompt_for_asset(asset: dict[str, Any]) -> str:
    prompt = str(asset.get("prompt_path") or "").strip()
    if prompt and Path(prompt).exists():
        return Path(prompt).read_text(encoding="utf-8", errors="replace")
    path = Path(asset["canonical_path"])
    for candidate in (path.with_suffix(".prompt.txt"), path.with_suffix(".prompt.md"), path.parent / "prompt.final.txt"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="replace")
    return ""


def is_allowed_asset_root(root: Path) -> bool:
    root = root.resolve()
    if root == SCREEN_SCRIPT_ROOT.resolve():
        return True
    try:
        root.relative_to(SCREEN_SCRIPT_ROOT.resolve())
        return True
    except ValueError:
        pass
    try:
        root.relative_to(NOVEL_ROOT.resolve())
        return True
    except ValueError:
        return False


def resolve_asset_root(value: str | Path) -> tuple[Path, Path]:
    root = ensure_under_repo(resolve_repo_path(value))
    if root.name == "assets":
        assets_dir = root
        root = root.parent
    else:
        assets_dir = root / "assets"
    if not is_allowed_asset_root(root):
        raise HTTPException(status_code=400, detail="asset root must be under novel/ or screen_script")
    if not assets_dir.exists() or not assets_dir.is_dir():
        raise HTTPException(status_code=404, detail="assets directory not found")
    return root.resolve(), assets_dir.resolve()


def discover_asset_roots() -> list[dict[str, str]]:
    roots: list[Path] = []
    if NOVEL_ROOT.exists():
        roots.extend(path for path in NOVEL_ROOT.iterdir() if path.is_dir() and (path / "assets").is_dir())
    roots.extend(root for root in iter_screen_script_project_roots() if (root / "assets").is_dir())
    result = []
    for root in sorted({path.resolve() for path in roots}, key=lambda p: rel(p).lower()):
        result.append(
            {
                "label": rel(root),
                "root_path": str(root),
                "asset_dir": str(root / "assets"),
            }
        )
    return result


def resolve_browser_prompt_path(image_path: Path) -> Path:
    prompt_txt = image_path.with_suffix(".prompt.txt")
    if prompt_txt.exists():
        return prompt_txt
    prompt_md = image_path.with_suffix(".prompt.md")
    if prompt_md.exists():
        return prompt_md
    return prompt_txt


def validate_browser_image_path(value: str | Path) -> Path:
    image = ensure_under_repo(resolve_repo_path(value))
    if image.suffix.lower() not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="asset image must be jpg, jpeg, png, or webp")
    if not image.exists() or not image.is_file():
        raise HTTPException(status_code=404, detail="asset image not found")

    parts = image.parts
    try:
        assets_index = parts.index("assets")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="asset image must be under an assets directory") from exc

    root = Path(*parts[:assets_index])
    assets_dir = Path(*parts[: assets_index + 1])
    resolve_asset_root(root)
    try:
        image.relative_to(assets_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="asset image is outside the selected assets directory") from exc
    return image


def browser_asset_item(image: Path, asset_type: str, batch: str, source_dir: Path) -> dict[str, Any]:
    prompt_path = resolve_browser_prompt_path(image)
    return {
        "asset_type": asset_type,
        "label": image.stem,
        "image_path": str(image),
        "prompt_path": str(prompt_path),
        "prompt_exists": prompt_path.exists(),
        "batch": batch,
        "source_dir": rel(source_dir),
    }


@app.get("/api/asset-roots")
def list_asset_roots() -> dict[str, Any]:
    return {"roots": discover_asset_roots()}


@app.get("/api/asset-browser")
def list_browser_assets(root_path: str = Query(...)) -> dict[str, Any]:
    root, assets_dir = resolve_asset_root(root_path)
    items: list[dict[str, Any]] = []

    characters_dir = assets_dir / "characters"
    for image in sorted(path for path in characters_dir.glob("*") if path.suffix.lower() in IMAGE_EXTENSIONS):
        items.append(browser_asset_item(image.resolve(), "character", "characters", characters_dir.resolve()))

    for asset_type, folder_name in (("prop", "props"), ("scene", "scenes")):
        for source_dir in sorted(path for path in assets_dir.glob(f"visual_refs*/{folder_name}") if path.is_dir()):
            batch = source_dir.parent.name
            for image in sorted(path for path in source_dir.glob("*") if path.suffix.lower() in IMAGE_EXTENSIONS):
                items.append(browser_asset_item(image.resolve(), asset_type, batch, source_dir.resolve()))

    counts = {
        "all": len(items),
        "character": sum(1 for item in items if item["asset_type"] == "character"),
        "prop": sum(1 for item in items if item["asset_type"] == "prop"),
        "scene": sum(1 for item in items if item["asset_type"] == "scene"),
    }
    batches = sorted({str(item["batch"]) for item in items})
    return {
        "root": {"label": rel(root), "root_path": str(root), "asset_dir": str(assets_dir)},
        "assets": items,
        "counts": counts,
        "batches": batches,
    }


@app.get("/api/asset-browser/prompt")
def get_browser_asset_prompt(image_path: str = Query(...)) -> dict[str, Any]:
    image = validate_browser_image_path(image_path)
    prompt_path = resolve_browser_prompt_path(image)
    prompt = prompt_path.read_text(encoding="utf-8", errors="replace") if prompt_path.exists() else ""
    return {
        "image_path": str(image),
        "prompt_path": str(prompt_path),
        "prompt": prompt,
        "prompt_exists": prompt_path.exists(),
    }


@app.put("/api/asset-browser/prompt")
def save_browser_asset_prompt(req: AssetPromptSaveRequest) -> dict[str, Any]:
    image = validate_browser_image_path(req.image_path)
    prompt_path = ensure_under_repo(resolve_browser_prompt_path(image))
    if prompt_path.parent != image.parent or prompt_path.stem not in {image.stem, f"{image.stem}.prompt"}:
        raise HTTPException(status_code=400, detail="prompt path must be a same-stem asset sidecar")
    if prompt_path.suffix not in {".txt", ".md"} or not prompt_path.name.startswith(f"{image.stem}.prompt"):
        raise HTTPException(status_code=400, detail="prompt path must be .prompt.txt or .prompt.md")
    prompt_path.write_text(req.prompt, encoding="utf-8")
    return {
        "saved": True,
        "image_path": str(image),
        "prompt_path": str(prompt_path),
        "prompt_exists": True,
    }


@app.get("/api/assets/{asset_id}")
def get_asset(asset_id: int) -> dict[str, Any]:
    row = db.one("select * from assets where id=?", (asset_id,))
    if not row:
        raise HTTPException(status_code=404, detail="asset not found")
    asset = dict(row)
    reviews = [dict(r) for r in db.all("select * from review_runs where asset_id=? order by id desc", (asset_id,))]
    return {"asset": asset, "base_prompt": read_prompt_for_asset(asset), "review_runs": reviews}


@app.post("/api/assets/{asset_id}/review-runs")
def create_review_run(asset_id: int, req: ReviewRunRequest) -> dict[str, Any]:
    row = db.one("select * from assets where id=?", (asset_id,))
    if not row:
        raise HTTPException(status_code=404, detail="asset not found")
    asset = dict(row)
    src = Path(asset["canonical_path"])
    if not src.exists():
        raise HTTPException(status_code=400, detail="canonical asset file is missing")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = REVIEW_ROOT / str(asset["project_id"]) / slugify(asset["label"]) / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    output = run_dir / src.name
    shutil.copy2(src, output)
    base_prompt = read_prompt_for_asset(asset)
    final_prompt = "\n\n".join([p for p in [base_prompt.strip(), req.prompt_override.strip()] if p])
    base_prompt_path = run_dir / "prompt.base.txt"
    final_prompt_path = run_dir / "prompt.final.txt"
    base_prompt_path.write_text(base_prompt, encoding="utf-8")
    (run_dir / "prompt.override.txt").write_text(req.prompt_override, encoding="utf-8")
    final_prompt_path.write_text(final_prompt, encoding="utf-8")
    write_json(
        run_dir / "manifest.json",
        {
            "asset_id": asset_id,
            "source": str(src),
            "output": str(output),
            "status": "prepared",
            "note": "v1 review run workspace; generation scripts remain canonical-path based.",
        },
    )
    review_id = db.execute(
        """
        insert into review_runs(asset_id, project_id, status, prompt_override, base_prompt_path, final_prompt_path, output_path, run_dir, created_at, updated_at)
        values(?, ?, 'prepared', ?, ?, ?, ?, ?, ?, ?)
        """,
        (asset_id, asset["project_id"], req.prompt_override, str(base_prompt_path), str(final_prompt_path), str(output), str(run_dir), now_iso(), now_iso()),
    )
    return {"review_run": dict(db.one("select * from review_runs where id=?", (review_id,)))}


def mark_downstream_stale(project_id: int, asset_type: str, episode_id: str, shot_id: str) -> None:
    if asset_type == "character_image":
        targets = ("keyframe", "video_clip", "assembled_episode")
    elif asset_type == "keyframe":
        targets = ("video_clip", "assembled_episode")
    elif asset_type == "video_clip":
        targets = ("assembled_episode",)
    else:
        targets = ()
    for target in targets:
        if shot_id and target != "assembled_episode":
            db.update(
                "update assets set stale=1, updated_at=? where project_id=? and asset_type=? and shot_id=?",
                (now_iso(), project_id, target, shot_id),
            )
        else:
            db.update(
                "update assets set stale=1, updated_at=? where project_id=? and asset_type=? and (?='' or episode_id=?)",
                (now_iso(), project_id, target, episode_id, episode_id),
            )


@app.post("/api/review-runs/{review_id}/accept")
def accept_review_run(review_id: int) -> dict[str, Any]:
    review_row = db.one("select * from review_runs where id=?", (review_id,))
    if not review_row:
        raise HTTPException(status_code=404, detail="review run not found")
    review = dict(review_row)
    asset = dict(db.one("select * from assets where id=?", (review["asset_id"],)))
    src = Path(review["output_path"])
    dst = Path(asset["canonical_path"])
    if not src.exists():
        raise HTTPException(status_code=400, detail="review output file is missing")
    archive_dir = ARCHIVE_ROOT / str(asset["project_id"]) / slugify(asset["label"]) / datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.copy2(dst, archive_dir / dst.name)
    shutil.copy2(src, dst)
    accepted_prompt = Path(review["run_dir"]) / "accepted.prompt.final.txt"
    if Path(review["final_prompt_path"]).exists():
        shutil.copy2(review["final_prompt_path"], accepted_prompt)
    db.update("update review_runs set status='accepted', updated_at=? where id=?", (now_iso(), review_id))
    db.update("update assets set stale=0, updated_at=? where id=?", (now_iso(), asset["id"]))
    mark_downstream_stale(asset["project_id"], asset["asset_type"], asset.get("episode_id") or "", asset.get("shot_id") or "")
    return {"accepted": True, "asset": dict(db.one("select * from assets where id=?", (asset["id"],)))}


@app.post("/api/review-runs/{review_id}/reject")
def reject_review_run(review_id: int) -> dict[str, Any]:
    if not db.one("select id from review_runs where id=?", (review_id,)):
        raise HTTPException(status_code=404, detail="review run not found")
    db.update("update review_runs set status='rejected', updated_at=? where id=?", (now_iso(), review_id))
    return {"rejected": True}


@app.get("/api/file")
def get_file(path: str = Query(...)) -> FileResponse:
    file_path = ensure_under_repo(resolve_repo_path(path))
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(file_path)


@app.get("/")
def root() -> dict[str, Any]:
    return {"service": "Short_videoGEN WebUI API", "frontend": "run Vite from webui/frontend"}
