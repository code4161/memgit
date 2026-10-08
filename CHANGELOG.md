# Changelog

## [0.13.0] — 2026-10-08

A save whose parameters were swallowed into another field is now refused instead of stored. Measured 2026-10-07 on one machine: 748 of 3,025 `save_memory` calls (24.7%) arrived with tool-call markup inside a field, and memgit stored every one with defaults for the fields that never arrived and answered `status: ok`.

### Fixed
- **`save_memory` refuses values that carry tool-call markup.** The model closes a value with a tag named after the field (`</rule>`), the host parser does not accept that as the end of the value, and every parameter until the next accepted closer lands inside it. The refusal names the damaged field and the parameters found inside it, and nothing is written, so the model retries in the same turn. It checks every string argument and every list item. Markup counts when it is a parameter, invoke or function_calls tag (with or without a namespace prefix), or a closing tag named after a save_memory field with nothing but whitespace or more markup after it, so a `</body>` in a note about HTML is prose. Anything inside backticks is exempt, so a memory can quote the defect. Replayed over the 2,935 save calls still on disk, it refuses 725; the only two loose matches it lets through quote the markup deliberately. `memgit add` and the HTTP `PUT /memories/<slug>` apply the same check.
- **Damaged text is no longer injected back into context.** Exposure to a damaged memory raised one model's damage rate from 40.5% to 59.6%, because the markup reads as content. The resume digest (status board, recent memories, critical rules, core guide), the recall hook, the core-guide auto block and every MCP read now show each field cut at its first markup token. Read results carry a `damaged` flag naming the repair command. The store is never rewritten by a read.

### Added
- **The save response says what was stored.** A `stored` block gives the length of rule, why, when and body, the tag count, and which of them arrived empty. `defaulted` names values that came from a default.
- **Warnings for the silent cases**: a `type_code` that never arrived (stored as `fb`), an unknown argument such as `memory_type` (which memgit never accepted, and which came with damage in 36 of 40 calls), and a rule over 400 characters (the damaged median was 992, the clean median 306).
- **`memgit doctor` counts damaged memories by project in its default report, and `memgit doctor --repair-markup` repairs them.** It splits each damaged field back into its fields, merges swallowed tags, related and supersedes into the real lists, restores a swallowed `type_code` or priority, drops the start of a following tool call, keeps the original timestamp, and covers superseded memories too. It is a dry run until `--yes`, writes one checkpoint, and `--project` limits it to one label.

### Not done
- Renaming the save parameters to names that do not read as element names (`fact`, `reason` and so on) needs a save-side eval against a live model first. It is not in this release.

## [0.12.0] — 2026-09-20

A project whose memories have split across two labels raises no error anywhere, so `memgit doctor` now volunteers it. Measured 2026-09-20 on a 4,957-memory store: 2,190 memories did not surface in the workspace that owns them, and 2,168 of those were one relabel away.

### Fixed
- **The two project-label derivations disagreed, and a test asserted the disagreement was correct.** `project.py`'s docstring promises that a label derived from a path and a label derived from a Claude Code `projects/` directory name agree byte for byte, or scoping silently breaks. They did not: the munge regex kept the `_` character and Claude Code rewrites it as a dash, so `~/Freelance/logistics_crm` derived as `Freelance-logistics_crm` from the path and `Freelance-logistics-crm` from the directory name, and neither half of that project could see the other. Zero of the ~2,000 directories in a real `~/.claude/projects/` contain a `_`. `test_underscore_preserved` asserted the bug, and the parity test passed because it paired a path holding a `_` with a hand-written directory name that kept it — both sides built from the same wrong assumption, so the one test written to catch this could not see it.
- **Existing labels are not stranded by that fix.** Comparison folds the two forms and storage is untouched: `normalize_label` runs inside `same_project_family` and `project_affinity`, never on the way to disk. Labels written before the fix, and memories arriving from an older writer or another machine, keep resolving. The `_unknown` quarantine label carries a `_` by design and is returned untouched, so it can never fold onto a real label.

### Added
- **`memgit doctor` reports scope losses by default, and `--audit` adds the detail.** A split label passes `fsck`, raises nothing and generates no bug report, so the only way anyone learns of one is a report that volunteers it. Four mechanisms are detected: the directory moved, the label was misspelled by hand, a short label was used where the workspace label was meant, and the two derivations disagreed. `--json` emits the whole report.
- **Which label survives a repair is decided by the directory, not by the memory count.** On a real store, healing toward the bigger pile would have kept a dead label holding 1,819 memories over the live one holding 18, and a misspelling holding 75 over the spelling holding 18 — stranding both projects a second time.
- **Successor guessing is narrow on purpose.** Matching a stranded label to a live one by its last path segment paired two different clients who happened to share the segment `crm`, which would have filed one client's memories under another. A candidate must be a trailing segment run of the stranded label and already hold memories, and ties break on directory depth.
- **`memgit.tiers` and `memgit.org`: the company and component tiers, foundation only.** A client folder is not one project — one measured folder held six separate git repos and one workspace held thirteen sub-projects, and every save landed on whatever depth the session started from. `project_root` resolves a working directory to the project that owns it plus the component inside it, so a directly opened sub-repo stops looking like a project of its own. `org.resolve` derives a project's company from evidence inside the project and never from a folder name alone: a folder holding six unrelated clients resolves to `container`, not to a company. **Nothing calls either module yet** — no scoping, ranking or save behaviour changes in this release.

### Internal
- **`toon.py` carries unknown fields through a parse and serialize round trip.** A field written by a newer memgit was previously dropped by an older one, silently and with a success report, which is how a machine running two versions against one store loses data with nothing in any log.
- `project_label_from_path` takes an optional `home`. Deriving labels against another root needed a second copy of the munging, and a second copy is exactly how the two derivations drifted apart.

## [0.11.0] — 2026-09-11

Concurrent writes stop losing memories, sync stops claiming it shipped one, and the dependency range stops permitting an MCP SDK with a published advisory.

### Security
- **The `mcp` floor is raised from 1.0.0 to 1.28.1.** Six advisories stand against the MCP Python SDK — CVE-2025-53366 (<1.9.4), CVE-2025-53365 (<1.10.0), CVE-2025-66416 (<1.23.0), CVE-2026-52869 (<=1.27.1), CVE-2026-52870 (1.23.0 to 1.27.1) and CVE-2026-59950 (<1.28.1) — and the old range permitted every affected version. **Five of the six are in the SDK's HTTP, SSE or WebSocket server transports and the sixth needs `server.experimental.enable_tasks()`. memgit imports `mcp.server.Server` and `mcp.types`, serves stdio, instantiates none of those transports and never enables tasks, so none of the six was reachable in this package** — and `memgit serve --http` is memgit's own `http.server` handler, not the SDK's. What was actually wrong is the declared range, which is what a resolver is allowed to pick from and what a supply-chain scanner reads. A clean install resolved 1.29.1 before this change and 1.30.0 after it; `tests/test_dependency_floor.py` now fails if the floor is lowered under any of the six again, or if the upper bound stops excluding the 2.x API break.
- **`memgit git push` / `pull` / `init --remote` validate the remote and branch before they become git arguments.** No shell was ever involved, so there was nothing to quote, but argv is not inert: git reads a leading `-` as an option, which is how a remote name becomes `--upload-pack=<command>`, and an `ext::` URL is by definition a command line that git-remote-ext executes. These values arrive from a CLI argument, a teammate's checked-in config or an MCP caller. They are now refused with a message that says which rule they broke, before any process is spawned and before `git_push` exports anything.

