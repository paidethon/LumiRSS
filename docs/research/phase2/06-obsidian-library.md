# 06 Obsidian 库(Obsidian Vault Integration)

> 状态:READY FOR IMPLEMENTATION(100 文件假 vault PoC 已实跑:全量 10ms、
> 增量/改名/删除正确;推荐只读投影架构)
> 公共内容见 [00-platform](00-platform-architecture.md)。

## 1. Executive decision
**RECOMMENDED** — **Vault = source of truth,LumiRSS = 只读派生索引**。
接入方式优先级:A. 本地文件系统(vault 与服务同机)→ D. Obsidian URI(仅
跳转回写用)→ 其他(B/C/E/F)延后。默认绝不由 LumiRSS 改写用户笔记。

## 2. Problem
用户(开发者/研究者)的知识在 Obsidian vault 里;RSS+剪藏信息需要与既有
知识库互相引用、统一搜索/图谱/RAG。不解决则 Phase 2 的"统一阅读+知识"
愿景断在 vault 墙外。

## 3. Current LumiRSS gap
无 vault 感知、无 Markdown 管线、无文件监听;search 只投影 RSS。

## 4. User stories
- 普通:配置 vault 路径 → 全量索引 → 之后笔记保存即出现在"Obsidian 库"
  与统一搜索。
- 移动:只读浏览/搜索 vault 笔记(编辑去 Obsidian——跳转 Obsidian URI)。
- 失败:vault 不可达 → 索引保留上次状态+错误标记;大 vault(万级)→
  增量扫描。
- offline:本地场景 vault 天然在本机;remote 场景(WebDAV)属延后。

## 5. Non-goals
v1 不做:写回笔记(除"打开 in Obsidian"URI 跳转)、WebDAV/移动 vault 同步、
canvas/excalidraw 渲染、插件发布。

## 6. OSS research(≥3)

| 项目 | 事实能力 | 架构 | 活跃 | License | 复用 | 不复用 |
|---|---|---|---|---|---|---|
| Obsidian Local REST API | 社区插件:本地 REST 读写 vault | 插件 | 活跃 | MIT | 可选 E 路线 | 要求用户装插件 |
| Foamsys/foam | vault 作为知识库工具链 | VSCode 扩展 | 活跃 | MIT | wikilink 约定理解 | — |
| Logseq | 大纲+文件库 | Electron | 活跃 | AGPL-3.0 | md 解析兼容教训 | — |
| markdown-it / mistune | 成熟 Markdown 解析 | 库 | 活跃 | MIT(both) | **解析器本体** | 不用正则自解析 |
| python-frontmatter | frontmatter 解析 | 库 | 活跃 | MIT | PoC 已验证 | — |

## 7. Build vs reuse
**复用成熟 parser**(mistune/markdown-it,任务红线:禁正则自解析);
扫描/增量/改名检测 Lumi 自建(极简 fingerprint 方案,PoC 验证);
Obsidian 品牌资产/图标一律不用。

## 8. Proposed architecture

```text
Vault(用户文件系统, source of truth)
  │ 扫描器(BFF 内 job: 全量 or (mtime,size) fingerprint 增量; watchdog 可选)
  ├─ frontmatter + wikilink + tag + image 提取(mistune AST, 不用正则)
  └─ upsert library_items(kind='obsidian_note', path 唯一) + FTS 投影
改名 = 内容指纹匹配(move); 删除 = 索引移除(vault 永远是真源)
跳转: obsidian://open?vault=…&file=…(仅客户端链接, 不经 BFF)
```

## 9. Data ownership
Vault 文件=真源;library_items 行与 FTS 投影=derived(rebuildable, 可全量
重建不丢信息)。LumiRSS 对 vault **零写入**。

## 10. Data model(草案)
```sql
CREATE TABLE obsidian_notes (
  uuid TEXT PRIMARY KEY,
  rel_path TEXT NOT NULL UNIQUE,       -- vault 相对路径(唯一键)
  fingerprint TEXT NOT NULL,           -- mtime_ns:size
  title TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]',   -- JSON array
  wikilinks TEXT NOT NULL DEFAULT '[]',                   -- JSON array of target paths
  body_text TEXT NOT NULL,             -- 派生纯文本(FTS/RAG 用)
  indexed_at TEXT NOT NULL
);
```

## 11. API contract(草案)
```text
PUT  /api/v1/obsidian/settings {vault_path} → {scan: started}
POST /api/v1/obsidian/rescan → {added,changed,removed,renames}
GET  /api/v1/obsidian/notes ?cursor&limit&q= → {items[], nextCursor}
GET  /api/v1/obsidian/notes/{uuid} → note view(+渲染后 md→html)
errors: vault_unreachable / permission_denied
```

