# 02 网页快照(Web Snapshots)

> 状态:READY FOR IMPLEMENTATION(PoC 已实跑;条件:assets 配额策略落地)
> 公共内容见 [00-platform](00-platform-architecture.md)。

## 1. Executive decision
**RECOMMENDED**(CONDITIONAL→READY 当配额/去重清理策略按 §14 落地)。
v1 = monolith 单文件快照,按需生成,不做常驻浏览器。

## 2. Problem
Clip 是"可读正文";快照是"页面当时的样子"。链接腐烂(实测 404 率高:
本轮候选验证中 2 个猜测 URL 直接 404)要求对关键页面留存完整证据。

## 3. Current LumiRSS gap
无 assets 存储、无快照能力。backup 体系(0018)只管 SQLite 与 FreshRSS data。

## 4. User stories
- 普通:文章详情页"保存快照"→ 生成单文件 → 离线可开原样页面。
- 移动:快照列表点开即看(单文件,无外链依赖)。
- 失败:超大页面(实测 29MB)超配额 → 明确提示+只存文本。
- offline:快照本身就是离线资产。

## 5. Non-goals
v1 不做:常驻 headless Chromium、截图缩略图墙、增量 DOM 级版本树、全文
渲染级归档(SingleFile 式浏览器端保留为后续入口选项)。

## 6. OSS research(≥3)

| 项目 | 事实能力 | 架构 | 活跃 | License | 复用 | 不复用 |
|---|---|---|---|---|---|---|
| Monolith | URL→单 HTML(资源内嵌 data:)+isolate | Rust CLI | 活跃(v2.10.1,本轮实测) | CC0(公共域) | **CLI 本体**(外部工具,非依赖) | — |
| SingleFile | 浏览器端整页单文件 | 扩展/CLI | 活跃 | AGPL-3.0 | 客户端入口思路 | — |
| ArchiveBox | 自归档服务(多 extractor 队列) | server+playwright | 活跃 | MIT | 队列/配额概念 | 不引常驻 playwright |
| Linkwarden | 链接+网页/截图/PDF 归档 | server+workers | 活跃 | AGPL-3.0 | 存储布局参考 | — |

## 7. Build vs reuse
**复用 monolith 二进制**(CC0、零依赖、单二进制,BFF 子进程调用);存储/
配额/去重 Lumi 自建。不部署 ArchiveBox(引入重型常驻服务)。

## 8. Proposed architecture

```text
Reader/Clip 详情 ──"保存快照"──► BFF snapshot job(串行队列)
   ├─ subprocess: monolith <url> -o data/library/assets/<uuid>/page.html -I -t 60
   ├─ 校验:大小 ≤ 50MB、MIME=html、checksum 入库
   └─ UPDATE library_items(kind='snapshot') → assets 路径经鉴权路由读出
路由: GET /api/v1/library/assets/{uuid}/page.html (single-user 鉴权内)
```

## 9. Data ownership
快照文件=Lumi assets;URL 元数据在 library_items;与 FreshRSS 零交集。
一个 URL 可同时有 Clip(可读)与 Snapshot(原样)——两个 kind 各自成行。

## 10. Data model(草案)
```sql
CREATE TABLE library_assets (
  uuid TEXT PRIMARY KEY, item_uuid TEXT NOT NULL REFERENCES library_items(uuid),
  path TEXT NOT NULL,             -- 相对 assets 根, 服务器生成的 uuid 路径
  bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
);
```

## 11. API contract(草案)
```text
POST /api/v1/library/snapshots {url|item_uuid} → 202 {asset_uuid, status}
GET  /api/v1/library/snapshots?cursor → {items[], nextCursor}
GET  /api/v1/library/assets/{uuid}/page.html → text/html(CSP 隔离沙箱头)
DELETE /api/v1/library/snapshots/{uuid} → 204
errors: snapshot_too_large / fetch_failed / quota_exceeded
```

## 12. Sync/lifecycle
create(子进程, 串行, 60s 超时)→ready/failed;delete(删文件+行);
cleanup(每日: 配额 LRU+sha256 去重引用计数)。

## 13. Security
SSRF 同基线;**快照渲染必须 iframe sandbox**(无 script 执行,禁止同源
cookie 泄露:serve 时加 `Content-Security-Policy: sandbox` + 独立路径);
路径仅服务器 uuid(基线 4);文件大小上限。

