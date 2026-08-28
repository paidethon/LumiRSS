# Spec 0008 — RSSHub Source Expansion

> 日期：2026-08-28
> 对应 PRD 阶段：Phase 4 — Source Expansion
> 状态：**Draft — 等待用户批准，未批准前不开始 Build**
> 批准前唯一允许写入的文件是本 Spec。

## Goal

在现有 docker-compose 开发环境中加入一个**最小** RSSHub 服务，然后真实证明
一条完整的内容来源扩展链路：

```text
一个本身没有标准 RSS 的网页来源（IT 之家热榜）
    ↓
RSSHub Route（/ithome/ranking/24h）
    ↓
标准 RSS/Atom XML
    ↓
FreshRSS Subscription（http://rsshub:1200/ithome/ranking/24h）
    ↓
FreshRSS 抓取并保存 Entry
    ↓
GET /api/v1/feeds
    ↓
GET /api/v1/entries?feedUrl=...
    ↓
GET /api/v1/entries/{entryRef}
    ↓
LumiRSS Web Reader（Sidebar → Entry List → Reader）
```

最终必须证明的结论：

> 对于 LumiRSS BFF 和 Web 来说，RSSHub 生成的 Feed 和普通原生 RSS
> **没有任何区别**。

以及最重要的架构验收：

> RSSHub 临时宕机 ≠ LumiRSS Reader 宕机（Failure Isolation）。

0008 与 0001–0007 的本质区别：

```text
0001–0007  主要在构建 Reader 本身
0008       主要是在 Reader 的"上游"扩充内容来源
```

所以一个合格的 0008 最终 Diff 应该非常克制：

```text
docker-compose.yml               ← + rsshub service（唯一运行时代码变化）
README.md                        ← 最小使用说明
PROJECT_STATE / Board / Devlog   ← 进度记录
services/bff/                    ← 0 runtime changes
apps/web/src/                    ← 0 runtime changes
```

## 前置条件核对（Spec 阶段已真实确认，非旧聊天回忆）

### 分支基线（已验证）

```text
git branch --show-current   → feat/0008-rsshub-source-expansion
git status --short --branch → 干净（无未提交改动）
git log -10                 → 基于 main（4f163d6 = PR #13 merge，含 0007）
```

### 0007 前置已满足

0007 — Mobile + PWA 已 Review → Commit → PR #13 → Merge main。
Phase 3 — Reading Experience 完成。0008 进入 Phase 4。

### 当前环境事实（逐文件读自仓库）

- **docker-compose.yml**（全 15 行）：仅一个 `freshrss` 服务
  （`freshrss/freshrss:1.29.1`，固定版本 tag），`container_name: freshrss`，
  `restart: unless-stopped`，`ports: "127.0.0.1:8080:80"`（仅本机），
  `TZ=Asia/Shanghai`，named volume `freshrss-data`。**没有自定义 network
  定义**——Compose 默认创建 project network，服务间通过 service name DNS
  互通。没有 `depends_on`、没有 healthcheck（freshrss 未配置）。
- **BFF 路由现状**（`services/bff/src/lumirss/main.py` 已读实）：
  `GET /health/live`、`GET /api/v1/feeds`、`GET /api/v1/entries`（query
  参数 view/feedUrl/cursor）、`GET /api/v1/entries/{entry_ref}`、
  `PATCH /api/v1/entries/{entry_ref}/state`。0008 **零修改**。
- **Web 现状**（`apps/web/package.json` 已读实）：React 19 + Vite 8 +
  Tailwind v4 + TanStack Query + Zustand + DOMPurify；scripts =
  dev/build(tsc -b && vite build)/lint(oxlint)/test(vitest run)。
  0008 **零修改**。
- **测试基线**（devlog 0007 记录）：Web 121 passed / BFF 121 passed
  （仅作参考观测值，非最终 AC 数字）。
- **网络历史**（devlog 0001）：Docker Hub 直连超时，已通过 systemd
  drop-in 为 Docker daemon 配置代理后成功拉取 FreshRSS 镜像；该代理
  配置可能仍在（Build 时以实际 pull 结果为准）。

## 当前官方 RSSHub 事实（Spec 阶段重新核验，2026-08-28）

以下事实全部来自**当前**官方仓库 / 官方 compose / 官方 route source 的
真实核验（不是机械照抄任务指令）：

### 官方镜像来源（已核验）

```text
diygod/rsshub          （Docker Hub，官方）
ghcr.io/diygod/rsshub  （GitHub Container Registry，官方）
```

官方 `docker-compose.yml` 中注释原文：
`image: diygod/rsshub # or ghcr.io/diygod/rsshub`。
两者都是 DIYgod/RSSHub 官方发布渠道；**禁止任何第三方 fork / 中国镜像 /
未知个人构建**。

### 端口与健康检查（已核验）

- 服务端口：**1200**；
- 健康检查端点：**`/healthz`**（官方 compose 健康检查原文：
  `test: ['CMD', 'curl', '-f', 'http://localhost:1200/healthz']`，
  interval 30s / timeout 10s / retries 3，无 start_period）；
- 镜像内含 `curl`（官方 healthcheck 即依赖它）。

### Redis / Browserless 不是基础硬要求（已核验）

- 官方完整版 compose 确实提供 Redis + Browserless，但它们服务于：
  **共享/持久缓存**（多实例场景）和**需要浏览器的 Route**；
- 官方 README 快速上手的最小 compose 就是单服务：

  ```yaml
  services:
    rsshub:
      image: diygod/rsshub
      restart: always
      ports:
        - "1200:1200"
      environment:
        NODE_ENV: production
        CACHE_TYPE: memory
  ```

  ——无 Redis、无 Browserless。`CACHE_TYPE: memory` 是官方支持的
  单实例内存缓存模式；
