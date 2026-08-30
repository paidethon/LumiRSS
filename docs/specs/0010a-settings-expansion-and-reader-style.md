# Spec 0010a — 设置中心扩展与阅读样式自定义（0010 补丁轮）

> 日期：2026-08-30
> 状态：待用户批准
> 分支：沿用 `feat/0010-settings-center-adaptive-shell`（0010 Gate A–D 已完成、未合并）
> 前置研究：Folo 源码（设置全功能 + 移动端结构）、OrigRead 双端源码（六页字段级清单）、
> 10+ 高 star 阅读器样式调研（Reeder/Readwise/Miniflux/NetNewsWire/NewsBlur/Legado 等）
> 结论基调：**纯前端、BFF 零变化、诚实原则不变**。

---

## 0. 用户决策记录（2026-08-30）

| # | 决策点 | 用户决策 |
|---|---|---|
| 1 | JSON 规则/网站解析规则（自造源）与冻结架构冲突 | **A：不做自造源**。RSSHub 承担同等需求（0013 Source Discovery）；OrigRead 规则页的 UI 模式（教程/模板/导入导出/测试）作为 0013 的设计蓝本 |
| 2 | 阅读样式 P1（自定义 CSS + 排版预设主题）放本轮还是下轮 | **本轮**（Gate F） |
| 3 | 滚动标记已读 | **实验性开关（默认关）**，正式版规划在 Reader Power UX 里程碑（顺延后 0016） |
| 4 | Reader 深度自定义 P2 独立成新 0011 里程碑 | **允许插入**，原 0011–0017 顺延为 0012–0018（路线修订见 §8） |

---

## 1. 背景与问题

### 1.1 移动端设置布局 bug（必须修复）

0010 Gate D 交付的移动端设置存在布局缺陷（真实浏览器 390px 实测确认）：

- 根因：SettingsModal 双栏容器缺少 `max-md:flex-col`——<768px 时全宽分类导航与
  内容区仍横向并排，内容区被挤出视口；分类 chips 又被 flex stretch 拉成 763px
  高竖条。
- Gate D 验证只断言了「设置能打开」（isVisible），未验证视觉布局，属验证疏漏。
- 修复方式不是给 chip 条打补丁，而是**按 Folo 移动端模式重设计**（§3.1）。

### 1.2 功能缺口（用户需求 2/3/4）

- 对照 Folo 桌面 14 个设置 tab 的完整清单：LumiRSS 缺 accent 主题色、全局字号、
  UI 字体、减少动效、自定义 CSS、已读变暗、按日期分组、启动仅未读、滚动标记
  已读、字体族选择等基础项。
- 用户指定合并 OrigRead 六页中的四页（翻译/文章过滤/RSSHub/备份与恢复），
  要求复刻全面。
- 阅读样式调研结论：字号/行距/宽度/明暗三态是行业「必备四件套」；自定义 CSS
  注入是自托管阅读器（Miniflux/CommaFeed）标配；排版预设主题与预设导入导出
  是进阶特性（TTRSS/NetNewsWire 先例）。

---

## 2. 目标与非目标

### 目标

1. 移动端设置按 Folo 模式重设计并修复布局 bug；
2. Folo 设置功能补全（14 项纯前端真实生效 + planned 归属标注）；
3. OrigRead 四页复刻（翻译/文章过滤/RSSHub/备份与恢复）；
4. 阅读样式 P0（字体族/背景扩展/段距/对齐/图片控制）+ P1（自定义 CSS + 排版预设主题）；
5. 路线修订：插入 0011 Reader 深度自定义，原 0011–0017 顺延 0012–0018。

### 非目标（明确不做）

- **自造源功能**（JSON 规则解析、网站 CSS Selector 抓取、WebView 动态渲染）——
  决策 A，违反冻结架构（BFF never re-implements RSS fetching）；
- Folo 多用户 SaaS 特性（plan/cli/feeds 表格/账户系统/服务端设置同步队列）；
- 阅读样式 P2/P3：字体导入（FontFace+IndexedDB）、中文排版细节（首行缩进/标点
  悬挂/简繁）、CJK 阅读时长、代码高亮主题（需 shiki 新依赖）、Bionic Reading、
  分页滚动、主题包分享生态——**全部归新 0011**；