## 14. Resource budget(1.6GB)
实测:普通文章 4-18s、16-29MB RSS(子进程瞬时);图片极重页 79s/131MB/29MB
产物 → 串行执行+50MB 上限+2GB 配额(超限 LRU 清理+去重)是硬要求,不做
配额则 READY 不成立。无常驻进程。

## 15. UI information architecture
Reader 工具栏"快照"按钮;侧栏"网页快照"占位点亮为资产列表。

## 16. Desktop wireframe
```text
┌──────────┬───────────────────────────────┐
│ 侧栏      │ 详情页工具栏: [保存快照] [打开] │
│ 快照 ◀── ├───────────────────────────────┤
│          │ ▢ snap · url · 大小 · 时间      │
└──────────┴───────────────────────────────┘
```

## 17. Mobile wireframe(390px)
```text
┌──────────────────────┐
│ ▢ snap · 大小 · 时间  │
│ ▢ …                  │
│ [首页 订阅 搜索 收藏] │
└──────────────────────┘
```

## 18. States
empty/loading(generating 进度)/success/error(超限/失败)/offline(已存快照
可开)/permission(n/a)。

## 19. Accessibility
列表语义化;sandbox iframe 加 title;触控 44px;错误 alert。

## 20. Runnable PoC
`research/phase2-pocs/snapshots/poc_snapshots.sh`(monolith v2.10.1)。

## 21. PoC evidence(实跑)
```text
[1] OK  6.3s  1.13MB rss= 21MB lucumr.pocoo.org/2026/9/7/astra-why/
[2] OK  4.7s  0.11MB rss= 16MB simonwillison.net/2026/Sep/10/calif-research/
[3] OK 14.3s  3.19MB rss= 29MB blog.vllm.ai v1-alpha-release
[4] OK 18.3s  1.57MB rss= 24MB ruanyifeng weekly-issue-411
[5] OK 79.1s 29.05MB rss=131MB openai.com/news (图片极重页)
自包含验证:所有快照 <img|script|source src="http*"> 计数 = 0(资源全部内嵌)
```

## 22. Testing
integration:生成/删除/配额;E2E:保存→断网打开(Playwright offline);
security:sandbox 头断言、超大拒绝;perf:并发=1 队列。

## 23. Migration
新增 assets 卷(data/library/assets)与表;纳入 0018 backup 资产清单(可选)。

## 24. Rollback
禁用路由;删除 assets 目录不影响 RSS/Clip 文本数据。

## 25. Implementation Gates
```text
Gate 0: assets 目录+library_assets 表+配额常量(先于功能!)
Gate 1: monolith 子进程 job(串行)+大小/超时上限
Gate 2: 鉴权读出路由+iframe sandbox 渲染
Gate 3: 快照列表 UI+Reader 入口
Gate 4: 清理 job(去重/LRU)+错误态+E2E 断网验证
```

## 26. Expected commits
```text
feat(snapshots): assets storage with quota and dedup foundation
feat(snapshots): monolith job pipeline + sandboxed viewer
feat(snapshots): snapshot list UI + reader entry
```

## 27. Acceptance criteria
- [x] OSS/license(§6) [x] 架构/schema/API(§8/10/11) [x] 线框(§16/17)
- [x] 安全(§13) [x] 预算含实测(§14) [x] PoC 证据(§21) [x] Gates(§25)
- [x] 实施 prompt(§28) — 其余 checkbox 由实施 Gate 勾选

## 28. Standalone ZCode implementation prompt
```text
你在 LumiRSS 仓库(先读 AGENTS.md 与 docs/research/phase2/00-platform-architecture.md)。
实施"网页快照 v1":严格按 docs/research/phase2/02-web-snapshots.md §10/§11/§25。
硬约束:monolith 以外部二进制子进程调用(不进 Python 依赖);串行队列;单文件
50MB 上限;assets 总配额 2GB + sha256 去重 + LRU 清理 job 必须在 Gate 0 落地;
快照渲染仅经 iframe sandbox + CSP sandbox 头;抓取走 http_fetch 的 SSRF 防护
复核目标 URL;SQL inline literal+绑定参数。Non-goals:常驻浏览器、截图墙、
版本树。每 Gate 跑受影响测试,完成跑全量回归。
```
