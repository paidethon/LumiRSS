# LumiRSS 产品需求文档

> **版本**：v5.0 — Reboot Baseline
> **日期**：2026-08-24
> **状态**：MVP Scope Frozen
> **产品形态**：单用户、自托管、AI 增强型 RSS 阅读器

---

## 1. 产品是什么

LumiRSS 是一个面向个人用户的自托管 RSS 阅读器。

目标不是重新实现 RSS 基础设施，而是组合成熟开源组件，提供：

* 简洁现代的阅读体验；
* 良好的桌面和移动 Web 体验；
* 数据自主；
* 按需 AI 摘要与翻译；
* 简单、可维护的自托管部署。

核心使用闭环：

```text
打开 LumiRSS
→ 查看未读 / Feed / 分类
→ 浏览文章列表
→ 阅读文章
→ 标记已读或收藏
→ 需要时生成摘要或翻译
→ 下次打开状态保持一致
```

---

## 2. 核心原则

### 阅读优先

没有 AI 时，LumiRSS 必须仍是一款完整可用的 RSS 阅读器。

### 不重复造轮子

RSS 抓取、订阅更新、Entry 存储和阅读状态优先交给 FreshRSS。

没有标准 RSS 的网站优先通过 RSSHub 转换为 Feed，而不是在 LumiRSS 内自行实现爬虫系统。

### FreshRSS 是唯一 RSS 真源

Feed、分类、文章、已读和收藏状态以 FreshRSS 为准。

LumiRSS 不维护第二套 RSS 数据库。

### 移动端是一等客户端

桌面和手机使用同一套 Responsive Web。

移动端不能只是桌面三栏界面的缩小版。

### AI 是可选增强

摘要和翻译只在用户主动请求时运行。

AI Provider 故障不得阻塞正常阅读。

### 项目知识属于 Git 仓库

项目不能依赖某一次 Qoder、Codex 或其他 Agent 的聊天记录才能继续开发。

稳定架构、当前状态和任务要求必须记录在仓库中。

---

## 3. 系统架构

```text
                         内容来源
                            │
               ┌────────────┴────────────┐
               │                         │
          原生 RSS / Atom             没有 RSS
               │                         │
               │                      RSSHub
               │                         │
               └────────────┬────────────┘
                            ↓
                         FreshRSS
                      RSS 唯一真源
                            ↓
                     FreshRSSAdapter
                            ↓
                       FastAPI BFF
                    ↙               ↘
              FreshRSS             SQLite
                              AI / 缓存 / 设置
                    ↘               ↙
                       React Web
                            ↓
                   Responsive + PWA
                            ↓
                          Caddy
                            ↓
                     Docker Compose
                            ↓
                       阿里云 ECS
```

### RSSHub

负责将没有标准 RSS 的网站转换成 RSS Feed。

RSSHub 是 FreshRSS 的上游，不是 LumiRSS 的第二个数据后端。

正式路径：

```text
网站
→ RSSHub
→ FreshRSS
→ LumiRSS
```

BFF 不直接读取 RSSHub。

### FreshRSS

负责：

* Feed；
* 分类；
* 抓取；
* Entry；
* 已读；
* 收藏；
* RSS 更新；
* OPML 等 RSS 基础能力。

### FreshRSSAdapter

负责 LumiRSS 与 FreshRSS API 之间的转换。

前端不需要知道 FreshRSS 的具体 API 格式。

### FastAPI BFF

是 LumiRSS 自己的后端。

负责：

* 向 Web 提供统一 API；
* 调用 FreshRSS；
* 调用 Runtime AI；
* 保存 LumiRSS 自己的派生数据；
* 处理 LumiRSS 业务逻辑。

### SQLite

只保存 LumiRSS 自己的数据，例如：

* AI 摘要；
* AI 翻译；
* AI 缓存；
* LumiRSS 设置；
* 必要的派生内容。

不保存 FreshRSS Entry 的完整副本。

### React Web

负责全部用户界面。

技术基线：

* React；
* TypeScript；
* Vite；
* Tailwind CSS；
* TanStack Query。

### Caddy

生产环境公网入口。

负责：

* HTTPS；
* Web 静态资源；
* `/api` 反向代理；
* 基础访问保护。

### Docker Compose

负责在一台服务器上组织 LumiRSS 服务。

最终主要部署目标为普通 Linux VPS / 阿里云 ECS。

---

## 4. MVP 功能

### 阅读

MVP 必须支持：

