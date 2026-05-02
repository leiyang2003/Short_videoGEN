import React, { useEffect, useMemo, useState } from "react";
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
  Square,
  Upload,
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
type ViewMode = "projects" | "assets";

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
        <button className="navItem"><ListChecks size={18} /> Episodes</button>
        <button className={`navItem ${activeView === "assets" ? "active" : ""}`} onClick={() => onView("assets")}><Image size={18} /> Assets</button>
        <button className="navItem"><Clock3 size={18} /> Jobs / Runs</button>
        <button className="navItem"><GitFork size={18} /> Dependency</button>
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
  const [activeView, setActiveView] = useState<ViewMode>("projects");
  const [episodeId, setEpisodeId] = useState("EP01");
  const [scope, setScope] = useState("episode");
  const [selectedShot, setSelectedShot] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [prepareOnly, setPrepareOnly] = useState(false);
  const [selectedJob, setSelectedJob] = useState<Job | undefined>();
  const [selectedAsset, setSelectedAsset] = useState<Asset | undefined>();
  const [error, setError] = useState("");

  async function refreshProjects() {
    const data = await api<{ projects: Project[] }>("/projects");
    setProjects(data.projects);
    if (!projectId && data.projects[0]) setProjectId(data.projects[0].id);
  }

  async function refreshDashboard(id = projectId) {
    if (!id) return;
    const data = await api<Dashboard>(`/projects/${id}?episode_id=${episodeId}`);
    setDashboard(data);
    if (!selectedAsset && data.assets[0]) setSelectedAsset(data.assets[0]);
  }

  useEffect(() => {
    refreshProjects().catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    refreshDashboard().catch((err) => setError(String(err)));
    const timer = window.setInterval(() => refreshDashboard().catch(() => undefined), 4000);
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
    } catch (err) {
      setError(String(err));
    }
  }

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
        ) : (
          <>
            <ProjectCreator onCreated={(project) => {
              setProjects((prev) => [project, ...prev.filter((item) => item.id !== project.id)]);
              setProjectId(project.id);
            }} />
            <ProjectDashboardHeader dashboard={dashboard} />
            <PipelineDashboard
              dashboard={dashboard}
              episodeId={episodeId}
              scope={scope}
              selectedShot={selectedShot}
              dryRun={dryRun}
              prepareOnly={prepareOnly}
              onEpisode={setEpisodeId}
              onScope={setScope}
              onShot={setSelectedShot}
              onDryRun={setDryRun}
              onPrepareOnly={setPrepareOnly}
              onRun={runStep}
              onSelectJob={setSelectedJob}
            />
            <PipelineDag dashboard={dashboard} onRun={runStep} />
            <AssetReview dashboard={dashboard} selectedAsset={selectedAsset} onSelectAsset={setSelectedAsset} onRefresh={() => refreshDashboard()} />
            <JobConsole job={selectedJob} onClose={() => setSelectedJob(undefined)} />
            <DependencyPanel asset={selectedAsset} />
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
