# E2E 遗留问题清单（B/C 类）— 2026-09-06

> **✅ 已全部解决（2026-09-08 核验）**：B（J2 数据依赖）与 C1/C2（对比度
> token）、C3（移动 a11y 扫描含抽屉）的修复为 `f9e86fb` + `6bed703`
> （fix/article-switch-performance 分支，经 PR #34 进入 main，位于本任务分支
> 祖先）。修复后真实运行复核：J2 ×4、a11y 桌面 3 项 + 移动 4 项全绿。
> 证据见 [VALIDATION.md](VALIDATION.md) §2。下文为修复前的历史记录，保留存档。

> 来源：`fix/article-switch-performance` 分支上对本地栈（dev server + BFF + FreshRSS 容器）的全量 e2e 排查。
> A 类（过期分类名）已在 commit `ce975ca` 修复；本文档记录剩余两类，供另开修复任务使用。
> 基线对照：以下问题在未打补丁的 `17d517c` 上逐一复现，与性能修复无关。

---

## B — e2e 数据状态依赖（J2，desktop-1920/1440 两个项目失败）

| | |
|---|---|
| 位置 | `apps/web/e2e/desktop-journeys.spec.ts:96`（J2），失败点 `:109` |
| 现象 | `expect(unread.items.some(i => i.title === openedTitle)).toBe(true)` 失败 |
| 根因 | J2 隐式依赖「存在未读条目」的前置数据。本地 FreshRSS 数据集**所有条目 `read=true`**（首次验证即如此），且 J2 每次运行还会把打开的文章显式标记已读，反复运行持续污染。e2e 没有数据重置/隔离夹具。 |
| 复现 | `curl '…/api/v1/entries?view=all'` 确认全 `read=true`，再跑 `-g "J2"` |
| 影响 | 仅 e2e 可运行性。应用行为本身没问题——"打开不自动已读"的架构不变量没有被违反，是这个测试在当前数据下无法验证它。 |

**修复方向（任选其一）：**

1. **测试自建前置（推荐，幂等）**：J2 打开文章前，先用 set 语义 PATCH 把目标文章置为未读（`setEntryState(entryRef, { read: false })` 经 UI 或直接 `page.request.patch('/api/v1/entries/<ref>')`），再执行"打开 → 仍在未读视图"断言。不依赖种子状态，可重复运行。
2. **e2e 数据夹具**：完整栈跑法提供 run 前重置（把测试订阅源条目批量置未读的脚本/endpoint）。

---

## C — a11y 对比度 token 违规（axe `color-contrast`，wcag2aa 1.4.3，serious）

两条 token 组合低于 WCAG AA 的 4.5:1，都是**既有设计 token 问题**（与组件重构无关）。

### C1：tertiary 文字 on 选中表面 = 4.43:1（差 0.07）

- **前景** `#6a6770`（`--lumi-text-tertiary`），**背景** `#e7e5e9`（`--lumi-surface-selected`），11px/12px normal 字重
- **命中元素**（首页扫描 58 节点 / Reader 扫描 128 节点）：
  - Sidebar 选中分组容器（`RssTree` 的「全部信息源 + 未读」wrapper `bg-[var(--lumi-surface-selected)]`，`Sidebar.tsx:452`）内的导航按钮（`button.mr-1.5`）
  - 选中的文章行：`EntryRow`/`EntryCard` 行根 `bg-[var(--lumi-surface-selected)]` 上的次要文字
- **出现的测试**：`a11y — 首页`、`a11y — Reader`（desktop-1440）；移动端 `a11y — 设置` 扫到的 1 个违规也是它（抽屉在设置 Sheet 下仍开着被扫进去，见 C3）
- **修复方向**：选中表面上的 tertiary 文字改用 secondary token；或调深 `--lumi-text-tertiary` / 调浅 `--lumi-surface-selected` 使组合 ≥4.5:1。token 真源在 `docs/design/design-system.md` + `tokens.css`，改后跑 `a11y.spec.ts` 用 axe 复测。

### C2：白字 on danger 红 = 4.1:1

- **前景** `#ffffff`，**背景** `#b8656b`（`--lumi-danger`），14px/12px
- **命中元素**（设置-数据控制页扫描 93 节点）：危险动作按钮——「恢复默认设置」的「重置」、「清除本地缓存」的「清除」等 danger 按钮
- **出现的测试**：`a11y — 设置`（desktop-1440）。此前该测试卡在旧分类名根本进不了数据控制页，属于 A 类修复（`ce975ca`）后才暴露
- **修复方向**：调深 `--lumi-danger` 使白字对比 ≥4.5:1（或危险按钮改用深一档的 danger 背景）。同样以 token 调整 + axe 实测为准。

### C3：测试侧注记（配合 C1 修复时跟进）

移动端 `a11y — 设置` 的扫描用 `include('[role="dialog"]')`，而**设置 Sheet 在导航抽屉之上打开、抽屉不自动关闭**——扫描会同时扫到抽屉里的 Sidebar，把 C1 的违规算到设置测试头上。修掉 C1 后该测试大概率转绿；若想彻底解耦，可在扫描前把抽屉关干净（参考 `mobile-journeys.spec.ts` 的 `closeMobileSettings` helper，commit `ce975ca`）。

---

## 环境备注（非问题；解释本地全量跑的剩余失败）

- **milestone-0018 Flow C/E、webdav**：依赖 `docker-compose.prod` 拓扑——BFF 容器挂载 FreshRSS 数据卷。宿主机 BFF + 容器 FreshRSS 的本地组合下备份 job 全部 failed（`"FreshRSS data directory is not configured for backup."`），WebDAV mock 地址默认 docker 网桥（`172.19.0.1`）。这两类 spec 是 **docker 栈专用**，改名后（`ce975ca`）在完整栈上应可通过。
- **CI**（`.github/workflows/ci.yml`）的 e2e 门只跑 `ci-smoke.spec.ts`（静态构建 + API 降级态）；journeys / a11y / milestone / webdav 套件按 `playwright.config.ts` 注释的设计需要**手动对完整栈**运行，所以 B/C 问题从未被 CI 拦截。

## 当前状态（fix/article-switch-performance @ ce975ca）

| 测试组 | A 修复前 | A 修复后（本地栈） |
|---|---|---|
| mobile-journeys M1 ×3 | ❌ 旧分类名 | ✅ 通过 |
| mobile-journeys M4 ×3 | ❌ 旧分类名 + 重开竞态 | ✅ 通过（单会话导航 + 确定性关闭） |
| mobile-journeys M2/M3 | ✅（M3 需全量跑中 desktop-journeys 先配置 mock AI） | ✅ 同左 |
| a11y — 设置 ×2 | ❌ 旧分类名 | ❌ 收敛为 C1/C2（token 问题） |
| a11y — 首页/Reader ×2 | ❌ C1 | ❌ C1（待修 token） |
| J2 ×2 | ❌ B | ❌ B（待修数据前置） |
| milestone-0018 / webdav ×4 | ❌ 旧分类名 | ❌ 收敛为 docker 栈依赖（改名已生效） |
| rapid-selection（新增）×5 | ✅ | ✅ |
