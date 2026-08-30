# Spec 0012 — Reader Style Deep Customization / 阅读样式深度自定义

> 状态：**Approved（用户指令全文，2026-08-30）**
> 日期：2026-08-30
> 依据：用户 0012 里程碑指令（全文）+ docs/reference/reader-style-survey.md
> 前置：0011（Mobile UI Five-Screen Alignment）已合入 main（PR #18，dd95924）
> 分支：feat/0012-reader-style-deep-customization（从 main 新建）

---

## Goal

在 0010a Reader Style 基础上，把阅读器升级为真正成熟、适合中英文长文阅读的
深度可定制 Reader。本轮不重新设计 LumiRSS，不修改 0011 导航，BFF 零改动。

统一工程模型（本 Spec 的核心原则）：

```text
Reader Preferences
        ↓
versioned settings（useAppSettings + app-settings.ts）
        ↓
safe content presentation pipeline（transforms → DOMPurify 终点）
        ↓
Reader CSS variables / controlled transforms
        ↓
desktop + mobile
```

优先级：统一模型 > 功能数量；安全 rendering boundary > 炫技；
按需加载 > 巨型 bundle；复用 0010a > 重复造轮子；
中文阅读体验 > 机械模仿英文 Reader。

## 前置条件核对（Gate 0 已真实核验，2026-08-30）

```text
Git:        main @ dd95924（PR #17 + #18 已合并），工作区干净
分支:       feat/0012-reader-style-deep-customization（从 main 新建）
Web 基线:   pnpm test 313 passed（25 files）/ pnpm build 成功
            （js 409.44KB / gzip 121.68KB，css 40.15KB / gzip 8.48KB）
BFF 基线:   uv run pytest 134 passed（0012 零改动，最终复跑）
已有设置:   useAppSettings + store/app-settings.ts（localStorage 单 key
            lumirss-settings，逐字段 normalize，legacy key 迁移）
已有 Reader: lib/reader-style.ts（背景/字体栈/段距/预设/CSS 前缀）；
            Reader CSS 变量（--lumi-reader-*）挂 <html>
已有安全:   ArticleContent.tsx 唯一 dangerouslySetInnerHTML；
            sanitize-article-html.ts 唯一 DOMPurify 清洗点
0010a 能力: 字体族四档/字号/行高/宽度/背景/段距/justify/图片模式/
            custom CSS（.lumi-reader 前缀）/5 预设 + import/export
工具链:     Node 24.19.0（nvm）+ pnpm；oxlint；vitest
```

## 架构边界（冻结）

```text
FreshRSS → FastAPI BFF → EntryDetail → sanitized article
        → Reader presentation layer → reader styles/typography/transforms
```

禁止：新增 Reader 后端 API；字体文件存进 BFF；主题包存进 FreshRSS；
修改 FreshRSS 数据模型；把文章样式偏好写进 TanStack Query；创建第二套
Reader settings store；为视觉功能破坏 RSS HTML 安全边界。

小范围模块化重构允许；大规模目录搬迁禁止。

## 安全模型（本 Spec 最重要的设计变更）

旧 invariant：「sanitize 后字符串不得继续修改」——与简繁转换 / Bionic /
语法高亮等 presentation transform 冲突。新 pipeline：

```text
raw RSS HTML
      ↓ parse（DOMParser → inert document）
controlled presentation transforms（OpenCC / Bionic / Shiki 标记）
      ↓
DOMPurify — 最终安全边界（sanitize 整个 transform 后的 DOM）
      ↓
safe HTML → render（唯一 dangerouslySetInnerHTML）
```

硬规则：

1. DOMPurify 仍是最终可信边界（顺序：transforms 先做，sanitize 最后）；
2. 原始 RSS HTML 永远不得直接进入 React；
3. transforms 不得执行 script、保留 event handler、放开 iframe /
   arbitrary style / `javascript:` URL；
4. 禁止 regex 拼 HTML；禁止对 sanitizer 输出做不受控字符串替换；
5. 所有新增 DOM markup 必须来自 Lumi 自己的固定模板/DOM API
   （`document.createElement` / `textContent`，不得 `innerHTML` 不可信数据）；
6. 恶意 HTML regression tests 必须覆盖 transforms 之后的输出。

同步更新 ArticleContent.tsx / sanitize-article-html.ts 注释与 AGENTS.md。

## Scope（按 Gate 划分）

### Gate 1 — 设置数据模型收敛

- 新增 Reader 设置字段（全部纳入现有 normalize/migration，安全默认值）：
  - `readerCustomFontId: string | null`（IndexedDB 字体引用）；
  - `readerFontUrl: string | null` + `readerFontUrlName: string`（Gate 3）；
  - `readerTextIndent: 'off' | '2em'`（中文首行缩进）；
  - `readerHangingPunctuation: boolean`（progressive enhancement）；
  - `readerChineseConversion: 'off' | 's2t' | 't2s' | 'tw' | 'hk'`；
  - `readerShowReadingTime: boolean`；
  - `readerCodeHighlight: 'auto' | 'off'` + `readerCodeTheme: string`；
  - `readerBionic: boolean`（实验性，默认 false）。
