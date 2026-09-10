# 11 标签与图谱(Tags & Graph)

> 状态:READY FOR IMPLEMENTATION(渲染性能 PoC 已实跑:Cytoscape 2000 节点
> 43FPS;标签模型含 AI 建议默认仅"建议"不自动写入)
> 公共内容见 [00-platform](00-platform-architecture.md)。

## 1. Executive decision
**RECOMMENDED(分两期)** — 一期:统一标签模型(手动/来源/AI 建议,后者
默认仅建议);二期:图谱只读视图(Cytoscape.js canvas 渲染)。**不为漂亮
做一团毛线**:图=真实关系(Item↔Tag/Source/Workspace、wikilink、引用)。

## 2. Problem
内容多起来后需要横切组织维度:标签(跨源聚合)与关系图(发现"这篇笔记
引用了那篇 RSS 文章")。

## 3. Current LumiRSS gap
RSS 源分类=FreshRSS category;library 无标签;无图谱;vault wikilink 已在
06 号提取(PoC 199 边)。

## 4. User stories
- 普通:给笔记/RSS 条目打标签;AI 建议标签出现在卡片旁,一键采纳。
- 移动:标签列表+过滤;图谱为桌面优先,移动只读缩放。
- 失败:AI 建议失败→不阻塞手动标签;图谱数据损坏→按关系表重建。
- offline:标签列表缓存;图谱大图不缓存。

## 5. Non-goals
不做:自动打标(未经审核)、图算法中心性分析产品化、协作编辑、跨设备
图谱同步冲突。

## 6. OSS research(≥3)

| 项目 | 事实能力 | 架构 | 活跃 | License | 复用 | 不复用 |
|---|---|---|---|---|---|---|
| Cytoscape.js | 图渲染+布局+算法(canvas) | 库 | 活跃 | MIT | **渲染本体(默认)** | — |
| Sigma.js | WebGL 大图渲染 | 库 | 活跃 | MIT | 万级节点时的升级路线 | — |
| react-force-graph | 3D/力导向封装 | 库 | 活跃 | MIT | — | 3D 非需求 |
| React Flow | 节点编辑器 | 库 | 活跃 | MIT | — | **编辑器≠知识图谱**(不因流行误选) |
| Obsidian graph | 本地图谱 UX | 产品 | 活跃 | 商业 | 交互模式参考 | — |

## 7. Build vs reuse
渲染复用 Cytoscape.js(MIT;PoC 2000 节点 43FPS 足够一期);标签模型自建
(两张表);AI 建议复用现有 ai_provider。

## 8. Proposed architecture

```text
标签: manual(用户) + source(来源固有, 如 feed 分类) + suggested(AI, 默认 suggested 状态)
  tags(id,name UNIQUE) ←→ item_tags(item_ref, tag_id, origin, status)
图谱边(全部由既有关系派生, 只读视图):
  item→tag(item_tags)  item→source(feed)  item→workspace(workspace_items)
  note→note(vault wikilinks, 06 号已提取)  clip→url 引用(可选一期不做)
渲染: GET /api/v1/graph?scope=… → {nodes,edges} (上限 2000, 超出按度数截断)
      → Cytoscape canvas, 详情点击→ItemRef 跳转
```

## 9. Data ownership
标签/边=Lumi(关系层);被指内容仍归各自真源;wikilink 边=派生(来自 vault)。

## 10. Data model(草案)
```sql
CREATE TABLE tags (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE
);
CREATE TABLE item_tags (
  item_ref TEXT NOT NULL,             -- typed ItemRef
  tag_id INTEGER NOT NULL REFERENCES tags(id),
  origin TEXT NOT NULL CHECK (origin IN ('manual','source','ai')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','suggested')),
  created_at TEXT NOT NULL,
  UNIQUE (item_ref, tag_id, origin)
);
```

## 11. API contract(草案)
```text
GET  /api/v1/tags ?q= → [{id,name,count}]
PUT  /api/v1/tags/{id} / DELETE(级联 item_tags)
POST /api/v1/tags/assign {item_ref, name, origin=manual}
GET  /api/v1/tags/suggestions/{item_ref} → [{name}](AI, 未落库)
POST /api/v1/tags/suggestions/{item_ref}/accept {name}
GET  /api/v1/graph ?scope=library|workspace:{id}&max=2000 → {nodes:[{ref,label,kind}],edges:[{src,dst,kind}]}
errors: too_many_nodes(截断标志) / invalid_ref
```

## 12. Sync/lifecycle
assign/delete 即时;suggested→accept=升级为 manual 行(不复制);图谱视图
即时从关系表组装(无独立图存储, rebuildable by design)。

## 13. Security
无新外部面;graph 响应按 scope 鉴权(单用户单一);标签名长度/转义;
AI 建议不自动落库(安全=防止提示注入污染库,与 10 号同源规则)。

## 14. Resource budget(1.6GB)
两表 + 图响应(<1MB);渲染在客户端(canvas/WebGPU 无关);PoC 2000 节点
heap 10MB(客户端)。服务端零新进程。

## 15. UI information architecture
侧栏"标签"过滤列表 + "图谱"只读视图;卡片标签徽标(建议=虚线样式)。

## 16. Desktop wireframe
```text
┌──────────┬──────────────────────────────┐
│ 标签      │  ┌────────────────────────┐  │
│ #ai(89)◀ │  │   力导向/网格 图视图     │  │
│ #rag(31) │  │  点击节点→侧栏详情卡     │  │
│ 图谱      │  └────────────────────────┘  │
└──────────┴──────────────────────────────┘
```

## 17. Mobile wireframe(390px)
```text
┌──────────────────────┐
│ #ai #rag #翻译       │
│ ▢ 带此标签的条目…    │
│ [首页 订阅 搜索 收藏] │
└──────────────────────┘
```

## 18. States
tags:empty/loading/success;graph:loading(布局动画, reduced-motion 静止)/
truncated(提示已按连接数截断)/empty;error(重建按钮)。

## 19. Accessibility
图谱不作为唯一信息入口(纯图形不 a11y, 必须有标签列表等价路径);
canvas 有文字说明;节点点击有键盘等价(列表点击同一详情)。

## 20. Runnable PoC
`research/phase2-pocs/graph/poc_graph.mjs`(Cytoscape.js, vendored)。

## 21. PoC evidence(实跑)
```text
nodes=100   layout=37ms   interactionFPS=54  heap=10MB
nodes=500   layout=61ms   interactionFPS=53  heap=10MB
nodes=2000  layout=173ms  interactionFPS=43  heap=10MB
结论: canvas 渲染 2000 节点可交互(43fps); WebGL(Sigma) 留作万级升级路线
```

## 22. Testing
unit:标签唯一性/suggested→accept;integration:四类边派生正确;E2E:
打标→过滤→图谱→点开详情;perf:2000 节点响应 <500ms。

## 23. Migration
纯新增;现有 wikilink 数据由 06 号扫描产出。

## 24. Rollback
删表+隐藏视图即净。

## 25. Implementation Gates
```text
Gate 0: tags/item_tags 表+assign/list API
Gate 1: 卡片标签 UI(手动)+过滤
Gate 2: AI 建议(suggested 状态, 采纳动作)
Gate 3: 图谱只读视图(Cytoscape, 2000 截断)
Gate 4: a11y 等价路径打磨
```

## 26. Expected commits
```text
feat(tags): unified tag model with suggested tier
feat(graph): read-only relationship graph view (cytoscape)
```

## 27. Acceptance criteria
- [x] OSS(§6) [x] schema/API(§10/11) [x] 线框(§16/17) [x] 渲染 PoC(§21)
- [x] AI 建议默认不污染(§8/13) [x] a11y 等价(§19) [x] prompt(§28)

## 28. Standalone ZCode implementation prompt
```text
你在 LumiRSS 仓库(先读 AGENTS.md 与 docs/research/phase2/00-platform-architecture.md)。
实施"标签与图谱 v1"按 docs/research/phase2/11-tags-graph.md §10/§11/§25。
硬约束:标签三来源(manual/source/ai), AI 建议落库必须为 status='suggested'
且默认不进任何过滤结果, 采纳是显式动作;图谱纯派生只读(无独立图存储),
节点上限 2000 按度数截断并告知;渲染用 Cytoscape.js(MIT);图谱必须提供
非图形等价信息路径;SQL inline literal+绑定参数。Non-goals:React Flow、
图算法产品、自动打标。每 Gate 跑受影响测试,完成跑全量回归。
```
