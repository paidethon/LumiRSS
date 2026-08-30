# 0006 — Reader

> Status: **Completed**
> Original spec: Git history (docs/specs/0006-*.md)

---

## Status

Completed. All acceptance criteria of
[Spec 0006](../specs/0006-reader.md) (AC1–AC28) met; automated tests,
lint, production build, real integration smokes and reversible state
smokes all pass. Work is NOT committed — parked in the worktree for
human review.

## Goal

Turn the 0005 reader placeholder into a real reading pane:

```text
selectedEntryRef → TanStack Query → GET Detail
→ DOMPurify → ArticleContent → read/star explicit controls
```

## Reader architecture

```text
Zustand (UI state only: view / selectedFeedUrl / selectedEntryRef)
        ↓
useEntryDetail(entryRef)          useEntryStateMutation()
  queryKey ["entry", ref]           one shared mutation instance
  enabled: ref !== null             mutationFn → PATCH state (set semantics)
  AbortSignal on selection change   onSuccess: invalidate
        ↓                             ["entry", variables.entryRef] (exact)
  GET /api/v1/entries/{ref}          + ["entries"] (prefix, all scopes)
        ↓
  Reader.tsx state machine:
  no-selection → placeholder
  pending      → skeleton
  404          → "已不存在" + 返回文章列表
  error        → 加载失败 + 重试
  success      → ReaderHeader (key=entryRef) + ArticleContent
```

Server state stays entirely in TanStack Query; Zustand is untouched
(zero changes to `reader-ui.ts`).

## Entry Detail contract change

`GET /api/v1/entries/{entryRef}` gained exactly one field:

- `contentHtml: string | null` — the raw HTML FreshRSS has stored for the
  entry (`summary.content`). Missing or empty upstream HTML normalizes to
  `null`. `contentText` is unchanged and still always present.

Bounded changes: `models.py` (`EntryDetail.contentHtml` + docstring) and
`adapters/freshrss.py` (`get_entry` passes `base["content_html"] or None`).
`main.py` needed zero changes (response_model serializes the new field).
The entry list (`EntryListItem`) was not touched and tests assert no body
fields leak into it.

## contentHtml trust boundary

FreshRSS entry HTML comes from **external RSS feeds** — anyone can publish
a feed, so the HTML can carry `<script>`, `onerror=`, `javascript:` hrefs.
"Returned by my own BFF" does not make it trusted: the BFF is a
transporter, not a sanitizer. The BFF therefore only passes the HTML
through (documented as *untrusted upstream HTML* in models/adapter and in
the web types), and the **web client sanitizes right before rendering**:

```text
raw contentHtml (untrusted)
  → DOMPurify.sanitize (ONLY call site: lib/sanitize-article-html.ts)
  → sanitized (cleaned for the ArticleContent HTML sink)
  → dangerouslySetInnerHTML (ONLY use in the app: ArticleContent.tsx)
```

The same reasoning applies to `EntryDetail.url`: the "open original" link
is only rendered when `safeExternalHttpUrl()` (absolute http/https only)
accepts it.

## DOMPurify design

- `USE_PROFILES: { html: true }` — pure HTML profile, no SVG/MathML.
- `FORBID_TAGS`: form, input, button, textarea, select, option, iframe,
  object, embed, style, template — interactive/embedded elements that
  don't belong in a reader.
- `FORBID_ATTR: ['style']` — inline styles removed.
- Script tags, `on*` handlers and `javascript:` URLs are removed by
  DOMPurify's own default rules; we do NOT hand-roll any URI regex.
- After sanitize, the string is never modified again (no regex replaces)
  — post-processing would void the sanitizer's guarantees.
- Version: dompurify ^3.4.14 (npm dist-tags.latest at spec time), the
  only new runtime dependency of this milestone.

## Why a sanitizer is required

React escapes text by default, but the moment you insert an HTML string
into the DOM via `dangerouslySetInnerHTML`, the browser parses it as
markup — and would execute any script/event-handler payloads inside.
Sanitizing to a known-safe element/attribute subset *before* that single
boundary is the standard defense; security tests assert the sanitized DOM
structure (script gone, `onerror` gone, `javascript:` href gone,
forbidden tags gone, safe p/strong kept).

## Mutation design

- Explicit buttons only: 标记为已读/未读 and 收藏/取消收藏 send the
  **target** state (`{"read": true}` etc. — set semantics, never a
  toggle endpoint). Opening an article never writes anything.
- One shared `useEntryStateMutation` instance for both buttons; any
  pending mutation disables both (at most one PATCH in flight per entry).
