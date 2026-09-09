# LumiRSS Architecture

> 本文回答"系统现在如何实现"（HOW），只描述当前状态；历史与决策过程见
> [../decisions/](../decisions/)（ADR）与 [../history/milestones.md](../history/milestones.md)。
> 产品范围与动机见 [../product/PRD.md](../product/PRD.md)。

## Principles

1. **Mature engines behind a Lumi-owned boundary.** FreshRSS 和 RSSHub 承担它们擅长的职责；Lumi 提供唯一日常产品界面。
2. **FreshRSS owns the RSS domain.** feeds / categories / entries / read / starred / subscriptions / OPML 只以 FreshRSS 为真源；Lumi SQLite 永不影子复制 RSS 数据（唯一例外是派生、可重建的搜索投影，见 [search.md](search.md)）。
3. **The browser talks only to the Lumi BFF**（`/api/v1/*` 相对路径），不直连 FreshRSS、RSSHub 或 AI Provider，不持有上游凭据。
4. **Two-plane split.** 读取数据面与来源/服务控制面分离；控制面不改变读取路径。
5. **AI is optional and non-blocking.** AI 未配置或失败不影响阅读、状态写入与来源管理；GET 类 AI 端点绝不触发 Provider 调用。
6. **Untrusted content is sanitized as the final boundary.** 文章 HTML 经受控 transform 后必须通过 DOMPurify 才能进入 React。
7. **Honest state.** read/star 写入用 set 语义；分页 cursor 与 `entryRef` 均为 opaque；打开文章不自动标为已读；所有网络状态都有 loading/empty/error UI。

## Data flow

```text
Native RSS / Atom ────────────────┐
Non-RSS → RSSHub-generated feed ──┤
                                  ▼
                               FreshRSS          ← RSS 域唯一真源
                                  ▼
                     FreshRSSAdapter / ControlAdapter
                                  ▼
                             FastAPI BFF  ──  Lumi SQLite（AI/设置/搜索投影）
                                  ▼
                         React Web / PWA
```

浏览器只信任 Lumi 契约，不感知上游实现细节。

## Data ownership

| 数据 | 权威位置 |
| --- | --- |
| RSS feeds / categories / entries、read / starred、订阅 / 分类 / OPML | FreshRSS（订阅经 `FreshRSSControlAdapter` 管理） |
| RSSHub 路由目录（Lumi 精选元数据） | BFF 静态 `CATALOG`（pinned 实例逐一验证） |
| RSSHub 期望/已应用配置、AI 非机密设置与 purpose 映射、AI 结果、便携设置（`app.settings`）、备份账本、schema 版本 | Lumi SQLite |
| RSSHub 实例地址 | `RSSHUB_BASE_URL` / `RSSHUB_FRESHRSS_BASE_URL` |
| 设备本地设置（布局宽度、自定义字体、过滤规则、稍后读） | 浏览器 localStorage / IndexedDB，不上传 |
| AI API keys、WebDAV 密码、RSSHub 机密 | `data/secrets.json`（0600；刻意置于 DB 与备份之外） |

## Read path

FreshRSS 抓取并规范化 RSS 域数据；RSSHub 只在上游生成 feed（宕机时已抓取内容照常可读）。`FreshRSSAdapter`（Google Reader 读路径）：ClientLogin 认证、feed / entry 列表（过滤在 FreshRSS 侧执行）、entry 详情（HTML → 纯文本）、`edit-tag` 写 read/star（set 语义）。BFF 把上游协议映射为稳定 Lumi DTO；Web 只经 BFF 读写。

## Source / service control plane

- `FreshRSSControlAdapter`：subscribe / unsubscribe / 分类移动与重命名 / OPML 导入导出；复用读路径的同一个 `FreshRSSSession`，不向浏览器暴露原始凭据。
- RSSHub 控制链固定为 Browser → Lumi BFF → RSSHub；正常文章读取路径绝不绕过 FreshRSS 去"读 RSSHub"。路由目录是 Lumi 自有静态精选 `CATALOG`；预览返回的 `feedUrl` 使用 `RSSHUB_FRESHRSS_BASE_URL`（FreshRSS 抓取视角）。
- 实例配置为 schema 驱动的类型化 allow-list：非机密键存 `lumi_settings`（desired/applied 两态），机密走 `SecretsStore`（write-only）；保存不等于生效——`restartRequired = desired ≠ applied`，operator 导出 `rsshub.env` 片段重启 RSSHub 后调 `POST /api/v1/rsshub/config/apply` 确认；Lumi 不自行重启 RSSHub，绝不暴露任意 shell / Docker 控制。

## AI path

