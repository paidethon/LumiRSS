# LumiRSS 产品需求文档（PRD）

> 职责：定义产品“应该具备什么能力”（WHAT / WHY）。
> 系统如何实现（HOW）见 [architecture/README.md](../architecture/README.md)；
> 下一步计划见 [ROADMAP.md](../ROADMAP.md)。

---

## 1. 产品定义

LumiRSS 是一个：

> **单用户、自托管、来源可控、阅读优先、AI 可选的现代信息阅读器。**

当前阶段以 RSS 为核心：

- FreshRSS 负责成熟的 RSS 抓取、订阅、分类、文章和状态；
- RSSHub 将没有原生 RSS 的网站转换成 Feed；
- LumiRSS 提供统一、精致、响应式的阅读与管理界面；
- FastAPI BFF 隔离上游服务、凭据与前端；
- SQLite 保存 Lumi 自己的设置、AI 结果和必要派生数据。

中长期方向是在 RSS MVP 稳定后演进为：

> **RSS、网页剪藏、API 信息、邮件简报、Obsidian 库与 Agent 的个人信息聚合知识工作台。**

这不是要求当前立即扩张范围。LumiRSS 必须先把 RSS Reader 做成真正可长期使用的产品。

---

## 2. 目标用户

### 2.1 主要用户

单个自托管用户，具有以下特征：

- 长期订阅大量中文和英文信息源；
- 希望数据与订阅由自己控制；
- 主要通过桌面浏览器和手机 Web 阅读；
- 不希望为日常使用理解 FreshRSS、RSSHub、Docker 或 API；
- 需要摘要、翻译和文章对话能力；
- 重视界面精致、信息密度、阅读舒适和可维护性。

### 2.2 当前不面向

- 多租户 SaaS；
- 社交内容平台；
- 公共推荐社区；
- 企业协作知识库；
- 原生移动 App 商业产品。

---

## 3. 产品价值与原则

LumiRSS 的核心价值不是重新发明 RSS 抓取器，而是把成熟后端组合成一个完整产品：

```text
发现来源
  ↓
添加与管理订阅
  ↓
统一 Timeline
  ↓
舒适阅读
  ↓
摘要 / 翻译 / 提问
  ↓
收藏、导出与知识整理
```

用户日常只需要进入 LumiRSS。FreshRSS 和 RSSHub 是实现服务，不是普通用户必须来回切换的产品界面。

产品原则：

1. **阅读优先**：文章是主角，AI 是辅助；AI 关闭或失败时，RSS 阅读完整可用。
2. **来源可控**：用户明确订阅什么，Timeline 就来自什么；不引入算法推荐；
   保留原始链接；来源发现是确定性的，不依赖 AI 才能工作。
3. **Lumi 是唯一日常 UI**：添加/删除/移动/分类 Feed、OPML、刷新、来源发现、
   服务状态、AI/主题/阅读/备份配置都应能在 Lumi 内完成；
   FreshRSS / RSSHub 原生页面只保留为高级调试与紧急逃生入口。
4. **成熟组件优先**：不重写 FreshRSS；非 RSS 转 Feed 优先 RSSHub；
   不为“以后也许需要”提前创建复杂抽象。

---

## 4. 当前能力基线（Current MVP）

以下能力均已实现（以源码为准，非规划）：

- **阅读**：全部/未读/收藏视图、Feed 与分类筛选、连续 Timeline、安全正文
  Reader、显式已读/星标（打开文章不自动标读）、opaque cursor 分页、
  打开原文；
- **订阅中心**：添加/退订/分类管理、OPML 导入导出、FreshRSS 连接状态与
  高级入口；
- **来源发现**：网站 RSS/Atom 发现、RSSHub 精选路由目录 + 参数表单 + 预览 +
  一键订阅（全链路经 BFF）；
- **RSSHub 控制中心**：健康探测、schema 驱动的 allow-list 实例配置、
  机密 write-only、restartRequired 语义、env 导出与应用确认；
- **AI**：单篇摘要、标题+正文翻译（译文视图）、文章上下文对话、
  多 Profile（purpose 映射：摘要/翻译/对话）、浏览器配置 API Key
  （服务端 SecretsStore 保存）、结果缓存与诚实的失败/缓存状态；
- **Reader 深度定制**：连续排版滑杆、排版预设、`.lumitheme` 主题包、
  自定义 CSS、自定义字体、中文排版（简繁/缩进/标点悬挂）、代码高亮、
  图片模式、滚动标记已读（可选）；
- **统一设置中心**：13 个分类（含“数据控制”，备份与恢复已并入）；
- **备份/恢复**：本地 + WebDAV 备份、历史记录、两步恢复（预览校验 +
  显式确认 + 自动安全备份）、FreshRSS 数据离线恢复；
- **部署运维**：生产 Compose + Caddy（TLS/basic auth/安全头）、健康检查、
  真实依赖状态页、版本溯源、日志轮转与脱敏；
- **移动 Web / PWA**：可安装 manifest、移动五屏信息架构、touch target
  与 safe-area。

