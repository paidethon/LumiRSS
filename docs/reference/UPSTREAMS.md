# LumiRSS Reference Upstreams

> Purpose: pin research baselines so Lumi UI/behavior does not drift with
> upstream changes. All values below are verified against locally cloned
> repositories on 2026-08-28 (Gate 0C).

---

## 1. Rules

Reference repositories are:

- read-only;
- stored outside LumiRSS (`~/projects/LumiRSS-reference/`), never nested,
  vendored or added as Git submodules;
- pinned by exact commit SHA;
- used only after license/source review (see `LICENSE_AUDIT.md`);
- never a source of private user screenshots or browser session data.

Directory convention:

```text
../LumiRSS-reference/Folo
../LumiRSS-reference/OrigRead
../LumiRSS-reference/OrigRead-Desktop
```

---

## 2. Pinned baselines

| Project | Repository | Branch | Commit SHA | Retrieved | License | Lumi use |
|---|---|---|---|---|---|---|
| Folo | https://github.com/RSSNext/Folo | `dev` | `78f6bd1b745ba5d85027f6ca85ce60b06ca46569` | 2026-08-28 | AGPL-3.0 + special `icons/mgc` exception | Primary desktop/mobile UI and interaction research |
| OrigRead (Android) | https://github.com/ZGMFX01A/OrigRead | `main` | `18d3281de241fabc22c94d4cacb965ec1eaa1430` | 2026-08-28 | GPL-3.0 | Mobile patterns and multi-source discovery research |
| OrigRead-Desktop | https://github.com/ZGMFX01A/OrigRead-Desktop | `main` | `8b59bcb4ec63c4514e06e3863b1bc527eed861dd` | 2026-08-28 | AGPL-3.0-only | Settings, reader tools, panes, source discovery, AI panel research |

Notes verified at the pinned SHAs:

