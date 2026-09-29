# LumiRSS 2.0.1 · R2｜持续执行与真实交付任务书

> 交付目标：累计 **400 项真实修复、400 项可感知新增、10 项架构整改**，新增并实际应用 **20 Skills、10 MCP、10 Agent 定义**，完成文档与结构精简，将同一受测预构建产物更新到 `47.100.64.202`。  
> 本任务书是给 ZCode 的执行指令，不是已经完成的安装、测试或部署报告。研究日期：2026-09-28。

## 0. 现在开始做，而不是再做一轮“工具预备”

工作区沿用 `/home/zephyr/projects/LumiRSS`，以现场实际路径为准。先阅读本文件和 `START.md`，按领域读取 `TASKS-800.md` 与 `tasks.json`。原 `LumiRSS-2.0.1-ZCode-task.md` 只用于追溯旧 ID；发生冲突时，本 R2 的交付、计数和安全规则优先。用户原有安全规则仍有效。

本轮不是“只安装工具，然后结束”。原 prep-only 指令曾明确要求安装后停止，那次停止符合指令；现在该阶段已经过去。安装失败、某新角色尚未注册，都不能成为停止全部业务工作的理由。不得重新安装全部旧工具以制造进度，不得重复新建版本文件或空台账。

“升级为 400+400”是本版本累计目标：旧编号 001…200 保留，新编号 201…400 补充。接管已做的真实工作，审查后复用，不从零开始。新增工具是另一套真实上游定义，不能把旧工具改个 lumi2 前缀算新工具。

版本仍以 2.0.1 为目标。在执行现场核实 tag/Release 是否已正式发布：未发布则继续既有 release/2.0.1；已发布且不可变则不得覆盖或移动 tag，把后续修改留在后续候选版本并报告版本冲突。不得根据文件名推断已经上线。

你有权限修改本项目、测试、提交、推送、按仓库规则合并及部署。不得绕过分支保护、权限、平台预算、用户暂停和安全控制；这些限制不允许通过另开进程规避。

## 1. 已有证据与首轮接管

### 1.1 日志支持的事实，不扩大解释

用户附件《粘贴的文本 (1)(10).txt》记载：

| 观察 | 接管动作 |
|---|---|
| 宣称 45/45，同时只核对到 11/20 个 Agent，其余仍安装 | 拆分“磁盘存在、注册可用、已派发、实际产生结果”，分别逐项核验。 |
| 只成功加载一个 Skill，便推论全部 Skills 可调用 | 不能外推；沿用有效安装，给实际被应用的每个 Skill 绑定任务和产物。 |
| 有去重任务派发失败，随后仍把四个都算运行 | 查询真实任务 ID、状态、工作区与输出；失败派发不占运行槽。 |
| release/2.0.1 据称有 99c9ba6、41ee494、b6f7343、0d34f77 | 用 Git 验证是否存在、所在分支、变更及测试，不盲目 cherry-pick 两次。 |
| 最后阶段台账为 7 done / 1 in_progress / 402 candidate | 这是旧日志快照，不是现在进度；重新核验，不复制为当前成绩。 |
| root SSH 已成功；生产据称在 /opt/lumirss，2 CPU、1.6 GB 内存、外部 Caddy，运行 2.0.0 | 视为已解决过的历史身份与拓扑线索，现场重新只读确认，不再猜 14 个用户名。 |
| 先说备份恢复通过，最后承认 CLI 裸 tar 活库，FIX-192 判断过早 | 重开 FIX-192。SQLite integrity_check 成功不证明业务时点一致，也不证明完整应用恢复。 |

日志定位：工具矛盾约 254–257 行；SSH/生产约 287–319、366–367 行；三个架构提交约 369–376 行；备份判断推翻约 394–405 行。不要在公共仓库上传整份聊天和终端日志。

本任务包编写时公开 main 的 VERSION 和 web package 仍为 2.0.0；公开 CLI 有备份失败继续升级、裸 tar 备份、仅停止 BFF 后恢复、离线导出镜像名与发布流程不一致等待修链路。公开 main 不等于本地 release 分支，也不等于生产；现场须记录三者各自 SHA/digest。来源见文末 [P1]–[P4]，不能把网页缓存当实时部署证据。

### 1.2 保住现场

检查 `git status`、分支、worktree、未提交改动和实际子任务。重点接管：
- `/home/zephyr/projects/LumiRSS-201/fix-a`、`fix-b`、`fix-c`。
- 已有 `.work/2.0.1/tools-ready.md` 和 `/home/zephyr/.lumi-201-ledger/`。
- `.work/2.0.1/` 下既有脱敏证据，而不是新建 phase2、phase3 或十套报告目录。

选择一个既有台账目录作为唯一权威位置，另一处只放简短指向说明。私人原始证据不搬进 Git；公共仓库只保留必要、已脱敏的结果索引。未提交文件先辨认所有权，不能 reset、clean、强制 checkout、覆盖或删除别人的改动。

首轮就开始一个有实际影响的修复与测试。优先顺序为：备份/升级安全链路 → 账户隔离/登录/管理 → 阅读核心和 UI → 其他修复与新增。工具维护和候选去重用独立轻量任务推进，不能所有人等待安装结束。

## 2. 持续执行协议：避免“汇报一次就不动了”

使用 ZCode 官方 Goal，而不是靠一句“至少干八小时”。已有目标用 `/goal replace` 更新；处于暂停状态时使用 `/goal resume`。手动 Stop 会暂停 Goal；预算、用户暂停和权限不会被本任务书覆盖。[Z1]

每轮执行闭环：
1. 读取真实任务、进程和台账状态，找出最优先、依赖已满足的任务。
2. 把小批独立任务分给有明确文件所有权的 Agent；保留一个可推进的协调者任务。
3. 主协调者工作时检查已完成通知，及时合入、测试并回写结果，不只轮询或写进度散文。
4. 批次合入后运行受影响测试和核心烟测；失败立即定位，不把失败累积到最后。
5. 还有可安全推进的未完成项就进入下一批；只有完整交付或真实硬阻塞才给终局报告。

### 2.1 真实并行，不用角色数量冒充并行上限

使用平台实际允许、工作区资源能支持的最大有效并行。20/10 是工具或定义数量，不是并发数，也不虚构 `max_agents=20` 参数。截图的进程数字不证明平台永久上限。

为每个运行任务记录实际 handle、角色、ID 范围、worktree、文件域、开始时间、最近产物、测试资源和状态。没有返回 handle 的派发不得算运行。进程退出、调用失败和仍有活动的长测试分开判断；发现停滞先取证，不按固定几分钟就强杀。