明确未实现：web clipping、Obsidian 集成、邮件/JSON/API connector、
统一搜索、PWA 离线缓存（无 Service Worker）、多用户——见 §10。

---

## 5. 功能需求

### 5.1 阅读

- 全部、未读、收藏视图；Feed 与分类筛选；连续 Timeline；
- 文章详情：安全 HTML 渲染、加载/空/错误状态；
- 已读/未读、收藏/取消收藏：用户显式设置（set 语义，非 toggle）；
  **打开文章不得自动标记已读**（滚动标记已读为可选、默认关闭）；
- cursor pagination；打开原文（仅绝对 http/https）。

### 5.2 订阅中心

- 添加、退订、重命名、分类创建/移动/重命名/筛选；
- OPML 导入（merge-only）导出；
- FreshRSS 连接与健康状态；明确错误与恢复操作；
- 不应要求普通用户进入 FreshRSS 完成这些高频操作。

### 5.3 来源发现与 RSSHub

目标流程：

```text
粘贴 URL
  ↓
直接 RSS / Atom → HTML rel=alternate → 常见 Feed endpoint
  ↓
RSSHub 精选路由匹配
  ↓
参数表单与预览
  ↓
订阅进 FreshRSS
```

- 路由目录、路由搜索、参数说明与表单、route 预览、实例健康；
- 需要配置的路由给出明确提示；生成的 Feed 一键加入 FreshRSS；
- RSSHub 实例配置：类型化 allow-list、secrets 只写不读、
  「重启后生效」明确展示；
- RSSHub 不可用时不影响已有阅读。

MVP 不要求：自定义编写 RSSHub route、fork RSSHub、通用 Docker 管理
面板、自动绕过登录/验证码/付费墙。

### 5.4 AI

- 单篇摘要；标题 + 正文翻译（原文/译文切换的译文视图）；
  当前文章上下文对话；
- 多 Profile 管理（Base URL / Model / 启停），purpose 映射
  （摘要 / 翻译 / 对话 → 默认配置或任一 Profile）；
- API Key 在浏览器表单填写、经 write-only 接口提交、仅保存于服务端
  SecretsStore（不可回读，不在前端持久化）；环境变量仅作为默认配置
  路径的回退；
- 用户主动触发；AI 不阻塞普通阅读；OpenAI-compatible 为 provider 契约；
- 翻译仅由 AI Provider 驱动；**本地简繁转换（OpenCC）是展示层字形转换，
  不属于翻译**，不依赖任何 Provider；
- 缓存 key 至少考虑内容、provider、model、prompt 版本、语言；
  缓存命中与新生成在 UI 上明确区分；
- 失败、重试、模型与时间状态诚实呈现；清晰标注 AI 生成内容；
- 不做：多 Provider 自动路由、向量数据库、全库语义搜索。

### 5.5 设置

统一设置中心，当前分类：

```text
通用 · 外观 · 阅读 · 快捷键 · 翻译 · 文章过滤 · RSSHub
订阅与来源 · AI · 数据控制（含备份/恢复） · 账户与服务 · 工作区（占位） · 关于
```

- 不照搬 FreshRSS 的所有界面偏好，只映射影响 Lumi 行为和数据的设置；
- 设置应区分即时生效 / 重启后生效；
- secret 值只写不读；工作区等未实现分类必须诚实标注“占位”。

### 5.6 移动 Web / PWA

```text
导航 / Timeline → Reader → Back
```

- 不是桌面三栏压缩版；无异常横向滚动；
- touch target ≥ 44px；safe-area；图片、表格、代码和长链接不撑破页面；
- 基础安装能力（manifest）；完整离线、Push 和后台同步不属于当前范围。

---

## 6. UI / UX 需求

### 6.1 参考层级

1. **Folo**：结构、信息密度、Timeline、Reader、微交互；
2. **OrigRead Desktop**：Settings、Reader tools、来源发现、AI 面板模式；
3. **用户配色参考**：低饱和柔彩、暖中性背景；
4. 其他项目（Fluent Reader、FeedFlow、Read You、NetNewsWire、NewsFlash）
   专项经验；
5. **Lumi 品牌**：淡靛 Accent、安静阅读。

只追求交互与精致度参考，不追求 Folo 产品功能全量复刻。详细视觉规范见
[design/design-system.md](../design/design-system.md)。

### 6.2 默认视觉语言

默认主题名：`Lumi Mist / 雾光`

- 暖灰 / 粉灰中性背景；冷白 Reader；偏蓝淡靛主强调色；
- 雾蓝、鼠尾草绿、杏橙、薰衣草紫、灰青、豆沙红等柔彩分类色；
- 极淡分隔线；低对比 hover/selected；有限圆角；
- 阴影只用于 popover、dialog、floating panel；
- 文字层级清楚；文章列表不是卡片瀑布流。

### 6.3 主题系统

- System / Light / Dark；默认与若干预设色板；自定义 Accent（取色器，
  派生色自动生成并做对比度校验）；
