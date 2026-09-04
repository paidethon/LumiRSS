# 0019 — MVP Stabilization & Release

> Status: **Completed (2026-09-05)** · Branch: `feat/0019-mvp-stabilization-release`
> Baseline: 0018 complete at commit `e5bdea0`（feat/0018-production-operations-backup）

## Why

0001–0018 之后，LumiRSS 已是功能完整、可部署、可备份恢复的单用户阅读器，
但离「可发布」还差一层稳定化：没有可重复的端到端用户流程验证（桌面 ×
移动 × 明暗主题）、没有可访问性门禁、没有性能预算、没有 disaster
recovery / upgrade 演练记录、CI 只检查文档存在性、operator 文档与 release
notes 缺失。0019 不新增任何产品功能，只做**验证、加固、记录与收口**，
产出 release-ready 分支与验证证据。

## Goal

在不改变产品行为边界的前提下：

```text
A. E2E 基础设施    — Playwright 两层（确定性产品 E2E + production smoke）
B. 用户流程验证    — 桌面/移动 × 明暗 × 全部主要 journey，axe 可访问性门
C. 加固与度量      — 性能预算、安全与隐私复查、备份恢复演练记录
D. 发布工程        — CI 完整化、许可证审查、operator 文档、release notes
```

## Non-goals（硬边界）

- **不新增主要产品功能**；
- 不实现未批准的全局搜索后端（搜索入口保持「诚实说明尚未提供」）；
- 不实现 Phase 2（web clipping / Obsidian / email / 语义搜索 / 多用户）；
- 不复制 FreshRSS 数据进 lumi.sqlite；
- 不重构与 stabilization 无关的架构；
- 不升级 FreshRSS / RSSHub pin；
- 不用 release milestone 掩盖产品缺陷：发现缺陷 → 修复 + 回归测试，
  不得用放宽断言 / skip 掩盖。

## Release scope

1. Playwright E2E（已在 0018 G11 引入）扩展为完整 journey 矩阵：
   - 桌面 journeys：启动导航 / 时间线与 Reader / 订阅与分类（含 OPML
     文件上传）/ AI（本地 mock provider）/ 设置与运维 / 搜索页诚实边界；
   - 移动 journeys：底部导航与抽屉 / 时间线与全屏 Reader / AI 面板 /
     订阅与设置；三档视口（430×932、390×844、375×812）+ 横向 smoke；
   - 明暗主题各跑一轮主要路径；system 主题 smoke；
   - 无横向溢出、无文本裁切断言；OPML/文件上传用 Playwright
     `setInputFiles`（内置浏览器不能上传文件）。
2. 可访问性门：`@axe-core/playwright` 对主要页面扫描，
   **0 critical / 0 serious** 为硬门；键盘走查覆盖焦点顺序、Escape、
   focus-visible。
3. 性能预算（同一 production build、同一机器、同一测试数据）：
   - 以 0018 基线测量，冻结为 0019 budget；
   - CLS ≤ 0.1；本地受控 mobile production smoke LCP 目标 ≤ 3s；
   - 主 JS chunk 相对基线不得无解释回归（当前 1.10 MB / gzip 475 KB，
     来源为monaco-shiki 等大依赖，0019 允许通过 lazy 化改善，不允许恶化）；
   - 轮询不得造成无限请求；长列表与 Reader 无明显主线程卡死。
4. 安全与隐私复查（0018 G10 延续）：secret 扫描、tracked env 检查、
   DOMPurify 边界、危险 URL protocol、target blank、SSRF/归档/恢复
   防护回归、Caddy headers、日志脱敏、AI key 不回显、error payload 不泄密。
5. 备份恢复 disaster drill（隔离 compose 栈）：创建测试数据 → 完整备份 →
   checksum/manifest 验证 → WebDAV 上传/下载 → 修改状态 → 恢复 →
   readiness → 数据核对；损坏 checksum 拒绝、不兼容版本拒绝、
   中断恢复语义（0018 已实现的对账行为）。
