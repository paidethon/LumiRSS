---
layout: home

title: LumiRSS
titleTemplate: false

hero:
  name: LumiRSS
  text: Your information. Your reader.
  tagline: 自托管 · RSS · AI · 多账户 · Source-first
  actions:
    - theme: brand
      text: 快速开始
      link: /getting-started
    - theme: alt
      text: 部署与运维
      link: /operations
    - theme: alt
      text: GitHub
      link: https://github.com/paidethon/LumiRSS

features:
  - icon: 🏠
    title: 自托管
    details: 一条命令部署到自己的服务器。Caddy + FastAPI BFF + FreshRSS + RSSHub，预构建镜像、自动 TLS、健康检查、一键回滚。
    link: /operations
    linkText: 部署手册
  - icon: 📖
    title: 阅读与订阅
    details: 统一时间线、深度排版定制（字体/背景/分页/中文排版）、显式已读与收藏、稍后读、网页快照。
    link: /usage#reading
    linkText: 使用指南
  - icon: 🗂️
    title: 信息整理
    details: 全局搜索、工作区、标签与图谱、批注笔记、阅读队列、保存的搜索视图（可订阅 Atom）。
    link: /usage#organize
    linkText: 整理与搜索
  - icon: ✨
    title: AI 可选
    details: 摘要 / 翻译 / 文章对话 / TTS / 语义检索 RAG / Agent 工作台——自备 OpenAI 兼容端点，未配置时诚实降级，永不阻塞阅读。
    link: /usage#ai
    linkText: AI 功能
  - icon: 👥
    title: 多账户
    details: 邀请制多账户：一次性限时邀请、自选账号激活、FreshRSS 账号池原子分配，每个账号数据完全隔离。
    link: /operations#member-admin
    linkText: 成员管理
  - icon: 🔒
    title: 数据可控
    details: 本地 + WebDAV 备份、两步恢复、数据导出、隐私中心；secrets 服务端 write-only，上游凭据永不下发浏览器。
    link: /operations#backup-restore
    linkText: 备份与恢复
---

<div class="lumi-home-docs">

## 文档导航

| | |
|---|---|
| **[快速开始](/getting-started)** | 一条命令自托管；首次登录；邀请成员；本地开发环境 |
| **[使用指南](/usage)** | 阅读、订阅与九类来源、整理与搜索、AI、账户与数据控制 |
| **[部署与运维](/operations)** | 部署 / 升级 / 回滚 / 备份恢复 / 成员与池 / 健康检查 / 排障 |
| **[配置参考](/configuration)** | 全部配置键、默认值与安全语义的唯一权威 |
| **[架构](/architecture)** | 数据流、边界、数据归属、账户隔离、搜索、安全边界 |
| **[设计系统](/design-system)** | 视觉语言、tokens、组件架构、响应式与可访问性 |
| **[开发指南](/development)** | 测试与 CI、生成物与复用边界、文档治理、发布检查 |
| **[Roadmap](/roadmap)** | 接下来做什么、明确不做 |
| **[上游对照](/upstreams)** | FreshRSS / RSSHub 能力覆盖与委托边界 |

</div>
