# LumiRSS UI Reboot v1

> Approved design and implementation specification for milestone 0009 (user-approved 2026-08-28, after Gate 0 verification). Implementation gates proceed one at a time, each requiring user approval.
>
> This document changes presentation architecture, not the completed RSS data model or API behavior.

---

## 1. Design objective

The current LumiRSS interface is functional but visually temporary. The reboot must produce a product that feels:

```text
quiet
precise
content-first
native-like
soft but not decorative
dense but not crowded
recognizably Lumi
```

Target formula:

```text
Folo structure and interaction
+ OrigRead Desktop settings and reader tools
+ muted palette from the user's color reference
+ Lumi pale blue-indigo identity
```

Not the target:

- a Folo clone;
- a generic AI dashboard;
- a card-heavy SaaS interface;
- a purple OrigRead reskin;
- a desktop layout shrunk onto a phone.

---

## 2. Reference hierarchy

### Primary — Folo

Study:

- desktop three-pane shell;
- compact Sidebar;
- continuous Timeline;
- feed/source metadata hierarchy;
- selected/hover/read/unread states;
- Reader title/body hierarchy;
- toolbar icon treatment;
- light/dark surface layering;
- popover/menu/tooltip details;
- AI Summary and floating AI panel;
- restrained motion.

### Secondary — OrigRead Desktop

Study:

- Settings navigation and grouped rows;
- source discovery UX;
- RSSHub-related controls;
- reader appearance controls;
- resizable panes;
- AI summary dock/tool patterns;
- dialogs and source switchers.

### Supporting references

- FeedFlow: modern cross-platform timeline and reading modes;
- NetNewsWire: native split-view, keyboard and pane behavior;
- Read You: Material You mobile list/detail adaptation;
- Fluent Reader: desktop settings/grouping/dark-mode patterns;
- NewsFlash: adaptive GNOME reader behavior;
- Readeck: later read-later/web-clipping concepts only.

### User palette reference

The supplied Obsidian image is a **color reference only**:

- warm gray/rose-neutral canvas;
- muted blue, green, orange, purple, cyan, rose and red;
- translucent low-saturation selected rows;
- no layout copying.

---

## 3. Product-level UX rules

1. Reading content has the highest visual priority.
2. Sidebar and Timeline are continuous surfaces, not stacks of cards.
3. A card is used only when information has real semantic containment, such as AI Summary or a Settings group.
4. Accent color is scarce and meaningful.
5. Selected state normally uses a subtle neutral or tinted surface, not a saturated button.
6. Borders are separators, not decoration.
7. Shadows communicate elevation only: popover, dialog, floating panel.
8. AI is available but never visually dominates normal reading.
9. Every desktop behavior has a deliberate tablet/mobile expression.
10. Theme/custom color support is architectural, not a late CSS patch.

---

## 4. Default theme — Lumi Mist / 雾光

These values are starting candidates, not final measured values. Qoder must validate contrast and compare visual output.

### 4.1 Light palette

```css
:root,
[data-theme="lumi-mist-light"] {
  --lumi-canvas: #f6f4f4;
  --lumi-sidebar: #f1eeee;
  --lumi-surface: #fbfafa;
  --lumi-surface-elevated: #ffffff;
  --lumi-reader: #fcfbfb;

  --lumi-surface-hover: #efeced;
  --lumi-surface-selected: #e7e5e9;
  --lumi-surface-pressed: #dfdde2;

  --lumi-text-primary: #29282c;
  --lumi-text-secondary: #77747b;
  --lumi-text-tertiary: #9b979f;
  --lumi-text-disabled: #bbb7be;

  --lumi-border: rgba(52, 47, 57, 0.10);
  --lumi-separator: rgba(52, 47, 57, 0.075);

  --lumi-accent: #6d78e8;
  --lumi-accent-hover: #616cd8;
  --lumi-accent-pressed: #5660c8;
  --lumi-accent-soft: #eceeff;
  --lumi-accent-contrast: #ffffff;
  --lumi-focus-ring: rgba(109, 120, 232, 0.38);
}
```

### 4.2 Dark palette

