# 03 API 来源(API Sources)

> 状态:READY FOR IMPLEMENTATION(PoC 已实跑:3 个真实公开 API 经 JMESPath
> 映射为统一 item;首选路线=转换成 RSS/Atom 交给 FreshRSS 主链)
> 公共内容见 [00-platform](00-platform-architecture.md)。

## 1. Executive decision
**RECOMMENDED** — v1 = "JSON API →(JMESPath 映射)→ RSSHub 风格的 Lumi 本地
Atom feed → FreshRSS 订阅"。即:**优先保持 FreshRSS 主链**,connector 只做
转换器;Lumi Library 直存路线仅作为 FreshRSS 不可用时的 fallback(暂不建)。

## 2. Problem
许多信息源只提供 JSON API(GitHub releases、状态页、公开数据接口)。
用户希望它们与 RSS 同等出现在时间线/搜索/未读体系里,而不是再造一套
"API item 阅读器"。

## 3. Current LumiRSS gap
- RSSHub 已在栈内(可写自定义 route),但写 route=改 Node 代码,普通部署
  升级困难。
- BFF 无通用抓取→转换→feed 服务;`http_fetch.py` 与 feed 生成尚缺。

## 4. User stories
- 普通:填 API URL+JMESPath 表达式 → 预览 5 条 → 保存 → 得到本地 Atom
  URL → 一键加入 FreshRSS。
- 移动:同 RSS 流程(订阅中心发现/预览页已有形态)。
- 失败:表达式错误/超时 → 保留上次成功快照,标记 fetch_error(FreshRSS
  原生行为)。
- offline:条目已在 FreshRSS,无额外客户端逻辑。

## 5. Non-goals
v1 不做:POST/GraphQL、任意 JS/Python 脚本转换、OAuth 类鉴权 API、写操作、
调度器(BFF 不做 cron;抓取由 FreshRSS 订阅刷新自然触发)。

## 6. OSS research(≥3)

| 项目 | 事实能力 | 架构 | 活跃 | License | 复用 | 不复用 |
|---|---|---|---|---|---|---|
| RSSHub | 万物皆可 RSS(route 生态) | Node 服务(已在栈内) | 活跃 | MIT | 主链思路:转成 RSS 交 FreshRSS | 不为单用户写 route |
| RSS-Bridge | 网页→RSS bridge 集合 | PHP 服务 | 活跃 | AGPL-3.0 | — | PHP 栈 |
| Huginn | 通用 agent 管线(含 website→RSS) | Rails agent 服务 | 活跃 | MIT | 概念参考 | 过重 |
| JMESPath | JSON 声明式查询语言 | 库(py/js 多实现) | 活跃 | Apache-2.0 | **映射语言本体** | — |
| jsonpath-ng | JSONPath 实现 | 库 | 活跃 | MIT | 备选 | 表达力弱于 JMESPath 函数 |

## 7. Build vs reuse
**复用 JMESPath 库**(声明式、无执行面、多语言);connector/feed 生成 Lumi
自建(极薄:fetch→jmespath→atom xml)。不自造 `items[*].x` DSL(任务红线)。

## 8. Proposed architecture

```text
设置 UI(API 来源)
  │ POST /api/v1/api-sources {name, endpoint, items_expr, field_exprs…}
  ▼
BFF connector(Lumi Library 域内注册表)
  ├─ 预览: http_fetch(endpoint) → jmespath.search(items_expr)
  ├─ 保存 → 生成/维护 http://bff/api/feeds/<source-uuid>.atom
  │        ( FreshRSS 视角:这就是一个普通 Atom 订阅 )
  └─ FreshRSS 每次刷新拉取该 Atom → 常规 entry 入库/未读/搜索全链路
```

## 9. Data ownership
转换后的 entries 真源=FreshRSS;api_sources 配置=Lumi(设置域)。
Atom 端点是派生物(rebuildable)。

## 10. Data model(草案)
```sql
CREATE TABLE api_sources (
  uuid TEXT PRIMARY KEY, name TEXT NOT NULL,
  endpoint TEXT NOT NULL,             -- https only
  items_expr TEXT NOT NULL,           -- JMESPath: items 数组
  field_map TEXT NOT NULL,            -- JSON: {id,title,url,published,body} → JMESPath
  etag TEXT, last_status TEXT, created_at TEXT NOT NULL
);
```

## 11. API contract(草案)
```text
POST   /api/v1/api-sources         {…} → {uuid, preview_url}
POST   /api/v1/api-sources/preview {endpoint, items_expr, field_map} → {items[≤5]}(不保存)
GET    /api/v1/api-sources → list
PUT    /api/v1/api-sources/{uuid} / DELETE → 204
GET    /api/feeds/{uuid}.atom → Atom(仅内网/FreshRSS 可拉; 带 etag)
errors: invalid_expression / fetch_failed / schema_mismatch
```