- **官方 compose 的一个新事实**：浏览器自动化相关环境变量现已改名为
  `PLAYWRIGHT_WS_ENDPOINT`（任务指令中写的 `PUPPETEER_WS_ENDPOINT`
  是旧名），官方注释说明需要浏览器的 Route 现在通过 Playwright 走
  Browserless，或直接使用 `diygod/rsshub:chromium-bundled` 镜像。
  0008 两者都不需要（见 Route 选择）；
- 普通镜像（`diygod/rsshub`）**不包含** Chromium/浏览器能力。

### 镜像 tag 事实（已核验）

- `diygod/rsshub:latest` 是 floating tag，**禁止**提交进 Compose；
- 官方发布**日期 tag**（如 `diygod/rsshub:2026-01-29`，普通版约
  448MB；`chromium-bundled-YYYY-MM-DD` 系列为浏览器版约 1.06GB）——
  日期 tag 是官方提供的相对不可漂移标识；
- 任何镜像都可用 Registry digest 固定：
  `diygod/rsshub@sha256:<digest>`（Build 时通过 `docker image inspect`
  读取 `RepoDigests` 真实解析，**不编造**）。

### Route 事实：/ithome/ranking/24h（Build 前已重新核验 master 源码）

当前官方 master 的 `lib/routes/ithome/ranking.ts` 元数据：

```text
path:              /ithome/ranking/:type（example: /ithome/ranking/24h）
name:              热榜
categories:        new-media
requireConfig:     false
requirePuppeteer:  false
antiCrawler:       false
maintainers:       immmortal, luyuhuang
```

handler 行为（源码已读实）：

- 抓取 `https://www.ithome.com/block/rank.html`（**网页，非 RSS**——
  这正是"非 RSS 来源 → RSSHub 生成 RSS"的价值证明）；
- 用 cheerio 解析热榜 DOM（24h / 7days / monthly 三种 type）；
- 对每个 item 再抓取文章页补全 description/pubDate；
- 使用 `cache.tryGet`（memory cache 模式下工作正常，无需 Redis）；
- 不需要 Cookie / token / 登录 / 任何 config。

### 与任务指令核对结论

任务指令中的 RSSHub 事实（diygod/rsshub、1200、/healthz、无需 Redis
即可运行基础 Route、普通镜像无浏览器）**全部与当前官方事实一致**；
唯一更新：浏览器自动化环境变量名已从 `PUPPETEER_WS_ENDPOINT` 改为
`PLAYWRIGHT_WS_ENDPOINT`（0008 不使用，仅作事实记录）。

## Context — 概念解释（写给初学者）

### RSSHub 是什么？它不是 RSS Reader

```text
RSS Reader（FreshRSS、LumiRSS）  = 订阅、存储、阅读已有的 RSS
RSSHub（Feed Generator）         = 把没有 RSS 的网站变成 RSS
```

很多网站（热榜、论坛、社交媒体）不提供标准 RSS。RSSHub 内置了上千个
"Route"，每个 Route 知道如何抓取某个网站的数据并转成标准 RSS/Atom。
RSSHub 本身不是阅读器——它生成 Feed，阅读交给下游。

### Route 是什么

```text
/ithome/ranking/24h
 └─┬─┘  └───┬────┘  └┬┘
   │        │         └── 参数（24 小时阅读榜）
   │        └── 路径（热榜）
   └── 命名空间（IT 之家）
```

访问 `http://<rsshub>/ithome/ranking/24h`，RSSHub 就实时抓取
ithome.com 的热榜页面，解析成 RSS XML 返回。

### Native RSS vs RSSHub

```text
Native：Website → RSS（网站自己发布）
RSSHub：Website → RSSHub Route → RSS（RSSHub 代办）
```

之后两者都进入 FreshRSS——对 FreshRSS 及下游的一切，两种 Feed 完全
同构。

### 为什么 FreshRSS 仍是唯一真源

LumiRSS 不关心（也不知道）某篇 Entry 当初是原生 RSS 还是 RSSHub 生成。
Feed/Entry/read/starred 的真源永远是 FreshRSS。RSSHub 只在"生成 Feed"
这一步参与，随后 FreshRSS 抓取、保存、管理状态。

### 为什么 BFF 不应该直接调用 RSSHub

```text
source generation（生成内容来源） ≠ reader backend（阅读后端）
```

如果 BFF 直接调 RSSHub：每次阅读都依赖 RSSHub 在线、LumiRSS 得自己
处理 Route/缓存/分页、架构出现第二条数据链路。正确分层：RSSHub 定期
生成 Feed → FreshRSS 抓取保存 → 之后所有阅读走 FreshRSS。这就是
Failure Isolation 的来源。

### Docker Service DNS：两个视角

```text
宿主机（WSL/浏览器/curl）看到的 RSSHub：
    http://127.0.0.1:1200          ← host port binding，仅用于调试

FreshRSS container 看到的 RSSHub：
    http://rsshub:1200             ← Compose 内部 service name DNS
```

Compose 默认 network 提供 DNS：service name `rsshub` 解析到 RSSHub
容器的内部 IP。因此 FreshRSS 的订阅 URL 用 `http://rsshub:1200/...`，
**不依赖** host port、WSL IP、Windows IP、DHCP、代理。未来迁移到 ECS
只要 service name 不变，订阅 URL 保持稳定。

