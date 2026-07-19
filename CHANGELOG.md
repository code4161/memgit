# Changelog

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