```css
[data-theme="lumi-mist-dark"] {
  --lumi-canvas: #18181a;
  --lumi-sidebar: #1d1d20;
  --lumi-surface: #222226;
  --lumi-surface-elevated: #28282d;
  --lumi-reader: #1b1b1e;

  --lumi-surface-hover: #29292d;
  --lumi-surface-selected: #303036;
  --lumi-surface-pressed: #38383f;

  --lumi-text-primary: #ececef;
  --lumi-text-secondary: #aaa8b0;
  --lumi-text-tertiary: #77757d;
  --lumi-text-disabled: #5f5d64;

  --lumi-border: rgba(255, 255, 255, 0.10);
  --lumi-separator: rgba(255, 255, 255, 0.07);

  --lumi-accent: #8993f5;
  --lumi-accent-hover: #98a1ff;
  --lumi-accent-pressed: #7782e6;
  --lumi-accent-soft: rgba(137, 147, 245, 0.14);
  --lumi-accent-contrast: #15151a;
  --lumi-focus-ring: rgba(137, 147, 245, 0.48);
}
```

### 4.3 Category palette

```css
--lumi-category-blue: #79a9d6;
--lumi-category-green: #76a08b;
--lumi-category-orange: #c98d59;
--lumi-category-purple: #8b79b8;
--lumi-category-cyan: #6f9fae;
--lumi-category-rose: #b87d91;
--lumi-category-red: #b8656b;
```

Usage:

- small icons/dots;
- category labels;
- 6–12% tinted selected/hover surfaces;
- never a full rainbow dashboard.

---

## 5. Theme model

### 5.1 App appearance

```text
Mode
- Follow system
- Light
- Dark

Palette
- Lumi Mist (default)
- Neutral White (later)
- Warm Paper (later)
- custom preset import/export (future)

Accent
- Lumi Indigo
- blue / purple / green / orange presets
- custom color
```

### 5.2 Reader appearance

Independent from app appearance:

```text
Reader background
- Follow app
- Paper white
- Warm white
- Sepia
- Soft green
- Custom

Font
Font size
Line height
Maximum content width
```

### 5.3 Custom accent behavior

The user chooses one base accent. The system derives hover, pressed, soft, focus and contrast variants and rejects unreadable combinations. Do not expose ten independent color inputs in the first version.

### 5.4 Persistence

0009 must inspect the current settings architecture.

Preferred final persistence is server-side Lumi settings. If that API does not yet exist, 0009 may use a clearly documented temporary local preference store only for non-sensitive appearance values, with a migration note for 0014. Do not invent a backend API during a UI-only milestone.

---

## 6. Typography

Start from a reliable system sans stack. Do not bundle proprietary fonts.

Suggested scale:

| Token | Size | Line height | Use |
|---|---:|---:|---|
| `text-xs` | 11–12 | 16 | timestamps, source metadata |
| `text-sm` | 13 | 18 | Sidebar, controls, secondary text |
| `text-md` | 14–15 | 20 | Timeline title/body UI |
| `text-lg` | 17–18 | 26 | Reader body base |
| `heading-sm` | 20–22 | 28 | pane/page heading |
| `heading-lg` | 32–38 | 1.15–1.25 | Reader title desktop |
| `heading-mobile` | 26–30 | 1.2 | Reader title mobile |

Rules:

- avoid excessive bold weights;
- titles can use 600–700;
- metadata should be visually quiet without becoming unreadable;
- article body line-height target around 1.7–1.8;
- long Chinese and English titles must wrap gracefully.

---

## 7. Spacing, radii and elevation

### 7.1 Spacing scale

Prefer a small systematic scale:

```text
2 / 4 / 6 / 8 / 10 / 12 / 16 / 20 / 24 / 32 / 40 / 48
```

### 7.2 Radius scale

```text
4px   tiny badge/detail
6px   thumbnail/small control
8px   nav item/button/icon button
10px  input/select/menu/popover item group
12px  settings group/dialog body
14px  AI summary/large content card
16px  floating AI panel/major overlay
999px true pill/switch only
```

Do not use one radius everywhere.

### 7.3 Elevation

```text
flat surfaces       no shadow
popover/menu        soft small shadow
modal/dialog        medium diffuse shadow
AI floating panel   medium large diffuse shadow
```

Selected Timeline/Sidebar rows should not float.

---

## 8. Motion

Suggested durations:

```text
hover/focus feedback       100–120ms
menu/popover               120–160ms
modal                      160–180ms
sidebar/pane transition    180–220ms
bottom sheet               200–260ms
```

Use CSS transitions for simple micro-interactions. Use a motion library only where it materially improves overlays/sheets and after dependency review.

Allowed:

- opacity;
- 1–3px translate;
- subtle scale around 0.98→1 for overlays;
- width/pane transitions where they do not cause content jitter.