- TTS/通知渠道/AI 摘要开关的真实执行（归 0014+，本轮仅 planned 标注）。

---

## 3. 工作分解

### Gate E — 移动端重设计 + 信息架构重组 + 通用页补全

**E1 CategoryPage 组件抽出**
- 把 SettingsModal 内各分类内容抽为独立的 `settings/categories/*.tsx` 组件；
- 桌面 Modal 与移动全屏页共享同一组分类组件与同一 store（Folo 的共享方式：
  数据层/UI 内容共享，外壳各自实现）。

**E2 MobileSettingsScreen（Folo 移动端模式）**
- 全屏设置首页：分组列表（iOS 风格 GroupedInsetList：彩色圆角图标 + 标题 +
  chevron），分组：主设置（通用/外观/快捷键/翻译/文章过滤/RSSHub）、数据
  （数据控制/备份与恢复）、订阅（订阅与来源/AI/工作区）、其他（账户与服务/关于）；
- 点击任一行 → **push 全屏子页**（内部状态栈实现，无路由依赖）：左上返回按钮
  + 吸顶标题 + 该分类设置项；
- 桌面 Modal（左导航 + 右内容）保持现状不动；
- MobileTabBar 的设置入口改挂 MobileSettingsScreen（替代 fullscreenOnMobile 的
  Dialog 方案；Dialog 的 fullscreenOnMobile 变体保留给其他潜在用途）。

**E3 设置信息架构重组（桌面 + 移动一致）**
- 分类从 9 → **13**：通用 / 外观 / 快捷键 / 订阅与来源 / AI / **翻译** /
  **文章过滤** / **RSSHub** / 数据控制 / **备份与恢复** / 账户与服务 / 工作区 / 关于；
- 图标沿用 lucide（Languages/Filter/Rss/DatabaseBackup 等已有图标）。

**E4 通用页补全（4 项真实生效）**
- 已读条目变暗 `dimRead`（EntryRow 透明度，不只靠颜色——保留字重差异）；
- 按日期分组 `groupByDate`（EntryList 日期小节标题，与现有虚拟滚动兼容则做，
  不兼容则降级为 planned 并记录原因）；
- 启动时仅看未读 `unreadOnly`（view 默认值，持久化）；
- 滚动标记已读 `scrollMarkUnread`：**实验性开关（默认关 + 「实验性」徽标 +
  planned·0016 正式版标注）**；实现为 IntersectionObserver，条目完全滚出
  视口才标记（保守策略），仅影响当前已加载列表。

### Gate F — 外观补全 + 阅读样式 P0/P1 + OrigRead 四页

**F1 外观页补全（5 项）**
- Accent 主题色：8 预设色板 + `<input type="color">` 自定义取色 → 写
  `--lumi-accent`（及 hover/active 派生变量）全站生效；
- 全局界面字号：15/16/18/20 四档 → root font-size rem 缩放（Folo 同方案）；
- UI 字体：预设栈选择（默认 / 无衬线 / 衬线 / 等宽，沿用 OrigRead 四档 CSS 栈
  值）→ `--lumi-font-sans`；
- 减少动效 `reduceMotion`：设置值与系统偏好取或 → `data-motion-reduce` 属性 +
  CSS 过渡禁用（tokens.css 已有 reduced-motion 钩子）；
- 自定义 CSS（见 F7，归入阅读样式但入口在外观页，同 Folo）。

**F2 翻译页（OrigRead 复刻）**
- 字段：`translationSettings = { defaultProvider, targetLanguage, displayMode,
  providers[] }`（Microsoft/DeepL/DeepLX 三 Provider，Google/MLKit 不做）；
- UI 完整复刻 OrigRead Provider 卡片模式：radio 选默认 + 启用开关 + Endpoint
  输入（自动补 https:// 去尾斜杠）+ Region（仅 Microsoft）+ API Key 密码框
  （眼睛切换 + 保存按钮 + 「未保存/已存储 N 字符」状态行）；
