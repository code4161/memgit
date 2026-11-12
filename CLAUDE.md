# memgit core — operating guide

Git for AI memory: Python CLI + MCP server + hooks + VS Code extension
(repo `code4161/memgit`, public). The live store on this machine is
`~/.claude/memgit-store/`; the installed tool runs from the system Python 3.13
site-packages — **this checkout is not the live tool**.

## Rules

- **Release via the `memgit-maintenance` skill** — tag push auto-publishes PyPI/npm/choco;
  brew tap, `vsce publish` and the Claude plugin are manual, and README/docs must move in
  the same release. The 2026-08-05 audit traced nearly every live defect to ONE unreleased
  commit: a merged feature is dead until released and installed.
- **Autonomy is a design constraint** (`memgit-autonomous-durability`): a maintenance task
  requiring a human command will never happen. Backup is automatic end-of-session; memgit
  never invents a git remote.
- **MCP registry search matches NAME ONLY** (`mcp-registry-search-is-name-only…`) — naming
  decisions are distribution decisions and effectively permanent.
- Dogfooding findings become memories (project `Personal-business`) AND GitHub issues —
  the store this tool manages is also its best test fixture.
- Pricing/billing decisions: `memgit-cloud-billing-august-cash` + MEMGIT_NEXT_STEPS
  gates. No money on memgit-cloud until the free test converts.

Doc: [MEMGIT_NEXT_STEPS.md](MEMGIT_NEXT_STEPS.md). Group map: [../CLAUDE.md](../CLAUDE.md).

## 🔴 CORE RULE — no conflicting or stale memory (workspace-wide, 2026-08-31)

`save_memory` is not append-only in effect: a stale memory competes with its own
correction and can OUTRANK it in search. Before every save — `search_memories` on the
QUANTITY, and if an existing memory states a different value, **re-save that one or pass
`supersedes`**. Correct the `rule` line, not just the body (search and digests render the
rule). If a correction inverts a finding, the **slug** changes too. `lx` lessons carry no
operational directives ("do not arm") — those expire with state, and state lives in the
`tr` tracker. `save_memory` on an existing slug REPLACES: always resend the full body.
Close the loop — re-search what you wrote and read the top hit.

Full doctrine: [root CLAUDE.md §1a](../../CLAUDE.md).

<!-- MEMGIT:BEGIN -->
<!-- memgit-managed core operating guide — auto-generated navigation aid. If this conflicts with this repo's own CLAUDE.md / AGENTS.md / rules, THOSE win — this is not policy. Regenerate with `memgit core sync`; edit the source with `memgit core edit`. Safe to delete. -->

# Core operating guide

How to work in this project. Prefer these over guessing; defer to the repo's own rules where they differ.

