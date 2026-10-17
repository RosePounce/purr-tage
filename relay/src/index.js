// Copyright (C) 2026 RosePounce
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The bug report relay: the only address the game knows.
//
// The game posts a report here (see purrtage/bugsend.py); the relay checks
// it, keeps a copy in Workers KV and hands it to every connector that is switched on
// — an issue, a Discord message, an e-mail. Plugging a service in or out is a
// matter of secrets on this Worker: the game never changes, and never holds a
// service key, since its code is public.
//
// What the game expects back:
//   2xx           the report is taken, the game forgets it;
//   4xx           refused for good (too big, malformed): the game drops it,
//                 except 408 and 429, which pass with time;
//   anything else the game keeps it and retries on its next launch.

import { activeConnectors } from "./connectors/index.js";

export const LIMITS = {
  body: 8 * 1024 * 1024, // the whole request
  report: 64 * 1024, // the .txt written by bugreport.py
  screenshot: 6 * 1024 * 1024, // a 2880x1800 capture fits comfortably
  description: 2000, // the game stops at 1200 characters
  field: 120, // version, language, system...
};

const META_FIELDS = ["version", "language", "system", "install"];
const DEFAULT_TTL_DAYS = 180; // how long KV keeps a report, unless REPORT_TTL_DAYS says otherwise
const PNG_MAGIC = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

