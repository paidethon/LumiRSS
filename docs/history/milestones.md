# Milestone History

> LumiRSS 已完成里程碑的归档索引。每个里程碑的完整 spec、验收清单与过程
> 记录已从工作区移除，可在 Git 历史（`git log --diff-filter=D -- docs/milestones/`）
> 中找回。正常开发无需预读本文。

## 里程碑总表

| 里程碑 | 标题 | 状态 | 交付要点 |
|---|---|---|---|
| 0000 | Project Reboot | Completed | 仓库收敛为最小清晰基线：采用 PRD v5.0，重写核心文档，删除旧脚手架（旧历史保留在 `archive/pre-wsl-reset` 分支） |
| 0001 | FreshRSS Development Environment | Completed | docker compose 启动 FreshRSS 并完成浏览器初始化，经 ClientLogin 实读订阅列表，验证数据源链路可用 |
| 0002 | BFF & FreshRSS Adapter | Completed | FastAPI BFF 骨架 + `FreshRSSAdapter`（ClientLogin），`GET /api/v1/feeds` 返回真实订阅 |
| 0003 | Entry Read Path | Completed | 文章列表 + 单篇详情（opaque `entryRef`、`contentText` 纯文本） |
| 0004 | Entry State, Filters & Pagination | Completed | read/star 写入（set 语义）、all/unread/starred/feed 过滤、FreshRSS continuation → opaque cursor 分页 |
| 0005 | Web Shell | Completed | 建立真正的 React Web 应用（TanStack Query + Zustand + Vite），展示 Feed 与文章列表 |
| 0006 | Reader | Completed | 真实阅读窗格：DOMPurify 净化渲染 + 显式 read/star 控件 |
| 0007 | Mobile & PWA | Completed | 响应式移动布局（抽屉导航、列表→全屏 Reader）+ 可安装 PWA manifest（无 Service Worker） |
| 0008 | RSSHub Source Expansion | Completed | dev compose 加入 RSSHub，以 IT之家热榜验证「非 RSS 来源 → RSSHub → FreshRSS → Reader」扩展路径 |
| 0009 | UI Reboot & Reference Lab | Completed | Lumi 设计体系（Lumi Mist 主题、语义 token、共享 UI primitives）整体替换临时视觉；BFF 零改动 |
| 0010 | Settings Center & Adaptive Shell (+0010a) | Completed | 声明式设置中心 + 自适应外壳（三栏拖拽/折叠、移动端 Tab 导航）；0010a 补设置扩展与阅读样式（自定义 CSS 等）并修复移动端设置布局 |
| 0011 | Mobile UI Five-Screen Alignment | Completed | 移动端首页/订阅/搜索/收藏/侧边栏五屏对齐参考图；建立 AppSection 一级导航模型 |
| 0012 | Reader Style Deep Customization | Completed | 阅读器深度排版自定义：版本化设置 + 安全内容呈现管线（transforms → DOMPurify）+ Reader CSS 变量 |
| 0013 | Unified Subscription Center | Completed | Lumi 内完成添加/预览/分类管理/退订/OPML 导入导出，无需打开 FreshRSS UI（`FreshRSSControlAdapter`） |
| 0014 | Source Discovery & RSSHub Integration | Completed | 「网站 URL 发现 RSS」与「RSSHub 路由配置」两类入口 → 预览 → 订阅；订阅结果仍归 FreshRSS |
| 0014a | UI Acceptance & Navigation Consistency | Completed | 修复 0014 真实验收发现的 UI 缺口：桌面添加来源入口、移动收藏→全屏 Reader、stale planned 标签、Playwright 实机验收 |
| 0015 | AI Foundation, Summary & Lumi SQLite Foundation | Completed | 激活 lumi.sqlite（版本化 migrations）+ 单一 OpenAI-compatible provider + 确定性缓存身份的文章摘要（GET 只读缓存、POST 才生成） |
| 0016 | Translation & AI Conversation | Completed | 文章翻译（原文/译文切换、缓存）+ 文章上下文 AI 对话（历史持久化），复用 0015 的 provider/缓存/持久层 |
| 0017 | Reader Power UX & Unified Settings | Completed | 连续排版控件（字号/行高/段距/宽度/边距）+ Reader Aa 面板与设置中心共享同一设置真源 + 便携设置服务端持久化与迁移 |
| 0018 | Production, Operations & Backup | Completed | 生产部署拓扑（Caddy + 持久卷 + healthcheck）、schema 驱动 RSSHub 控制中心、FreshRSS 真实依赖诊断、备份/WebDAV/分阶段恢复 |
| 0019 | MVP Stabilization & Release | Completed | Playwright E2E 体系、axe 可访问性门禁、性能预算、CI 完整化、升级/回滚与灾难恢复演练、operator 文档与 release notes |
| 0020 | MVP Release Remediation | Completed | 按优先级以小步、带回归测试的改动修复发布审计缺陷（备份恢复完整性、前端回归、可访问性、CI/operator、文档真实性），不重写架构 |
| — | Post-0020 settings control-plane maintenance（2026-09-05，无编号） | Completed | AI profiles + purpose 映射、「备份与恢复」并入「数据控制」、诚实 RSSHub 控制链、版本溯源 |

