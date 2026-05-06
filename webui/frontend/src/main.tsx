import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Boxes,
  CheckCircle2,
  Circle,
  Clock3,
  FileVideo,
  GitFork,
  Image,
  ListChecks,
  Loader2,
  Play,
  RefreshCw,
  Sparkles,
  Square,
  Upload,
  Wand2,
  XCircle
} from "lucide-react";
import "./styles.css";

const API = "/api";
const STEPS = [
  "novel2video_plan",
  "character_image_gen",
  "generate_cover_pages",
  "run_novel_video_director",
  "run_seedance_test",
  "assemble_episode",
  "qa_episode_sync"
];

type Project = {
  id: number;
  name: string;
  slug: string;
  novel_path: string;
  project_dir: string;
  plan_bundle_path: string;
};

type Episode = { id: number; episode_id: string; title: string; status: string };
type Shot = { id: number; episode_id: string; shot_id: string; status: string; record_path: string };
type Job = {
  id: number;
  step: string;
  scope: string;
  episode_id: string;
  shots: string;
  status: string;
  command_json: string;
  log_path: string;
  output_manifest: string;
  dry_run: number;
  created_at: string;
  started_at?: string;
  ended_at?: string;
  log_tail?: string;
};
type Asset = {
  id: number;
  asset_type: string;
  episode_id: string;
  shot_id: string;
  label: string;
  canonical_path: string;
  prompt_path: string;
  status: string;
  stale: number;
};
type ReviewRun = {
  id: number;
  status: string;
  prompt_override: string;
  base_prompt_path: string;
  final_prompt_path: string;
  output_path: string;
  run_dir: string;
  created_at: string;
};
type Dashboard = {
  project: Project;
  episodes: Episode[];
  shots: Shot[];
  assets: Asset[];
  jobs: Job[];
  pipeline: { step: string; status: string; job?: Job }[];
};
type AssetRoot = { label: string; root_path: string; asset_dir: string };
type BrowserAsset = {
  asset_type: "character" | "prop" | "scene";
  label: string;
  image_path: string;
  prompt_path: string;
  prompt_exists: boolean;
  batch: string;
  source_dir: string;
};
type BrowserAssetResponse = {
  root: AssetRoot;
  assets: BrowserAsset[];
  counts: { all: number; character: number; prop: number; scene: number };
  batches: string[];
};
type BrowserPrompt = {
  image_path: string;
  prompt_path: string;
  prompt: string;
  prompt_exists: boolean;
};
type MediaCandidate = {
  candidate_id?: number;
  asset_id: number;
  asset_type: string;
  media_type?: "keyframe" | "clip";
  label: string;
  path: string;
  prompt_path: string;
  payload_path: string;
  manifest_path?: string;
  run_name: string;
  mtime: string;
  status: string;
  stale: number;
  source_kind?: string;
  selected_source?: string;
  metadata?: Record<string, unknown>;
  source_keyframe_path?: string;
};
type ShotBoardRow = {
  shot_id: string;
  episode_id: string;
  record_path: string;
  record_status: string;
  summary: string;
  source_excerpt: string;
  location: string;
  characters: string[];
  props: string[];
  keyframes: MediaCandidate[];
  video_clips: MediaCandidate[];
  keyframe_candidates?: MediaCandidate[];
  clip_candidates?: MediaCandidate[];
  latest_keyframe?: MediaCandidate | null;
  clip_for_latest_keyframe?: MediaCandidate | null;
  linked_clip_for_latest_keyframe?: MediaCandidate | null;
  matching_clip_candidates?: MediaCandidate[];
  selected_clip_for_keyframe?: {
    keyframe_path: string;
    clip_path: string;
    selected_at: string;
    clip: MediaCandidate;
  } | null;
  default_keyframe?: MediaCandidate | null;
  default_video?: MediaCandidate | null;
  selected_keyframe?: MediaCandidate | null;
  selected_clip?: MediaCandidate | null;
  linked_assets: { asset_type: string; label: string; path: string }[];
  qa: string[];
};
type ShotBoard = {
  project: Project;
  episode_id: string;
  counts: {
    shots: number;
    keyframes: number;
    clips: number;
    missing_keyframes: number;
    missing_clips: number;
    stale: number;
  };
  shots: ShotBoardRow[];
  runs: Job[];
};
type AssemblyMissing = {
  shot_id: string;
  reason: "missing_keyframe" | "missing_clip" | "clip_file_missing" | "unknown_shot" | string;
  label: string;
  keyframe_path?: string;
  clip_path?: string;
};
type AssemblyResolved = {
  shot_id: string;
  keyframe_path: string;
  clip_path: string;
  clip_run_name: string;
  clip_selected_source: string;
};
type AssemblyCheck = {
  episode_id: string;
  mode: string;
  requested_shots: string[];
  ordered_shots: string[];
  resolved: AssemblyResolved[];
  missing: AssemblyMissing[];
  ready: boolean;
};
type RedoPromptDraft = {
  source_prompt: string;
  adjusted_prompt: string;
  warnings: string[];
  applied_changes: string[];
  draft_metadata: {
    model: string;
    source_prompt_path: string;
    source_clip_candidate_id: number;
    source_clip_path: string;
    source_keyframe_path: string;
    policy: string;
    created_at: string;
  };
};
type ViewMode = "projects" | "episodes" | "assets" | "runs";
type InspectorTab = "record" | "keyframe" | "seedance" | "payload" | "qa";

function clipMatchesKeyframe(clip?: MediaCandidate | null, keyframe?: MediaCandidate | null): boolean {
  if (!clip?.path || !keyframe?.path) return false;
  return Boolean(clip.source_keyframe_path && clip.source_keyframe_path === keyframe.path);
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

function fileUrl(path: string) {
  return `${API}/file?path=${encodeURIComponent(path)}`;
}

async function fileText(path: string) {
  if (!path) return "";
  const response = await fetch(fileUrl(path));
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.text();
}

function statusIcon(status: string) {
  if (status === "completed" || status === "ready") return <CheckCircle2 size={18} />;
  if (status === "running" || status === "queued") return <Loader2 size={18} className="spin" />;
  if (status === "failed") return <XCircle size={18} />;
  if (status === "canceled") return <Square size={18} />;
  return <Circle size={18} />;
}

function statusClass(status: string) {
  if (status === "completed") return "completed";
  if (status === "ready") return "ready";
  if (status === "running" || status === "queued") return "running";
  if (status === "failed") return "failed";
  if (status === "stale") return "stale";
  return "idle";
}

function basename(path: string) {
  return path.split("/").filter(Boolean).pop() || path;
}

function isImage(asset?: Asset) {
  if (!asset) return false;
  return /\.(png|jpe?g|webp)$/i.test(asset.canonical_path);
}

function isVideo(asset?: Asset) {
  if (!asset) return false;
  return /\.mp4$/i.test(asset.canonical_path);
}

function mediaStatus(candidate?: MediaCandidate | null) {
  if (!candidate) return "missing";
  return candidate.stale ? "stale" : candidate.status || "ready";
}

function statusLabel(status: string) {
  return status === "missing" ? "missing" : status;
}

function isActiveJobStatus(status?: string) {
  return status === "queued" || status === "running";
}

function terminalJobStatus(status?: string) {
  return status === "completed" || status === "failed" || status === "canceled";
}

function assetTypeLabel(type: BrowserAsset["asset_type"] | "all") {
  if (type === "all") return "All";
  if (type === "character") return "Characters";
  if (type === "prop") return "Props";
  return "Scenes";
}

function Sidebar({
  projects,
  selectedProjectId,
  activeView,
  onSelect,
  onView
}: {
  projects: Project[];
  selectedProjectId?: number;
  activeView: ViewMode;
  onSelect: (id: number) => void;
  onView: (view: ViewMode) => void;
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brandMark"><Play size={18} /></div>
        <div>
          <strong>Novel2Video Studio</strong>
          <span>localhost control room</span>
        </div>
      </div>
      <nav>
        <button className={`navItem ${activeView === "projects" ? "active" : ""}`} onClick={() => onView("projects")}><Boxes size={18} /> Projects</button>
        <button className={`navItem ${activeView === "episodes" ? "active" : ""}`} onClick={() => onView("episodes")}><ListChecks size={18} /> Episodes</button>
        <button className={`navItem ${activeView === "assets" ? "active" : ""}`} onClick={() => onView("assets")}><Image size={18} /> Assets</button>
        <button className={`navItem ${activeView === "runs" ? "active" : ""}`} onClick={() => onView("runs")}><Clock3 size={18} /> Jobs / Runs</button>
      </nav>
      <div className="projectList">
        <div className="miniTitle">Projects</div>
        {projects.map((project) => (
          <button
            key={project.id}
            className={`projectPill ${selectedProjectId === project.id ? "selected" : ""}`}
            onClick={() => {
              onSelect(project.id);
              onView("projects");
            }}
          >
            {project.name}
            <span>{project.slug}</span>
          </button>
        ))}
      </div>
      <div className="userCard">
        <div className="avatar">A</div>
        <div>
          <strong>Admin</strong>
          <span>single-user local</span>
        </div>
      </div>
    </aside>
  );
}

function ProjectCreator({ onCreated }: { onCreated: (project: Project) => void }) {
  const [name, setName] = useState("");
  const [novelPath, setNovelPath] = useState("novel/ginza_night/ginza_night.md");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function importExisting() {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("novel_path", novelPath);
      form.append("name", name || "GinzaNight");
      const data = await api<{ project: Project }>("/projects/import", { method: "POST", body: form });
      onCreated(data.project);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File | null) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("name", name || file.name.replace(/\.md$/i, ""));
      const data = await api<{ project: Project }>("/projects", { method: "POST", body: form });
      onCreated(data.project);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel projectCreator">
      <h2>Start Project</h2>
      <p>Upload a novel markdown file, or import an existing one from this repo.</p>
      <label>
        Project name
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="GinzaNight" />
      </label>
      <label className="uploadBox">
        <Upload size={22} />
        Upload novel .md
        <input hidden type="file" accept=".md,text/markdown" onChange={(e) => upload(e.target.files?.[0] || null)} />
      </label>
      <div className="importRow">
        <input value={novelPath} onChange={(e) => setNovelPath(e.target.value)} />
        <button onClick={importExisting} disabled={busy}>{busy ? "Working..." : "Import"}</button>
      </div>
      {error && <div className="errorText">{error}</div>}
    </section>
  );
}