## 🔴 STRICT — THE SYSTEM RUNS ITSELF (added 2026-09-07, owner directive: "the core rule, the system should be completely automatic")
- **A step that needs a person is a DEFECT, and the defect is the step, not the person.** This was an AlphaNova directive on 2026-09-06 ("the system should be autonomous, please take decisions yourself... the system should do this automatically", then "nothing should need or depen on this mac, it should be completely automtic") and again on 2026-09-07 ("Completely run on vm, the system should be 100% autonomus"). It is now THE CORE RULE and it applies to every engine here, not to AlphaNova alone.
- **Decide. Do not hand the decision back.** A session that ends on "the one decision: nothing has been submitted" has failed; two in a row is what produced this rule. Report what you DECIDED and why — never ask for a go-ahead the evidence already settles.
- **A measurement that only exists when someone runs it is true for one afternoon.** Wire it into the loop that already runs (`improve/` check, a workflow step, a timer) in the SAME session that first computed it. Measured 2026-09-07: `expected_score.py` was computed by hand, found the datacrunch family narrower than noise, and would have been a one-day fact; it is now a check and a daily job step.
- **Where it runs: a VM or CI. Never the Mac, never a command someone types.** `[[nothing-of-ours-is-scheduled-on-the-mac]]` — one granted exception, `com.hari.youtube-drain`, and a second local schedule needs its own ping.
- **A rule is not a mechanism.** "We will remember to" does not survive the session that wrote it. `MAX_MINTS_PER_DAY = 20` against a vendor cap of 150 is a mechanism; "we read the docs" is not. If the thing you are about to write down can be a constant, a gate or a check, write that instead.
- **The repair channel sits UPSTREAM of every guard that can refuse.** A guard evaluated before the thing that fixes it cannot be fixed by the system itself, and it fails silently while looking armed — `[[a-self-healing-job-must-fetch-its-own-repair-before-any-guard-can-refuse-it]]`: twelve hours dead on the one engine whose whole point is to need nobody, recovered by a human at a laptop.
- **Every unattended pass REPORTS, including the quiet ones**, to /admin/health. Absence of an error is not success; assert the work happened.
- ⚠️ **AUTONOMY IS NOT A LICENCE TO PROMISE AN OUTCOME.** It authorises spending a slot, a run or a quota and choosing a candidate. It does NOT authorise a gate whose pass condition names a leaderboard position or a return — that is a confident rail on an uncalibrated ruler (`[[a-rail-must-not-judge-on-a-ruler-measured-not-to-transfer]]`). Optimise, and REPORT against the live bar.
- ⚠️ **Landing code stopped being the human step on 2026-09-11** — the agent lands its own work, so a new loop no longer waits on a person. What is still human: a tag or release, a rail change, and anything a permission classifier refuses.
- Full case: `[[the-system-runs-itself-is-the-core-rule-not-an-alphanova-one]]`.

## 🔴 STRICT — an agent LANDS ITS OWN WORK (owner directive 2026-09-11)
- **Fix it, verify it, land it, same session** — `ops/push-repo.sh "<repo-dir>" "<msg>"`, once per subrepo, and read its output. Do not leave work staged for someone else to push.
- ⚠️ **This SUPERSEDES "an agent STAGES, the owner PUSHES" (2026-09-02).** Owner's words: *"proceed and run the commands, please remove the rule of me running commands."* The 2026-08-06 wipe lesson is unchanged — work must never live only in a session's head — and the 2026-09-02 answer to it (stage and wait) is withdrawn in favour of landing it.
- **The script carries what the person used to carry.** push-repo.sh reads the remote branch, refuses unstaged files, refuses a secret shape, commits, rebases onto that branch, pushes by name and asserts HEAD == origin. Never hand-type a git chain in its place: on 2026-09-09 three hand-typed chains failed in one evening (rebase before commit; `HEAD:main` on a `master` repo; one unexplained). RUNBOOK §32.
- 🔴 **The judgement the old rule reserved for a person is now YOURS.** The gap that rule named was **a conflict resolved by taking the older side**, and no script catches that. Know which commit you are on before you read anything: `git rev-parse --abbrev-ref HEAD && git fetch -q origin && git log --oneline -1 origin/main`. This repo has long-lived working branches — `automation/` sat on `session-work`, forked before 2026-09-02, still carrying three rails retired *after they cost real money*. Reading a retired branch as if it were live is the frame failure §1 describes.
- ⛔ **Three things stay the owner's:** a **tag or release** that publishes to the world, a **rail change** (floors, kill switches, caps — that consent requirement is untouched), and anything a **permission classifier refuses**. Never route around a refusal by wrapping the refused command in a script.
- History: `[[an-agent-stages-the-owner-pushes]]` records the superseded rule and why it existed.

