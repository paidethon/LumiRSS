# 0020 — MVP Release Remediation

> Status: **Completed (2026-09-05)** · Branch: `fix/0020-release-remediation`
> Baseline: 0019 complete at commit `3bed7c5`（feat/0019-mvp-stabilization-release）

## Objective

前一次全仓只读审计给出 `P0:0 / P1:2 / P2:27 / P3:29`，同时基线为
BFF 559 pytest、Web 533 vitest、lint/build/静态 Playwright smoke 全绿，
核心架构健全。因此 0020 **不是架构重写**，而是：

> 用小的、带回归测试的改动修复已确认的发布相关缺陷，同时完整保留
> LumiRSS 现有架构不变量。

不追求「审计零发现」的人为分数；按 data integrity → backup/restore →
真实功能回归 → 前端状态正确性 → 可访问性/响应式 → CI/生产/operator →
文档真实性 → 选择性低风险清理 的优先级推进。

## Input audit

审计发现是**有证据支撑的假设**，但当前源码为准。每一项在修复前都先
核验当前实现、建立代码路径证据，再实现 + 回归测试；已修复/不可复现的
项记录后跳过，绝不为凑 AUDIT ID 改动可用代码。

## Scope（六个 Gate）

```text
Gate 1  Backup / Restore 完整性（最高优先）
Gate 2  前端功能回归（Reader / settings / 导航）
Gate 3  可访问性 / 响应式
Gate 4  发布 / CI / 运维契约
Gate 5  文档真实性 + 本 0020 记录
Gate 6  选择性 P3 清理（仅 confirmed/local/small/low-risk/clear-benefit）
```

## Fixes completed

### Gate 1 — Backup / Restore（AUDIT-001/004/005/006/034/036/037/038）

- **AUDIT-001**：备份 manifest 的 `size`/`sha256` 现在都描述**被归档的快照**
  （在线备份产物），而非活动源文件。WAL 模式下 FreshRSS SQLite 的快照大小
  与活动主库不同，此前 `size` 取活动文件导致恢复端 `info.file_size !=
  expected_size` 校验拒绝 Lumi 自己的备份。
- **AUDIT-004**：恢复时先对解压出的快照跑 `PRAGMA integrity_check`，
  **在替换活动库之前**；已知会失败的快照绝不写回。交换后校验保留为纵深防御。
- **AUDIT-005**：校验成员/总量/压缩比边界**先于**昂贵读取；哈希改为流式，
  不再把任意大成员一次性读入内存。
- **AUDIT-006/038**：启动清扫的完成标志只在 `mark_interrupted()` 成功后置位，
  单次瞬时失败不再把 Backup/Restore 永久卡在 409 Busy。
- **损坏备份 API**：非 ZIP / 截断归档在 preview 路由返回稳定的
  `400 backup_invalid`，不再泄漏通用 500。
- **AUDIT-034/036/037**：同秒本地备份文件名不再互相覆盖；WebDAV 上传失败
  时抢救有效本地归档；远端恢复改为流式落盘、以 `MAX_TOTAL_BYTES` 为界，
  与备份创建上限内部一致。
- 恢复路由级安全测试：running 守卫、恢复后账本对账、失败安全备份路径。

### Gate 2 — 前端功能回归（AUDIT-002/008/010/011/012/013/014/016）

- **AUDIT-002**：正式 Reader 根元素提供稳定 `.lumi-reader` 作用域，使设置/
  主题包的自定义 CSS（前缀 `.lumi-reader`）真正生效（此前只有
  `.lumi-reader-article`，自定义 CSS 从不命中）。
- **AUDIT-008**：app-settings 成为主题单一真源。首帧内联脚本 +
  `resolveInitialTheme` 读规范 `lumirss-settings.themeMode`（旧
  `lumirss-theme` 仅作迁移回退）；规范 `watchSystemTheme` 仅在 system 模式
  跟随 OS，显式 light/dark 绝不被 OS 覆盖。旧 `lumirss-theme` 所有权从生产
  启动路径退役（仅 dev Playground 保留）。