Avoid:

- list row lift/scale;
- bounce;
- glow;
- decorative continuous animation;
- motion that ignores `prefers-reduced-motion`.

---

## 9. Desktop App Shell

### 9.1 Layout

Current public baseline:

```text
240px | 400px | 1fr
```

0009 may refine sizes while preserving behavior:

```text
Sidebar: 220–260px
Timeline: 360–440px
Reader: minmax(0, 1fr)
```

Use CSS Grid or an equivalent resilient layout. The Reader must use `min-width: 0` to prevent overflow.

### 9.2 Pane hierarchy

```text
Sidebar background
  < Timeline surface
  < Reader surface/content
  < Popover/dialog/floating AI elevation
```

Separate panes with subtle 1px separators, not boxed cards.

### 9.3 Resize/collapse

0009 should prepare consistent divider/collapse behavior. Persistent arbitrary pane sizes may wait until 0014 if not already supported.

---

## 10. Sidebar

### 10.1 Structure

```text
Brand / compact actions
Primary views
  All
  Unread
  Starred
Subscriptions
  folders/categories
  feeds
Bottom utility
  Add source
  Settings
```

Do not copy Folo-specific content-type/community navigation unless it maps to an approved Lumi feature.

### 10.2 Dimensions

Suggested:

```text
item height       34–36px desktop
icon              17–18px
horizontal pad    8px
row gap           8px
radius            8px
section label     11–12px
```

### 10.3 States

- default: transparent;
- hover: subtle neutral surface;
- selected: subtle neutral/tinted surface;
- focus: visible ring/inset outline;
- unread counts: tertiary text or small badge;
- category color: icon/dot and soft tint only;
- expanded folder: clear chevron state and accessible disclosure semantics.

### 10.4 Mobile

The same navigation content appears in a Drawer, not a second duplicate implementation. Focus must be trapped and restored; swipe behavior is optional, not required.

---

## 11. Timeline

The Timeline is the highest-priority visual component after the shell.

### 11.1 Continuous list

Do not render each entry as a floating card. Use one continuous pane with selected/hover surfaces and optional separators.

### 11.2 Information hierarchy

Ideal row model:

```text
[favicon] Source · time                       [optional thumbnail]
          Article title
          Short excerpt / metadata
```

Available-data fallback:

- no favicon: generated neutral source mark;
- no excerpt: omit cleanly;
- no thumbnail: text layout expands;
- no author: do not leave empty separators;
- long source/title: clamp/wrap according to viewport and accessibility needs.

### 11.3 Density

Target row height is content-dependent, approximately 82–112px in comfortable desktop mode. Do not enforce a single fixed height that clips multilingual titles.

### 11.4 Read/unread/starred

Unread can use:

- title weight;
- a small dot;
- restrained accent.

Do not rely only on color. Star is a secondary action/status and should not overwhelm the title.

### 11.5 Selected state

Use a quiet neutral/tinted surface similar in visual weight to Folo. No thick borders or strong brand fill.

### 11.6 Actions

Hover-revealed actions must also be keyboard reachable and available through a more menu/context menu. Mobile must not depend on hover.

---

## 12. Reader

### 12.1 Content layout

```text
Reader toolbar
article metadata
article title
optional summary/action region
article content
```

### 12.2 Width and rhythm

Recommended initial limits:

```text
normal content width: about 720–780px
wide option: about 840–900px
body font: around 17px
body line height: around 1.75
```

The Reader may center content inside a fluid pane. It should not look like a giant card.

### 12.3 Toolbar

- compact icon buttons;
- 30–34px visual control size on desktop;
- accessible name/tooltip;
- safe actions: mark read, star, open original, reader settings, future AI;
- destructive actions separated and confirmed where applicable.

### 12.4 HTML boundary

Preserve the existing DOMPurify-based sanctioned HTML boundary. The UI reboot must not relax sanitization for prettier embeds.

### 12.5 AI Summary — later

Inline AI Summary belongs after title/metadata and before body. Style:

- light semantic card;
- 14px radius;
- subtle border;
- small accent icon/title;
- provider/model/time/status metadata available but quiet;
- collapsible/retry controls later.

Do not implement AI requests in 0009.

---

## 13. Settings shell

The visual shell may be prepared in 0009; service-backed settings arrive later.

### 13.1 Desktop structure

```text
Settings modal/page
├── left navigation
└── content
    ├── page title/description
    └── grouped settings sections
```

