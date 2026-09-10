# 01 网页剪藏(Web Clipping)

> 状态:READY FOR IMPLEMENTATION(全部验收项见 §27;PoC 已实跑)
> 公共内容见 [00-platform](00-platform-architecture.md)。

## 1. Executive decision
**RECOMMENDED** — v1 采用"URL 交给服务器抓取 + Readability/Defuddle 提取 +
净化入库"路线;浏览器扩展与 PWA Share Target 作为 Gate 后续入口。

## 2. Problem
LumiRSS 只能读 RSS;用户需要把**非 RSS 的单篇文章**(博客、文档、新闻)
存进自己的阅读库做稍后读/标注/AI 处理。解决"我读过的东西值得留下来",
不是"别人都有剪藏"。

## 3. Current LumiRSS gap
- 无 library 域(BFF `lumirss/` 无 clip 模块);搜索投影只认 FreshRSS entry;
  侧栏有"网页剪藏 Phase 2"占位。
- 可复用:ArticleContent 渲染管线(sanitize 边界)、`http_fetch.py`、
  ai_translation 段缓存模型(entry_ref→item_ref 泛化)。

## 4. User stories
- 普通:粘贴 URL → 看到标题/正文预览 → 保存 → 出现在"剪藏"列表。
- 移动:从系统分享(PWA Share Target,Gate 3)直接发起;弱网下抓取失败
  可重试。
- 失败:目标站 403/超时 → 明确错误 + "重试/只存链接"两选项。
- offline:已保存 clip 从缓存可读(与 RSS 缓存同一 app-shell 策略)。

## 5. Non-goals
v1 不做:浏览器扩展(MV3)、整页快照(02 号)、批量 OPML 式导入、协作/分享、
自动定时抓取。

## 6. OSS research(≥3)

| 项目 | 事实能力 | 架构 | 活跃 | License | 复用 | 不复用 |
|---|---|---|---|---|---|---|
| Obsidian Web Clipper | 官方剪藏扩展:Defuddle 提取+模板+高亮 | MV3 扩展+Defuddle | 活跃 | MIT(代码;商标/资产不可用) | Defuddle 提取思路 | 扩展壳/Obsidian 品牌 |
| Defuddle | "页面→干净正文+元数据"提取库 | 浏览器/DOM 级 | 活跃 | MIT | **提取库本体** | — |
| Mozilla Readability | Firefox Reader Mode 内核 | DOM 启发式 | 活跃 | Apache-2.0 | 备选提取器(AB 对比) | — |
| Karakeep(原 hoarder) | 全功能书签+剪藏+全文检索 | server+extension+ML 标签 | 活跃 | AGPL-3.0 | 交互模式参考 | 不引其服务端 |
| Linkwarden | 链接+归档+截图 | server+extension | 活跃 | AGPL-3.0 | 链接管理 UX 参考 | — |
| Omnivore(已关停) | 稍后读+newsletter 内嵌 | server+app | 归档 | AGPL-3.0 | 概念参考 | — |

## 7. Build vs reuse
**复用提取,自建集成**:提取用 Defuddle(主)/Readability(备)——两者 MIT/Apache
可直连;Lumi 自建 library 存储与 API(与自有架构边界一致)。Karakeep 类
整体方案违反"不引第二个内容后端"。

## 8. Proposed architecture

```text
Web(粘贴 URL / Share Target)
  │ POST /api/v1/library/clips {url}
  ▼
BFF clip service
  ├─ http_fetch(安全出口: SSRF 防护/超时/大小上限 5MB)
  ├─ Defuddle(主) 提取 title/byline/content → 失败降级 Readability
  ├─ sanitize(DOMPurify 同规则子集, server-side)
  └─ INSERT library_items(kind='clip') + FTS 投影
  ▼
Reader 复用 ArticleContent 渲染(译文/摘要/AI 全链路直接可用)
```

## 9. Data ownership
`library_items(kind='clip')` = Lumi 拥有;无 RSS 域读写。

## 10. Data model(草案)
```sql
CREATE TABLE library_items (
  uuid TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind='clip'), -- per-kind CHECK 由迁移细化
  title TEXT NOT NULL, byline TEXT, url TEXT UNIQUE,
  content_html TEXT NOT NULL, content_text TEXT NOT NULL,
  fetched_at TEXT NOT NULL, created_at TEXT NOT NULL
);
```

## 11. API contract(草案)
```text
POST /api/v1/library/clips        {url} → 202 {item_id, status: fetching|ready|failed}
GET  /api/v1/library/clips        ?cursor&limit → {items[], nextCursor}(opaque 分页)
GET  /api/v1/library/items/{uuid} → LibraryItemView(与 EntryView 同形的读视图)
DELETE /api/v1/library/items/{uuid} → 204
errors: invalid_url / fetch_forbidden / fetch_timeout / extraction_failed / already_exists
```

## 12. Sync/lifecycle
create(fetch+extract)→ready;refresh(重抓, 手动);delete(连带 FTS 投影);
无自动重试(money rule)。