6. 升级 / 回滚演练（disposable 数据）：0018 数据库 → 0019 迁移 →
   readiness → 核心流程 → rollback（恢复升级前安全备份的正式流程）。
7. CI 完整化（`.github/workflows/`）：docs 检查、敏感文件检查、Python
   3.12 + uv BFF tests、Node/pnpm Web tests+lint+build、Playwright
   Chromium smoke、compose config、concurrency/timeout、workflow_dispatch、
   E2E 失败 artifact；**不使用任何真实 FreshRSS/AI/WebDAV/生产凭据**。
8. 许可证与来源审查：依赖许可证清单、图标/字体来源、无未授权复制的
   上游资产；THIRD_PARTY_NOTICES 更新（如需）。
9. Operator 与 release 文档：production install、Caddy auth/noauth、TLS、
   health、logs、backups/WebDAV/restore、upgrade/rollback、DR、
   troubleshooting、数据所有权、secrets、最低资源、release notes、
   verification checklist。

## Responsive matrix

| 级别 | 视口 | 主题 | 覆盖 |
|---|---|---|---|
| 完整 | 1440×900 | light + dark | 全部桌面 journeys |
| 完整 | 1920×1080 | light | 全部桌面 journeys |
| smoke | 1920×1080 | system | 启动 + Reader + 设置 |
| 主路径 | 390×844 | light + dark | 全部移动 journeys |
| 完整 | 430×932 | light | 移动 journeys |
| 完整 | 375×812 | light | 移动 journeys |
| smoke | 390×844 横屏 | — | Reader 无横向溢出 |

## Accessibility gate

- axe：首页 / Reader / 订阅 / 设置 / operations / backup / restore / AI
  surfaces — 0 critical、0 serious；
- heading 顺序、landmark、label、button accessible name、dialog title；
- focus trap、Escape、focus-visible、不只靠颜色、reduced motion；
- 触控目标：项目既有设计系统规格（44×44 目标优先，遵循现有 primitives）。

## Performance budget（0019 冻结）

在 0018 production build（e5bdea0）上测量基线并记录于本文件执行记录；
预算 = 基线无回归 + 上述 CLS/LCP 硬门。测量方式：production build +
Playwright CDP metrics（本机受控环境）。

## Loading / empty / error / offline gate

主要数据面（时间线、订阅、AI 状态、operations、backup）在 loading、
empty、error 三态有明确 UI（0018 已达），0019 用 journey 断言覆盖；
offline/degraded 依赖 operations/status 的诚实降级展示。

## CI

现状：仅 `repository-checks.yml`（docs 存在性，PR + main push）。
0019 新增 `ci.yml`：BFF (Python 3.12 + uv) tests、Web (pnpm) test + lint +
build、Playwright Chromium deterministic smoke（自启动静态服务与 API
mock，不依赖真实上游）、compose config 校验、敏感文件检查、
workflow_dispatch。远程 CI 闭环：push 后触发 + `gh run watch` 至 green。

## Completion contract

仅当以下全部满足才允许判定完成：

1. 全部 journey（桌面/移动 × 主题 × 视口矩阵）通过；
2. axe 门 0 critical / 0 serious；
3. BFF 全量 pytest、Web 全量 vitest、lint、build 通过；
4. `pnpm test:e2e` 全绿；
5. performance budget 无未解释回归，硬门达标；
6. 安全与隐私复查项全过；
7. disaster drill 与 upgrade/rollback drill 完成并有证据；
8. CI 完整化且本地 parity 验证；push 后远程 CI green（或网络不可用如实
   记录，不算通过）；
9. 文档（operator/release notes/README/ROADMAP/milestone）与真实状态一致；
10. 0019 commit 推送远程功能分支，工作区干净，无 secret / runtime 文件。

## Rollback policy

- 分支级：`main` 未合并，不满足 contract 即不合入；发布物只来自已通过
  contract 的 commit。
