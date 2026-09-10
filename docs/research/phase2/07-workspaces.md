# 07 工作区(Workspaces)

> 状态:READY FOR IMPLEMENTATION(PoC 已实跑:ItemRef 工作区模型+联邦视图;
> 移动信息架构不受冲击方案已定)
> 公共内容见 [00-platform](00-platform-architecture.md)。

## 1. Executive decision
**RECOMMENDED** — Workspace = 有序的 **ItemRef 集合 + 面板/笔记元数据**,
不复制任何内容;RSS 与 Library 两大域统一入列。它是 Phase 2 的组织基座
(阅读队列 read-later 即预置工作区)。

## 2. Problem
"围绕一个主题的阅读"散落在:star、未读、外部笔记。用户需要把 RSS 条目、
剪藏、书签、vault 笔记聚合成可命名的项目(例:"考研"、"AI 研究"),并
在其中工作(标注/汇总/Agent 操作)。

## 3. Current LumiRSS gap
无工作区概念;侧栏占位;收藏(star)是布尔标记,无组织结构。

## 4. User stories
- 普通:新建工作区 → 从时间线/书签/笔记"添加到工作区" → 拖动排序 →
  工作区视图统一展示两类来源。
- 移动:入口在"更多/工作区"(不进底部 Tab),列表+详情两级。
- 失败:被引用的 RSS 条目随 FreshRSS 清理而失效 → 行保留,渲染为
  "源已失效"占位(可一键移除)。
- offline:已加载工作区列表缓存;增删动作排队。

## 5. Non-goals
v1 不做:协作/分享、看板视图、嵌套工作区、权限(单用户)。

## 6. OSS research(≥3)

| 项目 | 事实能力 | 架构 | 活跃 | License | 复用 | 不复用 |
|---|---|---|---|---|---|---|
| Readwise Reader | 阅读队列+高亮+文档聚合 | 云服务 | 商业 | — | "队列=工作区"交互模式 | — |
| Zotero | 文献集合(collections=引用不复制) | 本地+同步 | 活跃 | AGPL-3.0 | **collection-of-refs 模型** | — |
| Karakeep | 列表(lists)聚合书签 | server | 活跃 | AGPL-3.0 | 列表 UX | — |
| Obsidian | 文件夹/标签组织 | 本地文件 | 活跃 | 商业(免费) | — | — |

## 7. Build vs reuse
自建(模型即 §10 两张表;Zotero 证明 ref-collection 是久经考验的组织形态)。

## 8. Proposed architecture

```text
任意内容卡片 ─"添加到工作区"─► POST /workspaces/{id}/items {item_ref}
                                     │ 只存 ref + position
                                     ▼
Workspace 视图: BFF resolve(ref) → EntryView | LibraryItemView
     (RSS 条目实时从 FreshRSSAdapter 取, 永不落副本)
read-later = 预置 workspace(workspace_id='read-later', 不可删)
```

## 9. Data ownership
workspace_items=Lumi;RSS 内容=FreshRSS(仅引用);Library 内容=各 kind 表。

## 10. Data model(草案)
```sql
CREATE TABLE workspaces (
  id TEXT PRIMARY KEY,                 -- 'read-later' 为保留 id
  name TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE workspace_items (
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  item_ref TEXT NOT NULL,              -- 'rss:<…>' | 'library:<uuid>' (typed)
  position INTEGER NOT NULL DEFAULT 0, added_at TEXT NOT NULL,
  UNIQUE (workspace_id, item_ref)
);
```

## 11. API contract(草案)
```text
POST   /api/v1/workspaces {name} → {id}
GET    /api/v1/workspaces → [{id,name,itemCount}]
GET    /api/v1/workspaces/{id}/items ?cursor → {items:[{ref,resolved}], nextCursor}
POST   /api/v1/workspaces/{id}/items {item_ref} → {position}
DELETE /api/v1/workspaces/{id}/items/{ref} / DELETE /api/v1/workspaces/{id}
PATCH  /api/v1/workspaces/{id}/items (批量重排序: [{ref,position}])
errors: invalid_ref / ref_stale(RSS 源已失效) / reserved_id
```