function PipelineDashboard({
  dashboard,
  episodeId,
  scope,
  selectedShot,
  dryRun,
  prepareOnly,
  onEpisode,
  onScope,
  onShot,
  onDryRun,
  onPrepareOnly,
  onRun,
  onSelectJob
}: {
  dashboard: Dashboard;
  episodeId: string;
  scope: string;
  selectedShot: string;
  dryRun: boolean;
  prepareOnly: boolean;
  onEpisode: (value: string) => void;
  onScope: (value: string) => void;
  onShot: (value: string) => void;
  onDryRun: (value: boolean) => void;
  onPrepareOnly: (value: boolean) => void;
  onRun: (step: string) => void;
  onSelectJob: (job: Job) => void;
}) {
  const counts = useMemo(() => {
    const result = { running: 0, completed: 0, ready: 0, failed: 0, stale: 0 };
    for (const asset of dashboard.assets) {
      if (asset.stale) result.stale += 1;
      else if (asset.status === "ready") result.ready += 1;
    }
    for (const job of dashboard.jobs) {
      if (job.status === "running" || job.status === "queued") result.running += 1;
      if (job.status === "completed") result.completed += 1;
      if (job.status === "failed") result.failed += 1;
    }
    return result;
  }, [dashboard]);

  return (
    <section className="panel dashboardPanel">
      <div className="panelHeader">
        <div>
          <span className="eyebrow">Project Dashboard</span>
          <h1>{dashboard.project.name}</h1>
          <p>Plan: {basename(dashboard.project.plan_bundle_path || "not generated")}</p>
        </div>
        <div className="toolbar">
          <select value={episodeId} onChange={(e) => onEpisode(e.target.value)}>
            {(dashboard.episodes.length ? dashboard.episodes : [{ episode_id: "EP01" } as Episode]).map((ep) => (
              <option key={ep.episode_id}>{ep.episode_id}</option>
            ))}
          </select>
          <select value={scope} onChange={(e) => onScope(e.target.value)}>
            <option value="project">Project</option>
            <option value="episode">Episode</option>
            <option value="shot">Shot</option>
          </select>
          <select value={selectedShot} onChange={(e) => onShot(e.target.value)} disabled={scope !== "shot"}>
            <option value="">All Shots</option>
            {dashboard.shots.map((shot) => <option key={shot.shot_id}>{shot.shot_id}</option>)}
          </select>
        </div>
      </div>
      <div className="toggleRow">
        <label><input type="checkbox" checked={dryRun} onChange={(e) => onDryRun(e.target.checked)} /> Dry run</label>
        <label><input type="checkbox" checked={prepareOnly} onChange={(e) => onPrepareOnly(e.target.checked)} /> Prepare only</label>
      </div>
      <div className="stepGrid">
        {dashboard.pipeline.map((node) => (
          <button key={node.step} className={`stepCard ${statusClass(node.status)}`} onClick={() => onRun(node.step)}>
            <span>{statusIcon(node.status)} {node.step}</span>
            <strong>{node.status}</strong>
          </button>
        ))}
      </div>
      <div className="lowerGrid">
        <div className="tableBox">
          <h3>Episodes</h3>
          <table>
            <tbody>
              {dashboard.episodes.map((ep) => (
                <tr key={ep.episode_id}>
                  <td>{ep.episode_id}</td>
                  <td>{ep.title || ep.episode_id}</td>
                  <td><span className={`badge ${statusClass(ep.status)}`}>{ep.status}</span></td>
                </tr>
              ))}
              {!dashboard.episodes.length && <tr><td>No episodes indexed yet</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="summaryBox">
          <h3>Status Summary</h3>
          <div className="summaryGrid">
            <span>Running</span><b>{counts.running}</b>
            <span>Completed</span><b>{counts.completed}</b>
            <span>Ready assets</span><b>{counts.ready}</b>
            <span>Stale assets</span><b>{counts.stale}</b>
            <span>Failed</span><b>{counts.failed}</b>
          </div>
        </div>
      </div>
      <div className="jobStrip">
        {dashboard.jobs.slice(0, 6).map((job) => (
          <button key={job.id} onClick={() => onSelectJob(job)}>
            #{job.id} {job.step} <span className={statusClass(job.status)}>{job.status}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function PipelineDag({ dashboard, onRun }: { dashboard?: Dashboard; onRun: (step: string) => void }) {
  const nodes = dashboard?.pipeline || STEPS.map((step) => ({ step, status: "not_started" }));
  return (
    <section className="panel dagPanel">
      <div className="panelHeader compact">
        <h2>Pipeline DAG</h2>
        <span>{dashboard ? dashboard.project.slug : "no project"}</span>
      </div>
      <div className="dagCanvas">
        {nodes.map((node, index) => (
          <React.Fragment key={node.step}>
            <button className={`dagNode ${statusClass(node.status)}`} onClick={() => onRun(node.step)}>
              <span>{node.step}</span>
              <strong>{node.status}</strong>
            </button>
            {index < nodes.length - 1 && <div className="dagEdge" />}
          </React.Fragment>
        ))}
      </div>
      <div className="legend">
        <span className="completed">Completed</span>
        <span className="running">Running</span>
        <span className="ready">Ready</span>
        <span className="failed">Failed</span>
        <span className="idle">Not Started</span>
      </div>
    </section>
  );
}

function AssetReview({
  dashboard,
  selectedAsset,
  onSelectAsset,
  onRefresh
}: {
  dashboard?: Dashboard;
  selectedAsset?: Asset;
  onSelectAsset: (asset: Asset) => void;
  onRefresh: () => void;
}) {
  const [assetDetail, setAssetDetail] = useState<{ asset: Asset; base_prompt: string; review_runs: ReviewRun[] } | null>(null);
  const [override, setOverride] = useState("");
  const [busy, setBusy] = useState(false);
  const assets = dashboard?.assets || [];

  useEffect(() => {
    if (!selectedAsset) {
      setAssetDetail(null);
      return;
    }
    api<{ asset: Asset; base_prompt: string; review_runs: ReviewRun[] }>(`/assets/${selectedAsset.id}`)
      .then((data) => {
        setAssetDetail(data);
        setOverride("");
      })
      .catch(() => setAssetDetail(null));
  }, [selectedAsset?.id]);

  async function createReview() {
    if (!selectedAsset) return;
    setBusy(true);
    try {
      const data = await api<{ review_run: ReviewRun }>(`/assets/${selectedAsset.id}/review-runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt_override: override })
      });
      setAssetDetail((prev) => prev ? { ...prev, review_runs: [data.review_run, ...prev.review_runs] } : prev);
    } finally {
      setBusy(false);
    }
  }

  async function accept(review: ReviewRun) {
    await api(`/review-runs/${review.id}/accept`, { method: "POST" });
    onRefresh();
  }

  async function reject(review: ReviewRun) {
    await api(`/review-runs/${review.id}/reject`, { method: "POST" });
    onRefresh();
  }

  const latest = assetDetail?.review_runs[0];

  return (
    <section className="panel assetPanel">
      <div className="panelHeader compact">
        <h2>Asset Review</h2>
        <button onClick={onRefresh}><RefreshCw size={16} /></button>
      </div>
      <select value={selectedAsset?.id || ""} onChange={(e) => {
        const found = assets.find((asset) => asset.id === Number(e.target.value));
        if (found) onSelectAsset(found);
      }}>
        <option value="">Select asset</option>
        {assets.map((asset) => (
          <option key={asset.id} value={asset.id}>
            {asset.asset_type} / {asset.episode_id || "-"} / {asset.shot_id || "-"} / {asset.label}
          </option>
        ))}
      </select>
      {selectedAsset ? (
        <>
          <div className="assetCompare">
            <div>
              <h3>Canonical {selectedAsset.stale ? <span className="badge stale">stale</span> : null}</h3>
              <Preview asset={selectedAsset} path={selectedAsset.canonical_path} />
              <small>{basename(selectedAsset.canonical_path)}</small>
            </div>
            <div>
              <h3>Review Run</h3>
              {latest ? <Preview asset={selectedAsset} path={latest.output_path} /> : <div className="emptyPreview">No review run</div>}
              <small>{latest ? basename(latest.output_path) : "Create one below"}</small>
            </div>
          </div>
          <div className="promptTabs">
            <h3>Base Prompt</h3>
            <pre>{assetDetail?.base_prompt || "No prompt found"}</pre>
            <h3>Override Prompt</h3>
            <textarea value={override} onChange={(e) => setOverride(e.target.value)} placeholder="Add user override without changing record JSON..." />
            <button onClick={createReview} disabled={busy}>{busy ? "Preparing..." : "Create Review Run"}</button>
            {latest && (
              <div className="reviewActions">
                <button className="ghost" onClick={() => reject(latest)}>Reject</button>
                <button className="accept" onClick={() => accept(latest)}>Accept & Replace</button>
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="emptyState">Select an image or video asset to review.</div>
      )}
    </section>
  );
}

function ShotControlRoom({
  dashboard,
  shotBoard,
  shotBoardLoading,
  activeView,
  episodeId,
  selectedShotId,
  selectedShotIds,
  onEpisode,
  onSelectShot,
  onSelectedShotIds,
  onRefresh,
  onRun,
  onSelectJob
}: {
  dashboard: Dashboard;
  shotBoard?: ShotBoard;
  shotBoardLoading: boolean;
  activeView: ViewMode;
  episodeId: string;
  selectedShotId: string;
  selectedShotIds: string[];
  onEpisode: (value: string) => void;
  onSelectShot: (value: string) => void;
  onSelectedShotIds: (value: string[]) => void;
  onRefresh: (refreshIndex?: boolean) => void | Promise<void>;
  onRun: (step: string) => void;
  onSelectJob: (job: Job) => void;
}) {
  const selectedShot = shotBoard?.shots.find((shot) => shot.shot_id === selectedShotId) || shotBoard?.shots[0];
  const [assemblyBusy, setAssemblyBusy] = useState(false);
  const [assemblyError, setAssemblyError] = useState("");
  const [assemblyCheck, setAssemblyCheck] = useState<AssemblyCheck | null>(null);

  function updateSelectedShot(shotId: string, checked: boolean) {
    const next = checked
      ? Array.from(new Set([...selectedShotIds, shotId]))
      : selectedShotIds.filter((item) => item !== shotId);
    onSelectedShotIds(next);
    if (assemblyCheck) setAssemblyCheck(null);
  }

  function selectAllShots() {
    if (!shotBoard?.shots.length) return;
    onSelectedShotIds(shotBoard.shots.map((shot) => shot.shot_id));
    if (assemblyCheck) setAssemblyCheck(null);
  }

  async function checkAssembly(): Promise<AssemblyCheck | null> {
    if (!selectedShotIds.length) return null;
    const data = await api<AssemblyCheck>(`/projects/${dashboard.project.id}/assembly-check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ episode_id: episodeId, shots: selectedShotIds })
    });
    setAssemblyCheck(data.missing.length ? data : null);
    return data;
  }

  async function assembleSelectedShots() {
    if (!selectedShotIds.length || assemblyBusy) return;
    setAssemblyBusy(true);
    setAssemblyError("");
    try {
      const check = await checkAssembly();
      if (!check || check.missing.length) return;
      const data = await api<{ job: Job }>("/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: dashboard.project.id,
          step: "assemble_episode",
          scope: "episode",
          episode_id: episodeId,
          shots: selectedShotIds,
          dry_run: false,
          prepare_only: false,
          params: { selected_mode: true }
        })
      });
      onSelectJob(data.job);
      await onRefresh();
    } catch (err) {
      setAssemblyError(String(err));
    } finally {
      setAssemblyBusy(false);
    }
  }

  async function completeMissingAssemblyMedia(check: AssemblyCheck) {
    const missingKeyframes = check.missing.filter((item) => item.reason === "missing_keyframe").map((item) => item.shot_id);
    const missingClips = check.missing.filter((item) => item.reason === "missing_clip" || item.reason === "clip_file_missing");
    setAssemblyBusy(true);
    setAssemblyError("");
    try {
      if (missingKeyframes.length) {
        const data = await api<{ job: Job }>("/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: dashboard.project.id,
            step: "run_novel_video_director",
            scope: "shot",
            episode_id: episodeId,
            shots: missingKeyframes,
            dry_run: false,
            prepare_only: false,
            params: { intent: "complete_missing_keyframes_for_assembly" }
          })
        });
        onSelectJob(data.job);
      } else if (missingClips.length) {
        const keyframePaths = Object.fromEntries(
          missingClips
            .filter((item) => item.keyframe_path)
            .map((item) => [item.shot_id, item.keyframe_path as string])
        );
        const shots = missingClips.map((item) => item.shot_id);
        const data = await api<{ job: Job }>("/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: dashboard.project.id,
            step: "run_seedance_test",
            scope: "shot",
            episode_id: episodeId,
            shots,
            dry_run: false,
            prepare_only: false,
            params: {
              keyframe_paths: keyframePaths,
              intent: "complete_missing_clips_for_assembly"
            }
          })
        });
        onSelectJob(data.job);
      }
      await onRefresh();
    } catch (err) {
      setAssemblyError(String(err));
    } finally {
      setAssemblyBusy(false);
    }
  }

  useEffect(() => {
    if (!shotBoard?.shots.length) return;
    if (!selectedShotId || !shotBoard.shots.some((shot) => shot.shot_id === selectedShotId)) {
      onSelectShot(shotBoard.shots[0].shot_id);
    }
  }, [shotBoard?.episode_id, shotBoard?.shots.length, selectedShotId]);

  useEffect(() => {
    if (!shotBoard?.shots.length) {
      if (selectedShotIds.length) onSelectedShotIds([]);
      return;
    }
    const available = new Set(shotBoard.shots.map((shot) => shot.shot_id));
    const next = selectedShotIds.filter((shotId) => available.has(shotId));
    if (next.length !== selectedShotIds.length) onSelectedShotIds(next);
  }, [shotBoard?.episode_id, shotBoard?.shots.length, selectedShotIds.join("|")]);

  return (
    <section className="shotControlRoom">
      <div className="panel shotTopBar">
        <div>
          <span className="eyebrow">{activeView === "episodes" ? "Episode Browser" : activeView === "runs" ? "Runs Monitor" : "Project Home"}</span>
          <h1>{dashboard.project.name}</h1>
          <p>{dashboard.project.plan_bundle_path || dashboard.project.project_dir}</p>
        </div>
        <div className="shotTopControls">
          <select value={episodeId} onChange={(e) => onEpisode(e.target.value)}>
            {(dashboard.episodes.length ? dashboard.episodes : [{ episode_id: "EP01" } as Episode]).map((ep) => (
              <option key={ep.episode_id}>{ep.episode_id}</option>
            ))}
          </select>
          <button onClick={() => onRefresh()}><RefreshCw size={16} /></button>
        </div>
        <div className="healthGrid">
          <Metric label="Shots" value={shotBoard?.counts.shots ?? dashboard.shots.length} />
          <Metric label="Keyframes" value={shotBoard?.counts.keyframes ?? 0} />
          <Metric label="Clips" value={shotBoard?.counts.clips ?? 0} />
          <Metric label="Missing" value={(shotBoard?.counts.missing_keyframes ?? 0) + (shotBoard?.counts.missing_clips ?? 0)} tone="warn" />
          <Metric label="Stale" value={shotBoard?.counts.stale ?? 0} tone="warn" />
        </div>
      </div>

      <ShotBrowser
        shots={shotBoard?.shots || []}
        selectedShotId={selectedShot?.shot_id || ""}
        selectedShotIds={selectedShotIds}
        onSelectShot={onSelectShot}
        onToggleShot={updateSelectedShot}
        onSelectAll={selectAllShots}
        onAssemble={assembleSelectedShots}
        active={activeView === "episodes" || activeView === "projects"}
        loading={shotBoardLoading}
        episodeId={episodeId}
        assemblyBusy={assemblyBusy}
      />
      {assemblyCheck?.missing.length ? (
        <MissingAssemblyPanel
          check={assemblyCheck}
          busy={assemblyBusy}
          error={assemblyError}
          onComplete={() => completeMissingAssemblyMedia(assemblyCheck)}
          onClose={() => setAssemblyCheck(null)}
        />
      ) : (
        <ShotInspector
          projectId={dashboard.project.id}
          episodeId={shotBoard?.episode_id || episodeId}
          shot={selectedShot}
          onSelectionChanged={onRefresh}
          onJobCreated={onSelectJob}
        />
      )}
      <PipelineCompact dashboard={dashboard} shotBoard={shotBoard} onRun={onRun} onSelectJob={onSelectJob} active={activeView === "runs"} />
      {assemblyError && !assemblyCheck?.missing.length && <div className="assemblyInlineError">{assemblyError}</div>}
    </section>
  );
}

