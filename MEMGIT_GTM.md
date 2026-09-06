# memgit Pro — the complete pipeline, from install to a rupee in the bank

Written 2026-09-03. Owner: *"proceed to build on the idea that has the most edge, we need
results, need to think along complete pipeline, memgit paid tier or the cloud, which we
already have, but has no marketing or plan to sell."*

Gate run 2 (`../../PASSIVE_ENGINES.md` §13) put memgit as the only BUILD across 27 venues.
This document is the whole pipeline for that build — every stage, who does it, what it
costs, and **what receipt proves the stage happened**. Nothing here is a forecast; where a
number is a guess it says so.

## 0. The decision: sell ONE thing, through ONE rail

| question | answer | why |
|---|---|---|
| Paid tier or cloud? | **Both are the same product.** "memgit Pro" = a licence key that unlocks hosted E2E sync (the cloud). | The market gates exactly this (§2); the cloud is built; a key needs no hosting to validate. |
| Which rail? | **Polar** (merchant of record). Cashfree path retired. | Polar lists 🇮🇳 India for individuals (polar.sh/docs/merchant-of-record/supported-countries, 09-03), bills subscriptions in USD, handles global tax, issues licence keys per purchase. Cashfree was INR-first, one-time orders, and its wired credentials belong to a company account that violates its T&C. |
| Price? | **$12/month · $99/year** | §2. The retired card was $8/₹399; the solo local-first-with-sync band is $9–$30 (Squish 9 · Hjarni 12 · Basic Memory 15 · Mem0/Supermemory 19 · Letta 20 · CMEM 30). $12 sits at the low-mid mode. INR presentment is Polar's, not ours — do not promise ₹ prices. |
| What is gated? | Hosted sync only. The local engine, store, MCP server and every command stay MIT. | The one gate every local-first competitor chose; also the only gate a server can enforce. |
| What leaves the machine? | The key and the public organisation id, to Polar's validate endpoint. Never memory content. | Stated in README, `pro --help`, and the module docstring. |

## 1. The pipeline, stage by stage

| # | stage | who | cost | state 2026-09-03 | receipt that proves it |
|---|---|---|---|---|---|
| 1 | **Discovery** — registries, package managers, README | done | ₹0 | listed on the official MCP registry (`dev.memgit/memgit` 0.9.1); Glama/PulseMCP/Smithery claims pending | npm 778/30d (09-03, `api.npmjs.org`), PyPI 792/30d (09-03, pypistats), GitHub 0★ |
| 2 | **Install** | users | — | ~1,570/month across npm+PyPI | same |
| 3 | **Activation** — first `resume`, hooks, token savings | product | — | shipped (0.4–0.9) | no telemetry by design; `memgit stats` is the user's own receipt |
| 4 | **Upgrade trigger** — second machine / team / "sync this" | product + README | — | README "memgit Pro" section + `memgit pro` commands (this commit) | user runs `memgit pro status` → sees Free + the pricing URL |
| 5 | **Checkout** — Polar checkout link | OWNER | ₹0 to create | ⛔ **not created** — needs a Polar org (KYC) | a live `buy.polar.sh/...` URL that returns a checkout page |
| 6 | **Key delivery** — Polar emails the key + purchases page | Polar | — | automatic once the product carries a licence-key benefit | a test purchase's email |
| 7 | **Local entitlement** — `memgit pro activate <key>` | product | — | ✅ built + tested (`memgit/license.py`, 28 tests) | `memgit pro status --json` → `entitled: true` |
| 8 | **Hosted entitlement** — key unlocks api.memgit.dev | product | — | ✅ built + tested (`cloud/api/app/routes_polar.py`, 11 tests); ⛔ **not deployed** — the running image is v5 and predates this route | `POST /v1/billing/polar/activate` → `{"plan":"pro"}` on the live host |
| 9 | **Money lands** — Polar → Stripe Connect Express → Indian bank | Polar | 5% + 50¢ (+1.5% intl card, +0.5% subscription), $2/month active payout + 0.25%+25¢/payout | ⛔ needs the org (stage 5) | a payout line in the Polar dashboard, then the bank statement |
| 10 | **Retention** — subscription renews, key stays granted; cancel → `subscription.revoked` webhook ends hosted entitlement; local grace 14 days | product + Polar | — | ✅ webhook route built + tested | Polar dashboard MRR / churn |
| 11 | **Measurement** — the only receipts that matter | owner reads Polar | — | — | checkouts started · paid · MRR · refunds (Polar dashboard); installs (npm/PyPI) |