- **AUDIT-010**：失败的设置 PATCH 不再被静默丢弃——未解决的 dirty 键跨重载
  持久化、受保护不被陈旧 hydration 覆盖，并在下次 flush / `online` 事件重试
  （无轮询、无无限循环）。
- **AUDIT-011**：`ReaderSummary` 按 `entryRef` 加 key（与 translation/
  conversation 兄弟一致），文章 A 的生成 pending/error/result 不泄漏到 B。
- **AUDIT-012**：破坏性恢复成功后无效化全部查询缓存、清除待同步设置，并
  提供确定性重载；陈旧本地设置不会 PATCH 覆盖刚恢复的服务端设置。
- **AUDIT-013**：j/k 滚动定位到真实的 `[data-entry-ref]` 元素，而非不存在的
  `button[data-entry-ref]` 嵌套选择器。
- **AUDIT-014**：真实模态（`aria-modal`）打开时抑制全局 j/k/u/s；Escape/Tab/
  焦点陷阱语义保留。
- **AUDIT-016**：底栏 section 切换器延伸到 `<1024`（此前仅 `<768`），使
  768–1023 平板宽度可进入「订阅 / 搜索」（Drawer 内 Sidebar 只导航到 home）。

### Gate 3 — 可访问性 / 响应式（AUDIT-009 + accent/touch/modal）

- **AUDIT-009**：应用内「减少动效」偏好真正生效——tokens.css 新增
  `[data-motion-reduce='true']` 规则，与既有 `prefers-reduced-motion` 等效
  （此前只挂属性、无 CSS 消费）。
- **Accent 对比**：`applyAppearance` 按 WCAG 相对亮度派生
  `--lumi-accent-contrast`（复用 `relativeLuminance`），亮色自定义 accent 得到
  近黑前景而非不可读的白字；默认中深 accent 保持白字。
- **MobileSettingsScreen**：此前是弱自定义全屏模态（无 Escape / 焦点陷阱 /
  还焦 / 滚动锁）。提取共享 `useModalA11y` hook（源自 Sheet/Dialog 的成熟
  逻辑），MobileSettingsScreen 与 Sheet 复用之。
- **触摸目标**：Switch、Slider stepper、搜索历史删除按钮此前低于 ~44×44；
  用透明伪元素扩展命中区，不改视觉、不放大桌面密集控件。

### Gate 4 — 发布 / CI / 运维（AUDIT-019/020 + WebDAV/HTTP/文档）

- **Python 依赖可复现（AUDIT-020）**：BFF 生产 Dockerfile 改为多阶段
  `uv sync --frozen --no-dev --no-editable`，安装**与测试一致的 uv.lock**
  （此前 `pip install .` 独立解析 `>=` 范围）。运行阶段只携带解析好的 venv。
- **Docker CI（AUDIT-019）**：新增有界 `docker-build` job 构建**两个**生产
  镜像（`push:false`）；`bff-tests` 增加 `uv lock --check` 防锁漂移。
- **WebDAV 校验**：结构性客户端输入错误（空 URL / 非法 scheme / URL 带凭据 /
  `..` 穿越）抛 `WebDavInvalidSettings` → 稳定 `400 webdav_invalid_settings`；
  `502 webdav_error` 仅保留给真实上游失败。
- **HTTP 健壮性**：FreshRSS adapter 网络映射扩到 `httpx.TransportError`
  （覆盖此前逃逸成裸 500 的 PoolTimeout/ReadError/WriteTimeout/ProtocolError）；
  上游返回非数字 continuation 时抛稳定 `UpstreamError`，而非让 `encode_cursor`
  抛裸 `ValueError` 500。
- **Operator 文档**：install/upgrade 健康检查改为真实拓扑（生产发布 80/443，
  `/health/*` 仅容器内，Caddy 只反代 `/api/*`）；清除 operations.md /
  testing.md / playwright.config.ts / perf-measure.mjs 中陈旧的 18080 假设。
- **备份保密性文档**：operations.md 与 RestoreWizard 预览明确「备份不含 Lumi
  秘密**值**，但 FreshRSS 数据可能含凭据敏感材料，归档须当作敏感文件保管」。
- **第三方声明**：补齐缺失的运行时依赖 feedparser（BSD-2-Clause）。