## 🔴 STRICT — memgit is the FIRST read, before ANY file (added 2026-08-28, owner directive)
- **The first tool call of every task is `search_memories`.** Not before *answering* — before **reading**. No `Read`, no `cat`/`grep`/`sed`/`head`, no CLAUDE.md, no `*_NEXT_STEPS.md`, no source, until memgit has been searched on the task. Only `resume_session` and the session digest may precede it.
- It is an **ORDER** rule, not an effort rule, and not a judgement call. No task is "too small". One call is the whole cost.
- The sequence, every task: `search_memories(task)` → `search_memories(the VARIABLE being measured)` → `get_memory("<entity>-status")` for each entity touched → *only now* open files, and read them as claims to be checked, not as findings.
- **Why the order:** whatever you read first becomes the frame you judge everything else in. A doc asserts; memgit corrects. Read the doc first and you inherit a settled story, then spend the session confirming it.
- ⚠️ **memgit-first is not memgit-trusted.** A tracker is a record; the box is the fact. The source-of-truth table (CLAUDE.md §2) still outranks memgit for live state. When memgit and the box disagree, that disagreement IS the finding — report it and fix the tracker the same session.
- Full case: `[[memgit-first-before-any-file-the-frame-you-read-first-wins]]`.

## 🔴 STRICT — NO CONFLICTING OR STALE MEMORY (added 2026-08-31, owner directive)
- **A memory that contradicts another is worse than no memory.** `save_memory` is not append-only in effect: a stale memory COMPETES with its own correction and can OUTRANK it. Measured 2026-08-31 — a corrected figure (`+0.0809 R, t +2.20`, disproved hours earlier as `+0.0526 R, t +1.54`) was still returned FIRST by search, from a memory written the same session. Nothing was missing; the store confidently served a retracted number.
- **Before every save:** `search_memories` on the QUANTITY, not just the topic. If an existing memory states a different value for the same thing, **re-save that memory with the correction, or pass `supersedes`.** Adding a second memory and leaving the first IS the defect.
- **Correct the `rule` line, not only the body.** Search ranking, the session digest and the status board all render `rule`. A body-only fix leaves the wrong claim in every listing.
- **A slug is a claim.** If a correction inverts the finding, the SLUG changes too — new slug + `supersedes`. A slug reading `…-cannot-be-measured` whose body says the opposite is a trap in every index.
- **`lx` lessons carry NO operational directives.** "Do not arm", "stay disarmed", "keep it off" expire when state changes; a lesson does not. State lives in the `tr` tracker. Found live 2026-08-31: a 2026-08-13 lesson still ordering "stay disarmed" on a funded, armed, trading account.
- **Close the loop before the session ends:** re-search every slug you wrote and read the top hit. If it is not the corrected one, you have not finished.
- Full case: `[[fundingrock-the-weekend-addon-is-worth-1-08-a-trade-and-only-rogue-size-makes-holding-dangerous]]` (the conflict) and `[[fundingrock-keeps-extensive-records-only-the-equity-path-was-absent]]` (the renamed slug).

## memgit
- ~3,200 saved memories cover trading, crypto, instagram, memgit, fundingrock, numerai — decisions, gotchas and corrections NOT in the code. Search the VARIABLE you're measuring, not just the strategy (playbook §1a).
- memgit `tr` trackers are the authority for entity STATUS; files are downstream. Changed state? Re-save the tracker, same slug, **that session** — a tracker you found stale and left stale is the next session's wrong answer. Corrections supersede.
- ⚠️ `save_memory` on an existing slug REPLACES it: omit `body` and the body is WIPED (done to this very guide 2026-08-24, **and again 2026-09-07 by an agent that had just read this very line**). Always resend the full body when updating. The failure mode is silent: the save returns `"action": "updated"` and looks like a success. **Read the memory back after every update to a slug that already existed** — that is the only thing that catches it.