Stages 1–4, 7, 8, 10 are done in code. **The pipeline is blocked at stage 5, which only the
owner can do (identity KYC).** Everything after it is mechanical.

## 2. Pricing evidence (vendor pages read 2026-09-03)

| product | model | paid gate | price |
|---|---|---|---|
| claude-mem / CMEM Pro (93k★) | local-first SQLite, opt-in cloud | automatic cloud sync, one private MCP link across machines | **$30/mo** |
| Basic Memory (3.8k★) | local-first Markdown, AGPL | cloud sync per seat | **$15/mo** (beta) → $19 |
| Squish | local MIT + cloud | multi-device sync, team workspaces | **$9 / $29 / $99** |
| Hjarni | hosted notes + MCP | unlimited notes, shared folders | **$12/mo · $120/yr** |
| Mem0 Platform (64.6k★) | cloud | volume; Pro adds graph memory | $19 / $249 |
| Supermemory (29.2k★) | cloud-first | usage + connectors | $19 / $100 / $399 |
| Letta | cloud + OSS | agents, seats | $20 / $20 per seat |
| Zep (Graphiti 30.5k★) | cloud only | credits + MCP seats | $125 / $375 |
| memkit · LangMem | local OSS | none | $0 — no paid tier |

Of 13 memory MCP servers surveyed by mnemoverse.com/docs (2026-08-08), 7 have no paid tier;
**every local-first one that charges gates sync/seats, never the local engine.** One MCP
vendor reports ~8% free→paid at $19/mo (dev.to/whoffagents, 2026-04-19, no customer count).

Applied to memgit's base: 1,570 installs/month × an assumed 1% paid (the product's own
§7.0 assumption; unmeasured) × $12 ≈ **$190/month ≈ ₹16k** gross before Polar's ~7%. At the
8% one vendor reports it would be ~₹1.3L/month. **Neither number is a forecast. The 30-day
read (§5) is the first measurement this project will ever have of trial→paid.**

## 3. What was built today (staged, owner pushes)

**core (`code4161/memgit`)**
- `memgit/license.py` — Polar validation via `POST /v1/customer-portal/license-keys/validate`
  (customer-portal endpoint: no org token needed, so nothing secret ships in an MIT client);
  cache at `~/.memgit/license.json` (0600); fail-open 14-day grace; 24-hour recheck; key
  never echoed beyond the last 4 characters; `MEMGIT_LICENSE_KEY` for headless MCP hosts,
  never written to disk; `urllib` only, no new dependency.
- `memgit pro activate | status [--json] [--offline] | deactivate` in `cli.py`; `activate`
  also upgrades a logged-in cloud account, best-effort.
- `tests/test_license.py` — 28 tests; full suite **459 passed**.
- README "memgit Pro" section + commands block; CHANGELOG `[Unreleased]`.

**cloud (`code4161/memgit-cloud`, branch master)**
- `api/app/routes_polar.py` — `POST /v1/billing/polar/activate` (validates server-side,
  opens/extends a `provider="polar"` subscription; period end = key `expires_at` or a
  35-day rolling window), `POST /v1/billing/polar/webhook` (Standard Webhooks HMAC over
  `id.timestamp.body`, signed with the full `whsec_…` secret per Polar's docs, ±5 min
  tolerance, idempotent via `webhook_events`; `subscription.revoked` /
  `benefit_grant.revoked` / `order.refunded` end entitlement).
- `entitlement.py` re-checks polar-backed periods lazily; `config.py` gains
  `POLAR_API`, `POLAR_ORGANIZATION_ID`, `POLAR_WEBHOOK_SECRET`, `POLAR_CHECKOUT_URL`;
  `/v1/billing/status` returns `provider` and `polar_checkout_url`.
