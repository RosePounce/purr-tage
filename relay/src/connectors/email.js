// Copyright (C) 2026 RosePounce
// SPDX-License-Identifier: GPL-3.0-or-later
//
// E-mail, through Resend (https://resend.com): one message per report, with
// the report and the screenshot attached.
//
// Secrets: RESEND_API_KEY, EMAIL_TO (one or several addresses, comma-separated),
//          EMAIL_FROM (an address on a domain verified in Resend).
// The addresses are secrets rather than vars so that they never land in the
// public repository.

import { check, summary, title, toBase64 } from "./format.js";

export function message(report, env) {
  const lines = [
    report.meta.description || "(no description)",
    "",
    `Build: ${summary(report)}`,
    `Relay id: ${report.id}`,
  ];
  if (report.screenshotUrl) lines.push(`Screenshot: ${report.screenshotUrl}`);

  const attachments = [{ filename: report.reportName, content: toBase64(new TextEncoder().encode(report.text)) }];
  if (report.screenshot) {
    attachments.push({ filename: "screenshot.png", content: toBase64(report.screenshot) });
  }
  return {
    from: env.EMAIL_FROM,
    to: env.EMAIL_TO.split(",").map((a) => a.trim()).filter(Boolean),
    subject: title(report),
    text: lines.join("\n"),
    attachments,
  };
}

export default {
  name: "email",

  enabled(env) {
    return Boolean(env.RESEND_API_KEY && env.EMAIL_TO && env.EMAIL_FROM);
  },

  async send(report, env) {
    const response = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        authorization: `Bearer ${env.RESEND_API_KEY}`,
        "content-type": "application/json",
      },
      body: JSON.stringify(message(report, env)),
    });
    await check(response, "email");
  },
};
