# 13 Phase 2 实施路线图(Dependency Graph & Milestones)

> 结论先行:**第一个开工的正式 milestone = M1 书签+工作区基座**;
> 第二个 = M2 剪藏+快照;翻译加固是随时可插的独立小 milestone(G0)。

## 1. Dependency graph(经本轮研究修正后的版本)

```text
00 平台基座(ItemRef / library domain / Source Registry)
        │
        ├── 05 书签 ──────────┐
        ├── 01 网页剪藏 ──────┤
        ├── 03 API 来源 ──────┼──► 07 工作区(read-later 预置)
        ├── 04 邮件简报 ──────┘        │
        ├── 06 Obsidian ──────┐        │
        │                     ▼        ▼
        │               08 统一视图(FTS 双腿 + 联邦收藏)
        │                     │
        │                     ▼
        │               09 RAG 索引(依赖 08 的 library 投影)
        │                     │
        │                     ▼
        │               10 Agent 工作台(工具=搜索/RAG/工作区)
        │                     │
        └── 02 网页快照(独立, 依赖 00 的 assets 策略)
              11 标签/图谱(依赖 05/06/07 的关系数据, 但一期可并行)
```

关键修正(vs 任务初始假设):Agent 只依赖"搜索+RAG+工作区"三个后端,
**不依赖标签/图谱**;图谱可以从关系表随时派生,放在最后不阻塞任何东西。

## 2. Milestones(每个独立可测可回滚, 禁 mega-milestone)

| Milestone | 内容 | 前置 | 规模预估 |
|---|---|---|---|
| **G0 翻译加固** | local-translation.md 的 G1-G4(源语言检测/组件指引文案/下载进度/重试点击) | 无 | 半天级 |
| **M1 基座+书签+工作区** | 00 基座表族、05 书签、07 工作区、12 UnifiedContentCard | 无 | 1-2 天级 |
| **M2 剪藏+快照** | 01+02(含 assets 配额) | M1 | 1-2 天级 |
| **M3 API 来源+邮件 outbound** | 03 全量、04 的 Gate 0-3 | M1 | 1 天级 |
| **M4 Obsidian+统一视图** | 06、08 | M1 | 1-2 天级 |
| **M5 RAG+Agent** | 09、10 | M4 | 2 天级 |
| **M6 标签图谱+邮件 inbound** | 11、04 Gate 4 | M5(标签);inbound 独立 | 1 天级 |

## 3. 每 milestone 的硬性出口(不可协商)
- 全量回归绿(BFF pytest+ruff、Web vitest+lint+typecheck+build、drift checks)
- 该报告 §27 验收表全勾
- 不 push main、不自动 merge(仓库既定规则)

## 4. 明确延后项(本轮结论, 不属于任何 milestone)
- Bergamot WASM 本地翻译(中文模型缺失, 引擎归档)— 重启条件见 local-translation.md
- 浏览器扩展剪藏入口(Share Target 先行)
- WebDAV vault、canvas 渲染、协作/分享、多用户任何形态
- 向量模型升级 bge-m3(需内存预算审批后另行评估)

## 5. 复用总审计(横向复核结论, PHASE 22 收敛)

| 问题域 | 复用什么 | License | 自建边界 | 决策 |
|---|---|---|---|---|
| 正文提取 | Defuddle / @mozilla/readability | MIT / Apache-2.0 | 净化+入库 | 复用 |
| HTML→MD | Turndown | MIT | — | 复用 |
| 页面归档 | Monolith(CLI 外部工具) | CC0 | 存储/配额/去重 | 复用 |
| JSON 查询 | JMESPath | Apache-2.0 | connector 薄层 | 复用 |
| mail→feed | 模式复用 KtN!;aiosmtpd 仅测试 | MIT/Apache | bridge 薄层 | 复用模式 |
| 书签导入 | Netscape 格式自解析(事实标准) | — | <100 行 | 自建 |
| Markdown 解析 | mistune / markdown-it | MIT | — | 复用 |
| 向量索引 | sqlite-vec | MIT | 单模块封装隔离 pre-v1 | 复用 |
| Embedding | fastembed(bge 系列) | MIT/模型各自 | 模型 sha256 锁定 | 复用 |
| 聊天 UI | assistant-ui(或 5 组件自写) | MIT | 与 Base UI 策略核验 | 复用优先 |
| 图渲染 | Cytoscape.js | MIT | 只读视图 | 复用 |
| 本地翻译 | Chrome 内置 API(平台能力) | — | 适配层已存在 | 直用 |
| LibreTranslate | 不新增(与 Argos=CT2 同底座却多 1GB+ 常驻) | AGPL | 存量 adapter 保留 | 不推广 |

许可证红线:全部候选为 MIT/Apache-2.0/CC0(AGPL 项目仅"模式参考",未复制
代码);引入任何依赖时更新 THIRD_PARTY_NOTICES.md。

## 6. Standalone prompt(路线图本身)
无需独立 prompt:各 milestone 直接使用对应报告 §28 的 prompt。