**特别注意**：FreshRSS container 里的 `localhost` 指 FreshRSS 容器
自己——不是 WSL host，更不是 RSSHub。所以订阅 URL 绝不能写
`http://127.0.0.1:1200/...`。

### Host port 为什么只绑定 127.0.0.1

`127.0.0.1:1200:1200` 表示只有本机能访问，方便开发调试（health probe、
浏览器看 Route XML）。RSSHub 当前不是公开 Web 服务，禁止 `1200:1200`
（会监听所有 host interface）。生产是否暴露由未来 Production Compose
决定，0008 不开始 Caddy。

### Healthcheck：container running ≠ service healthy

`docker ps` 显示 Up 只证明进程没退出；`/healthz` 返回 200 才证明
HTTP 服务真的可用。而 **RSSHub healthy ≠ 某个 Route 一定正常**——
Route 还依赖上游网站（ithome.com）可达。所以 0008 要验证三层：

```text
① Container running
② /healthz → 200（服务健康）
③ 真实 Route → 200 + 有效 RSS + items > 0（Route + 上游正常）
```

### 为什么不把 latest 永久提交进 Compose

`latest` 会随官方发布漂移：今天验证通过的 Route 行为，明天一次
`docker compose pull` 就可能改变。固定为日期 tag 或 digest 让环境
可复现、可回溯。Build 时通过真实 registry / `docker image inspect`
解析 immutable 标识，绝不编造。

### 为什么 0008 不加 Redis

RSSHub 可用 Redis 做共享/持久缓存，但 0008 场景：单用户、单实例、
开发环境、Route 数量极少、只证明 Source Expansion。内存缓存
（`CACHE_TYPE: memory`，官方支持）足够。未来真实规模证明需要时再加。

### 为什么 0008 不加 Browserless / Chromium

部分 Route 需要浏览器渲染，但 0008 特意选择 `requirePuppeteer=false`
的公开 Route。不为"以后可能需要某个 Route"提前引入一个重量级浏览器
容器。如果首选 Route 失败，优先换另一个同样无需浏览器的 Route，
而不是升级镜像。

### Failure Isolation：本里程碑最重要的架构验收

```text
错误架构（不存在）：
Browser → BFF → RSSHub（每次阅读都依赖 RSSHub）

正确架构：
RSSHub → 定期生成 Feed → FreshRSS 抓取并保存
之后阅读：Browser → BFF → FreshRSS
```

所以 RSSHub 宕机只意味着"RSSHub-backed Feed 暂时无法获取新内容"，
已抓进 FreshRSS 的文章照常可读，BFF/Web 完全不受影响。0008 用
`docker compose stop rsshub` 真实验证这一点。

## Scope（只做这些）

1. **docker-compose.yml 新增最小 `rsshub` service**（唯一运行时代码
   变化）：官方 immutable 镜像 + `127.0.0.1:1200:1200` +
   `/healthz` healthcheck + memory cache 环境；
2. **Resolve immutable image identifier**：Build 时真实解析官方镜像
   的日期 tag 或 RepoDigest；
3. **三层健康验证**：container running / `/healthz` 200 / 真实 Route
   返回有效 RSS + items > 0；
4. **FreshRSS 集成**：人工 checkpoint（用户在 FreshRSS Web UI 添加
   `http://rsshub:1200/ithome/ranking/24h`）；
5. **BFF End-to-End 验证**：/feeds → /entries?feedUrl= → /entries/{ref}
   全链路真实返回 RSSHub-backed 数据；
6. **Web UI End-to-End smoke**：真实浏览器走 Sidebar → Feed → Entry
   List → Reader；
7. **Failure Isolation Test**：stop rsshub → 验证 BFF/原生 RSS/已存
   RSSHub Entries 仍正常；
8. **Recovery Test**：start rsshub → health + Route 恢复；
9. **Resource Measurement**：`docker stats --no-stream` 记录 idle
   CPU/Memory（仅观察）；
10. **Demo Feed cleanup**：按规则恢复测试前订阅状态；
11. **文档更新**：README（最小 RSSHub 说明）/ PROJECT_STATE /
    Project Board / devlog 0008。

## Non-goals（明确不做，做了就是 scope creep）

Redis、Browserless、Chromium、postgres/mysql/mongodb 等任何额外容器；
BFF 任何修改（`services/bff` diff 必须为 0）；Web 任何 runtime source
修改（`apps/web/src` diff 必须为 0）；Web 端任何 RSSHub 特殊判断
（badge / RSSHub API client / route parser / route form）；BFF 端任何
RSSHub Adapter/Client/SourceProvider/FeedGenerator abstraction；
Feed Add/Delete API（不为自动化 smoke 顺手新增 Feed CRUD）；RSSHub
自定义 Route（不 clone RSSHub 源码、不 fork、不修改 lib/routes）；
Route Discovery UI（搜索路由 / 路由目录 / Route Builder / Radar /
"添加 RSSHub"按钮）；ACCESS_KEY / 任何 secret；为 RSSHub 配置
HTTP(S)_PROXY（除非真实证明需要且用户批准）；Caddy；Production
deployment；AI（0009，不启动）；`depends_on`（freshrss 不依赖 rsshub，
BFF 更不依赖）；mem_limit/cpu quota（除非出现真实资源问题）。

## 硬边界（冻结架构，0008 不得触碰）

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

- RSSHub 是 FreshRSS 的**上游 Feed Generator**，不是 LumiRSS 的第二套
  RSS Backend；
- 绝对禁止：`FastAPI → RSSHub`、`React → RSSHub`、
  `FreshRSSAdapter → RSSHub`；