- `AIProvider` protocol，唯一实现 `OpenAICompatibleProvider`（`chat/completions`，超时 connect 5s / read 60s，temperature 0.3；无自动重试、fallback 链、streaming）。Profile = 不同 base_url + model + key 组合；purpose（摘要 / 翻译 / AI 对话）映射到具体 profile 或 default。
- key 解析：映射的 profile 无自有 secret → `ai_not_configured`（不回退 default/env key）；default 依次回浏览器设置的 key → env `AI_API_KEY` → missing。`SecretsStore`（`data/secrets.json`，0600）write-only，永不可回读、不入备份。
- 结果缓存于 Lumi SQLite，缓存身份 = `entryRef + contentHash + provider + model + promptVersion + language`；prompt 版本 `summary-v1` / `translation-v1` / `chat-v1`，系统提示词含 prompt-injection 边界。
- `GET .../summary` / `GET .../translation` 只读缓存，`POST` 才显式生成；失败以稳定错误码返回，上游响应体不外泄。三个能力内嵌 Reader（摘要卡片 / 原文译文切换 / 文章对话）。

## Search path

全局搜索运行在**派生的、100% 可重建的 SQLite 投影**上（FreshRSS greader
API 不提供搜索）；投影只服务于搜索，删除不丢失任何 RSS 状态。详见
[search.md](search.md)。

## Reader content pipeline

```text
raw RSS HTML → inert DOM → controlled transforms（OpenCC 简繁、bionic、
Shiki 高亮）→ DOMPurify.sanitize（最终安全边界）→ ArticleContent
（全应用唯一 dangerouslySetInnerHTML 注入点）
```

外部链接经 `safeExternalHttpUrl` 校验（仅绝对 http/https），渲染为
`target="_blank" rel="noopener noreferrer"`。视觉/交互规则见
[../design/design-system.md](../design/design-system.md)。

## Frontend state

- **TanStack Query** 承载全部 server state；mutation server-confirmed 后
  invalidate，不做 optimistic update。
- **Zustand** 承载轻量 UI 状态（`useAppSettings`、`useReaderUi`、
  read-later）。便携键经 settings-sync（600ms debounce）PATCH 到
  `/api/v1/settings`；服务端严格校验，未知键/越界/NaN 一律拒绝。

## Security and trust boundaries

- 内容：RSS/网站 HTML 视为不可信，DOMPurify 是最终边界。
- 凭据：上游凭据只在服务端 env；AI/WebDAV/RSSHub 机密只在 `secrets.json`（0600）；所有机密接口 write-only，不回显、不入日志/Git/备份。
- 控制面：BFF 无 Docker socket；恢复需 preview + 显式输入 `RESTORE`，执行前自动安全备份；备份归档有成员数/总量/单文件上限。
- 网络：WebDAV http 仅允许回环/私网、重定向限同源；来源发现/预览有 scheme/host 校验、有界 body/超时；OPML 导入上限 2 MiB。
- 边缘：Caddy 安全响应头（nosniff / DENY / no-referrer / HSTS / Permissions-Policy / CSP，内联脚本 sha256 pin）；可选 basic auth（两个 auth 变量同设或同不设）；可选 BFF internal token（`X-Lumi-Token`）；BFF 全局请求体 4 MiB 上限与控制面路由限流（429 + `Retry-After`）。
- 多设备设置冲突：PATCH 可带 `baseRevision`，不一致返回 409 `app_settings_conflict`（Web 自动 re-hydrate 重试一次）。

## Deployment topology

```text
Internet / private access
          ▼
   web (Caddy, 80/443)      ← 唯一发布端口的服务（GHCR 预构建镜像）
   ├── /            → SPA 静态（try_files → index.html）
   └── /api/*       → bff:8000（lumi-data 卷；freshrss-data 只读卷）
                      ├─ FreshRSS（内网，healthcheck 门控 BFF 启动）
                      ├─ RSSHub（内网，非启动阻塞项）
                      └─ AI Provider（出站 HTTPS）
```

镜像 tag、端口隔离、构建溯源（`LUMIRSS_BUILD_COMMIT`）见
[../reference/configuration.md](../reference/configuration.md)；操作手册
（deploy/update/rollback）见 [../how-to/deploy.md](../how-to/deploy.md)。

## Failure isolation and observability

- RSSHub 不可用只影响来源发现/预览，不影响阅读；FreshRSS 故障以类型化"依赖不可用"呈现，不是空白页；
- AI 未配置/失败永不阻塞阅读、状态写入与来源管理；
- `/health/ready` 只由核心依赖（lumi.sqlite）决定；FreshRSS/RSSHub 只报告、永不导致 not ready；
- 备份/恢复单并发、阶段真实上报；无无界后台重试循环；日志脱敏；`/api/v1/operations/status` 提供各依赖真实探测。

## Deferred（不得描述为已存在）

- Phase-2 统一来源层：web clipping、JSON/API connector、邮件、Obsidian connector、unified source registry、agent workspace；
- 多用户 / 多租户与公共互联网硬化；PWA 离线（Service Worker / 离线缓存 / Push / 后台同步未实现，manifest 已有）；
- AI：streaming、fallback 链、多供应商路由、向量检索。

## Related

- ADR：[../decisions/](../decisions/) — FreshRSS owns RSS state / Web 只与 BFF 通信 / 不建 RSS 影子库（均 Accepted）；Build vs Reuse 边界：[reuse-policy.md](reuse-policy.md)。
- API 家族清单以 `services/bff/src/lumirss/main.py` 与生成的 OpenAPI schema 为准（`/api/v1/integrations/*` 等 Phase-2 家族未实现）。
