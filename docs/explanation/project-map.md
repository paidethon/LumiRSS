# 项目地图：如何读 LumiRSS

> 一页回答：先理解哪几个边界；从一次点击追到 API、服务、存储的方法；
> 图、源码、规范各能证明什么。细节背诵交给 IDE 搜索与测试。

## 先记住六个边界

| 部分 | 负责 | 不负责 |
|---|---|---|
| React Web | 展示、输入、导航、阅读反馈 | 保存业务事实、直连上游 |
| FastAPI BFF | 认证、业务规则、适配来源、组合结果、调用 AI | 重新实现 FreshRSS |
| FreshRSS | 订阅、条目、已读/收藏等 RSS 域事实 | 用户笔记、日报等 Lumi 自有内容 |
| Lumi SQLite | Lumi 自有内容、状态、引用、批准的可重建投影 | 复制整套 RSS 数据 |
| RSSHub | 非 RSS 来源 → 可消费 feed | 定义 UI 状态 |
| Caddy/Compose | 路由、进程与数据卷边界 | 业务语义 |

## 系统边界图

```text
            浏览器 / PWA
                │  只经 BFF (/api/v1/*)，Caddy 反代
                ▼
┌────────── LumiRSS BFF (FastAPI) ──────────┐
│  FreshRSSAdapter  RSSHub适配  邮件桥  AI   │
│  派生投影(search_entries)  Lumi SQLite    │
└───────┬──────────────┬───────────┬────────┘
        │ greader API  │ HTTP      │ OpenAI 兼容
        ▼              ▼           ▼
    FreshRSS        RSSHub      AI Provider
   （RSS 真源）   （来源生成器）  （外部付费）
        ▲
        │ 订阅 Lumi 生成的 Atom（/feeds/*，token）
        └──────────── 日报/邮件桥输出回流订阅 ────────
```

## 时序一：RSS 自动更新 → UI 可见

```text
FreshRSS 容器 cron（CRON_MIN 指定分钟）
  → actualize：向各上游 feed 发条件请求（ETag/304）
  → 新条目写入 FreshRSS 库
用户/BFF 侧（按需，不在采集路径上）：
  BFF FreshRSSAdapter.list_entries（greader API）
  → 后台同步刷新派生投影 search_entries（search_index）
  → 搜索/收件量统计等从投影读取
```

要点：自动采集的拥有者是 FreshRSS 容器 cron；BFF 没有第二套抓取器。
排查入口见 [how-to/troubleshoot.md](../how-to/troubleshoot.md)「RSS 永不
自动更新」。

## 时序二：GPT 日报 → Atom 订阅

```text
配置(gpt_digest_configs: hour/timezone/window/白名单)
  → 调度器每小时边界检查（重启幂等：last_issue_key）
  → 收割 search 投影文档（有上限）→ 窗口/白名单/去重/单源配额选材
  → 服务端分配 source id（s1..sN）→ AI 结构化生成
  → 严格校验（schema + 引用存在性；失败≠发布）
  → upsert 期刊（(config_id, issue_key) 唯一；同日=修订）
  → GET /feeds/gpt-digest/{token}.atom 只读输出（ETag/304；
     GET 永不触发生成、不产生费用）
```

## 数据归属

```text
控制库 lumi.sqlite：身份/会话/邀请/FreshRSS 池/审计（账户控制面）
每用户库 users/<uid>/lumi.sqlite：该账号全部业务数据（服务端身份路由）
FreshRSS：订阅/条目/已读/收藏（RSS 域唯一真源，每账号一个 FreshRSS 用户）
Obsidian Vault：只读投影，永不回写
secrets.json：API 密钥/SMTP/订阅 token（永不进 SQLite/日志/浏览器）
```

多账户分层细节：[explanation/architecture.md](architecture.md)
「控制库与每用户库」一节与 [ADR 0005](../decisions/0005-invite-multi-account.md)。

## 从一次点击追到存储（方法）

1. 组件事件 → `src/api/queries.ts` 找 useXxxMutation → `client.ts` 找
   HTTP 端点；
2. 端点 → `services/bff/src/lumirss/routers/<域>.py` → service/store
   → SQL（内联、绑定参数）或 adapter（FreshRSS 上游）；
3. 契约唯一来源：BFF Pydantic 模型 → `pnpm api:generate` 生成
   `apps/web/src/api/generated/schema.ts`。手改生成文件 = 违规。

## 图/源码/规范各能证明什么

- 本页示意图：解释**设计意图与边界**，不是运行时调用图；
- `search_entries` 等派生投影：可重建副本，不是原始资料；
- 静态 import 图：依赖关系证据，不能证明跨服务 HTTP 行为；
- 真实行为：以测试（BFF pytest / Web vitest / e2e）与运行日志为准；
- 架构不变量与 ADR：判定「对不对」，源码回答「是什么样」。
