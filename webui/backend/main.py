from __future__ import annotations

import asyncio
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


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def project_by_id(project_id: int) -> dict[str, Any]:
    row = db.one("select * from projects where id = ?", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail="project not found")
    return dict(row)


def execution_dir(project: dict[str, Any]) -> Path:
    bundle = Path(project.get("plan_bundle_path") or "")
    return bundle / EXECUTION_DIR_NAME


def records_dir(project: dict[str, Any]) -> Path:
    return execution_dir(project) / "records"


def discover_plan_bundle(project_dir: Path, project_name: str) -> Path:
    candidates = sorted(project_dir.glob("*_webui_plan"))
    if candidates:
        return candidates[-1].resolve()
    candidates = sorted(project_dir.glob("*_项目文件整理版"))
    if candidates:
        return candidates[-1].resolve()
    return (project_dir / f"{safe_name(project_name)}_webui_plan").resolve()


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

    if plan_bundle.exists():
        rec_dir = plan_bundle / EXECUTION_DIR_NAME / "records"
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
            db.execute(
                """
                insert into shots(project_id, episode_id, shot_id, record_path, status, updated_at)
                values(?, ?, ?, ?, 'ready', ?)
                on conflict(project_id, episode_id, shot_id) do update set
                  record_path=excluded.record_path, status='ready', updated_at=excluded.updated_at
                """,
                (project_id, episode_id, shot_id, str(record), now_iso()),
            )

    scan_assets(project_id)


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

    for manifest in sorted(TEST_ROOT.glob(f"webui_{project['slug']}_*_keyframes/keyframe_manifest.json")):
        try:
            data = read_json(manifest)
        except Exception:
            continue
        for item in data.get("items", []) if isinstance(data.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            shot_id = str(item.get("shot_id") or "").upper()
            episode_id = str(item.get("episode_id") or "")
            for key in ("output_path", "image_path", "path"):
                value = str(item.get(key) or "").strip()
                if value:
                    upsert_asset(project_id, "keyframe", resolve_repo_path(value), f"{shot_id} keyframe", episode_id, shot_id)

    for clip in sorted(TEST_ROOT.glob(f"webui_{project['slug']}_*_seedance_*/SH*/output.mp4")):
        shot_id = clip.parent.name.upper()
        ep_match = re.search(r"_(ep\d+)_", clip.parent.parent.name, re.IGNORECASE)
        episode_id = ep_match.group(1).upper() if ep_match else ""
        prompt = clip.parent / "prompt.final.txt"
        upsert_asset(project_id, "video_clip", clip, f"{episode_id} {shot_id}", episode_id, shot_id, prompt if prompt.exists() else None)

    for video in sorted(TEST_ROOT.glob(f"webui_{project['slug']}_assembled*/episode_*.mp4")):
        ep_match = re.search(r"(EP\d+)", video.name, re.IGNORECASE)
        episode_id = ep_match.group(1).upper() if ep_match else ""
        upsert_asset(project_id, "assembled_episode", video, video.stem, episode_id)


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
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "repo": str(REPO_ROOT), "db": str(DB_PATH)}


@app.get("/api/projects")
def list_projects() -> dict[str, Any]:
    rows = db.all("select * from projects order by updated_at desc")
    return {"projects": [dict(r) for r in rows]}


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
    if (SCREEN_SCRIPT_ROOT / "assets").is_dir():
        roots.append(SCREEN_SCRIPT_ROOT)
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
