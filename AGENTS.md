# LumiRSS Agent Guide

Start here. This is the project map for any agent working in LumiRSS.
It contains only long-term stable information. Current progress lives in
`docs/PROJECT_STATE.md`.

## Project

LumiRSS is a single-user, self-hosted, AI-enhanced RSS reader.

Product scope and requirements are defined in `docs/PRD.md`
(v5.0 Reboot Baseline is the highest product authority).

## Frozen architecture

```text
RSSHub → FreshRSS → FreshRSSAdapter → FastAPI BFF → React Web
```

Content sources: native RSS goes directly into FreshRSS; websites without
standard RSS are converted into feeds by RSSHub first.

- **RSSHub** converts websites without standard RSS into feeds. It is an
  upstream of FreshRSS, NOT a second LumiRSS data source. The BFF never
  talks to RSSHub directly.
- **FreshRSS** is the ONLY RSS source of truth. It owns feeds, categories,
  entries, read state, starred state and RSS fetching. The BFF never
  re-implements RSS fetching.
- **FreshRSSAdapter** translates the FreshRSS API into LumiRSS domain
  models, so the rest of the project never depends on FreshRSS shapes.
- **FastAPI BFF** is the LumiRSS backend and the only API the web client
  talks to.
- **SQLite** stores ONLY AI results, derived cache and LumiRSS settings.
  Copying the full FreshRSS RSS database into SQLite is forbidden.
- **React Web** accesses data ONLY through the LumiRSS BFF. Direct calls
  from the frontend to FreshRSS, RSSHub or the runtime AI provider are
  forbidden.
- **AI** is an optional enhancement. AI failure must never block normal
  RSS reading. Development tools such as Qoder are not runtime AI
  providers.

This architecture is frozen. Do not change it inside a task.

## Current state

Current progress is recorded in `docs/PROJECT_STATE.md`.

Do not duplicate progress details in this file.

## Development behavior

Before working:

1. Read `docs/PRD.md`.
2. Read `docs/ARCHITECTURE.md`.
3. Read `docs/PROJECT_STATE.md`.
4. Read the current spec, if one exists.
5. Check `git status`.

While working:

- Finish only the current goal at a time.
- No unrelated refactors.
- No implementing future features early.
- No adding dependencies without a real need.
- Never change the frozen architecture.
- "Maybe needed later" is not a reason to create an abstraction, a
  directory or an empty placeholder.

When done, report honestly:

- What changed and why.
- What was actually run.
- Which checks passed, which were not run, which cannot be verified.
- Whether `git diff` contains anything outside the task scope.

Never present "should work" as "ran successfully". Only report real
results.

## Git safety

By default, agents MUST NOT run:

- `git commit`
- `git push`
- `git reset --hard`
- force push
- delete branch

unless the user explicitly requests the action.

Preserve all user changes and unrelated work. Never rewrite history to
clean a dirty worktree.

## Documentation map

- `docs/PRD.md` — product requirements (v5.0)
- `docs/ARCHITECTURE.md` — architecture explanation
- `docs/PROJECT_STATE.md` — current project state
- `README.md` — human onboarding
