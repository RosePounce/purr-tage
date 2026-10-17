// Copyright (C) 2026 RosePounce
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The relay, end to end, with no dependency: Node 22 has fetch, FormData and
// Request built in. The services are replaced by a fake `fetch` that records
// what would have gone out.  Run with `npm test` or `node --test`.

import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";

import worker from "../src/index.js";
import { fenced, title } from "../src/connectors/format.js";
import { issueBody } from "../src/connectors/github.js";

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]);

function gameRequest({ description = "Le chaton est coincé.", screenshot = PNG,
                       agent = "Purrtage/1.0.0", report = "# Rapport\n" } = {}) {
  const form = new FormData();
  form.append("meta", JSON.stringify({
    version: "1.0.0", language: "fr", system: "Linux 7.0", install: "frozen",
    description,
  }));
  form.append("report", new Blob([report], { type: "text/plain" }), "bogue_20261016-101500.txt");
  if (screenshot) form.append("screenshot", new Blob([screenshot], { type: "image/png" }), "bogue.png");
  return new Request("https://relay.example/report", {
    method: "POST", body: form, headers: { "user-agent": agent },
  });
}

// Workers KV, as far as the relay uses it.
function fakeStore() {
  const objects = new Map();
  const options = new Map();
  return {
    objects,
    options,
    async put(key, value, opts) {
      objects.set(key, value);
      options.set(key, opts);
    },
    async get(key, type) {
      if (!objects.has(key)) return null;
      assert.equal(type, "arrayBuffer");
      return objects.get(key);
    },
  };
}

let sent;
let failing;
const realFetch = globalThis.fetch;

beforeEach(() => {
  sent = [];
  failing = new Set();
  globalThis.fetch = async (url, init) => {
    sent.push({ url: String(url), init });
    const host = new URL(url).host;
    return new Response("{}", { status: failing.has(host) ? 500 : 200 });
  };
});

afterEach(() => {
  globalThis.fetch = realFetch;
});

const ALL = {
  GITHUB_TOKEN: "t", GITHUB_REPO: "owner/repo", GITHUB_LABELS: "bug, joueur",
  DISCORD_WEBHOOK_URL: "https://discord.example/api/webhooks/1/x",
  RESEND_API_KEY: "k", EMAIL_TO: "a@example.org, b@example.org", EMAIL_FROM: "relay@example.org",
};

