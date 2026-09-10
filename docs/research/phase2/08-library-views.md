# 08 稍后读 / 收藏 / 搜索统一(Library Views)

> 状态:READY FOR IMPLEMENTATION( federated 视图 PoC 已实跑;搜索统一复用
> 现有 FTS 投影扩展,零新引擎)
> 公共内容见 [00-platform](00-platform-architecture.md)。

## 1. Executive decision
**RECOMMENDED** — RSS Favorite 继续存 FreshRSS star;Library Favorite 存
Lumi;UI 提供联邦"收藏/稍后读"视图,底层 ownership 不变;统一搜索=现有
`search_entries` 投影扩展出 library FTS 表 + 两个结果集合并排序,不把所有
内容塞进一张大表。

## 2. Problem
两大域并存后:收藏/稍后读/搜索都面临"各自一半"的割裂;用户要求一个入口,
但架构上不允许把 FreshRSS 数据复制进来。

## 3. Current LumiRSS gap
`search_entries` 仅 RSS;收藏仅 star;时间线仅 RSS。搜索的增量子同步、
keyset 分页、snippet 均已就绪(实测 p95<12ms@4.3k 条)。

## 4. User stories
- 普通:收藏页同时看到 RSS star 与 library 收藏,带域徽标;搜索一次出
  两类结果。
- 移动:同一底部"收藏/搜索"入口,结果分组展示。
- 失败:library FTS 损坏 → 自动 rebuild(rebuildable 投影);RSS 侧上游
  故障 → library 结果仍可用(分区降级)。
- offline:按现有 app-shell 缓存行为。

## 5. Non-goals
不复制 RSS 正文进 Lumi 表;不做跨域相关性学习/个性化排序;不做联合查询
下钻 SQL 大宽表。

## 6. OSS research(≥3)

| 项目 | 事实能力 | 架构 | 活跃 | License | 复用 | 不复用 |
|---|---|---|---|---|---|---|
| FreshRSS(自身) | star/标签/搜索边界 | 已在栈 | 活跃 | AGPL-3.0 | star 真源不动 | — |
| Miniflux | 简单 FTS 集成模式 | Go+PG | 活跃 | Apache-2.0 | 结果合并思路 | — |
| Linkding | bookmark 全文搜索(SQLite FTS) | Django | 活跃 | MIT | FTS5 tokenization 经验 | — |
| SQLite FTS5 | 内置全文引擎 | 库 | 稳定 | PD | **已有栈内**(现有投影即 FTS 形态) | — |

## 7. Build vs reuse
完全复用现有 SQLite/FTS 投影模式(仓库已有 search_entries 形态);新增
`search_library` FTS 表 + 服务层合并。

## 8. Proposed architecture

```text
统一搜索 GET /api/v1/search?q=…
  ├─ RSS leg:   现有 search_entries 投影(不变)
  ├─ Library leg: search_library FTS(bookmarks/clips/notes… 各 kind 写入时投影)
  └─ merge: 分组返回(rss[] library[])或 RRF 排序(mode 参数, 默认分组)
收藏页 GET /api/v1/favorites        → {rss:[star refs], library:[uuids]}
稍后读 GET /api/v1/workspaces/read-later/items(07 号预置工作区)
```

## 9. Data ownership
不变:RSS star=FreshRSS;library 收藏=Lumi;两个 FTS 表都是各自域的
派生投影(rebuildable)。

## 10. Data model(草案)
```sql
CREATE VIRTUAL TABLE search_library USING fts5(
  ref UNINDEXED, kind, title, body, url, tokenize='unicode61'
);
-- ref = 'library:<uuid>'; 写入点: bookmark/clip/note 各自的 upsert 后投影
```

## 11. API contract(草案)
```text
GET /api/v1/search?q=&mode=grouped|fused&limit&cursor → {rss:[…], library:[…]} | {items:[…]}
GET /api/v1/favorites → {rss:[{entryRef,…}], library:[{uuid,…}]}
POST /api/v1/library/favorites {item_ref} / DELETE …/{ref}
errors: 沿用现有 SearchQueryError;library 腿失败不影响 rss 腿(部分 200 + warning)
```

