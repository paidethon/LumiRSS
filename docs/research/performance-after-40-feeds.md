# 40-Feed 扩容后的真实性能基准

> 日期:2026-09-10/11 · 数据集:46 订阅 / 4,287 条目(6 原有 + 40 新增真实 AI 源)
> 环境:WSL2 dev host(20 核 / 7.6GB,docker-compose dev 栈)。生产 1.6GB 对照
> 结论:低内存预设(LUMIRSS_BFF_MEM_LIMIT=512m 等)覆盖全部实测峰值。
> 工具:`research/phase2-pocs/feeds/`、`apps/web/browser-heap-bench.mjs`

## 1. 数据集

| 指标 | 值 |
|---|---|
| 订阅数 | 46(40 个为直连 RSS/Atom) |
| 总条目 | 4,287(从 63) |
| 最大单源 | OpenAI News 1,186 / Hugging Face 861 |
| 周增量主力 | arXiv cs.AI/CL/LG ≈ 650 条/周 |

## 2. 服务端内存(idle)

| 容器 | idle RSS | 生产上限(low-memory preset) |
|---|---|---|
| freshrss | 84 MB | 512 MB(预设 320) |
| rsshub | 154–194 MB | 448 MB(预设 192 reservation) |
| bff(host 进程,等价) | ~150 MB(uvicorn) | 512 MB(预设 256) |

## 3. 全量刷新基准(45 源并发关、FreshRSS 串行)

| 指标 | 值 |
|---|---|
| 刷新时长 | **90.0 s / 45 源**(≈2 s/源,上游网络延迟主导) |
| FreshRSS RSS | idle 80 → **peak 126 MB**,结束 101 MB |
| RSSHub RSS | 全程 194 MB(直连源刷新不经过 RSSHub) |
| 新条目(重复跑) | 2(15 分钟内二次刷新;首次导入承载 ~4,200 条) |

生产影响评估:1.6GB 主机上每小时一次 90s 串行刷新,CPU 1.0 核上限内;
内存峰值 126MB 距 FreshRSS 容器限额余量 4 倍。**瓶颈是上游站点响应时间,
不是内存或 CPU**——无代码修改依据。

## 4. 搜索管线(4,287 条)

| 指标 | 值 |
|---|---|
| 全量重建 | 15.6 s(86 页上游分页;`POST /api/v1/search/rebuild`) |
| 增量同步(无变化) | **153 ms**(扫 1 页 50 条,状态比对后提前停止) |
| 增量同步设计 | newest-first 游标;`published_at/read/starred` 状态一致即停页;
  未变更条目不重取正文、不重写投影(见 `search_index.py:133-181`) |
| 索引大小 | lumi.sqlite 共 9.1 MB(search_entries 4,287 行) |

### 4.1 查询延迟(8 词 × 15 轮)

| query | p50 | p95 | max |
|---|---|---|---|
| AI | 7.1ms | 9.1ms | 11.4ms |
| LLM | 6.1ms | 6.4ms | 6.6ms |
| agent | 6.7ms | 7.1ms | 7.1ms |
| inference | 6.3ms | 6.6ms | 6.8ms |
| reasoning | 6.5ms | 6.8ms | 6.9ms |
| RAG | 7.1ms | 7.9ms | 11.0ms |
| vision | 5.4ms | 5.9ms | 5.9ms |
| robotics | 10.5ms | 11.3ms | 12.0ms |

### 4.2 查询计划审计(EXPLAIN QUERY PLAN)

- 搜索主查询:`SCAN s USING INDEX idx_search_entries_published` —— LIKE
  `%term%` 无法用索引,优化器走 published 索引顺序扫描同时满足 ORDER BY,
  LIMIT 提前退出。这是前缀通配 LIKE 下的最优形状;**不需要新索引**。
- `known_states()` 全表投影扫描(O(n)/同步页):4.3k 行时 ~1ms,单用户量级
  下不构成瓶颈;若未来 >10 万条目可改为 keyset 比对,当前不改(无证据)。
- category 过滤走 `sqlite_autoindex_search_feeds_1`,无 N+1。

### 4.3 增量同步审计结论(任务 3.4)

已是增量:有 `last_synced_at` 门控(60s)、最新优先提前停止、逐条状态比对
(不重复生成 plain text —— 正文提取只发生在变更条目的上游重取时)、无 N+1
FreshRSS 请求(分页批量)。**无需修改。**

## 5. API Payload

| 端点 | 大小 | 备注 |
|---|---|---|
| GET /entries?limit=25 | 6,757 B | 8 个轻字段;**无 contentHtml/translation/AI 输出** |
| GET /search?q=LLM&limit=20 | 11,485 B | 含 snippet(必要) |
| GET /entries/{ref} | 55,143 B | contentHtml + contentText(阅读/翻译分段需要) |

## 6. 浏览器(Chromium CDP,真实 46-feed 数据)

| 阶段 | JS heap | DOM 节点 | listeners |
|---|---|---|---|
| 首屏加载(20 条) | 3.8 MB | 1,161 | 343 |
| 深滚动 → 分页至 320 条 | 11.9 MB | 13,662 | 2,735 |
| 5 次搜索后 | 20.8 MB | 15,085 | 3,248 |
| settle + GC | **4.6 MB** | 460 | 191 |

- 峰值远低于移动端预算;GC 后完全回落基线,**无泄漏特征**(与 PR #40 soak
  harness 的 mock 结论一致,本次为真实数据复现)。
- 320 条 ≈ 13.7k DOM(≈42 节点/条):`maxPages` 有界缓存已防无限增长;
  该规模下 **content-visibility/虚拟化均不需要**(任务 3.9 顺序要求满足)。
- 文章开合阶段的内存由 `scripts/soak-memory.mjs`(M0–M6,100 次开合,0 漂移)
  覆盖;本轮真实数据开合因自动化选择器未命中未重测,已如实标注。

## 7. 结论与修改清单

**零代码性能修改。** 全部实测均在生产资源预算内,瓶颈为上游网络延迟;
搜索已是增量实现;查询计划最优;payload 无冗余;浏览器无泄漏。任何
"预防性"索引/虚拟化/守护进程都缺乏证据,按复用政策不加。