function json(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

// One JSON line per event: the dashboard's Logs page can filter on any field.
// Never the IP, the description or the report itself.
export function log(level, event, fields = {}) {
  const line = JSON.stringify({ event, ...fields });
  if (level === "error") console.error(line);
  else if (level === "warn") console.warn(line);
  else console.log(line);
}

function clip(value, max) {
  return String(value ?? "").slice(0, max);
}

// A random, unguessable id: it also names the screenshot's public link.
export function newId(now = new Date()) {
  const stamp = now.toISOString().slice(0, 19).replace(/[-:]/g, "").replace("T", "-");
  const bytes = crypto.getRandomValues(new Uint8Array(12));
  const random = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${stamp}-${random}`;
}

function isPng(bytes) {
  return bytes.length > PNG_MAGIC.length && PNG_MAGIC.every((b, i) => bytes[i] === b);
}

// Read and check the form. Returns { report } or { error, status }.
export async function parseReport(request) {
  const length = Number(request.headers.get("content-length") || 0);
  if (length > LIMITS.body) return { status: 413, error: "too large" };
  if (!(request.headers.get("user-agent") || "").startsWith("Purrtage/")) {
    return { status: 400, error: "not from the game" };
  }

  let form;
  try {
    form = await request.formData();
  } catch {
    return { status: 400, error: "not a form" };
  }

  let meta = {};
  try {
    meta = JSON.parse(form.get("meta") || "{}");
  } catch {
    return { status: 400, error: "bad meta" };
  }
  if (typeof meta !== "object" || meta === null) meta = {};

  const reportFile = form.get("report");
  if (!reportFile || typeof reportFile === "string") {
    return { status: 400, error: "no report" };
  }
  if (reportFile.size > LIMITS.report) return { status: 413, error: "report too large" };
  const text = await reportFile.text();

  let screenshot = null;
  const shotFile = form.get("screenshot");
  if (shotFile && typeof shotFile !== "string") {
    if (shotFile.size > LIMITS.screenshot) {
      return { status: 413, error: "screenshot too large" };
    }
    screenshot = new Uint8Array(await shotFile.arrayBuffer());
    if (!isPng(screenshot)) return { status: 400, error: "screenshot is not a PNG" };
  }

  const clean = { description: clip(meta.description, LIMITS.description).trim() };
  for (const key of META_FIELDS) clean[key] = clip(meta[key], LIMITS.field);

  return {
    report: {
      meta: clean,
      text,
      reportName: clip(reportFile.name || "report.txt", LIMITS.field),
      screenshot,
    },
  };
}

// Workers KV: one key per file, all expiring together. KV has no folders,
// but "reports/<id>/..." keeps the keys of one report side by side.
export function ttlSeconds(env) {
  const days = Number(env.REPORT_TTL_DAYS) || DEFAULT_TTL_DAYS;
  return Math.max(1, days) * 24 * 3600;
}

async function store(env, report) {
  const folder = `reports/${report.id}`;
  const options = { expirationTtl: ttlSeconds(env) };
  await env.REPORTS.put(`${folder}/meta.json`, JSON.stringify(report.meta), options);
  await env.REPORTS.put(`${folder}/report.txt`, report.text, options);
  if (report.screenshot) {
    const bytes = report.screenshot;
    const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    await env.REPORTS.put(`${folder}/screenshot.png`, buffer, options);
  }
}

async function handleReport(request, env) {
  // The IP only keys the rate limiter: it is neither stored nor forwarded.
  if (env.LIMITER) {
    const ip = request.headers.get("cf-connecting-ip") || "unknown";
    const { success } = await env.LIMITER.limit({ key: ip });
    if (!success) {
      log("warn", "refused", { status: 429, error: "slow down" });
      return json(429, { error: "slow down" });
    }
  }

  const parsed = await parseReport(request);
  if (parsed.error) {
    log("warn", "refused", {
      status: parsed.status,
      error: parsed.error,
      agent: clip(request.headers.get("user-agent"), LIMITS.field),
    });
    return json(parsed.status, { error: parsed.error });
  }
  const report = parsed.report;
  report.id = newId();
  report.receivedAt = new Date().toISOString();

  let stored = false;
  if (env.REPORTS) {
    try {
      await store(env, report);
      stored = true;
    } catch (err) {
      log("error", "storage_failed", { id: report.id, error: String(err) });
    }
  }
  // The screenshot's link only exists if it was stored.
  const origin = new URL(request.url).origin;
  report.screenshotUrl =
    stored && report.screenshot ? `${origin}/shot/${report.id}.png` : null;

  const connectors = activeConnectors(env);
  const outcomes = await Promise.allSettled(connectors.map((c) => c.send(report, env)));
  const delivered = [];
  const failed = [];
  outcomes.forEach((outcome, i) => {
    if (outcome.status === "fulfilled") delivered.push(connectors[i].name);
    else failed.push({ connector: connectors[i].name, error: String(outcome.reason) });
  });

  // Nowhere to keep it: let the game try again later rather than lose it.
  const status = !stored && delivered.length === 0 ? 503 : 202;
  log(failed.length || status !== 202 ? "error" : "info", "report", {
    id: report.id,
    status,
    version: report.meta.version,
    screenshot: Boolean(report.screenshot),
    stored,
    connectors: connectors.map((c) => c.name),
    delivered,
    failed,
  });
  if (status === 503) return json(503, { error: "no destination reached" });
  return json(202, { id: report.id, delivered });
}

async function handleShot(id, env) {
  if (!env.REPORTS || !/^[0-9]{8}-[0-9]{6}-[0-9a-f]{24}$/.test(id)) {
    return new Response("not found", { status: 404 });
  }
  const image = await env.REPORTS.get(`reports/${id}/screenshot.png`, "arrayBuffer");
  if (!image) return new Response("not found", { status: 404 });
  return new Response(image, {
    headers: {
      "content-type": "image/png",
      "cache-control": "public, max-age=86400",
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // "/" takes reports too: a game configured without "/report" at the
    // end of the address still gets its reports through.
    if (url.pathname === "/report" || (url.pathname === "/" && request.method === "POST")) {
      if (request.method !== "POST") return json(405, { error: "POST only" });
      return handleReport(request, env);
    }
    const shot = url.pathname.match(/^\/shot\/([^/]+)\.png$/);
    if (shot && request.method === "GET") return handleShot(shot[1], env);
    // What the relay can reach, without revealing any secret: is the KV
    // namespace bound, which connectors found their secrets.
    if (url.pathname === "/health") {
      return json(200, {
        storage: Boolean(env.REPORTS),
        limiter: Boolean(env.LIMITER),
        connectors: activeConnectors(env).map((c) => c.name),
      });
    }
    if (url.pathname === "/") {
      return new Response("Purr-tage bug report relay\n", {
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    }
    return new Response("not found", { status: 404 });
  },
};