## Never assert an absence (added 2026-08-24, after a 12-day wrong diagnosis)
- "Endpoint X returns nothing" is a fact about **X**, never about the data. Before writing "it's broken" / "there is no API for this", probe a SECOND independent route — raw HTTP not the SDK, adjacent paths, the SDK's own URL construction, a newer SDK. Report which routes were tried.
- **Confirm a write through the handle the write returned.** If `create` hands you an id, read THAT id — never a different endpoint's index.
- A guard must not read the same source as the thing it guards, or it cannot tell a source failure from the danger it exists to catch.
- ⚠️ **A guard whose pass condition is EMPTY OUTPUT must be shown to produce non-empty output once.** Empty has two causes that look identical: the thing is fine, or the check is not looking at it. Measured 2026-09-11 — a `git diff` "proving" the VS Code bundle was untampered ran against a **gitignored** path and could never have failed. `[[the-vscode-bundle-tamper-check-read-a-gitignored-file-so-it-could-never-fail]]`.
- Say only what the evidence reaches. Full case: `never-assume-a-capability-is-absent-verify-it-through-a-second-route`.

## 🔴 STRICT — READ THE WHOLE LIMITS TABLE, AND THE LIFETIME OF EVERY CREDENTIAL YOU MINT (added 2026-09-07, owner directive, after a 3-day self-inflicted broker lockout)
- **The limit that hurts is the one ADJACENT to the limit you went looking for.** We had already read and quoted Groww's rate-limit table for its per-second numbers. The line that cost us three days — *"/v1/token/api/access is also subject to a limit of 150 requests per 24 hours"* — is the note directly BELOW that table, and the token's *"Expires daily at 6:00 AM"* is on the same page. Read the section to the END, including the notes.
- **A credential with a documented lifetime is minted ONCE PER LIFETIME AND PERSISTED, never per process.** We minted one per process across 8 call sites, every timer and every interactive `ops/pb` run. A token designed to last 22 hours had a lifetime of ~4 seconds in our hands.
- **Cache the FAILURE, not just the success.** `execute.groww()` cached the client on success only, so every later call re-minted: 57 attempts in one hour, each spending another unit of the quota it was waiting on. A system that answers "you have asked too many times" by asking more times cannot recover on its own — that is what turns a bad afternoon into a multi-day outage.
- **Put a self-imposed ceiling UNDER the vendor's, in code.** "We read the docs" is a rule and rules do not survive the session that wrote them. `MAX_MINTS_PER_DAY = 20` against a cap of 150 is a mechanism; if it trips, that IS the bug report.
- **No test may spend production budget — intent is not a guard.** `run_tests.py` exports `PB_NO_BROKER_CALLS=1`. Second instance of this exact shape: the suite was quietly spending indianapi units (2026-09-05), from a file whose docstring said "No network".
- **Distinguish three answers, never two:** quota spent · credential refused · could not reach. They have opposite fixes, and collapsing them is how an auth failure gets reported as an unprotected book.
- ⚠️ **A dependency RANGE has two ends and both are load-bearing.** An upper bound keeps an API break out; a LOWER bound is what a resolver may pick from and what every supply-chain scanner reads. Measured 2026-09-11: `mcp>=1.0.0,<2` shipped for months permitting six advisory-affected SDK versions, none reachable from our code, and it still scored memgit 4.8 "Use Caution" on a public marketplace. Check both ends against the advisory database, not against a scanner's finding list.
- Facts: `ops/RUNBOOK.md` §3a. Full case: `[[a-daily-credential-minted-per-process-locked-us-out-of-our-own-broker]]`.

## Read the environment the code runs in, not the one you are standing in
- A config value read from your interactive shell is NOT the value the service sees. systemd `EnvironmentFile` (e.g. root-only `/etc/fundingrock.env`) is invisible to a plain ssh session — measured 2026-08-28: `rogue_risk_usd()` returned `0.0` interactively and `2000.0` under the service env. Load the unit's environment before measuring, or you will report the opposite of the truth.
- ⚠️ A file meant to be SOURCED gets the CALLER's shell, and this Mac's is **zsh**. `${BASH_SOURCE[0]}` is bash-only and empty there — measured 2026-09-07: the gcloud account pin resolved to the wrong path from an interactive shell, `pb_gcloud` was never defined, and every `secrets-ops/*-env.sh` reported its secret MISSING from Secret Manager while it sat there readable. Use `${BASH_SOURCE[0]:-$0}`, and test a sourced file by SOURCING it from each shell, never by executing it. Full case: `[[the-gcloud-account-pin-used-a-bash-only-idiom-and-broke-every-env-script-under-zsh]]`.

