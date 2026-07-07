# memgit — End-to-End Validation Report

**Date:** 2026-07-07  **Version audited:** 0.3.1 → fixes shipped as **0.4.0**
**Method:** three independent audits — (1) usage forensics over 166 real Claude Code sessions across 6 projects, (2) production-store forensics (123 checkpoints / 165 memories), (3) functional E2E of every CLI command + all 6 MCP tools against fresh stores.

> Previous report (v0.1.0, 2026-07-01) is superseded. Its headline "27/27 unit tests" grew to **160/160** here.

---

## The core finding: capture was voluntary, and voluntary ≈ never

| Measured across 166 sessions (Jul 2–7) | Result |
|---|---|
| Sessions where hook-injected resume context was delivered | **100%** (145/145 post-hook-install) |
| Sessions where the model voluntarily called any memgit tool | **6%** (10/166) |
| Sessions with ≥1 `save_memory` | 6% — confined to 2 of 6 active projects |
| `resume_session` / `list_memories` / `get_checkpoint_log` calls ever | **0** |
| MCP call failure rate | 2.1% (1/47, model arg error, self-recovered) |

Sessions in FittyMe/Dropzon/crackers/instagram-pipeline found production root causes (expired TLS cert timer, SES re-sandboxing) and client product decisions — and saved none of them. **Infrastructure worked; discipline didn't.** Hence 0.4.0's thesis: *what a hook enforces happens; what a tool description suggests mostly doesn't.*

## What 0.4.0 changes (all shipped + tested)

**New guardrail layer (`memgit setup hooks` installs all four):**
- `UserPromptSubmit` auto-recall — BM25 match per prompt, injected as context, store-size-aware threshold, per-session dedup
- `Stop` capture guard — substantive session (25+ tool calls) with zero memory writes gets ONE blocking nudge to save; never repeats
- `SessionStart` resume (existed) + `Stop` async sync (previously hand-rolled only on the dev machine — fresh installs got no checkpointing at all)

**Bugs found & fixed (severity order):**
1. **CR/CRLF corruption + field injection** (critical) — `\r` in a body truncated it at read and re-parsed the tail as injected fields (could override `RULE:`). Now escaped; byte-exact round-trip.
2. **Silent memory loss on space-containing slugs** (critical) — space-delimited index dropped them on every read, no error; 3 real FittyMe memories were being lost on every sync. Slugs normalized at all write surfaces + tolerant index reader.
3. **Project scoping broke in subdirectories** (major) — exact-match labels + munging that disagreed with Claude Code's (`_`, `.`) meant a session in `BITS/bits_back` matched nothing. Now hierarchical (exact > family > global) with byte-exact munging parity.
4. **Cross-project leak in resume** (major) — memory-less projects fell back to a global dump (client A's content in client B's session); critical rules fired unscoped in every project. Both now scoped.
5. **MCP saves never checkpointed** (major) — staged only, invisible provenance. Now committed instantly as `save: <slug> [type]`.
6. `sync` early-returned without committing staged work; rich markup ate `[tokens]`/shas in `show`/`add` output; body edge-whitespace stripped; `lint` exited 0 on issues; empty rules accepted; MCP unknown-tool returned success-shaped text; `--version` reported stale metadata; `save_memory` rejected the `type` alias that read tools themselves return.

**Machine hygiene (this laptop):** three conflicting installs unified — stale 0.2.0 PATH shadow removed from the analytics venv, dev venv metadata refreshed, all hooks + MCP now run one binary (the editable dev venv).

**Store hygiene:** 4 stale `validation-round*` p3 memories demoted+scoped (were injected into every session of every project), test artifact removed, memgit-internal memories scoped (checkpoint `43559c33`).

## Verification

- **160/160 unit tests** (128 existing + 32 new covering every fix above)
- Live smoke: subdir resume now project-scoped; prompt-recall injects 3/3 relevant memories for real prompts through the exact installed hook command; stop-guard block/silent verified on 6 transcript shapes; hooks installed in `~/.claude/settings.json` with all non-memgit settings untouched
- Production store: `fsck` clean, index consistent, zero legacy CR objects (fix is purely preventive)

## Known gaps (deliberate, tracked for 0.5)

- Project labels are path-based, not git-aware: the same repo cloned at two paths = two scopes (family matching softens but doesn't solve this)
- `sync` never prunes memories whose markdown source was deleted (needs `--prune`)
- `fsck` doesn't parse-and-reserialize objects (would have caught the CR bug); `init` non-tty auto-imports without a `--no-import` flag