- Folo `dev` HEAD commit date: 2026-08-26 ("fix(mobile): fix settings
  header safe area and contrast").
- Folo license verified in `Folo/LICENSE` (GNU AGPL v3) and `Folo/README.md`
  ("icons/mgc directory is copyrighted by https://mgc.mingcute.com/ and
  cannot be redistributed").
- OrigRead-Desktop declares `"license": "AGPL-3.0-only"` in `package.json`;
  LICENSE file is GNU AGPL v3.
- OrigRead LICENSE file is GNU GPL v3 (Android project).

---

## 3. Folo scope

### Adopt as interaction reference

- compact Sidebar hierarchy;
- continuous Timeline density;
- Reader typography and whitespace;
- selection, hover, focus and disabled states;
- semantic surface/color thinking;
- popover/menu/tooltip micro-interactions;
- light/dark behavior;
- future AI floating panel presentation;
- distinct desktop/mobile composition.

### Do not adopt as product scope

- social/community graph;
- public profiles;
- recommendations/discovery economy;
- creator/reward/POWER systems;
- shared lists unless later explicitly approved;
- proprietary/restricted assets.

### Prohibited asset

Never copy or redistribute files from Folo's `icons/mgc` directory.

### Relevant source regions (verified to exist at the pinned SHA)

```text
apps/desktop/                      Electron desktop app
apps/mobile/                       mobile app
packages/internal/components/      shared UI components
packages/internal/store/           state management
packages/internal/hooks/
```

---

## 4. OrigRead-Desktop scope

Study:

- Settings layout and grouped controls (`src/` — Electron + React +
  TypeScript, verified at pinned SHA);
- Source discovery flow;
- RSSHub route/instance handling concepts;
- reader font/background/width controls;
- resizable panes;
- AI Summary positions/docks;
- dialogs/popovers/source switcher.

Do not copy the whole application, its full stylesheet or platform-specific
Electron behavior into Lumi Web.

---

## 5. OrigRead Android scope

Study:

- mobile information architecture;
- adaptive list/detail behavior;
- source-first discovery (URL → RSS → rel=alternate → common endpoints →
  RSSHub route → JSON API → site parsing fallback);
- RSSHub matching concepts;
- touch-target and navigation patterns.

Android Compose code is not directly portable to React. Prefer behavior
study and independent Web implementation.

---

## 6. Additional UI research projects

These are conceptual references only. Pin them (repository/commit/license)
before any code-level study.

| Project | Main value | Current action |
|---|---|---|
| FeedFlow | minimal cross-platform timeline, reading modes, three-pane desktop | visual/behavior research |
| NetNewsWire | native split-view, keyboard, pane sizing | interaction research |
| Read You | Material You mobile/adaptive reading | mobile research |
| Fluent Reader | desktop grouping/settings/dark theme | settings research |
| NewsFlash | adaptive GNOME reader | responsive research |
| Readeck | read-later/web clipping/highlights | Phase 2 product research |

---

## 7. Live audit baseline (Folo web, 2026-08-28)

Read-only audit of https://app.folo.is performed with the user's own
manually logged-in session. No credentials were touched; no screenshots
were captured (all data from DevTools computed styles). Viewport
1211×890, dark theme (light values measured by temporary, reverted
`data-theme` attribute flip).

### Layout

- Sidebar width 256px (resizable 256–300px, drag separator);
- Timeline column ~449px at audit viewport (resizable 300–600px);
- Reader occupies remaining width; at ≤~1211px an opened entry replaces
  the timeline (list ↔ detail), matching Lumi's current mobile pattern;
- Floating AI button bottom-right: 64×64, radius 16px (rounded-2xl).

### Sidebar

- Feed row: height 32px, padding 2px 10px, radius 6px, font 14px/500;
- hover token `--fo-item-hover` with 200ms transition (`duration-200`);
- text primary: 85% white (dark), unread counts: 50% white;
- brand/controls 32×32 icon buttons, radius 6px.

### Timeline item

- item height ~108px (80px without excerpt), padding 14px vertical,
  16px left / 12px right;
- favicon 24×24 (rounded-sm);
- source/time row: 10px/700 uppercase-style, 50% opacity;
- title: 14px/500, line-height 17.5px, up to 2 lines, break-words;
- excerpt: 13px, secondary color;
- thumbnail (when present): 80×80, rounded;
- hover: `--fo-item-hover` over full row, 200ms.

### Reader

- title ~27px/700, line-height 1.5;
- metadata row 10px/700 secondary;
- body base 14px/24px in `prose` container, width ~432px at audit pane;
- toolbar icon buttons 32×32, radius 6px.

### Theme tokens (Folo semantic variables)

```text
Dark:  --fo-background hsl(0 0% 7.1%)   #121212
       --fo-sidebar   hsl(220 8.1% 14.5%)
       --fo-border    hsl(0 0% 22.1%)
       --fo-item-hover  oklab(37.1% 0 0 / .3)
       --fo-item-active oklab(43.9% 0 0 / .4)
       --fo-text-primary 80% white; inactive 50% white

Light: --fo-background hsl(0 0% 100%)
       --fo-sidebar   hsl(240 4.8% 95.9%)
       --fo-border    hsl(20 5.9% 90%)
       --fo-item-hover  oklab(70.5% .004 -.014 / .2)
       --fo-item-active oklab(70.5% .004 -.014 / .3)
       --fo-text-primary 10% black

Font:  system-ui, "SN Pro", "PingFang SC", "Hiragino Sans GB",
       "Microsoft YaHei", "Noto Sans CJK SC", sans-serif
```

Theme mechanism: `html[data-theme="dark|light"]` + `html[data-viewport]`;
scrollbar thumb 6px, dark oklch(0.556 0 0), hover rgba(161,161,161,.5).

### Settings modal measurements (0010 audit, 2026-08-29)

Read-only audit of Folo's settings modal (user's logged-in session,
computed styles only):

```text
Modal:      951×801, radius 12px (top corners), white bg, thin border
Left nav:   13 categories, row 34px / pad 2px 10px / radius 8px / 16px font
Content:    px-32 padding, independent scroll area
Section:    title 13px/700/51% opacity, margin-top 40px between groups
Setting row: flex justify-between gap-4, label 14px/500 left,
            control right (Switch 40×24), row mt-16px mb-12px
```

Source-code cross-check: `modules/settings/modal/layout.tsx` (Resizable
950×800 default, minWidth 700) + `helper/setting-builder.tsx` (declarative
item model) + `tabs/` (13 category pages).

---

### Audit limitations

- Qoder browser panel viewport is limited (~1025–1211px wide); 1920/1440
  desktop and 390×844 mobile layouts could not be measured live;
- Settings dialog, AI Summary card, empty/loading/error states and mobile
  screens were not deeply audited live; supplement from the pinned Folo
  source (see §3 paths) before Gate 1.

### User-provided reference screenshots (2026-08-29)

The user supplied additional Folo reference screenshots (settings panel
  showing grouped rows/toggles/selects, reader+AI panel, overview, plus
  color/micro-interaction references). They are stored **locally only** at
  `~/projects/LumiRSS-reference/screenshots/user-provided/` because they
  contain the user's private subscription names — they must not be
  committed to Git (see SOURCE_MAP §4). They inform the Gate 4 Settings
  shell design (grouped settings rows: label + description left, control
  right) and the future AI panel layout.

---

## 8. Update procedure

To intentionally update an upstream baseline:

1. create a dedicated research task;
2. record old and new SHA;
3. read upstream changelog/diff for relevant components;
4. update screenshots/measurements only where needed;
5. review license changes;
6. list affected Lumi components;
7. obtain user approval;
8. update this file and `SOURCE_MAP.md`;
9. implement in a separate scoped change.

Never silently pull a new upstream revision in the middle of 0009.

---

## 9. Local verification commands

```bash
git -C ../LumiRSS-reference/Folo status --short --branch
git -C ../LumiRSS-reference/Folo rev-parse HEAD

git -C ../LumiRSS-reference/OrigRead status --short --branch
git -C ../LumiRSS-reference/OrigRead rev-parse HEAD

git -C ../LumiRSS-reference/OrigRead-Desktop status --short --branch
git -C ../LumiRSS-reference/OrigRead-Desktop rev-parse HEAD
```

Reference worktrees should remain clean.