根据现场可用内存、浏览器实例和测试负载调整：轻量只读审查可以多开；前端构建、完整 E2E、数据库迁移、生产部署分别有资源锁。不能仅因“4.4GB 可用”永久拍定所有 Agent 只能 3 个，也不能 9 个浏览器把 WSL 打满。报告当前瓶颈，不捏造平台限制。

公共设计令牌、路由入口、OpenAPI、迁移编号、锁文件和发布流水线各有一个写入所有者。子 Agent 不再嵌套派发；需要协作交给主协调者。不得让多个 Agent 修改同一个 SQLite 测试库或共享浏览器 profile。

### 2.2 等待与中断

主协调者只有真实已启动的原生后台任务，才能说“后台运行”。不能在普通最终回复中许诺未来会自己继续。优先留在 Goal 循环内接收与处理完成事件；必须结束一轮时确认 Goal 和任务仍处于可续跑状态。

停止原因必须归类为：用户暂停、预算、权限/凭据、主机身份核验失败、安全风险、工具/进程错误，或真正完成。截图“已停止”本身不能用来推断原因。不得擅自恢复用户主动暂停。

上下文压缩或环境重启后，从唯一 checkpoint 恢复：当前 SHA、已合入 ID、运行句柄、未完成批次、硬阻塞、下一条可执行动作。不要重读所有聊天、重新安装全套工具或重新写一遍计划。

自定义新 Agent 的注册可能需要新会话；遵循实际版本官方说明。若本会话尚不可原生注册，先让已加载的内置/旧 Agent 执行同一职责，记录“临时执行、未原生验证”；不能谎报新定义已调用，也不能因此停掉可完成的修复。平台没有自动会话交接能力时，保存可直接恢复的 checkpoint，明确一次最小的重开动作，而不是假装能自动重开。

## 3. 验收与计数：不让任务表代替软件

`TASKS-800.md` 已完整列出 800 个 ID。默认 status=candidate；不是全部已确认缺陷，也不是全部已证实的新功能。

**修复工作流：** candidate → reproduced → implementing → review → tested → accepted。先有具体失败条件，再有修复和回归。只新增一个通过测试、检查配置本来正确、整理一次目录，都不是修复。共享根因的一次修正只能占一个 FIX；剩余候选保留并换成真正独立问题。

**新增工作流：** candidate → novelty_verified → implementing → review → tested → accepted。提交前写明用户入口、以前不能完成什么、现在可以完成什么、数据归属和负例。一个功能的按钮、接口、数据库字段、设置开关、测试不能拆算五项。

原功能已存在或原问题不存在，分别登记 ALREADY_EXISTS / BASELINE_OK；留原文和证据后在同 ID 登记一换一替代。QA 对全 800 项和历史已发布功能做语义去重。不能把 2.0.0 的普通账号、翻译、基础 RAG、旧 Phase2 页面换皮算新增。所有替代必须在实现前登记，不到收尾临时补名字。

同一代码提交可解决多个真正独立问题，但每项要有独立失败条件、用户结果与验收；不是强制 800 个提交。架构项可关联 FIX，但单独报告架构 10 项，不把它们再加进 800 个结果。

只有主协调者可把受审证据写入权威台账，子 Agent 输出紧凑交接：
`task_ids / actual_commit / changed_paths / command+cwd+exit_code / before+after evidence / unresolved / next action`。
禁止自然语言含“完成”就自动改 accepted。接受前审查者不能是该实现的作者。

测试日志须记录执行目录、开始/结束、代码 SHA、发现与实际执行用例数、退出码和报告路径；管道输出要保留原退出码。完整日志保留在受控目录，给模型只返回摘要及失败范围。截图须有视口、路由、身份类别和对应 SHA，不能用设计稿替代实际页面。

附带 `check_plan.py` 只验证任务包数量、ID 和来源结构，**不证明完成**。真正交付门禁必须读取真实提交、测试报告、工具调用、发行物和生产核验；不能只数自己写的 accepted 字段。

## 4. 新工具：按任务应用，不再把安装当成绩

现有 frontend-design、impeccable、ui-ux-pro-max、设计/交互/a11y Skills 与 Playwright、Chrome DevTools、Context7 等继续复用。截图里的 context7/fetch/playwright 与 lumi-* 对应项有能力重叠，先选本任务的规范实例；不擅自删除或关闭用户自用配置，不重复计算。

本轮另选 20 个不同 Skill 入口、10 个 MCP 和 10 个新来源 Agent 定义。来源表是核查后的入口，不是本机已安装证明。固定可固定的 release/commit，保存包摘要、许可和实际引用的 scripts/references；禁止只放一页改名说明或空壳。

**流行度的含义：** 公开 stars 是仓库关注量，不能称作某个 Skill/MCP 的实际使用人数。Storybook MCP 仍为 preview，Git/Memory 是官方参考实现；不能把十项全部宣传成生产成熟。它们只用于隔离的开发环境。需要收费或新增外部账户的能力不擅自购买。

安全适配先于运行：读入口和将要执行的脚本；不批量执行上游整仓安装器，不接管其他 IDE 配置。保留许可证和改动说明。Trail of Bits 当前是 CC-BY-SA-4.0；Serena 按组件许可，不得误记为全 MIT。研究链接会变化，安装前以锁定提交中的 LICENSE 为准。

把每个工具的“已研究、已安装、已注册、已连接/加载、已执行、已应用到结果”分开记录。只成功一次 initialize、HTTP 200 或一个 Skill probe，不等于整套可用。远端滚动服务只能记录端点、实际协议/schema 和时间，不能编造可锁定的服务器 commit。


### 4.0 启用范围与原生调用检查

ZCode 官方说明：每轮会注入全部已启用 Skills 的名称与描述摘要；元数据超出共享预算时会退化为只有名称，自动触发率下降。安装更多不等于实际用得更多。本轮二十个新 Skills 应全部完成实际应用，但不要求与旧技能、所有内置插件在每个批次同时启用。[Z4]

按业务批次建立精简的调用清单，明确指定需要的技能；调整仅限本项目或本轮新建条目，不擅自关闭用户全局其他配置。停用的技能不能被调用，需要它时先启用并验证。description 用短而具体的触发条件，不把整份规则塞进 frontmatter，也不改写上游语义来缩字。检查子 Agent 的真实工具白名单包含技能调用工具；列表可见不代表子 Agent 有调用权限。[Z4]

当前开发工作区位于 WSL，确认技能实际安装在执行 Agent 所在的 WSL 环境，而非只有 Windows 设置页可见。项目需要的开发工具可安装到该开发环境；不要为了“同步远端”把全部技能、MCP 或开发依赖复制到生产服务器。[Z4]

