# 09 RAG 索引(检索增强)

> 状态:READY FOR IMPLEMENTATION(真实向量 PoC 已实跑:1000 chunks、本地
> embedding、sqlite-vec 0-2ms、跨语言命中;条件项=embedding 模型选型在
> 实施时按 §17.5 复核)
> 公共内容见 [00-platform](00-platform-architecture.md)。

## 1. Executive decision
**RECOMMENDED(限界)** — RAG 只为语义检索/Agent 上下文/Q&A 服务,**不替代
普通搜索**。选型:**sqlite-vec(embedded, lazy, rebuildable)+ fastembed
ONNX 小模型**。不部署任何向量数据库服务。

## 2. Problem
FTS 只能词面匹配:"怎样在设备上翻译"搜不到写着"local translation on
device"的笔记。Agent 工作台(10 号)需要语义取材。

## 3. Current LumiRSS gap
只有 FTS(词面);无向量能力;SQLite 已是栈内核心(零新存储引擎的土壤)。

## 4. User stories
- 普通:搜索框开"语义"开关 → 结果包含措辞不同但语义相关的条目。
- 移动:同搜索页开关;服务端执行,端上零负担。
- 失败:模型缺失/索引损坏 → 自动降级 FTS 并提示重建。
- offline:n/a(服务器侧;本地方案仍在本机)。

## 5. Non-goals
不做:多用户、图数据库、常驻向量服务、实时索引(异步 rebuild)、自动
"全库问答"产品化(v1 只做检索层)。

## 6. OSS research(≥3)

| 项目 | 事实能力 | 架构 | 活跃 | License | 复用 | 不复用 |
|---|---|---|---|---|---|---|
| sqlite-vec | SQLite 向量扩展(vec0 虚表) | C 扩展 | 活跃(**pre-v1, API 可能变**) | MIT | **本体** | 接受 pre-v1 风险并封装隔离 |
| LanceDB | 嵌入式向量库(列式) | Rust 库 | 活跃 | Apache-2.0 | 备选(若 vec0 弃疗) | 双存储栈 |
| Qdrant local mode | 进程内向量引擎 | Rust/嵌入 | 活跃 | Apache-2.0 | — | 偏服务形态 |
| FAISS | 向量索引库 | C++/python | 活跃 | MIT | — | 无持久化故事 |
| Chroma | 向量 DB(含 server) | python | 活跃 | Apache-2.0 | — | server 心智 |
| fastembed | ONNX 轻量 embedding(无 torch) | 库 | 活跃 | MIT | **embedding 本体** | — |

## 7. Build vs reuse
**复用 sqlite-vec + fastembed**;chunking 借鉴 LangChain 语义分块思想但
自写极简规则(标题继承+段落边界,见 §8);混合排序 RRF 自写(20 行)。

## 8. Proposed architecture

```text
写路径(RSS/clip/note 各自 upsert 后投递)
  → chunker: 结构化切分(标题继承; 段落 300-800 chars; 表格不切)
  → fastembed(bge-small-zh-v1.5, ONNX CPU, 512 维) → sqlite-vec vec0 表
  → rag_chunks(chunk_id, ref, ord, text, model_id)   [rebuildable]
查询: embed(q) → vec KNN(30) ⊕ FTS(30) → RRF → top-k(ref 反查原文)
索引生命周期: lazy(首次查询/手动触发); model_id 变更=全量 rebuild;
              rebuild 在后台 loop 低优先级执行
```

## 9. Data ownership
rag_chunks 与向量=派生(rebuildable),ref 指向 RSS/Library 真源;
模型缓存文件=可再下载资产。

## 10. Data model(草案)
```sql
CREATE VIRTUAL TABLE rag_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[512]);
CREATE TABLE rag_chunks (
  chunk_id INTEGER PRIMARY KEY,
  ref TEXT NOT NULL,                -- typed ItemRef
  ord INTEGER NOT NULL, model_id TEXT NOT NULL,
  text TEXT NOT NULL,
  UNIQUE (ref, ord, model_id)
);
```

## 11. API contract(草案)
```text
GET  /api/v1/rag/search?q=&k=8&filter_kind= → {items:[{ref, score, text}]}
POST /api/v1/rag/rebuild {scope: all|library|rss} → 202 {job}
GET  /api/v1/rag/status → {chunks, model, lastRebuild, partial}
errors: model_unavailable(降级提示) / rebuild_in_progress
```

## 12. Sync/lifecycle
写路径投递→增量 chunk/embed(变更 ref 重嵌);全量 rebuild=删投影重建
(内容真源无损);模型升级=model_id 新表分段迁移,旧模型只读。

