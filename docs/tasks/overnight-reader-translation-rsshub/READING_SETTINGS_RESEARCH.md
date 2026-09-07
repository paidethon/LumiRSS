# READING_SETTINGS_RESEARCH.md — 微信读书 / Legado / LumiRSS 阅读设置对照

> 对象界定（按任务要求）：「微信阅读」按 **微信读书（WeRead）** 调查；「开源阅读」按 **Legado** 调查。
> 证据来源与日期：微信读书=官方帮助页（2026-09-07 抓取，覆盖面极小，无法核验项一律标注）；Legado=**CCSSNE fork**（gedoor 官方库已清空，fork HEAD `aa8819f`，GPL-3.0，内容可能滞后）。
> 详细证据（路径+符号）：`/home/zephyr/projects/research/reports/reading-settings-research.md`
> LumiRSS 证据：`apps/web/src/store/app-settings.ts`、`lib/reader-style.ts`、`components/ReaderAaPanel.tsx`、`components/settings/reader/*`、`index.css`（--lumi-reader-* 变量）。

## 0. LumiRSS 已实现盘点（不重复列为"新增"）

以下全部已实现（0012/0017 + 外观设置），对照时以此为基线：

字体族（含自定义字体导入 readerCustomFontId/readerFontUrl，ReaderFontManager）、字号（readerFontSize）、行距（readerLineHeight）、段距（readerParagraphSpacing）、内容宽度（readerContentWidth）、页边距（readerPageMargin）、两端对齐（readerJustify）、首行缩进（readerTextIndent，含 CJK 全角语义）、标点悬挂（readerHangingPunctuation，@supports 渐进增强）、背景（5 套内置预设 + 自定义色 + 基于 WCAG 亮度推导正文色的 readerTextPalette + 用户自建预设 readerPresets）、自定义 CSS（prefixCustomCss 以 .lumi-reader 作用域注入）、图片模式（readerImageMode）、简繁转换、词首强调、代码高亮+主题、阅读时间显示、App 明暗主题与 Reader 背景分离（--lumi-reader-* 变量族）、Aa 快速面板（与设置中心同一 settings source）、设置即时预览、预设一键应用。

## 1. 三方对照与差距分析

| 维度 | 微信读书（官方证据） | Legado（fork 源码证据） | LumiRSS 现状 | 差距/建议 | 优先级 |
|---|---|---|---|---|---|
| 字体文件导入 | 无法核验 | `textFont` 自定义字体文件 | ✅ readerCustomFont/FontUrl 导入 | 已对齐 | — |
| 字号/行距/段距/缩进 | 无法核验 | `textSize/lineSpacingExtra/paragraphSpacing/paragraphIndent` | ✅ 全部有（缩进为 CJK 全角语义） | 已对齐 | — |
| 字重/字距 | 无法核验 | `textBold`(0/1/2)、`letterSpacing` | ❌ 字重不可调、字距不可调 | 新增：字距滑杆（CSS letter-spacing）成本低；字重（font-weight 档位）次之 | P2 |
| 两端对齐 | 无法核验 | `textFullJustify` + 中文禁则 `useZhLayout` | ✅ readerJustify（text-justify: inter-ideograph 已有中文排版处理） | 基本对齐；完整禁则（避头尾）依赖浏览器，暂无法推进 | P2 |
| 背景/主题 | 多背景色+夜间模式（官方） | 多套样式 + 日/夜/墨水屏三态独立背景 + 透明度 | ✅ 预设+自定义色+预设体系；夜色=App 主题分离 | 差距：背景不随明暗主题自动双套（Legado 三态）。建议：背景预设记录 light/dark 两值，随主题切换 | P1 |
| 页面几何 | 无法核验 | 四向边距+页眉页脚 | ✅ readerPageMargin（统一边距） | 可细化四向，但收益低 | P2 |
| 翻页模式 | 无法核验 | 五种 delegate + 墨水屏自动无动画 | ❌（滚动阅读为唯一形态，符合 RSS 流式内容） | **不建议**引入分页/仿真引擎（RSS 流式内容 + DOM 渲染与 Canvas 自绘书籍不同构；任务红线：不上复杂分页引擎） | 不做 |
| 进度/目录 | 官方：工具栏含目录/进度按钮 | 目录界面+进度弹窗+点击区域自定义 | RSS 无"章节"概念；单篇无目录 | 不适用（内容形态不同） | — |
| 章节内搜索 | 无法核验 | SearchMenu 浮层，上一处/下一处高亮 | ❌ 文章内搜索 | **新增**：文章内搜索浮层（浏览器原生 Ctrl+F 已覆盖单篇；自建可做高亮计数，收益中等） | P2 |
| 朗读 TTS | 官网提"听书"，设置无法核验 | 系统 TTS + 自定义在线源，语速/定时 | ❌ | 新增：Web Speech API（浏览器免费本地）实现朗读——与翻译"运行位置"哲学一致 | P1 |
| 标注/书签 | 无法核验 | Bookmark 实体+选中操作条 | ❌ | 新增：划线/书签（涉及 Lumi SQLite 新表与选中菜单，成本高） | P2（单独立项） |
| 亮度/护眼 | 太阳按钮仅述背景色（官方） | 亮度滑杆+墨水屏模式 | ❌（网页无法控制系统亮度；滤镜调暗可行） | 不建议（Web 平台边界；夜间主题已覆盖主诉求） | 不做 |
| 配置导入导出 | 无法核验 | readConfig.zip（配置+字体+背景） | ✅ 已有「配置迁移」导出/导入（数据控制页，含阅读设置） | 已对齐 | — |
| Aa 面板一致性 | 工具栏一键唤出（官方） | ReadMenu 菜单 | ✅ Aa 在阅读工具栏，与设置中心同源 | 已对齐 | — |

## 2. 本次落地情况与后续路线

本次（时间约束）未新增阅读设置项；已完成与之强相关的：双语模式完整继承同一套阅读排版变量（--lumi-reader-* 与 .lb-translation 叠加，见 d3cf014），保证"双语模式下阅读样式不打折"。

后续路线（按优先级）：
1. **P1 背景双主题化**：预设/自定义背景各存 light+dark 两值，随 --lumi-reader 主题切换；接入点 `app-settings.ts` + `reader-style.ts:resolveReaderBackground`（现有 resolveTheme 机制可直接复用）。
2. **P1 本地朗读**：Web Speech API（speechSynthesis），设置：语速/音色/定时停止；运行位置="此浏览器"；接入点 ReaderHeader 工具栏 + Aa 面板。
3. **P2 字距/字重滑杆**：CSS letter-spacing/font-weight 档位，接入 Aa 面板与 PortableSettings。
4. **P2 文章内搜索**：自建高亮浮层或先验证浏览器 Ctrl+F 满意度后再立项。
5. **P2 划线/书签**：需 Lumi SQLite 新表 + 选中菜单，建议独立 milestone。
