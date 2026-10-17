// Copyright (C) 2026 RosePounce
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Every service a report can go to. A connector is an object with:
//   name             shown in the logs and in the relay's answer;
//   enabled(env)     true when its secrets are set;
//   send(report, env) resolves once delivered, throws otherwise.
//
// Adding a service: write a file next to these ones, add it to the list.
// Switching one off: delete its secret (`wrangler secret delete ...`).

import discord from "./discord.js";
import email from "./email.js";
import github from "./github.js";

export const CONNECTORS = [github, discord, email];

export function activeConnectors(env) {
  return CONNECTORS.filter((c) => c.enabled(env));
}