- 交互不变量照搬：至少保留 1 个启用 Provider；禁用默认项时自动迁移默认；
- 持久化：localStorage（lumirss-settings 扩展字段）真实生效；
- **测试连接 + DeepL 用量查询：planned·0015**（需 BFF 代理，按钮禁用 +
  归属徽标）；页面顶部 Banner 注明「翻译执行将在 0015 上线，当前保存配置」。

**F3 文章过滤页（OrigRead 复刻 + 显示层过滤）**
- 数据模型照搬：`filterRules = [{ id, keyword, feedId(null=全局), type:
  'keyword'|'regex', enabled }]` + 统计 `{ totalFiltered, lastFilteredAt,
  lastMatchedRule }`；
- UI 复刻：统计卡片（累计过滤 N 篇）+ 添加规则对话框（keyword/regex 单选 +
  pattern 输入 + 行内校验「regex 必须可编译」）+ 导入/导出 JSON + 规则列表
  （pattern + 范围·类型 + 启用开关 + 删除）；去重规则按（feedId,type,pattern）；
- **本轮过滤语义：显示层过滤**——时间线渲染时按规则过滤标题匹配项（keyword
  忽略大小写 contains / regex IGNORE_CASE，首条命中；页面标注「当前为显示层
  过滤，BFF 读取层过滤 planned·0012」）；
- 设置页只加全局规则（来源级规则从订阅管理侧入口加，0012）。

**F4 RSSHub 页（OrigRead 复刻）**
- 数据模型：`rsshubSettings = { enabled, instances[] }`，instance =
  `{ id, url, location, maintainer, enabled, builtIn }`；
- 复刻 16 个内置公共实例清单（研究已提取：official/rssforever/slarker/
  pseudoyu/rsstips/ktachibana/owonz/wudifeixue/henry/umzzz/isrss/emailonce/
  datuan/cups/spriple/virworks，含地区代码与维护者）；
- UI 复刻：总开关 Banner + 实例列表（启停/删除，显示 url·地区·维护者）+
  添加实例输入框 + 恢复默认按钮；
- **测试连接：planned·0013**（需 BFF 代理网络请求，前端不做直连——冻结架构
  禁止前端直连 RSSHub）；实例数据 localStorage 真实管理。

**F5 备份与恢复页（本轮全功能真实，纯前端）**
- 导出：JSON 信封 `{ schemaVersion: 1, appName: 'LumiRSS', createdAt,
  preferences, filterRules, translationSettings, rsshubSettings, readerPresets }`
  下载（文件名 `LumiRSS-config-<日期>.json`）；
- 可选加密：勾选「包含 API Key」→ 强制 ≥6 位密码 → **Web Crypto API**
  （PBKDF2 100k 迭代 + AES-256-GCM，密文/盐/IV base64 内嵌信封）——与 OrigRead
  同方案同语义（默认不含 Key；无密钥备份恢复时不清空当前 Key）；
- 导入：选文件 → inspect 只读摘要预览（创建时间/规则数/设置数/是否含机密）→
  确认 → validate-before-mutate（信封校验 + 字段归一化全部通过才写入）→
  逐字段合并恢复 + 结果反馈（恢复 N 项设置/M 条规则）；
- OPML 导入导出：planned·0012（数据在 FreshRSS 侧，需 BFF 控制平面）；
- 与「数据控制」页分工：数据控制保留清缓存/重置设置；备份页管配置可移植。

**F6 阅读样式 P0**
- 字体族四档（OrigRead 栈原值）：system（inherit）/ sans / serif
  （ui-serif, Georgia, "Times New Roman", "Songti SC", SimSun, serif）/ mono
  → `--lumi-reader-font-family`；
- 阅读背景扩展：现有 follow/sepia/warm 基础上 + paper 纸白 #fffefb / mint 淡绿
  #eef7ee / **custom 自定义**（hex 文本 + `<input type="color">`，改色自动切
  custom；色板 swatch 交互复刻 OrigRead）——每预设含暗色变体（ OrigRead 双主题
  色板原值）；
- 自定义背景 WCAG 自适应：对最终背景色算相对亮度，<0.42 判深 → 切换深色文字
  套（OrigRead resolveReaderColors 同算法）；
