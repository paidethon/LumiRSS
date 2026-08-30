# Devlog 0012 — Reader Style Deep Customization / 阅读样式深度自定义

> 日期：2026-08-30
> 分支：feat/0012-reader-style-deep-customization（基于 main @ dd95924）
> Spec：docs/specs/0012-reader-style-deep-customization.md（用户指令全文批准）
> 前置：0011（含 PR #18 修复）已合入 main

## 1. 最终 Scope

在 0010a Reader Style 体系之上，建立统一模型：

```text
Reader Preferences → versioned settings（useAppSettings）
                   → safe presentation pipeline（transforms → DOMPurify 终点）
                   → Reader CSS variables / controlled transforms
                   → desktop + mobile
```

新增能力：WOFF2 字体导入（IndexedDB）、字体 URL、中文深度排版
（首行缩进 / 标点悬挂 / 简繁转换）、CJK 阅读时间、.lumitheme 主题包、
Reader 内 Aa 快速面板、Shiki lazy 代码高亮、词首强调（实验性）。
BFF 零改动（`git diff -- services/bff` 为空，134 tests 全绿）。

## 2. Gate 完成情况

| Gate | 内容 | 状态 |
|---|---|---|
| 0 | 仓库审计 + Spec 0012 + AGENTS/PROJECT_STATE/ROADMAP/README active milestone 修订 | 完成 |
| 1 | settings schema 收敛：10 个新字段全部纳入 normalize/migration，逐字段校验 + 安全默认 | 完成 |
| 2 | 本地 WOFF2：三重校验（扩展名+魔数+FontFace load）→ IndexedDB → FontFace；内容 hash 去重；刷新恢复 | 完成 |
| 3 | 字体 URL：http/https 白名单 → FontFace 远程加载（不落 IndexedDB）；失败/CORS 结构化错误；启动恢复 + 失败静默回退 | 完成 |
| 4 | 中文排版 + **presentation pipeline 安全模型**（见 §5） | 完成 |
| 5 | CJK 阅读时间（`estimateReadingTime` 纯函数 + ReaderHeader 弱化显示 + 开关） | 完成 |
| 6 | .lumitheme：export/parse/validate/normalize/preview/confirm/apply；round-trip；兼容 0010a reader-presets | 完成 |
| 7 | Reader Aa 快速面板：桌面 Popover / 移动底部 Sheet，直连 useAppSettings（无第二 store） | 完成 |
| 8 | Shiki lazy：fine-grained（core + JS regex engine + 每语言/每主题独立 chunk） | 完成 |
| 9 | 词首强调（实验性）：pipeline 内 DOM transform，默认关闭 | 完成 |
| 10 | Paged Reading prototype | **Deferred**（结论见 §9） |
| 11 | 视觉/响应式/可访问性回归（Playground fixtures + 真实 App + 视口矩阵） | 完成 |
| 12 | 全量 test/lint/build + bundle 报告 + 文档 | 完成 |

## 3. 数据结构（settings schema 增量）

`AppSettings` 新增（全部有安全默认值、走 `normalizeSettings` 逐字段校验）：

```text
readerCustomFontId: string | null        # IndexedDB 字体引用（/^font-[0-9a-f]{8,64}$/）
readerFontUrl: string | null             # http/https 白名单（isValidFontUrl）
readerFontUrlName: string                # ≤64
readerTextIndent: 'off' | '2em'
readerHangingPunctuation: boolean        # @supports progressive enhancement
readerChineseConversion: 'off'|'s2t'|'t2s'|'tw'|'hk'
readerShowReadingTime: boolean
readerCodeHighlight: 'auto' | 'off'
readerCodeTheme: 'auto'|'github-light'|'github-dark'|'vitesse-light'|'vitesse-dark'
readerBionic: boolean                    # 实验性，默认 false
```

旧 0010a localStorage 设置无损加载（无新字段的 JSON → 新字段全部默认），
corrupted 字段回退默认不致启动失败，未知字段丢弃。CSS 接线：
`--lumi-reader-text-indent`（em 单位）、`html[data-reader-hanging-punctuation]`、
`html[data-reader-chinese-conversion]`、自定义字体族
`"LumiCustom-<id>", <档位栈>`（未注册完成时自动回退档位栈，不白屏）。

## 4. 字体存储方案

- **local**：`File → arrayBuffer → 魔数 wOF2 校验 → 内容 FNV hash 稳定 id
  （font-<hex16>）→ FontFace 实际加载校验 → IndexedDB（lumirss-fonts/fonts，
  存 Blob + 元信息）→ document.fonts.add`。重复导入按内容 hash 去重返回
  已有条目。启动时 `restoreLocalFonts()` 全量重注册（IndexedDB 不可用/单条
  损坏 → 静默跳过，不阻塞启动）。