- normalize/persist/load 逐字段校验；旧 localStorage 设置继续加载；
  corrupted data 回退默认；未知字段丢弃不报错。

### Gate 2 — 本地字体（WOFF2 → IndexedDB → FontFace）

- 仅接受 WOFF2（扩展名 + MIME + FontFace 实际可加载性三重校验）；
- IndexedDB 存 { id, name, fileName, blob, mime, size, createdAt }；
- 稳定 font id（hash）去重；FontFace API 加载 + `document.fonts.add`；
- 刷新后自动恢复注册；删除字体（含正在使用时）→ 解除引用 + fallback，
  不白屏、不留失效 reference；
- 处理：重复导入 / 无效字体 / IndexedDB unavailable / quota /
  load rejection；
- 字体 Blob 不进 localStorage。

### Gate 3 — 字体 URL（大型中文字体）

- 仅 http/https，建议 https；用户自托管场景；
- FontFace('…', url) 直接加载，不执行外部 CSS、不接受 @font-face 片段、
  不经 BFF 代理、不下载复制进 IndexedDB；
- load 成功才保存 active；失败显示原因（含 CORS）；网络字体失效时
  fallback 正文不消失；设置 UI 附隐私提示（外部请求）。

### Gate 4 — 中文深度排版 + presentation pipeline

- 「中文排版」设置区：首行缩进（off / 2em，相对单位）；
  标点悬挂（`@supports (hanging-punctuation: first)` 包裹，
  UI 标注「实验性 · 浏览器支持程度不同」）；
- 首行缩进作用域：`.article-content > p`（标题不缩进、blockquote /
  list / code / pre 不继承，图片后段落无异常）；
- 简繁转换（OpenCC，dynamic import）：原文 / 简 / 繁(台) / 繁(港)；
  展示层 DOM text node transform，不改 EntryDetail / Query cache /
  FreshRSS；切回原文完全恢复；文章间不串状态；HTML 标签/属性/URL
  不转换；code/pre/kbd 默认不转换；
- 建立新 presentation pipeline（见「安全模型」）。

### Gate 5 — CJK 阅读时间

- 纯函数 `estimateReadingTime(text)` → { minutes, cjkCharacters,
  latinWords }；速度常量集中定义带注释；
- ReaderHeader 弱化显示「约 N 分钟」（<1 分钟），有开关。

### Gate 6 — .lumitheme Reader Theme Pack

- JSON 信封 { schemaVersion:1, appName:'LumiRSS', type:'reader-theme',
  metadata, reader, customCss }（实际字段按 settings schema）；
- 导入流程：parse → schema validate → normalize → preview → 用户确认
  → apply；preview 显示名称/描述/字体/背景/字号/行高/中文排版状态/
  是否含 custom CSS；
- 指向不存在的 custom font → 显示「缺少字体」+ fallback，不致命；
- export → import → export 语义 round-trip；
- 兼容 0010a 旧 reader-presets JSON；
- 不包含 secret/credential/cookie/localStorage dump/字体二进制/
  任意 JS/HTML；theme pack 内 custom CSS 走与手工 CSS 相同的
  normalize/prefix 流程。

### Gate 7 — Reader 内 Aa 快速面板

- ReaderHeader 轻量「Aa / 阅读样式」入口，复用 useAppSettings
  （禁止第二套 store）；
- 快速访问：字体/字号/行高/宽度/背景/首行缩进/简繁/图片模式；
  「更多阅读设置」进入 Settings；
- desktop → popover；mobile → bottom sheet（现有 modal 模式）；
  keyboard accessible、focus trap/restore、Escape 关闭、touch ≥44px。

### Gate 8 — Shiki 代码高亮（lazy）

- 仅文章含 `<pre><code>` 且设置为 auto 时 dynamic import；
- fine-grained bundle；仅加载用到的语言/主题；支持语言白名单：
  js/ts/json/html/css/bash/python/java/c/cpp/go/rust/markdown/yaml；
  未识别 → plaintext；
- 加载期间保留普通 code block；失败 graceful fallback；
- 设置：代码高亮 自动/关闭 + 明暗匹配 code themes；
- 记录 build 前后 bundle size；异常即停止报告。

### Gate 9 — Bionic 词首强调（实验性）

- 名称「词首强调（实验性）」，默认关闭，不宣称速度/理解力收益；
- 仅 Latin word text nodes；跳过 code/pre/kbd/samp/button/链接复杂
  内容/heading/CJK（不给中文字符套 <b>）；
- pipeline 内 DOM transform；切换完全恢复；不嵌套 <strong>；
  反复开关不 DOM 膨胀；超长文性能可接受；
- 若显著破坏 pipeline/性能 → 标记 experimental deferred，不阻塞 0012。

### Gate 10 — Paged Reading（仅 candidate，非阻塞）

- 最小 prototype 评估（CSS columns / horizontal scroll / scroll-snap /
  selection / links / tables / code / image / resize / orientation /
  keyboard / a11y / progress）；
- 仅在稳定且复杂度合理时加入「阅读方式：连续滚动 / 分页（实验性）」；
  否则记录 deferred 理由，Roadmap 保持 Candidate。