- 段距 `paragraphSpacing`（紧凑/标准/宽松三档）+ 两端对齐 `justify`
  （`text-align: justify` + `text-justify: inter-ideograph`）开关；
- 图片显示控制：显示全部 / 灰度（Reeder 报纸模式）/ 隐藏。

**F7 阅读样式 P1**
- 自定义 CSS：外观页入口（textarea 等宽字体 + 变量清单文档说明 + 重置按钮）；
  注入前**自动前缀 `.lumi-reader`**（简易规则解析：普通选择器加前缀，
  @media/@keyframes 块递归处理，解析失败则整段拒绝并提示）；实时生效；
- 排版预设主题：5 套内置——「默认（Lumi Mist）」「纸感 Reeder」「期刊衬线」
  「AMOLED 真黑」「高对比」——每套 = 一组阅读样式变量快照（字体族/字号/行距/
  段距/对齐/背景/文字色）；一键切换 + 「从预设复制再改」派生能力；
- 预设导入/导出 JSON（用户自定义预设可分享；内置预设不可删）。

**F8 app-settings store 扩展**
- 新增字段：`accentColor, uiFontSize, uiFontStack, reduceMotion, customCss,
  dimRead, groupByDate, unreadOnly, scrollMarkUnread, readerFontFamily,
  readerBackground(+paper/mint/custom), readerBackgroundCustom,
  readerParagraphSpacing, readerJustify, readerImageMode, readerPreset,
  translationSettings, filterRules(+stats), rsshubSettings, readerPresets[]`；
- 全部走既有 normalize 逐字段归一化 + 单 key 持久化 + 旧字段向后兼容
  （0010 已存设置升级后无损）。

### Gate G — 全量回归 + 文档 + 看板

- 全量测试 + lint + build + 视口矩阵 + 真实浏览器实测（见 V 列表）；
- 文档修订（PRD v6.2 / ROADMAP / PROJECT_STATE / AGENTS / README / SOURCE_MAP
  新增借鉴登记）；
- 看板修订：0010 条目扩为含补丁轮 / 插入 0011 / 0012–0018 顺延；
- devlog 0010 增补补丁轮章节。

---

## 4. 验收标准（AC）

### 移动端与信息架构

- **AC1** <768px 设置为全屏页面：分组列表（图标+标题+chevron）→ 点击 push 全屏
  子页（返回按钮 + 吸顶标题）；无 chip 横条方案残留。
- **AC2** 移动端设置子页所有控件 ≥44px 触摸目标；390px 零横向溢出。
- **AC3** 桌面端 Modal 布局与 0010 Gate A 行为回归不变（左导航 + 右内容 +
  遮罩/Escape/✕ 关闭）。
- **AC4** 桌面与移动展示同一组 13 分类，修改同一 store 数据（在一端改设置另一端
  生效）。
- **AC5** 分类内容组件（CategoryPage）为共享组件，桌面/移动外壳仅做布局差异。

### 通用页

- **AC6** dimRead 开启后已读条目视觉变暗（透明度），字重差异保留（状态不只靠颜色）。
- **AC7** groupByDate 开启后时间线出现日期分组小节标题（若虚拟滚动不兼容，降级
  planned 并在报告中记录原因——不允许假生效）。
- **AC8** unreadOnly 开启后刷新应用默认进入未读视图。
- **AC9** scrollMarkUnread 默认关闭 + 「实验性」徽标 + planned·0016 标注；开启后
  条目完全滚出视口才标记已读（保守策略）。

### 外观页

- **AC10** accent 色选择后 `--lumi-accent` 及派生变量全站生效（真实浏览器
  computed style 实测：按钮/Sidebar 选中态/焦点环变色）。
- **AC11** 全局字号 4 档切换后 root font-size 变化，全站 rem 元素同步缩放。
- **AC12** UI 字体四档切换后 `--lumi-font-sans` 变化并生效。
- **AC13** reduceMotion 开启后过渡动画禁用（transition-duration 为 0）。
- **AC14** 自定义 CSS 保存后注入且**仅作用于正文**（选择器自动前缀 .lumi-reader，
  验证：规则影响 .lumi-reader 内元素、不影响 Sidebar）。

