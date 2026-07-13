# memgit — End-to-End Validation Report

**Date:** 2026-07-13  **Versions audited:** 0.4.1 + 0.5.0 → fixes + improvements shipped as **0.6.0**
**Method:** three independent audits — (1) usage forensics over 289 real interactive Claude Code sessions across 13 projects (Jul 7–13, post-0.4.0-hooks), (2) validation of every 0.4.1/0.5.0 feature on the live machine, (3) structured feedback from an AI operator asked *why it never used memgit unprompted* — plus functional E2E of all 0.6.0 changes against a production-store copy, a fresh store, and the live machine.

> Previous report (0.4.0, 2026-07-07) is superseded. Its "160/160 tests" grew to **245/245** here.

---

## The core finding: passive recall works so well the active layer is never used

0.4.0 fixed *delivery* — hooks inject the resume digest and per-prompt recall reliably. This window measured what happened next:

| Measured across 289 real sessions (Jul 7–13) | Result |
|---|---|
| Sessions with `<memgit-recall>` injection delivered | ~59% (176) |
| Sessions that called ANY memgit MCP tool | 15% (43) — up from 6% pre-0.4.0, but concentrated in 2 of 13 projects |
| **Recall-injected sessions followed by an active `search_memories`** | **6.8% (12/176)** |
| `resume_session` / `list_memories` calls, ever | 1 each |
| Stop capture-guard fired | 27 sessions |
| Store growth in window | 230 checkpoints (65% of all-time); Jul 7–10 = 100% passive auto-sync, Jul 11–12 = 66 explicit saves |
| Usage ledger (0.5.0) | 197 memories tracked, 534 hits — bimodal: 51% read exactly once |

An AI operator, asked directly why it never queried memgit until told to, named the mechanism: **"the better your passive recall gets, the less an agent thinks to actively query — I treated the injected sample as the memory rather than as a teaser of a queryable store."** When forced to search, per-task queries surfaced depth passive recall never showed (a do-not-push warning, exact version state). Its asks: advertise depth with counts, make live state a first-class kind, make supersession structural, cut first-call friction, trigger recall from file reads, and state that memgit — not files — is the authority for entity status.

## 0.4.1 / 0.5.0 feature validation (live machine)

| Feature | Verdict |
|---|---|
| `delete`/`rm`/`del` aliases + did-you-mean (0.4.1) | **PASS** — verified live |
| Usage ledger + accumulation loop (0.5.0) | **PASS** — 19.5 KB, live counts, decay working |
| Core operating guide (0.5.0 flagship) | **UNUSED** — zero `co` memories on any of 13 projects, `core seed`/`sync` never run, no host rule files anywhere. Root cause: the seed nudge lived only in MCP server instructions — the one surface no session acts on; the resume digest (the surface every session reads) said nothing |
| `co` type filterable | **FAIL (bug)** — `list --type co` / `search --type co` rejected the type; only `add`'s enum was updated in 0.5.0. openapi.json/llm-tool-definitions.json enums were still six-valued from 0.1.0 |
| Docs | README ok; website had zero mention of `memgit core` |

## What 0.6.0 changes (all shipped + verified)

**Thesis: the passive layer must advertise what the active layer knows.**

- **Supersession** — `supersedes` (+`related`) now writable via MCP/CLI/HTTP; superseded memories hidden from search/recall/resume/auto-promotion (escape hatches everywhere); `list` marks them `⊘superseded-by:<head>`; `get_memory` on a retired link returns `superseded_by` + `head`. Derived (no tombstones): removing the superseder resurrects. Cycles rejected at write; unknown targets kept with warning. Model fields + TOON `~SUP`/`~REL` existed since 0.1.0 with no write path — 0.6.0 wired them; existing SHAs untouched (regression-tested).
- **Trackers (`tr`) + status board** — live entity state, slug `<entity>-status`, updated by same-slug re-save; renders at the top of every resume under "memgit is authoritative; files may lag" with an `upd MM-DD` freshness stamp. Cap 8; never promoted into static rule files.
- **Memory index** — resume ends with truthful tag→count depth pairs + the exact query (`search_memories("<topic>", top_k=10)`). Superseded excluded from counts; project-label-derived junk tags excluded (found live: `business (76) · personal (75)` would have dominated).
- **"+N more" recall hint** — the `<memgit-recall>` block advertises on-topic depth behind the injected top-3 (live: `+39 more saved on 'dynamo'`). Hinted-not-shown slugs stay unmarked.
- **Context-triggered recall** — PostToolUse hook on `Read|Grep|Glob`: file paths matching a memory tag (≥3 memories) inject a one-line hint. Reads only a commit-time `tagmap.json` (never loads the store; lazy-built once on pre-0.6.0 stores); measured 0.05 s; per-tag session dedup shared with prompt-recall; hard cap 3/session.
- **Core-guide activation** — the seed nudge now lives in the resume digest (fires when a project has ≥10 memories and no guide); frontmatter parser handles YAML `>` block scalars (found live on `upwork-proposals`). Personal-business seeded + synced → `.claude/rules/memgit.md`, `.cursor/rules/memgit.mdc`, `.gemini/memgit.md`.
- **Authority framing** — server instructions, tool descriptions, stop-guard, onboard brief, and the seeded guide all state: memgit is the authority for entity status; corrections use `supersedes`, never "CORRECTED:" prefixes.
- **Hygiene** — `co`/`tr` in every enum, graph color/legend, stats labels, markdown exporter, openapi.json, llm-tool-definitions.json; HTTP PUT accepts `body`; website docs updated (co + tr + supersession).

## Verification

- **245/245 unit tests** (200 existing + 45 new: supersession graph/write/suppression, trackers, entity index, depth hints, ctx-recall incl. session cap, core nudge, token budget — new sections cost ≤250 tokens marginal, digest ≤900 tokens on a 200-memory store)
- **Production-store copy:** fsck clean before/after; tracker + superseding save verified; suppression confirmed in search (`--include-superseded` restores), resume pools, and list annotation
- **Fresh store:** full CLI matrix incl. `--supersedes` (unknown-slug warning), `--type tr`, status board render
- **Live machine:** 5-hook set installed (`PostToolUse` matcher `Read|Grep|Glob`); real digest leads with the seeded core guide, ends with a clean memory index (`crypto (14) · instagram (10) · trading (10) …`); ctx-recall fires on `trading/VM_RUNBOOK.md` → "10 memories tagged 'trading'"

## Baseline to re-measure (~Jul 20)

**Passive→active conversion was 6.8% (12/176) in the Jul 7–13 window.** The depth hints + memory index + ctx-recall exist to move exactly this number. If it stays <15% after a week of real sessions, the next lever is richer context triggers (per the deferred design), not more injection.

## Known gaps (deliberate, tracked for 0.7)

- Supersession chains are per-slug relations; there is no bulk "supersede everything on topic X"
- The entity index derives from tags only — untagged stores get no index (correct but silent); consider a nudge when a project's tag coverage is near zero
- `sync` still never prunes memories whose markdown source was deleted (`--prune`, carried from 0.4.0 report)
- Project labels remain path-based, not git-aware (carried from 0.4.0 report)
- Website deploy for the docs update is owner-tracked (separate repo)
