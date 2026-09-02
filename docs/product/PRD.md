# LumiRSS 产品需求文档

> 文档版本：v6.3 — 0014a UI Acceptance 路线修订  
> 日期：2026-09-02  
> 状态：Adopted（v6.1 经 0010a 补丁轮路线修订；v6.2 收口 Reader Style；
> v6.3 经 0014a 路线修订：插入 0014a、0015–0019 按用户批准的
> SQLite/Reader/运营决策定稿）  
> 适用范围：0009–0019 与后续 Phase 2 方向

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

## 2. 当前基线

截至公开仓库 2026-08-28 可见状态，0001–0008 已完成：

- FreshRSS 开发环境；
- FastAPI BFF 与 FreshRSSAdapter；
- Feed、文章列表、详情读取；
- read / unread、starred / unstarred；
- view / feed 过滤；
- opaque cursor pagination；
- React 三栏 Web Shell；
- 安全正文 Reader；
- 响应式移动 Web 与基础 PWA；
- RSSHub 最小服务与真实端到端链路；
- RSSHub failure isolation。

0009 原计划为 AI Summary，但本版本重新排序：

> **在继续增加 AI 和来源功能前，先完成 UI Reboot、主题系统和唯一用户界面的产品基础。**

本地事实已由 0009 Gate 0 重新验证（见 `docs/README.md`）。

---

## 3. 目标用户

### 3.1 主要用户

单个自托管用户，具有以下特征：

- 长期订阅大量中文和英文信息源；
- 希望数据与订阅由自己控制；
- 主要通过桌面浏览器和手机 Web 阅读；
- 不希望为日常使用理解 FreshRSS、RSSHub、Docker 或 API；
- 需要摘要、翻译和后续知识整理能力；
- 重视界面精致、信息密度、阅读舒适和可维护性。

### 3.2 当前不面向

- 多租户 SaaS；
- 社交内容平台；
- 公共推荐社区；
- 企业协作知识库；
- 原生移动 App 商业产品。

---

## 4. 产品价值

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
收藏、搜索、导出与知识整理
```

用户日常只需要进入 LumiRSS。

FreshRSS 和 RSSHub 是实现服务，不是普通用户必须来回切换的产品界面。

---

## 5. 产品原则

### 5.1 阅读优先

- 文章是主角，AI 是辅助；
- Timeline 必须连续、清晰、信息密度适中；
- Reader 必须安静、可读、可定制；
- AI 关闭或失败时，RSS 阅读完整可用。

### 5.2 来源可控

- 用户明确订阅什么，Timeline 就来自什么；
- 不引入算法推荐作为核心入口；
- 保留原始链接；
- 来源发现应尽可能确定性，不依赖 AI 才能工作。

### 5.3 Lumi 是唯一日常 UI

普通用户应能在 Lumi 内完成：

- 添加、删除、移动和分类 Feed；
- OPML 导入导出；
- 手动刷新；
- 搜索和生成 RSSHub 路由；
- 查看 FreshRSS / RSSHub 状态；
- 配置必要的来源凭据；
- 配置 AI、主题、阅读和备份。

FreshRSS / RSSHub 原生页面只保留为高级调试与紧急逃生入口。

### 5.4 成熟组件优先

- RSS 抓取与状态管理不重写 FreshRSS；
- 非 RSS 转 Feed 优先 RSSHub；
- 阅读抽取优先成熟库和确定性规则；
- 不因“以后也许需要”提前创建复杂抽象。

### 5.5 小步闭环

每个 milestone 必须：

```text
Spec
→ 解释计划
→ 实现
→ 自动测试
→ 实机验证
→ 查看 diff
→ 用户确认
→ Commit / PR
```

---

## 6. 架构总览

### 6.1 RSS 读取数据路径

```text
Native RSS ─────────────┐
                        ▼
Non-RSS → RSSHub → FreshRSS
                        ▼
                 FreshRSSAdapter
                        ▼
                   FastAPI BFF
                  ↙           ↘
            FreshRSS         SQLite
                         AI / Cache / Settings
                  ↘           ↙
                    React Web
                        ▼
                 Responsive / PWA
                        ▼
                      Caddy
                        ▼
                 Docker Compose
                        ▼
                   Alibaba ECS