### 阅读样式 P0

- **AC15** 字体族四档切换后正文 font-family 实测变化（serif 档含 Songti SC 栈）。
- **AC16** 阅读背景新增 paper/mint/custom：色板 swatch 交互 + custom 的 hex 输入
  与取色器联动 + 改色自动切 custom。
- **AC17** 自定义深色背景（如 #1a1a2e）下正文自动切换为浅色文字套（WCAG 亮度
  判定），自定义浅色背景保持深色文字。
- **AC18** 段距三档 + justify 开关（含 inter-ideograph）实测生效。
- **AC19** 图片三模式（全部/灰度/隐藏）实测生效（灰度=filter: grayscale(1)）。

### 阅读样式 P1

- **AC20** 5 套排版预设一键切换，每套至少差异化：字体族+背景+文字色+字号行距
  中的 3 项；切换持久化。
- **AC21** 用户预设可导出 JSON / 导入（信封校验）；内置预设不可删可复制派生。
- **AC22** 预设主题与自定义 CSS 共存：预设先应用变量、customCSS 后注入（用户
  CSS 可覆盖预设）。

### OrigRead 四页

- **AC23** 翻译页：三 Provider 卡片完整（radio/启用/endpoint/region/key 密码框/
  保存状态行）；至少保留 1 个启用的不变量；配置 localStorage 持久化 + 刷新恢复；
  测试连接/DeepL 用量按钮 disabled + planned·0015 徽标。
- **AC24** 过滤页：规则 CRUD + regex 行内校验（非法 regex 拒绝提交）+ 导入导出
  JSON + 去重；显示层过滤实测生效（命中规则的条目从时间线消失，统计计数增长）；
  页面标注「显示层过滤，BFF 层 planned·0012」。
- **AC25** RSSHub 页：16 内置实例预置 + 实例增删启停真实 + 恢复默认；测试连接
  disabled + planned·0013；**前端无任何对 RSSHub 的网络请求**（架构边界）。
- **AC26** 备份页：导出 → 修改/清空设置 → 导入恢复往返实测无损（含过滤规则与
  阅读预设）；inspect 摘要预览先于写入；非法文件被 validate 拒绝且不产生部分写入。
- **AC27** 加密备份：勾选含 Key 强制 ≥6 位密码；加密文件不导出明文 Key（导出文件
  grep 不到 Key 明文）；错误密码解密失败并提示；无密钥备份恢复时不清空本机已存 Key。

### 工程

- **AC28** app-settings 新字段全部归一化：损坏 JSON/非法枚举回退默认不抛错；
  0010 已存设置升级无损（向后兼容测试）。
- **AC29** BFF 零变化：`git diff -- services/bff` 为空。
- **AC30** 无新运行时依赖：Web Crypto/原生 color input/textarea 均为平台能力；
  不引入 shiki/CodeMirror/路由库。
- **AC31** 诚实原则：每个新控件要么真实生效要么 disabled + planned 归属徽标，
  无假保存/假成功。

---

## 5. 验证（V）

- **V1** 单测：全量通过（预计 208 → 260+，新增移动设置导航/13 分类/通用 4 项/
  外观 5 项/阅读 P0·P1/翻译页/过滤页/RSSHub 页/备份往返/加密解密/归一化兼容）。
- **V2** lint 0 errors + tsc + build 成功。
- **V3** 移动端实测（390/768）：设置首页 → 子页 push/返回 → 每个新分类页视觉
  正常、零溢出、零 console error（截图留证）。
- **V4** 真实浏览器 computed style 实测：accent 变量/自定义 CSS 作用域/字体族/
  自定义背景文字自适应/图片灰度。
- **V5** 备份往返实测：导出 → localStorage.clear → 导入 → 全部设置与规则恢复。
- **V6** 过滤实测：添加规则后时间线条目消失 + 删除规则恢复。
- **V7** 视口矩阵回归：5 尺寸 × 2 主题零溢出。
- **V8** BFF：121 passed 不变。

---

## 6. 硬边界