### Fixed
- **`memgit init` no longer swallows every error while looking for existing memories.** The scan of `~/.claude/projects` was wrapped in a bare `except Exception`, so a genuine importer bug looked identical to "you have no memories yet". It now catches only `OSError` and `ValueError` — an unreadable tree or a file that will not parse, the two cases that are a reason to skip the offer — and prints what it hit instead of hiding it.
- **The store lock did not exclude, and memories were silently lost.** Measured: 3 of 120 concurrent runs dropped a memory, with a holder counter seeing **3 simultaneous lock holders and 5 exclusion violations**. The object was written and readable, but the slug was absent from both `TOON_INDEX` and HEAD's MindState, nothing raised, and `fsck` reported clean. Root cause: acquisition is `os.open(O_CREAT|O_EXCL)` followed by `os.write` of the owner token, and **between those two calls the lockfile exists with zero bytes**. The stale-lock breaker read that empty file, computed `pid = 0`, skipped its liveness check because `pid > 0` was false, and fell through to `not pid_alive` — deleting a live lock. Two writers then ran the read-modify-write of the index at once and one of them won. An unstamped lockfile is now treated as a lock being born, never an abandoned one, and only a provably dead owner or a genuinely aged-out lock is broken. After the fix: **0 of 250 runs lost a memory**, max concurrent holders 1, violations 0.
- **Releasing the lock is now ownership-checked.** The old release unlinked unconditionally, so a holder whose lock had been broken and taken over would delete the new owner's lock on the way out, cascading one race into the next. Each acquisition now stamps a unique token and only removes the lockfile if it still holds that token.
- **`memgit savings` crashed on any unreadable file.** `_tracked_files()` called `is_file()` outside the guard that already protected `stat()` and `read_text()`, so a single unreadable entry (a `/proc` symlink, a directory without permission) killed the whole report with a `PermissionError`. The walk now skips what it cannot stat and continues.

### Changed
- **The VS Code extension's build toolchain moved to current: TypeScript 7.0.2, esbuild 0.28.2, `@vscode/vsce` 3.9.2**, and the dev tree now audits clean (vsce 2.x pulled a `cheerio` that pulled five `undici` advisories; vsce 3 does not). None of these ship in any artifact — the extension has zero runtime dependencies. TypeScript 7 removed `moduleResolution: node10` and no longer pulls every `node_modules/@types` package in implicitly, so `tsconfig.json` now says `moduleResolution: bundler` with `module: preserve` (which is what esbuild actually does) and names its ambient types explicitly as `["node", "vscode"]`.
  - ⚠️ **`@types/node` stays on 20 and `@types/vscode` on 1.90 on purpose, and `npm outdated` will keep listing them.** They are not dependencies to keep current; they describe the platform the extension targets. VS Code 1.90 runs Node 20 in its extension host, and `vsce` refuses to package an extension whose `@types/vscode` is newer than its `engines.vscode`. Raising either would drop support for older editors in exchange for nothing.
  - The rebuilt bundle was proved equivalent rather than assumed: both builds carry **the same 114 string literals**, no network-shaped literal, no injected markers, and two consecutive builds are byte-identical. The single difference esbuild 0.28 introduced is constant folding, `7*24*60*60*1e3` to `10080*60*1e3` — the same 604,800,000 ms.
- **The published `.vsix` no longer ships `.gitignore`** (7 files, 27.94 KB, from 8 and 28.09 KB).

### Added
- **Every environment variable memgit reads is inventoried in `memgit/env.py`, and a test keeps the inventory honest.** `tests/test_env_inventory.py` walks the package's AST on each run and fails if the code reads a name the inventory does not carry, or carries a name nothing reads — including the two that are read through a variable rather than a literal, which no simple scan would catch. The README table is generated from the same source, and says what each one does: 18 variables, 14 of them `MEMGIT_*`, the rest set by other software (`CLAUDE_PROJECT_DIR`, `PYTEST_CURRENT_TEST`, `USER`, `USERNAME`). None of them turns network access on.
- **The README documents how the project label is decided**, including the `_unknown` quarantine that a write takes rather than being filed globally, and the conditions under which a free-text label is folded onto an existing project.
- **`memgit cloud push` and `sync` refuse to run while memories are staged but not committed.** Sync ships checkpoints, and `add` does not create one — so pushing straight after `add` uploaded nothing of the user's while reporting `created (2 objects up)`, and the receiving machine then showed an empty store that `fsck` called OK. Nothing errored, which is why it reads as "sync is broken" rather than "you have not committed". The error names the memories and the fix; `--allow-uncommitted` is there for anyone who means it. `Repository.uncommitted_slugs()` exposes the same check.


## [0.10.0] — 2026-09-06

The server starts again, stops when you do, and stops re-reading the whole store.

Three things were wrong at once and only one of them was known. The MCP SDK released 2.0 on 2026-07-28; memgit asked for `mcp>=1.0.0` with no upper bound, so from that day every fresh install resolved to 2.x, which removed the decorators this server is built on, and **the server crashed on startup before answering a single request**. Both routes were affected: pip, and the npm wrapper, which installs memgit into a clean venv on first run. Separately, a stdio server lives as long as its host and an AI host stays open all day — measured here as six servers with living parents aged over seven hours, two of them still holding 126 MB and 112 MB — because nothing ever released the caches. And the thing filling those caches was rebuilding them from scratch on every single call.

### Fixed
- **`mcp` is pinned below 2.0, which is what makes memgit installable again.** The upper bound is the fix; the rest of this entry is what was found while proving it. Measured: a clean `pip install memgit` resolved `mcp 2.1.1`, and `memgit serve` died with `AttributeError: 'Server' object has no attribute 'list_tools'`. With the pin it resolves 1.29.1, starts, and answers `initialize`.
- **An incompatible SDK now says so, in words, with the command that fixes it.** MCP hosts do not surface a server's stderr, so the old failure reached the user as "the server failed to start" with no cause. The check runs before the decorators are touched and names the version found, the version needed, and the extra step for the npm route.
- **The server reports its own version again.** `Server()` was constructed without `version=`, so the MCP SDK filled in its own: every host displayed memgit's version as `1.29.1`. On a defect whose only symptom is silence, that was the one field that could have told anyone which memgit they were running.

### Added
- **The server releases its memory when it goes idle**, dropping the parsed-object and tokenization caches after 15 minutes with no tool call (`MEMGIT_IDLE_EVICT_SECONDS`). Eviction rather than exit: exiting would gamble on every MCP host reconnecting, and it is not needed to free the memory — the corpus pool below makes a reload cost about 40 ms.
- **An orphan watchdog.** Closed stdin already ends the process when a host exits, verified end to end (1 second after a `SIGKILL` of the parent). This is the backstop for when it does not: a server whose parent has become pid 1, having not started that way, stops.

