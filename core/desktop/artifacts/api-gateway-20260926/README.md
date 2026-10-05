# LamTools API gateway — deployment record (2026-09-26)

Aggregating gateway that fronts upstream model-provider API keys and exposes one
OpenAI-compatible endpoint, published over HTTPS for use by any client.

## Outcome

A working, hardened gateway is live at **`https://api.47.114.43.99.nip.io`**.
A relayed streaming and non-streaming chat completion was verified end to end
through the public TLS path, against a temporary in-network mock upstream, and
every pre-existing site on the host still answers 200.

## What runs

| Component | Image | Exposure |
|---|---|---|
| Gateway (`new-api`) | `calciumion/new-api:v0.13.2` | `127.0.0.1:3000` only; Caddy terminates TLS |
| Database | `postgres:16-alpine` | compose-internal network, no host port |
| Cache | `redis:7-alpine` | compose-internal network, no host port |

Compose project: `lamtools-api`, defined by `/opt/lamtools-api/docker-compose.yml`.
Secrets: `/opt/lamtools-api/.env` (0600), generated on the host.
Administrator credential: `/opt/lamtools-api/admin-credentials.txt` (0600, root only).
Redis is treated as a pure cache: no snapshotting, no AOF, `allkeys-lru`.

### Version choice

`v1.0.0-rc.40` was deployed first and its channel routing could not be made to
select any channel, despite systematic testing of weight/priority, the model
registry, billing-configuration gates, self-use mode and a restart. The project
ships no stable tag on the `v1.0.0` line, so the deployment was re-pinned to
`v0.13.2`, the newest stable release. The rc database was discarded rather than
migrated (it held nothing but the root account created minutes earlier).

## Mutations performed

1. Pulled images `calciumion/new-api:v1.0.0-rc.40`, `postgres:16-alpine`,
   `redis:7-alpine` (later `calciumion/new-api:v0.13.2`).
2. Created `/opt/lamtools-api/{,data,logs}` (root, 0750).
3. Wrote `/opt/lamtools-api/.env` (0600) and `docker-compose.yml` (0640);
   brought the stack up twice (rc, then stable, with `down -v` between).
4. Rotated `/opt/lamtools-api/admin-credentials.txt` (0600) when switching releases.
5. Backed up `/etc/caddy/Caddyfile` to
   `Caddyfile.before-api-gateway-20260926T110439Z`, appended the
   `api.47.114.43.99.nip.io` site, validated, and reloaded gracefully
   (`systemctl reload caddy-lamtools`; the unit's ExecReload is
   `caddy reload --config /etc/caddy/Caddyfile --force`).
   Old sha256 `c6da45995684b5d4b1575e676dc2e148dbba32855cf0d0cd6e4a4cfc8bf7b7a5`,
   new `dfc849f93891a506ed6cd0ab07ec97d4a1a34b628729029c3e72a5e719843098`.
6. Set options `RegisterEnabled=false`, `PasswordRegisterEnabled=false`,
   `EmailVerificationEnabled=false`, `TurnstileCheckEnabled=false`.
7. Installed `/usr/local/bin/lamtools-api-reload` (0755).
8. Cleared self-inflicted login-throttle keys in Redis (`rateLimit*`) twice,
   after repeated automated logins tripped the limiter.

Not touched: `caddy-lamtools` configuration other than the appended site,
`lamtools-relay`, `codex-api.service`, `frps` (Minecraft), `lamtools-cloudflared`,
`/var/www/lamtools`, security group, DNS, system packages.

## Exposure model

Only the gateway is published, and only on the loopback address; Caddy is the
sole public entry point and provisions a Let's Encrypt certificate for the new
name (issued 2026-09-26T10:06:19Z, expires 2026-12-25). The Caddy site rewrites
`X-Forwarded-For`/`X-Real-IP` from the real remote host instead of appending, so
callers cannot assert a fake client address; the gateway trusts only the compose
subnet (`172.30.0.0/24`). Security headers: `-Server`, HSTS one year,
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.

## Verified