- FreshRSS 仍是唯一真源：禁止 LumiRSS SQLite 存 RSSHub Feed、BFF 缓存
  RSSHub 原始 feed、Web 直接 fetch RSSHub；
- `FreshRSSAdapter` 继续是 BFF 唯一 RSS 读取边界；
- FreshRSS 不 `depends_on` rsshub（RSSHub 是 optional upstream source
  generator，不是 runtime request dependency）；
- 不破坏现有 Native RSS：不改 FreshRSS auth / volume / 不重建 FreshRSS /
  不清空 subscriptions / 不删 entries / **禁止 `docker compose down -v`**。

## Docker service 设计（冻结）

在现有 `docker-compose.yml` 的 `services:` 下最小追加（与现有 freshrss
风格一致：`restart: unless-stopped`、127.0.0.1 端口绑定、无 version
字段）：

```yaml
  rsshub:
    image: <Build 时真实核验的官方 immutable 标识>   # 见 Image Pinning
    container_name: rsshub
    restart: unless-stopped
    ports:
      - "127.0.0.1:1200:1200" # 仅本机可访问
    environment:
      NODE_ENV: production
      CACHE_TYPE: memory
    healthcheck:
      test:
        - CMD
        - curl
        - -f
        - http://localhost:1200/healthz
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

设计说明：

- **environment 只有两项**：`NODE_ENV: production` +
  `CACHE_TYPE: memory`（显式声明官方支持的单实例内存缓存，避免依赖
  隐式默认；不配置任何 secret / ACCESS_KEY / proxy 变量）；
- **healthcheck** 沿用官方 compose 的 curl + /healthz 写法；加
  `start_period: 10s` 容忍 Node 服务启动（RSSHub 冷启动可能需要几秒，
  避免启动期被误判 unhealthy）；
- **不加** `depends_on`（任何方向都不加）；**不加** volumes（RSSHub
  无需持久化——memory cache 重启即失，对"定期生成 Feed"的定位无害）；
- freshrss 服务**一行不动**；顶层 `volumes:` 不变。

### Image Pinning 策略（Build 时执行，绝不编造）

1. Build 允许先 `docker pull diygod/rsshub`（获取当前官方 image；
   若 Docker Hub 经 daemon 代理仍不可达，尝试官方
   `ghcr.io/diygod/rsshub`；两者都失败 → **停止报告**，不换第三方
   镜像）；
2. 解析 immutable 标识，二选一（优先 ①）：
   - ① **RepoDigest**：`docker image inspect diygod/rsshub` 读取
     `RepoDigests` → 提交
     `image: diygod/rsshub@sha256:<verified-digest>`；
   - ② **官方日期 tag**：查询 registry 确认当前最新日期 tag（形如
     `2026-01-29`）→ 提交 `image: diygod/rsshub:<date-tag>`；
3. 最终报告必须说明：Registry / Pinned identifier / 为什么选它；
4. **禁止**最终 Compose 出现 `:latest`。

## Route 计划（冻结）

### 首选 Route

```text
http://127.0.0.1:1200/ithome/ranking/24h     （host probe 视角）
http://rsshub:1200/ithome/ranking/24h        （FreshRSS 订阅视角）
```

选择理由（master 源码已核验）：官方 Route、当前存在、
`requireConfig=false`、`requirePuppeteer=false`、`antiCrawler=false`、
无 Cookie/token/登录、输出真实 items、且**从非 RSS 网页**
（`ithome.com/block/rank.html`）生成 Feed——充分证明 RSSHub 的价值，
不是官方 RSS passthrough。

### Host Route Probe（Build 阶段执行）

```bash
curl -fsS http://127.0.0.1:1200/ithome/ranking/24h \
  -o /tmp/lumirss-rsshub-probe.xml
```

用 Python stdlib（`xml.etree.ElementTree`）验证：

- HTTP 200（curl -f 已保证非 2xx 失败）；
- XML parseable；
- RSS/Atom root 合理（`rss`/`channel` 或 `feed`）；
- item/entry count > 0。

记录（进 devlog，不进仓库 XML 文件）：Route、Feed title
（预期 `IT之家-24 小时最热`）、item count、少量 item title。
**不复制文章正文**；probe 临时文件放 `/tmp`，**不进 repo**。

### Route fallback 规则（首选失败时）

如果 `/ithome/ranking/24h` 因 Route 删除 / 上游网站变化 / 网络限制 /
临时 upstream error 不可用，允许替代 Route，但必须**同时**满足：

1. 属于当前官方 RSSHub；
2. 当前 source/route metadata 可确认存在；
3. `requireConfig=false`；
4. `requirePuppeteer=false`；
5. 不需要 Cookie；
6. 不需要 token/API secret；
7. 不需要登录；
8. 不需要 Browserless；
9. 输出至少一个实际 item；
10. 最好证明是从非 RSS 来源生成 Feed。

**不要**选 GitHub 官方 Atom → RSSHub → FreshRSS 这类纯 RSS passthrough
作为唯一验收来源。找不到满足条件且网络可访问的 Route → **停止并报告**，
不为通过测试偷偷加入 Secret / Browser。

## FreshRSS 集成（人工 checkpoint，冻结）

### 当前状态确认（Build 阶段执行）

通过 `GET /api/v1/feeds` 确认目标 RSSHub Feed 是 `already existed` 还是
`not present`（BFF 当前订阅：FreshRSS releases + 阮一峰的网络日志，
预期 not present）。

### 人工订阅 checkpoint

Route probe 成功后，**暂停并告诉用户**：

1. 打开 FreshRSS Web UI（http://127.0.0.1:8080）；
2. 添加订阅：`http://rsshub:1200/<verified-route>`；
3. FreshRSS 内完成首次获取；
4. 回复"已完成"后继续。