- semantic tokens，业务组件禁止硬编码品牌色；
- **App Theme 与 Reader Theme 分离**：Reader 独立背景、字体、字号、
  行距、最大宽度；主题变化不需要重写组件。

### 6.4 布局与响应式

桌面 `Sidebar | Timeline | Reader` 三栏；AI 呈现内嵌于 Reader，
不是永久第四栏。

| Viewport | 主要布局 |
| --- | --- |
| ≥1440 | 三栏 |
| 1024–1439 | 三栏或折叠 Sidebar |
| 768–1023 | Sidebar drawer + list/detail |
| <768 | 单栏页面流（列表 ↔ 全屏 Reader） |

### 6.5 微交互与可访问性

- 简单状态优先 CSS transition（hover 100–120ms；menu 120–160ms；
  panel 180–220ms）；支持 reduced motion；
- 禁止 hover scale、卡片上浮、发光、无意义 bounce；
- 键盘可用；`focus-visible`；Dialog/Sheet focus trap；Escape 可关闭；
- unread / selected 不只靠颜色；对比度可读；aria label；
- 手机主要操作 ≥44px。

---

## 7. 安全与隐私

### 7.1 前端边界

React Web 只能访问 Lumi BFF：不直连 FreshRSS、RSSHub 或 AI Provider；
不持久化任何服务凭据。

### 7.2 内容安全

- Feed HTML 永远视为不可信；DOMPurify 是唯一批准的最终渲染边界；
- 外部链接只允许明确的 `http/https`；
- 不自动执行 Feed 中脚本、表单、iframe 或嵌入对象。

### 7.3 服务与凭据

- 不把 Docker Socket 暴露给 BFF；服务重载采用最小权限、allow-list 的
  控制方式；
- secrets 不写日志、不回传浏览器（只写接口）、不提交 Git；
- API Key 可在浏览器表单输入，但仅传输给服务端 SecretsStore 保存，
  前端不持久化、不可回读；
- 认证环境截图不得带入仓库。

---

## 8. 数据责任

| 数据 | 权威位置 |
| --- | --- |
| RSS Feed / Category / Entry / read / starred / 保留策略 | FreshRSS |
| RSSHub 路由目录 | Lumi 精选静态目录（BFF） |
| RSSHub 实例配置 | Lumi 期望/应用配置（重启生效）+ RSSHub 运行时 |
| Lumi UI / Reader 偏好 | 浏览器本地优先，便携键经 Lumi SQLite 服务端同步 |
| AI 结果缓存、AI 设置、备份账本 | Lumi SQLite |
| API keys / WebDAV 密码 / RSSHub 机密 | 服务端 secrets.json（0600） |
| Connector 配置（clip/email/Obsidian） | Phase 2，不进 FreshRSS |

硬规则：

> FreshRSS 是 RSS 数据唯一真源；Lumi SQLite 不能成为第二套 RSS 数据库。

---

## 9. 许可证与参考源码政策

Folo 和 OrigRead Desktop 是重要参考，但直接使用前必须完成：固定上游
commit SHA、许可证审计、用户批准 LumiRSS 许可证、`SOURCE_MAP.md`、
`THIRD_PARTY_NOTICES.md`、保留修改和来源说明。

LumiRSS 已于 2026-08-28 经用户批准采用 `AGPL-3.0-only`（仓库根目录
LICENSE），以便合规适配 AGPL 参考代码；来源映射与声明文件随实现逐步
维护（见 [upstream/](../upstream/)）。

硬规则：

- 不复制 Folo `icons/mgc`；
- OrigRead Android GPL 代码默认只作行为和移动端参考，除非另行确认；
- 视觉启发、独立重写、代码适配、直接复制必须分别记录。

---

## 10. 当前明确不做（Deferred）

- web clipping、JSON/API 来源、邮件简报、Obsidian connector、
  统一来源注册表、统一搜索、Agent workspace（Phase 2）；
- 多用户、注册、OAuth；
- Folo 社交、推荐、公开 Profile、奖励经济；
- 原生 iOS / Android；
- 向量数据库、多模型自动路由；
- Kubernetes、Redis / Celery（除非真实压力证明）；
- PWA 完整离线 / Push / 后台同步。

Phase 2 不得反向破坏 RSS 域边界。

---

## 11. 验收原则

- 用户无需日常进入 FreshRSS / RSSHub；
- 原生 RSS 和 RSSHub Feed 都可发现、添加和阅读；
- read / starred 与 FreshRSS 一致（set 语义；打开不自动标读）；
- 主题与阅读偏好可用且可持久化；
- AI 可关闭、未配置时诚实呈现，失败不影响阅读；
- 手机可舒适使用；加载/空/错误状态完整；
- 服务重启后数据存在；backup / restore 经过真实演练；
- DOMPurify 边界与行为回归测试保持绿色；
- 新 Agent 只读 Git 仓库（AGENTS.md → docs/README.md → 相关文档 →
  源码/测试）即可理解项目。