## 12. Sync/lifecycle
FreshRSS 刷新(现有 cron)→拉 Atom→BFF 即时执行 fetch+转换(带 etag 缓存);
源变更=重新生成 Atom;删除=unsubscribe+删配置。

## 13. Security
SSRF 基线(endpoint https-only,私网拒绝——注意 FreshRSS 容器访问 BFF 的
内网地址属于服务器内部路由,放行条件显式写死);JMESPath 无执行面;Atom
正文走 RSS 域净化管线;表达式长度/复杂度上限(防 ReDoS 类资源占用)。

## 14. Resource budget(1.6GB)
零新进程;fetch 在 FreshRSS 刷新时被触发,内存增量 = 单响应 JSON
(默认上限 2MB)。实测 PoC 3 API 映射耗时合计 <1s。

## 15. UI information architecture
设置中心 →"来源"新增"API 来源"分区;预览页复用 RSSHub 发现的预览组件。

## 16. Desktop wireframe
```text
┌────────────────────────────────┐
│ API 来源                [+ 新增]│
│ ▢ FastAPI releases · 正常 · 5m │
│ ▢ HN front page · 错误(上次快照)│
├────────────────────────────────┤
│ [endpoint____________]         │
│ [items 表达式_________] [预览]  │
└────────────────────────────────┘
```

## 17. Mobile wireframe(390px)
```text
┌──────────────────────┐
│ API 来源        [+]  │
│ ▢ FastAPI · 正常     │
│ [首页 订阅 搜索 收藏] │
└──────────────────────┘
```

## 18. States
empty/loading/success(预览 5 条)/error(表达式错=字段级提示;fetch 错=保留
快照)/offline(n/a 服务器侧)/permission(n/a)。

## 19. Accessibility
表达式输入 label+帮助文本;预览表语义 table;错误 alert。

## 20. Runnable PoC
`research/phase2-pocs/api-sources/poc_api_sources.py`。

## 21. PoC evidence(实跑)
```text
== GitHub releases (FastAPI)  HTTP 200, 5 items
   2026-07-28  0.140.13 → https://github.com/fastapi/fastapi/releases/tag/0.140.13
== Hacker News (Algolia search_by_date)  HTTP 200, 5 items
   2026-09-10  Show HN: Talleyrand … → https://talleyrand.app/
== Open Library search(嵌套 docs[].{…join()})  HTTP 200, 3 items
   2019  Hands-On Machine Learning … → /works/OL20709638W
JMESPath mapping of 3 public APIs OK
```

## 22. Testing
unit:表达式求值/字段缺失容错;integration:connector→Atom→FreshRSS
mock 拉取;security:私网 endpoint 拒绝;E2E:新增源→订阅→时间线出现。

## 23. Migration
纯新增;Atom 路由挂在现有 /api 反代规则外的新路径(FreshRSS 容器可达)。

## 24. Rollback
删配置+ unsubscribe 即净;FreshRSS 无残留。

## 25. Implementation Gates
```text
Gate 0: api_sources 表+Atom 生成器(纯函数, 先无 UI)
Gate 1: preview 端点(fetch+jmespath) + 校验错误分型
Gate 2: 设置 UI(新增/预览/删除)
Gate 3: 订阅打通(自动 quickadd 到 FreshRSS)+ E2E
```

## 26. Expected commits
```text
feat(api-sources): JMESPath connector and atom feed generation
feat(api-sources): settings UI with live preview
feat(api-sources): auto-subscribe into FreshRSS
```

## 27. Acceptance criteria
- [x] OSS/license(§6) [x] 架构/schema/API(§8/10/11) [x] 线框(§16/17)
- [x] 安全(§13) [x] 预算(§14) [x] PoC 证据(§21) [x] Gates(§25) [x] prompt(§28)

## 28. Standalone ZCode implementation prompt
```text
你在 LumiRSS 仓库(先读 AGENTS.md 与 docs/research/phase2/00-platform-architecture.md)。
实施"API 来源 v1":按 docs/research/phase2/03-api-sources.md §10/§11/§25。
硬约束:映射语言只用 JMESPath(python jmespath 库),禁止发明 DSL 或 eval 类
执行;endpoint 仅 https 且走 http_fetch SSRF 防护;产出 Atom feed 由 FreshRSS
拉取(不自建调度器);feed XML 生成用标准库或声明的模板,不引入重型依赖;
SQL inline literal+绑定参数。Non-goals:POST/GraphQL/脚本转换/写 API。
每 Gate 跑受影响测试,完成跑全量回归。
```