* 全部文章；
* 未读文章；
* 收藏文章；
* Feed 筛选；
* 分类筛选；
* 文章列表；
* 文章正文；
* 已读 / 未读；
* 收藏 / 取消收藏；
* 分页；
* 基本阅读位置恢复。

### 订阅

MVP 支持：

* 查看 Feed；
* 查看分类；
* 添加 Feed；
* 删除 Feed。

OPML 导入、导出和手动刷新在第一版可以继续使用 FreshRSS 原生管理界面。

### RSSHub

MVP 必须证明至少一条真实链路：

```text
非 RSS 网站
→ RSSHub
→ FreshRSS
→ LumiRSS
```

LumiRSS 第一版不实现：

* RSSHub Route 搜索；
* RSSHub Route 编辑器；
* 自动创建 Route；
* RSSHub 管理后台。

### AI

MVP 只实现：

* 单篇摘要；
* 标题翻译；
* 正文翻译。

要求：

* 用户主动触发；
* 相同输入尽量复用缓存；
* 明确显示失败状态；
* AI 关闭时正常阅读。

首个 Runtime AI 接口采用 OpenAI-compatible HTTP API。

开发期使用的 Qoder、Codex 等工具与 Runtime AI 完全无关。

### Web 与移动端

桌面采用适合阅读的多栏布局。

手机采用：

```text
导航
→ 文章列表
→ 阅读详情
```

而不是把桌面三栏强行压缩。

至少保证：

* 无异常横向滚动；
* 字号适合直接阅读；
* 操作按钮适合触摸；
* 图片、代码块和长链接不会撑破页面；
* 阅读页可以方便返回列表。

### PWA

MVP 提供基本可安装能力：

* Web App Manifest；
* 应用图标；
* standalone 启动。

完整离线阅读、Push Notification 和后台同步不属于 MVP。

---

## 5. 数据责任

| 数据           | 权威位置           |
| ------------ | -------------- |
| Feed         | FreshRSS       |
| Category     | FreshRSS       |
| Entry        | FreshRSS       |
| 已读状态         | FreshRSS       |
| 收藏状态         | FreshRSS       |
| AI 摘要        | LumiRSS SQLite |
| AI 翻译        | LumiRSS SQLite |
| AI / 正文缓存    | LumiRSS SQLite |
| 服务端设置        | LumiRSS SQLite |
| UI 布局和部分阅读偏好 | 浏览器            |
| Secrets      | 服务端环境          |

任何实现都不能改变：

> FreshRSS 是 RSS 数据唯一真源。

---

## 6. 用户体验

### Desktop

目标布局：

```text
┌────────────┬─────────────────┬────────────────────────┐
│ Navigation │ Article List    │ Reader                 │
│            │                 │                        │
│ 未读       │ 标题            │ 标题                   │
│ 收藏       │ 来源            │ 正文                   │
│ 分类       │ 时间            │ 摘要 / 翻译            │
│ Feed       │ 状态            │                        │
└────────────┴─────────────────┴────────────────────────┘
```

### Mobile

```text
文章列表
   ↓
打开文章
   ↓
全屏阅读
   ↓
返回列表
```

阅读体验优先于展示尽可能多的信息。

### 状态反馈

至少提供：

* Loading；
* Empty；
* Error；
* Retry；
* Offline；
* AI Disabled；
* AI Failed。

错误不能只显示 HTTP 状态码，而应告诉用户发生了什么以及下一步可以做什么。

---

## 7. 安全与隐私

RSS 内容视为不可信输入。

必须做到：

* 不直接渲染未经处理的危险 HTML；
* Secret 不发送到浏览器；
* FreshRSS 凭据只保存在服务端；
* Runtime AI API Key 只保存在服务端；
* `.env`、数据库、日志和备份不能提交 Git；
* 日志不得记录 API Key、完整 Prompt 或完整文章正文。

如果未来增加外部网页全文抓取，必须单独设计 SSRF 防护后才能实现。

使用云端 AI 时，界面应明确告诉用户：

> 当前文章内容将发送给配置的 AI Provider。

---

## 8. 明确不做

MVP 不实现：

* 多用户；
* 注册；
* OAuth；
* 社交功能；
* 推荐算法；
* 自动日报；
* AI Chat；
* 向量数据库；
* 语义搜索；
* 多 AI Provider 自动路由；
* Redis / Celery / RQ；
* Kubernetes；
* Miniflux；
* 多 RSS Backend；
* Folo 后端兼容；
* 原生 iOS App；
* 原生 Android App；
* 完整离线模式；
* 图片代理；
* 自动生产部署。