**禁止**：向用户索要 FreshRSS API Password；读取 `services/bff/.env`；
为自动添加 Feed 新增 BFF endpoint；写临时 subscription management
code。如果目标 Feed 已存在，**不重复添加**。

### Demo Feed 状态保护（冻结）

- 测试前已存在的 Feed：**绝对不删**；
- 0008 为测试新添加的 Demo Feed：全部验收（integration / failure
  isolation / Web smoke）完成后**默认删除恢复测试前状态**，除非用户
  明确说"保留这个 RSSHub 订阅"；
- 删除需要人工操作时（LumiRSS 无 Feed Delete API）：暂停告诉用户用
  FreshRSS UI 删除，等待确认；**不使用未经批准的 FreshRSS write API
  automation**；
- 清理后再次 `GET /api/v1/feeds` 确认其它用户 Feed 未受影响。

## BFF / Web End-to-End 验证（Build 阶段执行）

### BFF（零代码修改，只做真实请求）

启动现有 BFF 后：

1. `GET /api/v1/feeds` → 确认出现 RSSHub-backed Feed；
   **使用 BFF 实际返回的 `feedUrl` 作为后续查询参数**（不假定它与
   输入字符串完全一致——FreshRSS 可能对 URL 做规范化）；
2. `GET /api/v1/entries?feedUrl=<actual-feedUrl>` → 200、items > 0；
   记录 entry count、几个 title、read/starred shape（不记正文）；
3. 选一个 entryRef → `GET /api/v1/entries/{entryRef}` → 200，确认
   title / feedTitle / publishedAt / contentText/contentHtml path /
   read / starred——Reader Detail Contract 无任何 RSSHub 特殊分支。

### Web（零代码修改，真实浏览器 smoke）

启动 Vite dev server（BFF 运行中），真实浏览器走：

```text
Sidebar → RSSHub-backed Feed → Entry List → 点 Entry → Reader
```

必须工作。最重要的观察：**Web 不知道这个 Feed 来自 RSSHub**——它只
看到 Feed / Entry / Reader，与原生 RSS 完全一样。

## Failure Isolation Test（最重要的架构验收，冻结）

前置：RSSHub Feed 已被 FreshRSS 成功抓取，且 BFF /feeds、/entries、
Web 全部正常。然后：

```bash
docker compose stop rsshub        # 确认 rsshub stopped
```

此时验证：

1. `GET /health/live` → 200（BFF 不依赖 RSSHub）；
2. `GET /api/v1/feeds` → 仍正常；
3. 一个原生 RSS Feed：`GET /api/v1/entries?feedUrl=<native>` → 仍正常；
4. 已抓取的 RSSHub Feed：`GET /api/v1/entries?feedUrl=<rsshub-feed>`
   → FreshRSS 已存储的 Entries 仍可读取。

如 FreshRSS 实际行为与预期略有差异，**如实报告**。

### Recovery Test（不得让 RSSHub 留在 stopped 状态结束）

```bash
docker compose start rsshub       # 等待 healthy
curl -fsS http://127.0.0.1:1200/healthz   # → 200
# Route 再次 probe → 200 + 有效 items
```

## Resource Measurement（仅观察）

RSSHub 启动稳定后：

```bash
docker stats --no-stream
```

记录 RSSHub idle CPU / Memory 进 devlog。解释为什么 0008 没上
Redis / Browserless，以及基础 RSSHub 在当前机器的大致资源占用。
**不设置**随意的 mem_limit / cpu quota。

## 依赖变更（冻结）

```text
Python:  0 new dependencies
Web:     0 new dependencies
Docker:  + 1 官方 RSSHub image（immutable pin）
```

不增加 Redis image / Browserless image / Chromium image。不为 Docker
service 建大型测试框架（0008 是 infrastructure integration，验证靠
真实 curl / 浏览器 / 既有回归）。

## 数据与安全边界

- 0008 理论上**不新增任何 Secret**：不配置 RSSHub `ACCESS_KEY`
  （原因：host 只监听 localhost；FreshRSS 与 RSSHub 在 Compose internal
  network；不经 Caddy 暴露公网；且 ACCESS_KEY 若写在 Feed URL 的
  `?key=` 里会被 FreshRSS 保存，反而扩大 Secret 泄漏面。RSSHub 当前
  的安全边界 = host loopback binding + Docker internal network +
  不暴露 Caddy route）；
- 不创建 `RSSHUB_ACCESS_KEY` / .env secret / URL query secret；
- 不读取 `services/bff/.env`；
- 最终 secret 扫描（tracked + untracked 非 ignored）：确认不存在
  ACCESS_KEY 值 / API password / Auth token / Action token / Cookie /
  Authorization header。文档中"0008 不使用 ACCESS_KEY"这类**说明性
  提及**不算泄漏，不误报；
- Docker volume 安全：整个 0008 禁止 `docker volume rm` /
  `docker compose down -v` / `docker system prune --volumes`；不因
  RSSHub 拉取失败重置 FreshRSS；
- 禁止 `docker compose down -v`（对整个 milestone 有效）。

## 遇到错误时按层定位（现象 → 证据 → 问题层 → 根因 → 最小修复）

