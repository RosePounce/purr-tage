// Copyright (C) 2026 RosePounce
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Discord: a message in a channel, through a webhook, with the report and the
// screenshot attached.
//
// Secret: DISCORD_WEBHOOK_URL (channel settings > Integrations > Webhooks).

import { check, clip, summary, title } from "./format.js";

export function payload(report) {
  return {
    username: "Purr-tage",
    // The player's words must never ping @everyone or anyone else.
    allowed_mentions: { parse: [] },
    embeds: [
      {
        title: clip(title(report), 256),
        description: clip(report.meta.description || "*No description.*", 4000),
        color: 0xeec66c,
        footer: { text: clip(`${summary(report)} · ${report.id}`, 2048) },
        timestamp: report.receivedAt,
      },
    ],
  };
}

export default {
  name: "discord",

  enabled(env) {
    return Boolean(env.DISCORD_WEBHOOK_URL);
  },

  async send(report, env) {
    const form = new FormData();
    form.append("payload_json", JSON.stringify(payload(report)));
    form.append(
      "files[0]",
      new Blob([report.text], { type: "text/plain" }),
      report.reportName,
    );
    if (report.screenshot) {
      form.append(
        "files[1]",
        new Blob([report.screenshot], { type: "image/png" }),
        "screenshot.png",
      );
    }
    const response = await fetch(env.DISCORD_WEBHOOK_URL, { method: "POST", body: form });
    await check(response, "discord");
  },
};