### 4.1 二十个新 Skills（精确入口与用途）

| ID / 安装别名 | 上游实际入口 | 本项目应用 |
|---|---|---|
| SKILL-01 · `lumi2-systematic-debugging` | [obra/superpowers · skills/systematic-debugging/SKILL.md](https://github.com/obra/superpowers/blob/main/skills/systematic-debugging/SKILL.md) | 定位根因、最小复现；用于账户、备份和状态竞态，不随机改十处。 |
| SKILL-02 · `lumi2-test-driven-development` | [obra/superpowers · skills/test-driven-development/SKILL.md](https://github.com/obra/superpowers/blob/main/skills/test-driven-development/SKILL.md) | 为真实缺陷建立失败→修复→通过的证据；不得删除已有代码来表演 TDD。 |
| SKILL-03 · `lumi2-verification-before-completion` | [obra/superpowers · skills/verification-before-completion/SKILL.md](https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md) | 每次宣告通过前检查当前提交上的真实测试、退出码与产物。 |
| SKILL-04 · `lumi2-using-git-worktrees` | [obra/superpowers · skills/using-git-worktrees/SKILL.md](https://github.com/obra/superpowers/blob/main/skills/using-git-worktrees/SKILL.md) | 接管现有 fix-a/b/c，建立文件所有权与隔离测试目录，不复制秘密。 |
| SKILL-05 · `lumi2-dispatching-parallel-agents` | [obra/superpowers · skills/dispatching-parallel-agents/SKILL.md](https://github.com/obra/superpowers/blob/main/skills/dispatching-parallel-agents/SKILL.md) | 只并行独立任务；由主协调者派发并收集实际句柄。 |
| SKILL-06 · `lumi2-requesting-code-review` | [obra/superpowers · skills/requesting-code-review/SKILL.md](https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/SKILL.md) | 按真实 diff 提交独立审查；连同同目录 code-reviewer.md 等引用资源安装。 |
| SKILL-07 · `lumi2-tailwind-design-system` | [wshobson/agents · plugins/frontend-mobile-development/skills/tailwind-design-system/SKILL.md](https://github.com/wshobson/agents/blob/main/plugins/frontend-mobile-development/skills/tailwind-design-system/SKILL.md) | 统一 Tailwind 4 令牌、组件尺寸、状态与主题；沿用 Base UI。 |
| SKILL-08 · `lumi2-react-state-management` | [wshobson/agents · plugins/frontend-mobile-development/skills/react-state-management/SKILL.md](https://github.com/wshobson/agents/blob/main/plugins/frontend-mobile-development/skills/react-state-management/SKILL.md) | 清楚区分 TanStack Query 服务状态与 Zustand 界面状态。 |
| SKILL-09 · `lumi2-e2e-testing-patterns` | [wshobson/agents · plugins/developer-essentials/skills/e2e-testing-patterns/SKILL.md](https://github.com/wshobson/agents/blob/main/plugins/developer-essentials/skills/e2e-testing-patterns/SKILL.md) | 消除 J2/J4 数据依赖和契约漂移，隔离账号与测试资源。 |
| SKILL-10 · `lumi2-python-testing-patterns` | [wshobson/agents · plugins/python-development/skills/python-testing-patterns/SKILL.md](https://github.com/wshobson/agents/blob/main/plugins/python-development/skills/python-testing-patterns/SKILL.md) | FastAPI、SQLite、后台任务的异步集成与失败注入测试。 |
| SKILL-11 · `lumi2-vite` | [antfu/skills · skills/vite/SKILL.md](https://github.com/antfu/skills/blob/main/skills/vite/SKILL.md) | 检查项目实际 Vite 版本、分包和资产路径；不强制升级框架。 |
| SKILL-12 · `lumi2-vitest` | [antfu/skills · skills/vitest/SKILL.md](https://github.com/antfu/skills/blob/main/skills/vitest/SKILL.md) | 组件与状态测试，检查空测试集、假计时器及未 await 的断言。 |
| SKILL-13 · `lumi2-performance` | [addyosmani/web-quality-skills · skills/performance/SKILL.md](https://github.com/addyosmani/web-quality-skills/blob/main/skills/performance/SKILL.md) | 采集列表、正文与管理页的真实性能剖析，减少无效渲染。 |
| SKILL-14 · `lumi2-core-web-vitals` | [addyosmani/web-quality-skills · skills/core-web-vitals/SKILL.md](https://github.com/addyosmani/web-quality-skills/blob/main/skills/core-web-vitals/SKILL.md) | 测量交互、加载与布局稳定性；实验室结果不得冒充真实用户分位数。 |
| SKILL-15 · `lumi2-differential-review` | [trailofbits/skills · plugins/differential-review/skills/differential-review/SKILL.md](https://github.com/trailofbits/skills/blob/master/plugins/differential-review/skills/differential-review/SKILL.md) | 审查账户和部署变更带来的安全回归。 |
| SKILL-16 · `lumi2-variant-analysis` | [trailofbits/skills · plugins/variant-analysis/skills/variant-analysis/SKILL.md](https://github.com/trailofbits/skills/blob/master/plugins/variant-analysis/skills/variant-analysis/SKILL.md) | 从一个实际漏洞追踪同类调用点，但同一根因不拆成多个计数。 |
| SKILL-17 · `lumi2-sharp-edges` | [trailofbits/skills · plugins/sharp-edges/skills/sharp-edges/SKILL.md](https://github.com/trailofbits/skills/blob/master/plugins/sharp-edges/skills/sharp-edges/SKILL.md) | 发现容易误用的配置/API；用简明边界替代层层兜底。 |
| SKILL-18 · `lumi2-property-based-testing` | [trailofbits/skills · plugins/property-based-testing/skills/property-based-testing/SKILL.md](https://github.com/trailofbits/skills/blob/master/plugins/property-based-testing/skills/property-based-testing/SKILL.md) | 验证分页、权限、标识、导入和迁移的不变量。 |
| SKILL-19 · `lumi2-api-design-principles` | [wshobson/agents · plugins/backend-development/skills/api-design-principles/SKILL.md](https://github.com/wshobson/agents/blob/main/plugins/backend-development/skills/api-design-principles/SKILL.md) | 收敛契约、状态码和资源归属；不再复制第二套 API。 |
| SKILL-20 · `lumi2-doc-coauthoring` | [anthropics/skills · skills/doc-coauthoring/SKILL.md](https://github.com/anthropics/skills/blob/main/skills/doc-coauthoring/SKILL.md) | 以当前代码收集事实、精简并做新读者测试；授权明确时不重复提问。 |

这 20 个入口与旧 20 个名字不重复，但这只是“名单不重复”，不是功能结果自动增加。保留旧视觉 Skills，明确分工：旧技能负责视觉方向；新技能负责设计系统实现、React 状态、测试、安全、性能和交付证据。

应用规则：修改前读取相关 Skill，而非每轮把 40 份全文同时灌入上下文。每项至少留下真实 task ID、实施/审查结论与产物路径。无需为同一个工具写独立长报告。

上游约束须适配现场：TDD 不允许删除用户旧代码；教程中的 npm 命令按项目 pnpm/uv 锁文件转换；全套测试按合理批次运行而非每个微改都跑一次；请求代码审查由主协调者派发，不开启子 Agent 嵌套。模板里的 Next.js、Redux、Radix、Kubernetes 不是本项目采用它们的理由。

### 4.2 十个新 MCP（不是十个必须常驻的进程）

#### MCP-01 · `lumi2-github` — GitHub 官方 MCP

来源：[上游](https://github.com/github/github-mcp-server)；[配置依据](https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md)。

接入：现有安全认证 + 本地固定版本 stdio，或已有受支持 OAuth 的官方远端；只读 repos/pull_requests/actions 等必要工具。

实际验收：查明本轮提交是否在主分支、必需 CI 是否针对同 SHA 通过、Release 附件是否真实存在。

边界：不新建或明文落盘 PAT；没有可用授权只阻塞此服务，不阻塞本地修复；不调用 secrets、删除仓库或改保护规则。

成熟度说明：官方产品；仓库约 33.2k stars，非用户数。

#### MCP-02 · `lumi2-serena` — Serena

来源：[上游](https://github.com/oraios/serena)；[配置依据](https://oraios.github.io/serena/02-usage/020_running.html)。

接入：按官方 Quick Start 锁 commit，在隔离的本项目受控源码视图中使用 LSP；只开放项目所需工具。

实际验收：定位 AdminScreen、认证依赖和调度器的符号引用，支持有依据的拆分并用类型检查验证。

边界：禁止挂载 home、.ssh 和生产数据；项目排除规则不是安全沙箱；需要 OS/容器边界。GPL-3.0-or-later / SolidLSP MIT 分组件核验。

成熟度说明：社区代码工具；仓库约 29.8k stars。

#### MCP-03 · `lumi2-git` — Git 参考 MCP

来源：[上游](https://github.com/modelcontextprotocol/servers/tree/main/src/git)；[配置依据](https://raw.githubusercontent.com/modelcontextprotocol/servers/main/src/git/README.md)。

接入：固定 mcp-server-git 与兼容 MCP SDK 版本，隔离环境中只暴露本项目的只读状态、diff、log、show 工具。

实际验收：检查三个旧 worktree 的真实修改、提交关系及合入状态，不重复生成已经完成的补丁。

边界：不把 --repository 当作足够权限边界；禁止 reset/checkout/commit 等写工具，经原生 Git 由协调者合入。

成熟度说明：官方参考实现，README 明示早期开发；不称为生产就绪。

#### MCP-04 · `lumi2-semgrep` — Semgrep 当前内置 MCP

来源：[上游](https://github.com/semgrep/semgrep)；[配置依据](https://docs.semgrep.dev/cli-reference)。

接入：固定当前 semgrep 二进制，用 semgrep mcp；依据实际 --help 配置本地扫描与关闭不必要 metrics。

实际验收：对权限、路径、SQL、模板和 shell 变更扫描，再人工复核并写真实回归测试。

边界：禁止安装已归档 semgrep/mcp 旧服务；不接远端上传扫描，不输出秘密命中原文，不采用 --config auto 偷发项目地址。

成熟度说明：核心项目约 16.8k stars；MCP 已迁入主项目，许可证按组件和规则核验。

#### MCP-05 · `lumi2-markitdown` — MarkItDown MCP

来源：[上游](https://github.com/microsoft/markitdown/tree/main/packages/markitdown-mcp)；[配置依据](https://raw.githubusercontent.com/microsoft/markitdown/main/packages/markitdown-mcp/README.md)。

接入：固定 markitdown-mcp，stdio 沙箱运行，只挂载合成或已脱敏的转换样本目录。

实际验收：对导入/导出的 HTML、EML 等公开测试样本生成 Markdown 对照，检查文字和来源字段是否丢失。

边界：convert_to_markdown 能读 file URI；必须隔离文件权限和网络，不能仅靠提示词。不得读取私钥、生产备份或用户私人文档。

成熟度说明：Microsoft 项目约 187.3k stars；MCP 子包的实际用户数未知。

#### MCP-06 · `lumi2-eslint` — ESLint 官方 MCP

来源：[上游](https://eslint.org/docs/latest/use/mcp)；[配置依据](https://eslint.org/docs/latest/use/mcp)。

接入：固定 @eslint/mcp；放开发工具隔离目录，按需要补充项目现有 oxlint 未覆盖的少量检查。

实际验收：审查 React Hooks、组件约束等实际缺口，输出可定位违规与修复；没有缺口则记录证据，不造 lint 任务。

边界：不得把现有 pnpm lint 从 oxlint 全量换成 ESLint，不引入互相矛盾的两套格式化规则。

成熟度说明：官方提供 MCP；不把 ESLint 总采用率宣称为 MCP 用户数。

#### MCP-07 · `lumi2-storybook` — Storybook 官方 MCP

来源：[上游](https://storybook.js.org/docs/ai/mcp/overview)；[配置依据](https://storybook.js.org/docs/ai/mcp/overview)。

接入：开发环境使用兼容版本 @storybook/addon-mcp，在现有或最小隔离 React/Vite 组件工作台启用，固定依赖。

实际验收：读取真实 Base UI 包装组件的属性，建立登录表单、按钮、弹窗、用户表格的状态样本，并运行交互检查。

边界：官方能力仍为 preview；禁止称稳定版。只供开发，不进生产镜像；与重型 E2E 轮换资源，不为其改成 Next/Radix。

成熟度说明：Storybook 官方集成，MCP 明示 preview；API 兼容需现场验证。

#### MCP-08 · `lumi2-gitmcp` — GitMCP

来源：[上游](https://github.com/idosal/git-mcp)；[配置依据](https://github.com/idosal/git-mcp/blob/main/README.md)。

接入：使用项目公开文档的官方 GitMCP 端点；一个服务实例按需查询公共上游，不按仓库数量重复计 MCP。

实际验收：研究 FreshRSS 或成熟开源实现的准确接口与文档，把结论关联一个复用或兼容性任务。

边界：仅检索公开上游，不提交私人代码、生产日志、用户资料或认证信息；远端滚动服务记录工具 schema 与访问时间，不能虚报锁定版本。

成熟度说明：社区远端文档工具；仓库约 8.4k stars。

#### MCP-09 · `lumi2-microsoft-learn` — Microsoft Learn MCP

来源：[上游](https://learn.microsoft.com/en-us/training/support/mcp)；[配置依据](https://learn.microsoft.com/en-us/training/support/mcp-developer-reference)。

接入：官方 Streamable HTTP：https://learn.microsoft.com/api/mcp；无需新增认证，按初始化发现实际工具。

实际验收：核查 WSL、Windows/Edge/PWA 开发与测试边界；不能把桌面 WebKit 测试冒充真实 iPhone 测试。

边界：只查公开文档，不发送本机路径、凭据或浏览历史；不因为使用该工具就添加 Azure 基础设施。

成熟度说明：官方公开文档服务；不需要 API key。

#### MCP-10 · `lumi2-memory` — 本地 Memory 参考 MCP

来源：[上游](https://github.com/modelcontextprotocol/servers/tree/main/src/memory)；[配置依据](https://raw.githubusercontent.com/modelcontextprotocol/servers/main/src/memory/README.md)。

接入：固定 @modelcontextprotocol/server-memory，在受忽略且隔离的脱敏目录存储小型任务关系索引。

实际验收：保存 task ID→模块→证据路径→依赖关系，用于上下文压缩后找回准确位置，实际演示一次恢复查询。

边界：只能作为可重建索引，权威台账仍唯一；禁止存用户原文、私钥、Cookie、令牌或完整聊天。不得用于伪造长期后台执行。

成熟度说明：官方参考实现，非生产数据存储方案。


所有本地 MCP 都需要真实文件/网络权限边界。告诉工具“不要读 .ssh”不是沙箱；指定 working directory、`--repository` 或 ignore 文件也不是权限隔离。具备任意 file URI、文件读写或 shell 工具的服务应在受控环境运行，只提供必要源码/合成样本。不得挂载 Docker socket、home、SSH agent socket、生产数据库或 `.env.prod`；生产 SSH 仍由受控原生终端完成。

现有浏览器 MCP 必须用独立临时 profile，只测试本应用与合成测试账户，禁用不必要遥测；不连接用户日常浏览器。HAR、trace、截图中的 Cookie、Authorization、用户内容不能进入公共证据。

按批次启停，避免在 WSL 同时常驻所有服务。MCP 必须做一次真正服务于本项目的工具调用，不能只握手；暂不可用的留独立阻塞，不使用不相干服务器凑 10。

### 4.3 十个新 Agent 定义

来源改为 `msitarzewski/agency-agents`，不是把旧 VoltAgent 文件改名。角色职责可能与已有角色相关，但来源、正文与适配需要真实可查。只安装所选十份及必要引用，不执行“安装全部团队”。

| ID / 别名 | 精确来源 | 本项目责任 |
|---|---|---|
| AGENT-01 · `lumi2-frontend-developer` | [engineering/engineering-frontend-developer.md](https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-frontend-developer.md) | 前端实现与性能；负责分配到的组件域，不写公共台账。 |
| AGENT-02 · `lumi2-ui-designer` | [design/design-ui-designer.md](https://github.com/msitarzewski/agency-agents/blob/main/design/design-ui-designer.md) | 视觉方案与令牌；提交真实页面前后图，不只交设计建议。 |
| AGENT-03 · `lumi2-ux-architect` | [design/design-ux-architect.md](https://github.com/msitarzewski/agency-agents/blob/main/design/design-ux-architect.md) | 登录、管理和移动导航的信息结构；保持默认界面克制。 |
| AGENT-04 · `lumi2-backend-architect` | [engineering/engineering-backend-architect.md](https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-backend-architect.md) | FastAPI/FreshRSS/SQLite 的模块边界、迁移和任务调度。 |
| AGENT-05 · `lumi2-appsec-engineer` | [security/security-appsec-engineer.md](https://github.com/msitarzewski/agency-agents/blob/main/security/security-appsec-engineer.md) | A/B 数据隔离、认证、上传和第三方工具的授权审查。 |
| AGENT-06 · `lumi2-devops-automator` | [engineering/engineering-devops-automator.md](https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-devops-automator.md) | CI 产物、升级 CLI、备份恢复；生产写入由主协调者串行授权。 |
| AGENT-07 · `lumi2-api-tester` | [testing/testing-api-tester.md](https://github.com/msitarzewski/agency-agents/blob/main/testing/testing-api-tester.md) | 真实 BFF/FreshRSS 集成、权限矩阵与错误契约；不得只测 mock。 |
| AGENT-08 · `lumi2-evidence-collector` | [testing/testing-evidence-collector.md](https://github.com/msitarzewski/agency-agents/blob/main/testing/testing-evidence-collector.md) | 独立浏览器验收、截图和复现步骤；不以截图数量代替交互验证。 |
| AGENT-09 · `lumi2-reality-checker` | [testing/testing-reality-checker.md](https://github.com/msitarzewski/agency-agents/blob/main/testing/testing-reality-checker.md) | 独立核验用户结果、去重与正式发布条件；不能审查自己编写的代码。 |
| AGENT-10 · `lumi2-technical-writer` | [engineering/engineering-technical-writer.md](https://github.com/msitarzewski/agency-agents/blob/main/engineering/engineering-technical-writer.md) | 全量文档处置、稳定导航、命令验真和新读者理解测试。 |

ZCode 适配：`name`、`description` 必填；模型采用有效的 `inherit` 或当前确实可用的模型。字段与工具权限以实际官方文档核验，不能凭空填 `reasoningEffort`、工具通配符或不存在的模型。依赖 MCP 的 `mcpServers` 精确匹配，并先确认父会话已连接；自定义 tools 白名单不能意外剔除所需 MCP。[Z2]

新定义通常在新会话生效，不以磁盘文件存在冒充原生派发成功。每个角色至少有一次真实分工结果，记录 handle、输入任务、修改/审查和验收。若只用通用 Agent 加载角色文本，标注为适配执行而非原生注册，后续仍需验证新定义。

不要照抄上游“必须发现几处问题”“达到某个百分比”等表演式指标，也不要使用宣传性人格、虚构经验和成功率。无问题就报告无问题；缺证据就报告缺证据。安全角色不能在生产做未经限定的攻击测试；DevOps 不得独占 root 权限随意改系统。

## 5. 十项架构整改：沿用编号，重新验证，不重新造轮子

下表有“公开源码直接观察”“日志中的已改声明”和“待现场实测的风险”，不能全部写成已确认线上故障。旧 ARCH-04/06/10 的提交若真实有效，保留并补验证，不撤掉重写来制造新工作量。

| ID | 问题 / 证据类型 | 必须交付的改进与验收 |
|---|---|---|
| ARCH-01 | 管理界面与管理路由职责集中；检查当前分支实际规模，不沿用旧行数冒充实测 | 按账户、邀请、审计、运维拆分有内聚性的业务模块；同一接口契约与权限入口；管理核心 E2E 不退化。 |
| ARCH-02 | App 的导航、初始化和移动布局可能耦合；须现场测量 | 单一页面注册和清楚布局外壳；管理页不初始化无关阅读任务；切换路由无重复挂载/请求。 |
| ARCH-03 | 日志记录 J4 被 CI 排除、J2 有数据状态依赖 | 修复真实契约和测试隔离，恢复必需旅程；不得新增 skip、grep-invert 或放宽断言获得绿色。 |
| ARCH-04 | 公开 publish 工作流独立 push；日志声称 41ee494 已加同 SHA 门禁 | 核验该提交与当前逻辑，阻止失败或无可信门禁的 SHA 发布；workflow_run 的来源、权限、artifact 及 head_sha 必须验证，防止拿错提交。 |
| ARCH-05 | 公开 CLI 的备份/恢复/离线包链路不统一 | 统一备份协议和发行 manifest；备份失败阻止切换；恢复停住真实写入者；完整离线包在断网环境安装并恢复。 |
| ARCH-06 | 日志声称 b6f7343 固定基础镜像 digest | 验证已固定的镜像实际能拉取和构建；用受控更新流程维护，不强推新主版本，不把不存在 digest 写进 Dockerfile。 |
| ARCH-07 | 可选 RAG/翻译/媒体功能可能扩大默认开销 | 分析实际导入、依赖、任务和内存；未启用功能不启动重任务，基础 RSS 可独立运行；保存前后相同负载测量。 |
| ARCH-08 | 调度器依附应用生命周期时有重复执行与资源竞争风险 | 明确迁移、ready、调度、租约和停机顺序；单 worker/重启/重复启动的行为可测试，不为此盲目加 Redis 或微服务。 |
| ARCH-09 | 工具记录、实现台账与文档多处漂移，历史 verified 无证据 | 一份权威状态索引、按任务加载的文档导航、全量处置清单；证据丢失的完成项重新核验而不是复制“已完成”。 |
| ARCH-10 | 日志声称 0d34f77 去掉 web 的整份 .env.prod 注入 | 核验实际 Compose 与运行容器仅获得必要变量；角色、用户数据和 AI 秘密不越界，公共诊断不输出环境全量。 |

坚持模块化单体：FreshRSS 仍是 RSS 订阅/文章状态的既有后端；BFF 处理授权、适配与应用功能；SQLite 的迁移、归属和任务事务明确。不要为“800 项”添加 800 个零碎框架、表、后台守护进程和菜单。优先复用现有组件、库、解析器、测试设施和 API，不重新实现成熟协议。

## 6. UI 不能只“换个颜色”

目标是清楚、现代、尺寸统一、圆角与反馈自然，不是把所有区域做成透明玻璃。保留 Base UI、React/Vite/Tailwind 的现有架构；不要换成另一套组件库，也不靠全局 CSS 大量 !important 补丁修布局。

先用已安装视觉 Skills 产出一份短设计契约并立即应用到真实页面：颜色与层级、字号/行高、间距、控件高度、圆角、边框、阴影、动效、焦点和禁用态。选择一套与已有偏好相容的低饱和方案；不要每个 Agent 自选一套主题。

先完成四个可对比页面：登录、管理员用户列表、订阅/时间线、文章阅读。再覆盖设置、弹窗与新增工作流。组件的默认、悬停、焦点、按下、加载、错误、禁用、空状态都必须可操作；不是只画默认漂亮截图。

设计方向：
- 登录页有清楚品牌与表单层级，邀请码/注册关闭/错误/密码管理器状态真实；不把测试账户或默认密码印在公开页面。
- 管理页有明确导航、信息密度和危险动作区，普通用户不见无权入口，后端同样禁止访问；长用户名、空列表和大列表都正常。
- 移动端默认保留首页、订阅、搜索、收藏的清楚入口，设置在侧栏可达；高级研究、导入和工具工作流按情境展开，不挤满底栏。
- 正文优先，来源、标题和操作层级清楚；卡片密度可控，图标尺寸一致，透明背景必须有可读的实体底层。
- 动画只承担过渡与反馈，避免全页面持续动画；遵循减少动态效果设置，长列表不逐项做昂贵模糊和位移。

视觉证据矩阵至少覆盖：360、390、430 宽手机视口，768/1024 平板，1440/1920 桌面；明暗主题、文本放大、长中文/英文标题、无数据、慢请求、权限不足、软键盘遮挡和嵌套弹层。

先有固定合成数据与基线截图，再比较修复后同视口、同状态。不能更新基线掩盖回归。Playwright 的设备模拟和桌面 WebKit 是有用代理测试，不能称为“在真实 iPhone Safari 已验证”；没有真机就准确记录覆盖边界。

必须真正点击、输入、提交、返回、刷新与重登。Console/Network 错误要分类处理；浏览器打开过首页不算账号管理可用。Storybook 和组件测试是辅助，不能替代真实应用路由验证。

## 7. 新增功能的产品约束

本轮 400 项新增描述的是完整用户结果，不等于首页放 400 个按钮。每个新增先回答：谁用、从哪里进入、以前缺少什么、完成后看到什么、属于谁、刷新后什么保持、失败如何恢复。

大功能按纵向切片实现：一个入口、必要 API/数据、实际结果、权限和测试一起完成。不要先铺几百个占位页，或者把所有数据藏进 localStorage 伪造后端实现。

多数高级功能默认按需启用，不阻碍基础 RSS，不强迫用户配置 AI/邮件/API/对象存储。无真实 Provider 的付费功能不得声称跑通；优先使用合成测试输入和现有授权服务，有缺口保留精确 ID，继续无关工作。不能拿静态示例回复冒充真实翻译或 RAG。

对批量导入、导出、共享、离线、笔记与 AI 增加 A/B 隔离测试。管理员权限不是默认可读取所有用户私有文章的理由；运维统计只暴露必要汇总。共读必须显式共享，私人标注不自动带出。

新增下载、快照或媒体功能仅处理用户有权访问/保存的内容，不绕过付费、登录或平台访问控制。输出导出包前让用户选择内容范围，不把整库和秘密默认打包。

## 8. 文档和项目结构：全量审计，按任务读取

不是把 README 写得更长，也不是把所有说明压成难读缩写。借鉴成熟项目的明确入口、任务导向文档、代码定位和按需上下文，而不是复刻某个仓库的文件数量。参考 OpenCode 的 Agent 约束和 Aider 的 repository map；它们是公开设计参考，不等于已证明每份文档由 AI 编写。[D1][D2]

### 8.1 全部文档都有处置

盘点 Git 跟踪的 README/AGENTS/CONTRIBUTING/CHANGELOG、docs、.github、各应用脚本目录说明，以及 MD/MDX/RST/TXT/配置示例中的文档。单独盘点受忽略的本地开发说明，但先只列路径和类别，不输出秘密内容。

每个条目标记：更新、合并、移动并修复链接、归档、保留且核验未变，或不应纳入项目的第三方/历史原文。不能只改根 README 宣称“所有文档已更新”。许可证、第三方原文、真实历史变更记录不机械改写。生成文件通过生成器更新，不直接手改。

公共文档不包含 SSH 用户私人目录、私钥路径、生产密码、密钥内容、原始服务配置或含身份的截图。AI 工具的本地记录和运行证据不当作面向用户的产品文档提交。

### 8.2 目标结构是小入口，不是多一套目录

优先合并到既有位置，以下是职责而非必须照建的树：
- README：是什么、最快上手、一个主要截图、文档入口、必要限制。
- 根 AGENTS：少量安全规则、架构边界、常用验证命令、按任务去哪里读。
- 文档索引：按使用、开发、运维、账户/隐私、设计导航到唯一真源。
- 稳定手册：开发、架构、运维/恢复、设计、数据/账户。
- API/配置参考：尽量从真实 schema 生成。
- 版本进度/证据：唯一索引指向本轮台账，不把 800 项注入每个 Agent 的常驻上下文。

不要另建与原 docs 并列的 phase2 文件夹。若 e2e/stack 是服务编排测试夹具，保留合理位置并加短说明；只有能证明移动改善结构时才迁移，随后更新 CI、脚本和文档。不要为了根目录“好看”打断路径。

### 8.3 写作规则与验收

一段表达一个判断或操作；先动作与结果，再给必要条件。删除重复背景、空洞形容词、“进一步全面持续优化”等无信息句。保留失败条件、限制、安全注意与恢复路径。不能通过删掉关键语义或把几段合成一条巨长句来刷字数。

记录精简前后的总量与常驻上下文大小，但不设置“无条件删 70%”指标。中文表达通顺，少用生硬缩写。代码注释解释原因、约束和危险边界，不逐行复述代码。不得因“不要防御性编程”删掉权限校验、事务、输入验证或必要错误处理。

验收：全量清单 100% 有处置；内部链接、锚点和文档站路由通过检查；关键命令在干净环境实际跑通；两个未参与写作的阅读者分别回答“怎么运行、在哪里修改、怎么测试、怎么升级、怎么恢复、数据在哪里”，答案必须有文档依据，不补猜测。

## 9. SSH、生产授权与秘密保护

用户授权只操作 `47.100.64.202` 上现有 LumiRSS 项目及其明确所属资源，不是授权清理整机、重启系统或改其他应用。使用日志已确认过的 root 身份作为线索，现场重新核验当前权限和主机。

**私钥只由 SSH 客户端为本次连接按原路径读取；模型、脚本日志和 MCP 不读取/打印其内容。** 不复制、不移动、不改名、不上传、不创建副本、不存入仓库、镜像、附件或远端。原有 `~/.ssh/new.zephyr.pem` 若仍为已授权身份，可按路径引用；路径不存在或权限失败时不要猜其他人的密钥。

禁止 agent forwarding；保持严格主机身份核验。`ssh-keyscan` 只能采集候选指纹，不能自己证明主机可信；指纹改变必须通过可信渠道验证。不得设置 `StrictHostKeyChecking=no`、自动接受变更或批量猜用户名。认证失败只能描述实际拒绝，不能猜测 authorized_keys 被轮换。

不上传 authorized_keys，不新增身份，不扩大 sudo，不把 SSH key 用作 GitHub PAT。已有 GitHub/镜像认证只能经当前安全机制使用，秘密不进命令回显、配置文本或日志。不要全量打印 env、docker inspect、docker compose config；只提取允许公开的字段。关闭 set -x。

仅结束本轮新建连接、控制 socket 或专用短生命周期 agent；不删除用户原始私钥，不执行影响其他会话的 ssh-add -D。安全恢复 checkpoint 仅写身份的逻辑说明与非敏感路径，不保存凭据。

生产只做受控部署和小范围合成验证。禁止生产 npm/pnpm/pip 安装、Docker build、运行开发 MCP、安装大型模型、全机 prune、down -v、删除用户数据、开放全部端口、覆盖共享 Caddy。共用反代只修改 LumiRSS 的既有站点块，校验后温和 reload，确认其他站点仍正常。

## 10. 发布与恢复：验证同一个产物

### 10.1 发布前

同步并核验本地分支、远端主分支和生产运行版本；保留未提交工作。架构与功能测试通过后确定 RELEASE_SHA，所有候选镜像/包包含版本和完整 SHA。正式标签不可变，不靠 latest 判定。

必要测试至少包括：类型/格式/语法、版本一致性、OpenAPI/设置生成漂移、单元/集成、真实 FreshRSS 核心旅程、账号矩阵、A/B 越权、视觉/键盘/移动、备份并发、完整恢复、安装升级、离线路径、秘密扫描及资源测量。Mock 用于单元和可重复测试，但不得替代必要真实服务测试。

旧失败必须修复或如实说明，不得删除测试、无理由 skip/xfail、把错误返回 200、降低断言或吞掉 console.error。测试重跑需解释原失败与根因，不把偶然一次绿当解决。

### 10.2 CI 构建一次，候选测试后原样推广

用 CI 为 RELEASE_SHA 构建候选并记录 digest、架构、校验值与构建记录。下游拉同一 digest 测试，再把该产物推广为正式版本；不得 tag 后另构建一份未测镜像。当发布流程变更需要再测时生成新的候选，不移动已发布正式标签。

正式发行包含：部署 CLI、无 build 的生产 Compose、必要辅助文件、只含占位符的配置示例、release-manifest.json、SHA256SUMS、简短升级与恢复说明。manifest 明确支持平台、源 SHA、受测 digest、兼容范围、迁移与回退条件。

另外提供完整离线包：包括实际部署选择所需的所有预构建镜像与备份辅助工具，不仅 web+bff。全新隔离环境断网验证：解包→校验→加载→配置→启动→基础功能→备份/恢复；安装过程中不能偷偷去拉 alpine、pip 包或 Node 依赖。

### 10.3 备份不是“tar 成功”与“integrity ok”

统一 CLI 和 BFF 备份语义。SQLite 使用可靠一致性快照；涉及多个库与 FreshRSS 业务关系时，采用必要的短维护窗口或可证明一致的协调方案，并说明一致性边界。枚举真实写入者，不只停 BFF 就认为 FreshRSS 已停止。

备份清单记录库、配置、附件范围、版本和校验值，密文/秘密原件只留授权服务器目录且权限受控。升级前必须完成备份与可恢复性验证；失败停止切换，不能 warn 后继续。

恢复测试至少验证：包可解、校验一致、数据库结构可读、目标服务在隔离环境启动、合成或授权数据的用户归属/订阅/阅读状态/标注关联正确。不能只跑 PRAGMA integrity_check 宣告完整恢复。生产真实数据不上传开发 MCP 或公共 CI；需要完整私有恢复时在服务器授权目录内做受控演练，资源不足则选择安全的维护方案，不把副本搬到不必要位置。

### 10.4 更新顺序

只读盘点 → 核验身份与备份容量 → 项目升级锁 → 一致性备份与恢复验证 → 下载并校验受测产物 → 配置/兼容性检查 → 必要迁移与切换 → ready 与真实功能测试 → 观察资源/调度 → 保留回退窗口。

任何切换前错误不破坏旧服务。切换后失败先判断数据库向后兼容：可只回切旧镜像则保留新数据；需要覆盖数据且可能丢新写入时禁止自动破坏性恢复，报告风险。禁止为了绿色健康状态重建空数据库。

生产验收使用专用合成账号和最少测试数据，验证实际域名 TLS、登录、管理员/普通用户、订阅、正文、读/藏状态、搜索和代表性新增功能。测试对象清理仅限本轮创建记录。

最终对齐：tag、RELEASE_SHA、manifest、实际 BFF/Web digest、运行版本接口与前端版本。HTTP 200、Release 创建、镜像推送或拉取成功，任一个都不足以证明发布完成。

## 11. 最终门禁与报告

每轮都从真实未完成项继续。结束前独立验收下列内容，证据缺失的项不得过门禁：

| 范围 | 条件 |
|---|---|
| FIX | 400 个独立真实修复，原本正确/只审计的项不占数；有复现、修复、测试与审查。 |
| NEW | 400 个独立的新用户结果，真实入口和端到端验收；无占位与旧功能冒领。 |
| ARCH | 10 项全部有实际结论与验证，已有有效提交经核验继承。 |
| 新工具 | 20 Skills、10 MCP、10 Agent 定义分别安装/注册/调用/应用有证据；保留旧工具不重新充数。 |
| 文档 | 全量处置覆盖、链接/命令验证、新读者测试；唯一事实源与可恢复上下文。 |
| 构建 | 必需检查通过；受测 SHA、digest 与在线/离线正式包一致。 |
| 生产 | 47.100.64.202 的目标 LumiRSS 已更新到相同产物，数据及其他服务完好。 |
| 安全 | 无私钥副本、凭据泄漏、越界生产操作或未经授权的服务变更。 |

计数不足、功能被真实能力限制或工具不可注册时，不能写 COMPLETE。记录精确缺口、已验证内容、阻塞类型和安全下一步，继续不受阻的工作。禁止为凑数制造缺陷、添加无用功能、启用付费服务或伪造工具调用。

最终交付摘要保持简短：真实完成计数、主要可见变化、版本来源链、生产状态、测试/视觉证据、文档处置入口、恢复说明及剩余硬阻塞。原始长日志不粘满对话。

“不能停止”是要求保持执行与严格完成判定，不是允许无视用户暂停/预算/权限，也不能保证 800 项一定在一夜完成。禁止 sleep 或反复扫描以凑时长。

## 12. 公共核查来源与现场核验边界

下列是任务包研究时读取的公共来源；它们不是用户本地执行的证明。安装时记录实际 commit/version 和许可，部署时记录实际运行 digest。日志中的本地提交与生产观察以现场再次读取为准。

- [P1] [LumiRSS VERSION](https://raw.githubusercontent.com/paidethon/LumiRSS/main/VERSION)
- [P2] [LumiRSS web package](https://raw.githubusercontent.com/paidethon/LumiRSS/main/apps/web/package.json)
- [P3] [部署 CLI](https://raw.githubusercontent.com/paidethon/LumiRSS/main/lumirss)
- [P4] [发布 workflow](https://raw.githubusercontent.com/paidethon/LumiRSS/main/.github/workflows/publish-images.yml)
- [Z1] [ZCode Goal](https://zcode.z.ai/cn/docs/goal)
- [Z2] [ZCode 子智能体](https://zcode.z.ai/cn/docs/subagents)
- [Z3] [ZCode MCP](https://zcode.z.ai/cn/docs/mcp-services)
- [Z4] [ZCode Skills](https://zcode.z.ai/cn/docs/skill)
- [D1] [OpenCode AGENTS](https://github.com/anomalyco/opencode/blob/dev/AGENTS.md)
- [D2] [Aider repository map](https://aider.chat/docs/repomap.html)
- [T1] [Superpowers](https://github.com/obra/superpowers)
- [T2] [wshobson/agents](https://github.com/wshobson/agents)
- [T3] [antfu/skills](https://github.com/antfu/skills)
- [T4] [Web Quality Skills](https://github.com/addyosmani/web-quality-skills)
- [T5] [Trail of Bits Skills 与许可](https://github.com/trailofbits/skills)
- [T6] [Anthropic Skills](https://github.com/anthropics/skills)
- [T7] [Agency Agents](https://github.com/msitarzewski/agency-agents)
- [M1] [官方 MCP 参考实现的限制](https://github.com/modelcontextprotocol/servers)
- [M2] [Semgrep 旧 MCP 归档/迁移说明](https://github.com/semgrep/mcp)
- [M3] [Storybook MCP preview 说明](https://storybook.js.org/docs/ai/mcp/overview)
- [M4] [MarkItDown MCP 文件权限说明](https://github.com/microsoft/markitdown/blob/main/packages/markitdown-mcp/README.md)

每个 Skill、Agent 和 MCP 的精确入口、用途与边界已在第 4 节及 `tools.json` 列出。不要把研究清单中的未固定 revision 填为假的已安装 commit。
