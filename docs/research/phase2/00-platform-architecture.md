# Phase 2 平台总架构 — Library Domain 与共享基座

> 状态:RECOMMENDED(作为所有 Phase 2 特性报告的共同前提)
> 公共内容(Ownership 规则、ItemRef、Source Registry、安全基线、资源预算方法)
> 全部收敛在本篇;各特性报告只引用,不重复。

## 1. Executive decision

**RECOMMENDED** — Phase 2 引入统一的 **Library Domain**(Lumi SQLite 内的
新表族 + 新路由族),通过 **typed ItemRef** 与 RSS Domain 互引用,不复制
RSS 数据;FreshRSS 继续独占 RSS domain state。

## 2. 为什么需要统一基座

不先定基座直接做十个特性,必然出现:十个来源十套表、RSS 条目被复制到
Lumi 库、搜索/收藏/工作区各自造一遍"引用"概念。00 号报告的价值是把
"什么属于谁、用什么引用、如何失败"一次定死。

## 3. Current LumiRSS gap(审计)

- `services/bff/src/lumirss/` 已有:FreshRSSAdapter(唯一 RSS 后端)、
  search 投影(`search_entries`,entry_ref 全域唯一)、AI 段缓存
  (`ai_translation_segments`,按 entry_ref)、backup/restore。
- Lumi SQLite 只存派生数据与设置,无任何内容型 owner 表 —— Phase 2 的
  library_items 将是第一张"内容表",必须与 RSS 划清边界。
- Web 已有 Phase 2 占位导航(侧栏"网页剪藏/工作区/…"标 Phase 2)。

## 4. 核心模型

### 4.1 LibraryItem(内容物)

```text
LibraryItem = 一种 Lumi 拥有的内容对象
  kind: bookmark | clip | snapshot | api_item | newsletter_item | obsidian_note
```

- RSS Entry **不是** LibraryItem(留在 FreshRSS)。
- LibraryItem 是唯一允许携带正文的 Lumi 内容对象。

### 4.2 ItemRef(typed reference,全域统一)

```text
rss:<opaque-entry-ref>     # 指向 FreshRSS entry(现有 opaque_ref 机制)
library:<uuid>             # 指向 LibraryItem
```

- Workspace / Tag / RAG chunk / Agent thread / Favorite 一律只存 ref。
- ref 解析由 BFF 内聚:`resolve(ref) -> EntryView | LibraryItemView`,
  Web 永不拼接内部 id。
- 不复制对象;衍生文本(FTS/向量)允许投影,但必须带可重建标记
  (derived, rebuildable),见 09-rag。

### 4.3 Source Registry(来源注册,不统一后端)

| Source 类型 | 落点 | source of truth | 同步方向 |
|---|---|---|---|
| RSS | FreshRSS | FreshRSS | FreshRSS→投影(已存在) |
| RSSHub | RSSHub→FreshRSS | FreshRSS | 同上 |
| Web Clip | Lumi Library | Lumi | 无(写入即成) |
| API Source | Connector→Library item 流 | Lumi | 拉取→upsert |
| Newsletter | Email→Atom→FreshRSS | FreshRSS | 邮件→feed(优先);备选:直入 Library |
| Obsidian | Vault→Library 投影 | **用户的 Vault** | vault→index(单向只读) |

## 5. 数据 ownership 总图

```text
Native RSS/Atom ──► FreshRSS ◄── RSSHub
                       │ (唯一 RSS 真源: subscriptions/entries/read/star/OPML)
                 FreshRSSAdapter
                       │
                  FastAPI BFF ────────────────────────────┐
                       │                                  │
     ┌─────────────────┼──────────────────┐               │
     │ RSS domain 投影 (derived, rebuildable)             │ Library domain (owned)
     │  search_entries / ai_translation_segments          │  library_items(kind=…)
     └─────────────────┬──────────────────┘               │  library_favorites / workspace_items
                       │      ItemRef(rss:… | library:…)  │  tags / rag_chunks / agent_threads
                       ▼                                  ▼
                          assets 存储(快照/附件, 文件系统+配额)
                       React Web / PWA (只经 /api/v1/*)
```

## 6. 统一安全基线(所有特性报告的引用项)

1. **SSRF**:一切服务器侧 URL 抓取(clip、API source、webhook)走统一
   `http_fetch.py` 出口:HTTPS/HTTP 白名单判定、私网/环回/link-local 拒绝、
   重定向逐跳复检、超时+大小上限。
2. **XSS**:外部 HTML 一律 transforms→DOMPurify(现架构不变);译文/摘要
   只以 textContent 注入(0016 规则延续)。
3. **Secrets**:API source / WebDAV / SMTP 凭据走 secrets_store(现成),
   永不入日志。
4. **路径安全**:assets 存储 id 由服务器生成(uuid),文件名不得来自用户
   输入;vault 索引只读,绝不回写路径拼接。
5. **注入**:SQL 全部 inline literal + 绑定参数(仓库规范);FTS 查询串
   转义;JMESPath 表达式只读内存 JSON,无执行面。
6. **DoS**:抓取大小/次数上限、导出分页、Agent 工具白名单+频率上限。
7. **单用户前提**:无多租户;basic auth/会话为唯一边界(0018/0040 已定)。

## 7. 资源预算方法(1.6GB 生产机)

- 任何新常驻进程默认 **0**;新依赖先给 idle/peak RSS 实测(PoC 提供)。
- 已实测参考:CTranslate2 INT8 ~193MB(§local-translation)、fastembed
  bge-small-zh ~260MB(仅 rebuild 时)、monolith 单页 16-131MB(瞬时)。
- 存储:assets 目录配额默认 2GB,超限按 LRU+去重清理(02 号报告)。

## 8. 迁移与回滚(M2 基座本身的)

- 迁移:新增 library_* 表族与路由 = 纯增量;现有 RSS 读路径零改动。
- 回滚:删表族+路由即完全移除;Library domain 无数据反哺 RSS domain,
  回滚不丢任何 FreshRSS 状态。
