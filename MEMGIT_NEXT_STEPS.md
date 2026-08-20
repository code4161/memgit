# memgit — distribution plan, end to end

Written 2026-08-14 to the owner's question: *"do you have a confirmed idea to bring a
paying customer to memgit-cloud on day 1? It also costs us and conflicts with the VM on
Azure. Plan each end to end, no assumptions, every data should be checked."*

## 0. The direct answer

**No. I do not have a confirmed idea that brings a paying customer on day 1, and I am not
going to present one.** Listing on the MCP registries buys *discoverability*, not a
customer. Nothing measured here predicts a stranger will pay.

What can be said honestly:
- memgit has never been listed where its users actually look, so its **zero paying users
  has never been a demand verdict** — it is an untested hypothesis.
- The cheapest possible test of that hypothesis costs **₹0 and touches no Azure resource**.
- Therefore **no money should be spent on memgit-cloud until that free test returns a
  signal.** That ordering is the plan.

This respects the owner's own binding rule: *"if we build and it is not used, profitable,
we should not build that at all."*

---

## 1. Data checked today — and what could not be

Everything below was read from the live system on 2026-08-14, not from a memory or a doc.

| # | fact | how checked | value |
|---|---|---|---|
| 1 | one subscription shares quant-vm and memgit-cloud | `az account show`, `az resource list` | **Azure for Students** `c439da20-…5837`; `quant-rg` + `rg-memgit-cloud` both in it |
| 2 | credit lot | Billing `lots` API | $100 original, **closed balance $95.03**, `isEstimatedBalance: false`, start 2026-07-01, **expires 2027-07-01** |
| 3 | the $200 sign-up credit | same | **expired 2026-02-22 at $0** — irrelevant |
| 4 | memgit-api scale | `az containerapp show` | **minReplicas 0**, maxReplicas 2, cpu 0.25, mem 0.5Gi |
| 5 | memgit-api image | same | `memgitcloudacr.azurecr.io/memgit-api:v5` — **points at the deleted ACR** |
| 6 | Cosmos tier | `az cosmosdb list` | **free tier = True** |
| 7 | the only surviving image | `ls ~/pb-artifacts` | `memgit-api-v5.tar.gz`, **70,097,435 bytes**, **one copy, one laptop** |
| 8 | memgit on Glama | Glama search | **absent** from **72,234 indexed servers**; `memkit` and `MemGPT MCP Server` are listed |
| 9 | registry metadata in repo | `ls` / `find` | **no `server.json`, no `smithery.yaml`** |
| 10 | can a stdio server list? | official `server.json` reference | **YES** — `packages` (npm/PyPI/…) with `"transport":{"type":"stdio"}`; registry stores metadata only, package must already be on npm |
| 11 | Anthropic Connectors Directory | Claude docs | requires a **remote** server over HTTP (Streamable HTTP/SSE); **local stdio cannot connect directly** |

**Could NOT be verified today, and I am not assuming it:**
- **August's actual daily spend.** The Cost Management query API returned HTTP 429 on six
  consecutive attempts with backoff. So the current credit position is "$95.03 at July
  close, minus ~2 weeks of August burn" — the exact figure is **unknown right now**.
  `azure-credit-lots-api-is-the-only-real-clock` measured ₹37.42/day before the ACR was
  deleted and ₹21.69/day after; both are prior measurements, not today's.
- Whether Azure Container Apps' monthly free grant fully covers a restarted memgit-api.
- Whether Glama/PulseMCP auto-discover memgit once `server.json` exists, or need a manual
  claim.
- **Whether anyone searches for what memgit does.** This is the real unknown and no amount
  of infrastructure work answers it.

---

## 2. The cost conflict, quantified — and it is smaller than it looks

The owner's concern is correct in principle and mostly already resolved in fact.

**What actually cost money was ACR Basic — a *fixed registry fee*, ₹15.726/day (₹478/mo),
71% of the entire subscription's burn.** It is already deleted. That is why burn fell
₹37.42 → ₹21.69/day.

**The service itself is close to free at zero traffic**, because of fact #4 and #6:

| component | cost at zero users |
|---|---|
| Container App compute | **₹0** — `minReplicas: 0`, scales to zero |
| Cosmos DB | **₹0** — free tier |
| Key Vault | ~₹0.076/day — **already paid today**, not marginal |
| ACA managed environment | no base charge on Consumption |
| registry, if moved to **ghcr.io** | **₹0** (vs ₹15.726/day on ACR Basic) |