```text
Docker registry（pull 失败：代理/网络——0001 已处理过 daemon proxy）
    ↓
RSSHub container（起不来：image/环境）
    ↓
RSSHub health（/healthz 非 200：进程问题）
    ↓
RSSHub route（具体 Route 失败）
    ↓
upstream website（Route 正常但抓不到 ithome.com）
    ↓
Docker network DNS（freshrss 解析不了 rsshub）
    ↓
FreshRSS feed fetch（订阅 URL 错误视角：127.0.0.1 vs rsshub）
    ↓
FreshRSS stored entries（抓取成功但没存下来）
    ↓
FreshRSSAdapter / BFF / Web（既有链路，0008 未改动，回归验证）
```

不要把不同层的错误混在一起。**判断口诀**：image pull 失败是
registry/network 层；container 起来但 Route timeout 是
RSSHub → upstream website 层——不是同一个问题。

### Request Proxy 原则

0008 **不主动**为 RSSHub 配 `HTTP_PROXY` / `HTTPS_PROXY`。仅当真实
Route probe 证明 RSSHub container 无法访问公开 upstream、且问题明确
属于当前 WSL/网络环境时：**先停止并报告**（现象 / 容器网络证据 /
为什么需要），等用户批准。不把 Windows/WSL 代理地址随手写进
docker-compose。

## 预计文件变化（上限）

修改：

```text
docker-compose.yml                     # + rsshub service（唯一 runtime 变化）
README.md                              # 最小 RSSHub development 说明
docs/PROJECT_STATE.md                  # Implemented/Not implemented/Phase 4
docs/progress/project-data.js          # 0008 → completed 等板级更新
```

新增：

```text
docs/specs/0008-rsshub-source-expansion.md   # 本 Spec
docs/devlog/0008-rsshub-source-expansion.md  # 验收后写
```

**零改动（必须在最终 git diff 中验证）**：

```text
services/bff/**        # diff = 0
apps/web/src/**        # diff = 0
apps/web/package.json  # diff = 0
services/bff/pyproject.toml / uv.lock  # diff = 0
```

如果 Build 中觉得"要让 BFF 支持 RSSHub 需要改 Python"→ **立即停止**，
说明架构理解错了。

## Testing strategy

0008 不新增自动化测试（Docker service / integration 没有对应测试框架，
不为此建一个）。验证手段：

1. `docker compose config` — Compose 语法有效；
2. 真实 curl 探测（healthz / Route XML + Python stdlib 解析）；
3. 真实 BFF 请求（feeds / entries / detail）；
4. 真实浏览器 Web smoke；
5. **既有回归**（必须真实运行并报告实际数量）：

```bash
cd services/bff && uv run pytest        # 观测参考 121 passed
cd apps/web && pnpm test && pnpm lint && pnpm build
                                         # 观测参考 121 / 0 problems / 成功
```

不把固定数量当 AC；报告真实 `XX backend passed / YY frontend passed`。

## Acceptance Criteria（AC1–AC26）

| # | 标准 |
|---|---|
| AC1 | 所有修改位于 `feat/0008-rsshub-source-expansion` |
| AC2 | Build 开始前 baseline 健康：现有 FreshRSS 运行、BFF tests、Web tests/lint/build 全绿 |
| AC3 | 只使用官方 RSSHub image（diygod/rsshub 或 ghcr.io/diygod/rsshub），无第三方 fork/image |
| AC4 | Committed Compose 不使用 floating `latest`；使用真实核验的 immutable tag/digest（Build 时从 registry / image inspect 解析，不编造），报告说明 Registry + Pinned identifier + 选择理由 |
| AC5 | 只新增 `rsshub` 一个容器；不新增 Redis / Browserless / Chromium / 其它任何服务 |
| AC6 | 开发端口 `127.0.0.1:1200`，不监听所有 interface |
| AC7 | `curl -fsS http://127.0.0.1:1200/healthz` 真实 200；`docker compose ps` 中 rsshub 显示 healthy |
| AC8 | 至少一个无 secret / 无 config / 无 Puppeteer 的官方 Route 真实返回有效 RSS/Atom + items > 0（XML 用 stdlib 解析验证） |
| AC9 | 验证 Route 的价值不是纯 RSS passthrough（/ithome/ranking/24h 从网页热榜生成） |
| AC10 | FreshRSS 订阅使用 `http://rsshub:1200/<route>`（service DNS），不是 `127.0.0.1` |
| AC11 | FreshRSS 成功订阅并抓取 RSSHub Feed（人工 checkpoint，不新增 Feed CRUD） |
| AC12 | `GET /api/v1/feeds` 真实看到 RSSHub-backed Feed |
| AC13 | `GET /api/v1/entries?feedUrl=<actual-feedUrl>` 真实返回该 Feed 的 Entries（200 + items > 0；用 BFF 实际返回的 feedUrl） |
| AC14 | RSSHub-backed Entry 的 Detail 正常（title/feedTitle/publishedAt/content path/read/starred），且 BFF 无任何 RSSHub-specific code |
| AC15 | 现有 LumiRSS Web 真实浏览器 smoke 通过：Feed → Entry List → Reader |
| AC16 | 架构边界：实际代码中不存在 RSSHubAdapter / RSSHubClient / FastAPI → RSSHub / React → RSSHub |
| AC17 | Failure isolation：stop rsshub 后 BFF /health/live 仍 200、原生 RSS 数据仍正常、FreshRSS 中已存的 RSSHub Entries 仍可读取（按真实结果记录） |
| AC18 | Recovery：重启 RSSHub 后 health + Route 恢复；最终 RSSHub 不留在 stopped 状态 |
| AC19 | 数据安全：无 down -v / volume rm / subscriptions reset / FreshRSS 数据清空；现有用户 Feed 未受损 |
| AC20 | 无 Secret：不增加 RSSHub ACCESS_KEY / Cookie / Route token；最终扫描（tracked + untracked 非 ignored）无 Secret 泄漏 |
| AC21 | 依赖：Python / Web 0 new dependencies；Docker 仅新增官方 RSSHub image |
| AC22 | 既有 tests/lint/build 无 regression（报告真实数量） |
| AC23 | 记录 RSSHub idle CPU / Memory（docker stats，仅观察，不设武断 limit） |
| AC24 | Demo state cleanup：demo Feed 按 cleanup 规则恢复测试前订阅状态（除非用户明确要求保留）；清理后其它 Feed 确认未受影响 |
| AC25 | Scope：未实现 Feed CRUD / Route Discovery UI / 自定义 Route / Redis / Browserless / Chromium / AI / Search / Category / Caddy / Production deployment |
| AC26 | 全部通过后 Phase 4 — Source Expansion → Completed；0009 — AI Summary 标 Next，不启动 |