## 13. Security
无新网络面(模型文件从 HF 下载需哈希锁定);查询串绑定参数;ref 校验同
00 基线;chunk 文本来自已净化内容。

## 14. Resource budget(1.6GB)
实测(本机):embed 模型加载后进程 ~260MB(**仅 rebuild/embed 时运行,可
退出**),281 chunks/s;vec 查询 0-2ms@1k chunks;1 万 chunks 索引≈40MB
磁盘。**常驻成本 0**(lazy load + 空闲卸载);rebuild 期间限核。

## 15. UI information architecture
搜索页"语义匹配"开关;设置中心 AI 区新增"RAG 索引"卡(状态/重建按钮)。

## 16. Desktop wireframe
```text
┌────────────────────────────────┐
│ [搜索______] [x]语义匹配 [重建] │
│ ▢ 结果 · 相关度 · 来源 ref      │
└────────────────────────────────┘
```

## 17. Mobile wireframe(390px)
```text
┌──────────────────────┐
│ [搜索____] [语义 ⊙]  │
│ ▢ 结果 · 来源        │
│ [首页 订阅 搜索 收藏] │
└──────────────────────┘
```

## 18. States
indexing(进度)/ready/no-index(引导重建)/model-missing(降级 FTS 提示)/
error(rebuild 失败重试)/offline(n/a)。

## 19. Accessibility
开关有文字标签;重建按钮 loading 态可中断(Esc);结果与现有列表同组件。

## 20. Runnable PoC
`research/phase2-pocs/rag/poc_rag.py`(bge-small-zh + sqlite-vec + RRF)。

## 21. PoC evidence(实跑)
```text
model ready in 6.9s; peakRSS=261MB (ONNX 加载后)
embedded 1000 chunks in 3.6s (281/s)
[en→semantic] 2ms  top=chunk0   'retrieval augmented generation…'
[zh→semantic] 0ms  top=chunk145 '本地机器翻译…'        ← 中文问题命中中文 chunk
[cross zh→en] 1ms  top=chunk581 'quantized inference…' ← 中文问题命中英文 chunk!
[cross en→zh] 1ms  top 命中弱(预期): bge-small-zh 对 en→zh 跨语言弱
hybrid RRF top-5: 全部命中 quantized inference 主题簇
索引: vec0 表 1000×512 float32 ≈ 2MB;  查询 0-2ms
结论: 选 bge-small-zh 时 zh↔en 查询可用, en→zh 跨语言弱 → 实施时评估
bge-m3(多语言) 若磁盘/内存预算允许(模型 ~1.1GB, 需超预算审批)
```

## 22. Testing
unit:chunker 规则/RRF;integration:写路径投影→检索;perf:万级 chunks
rebuild 时长/内存;降级矩阵;security:模型文件 sha256 锁定。

## 23. Migration
纯新增;依赖 sqlite-vec 扩展随 BFF 镜像分发(linux wheel)。

## 24. Rollback
删投影+隐藏开关即净;内容真源无损。

## 25. Implementation Gates
```text
Gate 0: rag_chunks+vec0 表+fastembed 依赖(镜像内验证 wheel)
Gate 1: rebuild job(限核)+status
Gate 2: /rag/search+RRF+降级
Gate 3: 搜索页开关 UI
Gate 4: 万级 chunks 性能与内存验证(预算复核)
```

## 26. Expected commits
```text
feat(rag): sqlite-vec projection with fastembed pipeline
feat(rag): semantic search endpoint with rrf hybrid and fts fallback
feat(rag): search ui semantic toggle + index management
```

## 27. Acceptance criteria
- [x] OSS/license(§6) [x] 架构/schema/API(§8/10/11) [x] 线框(§16/17)
- [x] 真实向量 PoC(§21) [x] 跨语言实测(§21) [x] pre-v1 风险处理(§6/§13)
- [x] Gates(§25) [x] prompt(§28)

## 28. Standalone ZCode implementation prompt
```text
你在 LumiRSS 仓库(先读 AGENTS.md 与 docs/research/phase2/00-platform-architecture.md)。
实施"RAG 索引 v1"按 docs/research/phase2/09-rag-index.md §10/§11/§25。硬约束:
sqlite-vec 为唯一向量栈(封装在一个模块内隔离 pre-v1 API 风险);embedding 用
fastembed ONNX(CPU), 模型文件 sha256 锁定;embedding 进程 lazy+空闲卸载,
常驻内存增量必须为 0;所有向量数据 rebuildable(ref 指向真源);查询失败自动
降级 FTS 并如实提示;SQL inline literal+绑定参数。Non-goals:向量服务、实时
索引、问答产品。每 Gate 跑受影响测试,完成跑全量回归。
```