- **url**：`new FontFace(family, url(...))` 直接远程加载（浏览器向该服务器
  发请求，UI 有隐私提示）；load 成功才保存 active；不下载复制进 IndexedDB。
  启动按设置重新挂载，失败静默回退档位栈（AC：正文不消失）。
- 删除正在使用的字体 → store 解除 `readerCustomFontId` 引用 + IndexedDB
  记录删除 + FontFace 注销；CSS 栈自动回退。
- 全部错误结构化（FontError code：not-woff2 / load-failed /
  idb-unavailable / quota-exceeded / invalid-url / network / duplicate）。

## 5. Reader transform / security pipeline（本里程碑最重要变更）

旧 invariant（0006）：「sanitize 后字符串不得再修改」与简繁/Bionic/高亮的
presentation transform 冲突。新模型（spec §安全模型，已同步
ArticleContent/sanitize-article-html 注释 + AGENTS.md §9.3 + ARCHITECTURE.md）：

```text
raw RSS HTML
  ↓ DOMParser → inert document（不执行脚本、不加载资源）
controlled transforms（DOM API only：textContent / createElement）
  ├─ OpenCC 简繁转换：TreeWalker 只改 text node data
  │   （跳过 code/pre/kbd/samp/button…；标签/属性/URL 天然不受影响）
  ├─ Bionic 词首强调：<b class="lumi-bionic"> 包拉丁词首（跳过 code/a/heading/CJK）
  └─ Shiki 代码高亮：codeToTokens → span[class=lumi-sh-<hex>]（无 inline style）
DOMPurify.sanitize —— 最终安全边界（FORBID_TAGS/FORBID_ATTR 与 0006 一致）
  ↓
ArticleContent 唯一 dangerouslySetInnerHTML
```

transforms 全部关闭时退化为纯 sanitize（= 0006 原行为，零开销）；
开启时先渲染 sanitize 基线再异步替换（加载期间正文可见）。每次渲染从
raw HTML 重建 → 切换设置 = 重跑管线，无 DOM 膨胀、切回原文完全恢复。

**恶意 HTML regression**：10 类恶意输入（onclick / img onerror /
javascript: / iframe / style / form / svg / math / malformed / inline style）
× 4 种 transform 组合共 40 组断言 + 浏览器实测（script/iframe/form/style/
svg/onclick/js 链接渲染后全部为 0，安全文本可见）。

## 6. OpenCC 方案（简繁转换）

- 依赖 opencc-js@1.4.2（MIT AND Apache-2.0，词典数据源自 OpenCC 项目）。
- **按方向拆包**：`t2s` → `opencc-js/t2cn`（108.77KB / gzip 55.06KB）；
  `s2t/tw/hk` → `opencc-js/cn2t`（1,100.10KB / gzip 474.85KB，其中
  STPhrases 词典 ~1MB 是简→繁的固有成本）。**dynamic import，未启用时
  零加载、零首屏成本。**
- 模式映射：s2t={cn→t}，t2s={t→cn}，tw={cn→twp}（含用词转换：
  软件→軟體、网络→網路，实测验证），hk={cn→hk}。
- 只做展示层 transform；不改 EntryDetail / TanStack Query cache /
  FreshRSS 原始数据（AC7）。

## 7. Shiki bundle 策略（代码高亮）

- 依赖 shiki@4.4.3（MIT）。
- **不 import full bundle**：`shiki/core` + `shiki/engine/javascript`
  （JS regex 引擎，无 wasm）+ 每语言 `shiki/langs/*.mjs` + 每主题
  `shiki/themes/*.mjs` 各自独立 lazy chunk。
- 语言白名单 14 种：javascript/typescript/json/html/css/bash/python/
  java/c/cpp/go/rust/markdown/yaml（+ 常见别名 js/ts/sh/py/md/yml/xml…）；
  未识别语言（如 brainfuck）→ plaintext 原样保留，**不加载 shiki**。
- 触发条件：`readerCodeHighlight === 'auto'` 且文章含 `<pre><code>`
  （`containsCodeBlock` 预检）——无 code 文章零成本（AC13）。
- 主题：auto（跟随应用明暗，system 模式监听 matchMedia 重跑）或锁定
  github/vitesse 明暗四款。
- **适配 sanitize 策略**：应用 FORBID_ATTR style（禁 inline style），而
  Shiki 默认输出 inline color——改为 `codeToTokens` + 自建 DOM
  （span class=lumi-sh-<hex>），颜色规则由运行时注入 `#lumi-shiki-colors`
  样式表提供（内容只来自 bundled 主题色板，非文章内容）。

## 8. Bundle 影响（pnpm build 实测）