> **So restarting memgit-cloud on ghcr.io does not re-create the conflict — the conflict
> was the registry, and the registry is gone.** The marginal cost of a restart at zero
> traffic is approximately zero.

**Two honest caveats.** (a) I could not confirm today's burn, so this is arithmetic from
the resource configuration, not from a bill. (b) If the service actually gets traffic the
cost rises — but that is the outcome we want, and 0.25 vCPU / 0.5 GiB at low volume is
cheap. Scale-to-zero also means **cold starts**, which is a real UX cost for an MCP server.

**quant-vm's own position is unchanged either way**: its compute meter reads
`B2ats v2 - Free` (₹0); all its cost is the static IP and disk.

---

## 3. Plan A — free, no Azure, reversible (do this first)

**Goal: find out whether anyone wants this, for ₹0.** The stdio server is eligible for
four of the five push channels; only Anthropic's directory needs a remote server (fact
#11). So we get most of the distribution without spending anything.

**A0 — de-risk the image first. Do this regardless of everything else.**
`memgit-api-v5.tar.gz` is 70 MB on one laptop, ACR tags v1–v4 are gone, and
`api/requirements.txt` pins nothing (`>=` only), so a rebuild will not reproduce v5. This
is the exact shape of the 2026-08-06 loss. **Push it to ghcr.io** (free, and it is where a
restart would pull from anyway). ~15 minutes. This is not part of the bet; it is closing a
single point of failure that has already cost this project once.

**A1 — add registry metadata to the memgit repo.**
- `mcpName` in `package.json` for the npm package (`memgit-mcp`), matching the registry
  name — namespace `io.github.code4161/memgit`.
- `server.json` via `mcp-publisher init`, using a **`packages`** entry (npm, stdio
  transport), *not* `remotes`.
- The registry hosts metadata only and memgit-mcp is **already published on npm at 0.9.0**,
  so nothing needs rebuilding.

**A2 — publish and claim.**
- `mcp-publisher login` (GitHub auth proves the `io.github.code4161` namespace) then publish.
- Records propagate downstream — a Tallyfy server appeared on GitHub's registry **hours**
  after its upstream record went live.
- `smithery mcp publish`.
- Claim the Glama and PulseMCP listings once they index.

**A3 — instrument, so the answer is measurable.** ✅ **BASELINE CAPTURED 2026-08-14, before
any listing** — this is the number the gate is measured against:

| channel | pre-listing baseline | source |
|---|---|---|
| **npm `memgit-mcp`** | **782 downloads / 30 days** (2026-07-15 → 08-14), non-zero on **27 of 31 days** | `api.npmjs.org` |
| **PyPI `memgit`** | **693 / month · 95 / week · 24 / day** | `pypistats.org` |
| VS Code Marketplace | 272 installs (last read 2026-08-07) | prior record |
| GitHub `code4161/memgit` | **0 stars · 0 forks · 0 issues · 0 watchers**, public since 2026-07-01 | `gh api` |

🔴 **This corrects the premise the shutdown was argued on.** memgit is **not** at zero
users — it is at roughly **1,475 installs/month across npm + PyPI** with **zero
engagement and zero payment**. "Nobody uses it" is false; "nobody who uses it converts or
speaks to us" is true. Those are different diagnoses with different fixes, and only the
second is supported by evidence.

### 🔴 The baseline changes what the experiment should be

The gate I first drafted was *"≥50 net new installs"*. Against a measured base of ~1,475
installs/month that threshold is **noise**, and worse, it tests the wrong hypothesis.

Restating the funnel with the numbers actually in hand:

```
   ~1,475 installs / month   (npm 782 + PyPI 693)
            ↓
        0 stars · 0 forks · 0 issues · 0 watchers
            ↓
        0 paying users
```

**Top-of-funnel is not the broken part.** People already find and install memgit at a rate
of roughly fifty a day. Every single downstream step is zero. So adding four more
distribution channels pours more water into a funnel whose bottom is missing — it is
cheap, and it is not the fix, and it must not be sold as one.

The honest reformulation: **we do not know whether the ~1,475 installs/month ever run the
thing twice.** There is no telemetry, the product is local-first by design, and adding
usage tracking to a memory tool is a privacy decision the owner should make deliberately,
not a thing I should slip in.

### The gate — written before the data exists