里程碑之后的合并（均无独立里程碑文档，详见 Git 历史）：

- **0021 Security & Operations Hardening**（PR #37）：BFF 内部 token、
  CSP/HSTS、请求体上限、控制面限流、设置冲突语义（409 + re-hydrate）。
- **0022 全局搜索**：FreshRSS 投影之上的派生搜索索引（机制见
  [../explanation/search.md](../explanation/search.md)）。
- **`./lumirss` 生命周期脚本 + GHCR 预构建镜像**：一键 deploy/update/
  backup/restore/doctor/rollback（用法见 [../how-to/deploy.md](../how-to/deploy.md)）。
- **2026-09-13/14 Phase 2 Recovery**：13 个 P0 返工全部 production_verified。
  冻结账本：[../audits/phase2-recovery.md](../audits/phase2-recovery.md)。
- **2026-09-18 夜间批次**：RSS 自动采集修复（FreshRSS `CRON_MIN` 唯一调度
  拥有者）、Agent 桌面全宽布局、GPT 日报（多主题 + token 订阅 Atom）、
  收件量概览/稍后读延后/打印视图/溯源卡/能力页/存储用量/偏好迁移。
- **2026-09-19/20 一百二十项可感知功能批次**：来源管理（新鲜度预警、
  OPML 逐项导入/选择性导出、查重、备注、批量迁移、屏蔽规则、静音列表、
  RSSHub 参数编辑、正文提取策略、导入批次、批量健康检查）、阅读与批注
  （段落链接、对照阅读、阅读预算、批注服务端化与管理器/复习队列、脚注、
  公式、双语关联滚动与导出、外链清单、单源样式、跨设备续读）、搜索与
  知识（筛选构建器、同链聚合、回收站、命中定位/解释、清单导出、视图
  对照、同义词、图谱命名视图与路径、Obsidian 反链）、AI 与交付（输入
  预览、证据定位、版本比较、问答模板、术语命中、草稿审阅、补刊、配额、
  多文问答/对照、来源级 AI 禁用、自测、知识卡片）、维护与隐私（诊断包、
  设置历史撤销、CSS 隔离预览、隐私遮罩、保留策略、备份比较、冲突解决
  界面、版本更新确认、草稿恢复、审计时间线）、接入域（API 来源分页/
  结构预警、地址迁移向导、IMAP 启停、邮件解析对照/过滤规则/历史回填/
  会话串联、Inbox 事件重放/契约试跑/凭据轮换 UI、日报素材池/近期去重）。
  同批安全整改：登录限流按可信代理 XFF 分桶、订阅凭据单向哈希存储。
  完整实现/测试清单见当轮私有验收账本（不入库）。
- **文档考古说明（2026-09-20）**：`docs/research/`（Phase 2 研究与三篇
  研究报告）与 `docs/audits/mobile-liquid-glass-acceptance.md` 已完成
  历史使命删除，Git 历史可恢复
  （`git log --diff-filter=D -- docs/research/`）。

## Releases

- **MVP（0018 + 0019）**，2026-09-05 release-ready，随后经 0020 整改收口。
- 生产 compose：Caddy 统一入口（静态 Web + `/api` 反代），FreshRSS/RSSHub
  仅内部网络；持久卷、healthcheck、日志轮转、资源限额；无 Docker socket；
  FreshRSS 数据只读挂载供一致性备份。
- 单用户访问控制：Caddy Basic Auth（bcrypt，可关闭）；TLS 自动化
  （域名 → Let's Encrypt，localhost → 本地 CA）。
- RSSHub 控制中心：typed allow-list，desired/applied 双态与 restartRequired
  如实标记；secret 写只读、永不回显。
- 备份/恢复：版本化 manifest + 每文件 SHA-256；lumi.sqlite 在线备份 +
  FreshRSS 数据一致性备份；WebDAV 服务器端上传；分阶段恢复（预览 →
  当前状态安全备份 → 显式 `RESTORE` → 执行 → 健康验证）。
- 0019 交付 Playwright E2E、axe 门禁与性能预算冻结、CI 完整化。
- 发布时已知限制（部分已在此后解决）：无全局搜索（现已有，见上）、
  BFF 无结构化日志/关联 ID、BFF 镜像依赖未 pin、web 服务无 healthcheck。