**Prototype 结论（2026-08-30，deferred）**：CSS 多列方案
（`column-width: 100vw` + horizontal scroll）在最小验证中暴露以下
不可接受的缺陷：
1. 文本选区跨列时浏览器会同时选中多列内容；
2. 列高依赖容器固定高度，移动端地址栏收缩 / 旋转时列宽重算导致
   页码漂移；
3. 表格与宽代码块在列内溢出无法局部滚动（需要逐块再包一层）；
4. 键盘翻页需自研（焦点与滚动位置无原生联动），进度反馈需自算；
5. 与现有「Reader 自滚动容器 + 回顶」逻辑冲突，需要双模式状态机。

修好这些的复杂度与本里程碑「统一模型 > 功能数量」原则冲突。
决定：**deferred**，Roadmap 保持 Candidate，留待 0017 Reader
Power UX 重新评估（届时可考虑基于 scroll-snap 的纵向分节或
virtualized pagination 方案）。

### Gate 11 — 视觉 / 响应式 / 可访问性回归

- Playground Reader fixtures：english-long / chinese-long / mixed /
  code-heavy / images / malicious / no-html / long-title；
- 视口 390/430/768/1024/1280/1440/1920；主题 light/dark/system/
  paper/sepia/AMOLED/custom font/CJK font/indent/繁体/code/长表格/
  超大图/长 URL/custom CSS/Aa 面板/键盘/reduced motion；
- 无页面级横向 overflow；code block 局部滚动；图片/表格不撑破；
  mobile safe-area 正常；字体加载无严重 layout collapse。

### Gate 12 — 全量回归 + 文档

- pnpm test / lint / build；uv run pytest（BFF 零改动复跑）；
- 性能报告：initial bundle / lazy chunks / 最大新增 chunk / dist 变化；
- devlog 0012 + README / PROJECT_STATE / ROADMAP / AGENTS 同步；
  ARCHITECTURE.md 仅在安全边界变化时更新（本 Spec 会更新）。

## Non-goals（明确不做）

AI 摘要/翻译/对话；RSSHub route discovery；Feed 分类 CRUD；OPML；
搜索后端；订阅管理后端；TTS；Highlight/annotation；阅读笔记；知识库；
网页剪藏；多用户同步；服务端 Reader preference；website scraping；
arbitrary JS injection。TTF/OTF/ZIP 字体与 CSS font package 本阶段不做。

## Acceptance Criteria（指令 AC1–AC22，全文照录）

1. Reader 新设置建立在 0010a settings system 上，无第二套状态源；
2. WOFF2 导入后刷新仍可离线加载；
3. 删除字体 Reader 正确 fallback；
4. font URL 支持，失败/CORS 有清晰 fallback；
5. 中文首行缩进作用于正文且不污染 heading/list/code；
6. 标点悬挂 progressive enhancement，核心阅读不依赖；
7. 简繁转换不改服务器数据/Query cache，切回原文完全恢复；
8. 中英混排阅读时间稳定计算；
9. .lumitheme export/import/preview/round-trip；
10. 主题包不含 secret/字体二进制/JS/任意 HTML；
11. 0010a 旧 reader presets 兼容；
12. Reader 内 Aa 控件与 Settings 同一 settings source；
13. 含 code 文章按需 highlight，无 code 文章无 Shiki 成本；
14. Bionic 默认关闭且 experimental，不宣称速度收益；
15. Paged Reading 有明确 prototype 结论（非 blocking）；
16. RSS HTML 仍处于清晰、经测试的安全 rendering boundary 内；
17. 恶意文章 HTML regression tests 通过；
18. 刷新后字体/Reader settings/theme 保持正确；
19. 390px–1920px 无页面级横向 overflow；
20. 键盘/focus/reduced-motion 可访问性无退化；
21. BFF API 零改动；
22. read/unread、starred、稍后读、原文链接、list→reader、
    mobile navigation 无回归。

## Verification

- 每个 Gate 完成即跑对应测试（不等全部写完）；
- Gate 12：Web 全量 test/lint/build + BFF pytest + bundle 数据 +
  视觉矩阵截图（不入 Git 的私有 fixture 用占位/合成数据）；
- 向用户提交完整报告后才决定 commit/push/PR。

## Documentation updates

- Spec 0012（本文件）+ AGENTS.md + PROJECT_STATE.md + ROADMAP.md +
  README.md（Gate 0 修正：0011 → completed，0012 → active）；
- devlog 0012（Gate 12）；
- SOURCE_MAP / THIRD_PARTY_NOTICES（如有 source-derived 实现或新依赖）；
- ARCHITECTURE.md（安全 pipeline 变更，Gate 4 后同步）。

## Risks / Unknowns

- opencc-js 与 shiki 的 bundle 体积 → 全部 lazy，记录实测数据；
- 恶意 HTML regression 面（transforms 后必须重新消毒）→ 专用测试文件；
- IndexedDB 在隐私模式/旧浏览器不可用 → 功能降级但不影响启动；
- hanging-punctuation 浏览器支持差异 → @supports 包裹 + UI 标注。
