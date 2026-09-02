# 0014a — UI Acceptance & Navigation Consistency

> Status: **In Progress** · Branch: `fix/0014a-ui-acceptance-navigation`
> Created by Gate 0 (2026-09-02) on top of `feat/0014-source-discovery-rsshub`
> (`be5f80f`).

## Why this milestone exists

0014（Source Discovery & RSSHub Integration）通过了全部自动化测试，但
**post-implementation 人工/视觉验收**发现了若干真实 UI 接受度缺陷：

**Primary defects (A–D)**

```text
A. Desktop Web 无法轻易找到「添加来源」——添加来源入口目前位于
   移动端的订阅管理页（SubscriptionsPage），桌面浏览路径（Sidebar +
   Timeline + Reader）没有可发现入口。

B. 移动端从「收藏」选择文章后，没有进入全屏 Reader 视图：收藏列表
   section 仍然占用布局空间，与 Reader 形成垂直分屏（预期是列表 →
   全屏 Reader → back 原列表）。

C. 设置里仍存在 stale 的 FreshRSS / RSSHub “planned” 标签
   （如「账户与服务」里的 FreshRSS 状态 planned · 0013），与
   已经真实存在的 0013/0014 能力（订阅管理、OPML 导入导出、
   RSSHub 来源发现/预览）互相矛盾。

D. 0014 没有获得真正的 Playwright 实机点击验收（当时 Playwright MCP
   配置已持久化但需重启 OpenCode 才生效；0014 最终以 DOM 级测试 +
   live smoke 收口）。
```

## Goal

关闭 0014 之后发现的真实浏览器/UI 接受度缺口，并在 AI 工作开始前确立
统一的来源入口（Add Source）与文章打开（Reader）语义：

```text
Any normal article-list surface（首页/订阅列表/收藏/稍后读/未来的搜索）
        ↓ 点击文章
        full-screen mobile Reader（移动）；分栏（桌面）
        ↓ back
        回到来源列表（section / scope / view / 位置 保持不变）
```

## Scope

- Desktop/tablet/mobile 均有直观、一致的「添加来源」入口；
- 移动端所有正常文章列表 → 全屏 Reader → back 语义一致；
- 设置中 FreshRSS / RSSHub 能力标识与现实一致（01 已实现 / 0018
  运营 / 无过期重复）；
- **真实 Playwright 桌面 + 移动验收**（0014a 完成的前置条件）。

## Non-goals（本 milestone 明确不做）

- 不重设计整个应用；不引入新的路由框架；
- 不新建第二个 AddSourceDialog / 第二套订阅逻辑；
- 不创建新的复杂 FreshRSS 健康系统；
- 不实现 0018 RSSHub Control Center / FreshRSS 运营集成 / WebDAV；
- 不实现 0015 AI / Lumi SQLite 持久化；不开始 0015–0019 实现。

## Gates

```text
Gate 0 — 基线 + Spec + 分支（本文件）
Gate 1 — Desktop 添加来源可发现性（Sidebar 入口 ↔ 既有 AddSourceDialog）
Gate 2 — 移动端收藏 → 全屏 Reader（App 布局契约修复）+ 回归测试
Gate 3 — FreshRSS / RSSHub 设置界面真实性（分类 stale 标签清理）
Gate 4 — Playwright 桌面 + 移动实机验收（当前代码，无旧 dev server）
Gate 5 — 0014a 插入路线图 + 0015–0019 产品决策修订（文档）
Final — 全量测试 + lint + build + 验收矩阵 + 最终 commit
```

## Gate Progress

### Gate 0

Status: In Progress (2026-09-02)

- 基线：`feat/0014-source-discovery-rsshub` @ `be5f80f`（0014 Final
  commit），working tree clean；
- 分支：`fix/0014a-ui-acceptance-navigation`；
- 0014 保持历史状态为 Completed（重编号不做；0014a 是 post-0014
  验收 follow-up milestone，保持可追溯性）。