| Chunk | 大小 | gzip | 加载时机 |
|---|---|---|---|
| index（initial JS） | 451.00 KB | 132.66 KB | 首屏（基线 409.44/121.68 → **+41.6KB/+11.0KB**，全部为 settings schema + 组件接线，无 opencc/shiki） |
| css | 40.75 KB | 8.61 KB | 首屏（+0.6KB） |
| t2cn（OpenCC 繁→简） | 108.77 KB | 55.06 KB | 仅启用 t2s |
| cn2t（OpenCC 简→繁） | 1,100.10 KB | 474.85 KB | 仅启用 s2t/tw/hk |
| shiki core + engine | 111.87 + 57.63 KB | 35.78 + 20.18 KB | 仅含 code 文章 + auto |
| shiki 语言 chunk | json 2.81KB … cpp 796.96KB | 0.77–60.65KB | 仅该语言出现（cpp 最大，含嵌入语法） |
| shiki 主题 chunk | 11–14 KB × 4 | ~2.5–3KB | 仅高亮时按需 |

结论：性能预算达成——「不用 → 不加载」全链路成立，首屏无异常增长。

## 9. Bionic 与 Paged Reading

- **Bionic（词首强调）**：已实现，默认关闭，UI 标注「实验性 · 对拉丁文
  词首进行视觉强调，不同用户体验可能不同」，不宣称速度/理解力收益。
  只包 plain text node 的拉丁词首（≤2 字符全强调；3–4 取前半；更长 ~40%），
  跳过 code/pre/kbd/samp/button/a/heading/CJK；幂等（每次从 raw HTML
  重建）；不嵌套 <strong>。
- **Paged Reading**：**Deferred**（非阻塞 AC15）。CSS 多列最小原型暴露
  5 项不可接受缺陷（跨列选区、移动端列宽重算漂移、表格/代码块列内溢出、
  键盘翻页需自研、与现有滚动容器冲突），详见 Spec §Gate 10 结论。
  Roadmap 保持 Candidate，留待 0017 重新评估。

## 10. Theme Pack schema（.lumitheme）

```json
{
  "schemaVersion": 1,
  "appName": "LumiRSS",
  "type": "reader-theme",
  "metadata": { "name": "", "description": "", "author": "", "createdAt": "" },
  "reader": { /* 15 字段白名单：字体族/字号/行高/宽度/背景/自定义背景/段距/
                 对齐/图片/缩进/标点悬挂/简繁/高亮/代码主题/字体引用 */ },
  "customCss": ""
}
```

- 导出只含 reader 白名单字段 + customCss——**结构上不可能**携带
  accent/布局/翻译配置/secret（AC10）；metadata 字符串截断（64/280/64）。
- 导入：parse → 信封校验 → 逐字段 normalize（非法值回退默认，恶意字段
  丢弃）→ customCss 过 prefixCustomCss 校验 → **preview 对话框**
  （名称/描述/作者/字体/背景/字号/行高/中文排版/是否含 CSS/缺字体警告）
  → 用户确认 → apply。
- export → import → export 语义 round-trip（reader 段与 customCss 相等）。
- 兼容：`type: 'reader-presets'` 旧文件 → 首个预设升级为主题包（AC11）；
  0010a 原预设导入导出功能不变。
- 主题包引用本机不存在的字体 → 预览显示「缺少字体，将回退」，不致命、
  不自动联网（AC 见 Spec）。

## 11. Tests

```text
Web：399 passed（30 files；基线 313 + 新增 86）
  app-settings.test.ts      +6  （0012 字段 normalize/migration/corrupted/URL 白名单）
  reader-fonts.test.ts      +18 （WOFF2 校验/去重/URL/删除/恢复/IDB 不可用/load 失败）
  article-pipeline.test.ts  +28 （安全 regression 40 组 + OpenCC 真实词典 + Bionic + Shiki）
  reading-time.test.ts      +17 （CJK/Latin/混排/格式化/HTML 提取）
  theme-pack.test.ts        +15 （导出白名单/round-trip/非法输入/旧格式兼容/preview）
  reader-aa-panel.test.tsx  +4  （面板开关/同一 store/更多设置/Escape）
Lint：0 errors（3 warnings 为既有 React Compiler fast-refresh 提示）
BFF：134 passed（零改动复跑，git diff -- services/bff 为空）
```

## 12. Visual verification（真实浏览器）

Playground 新增 Reader Fixtures（8 场景：english-long / chinese-long /
mixed / code-heavy / images / malicious / no-html / long-title）+
transforms 开关矩阵（dev-only，不进生产 bundle）。

实测（Playwright，dev server + 真实 BFF/FreshRSS 数据）：

