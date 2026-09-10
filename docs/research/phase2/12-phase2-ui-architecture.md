# 12 Phase 2 UI 总体设计

> 公共视觉体系不变:柔和低饱和、淡靛主强调、现有卡片/圆角/Typography、
> Base UI primitives、`--lumi-*` tokens。**不做 Notion/Obsidian/Karakeep 克隆。**

## 1. Executive decision
**RECOMMENDED** — UI 层统一收敛在 **UnifiedContentCard(展示投影)** 与
既有三栏/移动五屏骨架;存储不强求一致(00 号原则的 UI 面)。

## 2. 灵感来源(提取模式, 不复制界面)
Karakeep(卡片网格+过滤器)、Linkwarden(列表密度切换)、Omnivore(阅读
队列节奏)、Readwise Reader(队列=工作区)、Obsidian(图谱只读模式)、
Folo(时间线分组头)。只提取 interaction patterns:双列密度、域徽标、
队列排序、建议态样式。

## 3. 统一组件策略

```text
UnifiedContentCard(展示投影, 输入是 ViewModel 而非数据模型)
  props: {ref, kind, title, source, datetime, excerpt?, actions[]}
  kind: rss | bookmark | clip | snapshot | api_item | newsletter | note
  · 卡片右上角域徽标(RSS/库/快照…) —— 永远诚实标注执行位置/来源域
  · 动作区由 kind 决定(打开原文/进阅读器/加入工作区/打标签)
存储模型不统一(00 号), 卡片只消费 BFF resolve 后的同形 ViewModel。
```

## 4. 信息架构(IA)增量

```text
桌面侧栏(现结构上增组):
  时间线 · RSS 订阅 · 收藏 · 搜索 · 稍后读
  工作区(组): AI 研究 · 考研 · … [+ 新建]
  知识(组): 标签 · 图谱 · Obsidian 库
  Agent 工作台
  设置
Phase 2 占位点亮顺序按 13 号路线图; 占位未点亮时保持现有"Phase 2"角标。
移动: 底部 Tab 恒为 首页/订阅/搜索/收藏 —— Phase 2 一律经"更多"或卡片
动作进入, 不新增底部 Tab(移动 IA 不受冲击红线)。
```

## 5. 关键页面模式
- 列表页统一骨架:工具栏(搜索/过滤/密度)+语义列表+opaque cursor 分页。
- 阅读器唯一(RSS/clip/note 共用 ArticleContent+翻译/AI 全链路)。
- 图谱/Agent 为两类新"全屏页",其余均为列表+详情既有模式。

## 6. States/a11y 统一基线
每页 6 态(empty/loading/success/error/offline/permission)沿用 01-11 各
报告;全局规则:域徽标带文字、44px 触控、role=status/alert、reduced-motion、
键盘等价操作(排序/图谱/审批)。

## 7. 无障碍与视觉回归
新增组件进 `components/ui/` 仅限原语;特性组件禁止直接 import Base UI;
对 UnifiedContentCard 增加深浅色快照测试与 axe 扫描(并入现有 e2e a11y)。

## 8. Gates
```text
Gate 0: UnifiedContentCard + 域徽标(先行, 被所有列表复用)
Gate 1: 工作区/知识侧栏组(占位点亮跟随功能 Gate)
Gate 2: 移动"更多"入口
```

## 9. Expected commits
```text
feat(ui): unified content card and domain badges
feat(ui): phase2 sidebar groups and mobile more-menu entries
```

## 10. Standalone ZCode implementation prompt
```text
你在 LumiRSS 仓库。实施 docs/research/phase2/12-phase2-ui-architecture.md 的
UnifiedContentCard 与侧栏/移动 IA 增量。硬约束:遵循 AGENTS.md UI 规约
(组件不得直用 Base UI、语义 tokens、44px、reduced-motion);卡片消费
ViewModel 而非泄漏存储模型;移动底部 Tab 不变。先写组件+快照测试再接页面。
```