Suggested categories:

```text
General
Appearance
Reading
Sources
AI
Data & Backup
Advanced
About
```

### 13.2 Setting group

- one 12px-radius group;
- subtle border;
- no ordinary shadow;
- internal separators;
- row 56–68px depending on description;
- label + explanatory text left;
- control right;
- mobile stacks when needed.

### 13.3 Planned source settings

Clearly label placeholders/planned controls rather than creating fake functionality:

- FreshRSS status and normal subscription management later;
- RSSHub status/catalog/config later;
- advanced links to upstream UI as escape hatches.

---

## 14. AI conversation presentation — future-ready shell

### 14.1 Large desktop

Default future mode:

```text
right-side floating panel
width 400–460px
min 360px
max around 520px
height around 78–86vh
right/top inset 16–24px / 72–88px
radius 16px
```

It overlays the Reader rather than becoming a permanent fourth data column.

### 14.2 Smaller desktop/tablet

Use a right Drawer or docked panel. The Reader should remain usable and focus behavior correct.

### 14.3 Mobile

Use a Bottom Sheet:

- initial 55–70% height;
- expandable to fullscreen;
- dismiss by explicit control and supported gesture;
- title/context and input remain reachable above safe areas.

Long conversations may navigate to a fullscreen route.

### 14.4 Shared core

Do not build separate chat logic for each presentation. Later architecture:

```text
AiChatCore
+ DesktopFloatingContainer
+ DrawerContainer
+ BottomSheetContainer
+ FullscreenRouteContainer
```

0009 only creates the overlay layer and component boundary if needed.

---

## 15. Menus, popovers and micro-details

Use the supplied model-selector screenshot as a micro-interaction reference:

- 6–8px outer padding;
- row height around 36–40px;
- 7–8px row radius;
- selected state neutral rather than saturated;
- secondary values aligned right and lower contrast;
- separators only between semantic groups;
- one shadow on the popover, no row shadows;
- footer action separated cleanly.

Every menu/select/feed chooser/model chooser should share the same primitive.

---

## 16. Responsive design

### 16.1 ≥1440px

- full Sidebar/Timeline/Reader;
- comfortable Reader margins;
- future floating AI panel;
- no horizontal page scroll.

### 16.2 1200–1439px

- slightly compact panes;
- still three-pane where content remains usable;
- future AI overlay/drawer.

### 16.3 1024–1199px

- preserve current desktop threshold behavior unless testing supports a better transition;
- Sidebar may collapse/drawer;
- Timeline + Reader remain primary.

### 16.4 768–1023px

- navigation drawer;
- list/detail flow or carefully tested two-pane tablet layout;
- no tiny fixed three-pane columns;
- future AI drawer/sheet.

### 16.5 <768px

- single-column Timeline page;
- article opens Reader page/state;
- top app bar with back/actions;
- bottom navigation only if it improves approved primary tasks;
- AI future Bottom Sheet/fullscreen;
- source/settings forms stack vertically;
- safe-area insets honored.

### 16.6 Mobile timeline

- compact but readable source/time row;
- title wraps to 2–3 lines;
- excerpt optional;
- thumbnail on right when available;
- swipe actions are optional and must have button alternatives.

### 16.7 Mobile reader

- title 26–30px;
- body 16–18px according to setting;
- controls reachable and not crowded;
- sticky toolbar only if it does not obscure content;
- AI and appearance actions accessible from a concise menu.

---

## 17. Accessibility

Mandatory:

- all icon buttons have labels;
- keyboard selection can move through navigation/list safely;
- focus ring is visible in every theme;
- dialogs/drawers/sheets trap focus;
- focus returns to the trigger on close;
- `Escape` closes appropriate overlays;
- selected state has non-color cues;
- minimum contrast is checked;
- reduced motion is honored;
- primary mobile targets are around 44px;
- Reader headings/links/lists retain semantic structure;
- loading states use accessible status where helpful.

---

## 18. Implementation sequence

### Gate A — Reference and audit

- pin repositories;
- browser read-only audit;
- measure components;
- source/license maps;
- current UI inventory;
- no code changes.

### Gate B — Foundations

- tokens;
- theme switching infrastructure;
- typography/spacing/radius/shadow/motion;
- icon decision;
- primitives;
- visual playground/story route if lightweight.

User review required before core pages.

### Gate C — App Shell and Sidebar

