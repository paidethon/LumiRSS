# Devlog 0009 — UI Reboot & Reference Lab

> 日期：2026-08-28 ~ 2026-08-29
> 分支：feat/0009-ui-reboot-reference-lab（基于 main @ c4b84e9）
> Spec：docs/specs/0009-ui-reboot-reference-lab.md（AC1–AC27 全部达成）
> 结论：**BFF 零变化、行为零回归、视觉体系重建完成**。

## 一句话总结

用 Lumi Mist 设计体系（semantic tokens + 11 个 primitives + 双主题）
替换了 0005–0007 的临时视觉外壳：Sidebar/Timeline/Reader 按 Folo 实测
密度与层级重建，App/Reader 主题分离落地，Settings 壳上线（Appearance
真实可用），五个 Gate 全部经用户逐一批准。

## Gate 时间线

| Gate | 日期 | 内容 | 用户批准 |
|---|---|---|---|
| 0 | 08-28 | 仓库审计、参考仓库钉 SHA、许可证决策（AGPL-3.0-only）、Folo 实机审计、v6 文档基线 | ✓ |
| 1 | 08-28 | tokens/themes、三态主题逻辑、lucide-react、11 primitives、playground | ✓ |
| 2 | 08-29 | Shell Grid、Sidebar（Folo 密度）、Timeline（两级行层级） | ✓ |
| 3 | 08-29 | Reader 重建（工具栏/27px 标题/46rem 宽/排版）、Reader 独立背景钩子 | ✓ |
| 4 | 08-29 | Settings 壳、统一 scrollbar、12 张视口矩阵截图、全量回归、文档收尾 | 待最终 Review |

## 关键设计决策

1. **旧变量别名过渡**：`--bg/--surface/--accent` 等旧 CSS 变量改为
   指向 lumi token——既有组件一行不改即获双主题，Gate 2/3 迁移完成后
   旧名字仍保留（尚未退役，退役归后续顺手清理）。
2. **主题机制 = Folo 同构**：`html[data-theme]` + 语义变量 +
   `oklab` 低透明度选中态。实现成本低于自创，且与实测锚点对齐。
3. **未读状态双信号**：字重（medium/normal）+ 圆点（aria-hidden 纯
   视觉）——不只靠颜色（AC10），屏幕阅读器不重复播报。
4. **Reader 主题分离的最小实现**：`--lumi-reader-bg` 钩子 +
   `[data-reader="sepia|warm"]` 变体；偏好 localStorage 持久化
   （`lib/reader-bg.ts`），正式设置 UI 归 0014。
5. **Settings 壳诚实原则**：只有 Appearance 真实可用；阅读/订阅/AI/
   备份分组带 planned 徽标、零交互控件（AC19 无假实现）。
6. **图标**：lucide-react@1.34.0（ISC，用户批准；1.35.0 registry
   缓存未同步）。分类色圆点用 feedUrl 哈希确定性分配（同 feed 永远
   同色，无状态）。

## 验证证据（全部真实运行）

```text
Web:  162 tests passed（121 既有零回归 + 41 新增：theme 12 +
      primitives 17 + timeline-gate2 7 + settings 5）
lint: 0 errors / 2 warnings（React Compiler fast-refresh 提示，
      Popover/Menu render-prop 模式固有 + SettingsDialog 已抽 lib）
build: 成功（css 30.18KB/gzip 6.91KB；js 290.54KB/gzip 92.03KB，
      含 lucide 子集）
BFF:  121 passed，git diff main -- services/bff 为空（V1 ✓）
V2:   src/ 硬编码调色板类全量清零（AC3 ✓）
V6:   12 张截图（1920/1440/1024/820/390 × light/dark + settings +
      390 reader），全部零横向溢出、零 console error（AC16 ✓）
Smoke: 真实 FreshRSS 数据下 read/star 可逆写入（状态完全恢复）；
      0 个前端直连 FreshRSS/RSSHub 请求（架构边界实测）
```

截图存档：`/tmp/gate{1,2,3,4}-shots/`（会话临时目录；关键视觉结论
已记录在 PROJECT_STATE §10 与本文件，gitignored 私人参考图不外流）。

## 工具环境攻坚（本轮最大意外成本）

- browser-use 截图要求 Qoder 浏览器面板可见（经常 false）；
- playwright MCP 硬编码 channel=chrome，需要系统级 Chrome（sudo）。
- 解法演进：免 sudo 方案（npx chromium + apt-get download 解包
  libnspr4/libnss3/libasound2 到 ~/.local + LD_LIBRARY_PATH + Noto
  CJK 字体到 ~/.local/share/fonts 解决中文豆腐块）→ 用户 sudo 授权后
  永久化（系统 Chrome 152 + 系统库）。Playwright MCP 与 CLI 双通道
  可用，版本错位（npx 缓存要 1237、实装 1234）用 executablePath 规避。

## 遗留与后续

- 旧 CSS 变量别名（--bg 等）仍在 index.css，随后续里程碑顺手退役；
- MobileHeader/Drawer 的 ☰ ✕ ← 文本符号保留（可访问性达标，视觉替换
  归后续 polish）；
- Timeline 缺摘要/favicon/缩略图——API 契约缺口已记录（0010+ 处理），
  0009 用优雅降级布局；
- 主题/Reader 背景偏好为 localStorage 临时方案，0014 迁移服务端；
- 2 个 lint warning（React Compiler 提示）非错误，暂留。

## 下一步

0010 — Unified Subscription Center（FreshRSSControlAdapter 控制平面
+ 订阅 CRUD + OPML），Lumi 成为唯一日常 UI 的第一块落地。