### Gate 5 — 文档真实性（AUDIT-027/028）

- **AGENTS.md**：纠正「AI 未实现」的错误声明——明确区分**已实现**（AI 摘要/
  翻译/对话/设置、订阅控制、RSSHub 发现/控制、统一设置、备份/恢复/运维、
  Caddy 生产）与**真正延后**（web clipping、Obsidian）。
- **docs/architecture/README.md**：当前实现基线、系统上下文图、控制面、
  Caddy 职责、API surface、各 adapter 与 source-discovery/unified-settings
  章节由 planned → implemented；仅保留显式标注为历史（0009 验收）的段落。
- **README.md**：补充已发布 MVP 能力，并诚实标注 Phase-2 未实现。
- **docs/README.md / ROADMAP.md**：登记 0020。

### Gate 6 — 选择性 P3 清理（AUDIT-051）

- **AUDIT-051**：ReaderHeader / EntryRow / ReaderSummary / ReaderTranslation
  各自 `new Intl.DateTimeFormat('zh-CN', {年/月/日 时:分})` 出**完全相同**的
  格式器（EntryCard 为无年份变体）。提取到共享 `lib/date-format.ts`
  （`dateTimeFormatter` / `listDateTimeFormatter`），5 个组件改为引用；输出
  逐字不变，全部既有测试绿。
- 其余 P3 候选（042 freshrss_control 重复代码、046 preview 外链守卫、
  047 OpenCC 转换失败缓存、049 lastMatchedRule、055 legacy storage 清理）
  经评估：或不满足「小且低风险」、或需更大范围核实，不在本里程碑强修。
  **AUDIT-058（时区敏感测试）在 0019（commit bc6e11e “remove environment
  dependencies found by CI (TZ, .env leak)”）已于当前 HEAD 解决**。

## Regression tests added

| Test | Bug prevented |
|---|---|
| `test_backup_restore_roundtrip.py`（BackupEngine → archive → RestoreService.preview，WAL FreshRSS） | AUDIT-001：Lumi 自己的备份被恢复校验拒绝 |
| `test_restore.py::test_corrupt_snapshot_rejected_before_swap` | AUDIT-004：已知损坏快照被交换进活动库 |
| `test_restore_api.py::test_restore_preview_corrupt_archive_returns_stable_400` / `_truncated_` | 损坏/截断归档泄漏通用 500 |
| `test_restore_api.py::test_restore_execute_failed_safety_backup_returns_stable_500` / `_reconciles_ledger_after_swap` | 恢复路由安全 / 账本对账 |
| `test_backup.py::test_startup_cleanup_retries_after_transient_failure` | AUDIT-006/038：一次失败永久卡 409 |
| `test_webdav.py::test_download_to_*` | AUDIT-037：远端恢复上限小于可创建归档 |
| `gate-b.test.tsx`（AUDIT-013 scroll / AUDIT-014 dialog+j/s/u） | j/k 不滚动；模态下快捷键改动隐藏 Reader |
| `reader.test.tsx`（AUDIT-002 `.lumi-reader` / AUDIT-011 summary 不泄漏） | 自定义 CSS 不命中；A 生成态泄漏到 B |
| `theme.test.ts` + `theme-system-watch.test.ts`（AUDIT-008） | 首帧用错源；OS 覆盖显式 light/dark |
| `settings-sync.test.ts`（AUDIT-010 三例） | 失败同步静默丢失本地设置 |
| `mobile-tabbar.test.tsx`（AUDIT-016） | 768–1023 无法进入订阅/搜索 |
| `app-settings.test.ts`（accent 对比 / reduce motion） | 亮色 accent 白字不可读；减少动效无效 |
| `gate-e.test.tsx`（MobileSettingsScreen Escape / 滚动锁） | 弱自定义模态缺 Escape/背景隔离 |
| `test_freshrss_adapter.py`（PoolTimeout / malformed continuation） | 传输子类与坏 continuation 逃逸成裸 500 |
| `test_webdav.py` / `test_operations_api.py`（invalid settings 400） | 客户端输入错误被当成 502 |

