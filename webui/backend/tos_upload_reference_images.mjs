import fs from "fs/promises";
import path from "path";
import { randomUUID } from "crypto";
import { createRequire } from "module";

const require = createRequire("/Users/leiyang/Desktop/Coding/seedance_test/package.json");
const { TosClient } = require("@volcengine/tos-sdk");

function loadDotenv(dotenvPath) {
  return fs
    .readFile(dotenvPath, "utf8")
    .then((text) => {
      for (const rawLine of text.split(/\r?\n/)) {
        const line = rawLine.trim();
        if (!line || line.startsWith("#") || !line.includes("=")) continue;
        const idx = line.indexOf("=");
        const key = line.slice(0, idx).trim();
        const value = line.slice(idx + 1).trim().replace(/^['"]|['"]$/g, "");
        if (key && process.env[key] === undefined) process.env[key] = value;
      }
    })
    .catch(() => {});
}

function extensionForPath(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg") return "jpg";
  if (ext === ".png") return "png";
  if (ext === ".webp") return "webp";
  return "bin";
}

function mimeForExtension(ext) {
  if (ext === "jpg") return "image/jpeg";
  if (ext === "png") return "image/png";
  if (ext === "webp") return "image/webp";
  return "application/octet-stream";
}

function objectUrlForKey(client, bucket, key) {
  const publicBase = process.env.TOS_PUBLIC_BASE_URL;
  if (publicBase) {
    return `${publicBase.replace(/\/+$/g, "")}/${key
      .split("/")
      .map(encodeURIComponent)
      .join("/")}`;
  }
  const expires = Math.min(
    604800,
    Math.max(60, Number(process.env.TOS_PRESIGNED_EXPIRES || 86400))
  );
  return client.getPreSignedUrl({
    bucket,
    key,
    method: "GET",
    expires,
  });
}

function safePart(value, fallback) {
  return String(value || "")
    .replace(/[^a-zA-Z0-9-_]/g, "")
    .slice(0, 80) || fallback;
}

const stdin = await new Promise((resolve) => {
  let data = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => {
    data += chunk;
  });
  process.stdin.on("end", () => resolve(data));
});

await loadDotenv(path.resolve(".env"));
await loadDotenv("/Users/leiyang/Desktop/Coding/seedance_test/.env");

const payload = JSON.parse(stdin || "{}");
const refs = Array.isArray(payload.references) ? payload.references : [];
const missing = [];
const accessKeyId = process.env.TOS_ACCESS_KEY || process.env.VOLC_ACCESSKEY;
const accessKeySecret = process.env.TOS_SECRET_KEY || process.env.VOLC_SECRETKEY;
const bucket = process.env.TOS_BUCKET;
if (!accessKeyId) missing.push("TOS_ACCESS_KEY");
if (!accessKeySecret) missing.push("TOS_SECRET_KEY");
if (!bucket) missing.push("TOS_BUCKET");
if (missing.length) {
  throw new Error(`TOS upload is not configured. Missing: ${missing.join(", ")}`);
}

const client = new TosClient({
  accessKeyId,
  accessKeySecret,
  region: process.env.TOS_REGION || "cn-beijing",
  endpoint: process.env.TOS_ENDPOINT || "tos-cn-beijing.volces.com",
});
const prefix = (process.env.TOS_UPLOAD_PREFIX || "seedance-uploads").replace(/^\/+|\/+$/g, "");
const runPrefix = [
  prefix,
  safePart(payload.project_slug, "project"),
  safePart(payload.episode_id, "episode"),
  safePart(payload.shot_id, "shot"),
].join("/");

const uploaded = [];
for (const ref of refs) {
  if (ref.url) {
    uploaded.push(ref);
    continue;
  }
  const filePath = String(ref.path || "");
  if (!filePath) {
    uploaded.push(ref);
    continue;
  }
  const bytes = await fs.readFile(filePath);
  const ext = extensionForPath(filePath);
  const key = `${runPrefix}/${randomUUID()}.${ext}`;
  await client.putObject({
    bucket,
    key,
    body: bytes,
    contentLength: bytes.length,
    contentType: mimeForExtension(ext),
    acl: process.env.TOS_UPLOAD_ACL || undefined,
    forbidOverwrite: true,
    meta: {
      originalName: Buffer.from(path.basename(filePath), "utf8").toString("base64"),
      sourceTag: Buffer.from(String(ref.tag || ""), "utf8").toString("base64"),
    },
  });
  uploaded.push({
    ...ref,
    url: objectUrlForKey(client, bucket, key),
    tos_key: key,
    tos_bucket: bucket,
  });
}

process.stdout.write(JSON.stringify({ references: uploaded }, null, 2));