## 12. Sync/lifecycle
library 投影=各 kind 写路径同步写(同现有 search_writer 模式);
rebuild 端点复用现有 /search/rebuild 语义,扩展 library 腿。

## 13. Security
无新外部面;FTS 串转义沿用 like_pattern/ESCAPE 约定;部分失败响应
显式标注,不静默。

## 14. Resource budget(1.6GB)
新增 FTS 表 ≈ 内容体积 ×~0.3;万级 library 条目 <10MB。查询双腿 <20ms
(实测单腿 p50 5-11ms)。零新进程。

## 15. UI information architecture
搜索页结果分组(RSS/Library 标签页或分组头);收藏页双域;卡片复用
UnifiedContentCard(12 号 UI 报告)。

## 16. Desktop wireframe
```text
┌────────────────────────────────┐
│ [搜索_______________]           │
│ ── RSS(12)──────────────────   │
│ ▢ 标题 · feed · 摘要            │
│ ── Library(4)───────────────   │
│ ▢ 标题 · kind · url             │
└────────────────────────────────┘
```

## 17. Mobile wireframe(390px)
```text
┌──────────────────────┐
│ [搜索___________]    │
│ RSS(12) | Lib(4)    │
│ ▢ 结果 · 摘要        │
│ [首页 订阅 搜索 收藏] │
└──────────────────────┘
```

## 18. States
双腿独立 loading/empty/error(分腿提示"库暂不可用,RSS 结果不受影响");
分页沿用 opaque cursor。

## 19. Accessibility
分组标题为 heading;域徽标非纯色差(带文字);键盘结果导航沿用现有列表。

## 20. Runnable PoC
`research/phase2-pocs/workspaces/poc_workspaces.py`(含统一 FTS 双域查询与
federated favorites 视图——同一 PoC 覆盖 07/08)。

## 21. PoC evidence(实跑)
```text
search 'translation': [('lib:0002','Local translation notes')]
search 'vllm':        [('rss:fr:e1001','vLLM V1 release notes')]
federated favorites: [('library','lib:0001'), ('rss','rss:fr:e1001')]
现有 RSS 搜索腿实测(46 feeds/4287 条): p50 5.4-10.5ms, p95 ≤11.3ms
```

## 22. Testing
unit:合并排序/部分失败;integration:library 投影写入→双域搜索;E2E:
收藏页双域+搜索分组;perf:万级 library 腿 p95。

## 23. Migration
search_library 表新增;现有 /search 响应形状向后兼容(新增 library 字段)。

## 24. Rollback
mode 参数回退 grouped-only;删表无 RSS 影响。

## 25. Implementation Gates
```text
Gate 0: search_library 表+投影 writer(挂 05/06 写路径)
Gate 1: /search 双腿+grouped 模式
Gate 2: 收藏双域 API+UI
Gate 3: fused(RRF) 模式(可选开关)
```

## 26. Expected commits
```text
feat(library-views): library fts projection alongside rss leg
feat(library-views): unified search + federated favorites
```

## 27. Acceptance criteria
- [x] OSS(§6) [x] 架构/API(§8/11) [x] 线框(§16/17) [x] PoC 证据(§21)
- [x] 性能引用实测(§14/21) [x] prompt(§28)

## 28. Standalone ZCode implementation prompt
```text
你在 LumiRSS 仓库(先读 AGENTS.md 与 docs/research/phase2/00-platform-architecture.md)。
实施"统一视图 v1"按 docs/research/phase2/08-library-views.md §10/§11/§25。
硬约束:不复制 RSS 正文;library FTS 为独立投影表(rebuildable),写入点在
各 kind 的 upsert;双腿查询部分失败必须显式暴露(部分 200+warning),不得
让 library 故障拖垮 RSS 搜索;FTS 查询串沿用现有转义约定;opaque cursor
不变。每 Gate 跑受影响测试,完成跑全量回归。
```
