# 05 书签(Bookmarks)与 稍后读/收藏的边界

> 状态:READY FOR IMPLEMENTATION(PoC 已实跑:Netscape 导入导出无损往返)
> 公共内容见 [00-platform](00-platform-architecture.md)。

## 1. Executive decision
**RECOMMENDED** — v1:Library 域 bookmark + Netscape HTML 导入导出;
三个概念严格分层:**Bookmark=长期保存链接 / Read Later=阅读队列(workspace)
/ Favorite=高价值标记(分域:RSS star / library favorite)**。

## 2. Problem
用户从 Pocket/浏览器迁移书签;并需要在阅读器里区分"存着以后看"(队列)与
"这是我的知识库"(书签)。现有收藏=FreshRSS star,只覆盖 RSS。

## 3. Current LumiRSS gap
star 走 FreshRSS(greader edit-tag);无 library 域;无导入导出;
侧栏"书签 Phase 2"占位。

## 4. User stories
- 普通:粘贴 URL 存书签(标题自动抓取,复用 01 提取器可选);从时间线
  "存书签"(RSS entry→只存 ref+元数据,不复制正文)。
- 迁移:导入浏览器导出的 bookmarks.html(千级)→ 去重+进度。
- 移动:书签列表/一键添加;稍后读=workspace 特例(见 07)。
- 失败:重复 URL→幂等更新;损坏导入文件→逐行容错+报告。

## 5. Non-goals
v1 不做:全文快照(02 号)、协作分享、浏览器插件同步(floccus 类)、
标签管理 UI(11 号)。

## 6. OSS research(≥3)

| 项目 | 事实能力 | 架构 | 活跃 | License | 复用 | 不复用 |
|---|---|---|---|---|---|---|
| linkding | 极简书签+标签+全文检索 | Django 单容器 | 活跃 | MIT | 数据模型/UX 简洁性 | 不引 Django |
| Karakeep | 书签+AI 标签+全文 | server+web | 活跃 | AGPL-3.0 | 概念参考 | 整体方案 |
| Linkwarden | 书签+归档协作 | server | 活跃 | AGPL-3.0 | 导入导出格式 | — |
| Shiori | 自托管书签 | Go 单二进制 | 活跃 | MIT | 单二进制理念 | — |
| Floccus | 浏览器书签同步 | 扩展 | 活跃 | MPL-2.0 | — | v1 不做同步 |

## 7. Build vs reuse
Lumi 自建(表极简);导入导出解析器自写(Netscape 格式是稳定事实标准,
PoC 证明 <100 行);提取标题复用 01 号 Defuddle/Readability。

## 8. Proposed architecture

```text
添加: 粘贴 URL ─► POST /library/bookmarks ─► (可选)标题抓取(01 管线)
RSS entry ──"存书签"──► POST {item_type:'rss', entry_ref} ─► 只存 ref+快照元数据
导入: 上传 bookmarks.html ─► 解析(poc 解析器) ─► 批量 upsert(唯一 url)
导出: GET /library/bookmarks/export.html ─► Netscape 格式(文件夹=tags 映射)
```

## 9. Data ownership
bookmark 行=Lumi;RSS entry 的正文/已读/star 仍归 FreshRSS——bookmark 对
RSS 条目仅保存 `rss:<ref>` + title/url 快照元数据(不含正文)。

## 10. Data model(草案)
```sql
CREATE TABLE library_bookmarks (
  uuid TEXT PRIMARY KEY,
  item_type TEXT NOT NULL CHECK (item_type IN ('url','rss')),
  url TEXT,                      -- kind=url 必填
  rss_item_ref TEXT,             -- kind=rss: rss:<opaque-ref>
  title TEXT NOT NULL, note TEXT,
  created_at TEXT NOT NULL,
  CHECK ((item_type='url') = (url IS NOT NULL))
);
CREATE UNIQUE INDEX ux_bookmarks_url ON library_bookmarks(url) WHERE url IS NOT NULL;
```

