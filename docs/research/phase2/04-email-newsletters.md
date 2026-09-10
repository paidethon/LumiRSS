# 04 邮件简报(Email Newsletters)

> 状态:CONDITIONAL(inbound PoC 已实跑;生产接入需 SMTP 收信前置条件,
> 见 §14 与 §25 Gate 顺序——先 outbound,后 inbound)
> 公共内容见 [00-platform](00-platform-architecture.md)。

## 1. Executive decision
- **Inbound(newsletter→阅读器):CONDITIONAL RECOMMENDED** — 优先路线=
  "email→Atom→FreshRSS"(Kill the Newsletter! 模式),**不发明 newsletter
  backend**;1.6GB 服务器不做完整 MTA,前置条件=使用外部收信(转发服务或
  现有邮箱+IMAP 拉取)。
- **Outbound(digest 邮件):RECOMMENDED** — SMTP relay + 模板,完全低风险。

## 2. Problem
大量优质内容只以邮件 newsletter 发行;用户已在阅读器里组织阅读,不想再开
邮箱客户端。反向:用户想要"我的阅读摘要"邮件。这是两个独立问题。

## 3. Current LumiRSS gap
无任何邮件能力;无 inbox 域;settings 有邮件类配置位(未实现)。

## 4. User stories
- inbound 普通:把 `lumi-xxx@bridge` 地址填进 newsletter 订阅 → 5 分钟内
  该邮件成为一条未读文章。
- inbound 失败:非白名单发件人→丢弃(计数可见);HTML 邮件→净化后可读。
- outbound 普通:勾选"每日 08:00 digest"→ 收到 HTML+纯文本双版本。
- mobile:digest 内容与站内时间线一致;inbound 文章走同一阅读器。

## 5. Non-goals
不运行完整 MTA(不监听 25 端口、不做 MX/反垃圾/自动回执);不引入
listmonk/营销系统;不做双向回信;不支持附件全文(v1 只存附件名)。

## 6. OSS research(≥3)

| 项目 | 事实能力 | 架构 | 活跃 | License | 复用 | 不复用 |
|---|---|---|---|---|---|---|
| Kill the Newsletter! | email→公开 Atom feed | Node+SMTP+web | 活跃 | MIT | **email→Atom 模式本体** | 其公开托管模式 |
| Omnivore newsletter ingest | 专属地址→inbox→文章 | cloud+MTA | 归档 | AGPL-3.0 | 专属地址 UX | 其 MTA |
| FreshRSS 生态(mail2rss 脚本) | IMAP→RSS 多种实现 | 脚本 | 分散 | 各异 | IMAP 拉取模式 | 不逐个引入 |
| aiosmtpd | Python SMTP server(测试/边缘) | 库 | 活跃 | Apache-2.0 | PoC/测试夹具 | 不做生产 25 端口服务 |
| Mailpit | 本地 SMTP sink+web 查看 | Go 二进制 | 活跃 | MIT | outbound 测试工具 | — |

## 7. Build vs reuse
**Inbound 优先复用"邮件转发服务→HTTP webhook/IMAP 拉取"**,Lumi 只写
"解析→净化→Atom/feed 注入"薄层(自建,极小);Outbound 用标准库 smtplib+
模板(自建)。不自建 MTA、不引入营销系统。

## 8. Proposed architecture

```text
[Inbound A(默认, 零端口)]
 newsletter → 用户邮箱(IMAP 拉取 或 转发服务 webhook)
   → BFF inbound bridge: 解析(html→净化)→ 生成 per-list Atom
   → FreshRSS 订阅该 Atom(与 03 号同主链!)
[Inbound B(可选自建, 仅开发/隔离环境)]
 aiosmtpd 监听 127.0.0.1:1587(绝不公网)→ 同上
[Outbound]
 调度(BFF 内轻量 job, 复用现有后台 loop)→ 选文章 → 模板渲染(text+html)
 → SMTP relay(用户配置) → 用户邮箱; 本地测试 → Mailpit sink
```

## 9. Data ownership
Inbound A:entries 真源=FreshRSS;bridge 状态(seen message ids)=Lumi。
Outbound:digest 配置与发送历史=Lumi。

## 10. Data model(草案)
```sql
CREATE TABLE mail_bridge_lists (
  uuid TEXT PRIMARY KEY, name TEXT NOT NULL, feed_url TEXT NOT NULL,
  secret TEXT NOT NULL UNIQUE,           -- 专属地址 token
  created_at TEXT NOT NULL
);
CREATE TABLE mail_seen (
  message_id TEXT PRIMARY KEY, list_uuid TEXT REFERENCES mail_bridge_lists(uuid),
  seen_at TEXT NOT NULL
);
CREATE TABLE digest_settings (
  id INTEGER PRIMARY KEY CHECK (id=1), enabled INTEGER NOT NULL,
  hour INTEGER NOT NULL,smtp_host TEXT NOT NULL, smtp_port INTEGER NOT NULL,
  from_addr TEXT NOT NULL, last_sent_at TEXT
);
```