- **`memgit pro activate | status | deactivate`** — a Polar-issued licence key, validated against Polar's public customer-portal endpoint and cached at `~/.memgit/license.json` (0600). Fail-open with a 14-day grace window, 24-hour recheck cadence, key never echoed in full. `MEMGIT_LICENSE_KEY` serves headless MCP hosts and is never written to disk.
- **No new dependency.** The check uses `urllib`; plain memgit stays `click + rich + mcp`.
- **Cloud attach.** When the store is logged in to memgit cloud, activation also upgrades the hosted account (`POST /v1/billing/polar/activate`).

- **`memgit savings` — what memory cost, against what finding the same fact would have cost.** `memgit metrics` refuses to print a savings figure, and its reasoning holds for the naive counterfactual: you cannot observe a file read that did not happen. A *stated* counterfactual is a different question and it is measurable. Without memgit, an agent needing a fact would grep the project and read the best-matching files, so this indexes every file a reader could open, finds the passages that actually carry a memory's terms, and prices the reads. Matching is done over passages rather than whole files on purpose: a 40 KB document holds half the vocabulary of almost any memory, so whole-file overlap made the three largest docs in a repo "contain" everything, and those are also the most expensive to read. **A memory no file carries is never converted into tokens** — it is reported as a count, because without memgit those facts are not found more expensively, they are not found. Measured on a 4,075-memory store against a 1,958-file workspace: **40.6% of recalled memories exist in no file at all**, and for the rest reading costs **94x** what recall costs.

### Changed
- **The store is loaded once, not once per call.** `Repository.list()` re-read and re-parsed every object on every call, and it is the first thing search, recall, the digest and the core guide all do. Measured on a 4,075-memory store: 4,075 gzip opens (429 ms) plus 4,075 TOON parses (718 ms), paid in full on **every** tool call. Memories are content-addressed, so a SHA-keyed cache of parsed objects can never serve stale content — the same reasoning `scorer._TOKEN_CACHE` already used one layer up, applied to the layer that was still doing the work. The cache hands out copies, because callers mutate what they are given (`verify`, `doctor --relabel`, dedupe) and then re-save it; copying all 4,075 costs 8.2 ms against the 1,040 ms it replaces.
- **A cold process reads one file instead of 4,075.** The in-process cache does nothing for a new process, and every AI session starts one. `.memgit/cache/corpus.json` is a pre-parsed pool written by whichever process paid the cold load. It is keyed by SHA and therefore needs no invalidation: a row for an edited memory belongs to a SHA nobody asks for any more. A missing, truncated or corrupt pool is not an error — every SHA it fails to supply is read from the object store exactly as before.
- **Measured on the live store, five searches in one process.** Cold first search **2,035 ms to 401 ms**. Every later search **1,150 ms to 80 ms**. A session making eight memory calls goes from about **10.1 s to 1.0 s**, and stops making roughly 33,000 gzip file opens.
- README: a "memgit Pro" section states exactly what is and is not gated, and what leaves the machine (the key and the organisation id; never memory content).


## [0.9.1] — 2026-08-14

Findable where the users actually are.

memgit ships on five package channels and appeared on **zero** MCP discovery surfaces. Glama auto-crawls 72,234 servers and did not list us, while competitors did; a search for "memgit MCP server" returned other projects entirely. The registries were never going to find us on their own, because the metadata they read did not exist in this repo. That is a distribution gap, not a product gap — and it means the absence of inbound interest had never actually been tested.

### Added
- **`server.json` — the official MCP Registry manifest.** Validates against the `2025-12-11` schema and declares **both** install routes, since the registry stores metadata only and both artifacts already exist: `memgit-mcp` on npm and `memgit` on PyPI (invoked as `memgit serve`), each over stdio. No required environment variables, so the zero-config path is preserved.
- **Namespace `dev.memgit/memgit`**, the reverse-DNS form of a domain we own, proven by DNS rather than by a GitHub account. Chosen before the first publish deliberately: the registry treats a name change as a *separate* server entry, not a rename.
- **Ownership markers.** `mcpName` in the npm package manifest, and an `mcp-name:` comment in this README — the two things the registry reads from the *published* artifacts to prove the packages are ours.

### Note
This release exists to carry that metadata to npm and PyPI. Ownership verification reads what is published, not what is committed, so the markers only take effect from this version onward.

## [0.9.0] — 2026-08-05

Durability that does not wait for a human.

memgit's whole premise is that the AI is the operator. Backup was the one place that premise broke: off-machine safety required someone to remember `memgit git init --remote <url>` and then keep pushing. On this project's own store — 1,734 memories, five weeks of daily use — it had never been run once. The entire memory set existed on a single disk with no copy anywhere. **A maintenance task that needs a human command is a maintenance task that will not happen.**