```

### 6.2 来源控制路径

后续 Lumi 内添加和配置来源需要单独的 Control Plane：

```text
React Web
   ↓
FastAPI BFF
   ├── FreshRSS Control Adapter
   │     ├── subscribe / unsubscribe
   │     ├── rename / category
   │     ├── OPML
   │     └── refresh / status
   │
   └── RSSHub Catalog / Control Adapter
         ├── route metadata
         ├── URL route matching
         ├── preview / health
         └── allow-listed configuration
```

控制路径不改变读取路径：

- RSSHub 生成的 URL 最终订阅进 FreshRSS；
- Reader 仍从 FreshRSS 读取；
- RSSHub 宕机不影响 FreshRSS 中已抓取文章。

### 6.3 长期统一来源层

Phase 2 才考虑：

```text
                       Lumi Domain API
                              │
        ┌───────────────┬─────┼─────┬──────────────┐
        ▼               ▼     ▼     ▼              ▼
     RSS Domain       Web Clip API  Email       Obsidian
     FreshRSS         Connector     Connector   Connector
        │
      RSSHub
   Feed Generator
                              │
                              ▼
                         Agent Context
```

FreshRSS 是 RSS 域唯一真源，不是未来所有信息类型的总数据库。

---

## 7. 数据责任

| 数据 | 权威位置 |
| --- | --- |
| RSS Feed | FreshRSS |
| RSS Category | FreshRSS |
| RSS Entry | FreshRSS |
| RSS read state | FreshRSS |
| RSS starred state | FreshRSS |
| RSS 更新与保留策略 | FreshRSS |
| RSSHub 路由定义 | RSSHub 官方元数据 / Lumi 缓存目录 |
| RSSHub 实例 / 配置 | RSSHub 运行时与配置（Lumi 只展示与缓存短期诊断；0018 经 schema 驱动 allow-list 控制面管理） |
| Lumi UI 设置 | 浏览器（0017 起可经 lumi.sqlite 服务端化） |
| Reader 偏好 | 浏览器（0017 起连续数值控制；可经 lumi.sqlite 服务端同步） |
| Lumi-owned 应用状态（lumi.sqlite，0015 起） | lumi.sqlite：AI 结果缓存、provider/model 元数据、prompt 版本、内容哈希、生成状态、需持久化的服务端设置、备份/恢复元数据 |
| AI 摘要 / 翻译 | Lumi SQLite |
| AI cache | Lumi SQLite |
| Connector 配置 | Lumi SQLite / 服务端 secrets，Phase 2 |
| Web clip 内容 | 未来 Web Clip 域存储，不进 FreshRSS |
| API / Email / Obsidian 内容 | 未来各 Connector 领域存储 |
| Secrets | 服务端环境或专用 secret store |

硬规则：

> FreshRSS 是 RSS 数据唯一真源；Lumi SQLite 不能成为第二套 RSS 数据库
> （feeds / entries / read / starred / 订阅 / FreshRSS 分类均不得影子复制）。

---

## 8. 当前 MVP 功能范围

MVP 由 0001–0019 组成（编号经 0010a / 0013 / 0014 / 0014a 插入后顺延；
实际编号以 docs/ROADMAP.md 为准）。

### 8.1 阅读

必须支持：

- 全部、未读、收藏；
- Feed 与分类筛选；
- 连续 Timeline；
- 文章详情；
- 已读 / 未读；
- 收藏 / 取消收藏；
- cursor pagination；
- 加载、空、错误状态；
- 打开原文；
- 安全 HTML 渲染；
- 基本阅读位置恢复；
- 桌面和移动端舒适阅读。

保留当前行为：

> 打开文章不自动标记已读，状态由用户显式设置，除非未来单独 spec 并由用户批准。

### 8.2 订阅中心

MVP 完成前必须在 Lumi 内支持：

- 添加 Feed；
- 删除 Feed；
- 重命名；
- 分类创建、移动与筛选；
- OPML 导入导出；
- 手动刷新；
- FreshRSS 连接和健康状态；
- 明确错误与恢复操作。

不应要求普通用户进入 FreshRSS 完成这些高频操作。

### 8.3 来源发现与 RSSHub

MVP 目标流程：

```text
粘贴 URL
  ↓
