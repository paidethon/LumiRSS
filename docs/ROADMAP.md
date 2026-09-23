# LumiRSS Roadmap

> What comes next, in order. Completed milestones and release notes:
> [history/milestones.md](history/milestones.md)。功能状态以本文与
> [explanation/architecture.md](explanation/architecture.md) 为准。

## Current state（2026-09）

- **MVP（0000–0020）与 Phase 2 knowledge workbench 均已合入 main**：
  Library 域（书签/剪藏/快照）、工作区与服务端稍后读、收件箱推送来源 +
  统一来源注册表（0021）、API 来源（JMESPath→Atom→FreshRSS）、邮件桥 +
  摘要、Obsidian 只读投影、统一搜索双腿 + 联邦收藏、标签/图谱、低内存
  RAG、Agent 工作台（服务端强制审批）。
- **2026-09-18 夜间批次已合入 main**：RSS 自动采集修复（FreshRSS
  `CRON_MIN` 为唯一调度拥有者，dev/prod compose 均已接线）；Agent 工作台
  桌面全宽布局契约（FULL_WIDTH_SECTIONS）；GPT 日报（多主题配置 + 选材
  预览 + 单源配额 + 来源白名单 + token 订阅 Atom，0026/0027 迁移）；
  收件量概览 / 稍后读延后（0029）/ 完整度提示 / 打印视图 / 溯源卡片 /
  能力可用性页 / 存储用量 / 偏好迁移 / 备份清单计数 / 邮件桥取消订阅
  匹配修复。
- **Phase 2 recovery（2026-09-13/14）已完成并部署生产**：13 个 P0 返工
  全部 `production_verified`，Gate 8 smoke 15/15。完整账本（已冻结）：
  [audits/phase2-recovery.md](audits/phase2-recovery.md)。
- **2026-09-19/20 一百二十项功能批次**：来源管理（新鲜度预警、OPML 逐项
  导入/选择性导出、重复订阅检查、来源备注、批量分类迁移、服务端屏蔽
  规则、静音列表、RSSHub 参数编辑、按源正文提取、导入批次追踪、批量
  健康检查）、阅读与学习（段落定位链接、对照阅读、阅读预算、批注
  服务端化+跨篇管理器+复习队列、脚注往返、公式渲染、双语关联滚动/
  手工修订/对照导出、外链清单、单源样式覆盖、跨设备续读、远程图片
  隐私、表格排序与公式注入防护、enclosure 播放器、追踪参数清理、
  Markdown 批量入库）、搜索与知识（筛选构建器、同链聚合、Library
  回收站、命中定位/解释/清单导出、视图对照与固定、私有 Atom 订阅、
  同义词、图谱命名视图/路径查找、Obsidian 反链断链、作者聚合、疑似
  重复审核、手工关联、独立笔记）、AI 与交付（输入预览、证据定位、
  版本比较、问答模板、术语命中、日报草稿审阅/缺失补刊/素材池/近期
  去重、调用配额、多篇问答/观点对照、来源级 AI 禁用、阅读自测、知识
  卡片、AI 任务中心）、维护与隐私（诊断包、设置撤销、CSS 隔离预览、
  隐私遮罩、保留策略、备份比较、冲突解决界面、版本更新确认、草稿
  恢复、审计时间线、会话管理、快捷键自定义、预设设备适用）、接入域
  （API 来源分页/结构预警/试跑强化、地址迁移向导、IMAP 启停+时区
  UI、邮件解析对照/过滤规则/历史回填/会话串联、Inbox 事件重放/契约
  试跑/凭据轮换）。完整清单与逐项测试见当轮私有验收账本（不入库）。
- **安全整改（2026-09-20）**：登录失败限流按可信代理 XFF 最后一跳
  分桶（`LUMIRSS_TRUSTED_PROXY_NETWORKS`，不可信 peer 的 XFF 忽略）；
  订阅/邮件/收件箱/视图/日报五处凭据改单向哈希存储（存量惰性回填，
  旧链接不失效）。
- **NE1 阅读排版批次（2026-09-23，全部设备本地）**：目录章节化阅读
  （章节模式只显示该章 + 浮动章节导航，段落深链自动换章）；分页阅读
  模式（CSS 多栏横向翻页 + 页码指示 + 方向键，位置经既有阅读位置
  锚点重锚）与分页点按翻页区（左右/上下 × 关/小/大；链接/选区/
  横向滚动元素不翻页）——「按屏翻页」开关由此演进为「阅读模式」
  select；阅读标尺增强（宽度/深浅三档持久化 + 全键盘操作）；中文排版
  细化（首行缩进按块类型扩展到列表/引用 + 避头尾，CSS-only）。
- **邀请制多账户（0.2.0）**：运营者经 `/admin` 发一次性限时邀请，受邀者
  在 `/activate` 激活独立账号（订阅/阅读状态/资料库/AI/设置/FreshRSS
  绑定按账号隔离）；FreshRSS 账号池预建与原子分配；数据层拆分为控制库
  + 每用户库（[ADR 0005](decisions/0005-invite-multi-account.md)）。
  运营者操作见 [how-to/invite-members.md](how-to/invite-members.md)。
- 明确不做：WebDAV vault、Bergamot 本地翻译（无中文模型）、公开注册 /
  多租户形态、外部向量库服务（sqlite-vec 单文件已够）。

## Next（候选，立项由用户批准的 spec 决定）

- BFF 结构化日志与关联 ID（发布时已知限制，operations/status 已含延迟
  与错误分类）；
- BFF 生产镜像依赖 pin；web（Caddy）服务 healthcheck（发布时已知限制）；
- Agent 消息 / RAG 状态端点补 `response_model`（OpenAPI 未收录，
  Web 侧暂以本地 interface 对照维护）；
- 剪藏/快照阅读体验打磨；
- CI 增加 Playwright 全量 journey 门（boot e2e compose 栈；当前 CI 只跑
  静态冒烟 1/32）。

## Explicitly deferred / rejected

- 公开注册 / 多租户、公共互联网硬化（邀请制小规模多账户已实现；
  对公网开放前的加固仍不在范围内）；
- PWA Push / 后台同步（app-shell 离线缓存已实现；其余明确延后）；
- Folo 产品克隆、社区/社交、算法推荐、原生移动 App；
- BFF 任意 Docker 管理（未来服务控制必须走窄 allow-list 边界）；
- 在 SQLite 复制 FreshRSS RSS 数据库（搜索投影除外——派生、可重建，
  见 [explanation/search.md](explanation/search.md)）。