## 12. Sync/lifecycle
设置路径→全量扫描;每 N 分钟(或 watchdog 事件)增量;改名按指纹迁移;
删除=移除索引;重建=删投影重扫(vault 无损)。

## 13. Security
路径校验:配置的 vault 根之外一律拒绝(基线 4);**只读打开**;结果注入
走净化文本管线;URI 跳转仅白名单 `obsidian://`(基线 1 引申)。

## 14. Resource budget(1.6GB)
PoC 实测:100 文件全量 10ms、增量 <10ms;万级笔记(平均 5KB)≈ 50MB 文本+
索引 ~100MB 磁盘,内存增量峰值 <50MB(流式)。零常驻进程(扫描为 job)。

## 15. UI information architecture
侧栏"Obsidian 库"列表(文件夹树或平铺+搜索);笔记阅读复用 Reader(md 渲染
管线与 RSS 正文同界);跳转 Obsidian 按钮。

## 16. Desktop wireframe
```text
┌──────────┬─────────────────────────────┐
│ 侧栏      │ [搜索笔记____]  [重扫]       │
│ Obsidian ├─────────────────────────────┤
│ 库 ◀──   │ ▢ 标题 · 标签 · 修改时间      │
│          │ 详情: 渲染正文 | 在 Obsidian 打开│
└──────────┴─────────────────────────────┘
```

## 17. Mobile wireframe(390px)
```text
┌──────────────────────┐
│ [搜索笔记____]       │
│ ▢ 标题 · 标签        │
│ [首页 订阅 搜索 收藏] │
└──────────────────────┘
```

## 18. States
unconfigured(引导)/scanning(进度)/ready/error(vault 不可达, 保留旧索引)/
offline(本地 n/a)/permission(权限错误分型)。

## 19. Accessibility
文件树用 tree 语义(或平铺 list 规避);"在 Obsidian 打开"为新窗口明示;
reduced-motion 下扫描动画静止。

## 20. Runnable PoC
`research/phase2-pocs/obsidian/poc_obsidian.py`(生成 100 文件含中文文件名/
frontmatter/wikilink/tag/图片 → 扫描 → 触摸/新增/删除/改名 → 增量同步)。

## 21. PoC evidence(实跑)
```text
fixture vault: 100 md files, 113 total entries
full scan: 100 notes in 0.01s
  sample tags=['ai','topic-0','随手笔记0'] links=['note-001-transformer'] images=['assets/img-0.png']
  chinese-named notes indexed: 25 (e.g. AI/深度学习/note-000-注意力机制.md)
incremental rescan 0.00s -> added=2 changed=1 removed=1
  renames=[('AI/深度学习/note-030-transformer.md','AI/深度学习/note-030-renamed-transformer.md')]
wikilink graph edges resolvable: 199
```

## 22. Testing
unit:frontmatter/wikilink/tag 提取(快照);integration:全量/增量/改名/
删除矩阵(PoC 同款);security:路径逃逸矩阵;E2E:配置→扫描→搜索→打开。

## 23. Migration
纯新增;FTS 投影挂现有 search 体系(08 号统一视图)。

## 24. Rollback
清空设置+删投影表即净;vault 文件零影响(只读铁律)。

## 25. Implementation Gates
```text
Gate 0: settings+表+扫描器(纯函数, PoC 逻辑产品化)
Gate 1: md→html 渲染接入 Reader(净化边界)
Gate 2: 列表/搜索 UI + obsidian:// 跳转
Gate 3: 增量 job + 错误态 + 万级文件性能验证
```

## 26. Expected commits
```text
feat(obsidian): read-only vault scanner with incremental sync
feat(obsidian): note rendering and unified search projection
feat(obsidian): library UI with obsidian-uri deep link
```

## 27. Acceptance criteria
- [x] OSS/license(§6) [x] 架构/schema/API(§8/10/11) [x] 线框(§16/17)
- [x] 安全含路径逃逸(§13) [x] 预算含实测(§14) [x] PoC 证据(§21)
- [x] Gates(§25) [x] prompt(§28)

## 28. Standalone ZCode implementation prompt
```text
你在 LumiRSS 仓库(先读 AGENTS.md 与 docs/research/phase2/00-platform-architecture.md)。
实施"Obsidian 只读集成 v1"按 docs/research/phase2/06-obsidian-library.md
§10/§11/§25。硬约束:vault 绝对只读(代码评审必须证明无写路径);Markdown
解析用 mistune(markdown-it 系),禁止正则自解析;增量用 (mtime_ns,size)
指纹,改名按内容指纹迁移;rel_path 唯一;路径校验防逃逸;md→html 必须过
净化;SQL inline literal+绑定参数。Non-goals:写回、WebDAV、canvas 渲染。
每 Gate 跑受影响测试,完成跑全量回归。
```