直接 RSS / Atom
  ↓
HTML rel=alternate
  ↓
常见 Feed endpoint
  ↓
RSSHub route match
  ↓
参数表单与预览
  ↓
订阅进 FreshRSS
```

支持：

- RSSHub route catalog；
- 路由搜索；
- 参数说明和表单；
- route preview；
- 实例 health；
- 需要配置的路由给出明确提示；
- 生成的 Feed 一键加入 FreshRSS；
- RSSHub 不可用时不影响已有阅读。

MVP 不要求：

- 自定义编写 RSSHub route；
- fork RSSHub；
- 通用 Docker 管理面板；
- 自动绕过登录、验证码、付费墙或站点安全措施。

### 8.4 AI

MVP 支持：

- 单篇摘要；
- 标题翻译；
- 正文翻译；
- 双语阅读；
- 当前文章上下文对话；
- 桌面浮动 / 停靠 AI；
- 移动 Bottom Sheet / Fullscreen；
- 失败、重试、模型、时间与缓存状态。

要求：

- 用户主动触发；
- AI 不阻塞普通阅读；
- OpenAI-compatible 为首个 provider contract；
- cache key 至少考虑内容、provider、model、prompt version、language；
- API key 不进入前端；
- 不在 MVP 做多 Provider 自动路由、向量数据库或全库语义搜索。

### 8.5 设置

统一设置至少包含：

- 通用；
- 外观；
- 阅读；
- 订阅与来源；
- FreshRSS；
- RSSHub；
- AI；
- 数据与备份；
- 高级诊断；
- 关于与第三方许可。

不照搬 FreshRSS 的所有界面偏好，只映射会影响 Lumi 行为和数据的设置。

### 8.6 移动 Web / PWA

手机正式支持：

```text
导航 / Timeline
  → Reader
  → Back