1. BFF 零变化；前端不得直连 FreshRSS/RSSHub/AI Provider/翻译 Provider。
2. 冻结架构不可动：不做自造源（决策 A）。
3. 无新运行时依赖（见 AC30）。
4. 诚实原则（AC31）与 planned 分组模式沿用 0010 规范。
5. localStorage 存翻译 API Key 为明文——单用户自托管场景可接受，风险与迁移
   计划（0016 服务端设置 + SQLite）在设置页与 PROJECT_STATE 注明。

---

## 7. 风险

| 风险 | 缓解 |
|---|---|
| app-settings 单 key 膨胀（规则+CSS+预设内嵌，估 <100KB） | 本轮可接受；0011 若做字体导入再评估拆 key |
| 自定义 CSS 前缀解析器边界情况（复杂选择器/@嵌套） | 简易解析 + 解析失败整段拒绝 + 变量清单文档；不做完整 CSS parser |
| groupByDate 与虚拟滚动/分页耦合 | AC7 允许降级 planned 并记录，不允许假生效 |
| 实验性滚动已读误标 | 默认关 + 完全滚出才标 + 实验性徽标 + 0016 正式化 |
| 13 分类在 1440 高度下左导航溢出 | 导航区自身滚动（Folo 同款） |

---

## 8. 路线修订计划（写入文档与看板）

### 8.1 插入新 0011

```text
0011 — Reader Style Deep Customization（阅读样式深度自定义）
  内容：字体导入（FontFace API + IndexedDB，仅 woff2 + 字体 URL 双方式）、
        中文排版细节（首行缩进/标点悬挂/简繁转换）、CJK 阅读时长估算、
        代码高亮主题（shiki，届时评估依赖）、主题包分享生态（.lumitheme JSON）、
        Bionic Reading、分页滚动（候选）
  依据：10+ 阅读器调研 P2/P3 分层（docs/reference 新增调研报告）
```

### 8.2 顺延映射

| 原编号 | 新编号 | 里程碑 |
|---|---|---|
| 0011 | 0012 | Unified Subscription Center（过滤 BFF 层 + OPML 激活） |
| 0012 | 0013 | Source Discovery & RSSHub（RSSHub 测试连接/实例代理激活；OrigRead 规则页 UI 蓝本） |
| 0013 | 0014 | AI Foundation & Summary |
| 0014 | 0015 | Translation & AI Conversation（翻译执行/测试连接/DeepL 用量激活） |
| 0015 | 0016 | Reader Power UX & Unified Settings（滚动已读正式版 + 服务端设置 API） |
| 0016 | 0017 | Production & Operations |
| 0017 | 0018 | MVP Stabilization & Release |

### 8.3 文档与看板修订清单（Gate G 执行）

- PRD v6.2（路线表 + 0011 插入）、ROADMAP（依赖图 + 变更记录）、PROJECT_STATE
  （0010 补丁轮详情 + 测试基线）、AGENTS（当前里程碑）、README；
- SOURCE_MAP 新增：MobileSettingsScreen（Folo mobile SettingsList/GroupedInsetList
  push 模式）、翻译/过滤/RSSHub/备份四页（OrigRead 数据模型与 UI 模式）、
  阅读背景色板与字体栈（OrigRead resolveReaderColors/reader-font）、排版预设
  （TTRSS feedly 主题/NetNewsWire .nnwtheme 概念）、accent 选择器（Folo
  AccentColorSelector）——全部 inspired 级 + 源码路径登记；
- 看板：0010 条目补 Gate E–G / 插入 0011 / 0012–0018 顺延（10 phases 不变，
  Phase 6 Product Shell 0009+0010、Phase 6b 或并入现有 phase 的 0011 归属
  ——按「0011 并入 Phase 6 Product Shell（0009,0010,0011）」处理）；
- docs/reference 新增《阅读器样式调研报告》（本轮调研产出归档）。

---

## 9. 轮次与批准点

```text
Gate E（移动端 + 重组 + 通用页）→ 停等批准
Gate F（外观 + 阅读 P0/P1 + 四页）→ 停等批准
Gate G（回归 + 文档 + 看板）→ 停等最终批准（commit/PR 决策）
```