- 部署级：upgrade 前必须有成功的安全备份；回滚 = 官方路径恢复该备份 +
  回退镜像 tag。数据库不做二进制降级（SQLite 向后兼容边界见 operator
  文档）：若新迁移引入不兼容 schema，唯一受支持路径是恢复升级前备份。
- 演练：C11 用 disposable 数据真实执行上述路径一次，命令与文档一致。

## Execution record（2026-09-05）

**Performance budget（冻结，0018 基线 vs 0019 实测）：**

| 指标 | 0018 基线 | 0019 | 结论 |
|---|---|---|---|
| 最大 JS chunk | 1,100.10 kB / gzip 474.85 kB | 相同（内容 hash 一致 cn2t-or2N4dp6.js） | 无回归 |
| LCP（本地 production smoke，桌面 1440） | 184 ms | 同环境 ≤ 200 ms | 达标（目标 ≤ 3s） |
| LCP（移动 390） | 112 ms | 同环境 | 达标 |
| CLS | 0 | 0 | 达标（≤ 0.1） |
| 轮询 | backup job 2s 仅在活动时 | 未变 | 无无限请求 |

测量方式：`apps/web/e2e/perf-measure.mjs`（Playwright + CDP，
LUMIRSS_E2E_BASE_URL 指向 production 栈）；bundle 体积取 `pnpm build`
输出。headless 下 LCP observer 偶发不回调（记 -1），以成功采样为准。

**A11y 修复（axe 发现 → 修复，全部有 e2e 断言护栏）：**

- EntryRow `role="row"` 无合法 table/list 祖先（critical ×13）→ 移除
  错误 role（li 已提供 listitem 语义）。
- 文本对比度（serious ×36+）：主题 token 调整——light
  secondary `#77747b→#64616a`、tertiary `#9b979f→#6a6770`；dark
  tertiary `#77757d→#9b99a2`（对最不利底色 ≥4.5:1，计算见测试记录）。
- accent 作为文字色在选中底上不足（3.05–4.32）→ 新增
  `--lumi-accent-text`（light `#4f59ce` / dark `#98a1ff`），Sidebar、
  SettingsModal、MobileTabBar、Operations 徽章、Backup 历史状态等
  32+ 处文字场景迁移。

**Journeys / drills 证据：**

- Playwright 全矩阵：48 passed（桌面 journeys 6、移动 journeys 4、
  0018 Flow A–E + WebDAV 7、a11y 7、移动 smoke 1、CI smoke 2；其余为
  按视口设计 skip）。
- Disaster drill（隔离 compose 栈）：readiness → 完整备份（lumi.sqlite +
  freshrss-data）→ 变更 Lumi 域状态（AI model）→ 恢复 → 数据核对
  （model 回滚为原值）→ 健康验证通过。FreshRSS 域状态（read/star）按
  架构归 FreshRSS 所有、不随 lumi 备份回滚（设计行为，非缺陷）。
- Upgrade drill：0018 → 0019 代码部署（migration 0003 幂等，无新迁移）→
  readiness 正常 → 核心 journeys 通过。Rollback = 恢复升级前安全备份
  （同上 restore 链路，已实测）。
- CI：`.github/workflows/ci.yml`（BFF / Web / Playwright CI-smoke /
  compose config），CI 冒烟在静态构建 + API 降级态下验证通过（本地
  parity 实测）。推送后远程 CI 以 `gh run watch` 验证。

## Verification checklist（发布前）

- [x] BFF：`uv run pytest` 全绿
- [x] Web：`pnpm test` / `pnpm lint` / `pnpm build` 全绿
- [x] E2E：`pnpm test:e2e` 全绿（本机 production 栈）
- [x] axe：0 critical / 0 serious
- [x] 性能：预算内、无回归
- [x] 生产栈 smoke：auth / TLS / 静态+API / 备份 / 恢复 / 重启持久化
- [x] 演练：disaster recovery + upgrade/rollback
- [x] 文档：operations.md / RELEASE-NOTES / README / ROADMAP / milestone
- [x] 无 secret / runtime 文件进入 Git