- Query/Mutation cancellation split: the detail GET uses the query's
  AbortSignal (fast A→B switching aborts A); the PATCH deliberately has
  **no** AbortSignal/AbortController — a write that has been sent is
  allowed to finish normally; no mutation cancellation framework.
- Cross-entry leakage: `ReaderHeader` is rendered with
  `key={detail.entryRef}`, so switching entries remounts the header and
  stale pending/error UI can never bleed into the next article. No
  `mutation.reset`, no extra state layer.
- 204 responses are not JSON-parsed (the client gained a `rawRequest`
  path that returns the Response without reading a body).

## Why no optimistic update

PATCH → 204 → invalidate `["entry", ref]` + `["entries"]` prefix →
refetch → the UI shows FreshRSS's real state. With single-user local
traffic the extra round-trip is free compared to the complexity of
hand-rolled cache mutation + rollback contexts. Failure semantics are
also trivially correct: on error the cache still holds the real state
(nothing was faked).

Side effects that are *legal* behavior: marking an entry read while in
the Unread view makes it disappear from the list (the reader keeps
showing it); unstarring in the Starred view likewise.

## Tests

- BFF (121 total): contentHtml mapping (verbatim, untrusted), empty/missing
  upstream HTML → null, list regression (no body fields), full 0002–0004
  regression.
- Web (97 total): getEntry/setEntryState client contracts (URL encoding,
  PATCH JSON body, 204 not parsed, ApiError/AbortError rules), DOMPurify
  security structure tests, safeExternalHttpUrl matrix, Reader states
  H–N, original link presence/absence, read/star mutation bodies,
  invalidation + invalidation race (A's mutation resolving after
  switching to B must invalidate `["entry", A]`, never B), pending
  disables both buttons, cross-entry error-leak protection, selection
  race, and full 0005 shell regression.

## Real detail smoke

- `GET /api/v1/entries/<entryRef>` → 200 in the browser network log;
  Reader rendered title / feedTitle / author / time / article content.
- Live rich HTML sample **was available**: the selected real article
  carries a 12,899-char HTML body with paragraphs, links and ~29 remote
  images, all rendered after sanitization (no article text is reproduced
  in this devlog).
- Console: no errors.

## Read/star state smoke (reversible)

- read: original=False → marked read (server verified True, list unread
  dot and reader button updated via invalidation/refetch) → restored
  (server verified False). final == original.
- starred: original=False → starred (server verified True, list shows
  已收藏) → unstarred (server verified False). final == original.
- Unread filter observation: switching to Unread shows only the 12
  unread of 13 entries; switching view clears the selection back to the
  placeholder.

## Visual review

- Real 856px viewport: three panes work, reader renders cleanly, no
  horizontal overflow, console clean, screenshot verified.
- 1024/1280/1440: true viewport resizing was not available in the tooling
  (window.resizeTo ignored; Playwright browser download blocked by the
  network), so layout was verified by forcing the grid width at those
  values: no overflow anywhere, `max-w-[44rem]` caps the article at
  ~704px on wide viewports (line length stays reasonable).

## Problems

| 现象 | 原因 | 层级 | 解决 |
| --- | --- | --- | --- |
| 分支缺 0005 | feat/0006-reader 基于 0004 创建，0005 已在 main | git | 经用户授权 fast-forward 合并 main |
| 36 个测试同时失败 | jsdom 元素没有 scrollTo 方法，Reader effect 抛异常 | tests | scrollTop 赋值替代 scrollTo |
| 危险 href 断言崩溃 | DOMPurify 移除整个 href 属性（null），`not.toContain(null)` 报错 | tests | `getAttribute('href') ?? ''` 容错 |
| 旧 Test K 失败 | 0005 断言“点击不触发 detail API”，与 0006 的核心行为冲突 | tests | 按 Spec 语义更新为断言点击真实发起 Detail 请求 |
| 无法 resize 视口 | window.resizeTo 被忽略；Playwright Chromium 184MB 下载网络受限 | tooling | 强制 grid 宽度近似验证 + 856px 真实视口 |

## Solutions

See table above. All were minimal fixes at the correct layer; none
touched FreshRSS, the adapter auth, or the frozen architecture.

## What I learned

- Untrusted-HTML handling is a chain: transport (BFF) → sanitize
  (DOMPurify, one call site) → render (one dangerouslySetInnerHTML
  boundary) — and the sanitized string is immutable afterwards.
- useQuery vs useMutation is also a cancellation split: reads abort on
  switch, writes run to completion.
- `onSuccess` must use `variables.entryRef`, not the current selection —
  the selection can change while the mutation is in flight.
- A React `key` is the smallest correct tool for per-entry UI isolation.
- 204 responses break `await response.json()`; API clients need an
  explicit no-body path.

## Next

0007 — Mobile + PWA (not started).