| Check | Result |
|---|---|
| Public TLS console | `HTTP/2 200`, HSTS + nosniff + referrer-policy present, no `Server` header |
| `/v1/models` without a key | `401` |
| `/v1/models` with a key | `200`, model list from the configured channel |
| `POST /v1/chat/completions` (non-streaming) | `200`, expected reply and usage |
| `POST /v1/chat/completions` (streaming) | `200`, 6 SSE frames, `data: [DONE]`, text reassembles |
| Self-service registration | rejected: "registration has been disabled by administrator" |
| `X-Forwarded-For` spoofing | forged `203.0.113.7` never reaches the gateway log |
| Client key in logs | not in container stdout, not in `/opt/lamtools-api/logs` |
| Existing sites | homepage, downloads manifest, installer, relay health, codex mock — all `200` |
| Host headroom | 469 MB of 3623 MB used; disk 31% |

A first pass of the log-leak check reported a hit; a controlled re-test counting
occurrences before and after a single call, plus a scan of the on-disk logs,
found zero. The initial hit was a false positive in the check itself (an empty
match pattern), and the guarded check now asserts a non-empty key length first.

## Known constraints

- **A configuration change takes up to one cache-refresh interval to become
  live.** New channels and newly purchased credit are written to the database
  immediately but the running process serves them from a cache it refreshes on a
  timer (`SYNC_FREQUENCY`, default 60s). Measured with the default: a channel
  added to a running gateway returned 503 for the first ~60s, then 200 with no
  restart. An earlier note here claimed a restart was required — that was wrong;
  the restart only cleared the cache early. `SYNC_FREQUENCY` is now set to `5`,
  and a channel plus a purchase both went live within 15s. `lamtools-api-reload`
  remains available for instant effect.
- **Self-service registration is now on**, per the operator's decision to run
  this as a paid relay. New accounts start with `0` credit, which is the correct
  default for that model: a stranger can sign up but cannot consume anything
  until credit is granted. There is no captcha or email verification enabled
  (no Turnstile keys, no SMTP), so the registration endpoint is open to bots
  until one of those is configured.
- Login is rate-limited (Redis-backed, per IP); automated probing trips it.

## Runbook for the operator

1. Console: `https://api.47.114.43.99.nip.io` — log in as `root` with the
   password from `/opt/lamtools-api/admin-credentials.txt`, then change it.
2. Add upstream providers under 渠道 (channel): API key, base URL, model list.
3. Run `lamtools-api-reload` on the host.
4. Create client keys under 令牌; hand those to users.
5. To open self-registration: set `RegisterEnabled` and `PasswordRegisterEnabled`
   to true in the console, and set a new-user quota at the same time.

## Rollback

- Remove the appended site block from `/etc/caddy/Caddyfile` (or restore
  `Caddyfile.before-api-gateway-20260926T110439Z`), then
  `systemctl reload caddy-lamtools`.
- `docker compose -f /opt/lamtools-api/docker-compose.yml down` stops the
  gateway; add `-v` to also drop the database volume.
- `rm -f /usr/local/bin/lamtools-api-reload` removes the helper.
- Nothing else on the host was modified, so no further rollback is required.

## Paid-relay mode (added later the same day)

The operator clarified the intended business model: aggregate upstream provider
keys and sell credit to users. That changes the target state, so the following
was configured and verified.

Verified working end to end:

| Step | Evidence |
|---|---|
| A stranger registers through the public endpoint | account created, `quota=0`, group `default` |
| An account with no credit is refused | `403 用户额度不足, 剩余额度: ＄0.000000` |
| A purchased voucher credits the account | `0` → `1000000`, and the customer's own `/api/user/self` agrees |
| The credited account can then call | `200`, reply returned |
| Credit is metered down by usage | per-request rows in the call log carry token counts and quota |
| A channel added to a running gateway becomes live | `503` before the cache refresh, `200` after |

Money-related settings, read from the gateway:

| Setting | Value | Meaning |
|---|---|---|
| `QuotaPerUnit` | `500000` | 500,000 credit units = US$1 |
| `GroupRatio` | `{"default":1,"svip":1,"vip":1}` | the markup knob; `1` sells at upstream cost |
| `TopupGroupRatio` | `{"default":1,"svip":1,"vip":1}` | credit granted per unit paid |
| `DisplayInCurrencyEnabled` / `Price` | `true` / `7.3` | credit shown to users as currency |
| `MinTopUp` / `payment_setting.amount_options` | `1` / `[10,20,50,100,200,500]` | top-up page presets |
| `ModelRatio` | 239 models | per-model cost ratios ship with the product |
| `EpayId`, `PayAddress`, `StripePriceId` | empty | **no payment gateway is configured** |

Consequences worth stating plainly:

- Automated online top-up is not available until merchant credentials are
  entered. The working sales path today is the redemption voucher: collect
  payment by whatever means, then issue a code.
- The operator must set `GroupRatio` to a markup above `1`; until then every
  sale is made at upstream cost.
- Payment credentials stay with the operator. They are entered in the console,
  not passed through this workflow.
- Regulatory exposure specific to selling: generative-AI service filing, ICP
  filing for the site, business licence and a licensed payment channel, plus
  liability for content produced through the platform.

Mutations in this phase: `RegisterEnabled` and `PasswordRegisterEnabled` set to
true; `SYNC_FREQUENCY` added to the compose environment as `"5"` (previous file
kept as `docker-compose.yml.before-syncfreq-*`), gateway container recreated.
Rehearsal artefacts — two channels, two customer accounts, three vouchers, four
token rows — were all removed; final state is `users=root`, `channels=0`,
`live tokens=none`, `vouchers=none`. Cloud Assistant identifiers:
`paid-setup` `01A0DD93-16A3-5F36-B3A2-FD0E698F46A7`,
`paid-loop` `01A0DD93-9C3A-5B9A-A7C5-3208BE97815F`,
`credit-staleness` `01A0DD94-5405-5BBD-9BD5-82880BC9F30F`,
`sync-interval` `01A0DD96-574D-533C-9B16-49BEEFDDA19E`. The payment-state
checks ran as `check-payment`, `check-payment-2`, `check-payment-3`
(`01A0DD90-979E-5AA2-A543-7F71C95F25DB`) and `check-payment-4`; their run files
in this directory hold the exact identifiers.

## Cloud Assistant audit trail

Read-only: `inspect` `01A0DD58-A685-5CAF-8A1E-7E82BDBB43F9`,
`inspect-services` `01A0DD58-F1C5-5244-8B44-4D16790FA1E8`,
`docker-probe` `01A0DD5A-AAB1-5001-9377-EA071BBA8C07`,
`probe-init` `01A0DD60-DBCE-58DF-988E-51E49A10CF3C`,
`probe-admin-api` `01A0DD62-315D-5FF5-AA18-C30B465E915E`,
`probe-token-auth` `01A0DD62-6E29-5375-A3F9-C944A0096D9D`,
`inspect-distributor` `01A0DD69-0E11-5CEB-AAC1-81E6C372979B`,
`list-versions` `01A0DD72-6931-5798-B223-D97261FD28DE`,
`list-versions-2` `01A0DD73-2D65-51E9-A529-F4EB8E7905D7`,
`session-diagnose` `01A0DD75-45EC-5757-849B-A74A7CE0909E`.

Mutations: `pull-images` `01A0DD5D-C7C2-5D02-B459-6A8F17029308`,
`deploy-stack` `01A0DD60-08DA-517D-8770-27F56BB383C5`,
`init-root` `01A0DD61-E01D-5EE5-9846-95A03CC99FAA`,
`harden-registration` `01A0DD62-B9ED-5A78-8916-A0A61FC98712`,
`publish-caddy` `01A0DD63-7841-52DC-90CF-C8D78608D5D9`,
`clear-throttle-read` `01A0DD6E-CB48-542C-800A-B8ABCF0137C2`,
`routing-gate-final` `01A0DD71-5081-59CD-97D7-A5472D8112B9`,
`repin-stable` `01A0DD73-BA1D-511B-8269-13E155442B02`,
`stable-auth-harden` `01A0DD74-95A0-5DD0-AC39-80556FA9A8F0`,
`session-verify` `01A0DD75-A09C-5F98-A879-29F7E03F92C7`,
`stable-e2e` `01A0DD76-5189-548A-A0A9-2D8FBB2E4D29`,
`index-check` `01A0DD76-D0C2-52B4-A2F1-037B7FB07DEC`,
`final-verify` `01A0DD77-7D54-584B-B5D4-1BBA53221DB6`,
`log-leak` `01A0DD78-2D1D-53D6-8064-8CA30510D00A`,
`final-acceptance` `01A0DD79-16CA-5EF0-88E8-335E52BF644A`.

All Cloud Assistant commands were submitted with `KeepCommand=true` under the
tag prefix `api-gateway-0926`; per-invocation scripts and outputs are stored
beside this file as `<name>.sh` / `<name>.output.txt`, with the API responses in
`<name>-run.json` and `<name>-result.json`.

No credential, access key or token appears in any command text, description or
output. All secrets were generated on the host and are used in place there.
