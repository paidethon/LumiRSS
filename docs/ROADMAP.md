# LumiRSS Roadmap

> What comes next, in order. Completed milestones and release notes:
> [history/milestones.md](history/milestones.md)。功能状态以本文与
> [explanation/architecture.md](explanation/architecture.md) 为准。

## Current state（2026-09）

- **可观测性已落地**：BFF 结构化访问日志（E01）、web/Caddy 容器真实
  healthcheck（E06）、GHCR 依赖 digest pin 审计（E07）、CI Playwright
  核心 journey 门（E05——boot 真实 e2e 栈）、backup/restore 闭环演练
  （E08）与 upgrade/rollback 真实进程演练（E09，数据零丢失）；
- **预编译发布管线修正**：BFF 镜像携带运维脚本（set-password /
  RSSHub config/apply），compose 镜像路径与 publish-images 推送路径
  一致——三处缺陷均在生产部署实测中发现并修复；

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
- **NW1 阅读辅助批次（2026-09-25，全部设备本地）**：附件下载队列
  （enclosure 白名单类型（音频/视频/图片/PDF/EPUB；脚本/可执行拒绝）
  加入本机下载队列，名称/大小/进度/取消/重试一次，200MB 上限 LRU 逐出
  并诚实提示，文件名净化保留 CJK，元数据 localStorage、二进制不落
  localStorage）；按源媒体仅手动加载（图片/视频/音频先进 DOM 前摘除
  加载属性——初始渲染零外部媒体请求，点击占位只加载该一个元素，按
  feedUrl 记忆）；触控操作练习区（设置「手势」区 3 张示例卡复用与文章
  列表完全相同的手势调度器，动作只记练习台账，绝不发起真实变更）；
  结构视图（标题大纲 h1–h6 文档序 + 链接/图片/表格/代码块/批注计数，
  sr-only/aria-hidden 子树剔除，标题可跳转，打开状态设备本地）；选词
  词典卡（单个词选区弹卡，词典端点由用户自配（缺 {word} 占位符视为
  未配置），未配置/离线诚实提示且零请求，查询只发送所选单词，发音走
  既有朗读链路）；纯键盘阅读定位（Alt+↑/↓ 类别内循环、Alt+Shift+↑/↓
  切换标题/链接/代码块/批注，指示 chip，输入框/IME/模态守卫，只定位
  不改已读状态，设置开关默认关）。
- **邀请制多账户（0.2.0）**：运营者经 `/admin` 发一次性限时邀请，受邀者
  在 `/activate` 激活独立账号（订阅/阅读状态/资料库/AI/设置/FreshRSS
  绑定按账号隔离）；FreshRSS 账号池预建与原子分配；数据层拆分为控制库
  + 每用户库（[ADR 0005](decisions/0005-invite-multi-account.md)）。
  运营者操作见 [how-to/invite-members.md](how-to/invite-members.md)。
- **公开注册（默认关闭）已实现**：实例级开关
  `allow_public_registration` 存控制库（迁移 0089），升级与全新安装
  均保持关闭，由 admin 经注册策略 API 显式开启；注册只创建 member，
  FreshRSS 池原子分配、空池诚实 pending，服务端强制、关闭时统一 403
  不构成用户名 oracle（[ADR 0006](decisions/0006-public-registration.md)）。
- **BFF 结构化访问日志已实现**：每请求一行 JSON（request_id/路由/
  status/duration_ms/actor），`LUMIRSS_ACCESS_LOG=off` 可静默，绝记
  query string / 请求体 / header。
- **来源管理增强（N012/N013/N015）**：退订影响预览（只读聚合工作区
  引用/看板状态/RSS 书签/批注/投影未读/收件箱规则命中；DELETE 支持
  `keep_artifacts`：true 保留工件（冻结 ref 以 stale 卡片呈现）、false
  显式清理、缺席保持 legacy）；来源改名服务端真源（`source_aliases` +
  每 feed 20 条改名历史含上游名快照，上游改名永不覆盖别名，展示服务端
  赢、localStorage 只作离线回退）；来源分时静音（每周循环窗口
  `mute_windows`，与 hiddenUntil/showFrom 同消费点——只影响通用时间线，
  抓取/搜索/阅读不受影响）。
- **Agent 任务运维批次（N164–N170，迁移 0112/0113/0114）**：任务暂停与
  续接（工具间检查点冻结 {completedSteps, pendingPlan}，续接复用
  transcript 已执行结果绝不重复副作用；暂停期间过期的批准在续接时要求
  重新确认）；线程级任务预算 {maxToolCalls, maxTurns}（budget_exhausted
  终态 + 消耗摘要，token 未上报时诚实显示 unknown）；工具执行时间线
  （durationMs / ≤80 字脱敏参数摘要 / resultType）；批准内容修改
  （修订 → 新批准行绑定新 args_hash，旧行 superseded、take → 410）；
  失败步骤单独重试（写工具幂等键 args_hash+turn，成功写重放返回缓存
  结果）；任务结果差异撤销（add_to_workspace / add_tag 前后快照，
  对象被改动过 → 冲突报告跳过；不支持工具 → 422）；任务配方（名称/
  输入/工具白名单/范围，白名单服务端强制执行，运行 = 新会话 + 首条
  消息 + 运行前预览）。
- 明确不做：WebDAV vault、Bergamot 本地翻译（无中文模型）、多租户形态、
  外部向量库服务（sqlite-vec 单文件已够）。

## Next（候选，立项由用户批准的 spec 决定）

- Agent 消息 / RAG 端点的 Web 侧本地 interface 迁移到生成 schema 别名
  （response_model 已补齐，剩余为 Web 消费端重构）；
- 剪藏/快照阅读体验打磨；
- CI Playwright journey 门扩展：AI journey（J4）因 AI purpose-profiles
  契约漂移暂不在门内，spec 待重写；
- 来源运维 UI 的 J4 类合并契约回归排查（ny1/nx1 批次）。

## Explicitly deferred / rejected

- 多租户形态、公共互联网硬化（邀请制小规模多账户与默认关闭的可选公开
  注册已实现，见 [ADR 0006](decisions/0006-public-registration.md)；
  对公网开放前的加固仍不在范围内）；
- PWA Push / 后台同步（app-shell 离线缓存已实现；其余明确延后）；
- Folo 产品克隆、社区/社交、算法推荐、原生移动 App；
- BFF 任意 Docker 管理（未来服务控制必须走窄 allow-list 边界）；
- 在 SQLite 复制 FreshRSS RSS 数据库（搜索投影除外——派生、可重建，
  见 [explanation/search.md](explanation/search.md)）。