- `api/tests/test_polar.py` — 11 tests; suite **25 passed**.

**website (`code4161/memgit-website`)**
- `Pricing.tsx`: Pro at $12/mo · $99/yr, CTA = `NEXT_PUBLIC_POLAR_CHECKOUT_URL` with a
  fallback to `/docs#memgit-pro` so a missing env var never renders a dead button (the old
  card linked to app.memgit.dev, whose API 404s — a dead CTA on the pricing page since 08-13).

## 4. The owner's runbook — in order, ~2 hours, ₹0

> 🔴 **ORDERING CORRECTED 2026-09-03 (evening).** The list below originally put the cloud
> restart at step 7, after the release. That is wrong and it is the one ordering mistake
> that could cost money: **memgit Pro sells hosted sync, and `api.memgit.dev` returns 404**
> (re-verified 09-03). A subscription bought before the cloud is up delivers nothing —
> a refund and a chargeback, against Polar's 0.4% chargeback threshold. And the restart
> needs a **v6** image: the preserved v5 predates `routes_polar.py`, so the activation
> endpoint would 404 on the live host.
> **Hard gate: the cloud serves before the checkout link is public.** Polar's own review
> may demand a video of the unpaid→paid flow "including how the product is automatically
> accessible after purchase", which is impossible while the API is down. Steps 1–4 below
> are safe to do in any order; **step 7 must complete before step 5's link is published.**


1. ✅ **Polar org — ONBOARDED AND APPROVED 2026-09-06.** Org `memgit`
   `1267be9a-acd0-4cdb-a3e4-0ee41134e87e`, created 09-03, account details submitted
   2026-09-06 08:29Z. API now reports `status: active`, `payout_account_id`
   `9fb6641b-f744-4305-a20a-e0979328ba8c`, and **all four money capabilities true**:
   `checkout_payments`, `subscription_renewals`, `payouts`, `refunds`. Approval came the
   same day, not the "up to 14 days" the docs warn about. **The store can now charge.**
2. ✅ **Products — created 2026-09-06 via the API.** Polar puts `recurring_interval` on the
   PRODUCT, not the price, so "one product with two prices" is not expressible: it is two
   products, both carrying the same licence-key benefit.
   - `memgit Pro` monthly $12 — `c2e29029-9297-4c78-af00-727089474d1b`
   - `memgit Pro (Annual)` yearly $99 — `5bbc8cbe-3843-4c5e-abb6-dc95893e2dd4`
   - benefit `license_keys` "memgit Pro licence key", prefix `MEMGIT`, no activation limit,
     no expiry (expiry follows the subscription) — `fa5578ef-fa00-45ba-9c64-cab331886cd6`
   ⚠️ Attaching a benefit is `POST /v1/products/{id}/benefits`. `PATCH /v1/products/{id}`
   with a `benefits` array returns **200 and silently ignores it** — `ProductUpdate` has no
   such field. Verify by re-reading the product.
3. ✅ **Checkout link — created 2026-09-06**, both products on one link,
   `https://buy.polar.sh/polar_cl_Hgl7dApmlGskDhIFb3yot0XvPtd9ZzdQCJcFO0wQkXO`, success URL
   `https://memgit.dev/docs#memgit-pro`. It renders (HTTP 200) but **cannot take a payment
   until step 1 clears.**
4. ✅ **Secrets — all three written 2026-09-06** via `secrets-ops/add-secret.sh --stdin`:
   `pb-polar-org-id`, `pb-polar-checkout-url`, `pb-polar-webhook-secret`. The webhook
   endpoint is live at `https://api.memgit.dev/v1/billing/polar/webhook` (id
   `8a1df5b2-2ca0-4089-82b7-2e4d524e6d70`, format `raw`) subscribing the eleven
   `subscription.*` / `order.*` / `benefit_grant.*` events the cloud reads.
   ⚠️ The API token is an **organisation** token, so every create body must OMIT
   `organization_id` — sending it is a 422. And Polar's edge rejects Python `urllib`
   (Cloudflare 1010); drive the API through `curl`.
5. **Website:** Vercel → `NEXT_PUBLIC_POLAR_CHECKOUT_URL` = the link → `vercel --prod` from
   `website/`. Receipt: the Pro button opens Polar checkout.