## Tasks（Build 顺序，批准后严格逐步执行，每步完成立即验证）

1. **Baseline check**：`docker compose ps`（freshrss running）；
   `cd services/bff && uv run pytest`；`cd apps/web && pnpm test &&
   pnpm lint && pnpm build`。失败 → 停止报告，不算 0008。
2. **重新核对 RSSHub 官方事实**（image registry 可达性 / 当前最新
   immutable tag / healthz / selected Route source metadata 仍在）。
3. **Resolve immutable image identifier**：`docker pull diygod/rsshub`
   → `docker image inspect` 读取 RepoDigests（或确认官方日期 tag）；
   Docker Hub 不可达则尝试 `ghcr.io/diygod/rsshub`；都失败 → 停止报告。
4. **docker-compose.yml 添加最小 rsshub service**（按冻结设计）。
5. `docker compose config` 通过（语法验证）。
6. `docker compose pull rsshub` + `docker compose up -d rsshub` +
   `docker compose ps`：rsshub running/healthy，FreshRSS 仍正常。
7. **Health 验证**：`curl -fsS http://127.0.0.1:1200/healthz` → 200。
8. **Real Route probe**：首选 `/ithome/ranking/24h` → 写
   `/tmp/lumirss-rsshub-probe.xml` → Python stdlib 验证 XML/RSS root/
   item count > 0；记录 Route / Feed title / item count / 少量 title；
   失败 → 按 fallback 规则换 Route 或停止报告。
9. **Docker networking / service-DNS 理解确认**：解释（进 devlog）
   `127.0.0.1:1200` 与 `rsshub:1200` 两个视角的区别。
10. **FreshRSS manual subscription checkpoint**：暂停，请用户在
    FreshRSS Web UI 添加 `http://rsshub:1200/<verified-route>` 并回复
    完成（先确认 not present，不重复添加）。
11. **BFF 验证**：启动 BFF → `GET /api/v1/feeds`（记录实际 feedUrl）→
    `GET /api/v1/entries?feedUrl=<actual>`（200 + items > 0）→
    `GET /api/v1/entries/{entryRef}`（Detail 正常）。
12. **Web smoke**：启动 Vite dev server → 真实浏览器
    Sidebar → Feed → Entry List → Reader。
13. **Failure isolation test**：`docker compose stop rsshub` → 验证
    /health/live、/feeds、原生 RSS entries、已存 RSSHub entries
    全部仍正常。
14. **Recovery test**：`docker compose start rsshub` → healthy →
    /healthz 200 + Route 200。
15. **Resource measurement**：`docker stats --no-stream` 记录。
16. **Demo subscription cleanup**：按规则恢复测试前状态（默认删除
    0008 新增的 demo Feed；需人工删除则暂停等待用户确认）→ 再次
    `GET /api/v1/feeds` 确认其它 Feed 未受影响。
17. **Full regression**：`uv run pytest` + `pnpm test` / `pnpm lint` /
    `pnpm build`（报告真实数量）。
18. **Secret / scope / dependency 扫描**：tracked + untracked 非
    ignored；确认 `services/bff` 与 `apps/web/src` diff = 0。
19. **文档更新**：README（最小 RSSHub 说明）/ PROJECT_STATE（Phase 4
    Completed，明确 Not implemented 保留 Redis/Browserless/Chromium
    routes/Authenticated routes/Custom routes/Route discovery UI）/
    Project Board（0008 → completed、0009 → next、phase-4 → completed、
    current phase 更新）/ devlog 0008。
20. **Final git 检查**：`git branch --show-current` / `git status
    --short --branch` / `git diff --stat` / `git diff --check` /
    `git diff` → **停在工作区等待人工 Review**（不 commit / 不 push /
    不建 PR；不开始 0009）。

## Verification

```bash
docker compose config                      # 通过
docker compose ps                          # freshrss + rsshub 均 running，rsshub healthy
curl -fsS http://127.0.0.1:1200/healthz    # 200
curl -fsS http://127.0.0.1:1200/<verified-route> -o /tmp/...   # 200 + 有效 RSS
cd services/bff && uv run pytest           # 全绿（报告真实数量）
cd apps/web && pnpm test && pnpm lint && pnpm build
git branch --show-current                   # feat/0008-rsshub-source-expansion
git status --short --branch                 # 仅预期文件
git diff --stat                             # docker-compose.yml + 文档；bff/web = 0
git diff --check                            # 无空白错误
```

外加：Failure isolation / Recovery / Resource measurement 的真实输出
记录（进 devlog），secret 扫描零命中。

## Documentation updates（AC 全过后单独做）