## 13. Security
SSRF(§00 基线 1);HTML 净化(基线 2);大小/频率上限(基线 6);URL 仅
http/https。禁止登录态页面抓取(不带用户 cookie)。

## 14. Resource budget(1.6GB)
BFF 内新增 fetch+extract:每请求瞬时 +10-30MB,峰值并发 1(单用户串行)。
存储:平均 30KB/篇(实测 PoC cleanHTML 1-129KB),2GB 配额≈数万篇。

## 15. UI information architecture
侧栏"网页剪藏"从占位变列表页;Reader 复用现有阅读器(含翻译/AI)。

## 16. Desktop wireframe
```text
┌──────────┬──────────────────────────────┐
│ 侧栏      │ [粘贴 URL__________] [剪藏]   │
│ 剪藏 ◀──  ├──────────────────────────────┤
│ …        │ ▢ 标题 · 来源 · 时间 · 预览行  │
│          │ ▢ …                          │
└──────────┴──────────────────────────────┘
```

## 17. Mobile wireframe(390px)
```text
┌──────────────────────┐
│ [+ 粘贴链接]          │
│ ▢ 标题 · 来源 · 预览  │
│ ▢ …                  │
│ [首页 订阅 搜索 收藏] │
└──────────────────────┘
```

## 18. States
empty(引导文案)/loading(抓取中骨架)/success/error(403·超时·提取失败分文案)/
offline(队列本地待发)/permission(n/a 单用户)。

## 19. Accessibility
列表为语义 list;粘贴输入有 label;44×44 触控;错误 role=alert;复用阅读器
焦点管理与 reduced-motion。

## 20. Runnable PoC
`research/phase2-pocs/clipping/poc_clipping.mjs` — URL→Readability→
sanitize-html→Turndown→Markdown,含转义规则。

## 21. PoC evidence(实跑)
```text
[plain blog] 200 698ms  raw=112KB clean=30KB  md=29KB  :: Astra for Coding…(Armin Ronacher)
[code blog]  200 796ms  raw=13KB  clean=1KB   md=1KB   :: A quote from Calif Research
[news heavy] 200 792ms  raw=641KB clean=26KB  md=22KB  a=20 img=63 :: Artificial Intelligence (The Verge)
[research]   200 722ms  raw=2.4MB clean=129KB md=122KB :: Publications (Apple ML)
[JS-heavy]   200 1924ms raw=127KB clean=19KB  md=16KB  a=35 img=9 :: vLLM V1
→ 5/5 提取成功;普通博客 29KB,重新闻页 22KB Markdown;证据 JSON 同目录
```

## 22. Testing
unit:提取降级/净化快照/URL 校验;integration:BFF clip 全流程(mock fetch);
E2E:粘贴→保存→阅读;security:私网 URL 拒绝矩阵;perf:5MB 上限。

## 23. Migration
纯新增;侧栏占位点亮。

## 24. Rollback
禁用路由+隐藏入口即回滚;删表不丢 RSS 数据。

## 25. Implementation Gates
```text
Gate 0: 00 号平台报告通读;library_items 迁移+路由骨架(空列表 API)
Gate 1: POST clip 全流程(fetch→Defuddle→sanitize→入库→FTS 投影)
Gate 2: 列表/详情/删除 UI(复用阅读器渲染)
Gate 3: PWA Share Target 入口
Gate 4: Readability 降级链+错误态打磨+安全矩阵测试
```

## 26. Expected commits
```text
feat(library): library domain skeleton (tables, routes, opaque refs)
feat(clipping): clip pipeline (fetch→defuddle→sanitize→store→fts)
feat(clipping): clip list + reader UI with share-target entry
```

## 27. Acceptance criteria
- [x] ≥3 OSS 对比+license(§6) [x] 架构图(§8) [x] schema(§10) [x] API(§11)
- [x] 桌面/移动线框(§16/17) [x] 安全(§13) [x] 资源预算(§14)
- [x] 可运行 PoC+证据(§20/21) [x] 测试计划(§22) [x] 迁移/回滚(§23/24)
- [x] Gates(§25) [x] 独立实施 prompt(§28)

## 28. Standalone ZCode implementation prompt
```text
你在 LumiRSS 仓库(先读 AGENTS.md 与 docs/research/phase2/00-platform-architecture.md)。
实施"网页剪藏 v1":按 docs/research/phase2/01-web-clipping.md 的 §10 schema、
§11 API、§25 Gates 顺序执行。硬约束:提取用 @mozilla/readability(备)与
Defuddle(主, MIT);所有服务器抓取必须经 services/bff/src/lumirss/http_fetch.py
的 SSRF 防护;HTML 入库前必须净化;SQL 为 inline literal+绑定参数;复用现有
search 投影与阅读器渲染;LibraryItem kind='clip';每 Gate 跑受影响测试,
Gate 完成跑全量回归。不要实现扩展/快照/批量导入(Non-goals)。
```