```

要求：

- 不是桌面三栏压缩版；
- 无异常横向滚动；
- touch target ≥ 44px；
- safe-area；
- 图片、表格、代码和长链接不撑破页面；
- AI 采用 Bottom Sheet 或独立页面；
- 基础安装能力；
- 完整离线、Push 和后台同步不属于首版 MVP。

---

## 9. UI / UX 需求

### 9.1 参考层级

1. **Folo**：首要结构、信息密度、Timeline、Reader、微交互；
2. **OrigRead Desktop**：Settings、Reader tools、来源发现、RSSHub、AI panel；
3. **用户提供的配色图**：低饱和柔彩、暖中性背景；
4. **其他项目**：Fluent Reader、FeedFlow、Read You、NetNewsWire、NewsFlash 的专项经验；
5. **Lumi 品牌**：淡靛 Accent、流光、安静阅读。

只追求交互与精致度参考，不追求 Folo 产品功能全量复刻。

### 9.2 默认视觉语言

默认主题名：`Lumi Mist / 雾光`

特征：

- 暖灰 / 粉灰中性背景；
- 冷白 Reader；
- 偏蓝淡靛主强调色；
- 雾蓝、鼠尾草绿、杏橙、薰衣草紫、灰青、豆沙红等柔彩分类色；
- 极淡分隔线；
- 低对比 hover 和 selected；
- 有限圆角；
- 阴影只用于 popover、dialog、floating panel；
- 文字层级清楚；
- 文章列表不是卡片瀑布流。

### 9.3 主题系统

必须支持：

- System / Light / Dark；
- 默认和若干预设色板；
- 后续自定义 Accent；
- semantic tokens；
- App Theme 与 Reader Theme 分离；
- Reader 独立背景、字体、字号、行距、最大宽度；
- 主题变化不需要重写组件。

禁止在业务组件中继续散落：

- `bg-blue-50`；
- `hover:bg-gray-100`；
- 任意硬编码品牌色；
- 每个页面自己定义一套圆角和 shadow。

### 9.4 桌面布局

```text
Sidebar | Timeline | Reader
```

- Sidebar：紧凑、可折叠、文件夹树；
- Timeline：连续列表、来源/时间/标题/摘要/图片清晰分级；
- Reader：正文优先、最大宽度、工具栏轻量；
- pane 可以在后续支持拖动或记忆宽度；
- AI 是 overlay / dock，不是永久第四栏。

### 9.5 响应式

| Viewport | 主要布局 | AI 形式 |
| --- | --- | --- |
| ≥1440 | 三栏 | 浮动窗口 / 右侧 dock |
| 1024–1439 | 三栏或折叠 Sidebar | overlay / drawer |
| 768–1023 | Sidebar drawer + list/detail | drawer / sheet |
| <768 | 单栏页面流 | bottom sheet / full screen |

### 9.6 微交互

- 简单状态优先 CSS transition；
- hover 100–120ms；
- menu 120–160ms；
- panel 180–220ms；
- 支持 reduced motion；
- 禁止 hover scale、卡片上浮、发光、无意义 bounce。

### 9.7 可访问性

- 键盘可用；
- `focus-visible`；
- Dialog / Sheet focus trap；
- Escape 可关闭；
- unread / selected 不只靠颜色；
- 对比度可读；
- aria label；
- 手机上主要操作 ≥44px。

---

## 10. 安全与隐私

### 10.1 前端边界

React Web 只能访问 Lumi BFF：

- 不直连 FreshRSS；
- 不直连 RSSHub；
- 不直连 Runtime AI；
- 不持有服务凭据。

### 10.2 内容安全

- FreshRSS HTML 继续视为不可信；
- DOMPurify 仍是唯一批准的 HTML 渲染边界；
- UI Reboot 不削弱 sanitization；
- 外部链接只允许明确的 `http/https`；
- 不自动执行 Feed 中脚本、表单、iframe 或嵌入对象。

### 10.3 服务控制

- 不把 Docker Socket 暴露给 BFF；
- 服务重载采用最小权限、allow-list 的控制方式；
- secrets 不写日志、不回传浏览器、不提交 Git；
- 认证浏览器截图不得带入仓库。

### 10.4 AI

- API keys 只在服务端；
- 日志脱敏；
- 清晰标注 AI 生成内容；
- 显示失败而不是假装成功；
- 用户可关闭 AI。

---

## 11. 许可证与参考源码政策

Folo 和 OrigRead Desktop 是重要代码参考，但直接使用前必须完成：

- 固定上游 commit SHA；
- 许可证审计；
- 用户批准 LumiRSS 的许可证；
- `SOURCE_MAP.md`；
- `THIRD_PARTY_NOTICES.md`；
- 保留修改和来源说明。

LumiRSS 已于 2026-08-28 经用户批准采用 `AGPL-3.0-only`（仓库根目录已添加 LICENSE），以便合规适配 AGPL 参考代码；来源映射与声明文件随实现逐步维护。

硬规则：

- 不复制 Folo `icons/mgc`；
- OrigRead Android GPL 代码默认只作行为和移动端参考，除非另行确认；
- 视觉启发、独立重写、代码适配、直接复制必须分别记录。

---

## 12. 开发路线

> 实际编号与最新状态以 docs/ROADMAP.md + docs/README.md 为准；
> 本节记录 0014a 修订后的 0015–0019 产品路线（用户 2026-09-02 批准）。

### 0009 — UI Reboot & Reference Lab

- v6 文档；reference baseline；license gate；design tokens；
- theme foundation；UI primitives；responsive App Shell；
- Sidebar / Timeline / Reader；Light / Dark；screenshot regression；
- 不改 BFF API 和业务行为。

### 0010 — Settings Center & Adaptive Shell

- Folo 式设置中心；侧栏信息架构分组；三栏拖拽 / 折叠 / 持久化；
- 移动端底部 Tab 演进（0010a/0011 一路修订）；快捷键基础集。

### 0010a — Settings Expansion & Reader Style

- 设置分类扩展；阅读样式（主题包 / 背景 / 排版预设）；
- 配置备份导出 / 导入（JSON 信封，可选加密）。

### 0011 — Mobile UI Five-Screen Alignment

- 移动端一级页面（首页 / 订阅 / 搜索 / 收藏）+ 导航抽屉 + 底部导航岛；
- 列表 ↔ 全屏 Reader 的移动出行契约（0014a 收口）。

### 0012 — Reader Style Deep Customization

- 字体导入、中文排版深度、主题包分享、代码高亮等阅读深度定制。

### 0013 — Unified Subscription Center

- Feed / Category CRUD、OPML 导入导出（BFF 控制平面）、FreshRSS
  订阅管理 + 实时连接状态；所有高频订阅操作进入 Lumi。

### 0014 — Source Discovery & RSSHub

- 网站 → RSS/Atom 发现、Lumi 静态精选 RSSHub 路由目录 + 参数表单 +
  预览 + 一键订阅；全链路经 BFF 代理。

### 0014a — UI Acceptance & Navigation Consistency

- 补齐 0014 人工验收缺口：桌面「添加来源」入口、移动端收藏 →
  全屏 Reader 一致性、设置 stale 标签清理、真实 Playwright 验收。

### 0015 — AI Foundation, Summary & Lumi SQLite Foundation

- 激活 Lumi-owned 持久层 lumi.sqlite（迁移/模式策略先行，杜绝无版本
  sqlite 文件）：AI 结果缓存、provider/model 元数据、prompt 版本、
  内容哈希、生成状态、需持久化的 Lumi 服务端设置、备份元数据；
- OpenAI-compatible provider 契约；单篇按需摘要；失败重试与真实状态；
- freshRSS 依然 RSS-domain 唯一真源：lumi.sqlite 不得存
  feeds/entries/read/starred/subscription/category 影子副本。

### 0016 — Translation & AI Conversation

- 标题翻译 + 正文翻译 + 双语阅读；翻译缓存；
- 当前文章上下文对话（共享 0015 AI foundation）；
- 桌面浮动/停靠 + 移动 Bottom Sheet / Fullscreen 的 AI 表面；
- privacy/上下文控制；依赖 0015。

### 0017 — Reader Power UX & Unified Settings

- 继承既有 Reader 定制（主题/字体/中文排版/代码/图片/对齐/首行缩进/
  减动效/双栏与滚动模式候选/重置默认）；
- 微信读书式连续阅读定制（WYSIWYG，即时生效，写入数值而非枚举）：
  - 字号：连续滑杆（A- / A+）；
  - 行高：compact ←→ spacious 连续滑杆；
  - 段距：compact ←→ spacious 连续滑杆；
  - 内容/页宽：narrow ←→ wide 连续滑杆（移动端按视口自动约束）；
  - 左右页边距：small ←→ large 连续滑杆（移动/桌面不同安全区间）；
- 统一设置（服务端侧用 0015 引入的 lumi.sqlite 持久化，保留 UI 即时响应）；
- 具体 min/max/default 在 0017 以视觉测试与排版约束选定；
- 不依赖 AI 概念上先行：序号是实现顺序，不是领域归属。

### 0018 — Production, Operations & Backup

三大运营面：

```text
A. RSSHub Control Center（schema 驱动的类型化 allow-list：
   Status / Instance / Cache / Network / Access control /
   Browser-runtime / Route credentials / Advanced 分组；
   secrets 只写不读回；restartRequired 明确展示；
   不用任意环境变量编辑器、不暴露任意 shell、不给 BFF 无限制
   Docker socket 权限）