- **Measurement window: 30 days** from the last listing going live.
- **PASS** requires **both**:
  1. **installs sustain ≥ +25% over the 1,475/month baseline** (a real lift, not the
     daily noise the baseline already shows), **and**
  2. **≥1 unsolicited inbound** — a GitHub issue, star, or message from someone we did not
     contact. *This is the binding one.* At 1,475 installs/month and zero engagement, the
     first genuine sign of a human on the other end is worth more than another thousand
     downloads.
- **FAIL** = memgit-cloud is **not** restarted, and the record shows the constraint is
  conversion rather than discovery — which points at pricing, packaging or the product
  itself, and *not* at more channels.

**Why still do Plan A at all, given the above?** Because it costs ₹0, it is the only step
that is reversible and risk-free, and criterion 2 is genuinely informative: MCP-registry
users arrive through a different door than package-manager users, and they are the
population Anthropic's directory would later expose us to. It is a cheap read on whether
that door has anyone behind it. It is *not* a growth plan.

Cost of Plan A: **₹0**, no Azure resource touched, fully reversible.

---

## 4. Plan B — memgit-cloud restart (gated on Plan A passing)

Do **not** start this now. It is written out so it is ready if A passes.

**Why it would be worth doing:** it is the only route to the Anthropic Connectors
Directory, which is the single best audience match that exists — in-product, in front of
exactly the people who want agent memory.

