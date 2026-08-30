# Devlog 0010 — Settings Center & Adaptive Shell

> 日期：2026-08-29 ~ 2026-08-30
> 分支：feat/0010-settings-center-adaptive-shell（基于 main @ 6686eea，
> 即 PR #15 合入后的 0009 完整基线）
> Spec：docs/specs/0010-settings-center-adaptive-shell.md（AC1–AC26 达成）
> + 0010a 扩展轮 docs/specs/0010a-settings-expansion-and-reader-style.md
> （AC1–AC31 达成；用户四项决策：不做自造源/ P1 本轮/实验性开关/0011 插入）
> 结论：**BFF 零变化、纯前端设置持久化、产品骨架完成**。

## 一句话总结

用 Folo 式设置中心（声明式设置行 + 最终 13 分类）、信息来源/工作区分组的
侧栏、可拖拽折叠的三栏、<768px 底部 Tab + push 式全屏设置、Lumi Mist 统一的
进度看板，以及 0010a 扩展轮的外观/阅读样式深度自定义（accent 色板/字体族/
自定义 CSS/排版预设）与 OrigRead 四页复刻（翻译/过滤/RSSHub/加密备份）——
把 0009 的视觉地基升级成了完整的产品骨架，全程零后端改动。

## Gate 时间线

| Gate | 日期 | 内容 | 用户批准 |
|---|---|---|---|
| A | 08-29 | app-settings store + SettingItem 渲染器 + SettingsModal 框架 + 遮罩关闭 bug 修复 | ✓ |
| B | 08-29 | 快捷键 j/k/u/s + 全部分类页（5 真实 + 4 planned）+ cache key bug 修复 | ✓ |
| C | 08-29 | 侧栏信息架构 + 三栏拖拽/折叠/持久化 + 分隔条塌陷 bug 修复 | ✓ |
| D | 08-30 | 底部 Tab + 移动全屏设置 + 看板双修订 + 文档 v6.1 | ✓ |
| E（0010a） | 08-30 | 移动设置 Folo 重设计 + 分类 13 + 通用页 4 项 | ✓ |
| F（0010a） | 08-30 | 外观 5 项 + 阅读 P0/P1 + OrigRead 四页 | ✓ |
| G（0010a） | 08-30 | 备份往返 16/16 + 矩阵 10/10 + 文档 v6.2 + 看板 0011 插入 | 待最终验收 |

## 关键设计决策

1. **声明式设置行**（Folo setting-builder 模式，inspired）：新增一项
   设置 = 加一行数据对象；四型条目自动映射控件；测试断言按语义写。
2. **诚实原则两次纠偏**：「侧栏隐藏已读」需要 feeds unreadCount 契约，
   一度想"先存偏好暂不生效"——识别出这就是假控件，改为 planned·0011。
3. **设置持久化单 key + 逐字段归一化**：损坏 JSON/非法枚举回退默认；
   旧 lumirss-theme / lumirss-reader-bg 首次加载自动迁移并入。
4. **移动端设置 = 全屏页而非 Modal**（Folo 同款策略）：Dialog 增加
   `fullscreenOnMobile` 变体；左导航在手机上变顶部横向滚动 chip 条。
5. **分隔条手写 pointer events**：不引入 re-resizable 依赖
   （Folo 用它但我们零依赖原则）——clamp + 键盘 + 双击重置全手写。
6. **看板双修订**：内容（0010 插入 + 0011–0017 顺延 + Phase 6 更名
   Product Shell）与样式（Lumi Mist Light/Dark 内联变量副本 + 主站
   字体栈；零依赖约束不变，Dark 跟随系统）。
7. **0010a 架构决策（用户批准）**：不做自造源（JSON 规则/网站解析
   规则）——违反冻结架构，由 RSSHub 承担（0013）；阅读样式 P1 归
   本轮；滚动已读做实验性开关（正式版 0016）；插入 0011 Reader Style
   Deep Customization（原 0011–0017 → 0012–0018）。
8. **移动端设置 = 分组列表 + push 子页**（Folo mobile 同款）：分类
   内容组件（CategoryPage）桌面/移动共享，外壳各自实现。