## 11. API contract(草案)
```text
POST /api/v1/mail/bridge-lists {name} → {uuid, address: lumi-<secret>@bridge}
GET  /api/v1/mail/bridge-lists / DELETE {uuid}
POST /internal/mail/ingest      (webhook: from/to/raw html) → 202;错误 4xx
PUT  /api/v1/digest/settings {enabled,hour,smtp…}; POST /api/v1/digest/send-now
errors: unknown_recipient / duplicate_message / smtp_unreachable
```

## 12. Sync/lifecycle
ingest→dedup(message_id)→净化→追加 Atom(保留 N=50 条);FreshRSS 正常刷
新;digest job 每小时整点检查 enabled+hour;失败重试仅手动。

## 13. Security
webhook 鉴权=地址内随机 secret(不可枚举)+来源 IP 可选白名单;HTML 邮件
=不可信输入,净化为 RSS 同级;**不发真实邮件做测试**(本地 sink);
SMTP 凭据入 secrets_store;拒绝=open-relay 风险(v1 根本不监听公网)。

## 14. Resource budget(1.6GB)
Inbound A:零端口零进程(复用用户既有邮箱);Inbound B 仅 dev。Outbound:
发送走用户 relay,增量≈0。无新常驻内存。**硬红线:1.6GB 生产不监听 25。**

## 15. UI information architecture
设置中心"邮件简报"分区(inbound 地址管理 + outbound digest);文章阅读复用
现有 Reader。

## 16. Desktop wireframe
```text
┌───────────────────────────────────┐
│ 收信地址                    [+ 新增]│
│ ▢ lumi-a1b2@bridge · TLDR · 正常   │
├───────────────────────────────────┤
│ 每日摘要  [开关] 08:00  [SMTP 配置] │
└───────────────────────────────────┘
```

## 17. Mobile wireframe(390px)
```text
┌──────────────────────┐
│ 收信地址        [+]  │
│ ▢ lumi-a1b2 · 正常  │
│ 每日摘要      [开]  │
│ [首页 订阅 搜索 收藏]│
└──────────────────────┘
```

## 18. States
inbound:empty/loading/success/error(重复/未知地址=静默计数);
outbound:未配置 SMTP=提示、发送失败=手动重试按钮;offline(n/a 服务器侧)。

## 19. Accessibility
地址可复制文本+复制按钮 label;表单 label;状态行 role=status。

## 20. Runnable PoC
`research/phase2-pocs/newsletters/poc_newsletters.py`(aiosmtpd 本地 SMTP→
解析→Atom;outbound digest→本地 sink,HTML+text 双版本)。

## 21. PoC evidence(实跑)
```text
SMTP received: 2 mails
Atom feed written (1059 bytes, entries=2, valid-shape=True)
outbound digest received by sink: subject='LumiRSS daily digest — 2 items' html+text=True
OK in 0.02s
(全程仅 127.0.0.1, 无真实邮件)
```

## 22. Testing
unit:邮件解析/去重/净化;integration:ingest→Atom→FreshRSS(mock 拉取);
digest 渲染快照(纯文本+HTML);E2E:添加地址→模拟 webhook→文章出现;
security:secret 枚举拒绝、HTML 净化矩阵。

## 23. Migration
纯新增;digest 复用 BFF 现有后台 loop(main.py search_sync_loop 同模式)。

## 24. Rollback
关 enabled/删路由即净;无外部状态残留(除用户自己邮箱里的信)。

## 25. Implementation Gates
```text
Gate 0: mail_bridge_lists/mail_seen 表+净化器(邮件 HTML 复用 RSS 净化)
Gate 1: ingest 端点(webhook 版, secret 鉴权)→ Atom 追加
Gate 2: digest outbound(设置+模板+send-now, 先只打 Mailpit/本地 sink)
Gate 3: UI(地址管理+digest 设置)
Gate 4: (可选)IMAP 拉取 adapter——仅在用户提供既有邮箱时实施
```

## 26. Expected commits
```text
feat(newsletters): mail bridge skeleton with html sanitization
feat(newsletters): webhook ingest to atom feed
feat(digest): outbound daily digest via user smtp relay
```

## 27. Acceptance criteria
- [x] OSS/license(§6) [x] 架构/schema/API(§8/10/11) [x] 线框(§16/17)
- [x] 安全(§13) [x] 预算(§14) [x] PoC 证据(§21) [x] Gates(§25) [x] prompt(§28)
- [ ] 生产 SMTP 前置条件(用户决策:转发服务 or IMAP)→ CONDITIONAL 项

## 28. Standalone ZCode implementation prompt
```text
你在 LumiRSS 仓库(先读 AGENTS.md 与 docs/research/phase2/00-platform-architecture.md)。
实施"邮件简报 v1"按 docs/research/phase2/04-email-newsletters.md §10/§11/§25,
顺序:先 digest outbound(Gate 0-3),再 inbound webhook(Gate 0-3);Gate 4 仅在
用户提供 IMTP/转发服务凭据后开始。硬约束:绝不在生产监听 25/465/587;邮件
HTML 必须过与 RSS 相同的净化边界;message_id 去重;SMTP 凭据进 secrets_store;
digest 默认关闭。Non-goals:MTA、附件全文、营销系统。每 Gate 跑受影响测试。
```
