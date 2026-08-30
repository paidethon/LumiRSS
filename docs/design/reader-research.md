# 阅读器样式自定义调研报告（0010a 决策依据）

> 日期：2026-08-30
> 用途：0010a Gate F 阅读样式 P0/P1 实现依据 + 新 0011 里程碑
> （Reader Style Deep Customization）的范围来源。
> 方法：10+ 高 star RSS 阅读器 / 稍后阅读 / 网页阅读器的公开文档与源码
> 调研（Folo/OrigRead 源码另见 UPSTREAMS.md）。

## 一、逐项目摘要

| # | 项目 | 平台 | Star | 样式自定义能力 | 实现方式 |
|---|------|------|------|---------------|---------|
| 1 | Reeder | iOS/macOS 闭源 | — | 主题配色（黑/半黑/白/米）、字号、行距、对齐、灰度图片、Bionic Reading | 原生预设面板 |
| 2 | Readwise Reader | Web/移动 SaaS | — | 字体族（含无障碍字体）、字号 14–80px、行距、宽度档、light/dark/auto、快捷键实时调节、分页滚动 | Aa 面板 + 服务端偏好 |
| 3 | Miniflux | Go 自托管 | 9.6k | 6 组主题（light/dark/system × serif/sans）、**每用户自定义 CSS + 自定义 JS + 外部字体域名白名单** | User 表 Stylesheet 字段注入 style |
| 4 | FreshRSS | PHP 自托管 | 15k | 多套官方主题、密度扩展、CustomCSS 扩展注入用户 CSS | 主题包目录 + 扩展机制 |
| 5 | Tiny Tiny RSS | PHP（官网 2025-11 关闭） | — | 主题选择 + 偏好级自定义 stylesheet（CSS 变量改字体/间距） | themes.local + 偏好注入 |
| 6 | NetNewsWire | Swift 开源 | 10.3k | 字号、衬线切换、**第三方 .nnwtheme 主题包导入/删除** | 主题包 = Info.plist + css + html 模板 |
| 7 | NewsBlur | 开源 Web/移动 | 7.6k | 字号 XS–XL、行距 XS–XL、字体族（免费 2 + Premium 商业字体 4）、正文位置 | 服务端偏好 + body class |
| 8 | Wallabag | PHP 自托管 | ~11.5k | 两套主题，排版自定义弱（反例） | 主题 CSS |
| 9 | Instapaper | SaaS | — | 字体（含 Atkinson Hyperlegible）、字号、行距、亮度、白/米/黑 | Aa 菜单 |
| 10 | Pocket | SaaS | — | **2025-07-08 停服** | — |
| 11 | Matter | iOS/Web | — | 免费版可自定义主题字体、TTS | Aa 菜单 |
| 12 | Omnivore | 开源（服务已死） | — | 2024-11 关闭 | — |
| 13 | **Legado 阅读3.0** | Android 开源 | **46k** | **天花板级**：TTF/OTF 字体导入、字号/字重/颜色、行距+段距分离、缩进、简繁转换、背景（预设+图片） | ReadBookConfig 参数化 |
| 14 | Read You | Android 开源 | ~5k | Material You 动态取色、AMOLED 纯黑、字号、行间距、Bionic Reading | Compose 本地偏好 |
| 15 | CommaFeed | Java 自托管 | ~3k | light/dark、4 布局、**设置页内置 CSS/JS 编辑器** | 服务端注入 |
| 16 | Raven Reader | Electron | ~3k | 4 主题、4 款内置 Web 字体 | 预设 + 打包字体 |

来源：GitHub 仓库与官方文档（readwise docs、tt-rss themes 文档、netnewswire ArticleTheme.swift、newsblur story_options_popover.js、miniflux user.go 等）。

## 二、功能维度全集（去重 Checklist）

**A 字体**：字体族（衬线/无衬线/等宽分通道）/ 字号档位+快捷键实时调 / 行距 / 字距+段距分离 / 字重 / 一键衬线切换 / 无障碍字体（Atkinson Hyperlegible、OpenDyslexic）/ 字体导入 / 尊重系统字号

**B 版式**：正文宽度 measure / 正文位置 / 页边距 / 两端对齐 justify / 段距 vs 首行缩进（中文） / 分页滚动 / 阅读进度 / 长文目录

**C 颜色主题**：light/dark/auto 三态（标配）/ sepia 护眼 / AMOLED 真黑 / 高对比度 / Material You 动态取色 / 自定义背景色+图片 / 排版预设主题（一组参数快照）

**D 内容元素**：图片灰度/隐藏（Reeder 报纸模式）/ 代码块等宽+语法高亮主题 / 引用块/表格/脚注/链接样式 / 简繁转换

**E 高级**：用户自定义 CSS 注入（自托管标配：Miniflux/CommaFeed/FreshRSS）/ 自定义 JS / 字体域名白名单（CSP）/ 主题包导入导出分享（NetNewsWire 唯一先例，Web 端空白）/ Bionic Reading / TTS / 按 feed 覆盖排版 / CJK 阅读时长

## 三、分层结论（LumiRSS 采用）

- **必备基础**（缺了不合格）：字号/行距/宽度档/明暗三态 → 0010 已有 + 0010a F6 补齐
- **进阶**（专业阅读器特性）：字体族多选/段距/justify/sepia+AMOLED/图片控制/自定义 CSS/字体导入/排版预设 → 0010a F6/F7 已做前六项，**字体导入归 0011**
- **差异化亮点**（竞品空白）：主题包导入导出分享（Web 端无先例）/ 中文深度排版（段距/首行缩进/标点悬挂/简繁/CJK 时长——英文产品全没做好）/ Bionic Reading / 分页滚动 → **全部归 0011**

## 四、技术路线（0011 实施依据）

1. **字体导入**：FontFace API + IndexedDB（Blob 存储，仅 woff2）；CJK 体积问题的两条路：
   cn-font-split 子集化 或 字体 URL 方式（自托管静态目录 + @font-face URL，零存储成本）
2. **中文排版**：首行缩进 `text-indent: 2em`（中文段落习惯）、标点悬挂、简繁转换（OpenCC wasm 或前端词典）
3. **主题包分享**：预设 JSON 信封（schemaVersion/appName/type: 'reader-presets'）——0010a F7 导入导出已实现该格式，0011 扩展为完整主题包（加背景图片/自定义 CSS）
4. **代码高亮**：shiki（届时评估 bundle 影响，仅按需加载）
5. **Bionic Reading**：按词加粗（正则分词 + `<b>` 包裹，纯前端成本低）

## 五、对 0010a 已实现项的对标

| 0010a 实现 | 对标 |
|-----------|------|
| 字体族四档 | OrigRead reader-font / NewsBlur 字体选择 |
| 背景色板 + 自定义 hex + WCAG 自适应 | OrigRead resolveReaderColors（原算法） |
| 段距三档 + justify | Legado 行距段距分离 / Readwise |
| 图片三模式（含灰度） | Reeder 灰度报纸模式 |
| 自定义 CSS（前缀注入） | Miniflux Stylesheet / CommaFeed Custom CSS |
| 5 套排版预设 + 派生 + 导入导出 | TTRSS Reeder 主题 / NetNewsWire .nnwtheme |