9. **主题 = CSS 变量快照**：排版预设切换即批量写变量；派生 +
   导入导出 JSON 形成分享雏形（Web 阅读器无先例，0011 差异化）。
10. **无密钥备份不清空本机凭据**（OrigRead 语义）：加密往返实测发现
    违反处并修复。

## 验证证据（全部真实运行）

```text
Web:  244 tests passed（162 基线 + 82 新增：gate-e 13 + gate-f 23 +
      app-settings 扩展 + 既有断言适配）
lint: 0 errors / 2 warnings（React Compiler 优化跳过提示）
build: 成功
BFF:  121 passed，services/bff 全程零改动
实测: 拖拽 240→277 + 刷新恢复；双栏折叠/展开 + 持久化；双击重置；
      键盘 j/k/u/s 真实浏览器；9 个 Phase 2 徽标；移动端设置
      分组列表 + push 子页 + 零溢出；accent 色板全站生效；排版预设
      一键切换全套变量；自定义 CSS 前缀注入；自定义深色背景自动浅
      文字（WCAG）；显示层过滤生效；加密备份往返 16/16（导出无明文
      Key/错误密码拒绝/往返恢复/非法文件拒绝/无密钥恢复保留 Key）；
      视口矩阵 10/10；看板 Light/Dark × 3 视口零溢出
```

## 实测发现的真 bug（jsdom 测不出的四个）

1. **Query cache key 不匹配**：快捷键构造 `['entries', {view}]`，
   useEntries 实际是 `['entries', {view, feedUrl}]`——单测预置缓存
   用了同一个错误 key 所以"假绿"；真实浏览器 j/k 完全失效。修复：
   key 构造对齐 + 单测 key 同步修正。
2. **PaneSeparator 高度塌陷**：`hidden lg:block` wrapper 在 flex-row
   中不拉伸 → 分隔条 height=0 完全不可点。修复：wrapper 改
   `lg:flex` + 分隔条 `self-stretch`。
3. **移动端设置布局损坏（用户报告）**：Gate D 的 Dialog+chip 条方案
   容器缺 `max-md:flex-col`，内容区被挤出视口、chips 被 stretch 拉成
   763px 竖条；根因是验证只测 isVisible 没查视觉。修复：按 Folo
   移动端模式重设计（分组列表 + push 子页）。
4. **CSS 前缀解析器嵌套配对**：`indexOf('}')` 命中嵌套块内层 `}`
   → @media 整段拒绝。修复：深度配对 matchingClose。

另两个：无密钥备份恢复清空本机 API Key（违反 OrigRead 语义，加密往返
实测发现并修复）；0009 遗留 Dialog 遮罩点击从不生效（e.target ===
e.currentTarget 永假）。

## 流程事故与恢复（如实记录）

Gate D 验证看板 390 溢出时，为隔离变量误用了 `git stash` +
`git checkout main -- index.html` 的组合，导致工作区修改被吞进
stash。**立即发现并通过 `git stash pop` 完整恢复**（208 tests 复跑
全绿确认无丢失）。教训：对比测试应复制文件到 /tmp 而非动 git。

## 遗留与后续

- Reader 排版三档（字号/行高/宽度）已接线 CSS 变量并实测生效；
- 快捷键为基础集（j/k/u/s），完整体系（Folo 数十个）不做；
- 「侧栏隐藏已读」待 0012 feeds unreadCount 契约（已记录缺口）；
- 翻译/RSSHub 配置已存 localStorage，0015/0013 激活执行与测试；
- 过滤规则当前显示层，0012 迁移 BFF 读取层；
- 主题/设置 localStorage 偏好在 0016 统一设置时迁移服务端；
- 768–1023 区间无设置入口（既有力学空白，0011 或后续补）；
- 滚动已读实验版 → 0016 正式化；
- 旧 store/theme.ts 与 lib/reader-bg.ts 保留兼容一个版本，
  0011 顺手退役。

## 下一步

0011 — Reader Style Deep Customization（字体导入/中文排版/主题包
分享/Bionic Reading——调研依据 docs/reference/reader-style-survey.md）；
之后 0012 — Unified Subscription Center（首个真实后端里程碑：
FreshRSSControlAdapter 控制平面 + 订阅 CRUD + OPML + 过滤 BFF 层）。
