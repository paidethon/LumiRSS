# Roadmap

> 只回答"接下来准备做什么"。已完成的工作与版本化发布记录在仓库根
> [CHANGELOG.md](https://github.com/paidethon/LumiRSS/blob/main/CHANGELOG.md)；
> 逐项任务状态以机读台账 `docs/implementation-status.json` 为准
> （220 项，`npm run check:dashboard` 漂移守卫，看板接法见
> [operations](/operations) §项目进度看板）。

## 客户端矩阵（2026-10 已批准）

- **iOS / iPadOS**：唯一单独维护的原生客户端（Swift + SwiftUI，
  `apps/ios`，独立 0.1.0 Preview 版本线）。首版范围：登录/会话恢复、
  时间线与筛选、订阅浏览、搜索、收藏、正文阅读（受控 WKWebView）、
  已读/收藏 set 语义、基础离线缓存、设置页。AI 摘要/翻译不在首版。
- **Web / PWA**（React + Vite）继续是全功能端，不重写。
- **Android**（2026-12 规划）：Capacitor 兼容封装复用 Web，不复制
  第二套业务 UI/API 层。
- **Windows**（2026-12 规划）：Tauri 薄壳 + 现有 PWA。
- 明确不引入：Capacitor iOS、React Native、Flutter、KMP、
  Android Compose、Windows WinUI。

## Current state（2026-10）

MVP（0000–0020）、Phase 2 知识工作台、Phase 2 recovery 返工、2.0.0
邀请制多账户与默认关闭的可选公开注册均已合入 main 并部署生产。3.0.0
重建批次在此之上小步补齐（用户视角明细见 CHANGELOG）：来源中心九类
汇总、Obsidian 服务端受限导出、AI 日报、邮件简报内容页、RAG 索引
内容页、OPML 导入 RSSHub 自动匹配、内置 8 款开源阅读字体、49 项用户
偏好上云、单容器拓扑；认证以应用会话为主，basic auth 转为兼容可选项。
iOS 原生客户端 0.1.0 Preview 已开工（`apps/ios`，macOS CI 构建；
契约经脚本过滤消费同一份权威 OpenAPI 导出）。
机读功能清单见 `docs/feature-manifest.json`；FreshRSS/RSSHub
上游全功能对照见 [upstreams](/upstreams) 与
`docs/public/reference/upstream-feature-matrix.html`。

## 2026-10 — iOS Native Preview（最高优先级）

状态：**in progress**（分支 `feat/ios-native-preview`；macOS CI
`.github/workflows/ios.yml`）。

- [x] 纵向闭环：服务器配置 → cookie 登录（含 TOTP）→ 时间线 →
  正文 → 已读/收藏（set 语义）→ 状态回读；
- [x] 订阅/搜索/收藏/设置入口；分页去重、下拉刷新、错误重试、
  空状态、深浅色；
- [x] 基础本地缓存（列表+正文，按服务器/账户隔离、容量上限）；
- [x] macOS CI：模拟器构建/单测/启动冒烟 + 未签名设备归档；
- [ ] 首版交付后：缓存与阅读体验完善、必要系统集成（按需立项）；
- [ ] 签名 IPA 与 TestFlight（**blocked**：仓库尚无 Apple 开发者
  证书/Profile Secrets，补齐清单见
  [development](/development) §iOS 签名）。

## 2026-11 — iOS 1.0 稳定化

状态：**planned**。

- 离线/同步策略（写队列、Delta Sync 评估）、设备会话管理；
- 兼容性矩阵（最低服务器版本探针的实际数据）、性能与恢复；
- 无障碍（VoiceOver/Dynamic Type 系统性核查）、iPad 布局打磨；
- 分发通道定型（Ad Hoc / TestFlight 取决于签名材料）。

## 2026-12 — Android / Windows 兼容客户端

状态：**planned**（依赖 iOS 与服务器先通过 2026-11 稳定性验收）。

- Android：Capacitor 封装现有 Web；
- Windows：Tauri 薄壳复用 Web/PWA；
- 两者均复用同一套 Web UI 与 `/api/v1` 契约，不新建原生业务层。

## Next（候选，立项由用户批准的 spec 决定）

- iOS 阅读体验细节（正文排版、图片加载策略、长文性能）；
- Agent 消息 / RAG 端点的 Web 侧本地 interface 迁移到生成 schema 别名
  （response_model 已补齐，剩余为 Web 消费端重构）；
- 剪藏/快照阅读体验打磨；
- 来源运维 UI 的 J4 类合并契约回归排查（ny1/nx1 批次）。

## Explicitly deferred / rejected {#deferred}

- WebDAV vault、Bergamot 本地翻译（无中文模型）、外部向量库服务
  （sqlite-vec 单文件已够）、多模型自动路由；
- 多租户形态、公共互联网硬化（邀请制小规模多账户与默认关闭的可选
  公开注册已实现，见 [architecture](/architecture#accounts)；对公网
  开放前的加固仍不在范围内）；
- PWA Push / 后台同步（app-shell 离线缓存已实现；APNs、Widget、
  Share Extension、Spotlight、App Intents 等原生系统集成按
  2026-10/11 路线图推进，未在 iOS 首版范围）；
- Folo 产品克隆、社区/社交、算法推荐、公开 Profile、奖励经济；
- 全平台原生客户端（Android/Windows 不做原生，见客户端矩阵）；
- OAuth；
- Kubernetes、Redis / Celery（除非真实压力证明）；
- BFF 任意 Docker 管理（未来服务控制必须走窄 allow-list 边界）；
- 在 SQLite 复制 FreshRSS RSS 数据库（搜索投影除外——派生、可重建，
  见 [architecture](/architecture#search)）。

## 验收原则

- 用户无需日常进入 FreshRSS / RSSHub；原生 RSS 和 RSSHub Feed 都可
  发现、添加和阅读；
- read / starred 与 FreshRSS 一致（set 语义；打开不自动标读）；
  iOS/Web 双端修改后另一端刷新可见相同状态；
- 主题与阅读偏好可用且可持久化；AI 可关闭、未配置时诚实呈现、失败
  不影响阅读；
- 手机可舒适使用；加载/空/错误状态完整；服务重启后数据存在；
  backup / restore 经过真实演练；
- DOMPurify 边界（Web）与 iOS WKWebView 沙箱边界
  （JS 禁用 + CSP + 导航策略）行为回归测试保持绿色；
- 新 Agent 只读 Git 仓库（AGENTS.md → 相关 docs → 源码/测试）即可
  理解项目。