B. FreshRSS Operations（服务诊断 / 健康 / 备份 / 高级逃生入口 /
   安全支持的 operator 设置；不重建 FreshRSS UI、不复制其数据库）
C. WebDAV Backup / Restore（manifest + FreshRSS 导出数据 +
   lumi.sqlite + Lumi 服务配置 + RSSHub 配置 + checksums；
   secrets 加密或按最终安全设计排除；
   restore 为多步流程：选择 → 下载 → 校验 → 兼容检查 →
   预览 → 当前态安全备份 → 显式确认 → 恢复 → 健康验证；
   非单钮破坏性操作）

另保留：production Compose、Caddy/TLS、单用户访问、持久卷、
健康/就绪、日志脱敏、升级/回滚、资源限制、灾难恢复演练。
```

### 0019 — MVP Stabilization & Release

- 全量回归；桌面/移动响应式矩阵；Playwright 流程；可访问性；安全；
  性能预算；空/加载/错误态；备份恢复演练；升级回滚演练；
  许可证审查；operator 文档；release notes；MVP release；
- 不再新增主要产品功能。

### Phase 2 — Knowledge Workbench

按真实需求逐项设计：

- Web Clip；
- JSON / API source；
- Email newsletters；
- Obsidian connector；
- Unified source registry；
- Unified search；
- Agent workspace。

Phase 2 不得反向破坏 RSS 域边界。

---

## 13. 当前明确不做

在 0009 不做：

- AI runtime；
- Feed CRUD；
- RSSHub route builder；
- Source Resolver；
- SQLite schema；
- 网页剪藏；
- JSON/API；
- 邮件；
- Obsidian；
- Agent；
- production；
- API contract 扩张；
- Folo 社交、推荐、公开 Profile、奖励经济；
- 多用户、注册、OAuth；
- 原生 iOS / Android；
- 向量数据库；
- 多模型自动路由；
- Kubernetes；
- Redis / Celery，除非后续有真实压力证明。

---

## 14. 0009 完成标准

0009 完成时必须满足：

- 0001–0008 行为无回归；
- BFF API contract 未变化，除非单独批准；
- semantic tokens 替代页面硬编码颜色；
- System / Light / Dark 可用；
- 默认 Lumi Mist 达到用户认可；
- Sidebar / Timeline / Reader 达到统一视觉；
- desktop / tablet / mobile 均无布局破坏；
- 加载、空、错误和 focus 状态完整；
- DOMPurify 安全边界保留；
- 自动测试、lint、build 通过；
- 真实浏览器 smoke 通过；
- 固定截图尺寸完成对照；
- reference repos 和来源记录可追溯；
- 未经批准的上游代码或资源未进入仓库；
- PROJECT_STATE、README、ROADMAP 与实际一致。

---

## 15. MVP 完成标准

0019 完成时应能演示：

```text
原生 RSS ────────────────┐
                         ▼