**B1 — rebuild the registry path.** Push v5 to ghcr.io (done in A0), then repoint the
container app: the current image reference is a **deleted** ACR (fact #5), so the app
cannot start as-is. A new registry also means the
`memgitcloudacrazurecrio-memgitcloudacr` secret must be reset.

**B2 — restore the app.** Pre-shutdown ACA config is committed at
`../cloud/infra/memgit-api-aca-config-2026-08-13.json` (KV references only, no secret
values); steps in `../cloud/infra/RUNBOOK.md` @ `e81eb66`. Keep **minReplicas 0**.

**B3 — verify cost before and after.** Re-run the Cost Management daily query (it 429s
readily — back off and retry) and confirm the delta is what §2 predicts. **If burn rises
above ~₹25/day, stop and re-measure.** The `azure-monthly-allup` (₹1,300/mo) and
`quant-rg-monthly` (₹800/mo) budgets already exist as the backstop.

**B4 — submit to the Connectors Directory** with a public HTTPS endpoint on
`api.memgit.dev` (the managed cert was deliberately kept).

**B5 — billing, last.** The Cashfree blocker is a merchant-entity swap: register a **new
Cashfree account as Individual** (PAN + Aadhaar + bank; no GST needed for domestic INR),
then swap the two Key Vault secrets. 0% PG fees for new businesses until March 2027, T+1
settlement. **This is deliberately last** — `memgit-cloud-billing-august-cash` establishes
billing was never the constraint, and building it before demand exists is the exact mistake
this project has already made.

---

## 5. What would make me wrong

- Plan A passes the gate but nobody converts to paid → the product is wanted and the
  *pricing or packaging* is wrong, not the distribution. Different problem, different fix.
- Plan A fails → demand is genuinely absent at this positioning. Record it, stop, and do
  not restart the cloud. The ₹0 spent is the whole point of sequencing it this way.
- Glama/PulseMCP turn out to need a manual submission that never lands → the push-channel
  premise is weaker than §1 fact #8 implies, and the honest read becomes "we are one of
  72,234, and being listed changes little".

---

## 6. Progress — 2026-08-14

| step | state |
|---|---|
| **A0** image de-risked | ✅ **DONE, by the route that needed no new credentials.** `memgit-api-v5.tar.gz` copied to iCloud Drive `memgit-backup/` with a `RESTORE-memgit-api-v5.txt` beside it. SHA256 of the copy verified identical to the recorded `d354d7f3…d15b3`. The image also loads cleanly (`docker load` → `memgitcloudacr.azurecr.io/memgit-api:v5`). It is no longer single-copy. |
| **A0b** ghcr.io push | ✅ **DONE.** Owner granted `write:packages`. `ghcr.io/code4161/memgit-api:v5` + `:latest` pushed, digest `sha256:7d83f456…8762`, and **pull-verified** after deleting the local copy. ⚠️ The package is **private**, so a restart (Plan B) must configure a registry pull credential on the container app — the image will not pull anonymously. |
| **A3** baseline | ✅ **CAPTURED** — see §3 table. Taken before any listing, so the gate stays interpretable. |
| **A1** metadata | ✅ **DONE, pushed** (`memgit@c7a7370`). `server.json` validates against the official 2025-12-11 schema; `mcpName` added to `npm-wrapper/package.json` and matches exactly. Declares both npm and PyPI install routes over stdio. Nothing published — it only makes publishing possible. |
| **A1b** namespace | ✅ **DECIDED + APPLIED** (`memgit@555a3ef`): **`dev.memgit/memgit`**, the reverse-DNS form of a domain we own. Re-validated against the schema. This commits us to **DNS auth**, not GitHub OAuth. |
| **A1c** DNS keypair | ✅ **GENERATED.** Ed25519 via openssl@3 (the macOS system LibreSSL 3.3.6 cannot do it). Private key in Secret Manager as **`pb-mcp-registry-dns-key`**, read-back verified byte-identical, local copy shredded. |
| **A1d** TXT record | ✅ **LIVE + VERIFIED.** Owner added it by hand. Serving on 1.1.1.1, 8.8.8.8 and Cloudflare's own NS. The published key **derives exactly** from the private key in Secret Manager, and there is **exactly one** `v=MCPv1` record at apex. |
| **A1e** registry auth | ✅ **LOGGED IN.** `mcp-publisher` 1.8.1 installed; `login dns --domain memgit.dev` returned **"✓ Successfully logged in"**. DNS auth works end to end. |
| **A1f** package ownership | ✅ **RESOLVED via the 0.9.1 release.** npm 0.9.1 carries `mcpName`; PyPI 0.9.1 carries the `mcp-name` marker. Both verified against the live registries. |
| **A2** publish | ✅ **PUBLISHED 2026-08-14.** `dev.memgit/memgit` **0.9.1, status active**, both npm and pypi packages listed. Verified by querying the registry, not by trusting the CLI. |
| **A2b** claim downstream | ⏳ **PENDING PROPAGATION** — Glama / PulseMCP / Smithery. Records propagate from the official registry downstream (a Tallyfy server appeared on GitHub's registry within hours). Re-check in 24–48h, then claim. |
| **A2** publish + claim | ⏸ **AWAITING OWNER APPROVAL** — outward-facing and hard to unpublish cleanly. Also gated on A1d. |
| **Plan B** | ⏸ Not started. Gated on A's 30-day gate. |

### ⛔ A1f — publishing needs a 0.9.1 release first

The registry proves you own a referenced package by reading the **published artifact**,
not the repository:

| package | requirement | status today |
|---|---|---|
| npm `memgit-mcp` | `mcpName` field in the published `package.json` | ❌ **absent from 0.9.0** (checked against `registry.npmjs.org`) |
| PyPI `memgit` | `mcp-name: dev.memgit/memgit` in the README, which becomes the PyPI description | ❌ **absent** (checked against the live PyPI JSON) |

Both markers are now **committed** (`memgit@555a3ef`, `@6403c81`) and verified to match
`server.json` exactly — but they only reach the registries on the next release. `server.json`
requires a `packages` *or* `remotes` block, and we have no remote server, so dropping the
packages is not an option.

**Therefore: a 0.9.1 release to npm + PyPI must land before `mcp-publisher publish` can
succeed.** That is an outward-facing release and should go through the `memgit-maintenance`
skill, which covers all six channels and keeps README/docs in sync.

One documented trap already respected: the `mcp-name:` token must be followed by a
newline, whitespace, an HTML tag, or the comment close. Gluing it to a trailing character
(e.g. a sentence-ending period) silently prevents the match. Ours sits inside
`<!-- … -->` on its own line.

### ~~A1d — the TXT record, and the access gap~~ ✅ RESOLVED

**The record to add, exactly** (generated 2026-08-14, matching the private key now in
Secret Manager):

```
name:  memgit.dev          ← the APEX. NOT _mcp-auth.memgit.dev, NOT any selector.
type:  TXT
value: v=MCPv1; k=ed25519; p=yfZC8ovWxRv2+gZX4IrRinF9XbuBySF+1vkI71mM3dY=
```

Two warnings from the registry's own docs, both of which would fail with an unhelpful
generic signature error:
- **Apex placement is mandatory.** MCP DNS auth is SPF-style, not DKIM-style. A record
  under a selector is never read.
- **No stale `v=MCPv1` record may remain** at the apex — a leftover is tried first and
  fails. ✅ Checked: `memgit.dev` apex currently has **no TXT records at all**, so there is
  nothing to clean up.

**Why it is blocked.** `memgit.dev` uses Cloudflare nameservers (`theo`/`ulla.ns.cloudflare.com`)
but is **not in the Cloudflare account our stored token reaches**. That token
(`pb-cloudflare-api-token`) sees exactly one zone, `harisankar.online`, and a direct
`?name=memgit.dev` lookup returns **zero** zones. So memgit.dev sits under a different
Cloudflare login.

**Either resolves it:**
1. Store a token from the account that holds memgit.dev (Zone → DNS → Edit on that zone),
   e.g. as `pb-cloudflare-api-token-memgit`, and the record can be created via API; or
2. Add the record by hand in that account's dashboard — it is one TXT record.

Then: `dig +short TXT memgit.dev` should return the value, and login is
`mcp-publisher login dns --domain memgit.dev --private-key <hex from the stored key>`.
`mcp-publisher` is **not yet installed** locally.

### The decision already made

**Namespace: `dev.memgit/memgit`** — chosen by the owner 2026-08-14 and applied. Taken
before publishing deliberately, because the registry treats a name change as a *separate*
server entry rather than a rename.

## 7. Immediate next actions

1. ~~Ship 0.9.1~~ ✅ done. ~~`mcp-publisher publish`~~ ✅ done — **memgit is listed**.
2. **In 24–48h:** re-check Glama and PulseMCP for the auto-crawled entry and claim it;
   run `smithery mcp publish` for the fourth surface.
3. **Two channels are behind and were not fixed by this release:**
   - **Chocolatey still serves 0.1.2.** The workflow reported success and the public feed
     did not advance — the long-standing moderation gap, now confirmed again at 0.9.1.
   - **VS Code Marketplace was not published.** The repo manifest is bumped to 0.9.1 but
     no `vsce publish` ran; it needs a marketplace PAT that does not exist locally.
4. **The 30-day gate starts now.** Re-read the §3 baseline against it — and remember it
   turns on **one unsolicited inbound**, not install counts.
4. Wait 30 days. Read the gate — remembering it now turns on **conversion**, not installs.
   **Only then** consider Plan B.

---

## 10. Is "day 1" reached? — measured 2026-08-14, ~30 min after publishing

**No, and it is not yet answerable.** npm and PyPI download statistics lag roughly a day,
so no same-day read exists. The gate in §3 is a 30-day question by construction.

What *was* checkable is whether the listing is **discoverable** rather than merely present.
It is not.

### 🔴 The registry's search matches NAME ONLY

| query | results | memgit |
|---|---:|---|
| `memory` | 100 | ❌ not present |
| `context` | 100 | ❌ not present |
| `knowledge` | — | ❌ |
| `agent memory` / `persistent memory` | 0 | ❌ (multi-word returns nothing) |
| `git` | 100 | ⚠️ rank **53** |
| `memgit` | 1 | ✅ (exact name) |

Proof it is name-only, not weak ranking: every word that appears **only in our
description** returns nothing — `sessions` 0, `persists` 0, `searchable` 0 — while
`version` returns 11 servers that all carry *version* in their **name**. Results also come
back in **name order** with a cursor, not by relevance.

Our description contains *memory, context, version-controlled, searchable, persists*. None
of them can surface us. **The only query that finds memgit is the word "memgit", which
requires already knowing the product.**

### What follows

1. **Upstream discoverability is decided entirely by the NAME.** For any future MCP server,
   put the words users search into the name — the description does no work here.
2. **The name is now expensive to change.** A name change creates a *separate* registry
   entry, not a rename. `dev.memgit/memgit` is effectively fixed.
3. **A second, more searchable entry under `dev.memgit/*` is technically possible** — the
   namespace is ours. But near-duplicate listings can read as spam, so this is an **owner
   decision**, not something to do unilaterally.
4. **This may cost less than it appears, and that is unverified.** The official registry is
   the *feed*, not the storefront. Real browsing happens on mcp.so (20,222 servers), Glama
   (72,234), PulseMCP and Smithery, which run their own search and may index descriptions.
   Our record propagates there with full metadata. **Do not assume it away — check once we
   are actually indexed.**

### The honest status of the day-1 goal

The mechanism is in place and verified working; its *reach* is worse than expected and the
decisive test has not run. Re-check at 24–48h: whether Glama/PulseMCP have indexed us, and
crucially **whether their search surfaces us for "memory"**. That answers whether the
name-only limitation is confined to the upstream feed or follows us downstream — and it is
the difference between a listing that works and one that is merely live.
