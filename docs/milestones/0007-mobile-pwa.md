# 0007 — Mobile & PWA

> Status: **Completed**
> Original spec: Git history (docs/specs/0007-*.md)

---

## Status

Completed (PR #13, `4f163d6`). All acceptance criteria of
Spec 0007 (AC1–AC28) met or explicitly marked; automated tests, lint,
production build, backend regression, real-browser smokes and a
reversible star smoke all pass.
Original spec available in Git history (`git show HEAD~:docs/specs/0007-mobile-pwa.md`).

## Goal

Make the same LumiRSS web app comfortable on phones and installable as
a PWA, without Service Worker, offline cache or any new dependency.

## Responsive architecture

```text
>=1024px (lg)                     <1024px
─────────────────────             ─────────────────────
MobileHeader  (display:none)      [☰] LumiRSS · scope   ← [← 返回] when reading
┌────────┬──────┬───────┐         ┌─────────────────────┐
│Sidebar │ List │ Reader│         │ Entry List  or  Reader (full screen) │
└────────┴──────┴───────┘         └─────────────────────┘
                                  Drawer(☰) → same <Sidebar />
```

- One component tree; layout decided purely by Tailwind `lg:` /
  `max-lg:` media queries. No `window.innerWidth`, no `useWindowSize`,
  no UA sniffing, no duplicated Mobile*/Desktop* components.
- The mobile list↔reader switch reads the **existing**
  `selectedEntryRef` (null → list, set → reader) to derive `hidden`
  classes in App.tsx — no second `mobilePane` state. Back =
  `selectEntry(null)`; the TanStack Query cache simply keeps showing
  (no reload, no detail re-fetch).
- Desktop ≥1024px behavior is unchanged from 0005/0006 (three panes,
  per-pane scrolling, `h-dvh`).

## Why CSS-first responsive

JS width checks don't react to rotation/split-screen without manual
listeners and UA strings are unreliable; CSS media queries are the
browser's native mechanism. JS here only handles interaction state
(drawer open, entry selection) — both already existed or are pure UI
state.

## Why selectedEntryRef drives the mobile Reader

`selectedEntryRef` already encodes "nothing selected / reading an
article" — exactly the phone's list-page/reader-page distinction. A
separate `mobilePane` state would be a second source of truth for the
same information. The 0005-frozen rule "view/feed change clears
selection" also gives navigation for free: switching views from the
drawer while reading lands back on the new list.

## Mobile drawer

- Same `<Sidebar />` component inside a fixed panel + backdrop (no
  MobileSidebar copy).
- Close: backdrop button / ✕ / Escape / completing a navigation.
- Navigation close is an **explicit optional `onNavigate` prop** on
  Sidebar — deliberately NOT event delegation (`closest('button')`
  would also close the drawer on the feeds retry button).
- A11y: non-modal semantics on purpose — `<aside aria-label="导航">`
  landmark, **no `aria-modal`**, no focus trap (we don't claim modal
  behavior we don't implement; a future `role="dialog"` upgrade would
  need WAI modal focus containment). Menu button keeps
  aria-expanded/aria-controls/label; backdrop is a real `<button>`.
- State: `mobileSidebarOpen` in the existing Zustand store — the only
  new UI state of this milestone.

## Safe areas & viewport

`viewport-fit=cover` added to the viewport meta; four CSS variables
(`--safe-top/right/bottom/left` = `env(safe-area-inset-*)`) defined
once in `:root` and used in a handful of places: MobileHeader top,
drawer panel (with `max(normalPadding, inset)` for left/right), entry
list footer bottom, reader bottom. `h-dvh` kept (dynamic viewport
height beats `100vh` under mobile URL-bar collapse).

## Touch / UX details

- `max-lg:min-h-11` (44px) on nav buttons, menu/back, retry, load more,
  and reader state buttons; reader header already wraps via flex-wrap.
- Phone entry titles wrap (`max-lg:line-clamp-3` instead of one-line
  truncate); metadata tightened.
- Reader padding `max-lg:px-5` (~20px); desktop `max-w-[44rem]`
  untouched. `.article-content code { overflow-wrap: anywhere }` added
  (img/pre/table protections already existed from 0006).

## PWA manifest

Hand-written static `public/manifest.webmanifest` (no plugin): id/name/
short_name/description/start_url `/`/scope `/`/`display: standalone`/
background & theme `#ffffff` (matches `--surface`), icons 192/512 +
maskable-512. No shortcuts/share_target/etc. Static public metadata
only. index.html gained manifest link, theme-color and
apple-touch-icon links; viewport-fit=cover added to the existing meta.

## PWA icon generation method

The interesting part of this milestone, because the machine has **no**
ImageMagick/Inkscape/rsvg-convert/PIL/cairosvg/Chromium CLI (all
checked) and installing any of them was forbidden:

1. *Attempt 1* — managed browser (browser-use MCP) canvas export:
   SVG → canvas(exact 192/512/180) → `toDataURL` → base64 back through
   the tool conversation. Works in principle, but transporting tens of
   KB of base64 through model-context transcription proved unreliable
   (a length+FNV-1a checksum caught a corrupted copy; an earlier
   localhost POST relay also failed because the browser is sandboxed
   away from the machine's network).
2. *Final method* — fully local, zero-dependency: a throwaway Node
   script using only `node:zlib` — hand-written PNG encoder
   (IHDR/IDAT/IEND, CRC32, filter 0) + pure-math rasterizer of the icon
   geometry with 4×4 supersampling antialiasing. Produces exact-pixel
   192/512/maskable-512/180 PNGs matching the committed SVG sources.
   Verified with `file` + a Vitest IHDR parser, and visually.

Icons reuse the favicon's purple family (#7e14ff / #47bfff) with
flat colors (gradients would balloon PNG size for no benefit at this
scale); the maskable version fills the whole canvas and keeps the
white L inside ~70% diameter — more conservative than the 80% minimum
safe zone.

## Why no Service Worker

MDN: a Service Worker is **not** required for PWA installability —
manifest + icons + secure context suffice. LumiRSS's MVP explicitly
does not do offline, and a Service Worker would prematurely introduce
stale-shell/stale-entry/cache-invalidation complexity. 0007 therefore
ships manifest/icons/standalone and nothing else; nothing anywhere
claims offline support.

## Installability verification

- `GET /manifest.webmanifest` → 200 `application/manifest+json`; all
  four icon URLs → 200 `image/png` (real dev server).
- `document.querySelector('link[rel=manifest]')` resolves in the live
  page; `matchMedia('(display-mode: standalone)')` reports the current
  browser mode as expected.
- OS-level actual installation: **USER/MANUAL VERIFICATION** (honest:
  not performed by the agent; no install prompt UI is built on
  purpose — users install via the browser's native Install / Add to
  Home Screen, which also covers iOS where `beforeinstallprompt`
  doesn't exist).

## Actual viewport checks

- **856×541 (live browser, real FreshRSS data)** — VERIFIED: mobile
  shell (header/list/footer), drawer open → Unread (12 unread entries,
  drawer auto-closed, aria-expanded false→true→false), entry →
  full-screen reader (list hidden), back → list restored, article with
  31 images + 53 links: **0px horizontal overflow** at document level,
  reversible star smoke (aria-pressed false→true→false, label
  收藏→取消收藏→收藏, final == original), screenshots captured and
  reviewed.
- **390 / 430 / 768** — PARTIALLY VERIFIED: same breakpoint bucket
  (<1024) as the verified 856px run; CSS rules for the mobile classes
  verified compiled (`max-lg:*` rules present in the built CSS).
  Pixel-accurate screenshots impossible (window.resizeTo ignored by
  the managed browser — same tooling limitation as 0006); please spot
  check a real phone when convenient.
- **1024 / 1280 / 1440 desktop** — PARTIALLY VERIFIED: `lg:grid`/
  `lg:block`/`lg:grid-cols-[240px_400px_1fr]` rules verified in the
  built CSS, desktop aside/grid structure unchanged from 0005/0006,
  and all 97 pre-0007 desktop-era tests still pass; no real ≥1024px
  viewport screenshot (resize unavailable).

## Problems

| 现象 | 原因 | 层级 | 解决 |
| --- | --- | --- | --- |
| playwright MCP 无法启动 | 需要的 Chrome 发行版不存在且下载受限 | tooling | 改用 browser-use MCP |
| 浏览器 fetch 127.0.0.1:9876 失败 | MCP 浏览器与沙箱网络隔离 | tooling | 放弃 POST 中转方案 |
| 长base64 转录后 PNG 损坏/长度漂移 | 大数据经模型上下文转录不可靠 | process | FNV-1a+长度校验拦截；最终改为本地纯 Node 生成，彻底绕开转录 |
| `lg:max-[1100px]:` 变体无 CSS 输出 | Tailwind v4 不支持该叠加变体（Spec 预案已预料） | css | 按预案退化为统一 `240px_400px_1fr`（列宽微调，非布局模式变化） |
| tsc 报 Cannot find name 'node:fs' | 测试用 node API 但 tsconfig types 未含 node | build | tsconfig.app.json `types` 加 `"node"`（@types/node 本就存在） |
| drawer 测试偶发拿不到「重试」按钮 | drawer 挂载新 observer 触发 stale-on-mount 后台 refetch，期间显示 skeleton | tests | waitFor 等 refetch 完成后再断言 |
| Test F 断言总 fetch 数增加 | ReaderPlaceholder 重挂载触发 entries 后台 refetch（0005 既有行为，数据不丢、无 loading） | tests | 断言语义改为：列表立即从 cache 恢复 + Detail 不重复请求 |

## Solutions

See table above. All fixes stayed at the correct layer; none touched
the BFF, the frozen architecture, or the Reader's security boundaries.

## What I learned

- Installability ≠ offline. Manifest + secure context make an app
  installable; the Service Worker is the *offline* mechanism, and it
  is optional. Deciding not to ship one removed a whole class of
  cache-invalidation bugs from this milestone.
- One component tree + CSS beats two React apps: the entire mobile
  shell needed only two small new components (MobileHeader,
  MobileNavigationDrawer) and one boolean of new state.
- Transporting bulk binary data through an agent conversation is a
  hazard: checksums catch corruption, but generating data *locally*
  with stdlib only (zlib + hand-rolled PNG chunks) is the robust
  answer when no rasterizer exists.
- a11y semantics must match implemented behavior: claiming
  `role="dialog"`/`aria-modal` without focus containment is worse than
  an honest non-modal `<aside>` landmark.
- jsdom tests assert DOM semantics; visual truth needs a real browser
  — here verified via a11y snapshots, numeric overflow measurements
  and screenshots together, with resize-dependent checks honestly
  marked UNVERIFIED/PARTIAL.

## Tests / Lint / Build / Backend

- Frontend: **121 passed** (97 pre-existing + 24 new: drawer A–D +
  a11y incl. retry-doesn't-close, mobile reader E/F/G, manifest/meta/
  PNG-IHDR H). `pnpm lint` 0 problems. `pnpm build` (tsc -b + vite)
  succeeds.
- Backend: `uv run pytest` → **121 passed**, `services/bff` diff = 0.

## Next

0008 — RSSHub (not started).