普通 URL → RSSHub ────→ FreshRSS
                         ▼
                  FreshRSSAdapter
                         ▼
                    FastAPI BFF
                   ↙           ↘
             FreshRSS         SQLite
                         AI / Settings
                   ↘           ↙
                    Lumi Web
                  Desktop / Mobile
                         ▼
                       Caddy
                         ▼
                    Alibaba ECS
```

同时：

- 用户无需日常进入 FreshRSS / RSSHub；
- Native RSS 和 RSSHub Feed 都可发现、添加和阅读；
- read / starred 与 FreshRSS 一致；
- 主题与阅读偏好可用；
- AI 可关闭且失败不影响阅读；
- 手机可舒适使用；
- 服务重启后数据存在；
- backup / restore 经过演练；
- 新 Agent 只读 Git 仓库即可理解项目。

---

## 16. 最终原则

> **LumiRSS 是唯一日常用户界面。**
>
> **FreshRSS 管 RSS。**
>
> **RSSHub 把非 RSS 内容变成 Feed。**
>
> **读取数据路径与来源控制路径分离。**
>
> **Folo 是 UI / UX 教科书，不是要完整复制的产品。**
>
> **OrigRead 是来源发现、设置和 Reader 工具参考。**
>
> **阅读优先于 AI。**
>
> **移动 Web 是正式客户端。**
>
> **成熟组件能解决的问题不重新实现。**
>
> **未来方向可以大，但当前 milestone 必须小。**
>
> **Git 仓库才是项目知识源。**