### Added
- **`memgit backup` — automatic off-machine durability.** Runs unattended from the end-of-session sync path, alongside the housekeeping the operator never has to think about. `backup status` reports the last copy and every destination available; `backup now` forces one; `backup set <path>` pins a destination; `backup off`/`on` control the automatic path.
- **Destination discovery.** A configured git remote ranks first (it is the user's own explicit choice), then cloud-synced folders already present on the machine (iCloud Drive, Dropbox, Google Drive, OneDrive), then writable external volumes.
- **The safety boundary is network egress, not effort.** Local destinations are used automatically — memgit copies files, opens no connection, and signs up for no service; whatever sync client the user already trusts does the rest. A git remote is pushed to automatically **only if one is already configured**: memgit never invents a remote, never creates a repository, and never sends memories to a host the user did not pick. That line matters because memories are not neutral text — a prior audit on this very store found client credentials among them, and convenience is not a reason to publish someone's private notes to a service they never chose.
- **One archive, not a directory tree.** The audited store is 203 MB across 10,295 small object files; handing a cloud-sync client 10k files to reconcile on every backup is how you get a sync client that never finishes. Backups are a single `memgit-store.tar.gz` (171 MB, ~7 s) plus a `RESTORE.txt`. Verified end-to-end: extract, point memgit at it, 1,741 memories restored with a clean `fsck`.
- **Atomic replacement.** The archive is staged and renamed over the target, with the previous copy kept until the new one lands. An interrupted backup must never leave a corrupt file where a good one used to be — that failure does not lose data loudly, it leaves something that *looks* safe.
- **Durability line in the resume digest.** When no backup exists the session-start digest says so, terse (~20 tokens) and self-clearing: it disappears the moment a backup exists, including an automatic one, so the steady-state digest is unchanged.

### Fixed
- **Test isolation: unattended backup could write to the developer's real cloud folder.** Found by inspecting the first live run — a test exercising the sync path had mirrored its temp store into an actual iCloud directory, because destination discovery reads the true home while the store was a temp path. `auto_backup_allowed()` now refuses the unattended path whenever `MEMGIT_STORE` or `PYTEST_CURRENT_TEST` is set. An explicit `backup now` is unaffected: that is someone asking on purpose.

### Note
Three commits in the 0.8.x releases carried an AI co-author trailer, against this project's standing rule that authorship is the user alone. They were rewritten and force-pushed; tags `v0.8.0` and `v0.8.1` were moved to the rewritten commits.

## [0.8.1] — 2026-08-05

### Fixed
- **The core guide's skill list was unbounded.** Skill `description` frontmatter is written to persuade a model to invoke the skill and routinely runs 600+ characters; the guide copied it verbatim. Caught immediately after 0.8.0 by running `core heal` on a real store: 18 skills produced **6,968 of the guide's 9,425 characters**, pushing the measured per-session floor from 2,765 to 3,710 tokens — on the surface that is injected every session on every host, and that the 2026-08-05 audit measured as the lowest-yield memory type in the store (2.10 recalls/memory against 17.5 for feedback). Descriptions are now trimmed to a routing summary at a sentence or word boundary; the full text is in the skill itself, one Read away.

## [0.8.0] — 2026-08-05

Retrieval you can prove, and adoption that starts itself.

Two audits fed this release. The first (2026-07-23, cross-host) produced five phases that were built, tested, and then **never released** — every host kept running 0.7.0, so measured-token honesty, the metrics ledger, host attribution, write-time conflict detection, the candidate boundary, and Codex/Antigravity setup were all dead code in production for two weeks. The second (2026-08-05) measured the live store — 1,727 memories, 17,933 recall events, 356 real sessions, 2.77 billion billed input tokens — and found that capture is solved (91.3% of real sessions both save and recall) while *reaching* saved memory is not.

The headline change is `memgit eval`. Ranking used to be adjusted on intuition; now every change is measured against two frozen sets before it ships. That discipline immediately paid for itself: a recency multiplier that seemed obviously right was **measured harmful and cut**, and a stemming change that fixed its motivating query was **measured harmful in aggregate and rebuilt** as an additive field.

### Added
- **`memgit eval` — a ruler for ranking.** `eval mine` freezes a regression set from the store's own history (real prompts, and the memories prompt-recall actually surfaced for them); `eval mine --synthetic` builds a **non-circular** set that queries each memory by its own `why` and expects itself back. The two answer different questions and are kept separate: the first measures *stability* against the ranking that produced the transcripts, the second measures *correctness* independently of it. `eval run --set <name>` reports hit@1, recall@3/5/10 and MRR, with `--baseline` to pin a comparison point and `--misses` to inspect failures. There is deliberately no single blended score — a change that trades hit@1 for recall@5 is a judgement the operator should see both sides of.
- **Measured-usage term in ranking.** The store has always recorded which memories actually get surfaced (`cache/usage.json`, 17,933 events on the audited store) and decayed those hits on a 14-day half-life — but only the core guide consumed it, while ranking ignored ground truth it was already collecting. Search, recall, MCP and HTTP now pass the ledger to the scorer as a bounded, saturating boost. Measured: real-prompt set hit@1 **+0.015**, recall@3 **+0.020**, MRR **+0.016**; synthetic set flat. Unused memories are never penalised, so a fresh correction cannot be buried under an old favourite.
- **Additive stem matching.** Queries and memories now meet on stems as well as exact terms (`deploy` finds `deployment-vercel`), via a separate low-weight pseudo-field rather than by folding the real fields. Weight (0.35) chosen by sweep on the harness, not by taste. Measured vs 0.7.0: real-prompt hit@1 **+0.020**, recall@3 **+0.041**, MRR **+0.019**; synthetic correctness floor unmoved.
- **Automatic core-guide bootstrap.** A project's first core operating guide is now created without anyone running `core seed`. This was the adoption bug: `seed` and `sync` were manual and nothing ever called them, so a project that never had a human run them had no guide — and `_refresh_core` returned early with nothing to refresh, and no rules file reached any host. On the audited install, 30 projects had memories and 6 had a guide; in the other 24, memgit's entire presence in Cursor/Codex/Antigravity was an MCP tool description, the exact surface the hook design had already measured as too weak to rely on. The self-improving loop could not start on its own; now it starts at `AUTO_SEED_MIN_MEMORIES` (5). Conservative by construction: never for the store itself or `_unknown`, and host files are delivered `project_only`, so no `.cursor/` is conjured in a repo that has never seen Cursor.
- **The seeded guide leads with evidence.** When a repo is available the memgit section opens with what the project actually holds ("This project has **N saved memories** covering *topics* — decisions, gotchas and corrections that are NOT in the code or the README"). An abstract instruction is something a model can weigh against its own confidence and skip; a stated count of real prior work is not — the same effect measured on depth hints below.
- **Project-label folding on save** (`project.canonical_project`). The MCP/HTTP `project` argument is free text, and agents supply the short name they have in their head. A label that is a trailing `-`-segment of exactly one known label, and that holds no memories of its own, is folded onto it — with a warning in the save response, never silently. An *established* label is never folded away in either direction, which is what makes it safe: on the audited store `log-report`(0) correctly folds into `Downloads-log-report`(850), while `FittyMe`(90) is correctly left alone rather than being moved onto `Freelance-FittyMe`(1).

### Fixed
- **Antigravity was never actually wired.** `setup antigravity` wrote to `~/.gemini/antigravity[-ide]/mcp_config.json`, but Antigravity 2.x shares one config across the IDE, the `agy` CLI and the SDK at `~/.gemini/config/mcp_config.json`. Verified on a live install: across 8 Antigravity sessions and 6,785 transcript lines there were **zero** memgit tool calls — it had been reduced to shelling out to the CLI with the user re-explaining memgit in the prompt each time. The shared config is now the primary target; the 1.x per-app paths remain as fallbacks.
- **Antigravity received no core operating guide at all** — it was absent from `delivery.TARGETS`. Antigravity reads `AGENTS.md`, so it now shares Codex's target (one target, union detection: two targets on one path would have clobbered each other's marker block on every sync).
- **Depth hints advertised identifiers.** Commit SHAs (`89e1fd7`), bare numbers and dates were being offered as topics to search. The shape filter is now shared by the memory index, context recall and the prompt-recall hint. The SHA test requires a digit, so words spelled entirely from a-f (`decade`, `faced`, `added`) survive as real topics.
- **Depth hints named nothing.** Measured across 886 real sessions, the bare-count form ("+34 more saved on 'crypto'") was acted on in only **20.5%** — four times in five the model was told depth existed and moved on. The hint now names the strongest unshown memory, deterministically. A count is not evidence; a specific rule the reader can see is missing is.
- **Search re-tokenised the whole corpus three times per query** — once for `avg_doc_len`, once for IDF, once for scoring, with no cache. Profiling put 76% of runtime in `re.findall`. Tokenisation is now memoised by content SHA (content-addressed storage makes the key free and impossible to stale) and computed once per query. Measured **6.8× faster** on the audited store: 46 ms → 6.8 ms per search, and the cost stops growing linearly with store size.
- **BM25 length normalisation was inconsistent** with the new stem field — `doc_len` excluded it while `avg_len` included it, silently shifting every score. Both now use one `_doc_len` helper. (Caught by the harness, which is the point of the harness.)

### Removed
- **The recency multiplier.** Built for this release on the reasoning that a correction and the thing it corrects should not tie, then measured on the harness: real-prompt hit@1 **−0.020**, MRR **−0.018**, with no benefit on the synthetic set — and no benefit either on the de-confounded slice. It was cut before release. Staleness is a write-time problem — supersession (which already correctly hides superseded memories from every retrieval path) and conflict detection on save — not something a blunt global age multiplier fixes. Do not reintroduce it without numbers.

## [0.7.0] — 2026-07-19