除非后续真实使用产生明确需求，否则不要提前实现。

---

## 9. 技术基线

| 层             | 技术                        |
| ------------- | ------------------------- |
| Web           | React + TypeScript + Vite |
| UI            | Tailwind CSS              |
| 数据请求          | TanStack Query            |
| BFF           | FastAPI                   |
| RSS Backend   | FreshRSS                  |
| 非 RSS 来源      | RSSHub                    |
| LumiRSS 数据    | SQLite                    |
| Runtime AI    | OpenAI-compatible API     |
| Reverse Proxy | Caddy                     |
| Deployment    | Docker Compose            |
| Production    | Linux / 阿里云 ECS           |

技术基线不是为了追求最先进，而是为了减少项目复杂度。

没有实际问题时不重新选择技术栈。

---

## 10. 开发方式

每次只完成一个小目标：

```text
需求
↓
Spec
↓
Agent 先解释计划
↓
实现
↓
实际运行
↓
测试
↓
查看 git diff
↓
人工验证
↓
Commit / PR
```

Spec 只描述当前功能：

```text
Goal
Scope
Out of scope
Acceptance Criteria
Verification
```

简单任务使用一个 Markdown 文件即可。

不要为了形式提前创建大量 ADR、Spec、目录或抽象层。

---

## 11. 开发阶段

### Phase 0 — Reboot

目标：

> 建立清晰、最小的新仓库基线。

只保留：

* README；
* PRD；
* ARCHITECTURE；
* PROJECT_STATE；
* AGENTS；
* Git 基础保护。

完成后立即进入真实开发，不继续扩充文档体系。

### Phase 1 — FreshRSS

目标：

```text
Docker
→ FreshRSS
→ 浏览器可访问
→ API 可认证
→ 可以读取真实订阅
```

这是 LumiRSS 第一个真正运行的里程碑。

### Phase 2 — BFF

目标：

```text
FreshRSS
→ FreshRSSAdapter
→ FastAPI
→ /api
```

至少完成 Feed、文章列表和文章详情。

### Phase 3 — Web Reading

目标：

```text
React
→ FastAPI
→ FreshRSS
```

完成：

* 列表；
* 阅读；
* 已读；
* 收藏；
* Desktop；
* Mobile。

到这里 LumiRSS 应该已经可以真正用于阅读。

### Phase 4 — RSSHub

完成：

```text
网站
→ RSSHub
→ FreshRSS
→ LumiRSS
```

只解决真实需要 RSSHub 的订阅源。

### Phase 5 — AI

增加：

* 摘要；
* 翻译；
* SQLite 缓存。

AI 不得影响普通 RSS 阅读。

### Phase 6 — Production

完成：

```text
Docker Compose
→ Caddy
→ HTTPS
→ 阿里云 ECS
→ Desktop / Mobile / PWA
```

随后增加备份和恢复。

---

## 12. MVP 完成标准

LumiRSS MVP 完成时，应能实际演示：

```text
原生 RSS ────────────────┐
                         ↓
非 RSS → RSSHub ─────→ FreshRSS
                         ↓
                  FreshRSSAdapter
                         ↓
                    FastAPI BFF
                   ↙           ↘
             FreshRSS         SQLite
                           AI / 设置
                   ↘           ↙
                    React Web
                         ↓
                Desktop + Mobile
                         ↓
                       PWA
                         ↓
                      Caddy
                         ↓
                   阿里云 ECS
```

同时满足：

* 普通 RSS 可以阅读；
* RSSHub Feed 可以阅读；
* 已读和收藏与 FreshRSS 一致；
* 手机可以舒适阅读；
* AI 关闭仍然正常阅读；
* 摘要和翻译可以按需生成；
* 服务器重启后数据仍然存在；
* 项目可以备份和恢复；
* 新的开发 Agent 不依赖旧聊天记录即可理解项目。

---

## 13. 最终原则

> **FreshRSS 管 RSS。**

> **RSSHub 负责把非 RSS 内容变成 Feed。**

> **LumiRSS 负责阅读体验和 AI 增强。**

> **阅读优先于 AI。**

> **移动 Web 是正式客户端。**

> **成熟组件能解决的问题，不重新实现。**

> **没有实际需求，不增加架构复杂度。**

> **聊天记录不是项目知识库，Git 仓库才是。**

> **每次只完成一个能够运行、验证和理解的小闭环。**