- **README**：增加很小的 "RSSHub development" 说明——启动
  `docker compose up -d rsshub`、health
  `curl http://127.0.0.1:1200/healthz`、host route example
  `http://127.0.0.1:1200/<route>`、FreshRSS subscription URL
  `http://rsshub:1200/<route>`，特别解释 `127.0.0.1` vs `rsshub`
  Docker service DNS。只放一个 verified example，不列几十个 Route。
  **不写**：RSSHub supports every website / all routes guaranteed /
  browser routes supported / Redis enabled / offline / production
  public RSSHub。明确当前是 Basic RSSHub：no Redis / no Browserless /
  no Chromium。
- **PROJECT_STATE**：Implemented 增加 RSSHub Docker service /
  RSSHub healthcheck / RSSHub → FreshRSS internal service-DNS path /
  Non-RSS → RSSHub → FreshRSS → LumiRSS verified / RSSHub failure
  isolation verified；Not implemented 明确保留 Redis / Browserless /
  Chromium routes / Authenticated RSSHub routes / Custom RSSHub routes /
  Route discovery UI；Phase 4 → Completed；Next → 0009 — AI Summary。
- **ARCHITECTURE.md**：冻结架构不变、不重写；若存在"planned / not
  implemented"状态字段才做最小 implemented 更新（当前文档无此字段，
  预期零改动）。
- **Project Board（project-data.js）**：0008 → completed（填
  implemented/acceptance/problems/learned + devlog 链接）、0009 → next、
  phase-4 → completed、currentPhaseId → phase-5、
  currentMilestoneId → 0009、updatedAt 更新。不伪造 0009 已开始。
- **Devlog `docs/devlog/0008-rsshub-source-expansion.md`**：Status /
  Goal / Why RSSHub exists / Architecture relationship / Official
  image pin / Docker service / Docker DNS / Route selected / Why route
  does not need browser/config / Route probe / FreshRSS integration /
  Manual subscription checkpoint / BFF end-to-end evidence / Web Reader
  evidence / Failure isolation / Recovery / Resource measurement /
  Problems / Solutions / What I learned / Next。**禁止记录**：FreshRSS
  password / Auth Token / Action Token / Authorization header / Cookie /
  Secret route credentials / 完整 RSS 文章正文 / AI internal reasoning。

## 最终解释义务（完成后向初学者解释）

RSSHub 是什么（不是 Reader，是 Feed Generator）；Route 是什么
（/ithome/ranking/24h 意味着什么）；Native RSS vs RSSHub（之后两者
都进 FreshRSS）；为什么 FreshRSS 仍是唯一真源（LumiRSS 不关心 Entry
的出身）；为什么 BFF 不应该直接调用 RSSHub（source generation vs
reader backend 两层职责）；Docker Service DNS（为什么
`rsshub:1200` 能被 FreshRSS container 找到；为什么 FreshRSS 里的
`localhost` ≠ RSSHub）；Host port vs Internal port（`127.0.0.1:1200`
只用于开发者调试，FreshRSS 实际走 `rsshub:1200`）；Healthcheck
（container running ≠ service healthy）；Route health（RSSHub healthy
≠ 某 upstream Route 一定正常）；Immutable image（为什么不把 latest
永久提交进 Compose）；Redis（RSSHub 为什么可以用、0008 为什么不用）；
Browserless / Chromium（为什么部分 Route 需要、0008 为什么故意选不用
浏览器的 Route）；Failure isolation（最重要：为什么 RSSHub 挂了以后
已抓进 FreshRSS 的文章仍然可以阅读）。

## Risks / Unknowns

- **镜像拉取**（最高概率风险）：0001 记录 Docker Hub 直连超时，靠
  daemon systemd 代理拉取成功。代理配置可能仍在；若 pull 失败：
  重试 → 官方 GHCR → 都失败停止报告。**不**换第三方镜像、**不**重置
  Docker、**不**改 LumiRSS 代码（这是 registry/network 层问题）。
- **Route 上游可达性**：ithome.com 从 RSSHub container 内是否可达
  属于 "RSSHub → upstream website" 层，与 image pull 不同层。若
  Route timeout：先换备选 Route；确认是容器网络环境问题才考虑代理
  报告流程（见 Request Proxy 原则）。
- **FreshRSS 对 feedUrl 的规范化**：FreshRSS 返回的 feedUrl 可能与
  订阅输入不完全一致（如加/去 query、编码差异）。处理方式：一律以
  BFF `GET /api/v1/feeds` 实际返回的 feedUrl 为准，不硬编码。
- **Feed 抓取延迟**：FreshRSS 添加订阅后首次抓取可能需要手动触发或
  等待。若 entries 为空：在 FreshRSS UI 手动刷新该 Feed 后重试；
  长时间无 entries → 如实报告，不伪造。
- **镜像体积**：普通 diygod/rsshub 日期 tag 约 450MB–1GB（含 Node
  runtime 与全部 Route），首次拉取可能较慢——如实记录，不为此换
  精简第三方镜像。
- **Web smoke 依赖既有链路**：FreshRSS + BFF + Vite 三者都要运行；
  沿用 0006/0007 的 smoke 流程。浏览器工具受限时按 0007 惯例标记
  VERIFIED / PARTIAL / UNVERIFIED，不假装。

---

**本 Spec 为 Draft。在用户明确回复"批准 Spec，可以开始 Build"之前：
不修改 docker-compose.yml、不 docker pull RSSHub、不 docker compose up
RSSHub、不修改 BFF、不修改 Web、不添加 FreshRSS 订阅、不安装任何依赖。
唯一允许写入的文件是本 Spec 自身。**