function ProjectOverview({
  dashboard,
  shotBoard,
  episodeId,
  onEpisode,
  onOpenEpisodes,
  onOpenRuns,
  onRefresh
}: {
  dashboard: Dashboard;
  shotBoard?: ShotBoard;
  episodeId: string;
  onEpisode: (value: string) => void;
  onOpenEpisodes: () => void;
  onOpenRuns: () => void;
  onRefresh: () => void | Promise<void>;
}) {
  const counts = shotBoard?.counts;
  return (
    <section className="projectOverview">
      <div className="panel overviewHero">
        <div>
          <span className="eyebrow">Project Overview</span>
          <h1>{dashboard.project.name}</h1>
          <p>{dashboard.project.plan_bundle_path || dashboard.project.project_dir}</p>
        </div>
        <div className="shotTopControls">
          <select value={episodeId} onChange={(e) => onEpisode(e.target.value)}>
            {(dashboard.episodes.length ? dashboard.episodes : [{ episode_id: "EP01" } as Episode]).map((ep) => (
              <option key={ep.episode_id}>{ep.episode_id}</option>
            ))}
          </select>
          <button onClick={onRefresh}><RefreshCw size={16} /></button>
        </div>
      </div>
      <div className="overviewCards">
        <button className="panel overviewCard" onClick={onOpenEpisodes}>
          <span className="eyebrow">Current Episode</span>
          <strong>{episodeId}</strong>
          <p>{counts?.shots ?? dashboard.shots.length} shots · {counts?.keyframes ?? 0} keyframes · {counts?.clips ?? 0} clips</p>
        </button>
        <button className="panel overviewCard" onClick={onOpenRuns}>
          <span className="eyebrow">Runs</span>
          <strong>{dashboard.jobs.filter((job) => job.status === "running" || job.status === "queued").length} active</strong>
          <p>{dashboard.jobs.length} recent jobs indexed</p>
        </button>
        <div className="panel overviewCard">
          <span className="eyebrow">Missing Media</span>
          <strong>{(counts?.missing_keyframes ?? 0) + (counts?.missing_clips ?? 0)}</strong>
          <p>{counts?.stale ?? 0} stale outputs</p>
        </div>
      </div>
      <div className="panel episodeOverviewPanel">
        <div className="panelHeader compact">
          <h2>Episodes</h2>
          <span>{dashboard.episodes.length} indexed</span>
        </div>
        <div className="episodeCards">
          {(dashboard.episodes.length ? dashboard.episodes : [{ episode_id: "EP01", status: "not_started", title: "EP01" } as Episode]).map((episode) => (
            <button
              key={episode.episode_id}
              className={`episodeCard ${episode.episode_id === episodeId ? "selected" : ""}`}
              onClick={() => {
                onEpisode(episode.episode_id);
                onOpenEpisodes();
              }}
            >
              <strong>{episode.episode_id}</strong>
              <span>{episode.title || episode.episode_id}</span>
              <em>{episode.status}</em>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value, tone = "normal" }: { label: string; value: number; tone?: "normal" | "warn" }) {
  return (
    <div className={`metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ShotBrowser({
  shots,
  selectedShotId,
  selectedShotIds,
  onSelectShot,
  onToggleShot,
  onSelectAll,
  onAssemble,
  active,
  loading,
  episodeId,
  assemblyBusy
}: {
  shots: ShotBoardRow[];
  selectedShotId: string;
  selectedShotIds: string[];
  onSelectShot: (shotId: string) => void;
  onToggleShot: (shotId: string, checked: boolean) => void;
  onSelectAll: () => void;
  onAssemble: () => void | Promise<void>;
  active: boolean;
  loading: boolean;
  episodeId: string;
  assemblyBusy: boolean;
}) {
  const selectedSet = useMemo(() => new Set(selectedShotIds), [selectedShotIds]);
  const allSelected = shots.length > 0 && selectedShotIds.length === shots.length;
  return (
    <section className={`panel shotBrowserPanel ${active ? "focusPanel" : ""}`}>
      <div className="panelHeader compact">
        <div>
          <h2>Shot Browser</h2>
          <span>{selectedShotIds.length ? `${selectedShotIds.length} selected · ` : ""}{shots.length} indexed shots</span>
        </div>
        <div className="shotBrowserActions">
          <button className="selectAllButton" onClick={onSelectAll} disabled={!shots.length || loading || allSelected}>
            <ListChecks size={15} />
            Select all
          </button>
          <button className="assembleButton" onClick={onAssemble} disabled={!selectedShotIds.length || assemblyBusy}>
            {assemblyBusy ? <Loader2 size={15} className="spin" /> : <FileVideo size={15} />}
            {assemblyBusy ? "Checking" : "Assemble"}
          </button>
        </div>
      </div>
      <div className="shotGrid">
        {shots.map((shot) => {
          const keyframe = shot.latest_keyframe || shot.default_keyframe || null;
          const clip = shot.clip_for_latest_keyframe || shot.linked_clip_for_latest_keyframe || null;
          const statusParts = [
            shot.record_status === "missing" ? "" : "R",
            keyframe ? "K" : "",
            clip ? "C" : "",
          ].filter(Boolean);
          const statusText = statusParts.join(", ") || "pending";
          return (
            <article
              key={shot.shot_id}
              className={`shotCard ${selectedShotId === shot.shot_id ? "selected" : ""} ${selectedSet.has(shot.shot_id) ? "checked" : ""}`}
              onClick={() => onSelectShot(shot.shot_id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelectShot(shot.shot_id);
                }
              }}
              role="button"
              tabIndex={0}
              title={`${shot.shot_id} · ${statusText}${shot.summary ? ` · ${shot.summary}` : ""}`}
            >
              <div className="shotCardMedia">
                <label className="shotSelectBox" title={`Select ${shot.shot_id} for assembly`} onClick={(event) => event.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selectedSet.has(shot.shot_id)}
                    onChange={(event) => onToggleShot(shot.shot_id, event.target.checked)}
                  />
                </label>
                {keyframe ? (
                  <img src={fileUrl(keyframe.path)} alt={`${shot.shot_id} keyframe`} />
                ) : (
                  <div className="shotPlaceholder">
                    <Image size={24} />
                    <span>No keyframe</span>
                  </div>
                )}
              </div>
              <div className="shotCardMeta">
                <div>
                  <strong>{shot.shot_id}</strong>
                  <small>{keyframe?.run_name || "No keyframe"}</small>
                </div>
                <span>{statusText}</span>
              </div>
            </article>
          );
        })}
        {!shots.length && (
          <div className="emptyState">
            {loading ? `Loading ${episodeId} shots...` : "No shots indexed for this episode."}
          </div>
        )}
      </div>
    </section>
  );
}

function MissingAssemblyPanel({
  check,
  busy,
  error,
  onComplete,
  onClose
}: {
  check: AssemblyCheck;
  busy: boolean;
  error: string;
  onComplete: () => void | Promise<void>;
  onClose: () => void;
}) {
  const missingKeyframes = check.missing.filter((item) => item.reason === "missing_keyframe");
  const missingClips = check.missing.filter((item) => item.reason === "missing_clip" || item.reason === "clip_file_missing");
  const otherMissing = check.missing.filter((item) => !missingKeyframes.includes(item) && !missingClips.includes(item));
  const completeLabel = missingKeyframes.length ? "Complete Keyframes" : "Complete Clips";
  return (
    <section className="panel shotInspectorPanel missingAssemblyPanel">
      <div className="panelHeader compact">
        <div>
          <span className="eyebrow">Assembly Blocked</span>
          <h2>Missing Clips</h2>
        </div>
        <button className="ghostButton" onClick={onClose}>Close</button>
      </div>
      <div className="missingSummary">
        <strong>{check.missing.length}</strong>
        <span>selected shots need media before assembly can start.</span>
      </div>
      <MissingGroup title="Missing keyframe" items={missingKeyframes} />
      <MissingGroup title="Missing clip" items={missingClips} />
      <MissingGroup title="Other blockers" items={otherMissing} />
      <div className="missingActions">
        <button onClick={onComplete} disabled={busy || !check.missing.length || !!otherMissing.length}>
          {busy ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />}
          {busy ? "Starting" : completeLabel}
        </button>
        {missingKeyframes.length > 0 && <small>Keyframes are completed first; run Complete again after refresh to create clips.</small>}
        {otherMissing.length > 0 && <small>Unknown shots must be removed from the selection before completion can continue.</small>}
      </div>
      {error && <pre className="inspectorText missingError">{error}</pre>}
    </section>
  );
}

function MissingGroup({ title, items }: { title: string; items: AssemblyMissing[] }) {
  if (!items.length) return null;
  return (
    <div className="missingGroup">
      <h3>{title}</h3>
      {items.map((item) => (
        <div key={`${item.reason}-${item.shot_id}`} className="missingItem">
          <strong>{item.shot_id}</strong>
          <span>{item.label || item.reason}</span>
          {item.clip_path && <small>{basename(item.clip_path)}</small>}
        </div>
      ))}
    </div>
  );
}

function ShotInspector({
  projectId,
  episodeId,
  shot,
  onSelectionChanged,
  onJobCreated
}: {
  projectId: number;
  episodeId: string;
  shot?: ShotBoardRow;
  onSelectionChanged: (refreshIndex?: boolean) => void | Promise<void>;
  onJobCreated: (job: Job) => void;
}) {
  const [tab, setTab] = useState<InspectorTab>("record");
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [videoBusy, setVideoBusy] = useState(false);
  const [selectionBusyPath, setSelectionBusyPath] = useState("");
  const [redoJob, setRedoJob] = useState<Job | undefined>();
  const [redoLogLine, setRedoLogLine] = useState("");
  const [adjustOpen, setAdjustOpen] = useState(false);
  const [adjustmentRequest, setAdjustmentRequest] = useState("");
  const [sourcePrompt, setSourcePrompt] = useState("");
  const [adjustedPrompt, setAdjustedPrompt] = useState("");
  const [draftWarnings, setDraftWarnings] = useState<string[]>([]);
  const [draftChanges, setDraftChanges] = useState<string[]>([]);
  const [draftBusy, setDraftBusy] = useState(false);
  const keyframe = shot?.latest_keyframe || shot?.default_keyframe || null;
  const currentClip = shot?.clip_for_latest_keyframe || shot?.linked_clip_for_latest_keyframe || null;
  const currentClipMtime = currentClip?.mtime || "";
  const redoClip = (shot?.clip_candidates || shot?.video_clips || []).find((clip) => (
    clipMatchesKeyframe(clip, keyframe) &&
    clip.path !== currentClip?.path &&
    (!currentClipMtime || (clip.mtime || "") > currentClipMtime)
  )) || null;
  const redoJobActive = isActiveJobStatus(redoJob?.status);
  const redoDisabled = videoBusy || redoJobActive || !keyframe || !currentClip?.path;

  useEffect(() => {
    setTab("record");
    setRedoJob(undefined);
    setRedoLogLine("");
    setAdjustOpen(false);
    setAdjustmentRequest("");
    setSourcePrompt("");
    setAdjustedPrompt("");
    setDraftWarnings([]);
    setDraftChanges([]);
  }, [shot?.shot_id]);

  useEffect(() => {
    if (!redoJob) return;
    let closed = false;
    const source = new EventSource(`${API}/jobs/${redoJob.id}/events`);
    source.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (closed) return;
      if (data.line) {
        const line = String(data.line);
        if (line.trim() && !line.startsWith("[CMD]")) {
          setRedoLogLine(line);
        }
        if (line.includes("[WEBUI] job") && line.includes("starting")) {
          setRedoJob((prev) => prev && prev.id === redoJob.id ? { ...prev, status: "running" } : prev);
        }
      }
      if (data.done) {
        source.close();
        setRedoJob((prev) => prev && prev.id === redoJob.id ? { ...prev, status: String(data.status || prev.status) } : prev);
        onSelectionChanged(true);
      }
    };
    source.onerror = () => {
      source.close();
    };
    return () => {
      closed = true;
      source.close();
    };
  }, [redoJob?.id]);

  useEffect(() => {
    if (!adjustOpen || !currentClip?.prompt_path) return;
    fileText(currentClip.prompt_path)
      .then((value) => setSourcePrompt(value))
      .catch(() => setSourcePrompt(""));
  }, [adjustOpen, currentClip?.prompt_path]);

  useEffect(() => {
    if (!shot) {
      setText("");
      return;
    }
    setError("");
    const qaText = [
      `Record: ${shot.record_status}`,
      `Keyframes: ${shot.keyframes.length}`,
      `Linked clip for latest keyframe: ${currentClip ? "yes" : "no"}`,
      `All shot clips indexed: ${shot.video_clips.length}`,
      shot.keyframes.length ? "" : "Missing keyframe output.",
      currentClip ? "Current keyframe has a linked Seedance clip." : "Current keyframe has no linked Seedance clip.",
      ...shot.qa
    ].filter(Boolean).join("\n");
    const path =
      tab === "record" ? shot.record_path :
      tab === "keyframe" ? keyframe?.prompt_path || keyframe?.payload_path || "" :
      tab === "seedance" ? currentClip?.prompt_path || "" :
      tab === "payload" ? currentClip?.payload_path || keyframe?.payload_path || "" :
      "";
    if (tab === "qa") {
      setText(qaText);
      return;
    }
    if (!path) {
      setText("No file available for this tab.");
      return;
    }
    fileText(path)
      .then((value) => {
        try {
          setText(JSON.stringify(JSON.parse(value), null, 2));
        } catch {
          setText(value);
        }
      })
      .catch((err) => {
        setText("");
        setError(String(err));
      });
  }, [shot?.shot_id, tab, keyframe?.path, keyframe?.prompt_path, keyframe?.payload_path, currentClip?.path, currentClip?.prompt_path, currentClip?.payload_path]);

  async function selectClip(clip: MediaCandidate) {
    if (!shot || !clip.path) return;
    return api(`/projects/${projectId}/artifact-selection`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        episode_id: episodeId,
        shot_id: shot.shot_id,
        media_type: "clip",
        candidate_id: clip.candidate_id,
        candidate_path: clip.path
      })
    });
  }

  async function keepClip(clip: MediaCandidate) {
    setError("");
    setSelectionBusyPath(clip.path);
    try {
      await selectClip(clip);
      await onSelectionChanged(false);
    } catch (err) {
      setError(String(err));
    } finally {
      setSelectionBusyPath("");
    }
  }

  async function createVideoFromKeyframe() {
    if (!shot || !keyframe) return;
    setError("");
    setVideoBusy(true);
    try {
      const data = await api<{ job: Job }>("/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          step: "run_seedance_test",
          scope: "shot",
          episode_id: episodeId,
          shots: [shot.shot_id],
          dry_run: false,
          prepare_only: false,
          params: {
            keyframe_path: keyframe.path,
            intent: "create_clip_from_keyframe"
          }
        })
      });
      onJobCreated(data.job);
      onSelectionChanged(false);
    } catch (err) {
      setError(String(err));
    } finally {
      setVideoBusy(false);
    }
  }

  async function createVideoWithSeedance2() {
    if (!shot) return;
    setError("");
    setVideoBusy(true);
    try {
      const data = await api<{ job: Job }>("/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          step: "run_seedance_test",
          scope: "shot",
          episode_id: episodeId,
          shots: [shot.shot_id],
          dry_run: false,
          prepare_only: false,
          params: {
            generation_mode: "seedance2_reference",
            video_model: "ark-seedance2.0",
            model_profile_id: "seedance2_ark",
            intent: "create_clip_from_references"
          }
        })
      });
      onJobCreated(data.job);
      onSelectionChanged(false);
    } catch (err) {
      setError(String(err));
    } finally {
      setVideoBusy(false);
    }
  }

  async function redoCurrentClip() {
    if (!shot || !keyframe || !currentClip?.path) return;
    setError("");
    setVideoBusy(true);
    try {
      if (currentClip.selected_source !== "user") {
        await selectClip(currentClip);
        onSelectionChanged(false);
      }
      const data = await api<{ job: Job }>("/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          step: "run_seedance_test",
          scope: "shot",
          episode_id: episodeId,
          shots: [shot.shot_id],
          dry_run: false,
          prepare_only: false,
          params: {
            keyframe_path: keyframe.path,
            source_clip_candidate_id: currentClip.candidate_id,
            source_clip_path: currentClip.path,
            intent: "redo_clip"
          }
        })
      });
      setRedoJob(data.job);
      setRedoLogLine("Redo clip job queued.");
      onJobCreated(data.job);
      onSelectionChanged(false);
    } catch (err) {
      setError(String(err));
    } finally {
      setVideoBusy(false);
    }
  }

  async function generateAdjustedPrompt() {
    if (!shot || !keyframe || !currentClip?.path) return;
    setError("");
    setDraftBusy(true);
    try {
      const data = await api<RedoPromptDraft>(`/projects/${projectId}/redo-prompt-draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          episode_id: episodeId,
          shot_id: shot.shot_id,
          keyframe_path: keyframe.path,
          source_clip_candidate_id: currentClip.candidate_id,
          source_clip_path: currentClip.path,
          adjustment_request: adjustmentRequest
        })
      });
      setSourcePrompt(data.source_prompt);
      setAdjustedPrompt(data.adjusted_prompt);
      setDraftWarnings(data.warnings || []);
      setDraftChanges(data.applied_changes || []);
    } catch (err) {
      setError(String(err));
    } finally {
      setDraftBusy(false);
    }
  }

  async function runAdjustedRedo() {
    if (!shot || !keyframe || !currentClip?.path || !adjustedPrompt.trim()) return;
    setError("");
    setVideoBusy(true);
    try {
      if (currentClip.selected_source !== "user") {
        await selectClip(currentClip);
        onSelectionChanged(false);
      }
      const data = await api<{ job: Job }>("/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          step: "run_seedance_test",
          scope: "shot",
          episode_id: episodeId,
          shots: [shot.shot_id],
          dry_run: false,
          prepare_only: false,
          params: {
            keyframe_path: keyframe.path,
            source_clip_candidate_id: currentClip.candidate_id,
            source_clip_path: currentClip.path,
            prompt_final_text: adjustedPrompt,
            adjustment_request: adjustmentRequest,
            intent: "redo_clip_with_adjustment"
          }
        })
      });
      setRedoJob(data.job);
      setRedoLogLine("Adjusted redo job queued.");
      setAdjustOpen(false);
      onJobCreated(data.job);
      onSelectionChanged(false);
    } catch (err) {
      setError(String(err));
    } finally {
      setVideoBusy(false);
    }
  }

  if (!shot) {
    return (
      <section className="panel shotInspectorPanel">
        <div className="emptyState">Select a shot to inspect outputs.</div>
      </section>
    );
  }

  return (
    <section className="panel shotInspectorPanel">
      <div className="panelHeader compact">
        <div>
          <span className="eyebrow">Selected Shot</span>
          <h2>{shot.shot_id}</h2>
        </div>
        <span>{shot.location || "No location"}</span>
      </div>
      <div className={`inspectorMedia ${redoClip ? "" : "clipOnly"}`}>
        <div className="videoPreview">
          {currentClip ? (
            <>
              <div className="videoPaneHeader">
                <span>Current</span>
              </div>
              <video src={fileUrl(currentClip.path)} controls />
              <div className="clipActionStack">
                <button className="redoClipButton" onClick={redoCurrentClip} disabled={redoDisabled}>
                  {redoJobActive || videoBusy ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
                  {redoJobActive || videoBusy ? "Redo Running" : "Redo Clip"}
                </button>
                <button className="adjustRedoButton" onClick={() => setAdjustOpen(true)} disabled={redoDisabled}>
                  <Wand2 size={16} />
                  Adjust & Redo
                </button>
                <button className="keepClipButton" onClick={() => keepClip(currentClip)} disabled={currentClip.selected_source === "user" || selectionBusyPath === currentClip.path}>
                  {selectionBusyPath === currentClip.path ? "Selecting..." : "Keep Current"}
                </button>
                <button className="seedance2Button" onClick={createVideoWithSeedance2} disabled={videoBusy}>
                  {videoBusy ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
                  Seedance 2.0
                </button>
              </div>
            </>
          ) : (
            <div className="emptyPreview videoEmpty">
              <span>No clip</span>
              <button onClick={createVideoFromKeyframe} disabled={!keyframe || videoBusy}>
                {videoBusy ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
                {videoBusy ? "Creating..." : "Create video"}
              </button>
              <button className="seedance2Button" onClick={createVideoWithSeedance2} disabled={videoBusy}>
                {videoBusy ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />}
                Seedance 2.0
              </button>
            </div>
          )}
        </div>
        {redoClip && (
          <div className="videoPreview">
            <div className="videoPaneHeader">
              <span>New Redo</span>
            </div>
            <video src={fileUrl(redoClip.path)} controls />
            <button className="useRedoButton" onClick={() => keepClip(redoClip)} disabled={redoClip.selected_source === "user" || selectionBusyPath === redoClip.path}>
              {selectionBusyPath === redoClip.path ? "Selecting..." : "Use New Redo"}
            </button>
          </div>
        )}
      </div>
      {adjustOpen && currentClip && keyframe && (
        <div className="adjustRedoPanel">
          <div className="adjustRedoHeader">
            <div>
              <span className="eyebrow">Adjust & Redo</span>
              <strong>{shot.shot_id}</strong>
            </div>
            <button onClick={() => setAdjustOpen(false)}>Cancel</button>
          </div>
          <div className="adjustRedoGrid">
            <div className="adjustPreviewStack">
              <div>
                <span>Current clip</span>
                <video src={fileUrl(currentClip.path)} controls />
              </div>
              <div>
                <span>Keyframe</span>
                <img src={fileUrl(keyframe.path)} alt={`${shot.shot_id} keyframe`} />
              </div>
            </div>
            <div className="adjustPromptStack">
              <label>
                <span>Adjustment Request</span>
                <textarea
                  value={adjustmentRequest}
                  onChange={(event) => setAdjustmentRequest(event.target.value)}
                  placeholder="动作更慢，领带必须全程可见，不要突然切镜头"
                />
              </label>
              <div className="adjustButtonRow">
                <button onClick={generateAdjustedPrompt} disabled={draftBusy || !adjustmentRequest.trim()}>
                  {draftBusy ? <Loader2 size={16} className="spin" /> : <Wand2 size={16} />}
                  {draftBusy ? "Generating..." : "Generate"}
                </button>
                <button onClick={runAdjustedRedo} disabled={videoBusy || redoJobActive || !adjustedPrompt.trim()}>
                  {videoBusy || redoJobActive ? <Loader2 size={16} className="spin" /> : <Play size={16} />}
                  Run
                </button>
              </div>
              {(draftWarnings.length > 0 || draftChanges.length > 0) && (
                <div className="adjustNotes">
                  {draftWarnings.map((warning) => <span className="failed" key={`warning-${warning}`}>{warning}</span>)}
                  {draftChanges.map((change) => <span className="ready" key={`change-${change}`}>{change}</span>)}
                </div>
              )}
              <label>
                <span>Generated Prompt</span>
                <textarea
                  className="adjustPromptText"
                  value={adjustedPrompt}
                  onChange={(event) => setAdjustedPrompt(event.target.value)}
                  placeholder="Generate a revised prompt, then edit it before running."
                />
              </label>
              <details>
                <summary>Source prompt.final.txt</summary>
                <pre>{sourcePrompt || "Generate first to load the source prompt."}</pre>
              </details>
            </div>
          </div>
        </div>
      )}
      {redoJob && (
        <div className={`redoJobStatus ${statusClass(redoJob.status)}`}>
          <div>
            <span>{statusIcon(redoJob.status)} Redo job #{redoJob.id}</span>
            <strong>{redoJob.status}</strong>
          </div>
          <p>{redoLogLine || (terminalJobStatus(redoJob.status) ? "Redo job finished." : "Waiting for log output...")}</p>
          <button onClick={() => onJobCreated(redoJob)}>Open Console</button>
        </div>
      )}
      <div className="assetChips">
        {shot.characters.map((name) => <span key={`char-${name}`}>Character: {name}</span>)}
        {shot.props.map((name) => <span key={`prop-${name}`}>Prop: {name}</span>)}
        {shot.location && <span>Scene: {shot.location}</span>}
      </div>
      <div className="tabs inspectorTabs">
        {(["record", "keyframe", "seedance", "payload", "qa"] as InspectorTab[]).map((item) => (
          <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item}</button>
        ))}
      </div>
      <pre className="inspectorText">{error || text}</pre>
      <div className="candidateMeta">
        <span>Latest keyframe: {keyframe?.run_name || "none"}{keyframe?.mtime ? ` · ${keyframe.mtime}` : ""}</span>
        <span>Clip for latest keyframe: {currentClip?.run_name || "none"}{currentClip?.mtime ? ` · ${currentClip.mtime}` : ""}</span>
      </div>
    </section>
  );
}

function PipelineCompact({
  dashboard,
  shotBoard,
  onRun,
  onSelectJob,
  active
}: {
  dashboard: Dashboard;
  shotBoard?: ShotBoard;
  onRun: (step: string) => void;
  onSelectJob: (job: Job) => void;
  active: boolean;
}) {
  return (
    <section className={`panel runStripPanel ${active ? "focusPanel" : ""}`}>
      <div className="runTimeline">
        {dashboard.pipeline.map((node) => (
          <button key={node.step} className={`runNode ${statusClass(node.status)}`} onClick={() => onRun(node.step)}>
            {statusIcon(node.status)}
            <span>{node.step}</span>
          </button>
        ))}
      </div>
      <div className="recentRuns">
        {(shotBoard?.runs.length ? shotBoard.runs : dashboard.jobs.slice(0, 8)).map((job) => (
          <button key={job.id} onClick={() => onSelectJob(job)}>
            #{job.id} {job.step} <span className={statusClass(job.status)}>{job.status}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function AssetBrowser() {
  const [roots, setRoots] = useState<AssetRoot[]>([]);
  const [selectedRoot, setSelectedRoot] = useState("");
  const [browserData, setBrowserData] = useState<BrowserAssetResponse | null>(null);
  const [typeFilter, setTypeFilter] = useState<BrowserAsset["asset_type"] | "all">("all");
  const [batchFilter, setBatchFilter] = useState("all");
  const [selectedAsset, setSelectedAsset] = useState<BrowserAsset | null>(null);
  const [promptDetail, setPromptDetail] = useState<BrowserPrompt | null>(null);
  const [promptText, setPromptText] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    api<{ roots: AssetRoot[] }>("/asset-roots")
      .then((data) => {
        setRoots(data.roots);
        if (!selectedRoot && data.roots[0]) setSelectedRoot(data.roots[0].root_path);
      })
      .catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    if (!selectedRoot) return;
    setBusy(true);
    setError("");
    api<BrowserAssetResponse>(`/asset-browser?root_path=${encodeURIComponent(selectedRoot)}`)
      .then((data) => {
        setBrowserData(data);
        setBatchFilter("all");
        setTypeFilter("all");
        setSelectedAsset(data.assets[0] || null);
      })
      .catch((err) => {
        setBrowserData(null);
        setSelectedAsset(null);
        setError(String(err));
      })
      .finally(() => setBusy(false));
  }, [selectedRoot, refreshToken]);

  useEffect(() => {
    if (!selectedAsset) {
      setPromptDetail(null);
      setPromptText("");
      return;
    }
    setStatus("");
    setError("");
    api<BrowserPrompt>(`/asset-browser/prompt?image_path=${encodeURIComponent(selectedAsset.image_path)}`)
      .then((data) => {
        setPromptDetail(data);
        setPromptText(data.prompt);
      })
      .catch((err) => setError(String(err)));
  }, [selectedAsset?.image_path]);

  const filteredAssets = useMemo(() => {
    const assets = browserData?.assets || [];
    return assets.filter((asset) => {
      if (typeFilter !== "all" && asset.asset_type !== typeFilter) return false;
      if (batchFilter !== "all" && asset.batch !== batchFilter) return false;
      return true;
    });
  }, [browserData, typeFilter, batchFilter]);

  useEffect(() => {
    if (!filteredAssets.length) {
      setSelectedAsset(null);
      return;
    }
    if (!selectedAsset || !filteredAssets.some((asset) => asset.image_path === selectedAsset.image_path)) {
      setSelectedAsset(filteredAssets[0]);
    }
  }, [filteredAssets, selectedAsset?.image_path]);

  const dirty = promptDetail ? promptText !== promptDetail.prompt : false;

  async function savePrompt() {
    if (!selectedAsset) return;
    setBusy(true);
    setStatus("");
    setError("");
    try {
      const data = await api<{ saved: boolean; prompt_path: string; prompt_exists: boolean }>("/asset-browser/prompt", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_path: selectedAsset.image_path, prompt: promptText })
      });
      setPromptDetail((prev) => prev ? { ...prev, prompt: promptText, prompt_path: data.prompt_path, prompt_exists: true } : prev);
      setBrowserData((prev) => prev ? {
        ...prev,
        assets: prev.assets.map((asset) => asset.image_path === selectedAsset.image_path ? {
          ...asset,
          prompt_path: data.prompt_path,
          prompt_exists: true
        } : asset)
      } : prev);
      setSelectedAsset((prev) => prev ? { ...prev, prompt_path: data.prompt_path, prompt_exists: true } : prev);
      setStatus("Saved");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel assetBrowserPanel">
      <div className="panelHeader">
        <div>
          <span className="eyebrow">Assets</span>
          <h1>Generated References</h1>
          <p>{browserData ? browserData.root.label : "No asset root selected"}</p>
        </div>
        <div className="assetBrowserControls">
          <select value={selectedRoot} onChange={(e) => setSelectedRoot(e.target.value)}>
            {roots.map((root) => <option key={root.root_path} value={root.root_path}>{root.label}</option>)}
          </select>
          <button onClick={() => setRefreshToken((value) => value + 1)} disabled={busy || !selectedRoot}><RefreshCw size={16} /></button>
        </div>
      </div>
      <div className="assetBrowserBody">
        <div className="assetBrowserLeft">
          <div className="assetFilters">
            {(["all", "character", "prop", "scene"] as const).map((type) => (
              <button
                key={type}
                className={`typeToggle ${typeFilter === type ? "active" : ""}`}
                onClick={() => setTypeFilter(type)}
              >
                {assetTypeLabel(type)}
                <span>{browserData?.counts[type] || 0}</span>
              </button>
            ))}
            <select value={batchFilter} onChange={(e) => setBatchFilter(e.target.value)}>
              <option value="all">All batches</option>
              {(browserData?.batches || []).map((batch) => <option key={batch} value={batch}>{batch}</option>)}
            </select>
          </div>
          <div className="assetGrid">
            {filteredAssets.map((asset) => (
              <button
                key={asset.image_path}
                className={`assetTile ${selectedAsset?.image_path === asset.image_path ? "selected" : ""}`}
                onClick={() => setSelectedAsset(asset)}
              >
                <img src={fileUrl(asset.image_path)} alt={asset.label} />
                <strong>{asset.label}</strong>
                <span>{assetTypeLabel(asset.asset_type)} · {asset.batch}</span>
                {!asset.prompt_exists && <em>No prompt file</em>}
              </button>
            ))}
            {!filteredAssets.length && <div className="emptyState">No matching assets.</div>}
          </div>
        </div>
        <aside className="assetDetailPane">
          {selectedAsset ? (
            <>
              <div className="assetDetailPreview">
                <img src={fileUrl(selectedAsset.image_path)} alt={selectedAsset.label} />
              </div>
              <div className="assetMeta">
                <strong>{selectedAsset.label}</strong>
                <span>{assetTypeLabel(selectedAsset.asset_type)} · {selectedAsset.batch}</span>
                <small>{selectedAsset.source_dir}</small>
                <small>{promptDetail?.prompt_path || selectedAsset.prompt_path}</small>
              </div>
              <textarea
                className="promptEditor"
                value={promptText}
                onChange={(e) => {
                  setPromptText(e.target.value);
                  setStatus("");
                }}
              />
              <div className="editorFooter">
                <span className={dirty ? "stale" : status ? "ready" : ""}>{dirty ? "Unsaved changes" : status}</span>
                <button className="accept" onClick={savePrompt} disabled={busy || !dirty}>{busy ? "Saving..." : "Save Prompt"}</button>
              </div>
            </>
          ) : (
            <div className="emptyState">No asset selected.</div>
          )}
        </aside>
      </div>
      {error && <div className="errorText">{error}</div>}
    </section>
  );
}

function Preview({ asset, path }: { asset: Asset; path: string }) {
  if (isVideo(asset)) return <video src={fileUrl(path)} controls />;
  if (isImage(asset)) return <img src={fileUrl(path)} alt={asset.label} />;
  return <div className="emptyPreview"><FileVideo /> {basename(path)}</div>;
}

function JobConsole({ job, onClose }: { job?: Job; onClose: () => void }) {
  const [detail, setDetail] = useState<Job | undefined>(job);
  const [lines, setLines] = useState<string[]>([]);

  useEffect(() => {
    setDetail(job);
    setLines([]);
    if (!job) return;
    api<{ job: Job }>(`/jobs/${job.id}`).then((data) => {
      setDetail(data.job);
      setLines((data.job.log_tail || "").split("\n"));
    });
    const source = new EventSource(`${API}/jobs/${job.id}/events`);
    source.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.line) setLines((prev) => [...prev.slice(-400), data.line]);
      if (data.done) source.close();
    };
    return () => source.close();
  }, [job?.id]);

  async function stop() {
    if (!job) return;
    await api(`/jobs/${job.id}/stop`, { method: "POST" });
  }

  return (
    <section className="panel consolePanel">
      <div className="panelHeader compact">
        <h2>Job Console</h2>
        <button onClick={onClose}>×</button>
      </div>
      {detail ? (
        <>
          <div className="consoleMeta">
            <strong>{detail.step}</strong>
            <span className={`badge ${statusClass(detail.status)}`}>{detail.status}</span>
          </div>
          <div className="tabs">
            <span className="active">Logs</span>
            <span>Parameters</span>
            <span>Manifest</span>
            <span>Outputs</span>
          </div>
          <pre className="logs">{lines.join("\n") || "Waiting for log output..."}</pre>
          <div className="consoleFooter">
            <span>Job #{detail.id}</span>
            {detail.status === "running" || detail.status === "queued" ? <button className="stop" onClick={stop}>Stop</button> : null}
          </div>
        </>
      ) : (
        <div className="emptyState">Select a job to inspect live logs.</div>
      )}
    </section>
  );
}

