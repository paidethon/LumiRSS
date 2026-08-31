# 0008 — RSSHub Source Expansion

> Status: **Completed**
> Original spec: Git history (docs/specs/0008-*.md)

---

## Status

Completed (PR #14, `c4b84e9`). All acceptance criteria of
Spec 0008 (AC1–AC26) met. Automated regression (BFF 121 / Web 121 +
lint + build), real route probe, FreshRSS integration, BFF end-to-end,
real-browser Web smoke, failure isolation and recovery all verified live.
Original spec available in Git history (`git show HEAD~:docs/specs/0008-rsshub-source-expansion.md`).

## Goal

Add a minimal RSSHub service to the development Docker Compose
environment and prove a real content-source expansion path:

```text
IT之家热榜（网页，无标准 RSS）
    ↓ RSSHub Route /ithome/ranking/24h
RSS 2.0 XML
    ↓ FreshRSS subscription（http://rsshub:1200/ithome/ranking/24h）
FreshRSS stored entries
    ↓
GET /api/v1/feeds → /api/v1/entries?feedUrl=… → /entries/{entryRef}
    ↓
LumiRSS Web Reader
```

The milestone proved: **for the BFF and the Web, an RSSHub-generated
feed is indistinguishable from a native RSS feed** — both `services/bff`
and `apps/web/src` have a zero-line diff.

## Why RSSHub exists (architecture relationship)

```text
Native RSS ──────────────┐
                         ↓
Non-RSS → RSSHub → FreshRSS
                         ↓
                  FreshRSSAdapter
                         ↓
                    FastAPI BFF
                         ↓
                    React Web
```

RSSHub is an upstream **feed generator** for FreshRSS, never a second
LumiRSS data backend. The BFF never talks to RSSHub; FreshRSS remains
the only RSS source of truth. 0008 changed exactly one runtime file:
`docker-compose.yml` (+ one service).

## Official image pin

- **Registry**: docker.io (Docker Hub, official DIYgod channel)
- **Pinned identifier**:
  `diygod/rsshub@sha256:387fd32ee2d8789154dcf6446a52365976e768d9ede1a7c1e610cf4da9d89fbc`
- **How resolved**: `docker pull diygod/rsshub` (the Docker daemon's
  systemd proxy from 0001 was still effective — pull succeeded on the
  first try), then `docker image inspect` → `RepoDigests`. Image build
  date: 2026-08-28 (same day, official latest build).
- **Why immutable**: `latest` drifts on every official push; a digest
  pins the exact bytes, keeping the environment reproducible and the
  verified route behavior traceable.

## Docker service

```yaml
rsshub:
  image: diygod/rsshub@sha256:387fd32e…d89fbc
  container_name: rsshub
  restart: unless-stopped
  ports:
    - "127.0.0.1:1200:1200"   # loopback only
  environment:
    NODE_ENV: production
    CACHE_TYPE: memory
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:1200/healthz"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 10s
```

- No Redis, no Browserless, no Chromium, no depends_on (RSSHub is an
  optional upstream generator, not a runtime request dependency), no
  volumes (memory cache is intentionally ephemeral for a feed
  generator), no ACCESS_KEY (loopback + internal network is the
  security boundary; a `?key=` secret in the feed URL would actually
  widen the leak surface because FreshRSS stores it).
- `CACHE_TYPE: memory` follows the official minimal deployment —
  Redis is only for shared/persistent cache across instances.

## Docker DNS (two views of one service)

- Host (browser/curl): `http://127.0.0.1:1200` — for probing and
  debugging only.
- FreshRSS container: `http://rsshub:1200/<route>` — the Compose
  default network (`lumirss_default`) resolves the service name to the
  container IP. Verified from inside FreshRSS: `getent hosts rsshub`
  → `172.18.0.3`.
- Inside the FreshRSS container, `localhost` means FreshRSS itself —
  which is why the subscription URL must use the service name, never
  `127.0.0.1`.

## Route selected

`/ithome/ranking/24h` (IT之家 24 小时最热).

Why it does not need a browser or config — verified against current
master source (`lib/routes/ithome/ranking.ts`):
`requireConfig: false`, `requirePuppeteer: false`, `antiCrawler: false`,
no cookie, no token, no login. The handler scrapes
`https://www.ithome.com/block/rank.html` (an HTML ranking page — a
genuine non-RSS source) with cheerio, then fetches each article page
for description/pubDate, and uses `cache.tryGet` (works with memory
cache). This proves RSSHub's actual value — not an RSS passthrough.

One refreshed official fact: the browser endpoint variable in the
official compose is now `PLAYWRIGHT_WS_ENDPOINT` (formerly
`PUPPETEER_WS_ENDPOINT`). 0008 uses neither.

## Route probe (host)

```text
curl http://127.0.0.1:1200/ithome/ranking/24h
→ HTTP 200, 59893 bytes, ~1.4s
→ RSS 2.0 root, channel title "IT之家-24 小时最热", 12 items
```

XML parsed and validated with Python stdlib
(`xml.etree.ElementTree`); sample item titles recorded, no article
bodies. Probe file written to `/tmp` (outside the repo).

Three-layer health distinction (all verified):
1. container running (`docker compose ps` → Up)
2. service healthy (`/healthz` → 200 `ok`, compose status healthy)
3. route works (200 + valid RSS + 12 items) — this also depends on the
   upstream website being reachable, which layer 2 does NOT prove.

## FreshRSS integration (manual subscription checkpoint)

LumiRSS has no Feed CRUD API and 0008 deliberately adds none. After
the route probe succeeded, the build paused and the user added the
subscription manually in the FreshRSS Web UI:

```text
http://rsshub:1200/ithome/ranking/24h
```

Pre-state: 2 feeds (FreshRSS releases, 阮一峰的网络日志) — the
RSSHub feed was confirmed not present first, so no duplicate was added.

## BFF end-to-end evidence

Zero BFF code changes. With the existing server on :8000:

- `GET /api/v1/feeds` → 3 feeds, including
  `IT之家-24 小时最热 | http://rsshub:1200/ithome/ranking/24h`;
  the BFF-returned feedUrl was used as the query parameter (not the
  raw input string);
- `GET /api/v1/entries?feedUrl=http%3A%2F%2Frsshub%3A1200%2F…` →
  200, 12 items, all `feedTitle == IT之家-24 小时最热`, read/starred
  booleans normal, nextCursor null (12 < 20);
- `GET /api/v1/entries/{entryRef}` → 200: title, feedTitle,
  publishedAt, contentText (449 chars), contentHtml (918 chars),
  read=false, starred=false. No RSSHub-specific branch anywhere.

## Web Reader evidence

Real browser (browser-use MCP) against the Vite dev server:

- All list: RSSHub articles mixed with native RSS entries — the Web
  has no way to tell them apart;
- Clicking an RSSHub article → Reader rendered fully (title, feed,
  time, 标记为已读 / 收藏 / 打开原文 to ithome.com, sanitized body
  with inline links);
- Sidebar → `IT之家-24 小时最热` → feed-scoped list (12 entries,
  "已经到底了").

Tooling note: the managed browser's `click` timed out on list rows
(known limitation class from 0006/0007); clicks were triggered via
`evaluate_script` DOM `.click()` instead, and screenshots were
unavailable (viewport hidden) — a11y snapshots are the evidence,
marked accordingly.

## Failure isolation

With `docker compose stop rsshub` (rsshub confirmed Stopped):

```text
GET /health/live                      → 200 {"status":"ok"}
GET /api/v1/feeds                     → 3 feeds (unchanged)
GET /entries?feedUrl=<ruanyifeng>     → 200, 3 native entries
GET /entries?feedUrl=<rsshub-feed>    → 200, 12 stored entries
GET /entries/{rsshub-entryRef}        → 200, full contentText
```

This is the architecture working as designed: reading always goes
Browser → BFF → FreshRSS. RSSHub participates only when new content is
generated; being down merely pauses new items for RSSHub-backed feeds.

## Recovery

`docker compose start rsshub` → Up (healthy) in ~18s;
`/healthz` → 200 `ok`; route → HTTP 200, 59893 bytes. RSSHub did not
remain stopped at the end of the milestone.

## Resource measurement

```text
docker stats --no-stream
rsshub     0.00% CPU   253.1 MiB
freshrss   0.59% CPU    73.4 MiB
```

Basic RSSHub (full route set, Node runtime) idles near 0% CPU at
~253 MiB memory — acceptable for the development machine, and the
reason no arbitrary mem_limit was set. Redis/Browserless were not
added because the single-user, single-instance, few-routes scenario
doesn't need shared cache or a browser container.

## Problems encountered

| 现象 | 原因 | 问题层 | 解决 |
| --- | --- | --- | --- |
| Docker Hub Registry API（HTTP）直连不可达 | 本机网络限制（0001 已知） | registry/network | daemon 的 systemd 代理仍生效，`docker pull` 一次成功，无需处理 |
| browser-use `click` 对列表项点击 5s 超时 | 托管浏览器工具限制（0006/0007 同类） | tooling | 改用 `evaluate_script` 直接对目标 button 触发 DOM click，Web smoke 完成 |
| 截图返回 NATIVE_BROWSER_VIEWPORT_UNAVAILABLE | 浏览器视图不可见 | tooling | 以 a11y snapshot 作为证据，截图标记 UNVERIFIED（惯例） |
| /tmp 下 probe 文件无法删除 | 沙箱 /tmp 只读 | tooling | 文件不在仓库内（git status 确认），无影响 |

## Solutions

See table above. All issues stayed at the tooling/network layer; none
touched the BFF, the Web, the frozen architecture, or FreshRSS data.

## What I learned

- Official RSSHub's minimal deployment is genuinely single-service
  (`CACHE_TYPE: memory`): Redis and Browserless are optional
  dependencies for multi-instance caching and browser routes —
  copying the full official compose would have been over-engineering.
- Pinning by `RepoDigests` (`@sha256:…`) from `docker image inspect`
  is more drift-proof than a date tag; both beat `latest`, which
  silently changes on every official push.
- Health has three distinct layers: container running ≠ `/healthz`
  200 ≠ a specific route working (routes also depend on upstream
  websites). Acceptance must verify each layer separately.
- `127.0.0.1:1200` (host view) vs `rsshub:1200` (container view) is
  the same service seen from two networks; subscription URLs must use
  the service DNS because a container's `localhost` is itself.
- Failure isolation is a direct consequence of layering: since RSSHub
  only generates feeds and FreshRSS stores them, an RSSHub outage
  affects only incremental updates, never the reading path.
- When browser automation clicks time out, driving the DOM directly
  via `evaluate_script` is a reliable fallback for smoke tests.

## Tests / Lint / Build / Regression

- Backend: `uv run pytest` → **121 passed** (both before baseline and
  after all changes; `services/bff` diff = 0).
- Frontend: `pnpm test` → **121 passed**; `pnpm lint` → 0 warnings /
  0 errors; `pnpm build` → success (both baseline and final;
  `apps/web/src` + `package.json` diff = 0).
- Secret scan (tracked + untracked-not-ignored): no real secrets; the
  8 "ACCESS_KEY" occurrences in spec 0008 are explanatory ("0008 does
  not use ACCESS_KEY"), per the agreed non-false-positive rule.

## Demo subscription

Pre-state: 2 feeds. Added for 0008: `IT之家-24 小时最热`. Final
state: 3 feeds — the demo subscription was **kept with explicit user
approval** (user chose "保留订阅" at the cleanup checkpoint), so no
removal was performed and the other feeds were verified unaffected.

## Next

0009 — AI Summary (Phase 5 — AI Enhancement). Not started.