6. **Ship the client:** release memgit **0.10.0** through the `memgit-maintenance` skill
   (tag push publishes PyPI/npm/choco; brew/vsce/plugin manual). ✅ The org id is already
   baked as the `MEMGIT_POLAR_ORG_ID` default in `license.py` (staged 2026-09-06, 459 tests
   green), so the prerequisite is met; the tag itself is the owner's to push.
   Receipt: `pipx install memgit==0.10.0 && memgit pro status` prints Free + URL.
7. **Restart the cloud on a v6 image** (Plan B in MEMGIT_NEXT_STEPS.md §4, unchanged
   mechanics): build `api/` → push `ghcr.io/code4161/memgit-api:v6` → set ACA env
   `POLAR_ORGANIZATION_ID`, `POLAR_WEBHOOK_SECRET`, `POLAR_CHECKOUT_URL` from Key Vault →
   registry pull credential (the ghcr package is private) → `minReplicas 0`. Cost at zero
   traffic ≈ ₹0 (the ACR line that cost money is gone). Receipt: `curl api.memgit.dev/healthz`
   returns `version` ≠ 0.1.0-v5, and a test purchase's key activates end to end.
8. **Test purchase** with a real card, then refund it in Polar. Receipt: email with key →
   `memgit pro activate` → `memgit cloud push` succeeds after the trial is expired.

## 5. Distribution — bounded, and the two halves kept apart

**PUSH (₹0, agent):** claim Glama and PulseMCP listings; `smithery mcp publish`; add
`.github/FUNDING.yml` (GitHub Sponsors is India-eligible; expect ₹0).

**PULL (owner labour, bounded to five posts, then stop):** the product page now has a
price and a button; launch posts without one were the 08-14 mistake in reverse.
1. Show HN: *"memgit – git for AI memory (Claude Code/Cursor MCP), now with paid sync"* —
   lead with the measured token-savings proof from `memgit stats`, not the price.
2. r/ClaudeAI, r/cursor, r/LocalLLaMA — one post each, the same proof.
3. One X thread. Link the pricing page, not the repo, in every post.
Timing: only after stages 5–7 are live. A post that lands on a dead button is a receipt of
nothing.

**In-product (owner decision, not done):** a one-line, once-per-30-days hint in the *human*
`memgit resume` output ("Sync this store across machines: memgit pro"). It is the only
surface the 1,570 monthly installs actually see. Deliberately NOT added to the MCP digest —
marketing inside an AI's context is a product defect. Say yes or no.

## 6. The 30-day read and the kill rule

Window starts the day the checkout link is live. Receipts come from Polar's dashboard;
nothing else is trusted.

| outcome | reading | next |
|---|---|---|
| ≥1 paid subscription | the funnel closes; the first measured conversion in the product's life | scale PUSH; write the case study memory; consider the in-product hint |
| 0 paid, ≥100 checkout views | price or packaging is wrong, not distribution | one change only: $9/mo or a 7-day trial — never both |
| 0 paid, <100 views, installs flat | distribution — the pricing page is not being reached | in-product hint (owner consent), then one more PULL round |
| 0 paid at 60 days | record it as the demand verdict this project has never had; stop spending hours; keep the code (it costs nothing) | — |

## 7. What is not done, honestly

- No Polar org, product, link, or webhook exists. Stage 5 is the owner's.
- The cloud is still off and the running image cannot serve the new route. A v6 build is
  required; `api/requirements.txt` still pins nothing (`>=` only) — pin before building.
- INR pricing is not offered (Polar presents USD; local-currency display is Polar's feature,
  unverified for INR). The old ₹399 card is gone from the site.
- The cloud web app's `/billing` page still shows the Cashfree flow. It works but is now the
  wrong door; the CLI path is the primary one. Replacing that page is a follow-up.
- `MEMGIT_POLAR_ORG_ID` default is empty until the org exists; `pro activate` reports
  "not configured in this build" rather than failing silently.
- No telemetry was added. Conversion is measured at Polar, installs at the registries; the
  gap between them is the number this document exists to obtain.