function DependencyPanel({ asset }: { asset?: Asset }) {
  return (
    <section className="panel dependencyPanel">
      <div className="panelHeader compact">
        <h2>Dependency</h2>
        <GitFork size={18} />
      </div>
      {asset ? (
        <div className="depList">
          <p><strong>{asset.label}</strong></p>
          <p>{asset.asset_type}</p>
          {asset.asset_type === "character_image" && <p>Accepting this marks keyframes, video clips, and assembled episodes as stale.</p>}
          {asset.asset_type === "keyframe" && <p>Accepting this marks the related Seedance clip and assembled episode as stale.</p>}
          {asset.asset_type === "video_clip" && <p>Accepting this marks assembly and QA outputs as stale.</p>}
          {asset.asset_type === "cover_page" && <p>Accepting this affects future assembly when cover pages are enabled.</p>}
        </div>
      ) : (
        <div className="emptyState">Choose an asset to see downstream impact.</div>
      )}
    </section>
  );
}

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | undefined>();
  const [dashboard, setDashboard] = useState<Dashboard | undefined>();
  const [shotBoard, setShotBoard] = useState<ShotBoard | undefined>();
  const [shotBoardLoading, setShotBoardLoading] = useState(false);
  const [activeView, setActiveView] = useState<ViewMode>("projects");
  const [episodeId, setEpisodeId] = useState("EP01");
  const [scope, setScope] = useState("episode");
  const [selectedShot, setSelectedShot] = useState("");
  const [selectedShotIds, setSelectedShotIds] = useState<string[]>([]);
  const [dryRun, setDryRun] = useState(false);
  const [prepareOnly, setPrepareOnly] = useState(false);
  const [selectedJob, setSelectedJob] = useState<Job | undefined>();
  const [selectedAsset, setSelectedAsset] = useState<Asset | undefined>();
  const [error, setError] = useState("");
  const shotBoardRequestRef = useRef(0);
  const shotBoardInFlightRef = useRef(false);

  async function refreshProjects() {
    const data = await api<{ projects: Project[] }>("/projects");
    setProjects(data.projects);
    if (!projectId && data.projects[0]) setProjectId(data.projects[0].id);
  }

  async function refreshDashboard(id = projectId, episode = episodeId, refreshIndex = false) {
    if (!id) return;
    const data = await api<Dashboard>(`/projects/${id}?episode_id=${episode}${refreshIndex ? "&refresh=1" : ""}`);
    setDashboard(data);
    if (!selectedAsset && data.assets[0]) setSelectedAsset(data.assets[0]);
  }

  async function refreshShotBoard(id = projectId, episode = episodeId, force = false, refreshIndex = false) {
    if (!id) return;
    if (shotBoardInFlightRef.current && !force) return;
    const requestId = ++shotBoardRequestRef.current;
    shotBoardInFlightRef.current = true;
    setShotBoardLoading(true);
    try {
      const data = await api<ShotBoard>(`/projects/${id}/shot-board?episode_id=${episode}${refreshIndex ? "&refresh=1" : ""}`);
      if (requestId !== shotBoardRequestRef.current) return;
      setShotBoard(data);
      setSelectedShot((current) => {
        if (current && data.shots.some((shot) => shot.shot_id === current)) return current;
        return data.shots[0]?.shot_id || "";
      });
    } finally {
      if (requestId === shotBoardRequestRef.current) {
        shotBoardInFlightRef.current = false;
        setShotBoardLoading(false);
      }
    }
  }

  function changeEpisode(nextEpisode: string) {
    setEpisodeId(nextEpisode);
    setShotBoard(undefined);
    setSelectedShot("");
    setSelectedShotIds([]);
    refreshDashboard(projectId, nextEpisode).catch((err) => setError(String(err)));
    refreshShotBoard(projectId, nextEpisode, true).catch((err) => setError(String(err)));
  }

  useEffect(() => {
    refreshProjects().catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    setSelectedShotIds([]);
    refreshDashboard().catch((err) => setError(String(err)));
    refreshShotBoard().catch((err) => setError(String(err)));
    const timer = window.setInterval(() => {
      refreshDashboard().catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [projectId, episodeId]);

  async function runStep(step: string) {
    if (!projectId) return;
    setError("");
    try {
      const shots = scope === "shot" && selectedShot ? [selectedShot] : [];
      const data = await api<{ job: Job }>("/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          step,
          scope,
          episode_id: episodeId,
          shots,
          dry_run: dryRun,
          prepare_only: prepareOnly
        })
      });
      setSelectedJob(data.job);
      await refreshDashboard();
      await refreshShotBoard();
    } catch (err) {
      setError(String(err));
    }
  }

  const visibleShotBoard = shotBoard?.episode_id === episodeId ? shotBoard : undefined;

  return (
    <main className="appShell">
      <Sidebar
        projects={projects}
        selectedProjectId={projectId}
        activeView={activeView}
        onSelect={setProjectId}
        onView={setActiveView}
      />
      <div className="mainGrid">
        {activeView === "assets" ? (
          <AssetBrowser />
        ) : !dashboard ? (
          <ProjectCreator onCreated={(project) => {
            setProjects((prev) => [project, ...prev.filter((item) => item.id !== project.id)]);
            setProjectId(project.id);
          }} />
        ) : activeView === "projects" ? (
          <ProjectOverview
            dashboard={dashboard}
            shotBoard={visibleShotBoard}
            episodeId={episodeId}
            onEpisode={changeEpisode}
            onOpenEpisodes={() => setActiveView("episodes")}
            onOpenRuns={() => setActiveView("runs")}
            onRefresh={() => {
              return Promise.all([
                refreshDashboard(projectId, episodeId, true),
                refreshShotBoard(projectId, episodeId, true, true)
              ]).then(() => undefined);
            }}
          />
        ) : (
          <>
            <ShotControlRoom
              dashboard={dashboard}
              shotBoard={visibleShotBoard}
              shotBoardLoading={shotBoardLoading}
              activeView={activeView}
              episodeId={episodeId}
              onEpisode={changeEpisode}
              selectedShotId={selectedShot}
              selectedShotIds={selectedShotIds}
              onSelectShot={setSelectedShot}
              onSelectedShotIds={setSelectedShotIds}
              onRefresh={(refreshIndex = true) => {
                return Promise.all([
                  refreshDashboard(projectId, episodeId, refreshIndex),
                  refreshShotBoard(projectId, episodeId, true, refreshIndex)
                ]).then(() => undefined);
              }}
              onRun={runStep}
              onSelectJob={setSelectedJob}
            />
            {selectedJob && <JobConsole job={selectedJob} onClose={() => setSelectedJob(undefined)} />}
          </>
        )}
        {error && <div className="toast">{error}</div>}
      </div>
    </main>
  );
}

function ProjectDashboardHeader({ dashboard }: { dashboard: Dashboard }) {
  return (
    <section className="panel topBanner">
      <div>
        <span className="eyebrow">Current Project</span>
        <h2>{dashboard.project.name}</h2>
        <p>{dashboard.project.novel_path}</p>
      </div>
      <div className="bannerStats">
        <span>{dashboard.episodes.length} episodes</span>
        <span>{dashboard.shots.length} shots</span>
        <span>{dashboard.assets.length} assets</span>
      </div>
    </section>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