Project isolation done right. A cross-project audit found the boundary was a *nudge*, not a wall: search and recall only **boosted** the current project, so any strong keyword match leaked one client's memories into another's session; a save whose workspace couldn't be detected silently became global; and the installed Stop hook's `cd <store> &&` prefix meant every background sync ran *as the store's own project* — which is why core auto-promotion never fired in production. 0.7.0 makes recall **filter-by-default** (current project family + explicitly-global, nothing else), makes unknown provenance loud instead of silently global, and ships the maintenance surfaces (`doctor`, cache GC, honest stats) a store needs after months of real use.

### Added
- **Filter-by-default recall + search** — `search_memories` (MCP), `memgit search`, the prompt-recall hook, and the resume digest's recent/critical/checkpoint/depth-hint pools are all **scoped** to the current project's family plus explicitly-global memories. BM25 IDF is computed over the scoped corpus, so a foreign project's vocabulary can't distort ranking. Widen deliberately: `all_projects: true` / `--all-projects` searches the whole store (every hit carries its `project` label); the existing `project` parameter stays a hard filter. Resume checkpoints are scoped too — a checkpoint survives only if a slug it touched resolves to a family-or-global memory, so a session never opens with another project's commit log.
- **Explicit-global vs `_unknown` quarantine** — `project=None` now MEANS "applies everywhere" (set with the new `memgit add --global`, or `project: ""` over MCP/HTTP). A save whose project cannot be detected is never silently global: it's quarantined under `_unknown`, the save response/output says so, `list` marks it `[?project]`, `lint` flags it, and it surfaces in no project's recall (`_unknown` family-matches nothing — not even itself) until relabeled.
- **One detection path** (`project.detect_project`) shared by the MCP server, CLI, and hooks: explicit caller value > `MEMGIT_PROJECT` > hook-payload cwd > `CLAUDE_PROJECT_DIR` > process cwd. The MCP server re-derives the label **per call** (envs win), keeping the startup cwd only as a fallback.
- **`memgit doctor`** — store hygiene in one place. Bare: a report of quarantined + explicitly-global memories grouped by tag, stale session-cache files, and usage-ledger entries whose memory no longer exists. `--relabel mapping.json` bulk re-projects memories (`{"slug": "Label" | ""}`) preserving timestamps and every other field, committed ONCE as `doctor: relabel N memories`; `--prune-usage <slug>`, `--clean-caches`, `--prune-session <id>` repair exactly what the report names.
- **Session-cache GC** — `memgit gc` (and, best-effort, the end of every `sync`) deletes per-session cache files older than 30 days under `.memgit/cache/{recall,recall-hints,ctx-recall,stop-guard}`.
- **Resume digest hard budget** — the SessionStart injection is capped at 9,500 chars; over budget, sections trim in a fixed order (recent 10→5, checkpoints 5→3, critical text →160 chars, index topics 8→5, recent 5→3). The core operating guide body and the status board are never trimmed.
- **`MEMGIT_STORE` env** — when set, it is the *only* store-discovery candidate (tests point it at a tmp path so the suite can never touch a live store).

### Fixed
- **Stop-hook `cd <store>` bug** — the `memgit setup hooks` template prefixed the sync command with `cd <store> && `, poisoning every cwd-derived project label; the background sync always "ran in" the store's own project, so core auto-promotion never triggered for real projects. The prefix is gone (`memgit sync` finds the default store from any cwd), and the auto-core path additionally refuses to ever create/refresh a core guide *for the store itself* or deliver rule files into it.
- **Hook/MCP binary resolution works for any install method** — setup resolves, in order: the entry point actually running it (`sys.argv[0]`, only when its basename is `memgit`/`memgit.exe`), `shutil.which("memgit")`, then the `<python> -m memgit.cli` form — and writes the resolved absolute path (quoted) into every hook command. A bare `pytest`/`python` argv0 can no longer be registered as the memgit binary.
- **Gemini CLI delivery was inert** — `.gemini/memgit.md` is a file Gemini CLI never loads (only `GEMINI.md` is auto-loaded, and nothing set `context.fileName`). The Gemini target is now a marker-delimited block in the project's `GEMINI.md` (same mechanism as Codex's `AGENTS.md`, user content untouched, 32k cap), and the old inert `.gemini/memgit.md` is deleted on sync.
- **`memgit stats` no longer fabricates savings** — the simulated "dump all" strawman, the "+critical overhead" line, the 10-sessions/week weekly/annualised extrapolations, and GPT-4o pricing are gone. What remains is measured or labeled: full-corpus token size, the resume digest counted from a real render, a labeled recall-block estimate (top-3 rules ≈ chars/4), and one comparison line: per-session injected vs full-store load.
- **Seeded skill descriptions no longer truncated** — `core seed`'s frontmatter reader now joins folded/literal YAML scalars (`>`, `>-`, `|`) and plain multi-line values into one sentence instead of keeping only the first indented line.

### Channels
- Chocolatey is unblocked: 0.6.2 pushed successfully on 2026-07-19 after the account approval (the 403 that had stalled every release since 0.1.5 is resolved).

## [0.6.2] — 2026-07-13

### Fixed
- **Recall depth hint no longer advertises project-label tags** — the third surface of the same noise class, also caught live ("+75 more saved on 'business'"). The exclusion rule (project label + its `-`-components are not topics) is now a single shared helper (`links.label_noise`) applied uniformly by the memory index, the context-recall hook, and the prompt-recall depth hint.

## [0.6.1] — 2026-07-13

### Fixed
- **Context-recall no longer hints project-label tags** — caught live within minutes of installing 0.6.0: reading a file under `Personal business/` hinted "77 memories tagged 'business'". Every path inside a workspace contains the label's words, and importer-derived label tags are not topics — the PostToolUse hook now excludes the current project label and its `-`-components from matching, the same exclusion the memory index already applied.

## [0.6.0] — 2026-07-13

The passive layer now advertises what the active layer knows. Measured across 289 real sessions (Jul 7–13): hook-injected recall delivered in ~59% of sessions, but only **6.8%** of recall-injected sessions ever ran an active `search_memories` — and `resume_session` was called once, ever. An AI operator explained why when asked: *"the better your passive recall gets, the less an agent thinks to actively query — I treated the injected sample as the memory rather than as a teaser of a queryable store."* When forced to query, per-task searches surfaced depth (do-not-push warnings, exact version state) that passive recall never showed. 0.6.0 makes every injected block carry a truthful advertisement of depth (counts per topic), the exact one-call query to get it, and trustworthy live state (trackers + supersession) — so what is injected is never stale and always names what more exists.