- pane surfaces/separators;
- navigation hierarchy;
- selected/hover/focus states;
- desktop/mobile drawer;
- preserve current view/feed selection behavior.

### Gate D — Timeline

- source metadata hierarchy;
- responsive row composition;
- read/star states;
- optional thumbnail/fallback;
- loading/empty/error;
- pagination behavior unchanged.

User review required before Reader.

### Gate E — Reader

- toolbar;
- headline/metadata/content rhythm;
- reader theme hooks;
- safe article HTML unchanged;
- desktop/mobile behavior.

### Gate F — Settings shell and overlay layer

- settings navigation/groups;
- appearance controls supported by current persistence;
- future AI panel slot;
- menus/dialogs/popovers unified.

### Gate G — Regression and polish

- light/dark/system;
- viewport matrix;
- keyboard/accessibility;
- tests/lint/build;
- visual comparison;
- docs/source/license update.

---

## 19. Required screenshots

Capture at least:

```text
1920 × 1080 desktop light
1920 × 1080 desktop dark
1440 × 900 desktop light
1024 × 768 compact/tablet landscape
820 × 1180 tablet portrait
390 × 844 mobile list
390 × 844 mobile reader
```

States:

- all entries;
- unread;
- feed selected;
- entry selected;
- long title/source;
- no image;
- empty;
- loading;
- API error;
- settings;
- menu/popover;
- drawer.

Private logged-in Folo screenshots remain local and gitignored. Lumi screenshots may be committed only when they contain safe test data.

---

## 20. Visual acceptance checklist

### Shell

- [ ] Pane backgrounds have deliberate hierarchy.
- [ ] No card boxes around entire panes.
- [ ] Dividers are subtle and consistent.
- [ ] Reader remains the visual destination.

### Sidebar

- [ ] Compact but readable.
- [ ] Selected/hover/focus are distinct.
- [ ] Folder hierarchy is clear.
- [ ] Category colors are muted and restrained.
- [ ] Mobile Drawer reuses the same source of truth.

### Timeline

- [ ] Continuous list, not card stack.
- [ ] Source/time/title/excerpt hierarchy is clear.
- [ ] Selected row resembles the intended Folo level of emphasis.
- [ ] Read/unread does not rely on color alone.
- [ ] Optional images do not cause layout jumps.

### Reader

- [ ] Title/body widths and rhythm support long reading.
- [ ] Toolbar is compact and accessible.
- [ ] Article HTML remains sanitized.
- [ ] App and Reader backgrounds can differ.

### Components

- [ ] One Button/IconButton system.
- [ ] One Menu/Popover/Select system.
- [ ] One focus-ring system.
- [ ] Radius/shadow rules are followed.
- [ ] Hard-coded migrated brand colors are removed.

### Responsive

- [ ] Existing list↔reader flow remains functional.
- [ ] No horizontal overflow at target widths.
- [ ] Primary mobile targets are usable.
- [ ] Overlay/drawer focus is correct.

---

## 21. Behavior regression checklist

- [ ] Feeds still load through BFF.
- [ ] Entry filters still work.
- [ ] Cursor pagination still works.
- [ ] Detail loads only when selected.
- [ ] Opening does not mark read.
- [ ] Explicit read/unread works.
- [ ] Star/unstar works.
- [ ] Query invalidation reflects FreshRSS state.
- [ ] Original link validation remains safe.
- [ ] HTML sanitization tests remain green.
- [ ] Mobile back returns to list without unnecessary reload.
- [ ] PWA Manifest remains valid.

---

## 22. Explicit prohibitions during 0009

Do not:

- redesign FastAPI contracts;
- add AI provider calls;
- implement source discovery;
- add subscription mutations;
- add Docker socket access;
- copy Folo `icons/mgc`;
- paste entire upstream CSS/component trees;
- add a heavyweight UI framework without approval;
- rewrite state management for style reasons;
- mark planned Settings controls as functional;
- commit private reference screenshots;
- claim pixel parity without measurement/evidence.

---

## 23. Definition of done

UI Reboot v1 is done when:

- the user approves Sidebar + Timeline + Reader screenshots;
- one semantic theme/token system drives migrated UI;
- the default Lumi Mist theme and dark mode are coherent;
- app/reader theme separation is represented correctly;
- responsive behavior works at the required matrix;
- keyboard/focus basics work;
- all existing behavior tests and builds pass, or failures are accurately isolated;
- source/license traceability is complete;
- documentation describes implemented vs planned states accurately;
- no commit/push occurs before approval.

