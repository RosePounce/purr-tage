# The bug report relay

[Français](README.md) · **English**

> **Reserved folder** — this relay is the game's own: it runs on RosePounce's
> Cloudflare account and receives the players' reports. There is nothing to do
> here to contribute to the game, and a pull request touching `relay/` is not
> merged: the *Relay guard* check refuses it and `.github/CODEOWNERS`
> reserves its review. A contributor has no reason to deploy it anyway: run
> from the sources, the game sends no report
> ([README-dev.en.md](../README-dev.en.md#sending-bug-reports)).
>
> What follows is for whoever keeps the game's relay, or hosts their own on
> their own fork and their own account.

The game knows a single address: this relay's. When a player sends a report
(**F8**), the relay checks it, keeps a copy and forwards it to every service
that is plugged in:

```
Game (F8)  ──HTTPS──>  Relay /report  ──>  GitHub Issues
                           │           ──>  Discord
                           │           ──>  e-mail (Resend)
                           └─ copy in Workers KV (report, screenshot)
```

Plugging a service in or out happens on the relay, with no new release of the
game. No key lives in the game, whose code is public.

It is a [Cloudflare Worker](https://developers.cloudflare.com/workers/),
written in JavaScript with no dependency at all. Both the Worker and its
storage, Workers KV, stay within Cloudflare's free plan for a game of this
size: 1 GB of storage and 1,000 writes a day, that is over 300 reports a
day.

## Putting the relay online

You need a Cloudflare account, on the free plan: no payment method is
asked for. Two ways to go about it.

### From the dashboard, with nothing to install

Cloudflare follows the GitHub repository and redeploys the relay on every
push: the simplest way when working from several computers.

1. **Storage & Databases** > **Workers KV** > **Create**: name the namespace
   `purrtage-reports`, then copy its **ID**.
2. Paste that ID into `wrangler.toml`, in place of
   `REPLACE_WITH_THE_NAMESPACE_ID`, then commit and push. The ID is not a
   secret.
3. **Workers & Pages** > **Create** > **Import a repository**: pick the
   repository, the branch that holds `relay/`, and set `relay` as the
   **Root directory**. The default deploy command, `npx wrangler deploy`,
   is fine.

The services' secrets are then added on the Worker's page: **Settings** >
**Variables and Secrets** > **Add**, type **Secret**. They are kept from one
deployment to the next. The public settings — `GITHUB_REPO`,
`GITHUB_LABELS`, `REPORT_TTL_DAYS` — are rewritten from `wrangler.toml` on
every deployment: that is where they are changed.

### From the command line

You need Node.js 18 or newer, with npm.

```bash
cd relay
npm install                                    # installs wrangler, Cloudflare's tool
npx wrangler login                             # opens the browser
npx wrangler kv namespace create purrtage-reports   # prints the ID to paste into wrangler.toml
npx wrangler deploy
```

Secrets are then added with `npx wrangler secret put`, as shown for each
service below.

### Trying it out

Both the dashboard and `deploy` give the relay's address, of the form
`https://purr-tage.<your-account>.workers.dev`.

Before touching the game, try it with the development version:

```bash
PURRTAGE_REPORT_URL=https://purr-tage.<your-account>.workers.dev/report python main.py
```

**F8**, a word, **Enter**: the window should read "Sent to the game's team.
Thank you!". Once the test works, the address goes into `BUG_REPORT_URL`, in
`purrtage/settings.py`, and the packages built from then on will send their
reports.

With no service plugged in, the relay still keeps every report in KV: you can
deploy it first and plug the services in afterwards.

## Plugging in the services

Each service switches on as soon as its secrets are set, and off when they are
removed. `wrangler secret put` asks for the value at the keyboard: it never
goes into the shell history or the repository.

### GitHub Issues

A report becomes an issue in the repository, with the screenshot shown in it.

1. GitHub > **Settings** > **Developer settings** > **Fine-grained tokens** >
   **Generate new token**.
2. **Repository access**: `purr-tage` only. **Permissions**: **Issues**,
   read and write. Nothing else.
3. ```bash
   npx wrangler secret put GITHUB_TOKEN
   ```

The repository and the labels are set in `wrangler.toml` (`GITHUB_REPO`,
`GITHUB_LABELS`). A token has an expiry date: when it runs out, issues stop
arriving and a new one has to be generated.

### Discord

A message in a channel, with the report and the screenshot attached.

1. Channel settings > **Integrations** > **Webhooks** > **New Webhook** >
   **Copy Webhook URL**.
2. ```bash
   npx wrangler secret put DISCORD_WEBHOOK_URL
   ```

Mentions are disabled: a player who writes `@everyone` wakes nobody up.

### E-mail

One e-mail per report, with the report and the screenshot attached. It goes
through [Resend](https://resend.com), whose free plan is more than enough.

1. Create a Resend account, verify a domain there, then create an API key.
   Without a verified domain, Resend only sends to the account's own address,
   from `onboarding@resend.dev`.
2. ```bash
   npx wrangler secret put RESEND_API_KEY
   npx wrangler secret put EMAIL_FROM     # e.g. bugs@your-domain.com
   npx wrangler secret put EMAIL_TO       # one or several addresses, comma-separated
   ```

The addresses are secrets rather than `wrangler.toml` settings: they have no
business in the public repository.

### Unplugging a service

```bash
npx wrangler secret delete DISCORD_WEBHOOK_URL
```

### Adding a service

A service is one file in `src/connectors/`, modelled on `discord.js`: a
`name`, an `enabled(env)` function that checks its secrets are there, and a
`send(report, env)` function that throws when it fails. Then add it to the
list in `src/connectors/index.js`. `src/connectors/format.js` already provides
the shared title, summary and formatting.

## What the relay accepts

| | |
|---|---|
| Address | `POST /report`, as `multipart/form-data` |
| `meta` | JSON: `version`, `language`, `system`, `install`, `description` |
| `report` | the report's `.txt` file, 64 KiB at most |
| `screenshot` | optional, a PNG of 6 MiB at most |
| Header | a `User-Agent` starting with `Purrtage/` |

The answers, and what the game does with them:

| Answer | Meaning | The game |
|---|---|---|
| 202 | report kept, or forwarded to at least one service | forgets it |
| 400, 413 | refused: malformed, too big | drops it |
| 429 | more than 5 reports in a minute from the same address | sends it again on the next launch |
| 503 | neither storage nor any service reachable | sends it again on the next launch |

`GET /shot/<id>.png` serves a stored screenshot: that is the link the issues
contain.

## Privacy

* A report holds nothing personal: the player's description, the game state,
  the game and system versions.
* The IP address is only used to limit the number of reports. It is neither
  stored nor forwarded.
* A screenshot can be opened by anyone who knows its link, which carries 96
  random bits. Since the repository is public, a screenshot linked from an
  issue is public too. The player can untick the screenshot before sending.
* KV deletes each report and its screenshot after 180 days. The lifetime is
  set by `REPORT_TTL_DAYS`, in `wrangler.toml`; it applies to the reports
  received afterwards. Past that delay, the screenshot link in an issue
  leads nowhere.

## Diagnosing

When a report does not arrive, three places tell where it stopped.

1. **On the game's side**: `send.log`, in the reports folder (the **Open the
   folder** button of the F8 window leads there). One line per attempt:
   `not sent, no relay address` (the game does not know the relay),
   `unreachable` (network, DNS, certificate), `refused` or `sent`, with the
   relay's answer.
2. **The relay's state**: `https://purr-tage.<your-account>.workers.dev/health`
   tells whether the KV storage is bound and which services found their
   secrets — without ever showing them.
   ```json
   {"storage":true,"limiter":true,"connectors":["discord"]}
   ```
   A service missing from `connectors` lacks its secret, or the secret goes
   by another name.
3. **The relay's logs**: the Worker's page > **Logs**. One JSON line per
   report (`"event":"report"`) with `stored`, `delivered` and, for each
   failing service, the error it returned; one `"event":"refused"` line per
   refused report. Neither the IP address nor the player's words.

## Developing

```bash
npm test               # the tests, with Node 22 alone: no dependency
npx wrangler dev       # the relay on http://localhost:8787
npx wrangler tail      # the live relay's logs, as they happen
```

With `wrangler dev`, secrets go into a `.dev.vars` file, which Git ignores:

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```