## 12. Sync/lifecycle
纯 CRUD;ref 失效在读取时惰性发现(条目 404→标记 stale,不自动删)。

## 13. Security
ref 严格前缀校验(rss:/library:);批量重排序接受上限 500 项/请求;
无其他新增面。

## 14. Resource budget(1.6GB)
两行/成员(~120B);UI 解析 RSS ref 走现有 entry 读路径,零额外内存压力。
PoC <1ms/操作。

## 15. UI information architecture
桌面:侧栏"工作区"组(列出现有+新建);移动:底部 4 Tab 不变,工作区从
"更多"进入。read-later 在列表页与侧栏同时可达。

## 16. Desktop wireframe
```text
┌──────────┬──────────────────────────────┐
│ 工作区    │ ▢ 1. vLLM V1 (RSS)           │
│ ▢ AI 研究◀│ ▢ 2. 本地翻译笔记 (Library)   │
│ ▢ 考研    │ ▢ 3. …     [拖动排序]        │
│ + 新建    │ [添加条目______]              │
└──────────┴──────────────────────────────┘
```

## 17. Mobile wireframe(390px)
```text
┌──────────────────────┐
│ AI 研究(12)     [+]  │
│ 1. vLLM V1 (RSS)     │
│ 2. 翻译笔记 (Lib)    │
│ [首页 订阅 搜索 收藏] │
└──────────────────────┘
```

## 18. States
empty/loading/success/ref-stale(占位+移除)/offline(动作排队)/permission(n/a)。

## 19. Accessibility
拖动排序必须提供键盘等价(上移/下移按钮);列表语义;44px 触控。

## 20. Runnable PoC
`research/phase2-pocs/workspaces/poc_workspaces.py`(refs-only 工作区+
联邦收藏/稍后读/统一 FTS 搜索视图)。

## 21. PoC evidence(实跑)
```text
federated favorites: [('library','lib:0001'), ('rss','rss:fr:e1001')]
read-later queue:    [('library','lib:0001','Bergamot model registry'), …,
                      ('rss','rss:fr:e1001','')]
search 'translation': [('lib:0002','Local translation notes')]
search 'vllm':        [('rss:fr:e1001','vLLM V1 release notes')]
workspace rss rows violating ref-only shape (must be 0): 0
OK in 0.001s
```

## 22. Testing
unit:ref 校验/排序;integration:两类 ref 的 resolve/stale 矩阵;E2E:
添加-排序-移除-工作区视图双来源渲染。

## 23. Migration
纯新增;read-later 预置行由迁移创建。

## 24. Rollback
删表即净(RSS/library 内容本就不在工作区里)。

## 25. Implementation Gates
```text
Gate 0: 表+CRUD API(含 reserved read-later)
Gate 1: 时间线/书签/笔记的"添加到工作区"动作
Gate 2: 工作区视图(双来源 resolve 渲染)+键盘排序
Gate 3: stale 占位与清理
```

## 26. Expected commits
```text
feat(workspaces): ref-collection model with reserved read-later
feat(workspaces): workspace view and add-to-workspace actions
```

## 27. Acceptance criteria
- [x] OSS(§6) [x] schema/API(§10/11) [x] 线框(§16/17) [x] PoC 证据(§21)
- [x] ref-only 断言(§21) [x] a11y 键盘排序(§19) [x] prompt(§28)

## 28. Standalone ZCode implementation prompt
```text
你在 LumiRSS 仓库(先读 AGENTS.md 与 docs/research/phase2/00-platform-architecture.md)。
实施"工作区 v1"按 docs/research/phase2/07-workspaces.md §10/§11/§25。硬约束:
workspace_items 只存 typed ItemRef(rss:|library:),任何内容复制都是实现错误;
read-later 为保留 id 由迁移预置;RSS ref 读取失败标记 stale 不自动删;
排序提供键盘等价操作;SQL inline literal+绑定参数。Non-goals:协作/看板/
嵌套。每 Gate 跑受影响测试,完成跑全量回归。
```