## Layout (restructured 2026-08-20; automation SPLIT PER HOST 2026-09-03 — each project has its own CLAUDE.md; open it FIRST *after* memgit)
- Engines live in SIX per-host repos, each keeping its `<engine>/` subdirectory: fundingrock/ (quant-vm + prop-vm) · crypto/ (crypto-vm) · brain-vm/ (brain + numerai) · competitions/ (crunchdao, quantiacs, alphanova, automation-system + all workflows) · kronus/ (research) · pb-core/ (improve_lib, logbook, evaluation shims). Per-engine CLAUDE.md + NEXT_STEPS in-repo.
- ⚠️ `automation/` is the ARCHIVED monorepo (remote archived, checkout deleted 2026-09-03). Nothing deploys from it — never read an engine file from it.
- trading-setup/ (equity VM mirror; TRADING/KRONUS docs in-repo) · equity-improve/ (equity verdict loop)
- instagram/ (pipeline repo at root now; absorbed daily.sh/ritual.sh/ga4_pull.py)
- memgit/{core,cloud,website,plugins,tap} (product group) · hari-portfolio/ · ops/ secrets-ops/ security-ops/
- The book lives on KDP/Pothi, not on disk; memory-archive was validated and deleted (git history keeps it).

## Commands (never look up keys/venvs/deploys)
- ops/pb health | pnl | stops | cycle | deploy | timers
- ops/pb improve (equity) · improve-crypto · improve-fundingrock · improve-brain · improve-numerai · improve-kronus · improve-instagram · improve-crunchdao · improve-quantiacs · improve-all
- `ops/push-repo.sh "<repo-dir>" "<msg>"` — the ONE landing channel, and now the agent's own step. `--dry-run` prints the plan.
- `python3 trading/groww_auth.py --status` (on the trading VM) — Groww token, expiry and mints in the last 24h. Free. `--probe` spends one mint.
- Read ops/AGENT_PLAYBOOK.md before any measurement, deploy, or VM command. §0a is the memgit-first gate.

## Non-negotiables (full list in CLAUDE.md)
- **the system runs itself — a step that needs a person is a defect** · **memgit before any file** · **no conflicting or stale memory** · **an agent LANDS ITS OWN WORK via ops/push-repo.sh** · **if a step is genuinely the owner's (tag/release, rail change, a refused permission), give the exact command** · **read the whole limits table and persist every credential** · Doc matches box, same commit · four gates for live changes · fix defects this session and LAND them · secrets never on disk · every claim carries source+date · never co-author as AI.

<!-- memgit:auto -->
## Frequently relevant in this project
(auto-maintained pointers — call memgit get/search for full detail)
- [memgit-tool] memgit is a fully working Python CLI tool built at `/Users/hari/Personal business/memgit/`. It imports, stores, versions
- [pothi-india-book-edition] Pothi distribution CONFIRMED-PROCEED 2026-07-14 (owner replied "skip print review, proceed" to Pothi's hold email) — Fli
- [brain-vm-ssh-flaky-use-detached-runs] gcloud compute ssh to brain-vm drops intermittently (exit 255), and a dropped connection KILLS the remote command mid-ru
- [toptal-mr-cooper-work-experience] 🔴 Write "Rocket (formerly Mr. Cooper)". C#-FIRST: C#/.NET back-end services over Kafka, React front end; Java secondary 
- [memgit-v020-design] memgit v0.2.0 is RELEASED on 2026-07-02 across PyPI, npm, Homebrew tap, VS Code Marketplace (displayName now "Memgit Too
- [domain-next-steps-doc-pattern] New domain status/decision docs go at the Personal-business root as <DOMAIN>_NEXT_STEPS.md (e.g. BOOK_NEXT_STEPS.md, CRY
<!-- /memgit:auto -->
<!-- MEMGIT:END -->