关键新增：**BackupEngine → RestoreService roundtrip**（`test_backup_restore_roundtrip.py`）
证明 Lumi 生成的备份（含 WAL 模式 FreshRSS SQLite）能被 Lumi 恢复校验接受。
所有前端行为回归测试均已通过 `git stash` 验证**修复前失败、修复后通过**。

## Architecture invariants preserved

- FreshRSS 仍是 RSS 域唯一真源；未建 Lumi RSS 影子库；
- Lumi SQLite 只承载 Lumi 自有状态（AI/settings/operations/backup/migrations）；
- 浏览器只经 Lumi BFF；未引入浏览器直连 FreshRSS/RSSHub/带密钥的 AI；
- 正常内容路径 RSS/RSSHub → FreshRSS → Adapter → BFF → Web 不变；
- 打开文章不隐式标记已读；read/star 仍是显式 SET 语义；分页 cursor 仍 opaque；
- DOMPurify 仍是文章 HTML 最终边界；未削弱 SSRF 防护；未向浏览器暴露密钥。

## Deferred audit items

| Audit | 分类 | 延后原因 | 建议里程碑 |
|---|---|---|---|
| AUDIT-021 | BFF 内部鉴权架构 | 单用户信任模型下的架构决策，非发布阻断 | 0021 安全/运维硬化 |
| AUDIT-030 | DNS-rebinding IP-pinning 重设计 | 传输层重设计，风险 > 发布收益 | 0021 |
| AUDIT-032 | CSP/HSTS/rate-limit 策略 | 策略性硬化，需独立评审 | 0021 |
| AUDIT-033 | 通用请求体大小中间件 | 通用中间件属架构扩展 | 0021 |
| AUDIT-043 | AI lock-map 架构 | 并发架构改进，非发布阻断 | 0021 |
| AUDIT-048 | 多设备设置冲突语义 | 单用户场景收益有限，语义需产品决策 | 0021 |

其余未逐项列举的 P2/P3 审计项：或为设计硬化建议（非发布缺陷），或在当前
HEAD 已不可复现，或不在本里程碑「小而proved」的修复边界内——一律不强修，
不为凑分数扩大 0020。

## Verification

| Check | Result |
|---|---|
| BFF pytest | PASS — 574（基线 559） |
| Web vitest | PASS — 557（基线 533） |
| Web lint (oxlint) | PASS — 0 errors（7 存量 warnings，未新增） |
| Web build (tsc + vite) | PASS（仅 chunk-size 提示） |
| `uv lock --check` | PASS（锁与 pyproject 一致） |
| `docker compose -f docker-compose.prod.yml config` | PASS |
| BFF 生产镜像 `uv sync --frozen` | 命令与自包含 venv 本地验证通过 |
| Docker 镜像构建（BFF/Web） | NOT RUN 本地——docker daemon 代理无法访问 ghcr/PyPI；已加入 CI `docker-build` job |
| Playwright smoke / a11y / 视觉矩阵 | NOT RUN 本地——需浏览器/运行时栈；CI `e2e-smoke` 覆盖静态冒烟 |
| Remote GitHub CI | 见推送后检查 |

Web 全量测试在本机 20 核并行下会出现 5s 超时假失败；使用
`pnpm test --no-file-parallelism` 得到稳定 557 全绿（并行 flakiness 非产品缺陷）。

## Commits

```text
efae51b  fix(backup): harden backup and restore integrity
4688f2d  fix(web): resolve reader and settings regressions
acf24a8  fix(a11y): close responsive and accessibility gaps
fa47151  fix(release): align CI deployment and operator contracts
<docs>   docs: align project documentation with implemented MVP（含本文件）
```

## Known remaining limitations

- 上表 Deferred 项（0021 候选）：BFF 内部鉴权、DNS-rebinding 传输硬化、
  CSP/HSTS/rate-limit、通用请求体限制、AI lock-map、多设备设置冲突语义。
- Docker 镜像构建与 Playwright/视觉验证依赖 CI/运行时环境，本地未执行。
- Web 全量并行测试存在环境相关 flakiness（超时），需 `--no-file-parallelism`
  或提高 testTimeout 才能在本机稳定全绿。