describe("the report endpoint", () => {
  it("stores the report and hands it to every connector", async () => {
    const env = { ...ALL, REPORTS: fakeStore() };
    const answer = await worker.fetch(gameRequest(), env);
    assert.equal(answer.status, 202);
    const body = await answer.json();
    assert.deepEqual(body.delivered.sort(), ["discord", "email", "github"]);

    const keys = [...env.REPORTS.objects.keys()].sort();
    assert.deepEqual(keys, [
      `reports/${body.id}/meta.json`,
      `reports/${body.id}/report.txt`,
      `reports/${body.id}/screenshot.png`,
    ]);
    assert.equal(sent.length, 3);
  });

  it("lets the stored reports expire", async () => {
    const env = { REPORTS: fakeStore(), REPORT_TTL_DAYS: "30" };
    await worker.fetch(gameRequest(), env);
    for (const opts of env.REPORTS.options.values()) {
      assert.equal(opts.expirationTtl, 30 * 24 * 3600);
    }
    const byDefault = { REPORTS: fakeStore() };
    await worker.fetch(gameRequest(), byDefault);
    const [first] = byDefault.REPORTS.options.values();
    assert.equal(first.expirationTtl, 180 * 24 * 3600);
  });

  it("links the stored screenshot from the issue", async () => {
    const env = { GITHUB_TOKEN: "t", GITHUB_REPO: "owner/repo", REPORTS: fakeStore() };
    const answer = await worker.fetch(gameRequest(), env);
    const { id } = await answer.json();
    const issue = JSON.parse(sent[0].init.body);
    assert.equal(sent[0].url, "https://api.github.com/repos/owner/repo/issues");
    assert.ok(issue.body.includes(`https://relay.example/shot/${id}.png`));
    assert.equal(issue.title, "Bug report: Le chaton est coincé.");

    const shot = await worker.fetch(new Request(`https://relay.example/shot/${id}.png`), env);
    assert.equal(shot.status, 200);
    assert.equal(shot.headers.get("content-type"), "image/png");
  });

  it("works with no screenshot", async () => {
    const env = { ...ALL, REPORTS: fakeStore() };
    const answer = await worker.fetch(gameRequest({ screenshot: null }), env);
    assert.equal(answer.status, 202);
    const issue = JSON.parse(sent.find((s) => s.url.includes("github")).init.body);
    assert.ok(!issue.body.includes("/shot/"));
  });

  it("keeps the report when a service fails", async () => {
    failing.add("discord.example");
    const env = { ...ALL, REPORTS: fakeStore() };
    const answer = await worker.fetch(gameRequest(), env);
    assert.equal(answer.status, 202);
    assert.deepEqual((await answer.json()).delivered.sort(), ["email", "github"]);
  });

  it("asks the game to retry when the report reached nowhere", async () => {
    failing.add("discord.example");
    const env = { DISCORD_WEBHOOK_URL: ALL.DISCORD_WEBHOOK_URL };   // no KV either
    const answer = await worker.fetch(gameRequest(), env);
    assert.equal(answer.status, 503);
  });

  it("refuses what does not come from the game", async () => {
    const answer = await worker.fetch(gameRequest({ agent: "curl/8" }), { REPORTS: fakeStore() });
    assert.equal(answer.status, 400);
  });

  it("refuses a screenshot that is not a PNG", async () => {
    const answer = await worker.fetch(
      gameRequest({ screenshot: new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9]) }),
      { REPORTS: fakeStore() });
    assert.equal(answer.status, 400);
  });

  it("refuses an oversized report", async () => {
    const answer = await worker.fetch(
      gameRequest({ report: "x".repeat(70 * 1024) }), { REPORTS: fakeStore() });
    assert.equal(answer.status, 413);
  });

  it("answers 429 when the limiter says so", async () => {
    const env = { REPORTS: fakeStore(), LIMITER: { limit: async () => ({ success: false }) } };
    const answer = await worker.fetch(gameRequest(), env);
    assert.equal(answer.status, 429);
    assert.equal(sent.length, 0);
  });

  it("serves no screenshot for a made-up id", async () => {
    const env = { REPORTS: fakeStore() };
    const answer = await worker.fetch(new Request("https://relay.example/shot/../secret.png"), env);
    assert.equal(answer.status, 404);
  });

  it("tells what it can reach, and nothing secret", async () => {
    const answer = await worker.fetch(new Request("https://relay.example/health"),
                                      { ...ALL, REPORTS: fakeStore() });
    const body = await answer.json();
    assert.deepEqual(body, {
      storage: true, limiter: false, connectors: ["github", "discord", "email"],
    });
    const text = JSON.stringify(body);
    assert.ok(!text.includes(ALL.DISCORD_WEBHOOK_URL) && !text.includes(ALL.GITHUB_TOKEN + '"'));
  });

  it("logs each report without the player's words", async (t) => {
    const lines = [];
    t.mock.method(console, "log", (line) => lines.push(line));
    t.mock.method(console, "error", (line) => lines.push(line));
    const env = { DISCORD_WEBHOOK_URL: ALL.DISCORD_WEBHOOK_URL, REPORTS: fakeStore() };
    await worker.fetch(gameRequest({ description: "secret du joueur" }), env);
    assert.equal(lines.length, 1);
    const entry = JSON.parse(lines[0]);
    assert.equal(entry.event, "report");
    assert.equal(entry.stored, true);
    assert.deepEqual(entry.delivered, ["discord"]);
    assert.ok(!lines[0].includes("secret du joueur"));
  });

  it("takes a report posted to the root as well", async () => {
    const request = gameRequest();
    const atRoot = new Request("https://relay.example/", request);
    const answer = await worker.fetch(atRoot, { REPORTS: fakeStore() });
    assert.equal(answer.status, 202);
    assert.ok((await answer.json()).id);
  });

  it("only takes POST", async () => {
    const answer = await worker.fetch(new Request("https://relay.example/report"), {});
    assert.equal(answer.status, 405);
  });
});

describe("what the services receive", () => {
  it("never lets Discord ping anyone", async () => {
    const env = { DISCORD_WEBHOOK_URL: ALL.DISCORD_WEBHOOK_URL, REPORTS: fakeStore() };
    await worker.fetch(gameRequest({ description: "@everyone regardez" }), env);
    const form = sent[0].init.body;
    const payload = JSON.parse(form.get("payload_json"));
    assert.deepEqual(payload.allowed_mentions, { parse: [] });
    assert.ok(form.get("files[0]"));
    assert.ok(form.get("files[1]"));
  });

  it("e-mails every recipient with both files", async () => {
    const env = { ...ALL, GITHUB_TOKEN: "", DISCORD_WEBHOOK_URL: "", REPORTS: fakeStore() };
    await worker.fetch(gameRequest(), env);
    const mail = JSON.parse(sent[0].init.body);
    assert.deepEqual(mail.to, ["a@example.org", "b@example.org"]);
    assert.deepEqual(mail.attachments.map((a) => a.filename),
                     ["bogue_20261016-101500.txt", "screenshot.png"]);
  });

  it("keeps the player's words inside the code fence", () => {
    const text = "avant ``` après";
    const block = fenced(text);
    assert.ok(block.startsWith("````text\n"));
    assert.ok(block.endsWith("\n````"));
  });

  it("titles a report without description", () => {
    assert.equal(title({ meta: { description: "" } }), "Bug report (no description)");
    const long = title({ meta: { description: "a".repeat(200) } });
    assert.ok(long.length <= "Bug report: ".length + 80);
  });

  it("caps the issue body below GitHub's limit", () => {
    const body = issueBody({
      id: "x", meta: { description: "d" }, text: "y".repeat(200000), screenshotUrl: null,
    });
    assert.ok(body.length <= 60000);
  });
});