### Added
- **First-class supersession** — `save_memory` (MCP + HTTP) and `memgit add` accept `supersedes` (and `related`): a correction names the memories it replaces instead of sitting beside them with a "CORRECTED:" prefix. Superseded memories are hidden by default from `search_memories`/`memgit search`, prompt recall, the resume digest, and core-guide auto-promotion (`--include-superseded` / `include_superseded: true` to see them); `list` keeps them visible but marked `⊘superseded-by:<head>`; `get_memory` on a retired link returns `superseded_by` + `head`. Derived, not tombstoned: removing the superseder resurrects the old memory. Self-references are stripped; cycle edges are rejected at write with a warning; unknown targets are kept (the old memory may sync in later). The `supersedes`/`related` model fields and `~SUP`/`~REL` TOON serialization existed since 0.1.0 — 0.6.0 gives them write paths and recall semantics; existing object SHAs are untouched.
- **Tracker memories (`tr`) + status board** — a new memory type for the LIVE status of exactly one entity (a deploy, draft, migration, campaign): slug `<entity>-status`, updated by re-saving the same slug. Trackers render as a status board at the top of the resume digest — `slug (upd MM-DD): state` with a freshness stamp — under the header "memgit is authoritative; files may lag". Capped at 8, project-scoped, never promoted into static host rule files (live state must not fossilize).
- **Memory index — depth advertisement in resume** — the digest now ends with tag→count pairs (`8a8f4ec (6) · instagram (5) · …`) plus the exact call to go deeper (`search_memories("<topic>", top_k=10)`). Tags only (they score at field weight 1.8, so every advertised topic is guaranteed to return results); count ≥ 2; superseded excluded from counts; ~30-45 tokens flat.
- **"+N more" count-line in prompt recall** — when the injected top-3 have ≥2 more on-topic memories behind them, the `<memgit-recall>` block ends with `+6 more saved on '8a8f4ec' — search_memories("8a8f4ec")`. One line max; hinted-but-not-shown memories are NOT marked seen or counted as usage.
- **Context-triggered recall** (`PostToolUse` hook on `Read|Grep|Glob`, installed by `memgit setup hooks`, `--no-ctx-recall` to skip) — prompt recall fires on what the user SAYS; this fires on where the model LOOKS. Reading a file whose path tokens match a memory tag with ≥3 memories injects one line: `memgit: 6 memories tagged '8a8f4ec' relate to this path — search_memories("8a8f4ec")`. Never loads the object store — reads a `tagmap.json` cache rebuilt at commit time; exact token match only; per-session per-tag dedup shared with prompt recall's hints; hard cap 3 injections/session.
- **Core-guide seed nudge in resume** — a project with ≥10 memories and no core guide now gets one line in the digest pointing at `memgit core seed` + `core sync`. (The nudge previously lived only in the MCP server instructions — the one surface no session reliably acts on; 0.5.0's flagship feature had zero adoption four days after release.)
- **Authority framing** across every operator-facing string — server instructions clause 6, tool descriptions, stop-guard nudge, onboard brief, core-guide seed: memgit is the AUTHORITY for entity status; files and READMEs are downstream and may lag; corrections use `supersedes`, state changes update trackers.

### Fixed
- **`co` rejected by `--type` filters** — `memgit list --type co` and `memgit search --type co` errored ("not one of fb, us, pj…"); only `add`'s enum was updated in 0.5.0. All CLI enums, stats labels, graph colors/legend, and the markdown exporter now know `co` (and `tr`). openapi.json / llm-tool-definitions.json type enums were still six-valued from 0.1.0 — now carry all eight.
- HTTP `PUT /memories/{slug}` now accepts `body` (long-form detail was silently dropped on the HTTP surface).

## [0.5.0] — 2026-07-11

Core operating guide — a per-project, always-on navigation aid that memgit carries into every AI host, so any tool instantly knows which skills/tools/commands to reach for even when its own CLAUDE.md/skills aren't configured. Built for the AI-as-operator model: the user installs, the AI drives it, and it maintains itself.

### Added
- **New memory type `co` (core)** — a normal, versioned `Mnemonic` (inherits checkpointing, sync, and cross-tool availability). Per-project scoped; injected in FULL at session start (its body, not the clipped rule), at the top of `resume` and the MCP `resume_session`, under an explicit header stating it is subordinate to the repo's own rules.
- **`memgit core` command group**: `show`, `set`, `edit`, `seed` (drafts a routing guide from the project's existing host skills + rule files), `sync` (delivers it), `refresh` (recompute usage section), `heal` (self-repair).
- **Cross-host delivery** (`memgit core sync`): writes a DEDICATED, memgit-owned rule file into each detected host's native surface — `.claude/rules/memgit.md`, `.cursor/rules/memgit.mdc` (`alwaysApply: true`), `.windsurf/rules/memgit.md` (`trigger: always_on`), `.clinerules/memgit.md`, `.roo/rules/memgit.md`, `.continue/rules/memgit.md`, `.gemini/memgit.md`; Codex's shared `AGENTS.md` gets a marker-delimited block. Additive only — never touches the host's own config or content. Idempotent (overwrite-in-full), size-cap aware (Windsurf 12k, Codex 32k).
- **Self-improving accumulation loop**: a sidecar usage ledger (`.memgit/cache/usage.json`, kept off the content-addressed object so memories stay immutable) counts which memories actually surface at recall/search time. The most-used, project-scoped memories are auto-promoted as POINTERS into the guide's auto-managed section on every `sync` (the Stop hook) — bounded by a hard size/item budget, decayed on a 2-week half-life, deduped against curated text, and NEVER promoting critical rules or conventions (those are policy, not navigation). The curated region is preserved byte-for-byte. `memgit core heal` rebuilds a guide that has drifted.
- **`delete` / `rm` / `del` aliases + did-you-mean** (also in 0.4.1) carried forward.

## [0.4.1] — 2026-07-11

Command ergonomics. A cross-project usage audit caught an AI reaching for `memgit delete`, hitting a bare "No such command", and only recovering by reading `memgit help`. The CLI now meets that intent halfway.

### Added
- **`delete` / `rm` / `del` aliases for `remove`** — the natural verbs now work instead of erroring.
- **Did-you-mean suggestions** on the root group: a mistyped command (`remve`, `serch`) now returns `No such command 'X'. Did you mean 'Y'?` (closest match via difflib), instead of a bare error. Unrelated garbage still fails cleanly with no misleading suggestion. Exact commands and `--help` are unchanged.

## [0.4.0] — 2026-07-07

Guardrail-grade memory. A transcript audit of 166 real Claude Code sessions showed the hard truth: context *injection* (hooks) delivered in 100% of sessions, while *voluntary* tool engagement happened in 6% — sessions found production root causes and client decisions and saved none of them. What a hook enforces happens; what a tool description suggests mostly doesn't. 0.4.0 makes recall and capture hook-enforced, and fixes every defect found in a full end-to-end audit (store forensics + 6-project usage scan + functional validation).

### Added
- **Per-prompt auto-recall** (`UserPromptSubmit` hook): every user prompt is BM25-matched against the store and the top relevant memories are injected as context — recall no longer depends on the model thinking to search. Silent unless a match clears a store-size-aware relevance bar (an absolute bar would mute recall on young stores, where BM25 IDF collapses); per-session dedup so the same memory is never injected twice.
- **Capture guard** (`Stop` hook): a session that did substantial work (25+ tool calls) and saved nothing gets blocked ONCE with instructions to save durable facts — or finish if nothing qualifies. Never nags twice (session marker + `stop_hook_active` double-guard). Detection is anchored to real `tool_use` JSON shapes, so tool names appearing as plain text don't count as saves.
- **`memgit setup hooks` now installs the full set**: SessionStart resume, UserPromptSubmit recall (`--no-recall` to skip), Stop capture-guard (`--no-guard` to skip) + async `memgit sync`. Previously only SessionStart was installed, so MCP-saved memories on hook-less machines were never checkpointed at all.
- **Project-family affinity**: search boost, `resume_session`, and the fresh-project nudge now match hierarchically — a session in `BITS/bits_back` counts `BITS` memories as its own (exact > family > global). Previously exact-string matching meant any session started in a subdirectory silently lost ALL project scoping.
- Resume digest flags a memory-less project explicitly and points to `memgit onboard` (`project_is_new`).

### Fixed
- **CRITICAL — CR/CRLF corruption + field injection** (found by E2E audit): a body containing `\r` was truncated at the first CR on read-back, and the lost tail re-parsed as *injected fields* (a crafted body could override `RULE:`). `\r` is now escaped like `\n`; round-trip is byte-exact. Windows MCP clients and pasted CRLF text hit this constantly.
- **CRITICAL — silent memory loss on space-containing slugs**: a markdown memory whose frontmatter `name:` contained spaces staged fine but vanished on every index read (space-delimited index), with no error. Slugs are now normalized at every write surface, and the index reader tolerates legacy entries.
- **Project-label munging now matches Claude Code byte-for-byte**: `_` and `.` were munged differently than Claude Code's project-dir naming, so memories synced from projects like `bits_back` could never match their own workspace label at recall time.
- **Cross-project leak in resume**: a project with no memories fell back to a global recency dump — a new client project's first session opened with another client's content. Fallback is now family + global(unscoped) only. Critical (p3) rules are scoped the same way instead of firing in every project.
- **MCP `save_memory` never checkpointed**: saves were staged only, waiting for a session-end sync that (a) doesn't exist on non-Claude-Code machines and (b) buried them in `sync:` messages. Each save now commits immediately as `save: <slug> [type]` — attributable and rollback-able.
- **`memgit sync` early-returned without committing staged work** when no markdown memories were found.
- Body first-line indentation / trailing whitespace no longer stripped (byte-lossless round-trip, incl. indented-code-first bodies).
- Rich markup no longer interpreted inside displayed user content: `[pj]` type codes, `[[wikilinks]]`, `[token]`-shaped text, and shas like `[fadc1234]` were being eaten as style tags by `memgit show`/`add` output.
- `memgit lint` exits 1 when issues are found (scripts/CI can gate); empty rules are rejected at write time.
- MCP: unknown tool call now returns a proper protocol error instead of a success-shaped text blob; `save_memory` accepts `type` as an alias for `type_code` (read tools return the field as `type` — operators mirror it back).
- `memgit --version` reads the source `__version__` — editable installs reported the metadata version frozen at install time.

## [0.3.1] — 2026-07-03

### Added
- **Git-aware onboarding** — `memgit onboard` now mines the repo itself before printing the brief: a deterministic, read-only, bounded digest (git branch/commit count/latest tag, recent commit subjects, hot files and directories by churn, recent authors, detected stack from manifests, docs to read first, CI presence). Every probe is timeout-guarded and commit-capped, so it is near-instant even on very large repositories (measured 0.19 s). The brief tells the AI operator to trust the digest and NOT crawl the tree — extraction the tool can do deterministically is no longer left to the model, which is exactly where errors and wasted tokens came from. `--json` emits the raw digest for tooling. Falls back to the generic reading plan when there is no git repo.

## [0.3.0] — 2026-07-03

Lossless memories, project scoping, and mid-project onboarding — fixes from the first real multi-project dogfooding audit, where a 17,500-char project memory was found stored as a 360-char first paragraph and 8 projects' memories were flattened into one undifferentiated pile.

### Added
- **`body` field — memories are now lossless.** The full long-form content of a memory (multi-line markdown) is stored alongside the compact one-line `rule`. The Claude Code importer keeps the entire file body (previously: first paragraph only, truncated to 400 chars — ~98% data loss on rich memories). TOON stays line-oriented via `\n` escaping in field values; old objects' SHAs are unchanged. Search results stay lean (`has_body: true` flag); `get_memory` / `memgit show` return the full body. `memgit add --body` (or `--body -` for stdin) and the MCP `save_memory` `body` param write it.
- **`project` field — memories know which workspace they belong to.** The importer derives it from the Claude Code projects directory; the MCP server auto-detects the current workspace (cwd, `MEMGIT_PROJECT` overrides) and (a) boosts the current project's memories in `search_memories` ranking, (b) leads `resume_session`'s recent-memories section with the current project instead of whatever project was touched last, (c) stamps `save_memory` writes. Hard filters: `search_memories`/`memgit search --project`, `memgit list --project`. `memgit stats` shows the per-project breakdown.
- **`memgit onboard` — adopt memgit mid-project.** A store that starts empty on an existing codebase is useless until seeded. `onboard` prints a bootstrap brief for the AI operator: what to read (README, CLAUDE.md, manifests, git log), what to extract (10–20 durable facts), how to type/tag/prioritize them, and how to checkpoint the seed set. The MCP server also nudges: when a search misses AND the current project has zero memories, the reply explains how to bootstrap instead of a bare "No results found."
- **Cross-project slug collision safety** — importing a slug that already exists under a *different* project re-slugs the incoming memory (`<slug>--<project>`) instead of silently overwriting.
- **Guided `memgit init`** — after initializing, `init` automatically finds existing Claude Code memories (`~/.claude/projects/*/memory`), reports how many across how many projects, offers to import them on the spot (auto-imports when non-interactive), and prints the next steps. No more hunting for the right path to pass to `import claude-code` — the path argument was always optional, and now the flow says so.

### Changed
- **Importer keeps real metadata**: the frontmatter `description` is stored as `desc` (searchable), tags derive from the project label instead of the useless type-code tag, an optional `priority:`/`tags:` frontmatter key is honored, and `source` records the originating file path.
- **`memgit sync` checkpoint messages name what changed** (`sync: +1 ~3 (crypto-module, …)`) when no `-m` is given — a history of "auto-sync on session stop" × 60 tells you nothing.
- BM25 search now indexes `body` content (low field weight, so one-liner rules still rank first).
- `memgit resume` is project-aware (label derived from cwd, `--project` overrides); recent memories from *other* projects are flagged `[Project-Name]` in the digest so agents don't conflate workspaces.

### Fixed
- Multi-line content in any TOON field no longer breaks parsing (values are `\n`-escaped on serialize, unescaped on parse).

## [0.2.0] — 2026-07-02

Session resume, garbage collection, and multi-agent write safety.

### Added
- **`memgit resume`** — a bounded "where we left off" digest: last checkpoints, staged work in flight, recently updated memories, and critical rules. `--plain` for context injection, `--json` for tooling. Measured ~335 tokens regardless of store size (rules clipped, critical list capped at 20).
- **`resume_session` MCP tool** — same digest for AI clients; the authoritative record of last actions, so agents stop guessing session state from open files. Also `GET /resume` on the HTTP server and `resume_session` entries in `llm-tool-definitions.json` / `openapi.json`.
- **`memgit setup hooks`** — installs a Claude Code SessionStart hook that injects `memgit resume --plain` into every new session automatically (`--remove` to uninstall). The model sees your last actions without having to decide to look.
- **`memgit gc`** — mark-and-sweep space reclamation: deletes only provably-unreachable objects (reachable history and staged memories are never touched), trims reflogs, reports bytes freed. `--dry-run`, `--squash-keep N` to compact then sweep. Benchmark: a 2,000-checkpoint store shrank 94% (39.5 MB → 2.2 MB) with `fsck` clean.
- **`memgit merge <thread>`** — three-way merge of another thread into the current one (nearest-common-ancestor based). Enables branch-per-agent workflows: each agent works on its own thread, results merge back. Conflicts resolve to the newest mnemonic; an edit always beats a delete.
- **Store-wide write lock** — git-style lockfile with stale-lock breaking (dead pid or >60 s old) serializes concurrent writers; `MEMGIT_LOCK_TIMEOUT` env tunes the wait. Measured overhead: 0.08 ms per acquire/release.
- **Concurrent-commit auto-merge** — the staging index now records its base checkpoint; if another agent moved HEAD since staging, `commit` three-way merges instead of silently clobbering (trigger `merge`, message notes the auto-merge).
- **`MEMGIT_AUTHOR` env** — per-agent checkpoint attribution in multi-agent jobs.
- **`memgit setup gemini-cli`** — register the MCP server with Gemini CLI (`~/.gemini/settings.json`); also included in `setup all` detection.
- `memgit log --skip N` — history pagination.
- `memgit stats` now reports object count and disk usage.
- **AI-operator surface** — memgit's primary operator is an AI agent, so the store signals its own upkeep: `resume`/`status`/`stats` emit a one-line maintenance hint when history passes 500 checkpoints or 50 MB (naming the exact command to run), and `gc`/`squash`/`stats` grew `--json` flags for terse machine-readable output instead of token-heavy rich tables.

### Changed
- **Squash now archives, never discards** — collapsed checkpoints leave one-line records (sha, time, trigger, author, diff, message) in an append-only `.memgit/logs/archive/<thread>` file that gc never touches. Compaction is lossless-in-substance.
- **History operations scale to long chains** — SHA-prefix resolution uses the object-store fan-out directories instead of walking the whole chain (92.7 ms → 0.08 ms at 2,000 checkpoints), and checkpoint counting uses an incrementally-maintained per-thread cache (92 ms → 0.07 ms; self-heals on any mismatch).
- MCP server instructions and tool descriptions now teach *judgment* ("does this request depend on state you don't have?") instead of keyword triggers; server `instructions` are actually passed in the MCP handshake (previously defined but never sent).

### Fixed
- **`squash` silently discarded staged (uncommitted) memories** — it rebuilt the index from the new HEAD; staged work now survives a squash.
- **`python -m memgit.cli` did nothing** — missing `__main__` guard; this was the documented last-resort fallback for MCP registration, which would have produced a silently-dead server.

## [0.1.5] — 2026-07-02

### Fixed
- **`memgit setup claude-code` registered the MCP server in the wrong file** — it wrote `mcpServers` to `~/.claude/settings.json`, which Claude Code ignores; MCP tools never loaded. Now writes to `~/.claude.json` (user scope) and removes the stale legacy entry automatically. Affects every Claude Code registration made with ≤0.1.4 — re-run `memgit setup claude-code` to fix.
- `memgit setup` no longer overwrites a config file it cannot parse — invalid JSON now aborts with an error instead of silently replacing the file (critical for `~/.claude.json`, which holds all Claude Code user state)
- `memgit setup` / `memgit setup all` detect Claude Code via `~/.claude/` instead of misfiring on the home directory

### Added
- Setup registration test suite (7 tests: correct target file, idempotency, state preservation, invalid-JSON guard, legacy cleanup)

## [0.1.4] — 2026-07-02

### Added
- `memgit rollback <ref>` — restore state to a checkpoint (`HEAD~N` or SHA prefix), git-revert style: creates a new checkpoint, history preserved; `--dry-run` and `-y` flags
- `Repository.resolve_ref()` — resolves `HEAD`, `HEAD~n`, and abbreviated checkpoint SHAs
- Store auto-detect fallback: CLI and MCP server now find the store from any directory (walk-up first, then `~/.claude/memgit-store`, `~/.cursor/memgit-store`, `~/.windsurf/memgit-store`, `~/.memgit-store`)
- Optional exact token counting via tiktoken: `pip install "memgit[tokens]"`

### Fixed
- Priority 1 (low) memories were silently stored as priority 2 — the serializer only emitted the priority flag for priority 3; now round-trips all priorities (with tests)
- `memgit stats` no longer prints an estimated "mem-search plugin" comparison row (the figure was fabricated, not measured)
- `memgit stats` search-cost estimate is now deterministic (top-8 × average memory size) instead of simulated canned queries that under-filled results and inflated savings
- GPT-4o input price corrected to $2.50/M tokens (was $5/M) — all $ savings figures in stats, README, and memgit.dev halved accordingly
- TOON efficiency claims corrected: ~5–10% leaner than markdown with a real tokenizer (the 95% savings figure is from BM25 top-k retrieval, not the format)
- README/docs no longer reference a nonexistent `memgit checkout`; docs pages match actual CLI flags and setup behavior
- USAGE.md rewritten as a generic quick start (previously contained machine-specific paths)

## [0.1.3] — 2026-07-01

### Added
- VS Code extension published to the Marketplace (`code416-memgit.memgit`), with LICENSE and icon
- Daemon HTTP API for IDE integrations (`memgit daemon`)

### Notes
- 0.1.3 is a VS Code–extension-only release; PyPI/npm/Homebrew remain at 0.1.2.

## [0.1.2] — 2026-07-01

### Added
- Smart `memgit init` — auto-detects Claude Code / Cursor / Windsurf and picks the store path, no argument needed
- Interactive setup wizard (`memgit setup`)
- Auto version from package metadata
- npm wrapper `memgit-mcp` published (run the MCP server via `npx memgit-mcp`)
- Homebrew tap `code4161/tap` with formula pinned to the PyPI sdist

## [0.1.1] — 2026-07-01

### Added
- First public PyPI release (0.1.0 was never uploaded to PyPI)

## [0.1.0] — 2026-07-01

### Added
- Core content-addressed object store with SHA-256 content hashing
- TOON (Token-Optimised Object Notation) format — 40% more token-efficient than JSON
- Repository layer: `add`, `commit`, `diff`, `log`, `list`, `remove`, `fsck`, `thread`
- MCP stdio server with 5 tools: `search_memories`, `get_memory`, `list_memories`, `save_memory`, `get_checkpoint_log`
- HTTP server (FastAPI) for ChatGPT Custom Actions and Gemini function calling
- OpenAPI 3.1 spec (`openapi.json`) for GPT integration
- Provider-agnostic tool definitions (`llm-tool-definitions.json`) for any LLM
- BM25 relevance scoring for memory search
- Claude Code memory file importer (`memgit import claude-code`)
- Auto-sync hook integration (`memgit setup claude-code` installs Stop hook)
- `memgit setup all` — auto-detects and registers with all installed AI tools
- Per-tool setup: Claude Code, Claude Desktop, Cursor, Windsurf, Cline, Roo-Code, Continue.dev
- Abbreviated SHA resolution (git-style 8-char short refs in `diff`)
- Interactive D3.js graph visualization of memory relationships (`memgit graph`)
- Multi-platform distribution: PyPI, Homebrew formula, Chocolatey, npm wrapper, winget manifest
- GitHub Actions workflow for automated PyPI publish on git tag
- 27-test suite with 100% pass rate

### Fixed
- Abbreviated SHA resolution in `diff` command (FileNotFoundError on short refs)
- Lint rule length raised from 200 → 400 chars to match real Claude Code memory sizes
- Slug regex relaxed to allow underscores (`^[a-z0-9_-]+$`) matching importer output
