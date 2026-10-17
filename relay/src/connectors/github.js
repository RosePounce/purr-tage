// Copyright (C) 2026 RosePounce
// SPDX-License-Identifier: GPL-3.0-or-later
//
// GitHub Issues: one issue per report.
//
// Secret: GITHUB_TOKEN, a fine-grained token limited to the repository, with
// "Issues: read and write" and nothing else.
// Vars:   GITHUB_REPO ("owner/name"), GITHUB_LABELS (comma-separated).
//
// The API cannot attach an image: the issue links to the copy the relay
// keeps in Workers KV.

import { check, clip, fenced, summary, title } from "./format.js";

const BODY_LIMIT = 60000; // GitHub refuses bodies over 65536 characters

export function issueBody(report) {
  const parts = [
    "### Description",
    "",
    report.meta.description ? fenced(report.meta.description) : "_No description._",
    "",
    `**Build:** ${summary(report)}  `,
    `**Relay id:** \`${report.id}\``,
    "",
  ];
  if (report.screenshotUrl) {
    parts.push("### Screenshot", "", `![screenshot](${report.screenshotUrl})`, "");
  }
  parts.push(
    "<details><summary>Full report</summary>",
    "",
    fenced(clip(report.text, BODY_LIMIT - 4000), "markdown"),
    "",
    "</details>",
  );
  return clip(parts.join("\n"), BODY_LIMIT);
}

export default {
  name: "github",

  enabled(env) {
    return Boolean(env.GITHUB_TOKEN && env.GITHUB_REPO);
  },

  async send(report, env) {
    const labels = (env.GITHUB_LABELS || "")
      .split(",")
      .map((l) => l.trim())
      .filter(Boolean);
    const response = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/issues`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${env.GITHUB_TOKEN}`,
        accept: "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
        "user-agent": "purrtage-relay",
        "content-type": "application/json",
      },
      body: JSON.stringify({ title: title(report), body: issueBody(report), labels }),
    });
    await check(response, "github");
  },
};