## 11. API contract(草案)
```text
POST   /api/v1/library/bookmarks {url|entry_ref, title?, note?} → {uuid}
GET    /api/v1/library/bookmarks ?cursor&limit&q= → {items[], nextCursor}
PUT    /api/v1/library/bookmarks/{uuid} (note/title) / DELETE → 204
POST   /api/v1/library/bookmarks/import  (multipart bookmarks.html) → {imported, skipped, failed[]}
GET    /api/v1/library/bookmarks/export.html → Netscape HTML
errors: invalid_url / duplicate(幂等更新, 返回既有 uuid)
```

## 12. Sync/lifecycle
create(可延迟抓标题)→update(note)→delete;import 为一次性批量 upsert;
导出无状态(即时生成)。

## 13. Security
URL scheme 白名单(http/https);导入 HTML 按不可信解析(大小上限 10MB、
行数上限);RSS ref 校验为合法 opaque ref(防注入任意字符串)。

## 14. Resource budget(1.6GB)
书签行 ~200B/条(不抓正文);1 万条≈2MB。导入批处理分页(500/批)。
零新进程。

## 15. UI information architecture
侧栏"书签"列表页;时间线卡片菜单加"存书签";稍后读=workspace `read-later`
(07 号),UI 上"稍后读"动作写 workspace 而非 bookmark。

## 16. Desktop wireframe
```text
┌──────────┬──────────────────────────────┐
│ 侧栏      │ [搜索____] [导入] [导出] [+]  │
│ 书签 ◀── ├──────────────────────────────┤
│          │ ▢ 标题 · url · note · 标签    │
└──────────┴──────────────────────────────┘
```

## 17. Mobile wireframe(390px)
```text
┌──────────────────────┐
│ [搜索____]      [+]  │
│ ▢ 标题 · url        │
│ [首页 订阅 搜索 收藏] │
└──────────────────────┘
```

## 18. States
empty/loading/success/error(导入报告: skipped/failed 计数可展开)/
offline(添加动作本地排队)/permission(n/a)。

## 19. Accessibility
列表/表单语义;导入报告为可聚焦 region;44px 触控;复制按钮有 label。

## 20. Runnable PoC
`research/phase2-pocs/bookmarks/poc_bookmarks.py`。

## 21. PoC evidence(实跑)
```text
parsed 4 bookmarks
  AI Reading        Sandboxed Python        tags=['llm','sandbox']
  AI Reading        vLLM V1                 tags=[]
  AI Reading/Deep Dives Diffusion Notes     tags=['diffusion']
  (root)            HN                      tags=[]
roundtrip lossless: True
(嵌套文件夹/标签属性/中文均可; 导出文件同目录)
```

## 22. Testing
unit:解析往返/去重/scheme 校验;integration:导入 1000 条分页批处理;
E2E:导入→搜索→导出→再导入无损;security:恶意 HTML 导入容错。

## 23. Migration
纯新增;"RSS 收藏"不动(仍 star)。

## 24. Rollback
删表+入口即净。

## 25. Implementation Gates
```text
Gate 0: 表+CRUD API(+唯一 url 幂等)
Gate 1: 列表/添加/删除 UI(+RSS entry 存 ref 书签)
Gate 2: 导入导出(流式解析, 报告 UI)
Gate 3: 标题自动抓取(复用 01 提取, 可关闭)
```

## 26. Expected commits
```text
feat(bookmarks): bookmark store with dedupe and rss refs
feat(bookmarks): netscape import/export
feat(bookmarks): list UI + timeline save action
```

## 27. Acceptance criteria
- [x] OSS/license(§6) [x] schema/API(§10/11) [x] 线框(§16/17)
- [x] PoC 证据(§21) [x] 三概念分层清晰(§1) [x] Gates(§25) [x] prompt(§28)

## 28. Standalone ZCode implementation prompt
```text
你在 LumiRSS 仓库(先读 AGENTS.md 与 docs/research/phase2/00-platform-architecture.md)。
实施"书签 v1"按 docs/research/phase2/05-bookmarks.md §10/§11/§25。硬约束:
RSS 条目书签只存 rss:<opaque-ref>+元数据,绝不复制正文;URL scheme 白名单
http/https;导入解析按不可信输入(大小/行数上限);url 唯一索引幂等;
"稍后读"不写 bookmark 表(写 workspace);SQL inline literal+绑定参数。
Non-goals:同步/协作/快照。每 Gate 跑受影响测试,完成跑全量回归。
```