- 首行缩进 2em 生效（computed 34px = 2×17px），heading/blockquote 0px 不污染；
- 简繁 s2t/tw 真实转换（tw 含用词：軟體/網路），切回原文完全恢复；
- Bionic 12 个强调 span，code 内 0 个；CJK 零标签；
- Shiki：ts+python 两块高亮（154 token span），brainfuck 保持 plaintext；
  dark 主题下自动切 github-dark 色板；
- 恶意 fixture：script/iframe/form/style/svg/onclick/js链接渲染后全为 0；
- 2400px 图片约束到容器内（1300 < 1348px），无溢出；
- 视口矩阵 390/430/768/1024/1280/1440/1920 × chinese-long：全部零横向溢出
  （发现并修复一处真实 bug：高亮 code 块 min-content 经 grid item 撑破
  Playground 布局 → `.lumi-reader { min-width: 0 }` + section min-w-0，
  修复后 390px code fixture body 零溢出、pre 局部滚动生效）；
- 真实 App：Aa 按钮出现（桌面 Popover / 390px 底部 Sheet 469px 高，
  触摸目标 min-h-11=44px），字号调整即时生效（--lumi-reader-font-size
  17→19px），Escape 关闭，阅读时间「约 2 分钟」正确显示；
- console 零错误。

## 13. Known issues / risks

1. **cn2t chunk 1.1MB（gzip 475KB）**：简→繁 STPhrases 词典固有成本，
   仅启用时加载。若未来需要进一步优化，可评估词典子集化（cn-font-split
   思路）或 Web Worker 内转换。
2. **cpp 语言 chunk 797KB**：TextMate 语法含嵌入语言。仅 cpp 文章加载；
   可考虑从白名单移除（保留 c）以控制极端 chunk。
3. **shiki 高亮颜色 class 样式表**依赖运行时注入 `#lumi-shiki-colors`
   （内容来自 bundled 主题色板）。若未来更换 sanitize 策略允许
   CSS-var inline style，可简化为 shiki 官方 css-vars 主题。
4. **Aa 面板移动断点**用 matchMedia JS 检测（768px），与全局 CSS 断点
   一致但机制不同；极端窗口快速拖动时有一帧延迟。
5. **URL 字体**不做本地缓存（Spec 决策：默认不下载复制）；离线时回退
   档位栈。
6. **字体管理器**未做上传进度/大小上限提示（quota 错误已有结构化处理）；
   UI 打磨留待反馈。

## 14. Deferred items

- Paged Reading（§9，Roadmap Candidate → 0017 重新评估）；
- TTF/OTF/ZIP 字体与 CSS font package（Spec Non-goal，仅 WOFF2）；
- 主题包「保存本地字体到包内」（Spec 明确本阶段不做）；
- feed-specific reader profiles（指令结语提及的远期方向，未立项）。

## 15. 下一 milestone

按 ROADMAP：0013 — Unified Subscription Center（Lumi 内订阅管理：
添加/退订/重命名/分类/OPML，经 FreshRSSControlAdapter）。

## 16. 文件清单（新增）

```text
docs/specs/0012-reader-style-deep-customization.md
apps/web/src/lib/reader-fonts.ts            # 字体管理（IndexedDB + FontFace + URL）
apps/web/src/lib/article-pipeline.ts        # 安全 presentation pipeline
apps/web/src/lib/reading-time.ts            # CJK 阅读时间
apps/web/src/lib/theme-pack.ts              # .lumitheme 信封
apps/web/src/lib/code-highlight.ts          # Shiki lazy 集成
apps/web/src/lib/playground-reader-fixtures.ts
apps/web/src/components/ReaderAaPanel.tsx
apps/web/src/components/settings/reader/ReaderFontManager.tsx
apps/web/src/components/settings/reader/ReaderDeepControls.tsx
apps/web/src/__tests__/reader-fonts.test.ts
apps/web/src/__tests__/article-pipeline.test.ts
apps/web/src/__tests__/reading-time.test.ts
apps/web/src/__tests__/theme-pack.test.ts
apps/web/src/__tests__/reader-aa-panel.test.tsx
```

修改：app-settings.ts（schema + CSS 接线）、ArticleContent.tsx（pipeline
接线 + 注释）、ReaderHeader.tsx（Aa 面板 + 阅读时间）、sanitize-article-html.ts
（注释）、main.tsx（字体恢复）、index.css（缩进/悬挂/bionic/shiki 样式）、
categories.tsx（设置区）、Playground.tsx（fixtures）、
THIRD_PARTY_NOTICES.md、docs/reference/SOURCE_MAP.md、docs/ARCHITECTURE.md、
AGENTS.md、docs/PROJECT_STATE.md、docs/ROADMAP.md、README.md。
