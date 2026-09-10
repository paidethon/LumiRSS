# 本地翻译:架构审计、失败根因、轻量替代方案与最终推荐

> 日期:2026-09-10/11 · 所有结论均基于本会话实际执行的 PoC 与真机诊断
> PoC 证据目录:`research/phase2-pocs/translation/`(probe 脚本、poc-page.html、CT2 转换与基准输出)
> 目标读者:下一轮 ZCode —— 只需本文 + `apps/web/src/lib/local-translator.ts` +
> `services/bff/src/lumirss/ai_translation_segments.py` 即可直接开工实施。

## 1. 当前翻译架构(代码审计结论)

```text
Article(contentHtml, 只读)
   │  annotateBlocks() — 内容块切分+稳定编号(translation-blocks.ts, DOM 级, 非换行猜测)
   ▼
blocks: [{index, text}]
   │  engine = settings.translationEngine(设置中心三选一)
   ├─────────────┬──────────────────────────────┐
   ▼             ▼                              ▼
engine=ai     engine=libretranslate          engine=browser
BFF 分段生成    BFF → POST {LT}/translate      100% 浏览器内执行
AI provider   source=auto, target 映射表     window.Translator(Chrome 内置)
(云端/自托管)   批量段, 逐段 upsert 缓存       create() 下载语言包→translate()
   │             │                              │
   └─────────────┴──────────────┬───────────────┘
                                ▼
              Lumi SQLite ai_translation_segments(段级缓存:
              (entry_ref,index,block_hash,engine,lang) 命中零调用)
                                ▼
        overlay 渲染:textContent 注入(原文/双语/仅译文),译文永不进 HTML 路径
```

关键事实(全部有代码出处):

- **AI 翻译**:运行在 BFF + 所配置 AI provider;按段批量(prompt 拼批 +
  标记解析),段级缓存按 block_hash 身份复用;费用 = provider 计费;正文
  离开设备到 provider(隐私取决于 provider)。
- **LibreTranslate**:运行在用户自托管的服务器(独立 HTTP 服务);BFF 仅
  POST `/translate`(source=auto)。**其底层本质 = Argos Translate →
  CTranslate2 运行时**(已从 Argos 源码确认:`argostranslate/translate.py`
  `import ctranslate2`;LibreTranslate README 确认 "powered by Argos
  Translate")。一个常驻 LibreTranslate 容器实测需 1GB+ 内存——这就是
  本轮要回答的"1.6GB 服务器常驻完整翻译服务"问题的来源。
- **Chrome Translator**:运行在浏览器进程,零 BFF 参与、零费用、正文不出
  设备;语言包 (~30-60MB/对) 由 Chrome 组件系统按需下载;结果仅存内存。

## 2. "本地翻译无法调用"的根因(证据链,非猜测)

在 Linux(WSL2/Ubuntu 24.04)上用三种浏览器二进制实测 + 官方文档核对:

| # | 环境 | window.Translator | availability(en→zh) | create() | 译出 |
|---|------|-------------------|----------------------|----------|------|
| 1 | Playwright Chromium 151(headless) | ❌ 不存在 | — | — | — |
| 2 | Chrome for Testing 153(headless + headed + flag) | ❌ 不存在 | — | — | — |
| 3 | **零售 Chrome stable 153(headless, https)** | ❌ 不存在 | — | — | — |
| 4 | **零售 Chrome stable 153(headed, https)** | ✅ 存在 | `"downloadable"` | ❌ `NotSupportedError`(瞬时,零下载事件) | — |
| 5 | 同上 + **chrome://components 手动拉取 TranslateKit 后** | ✅ | `"downloadable"` | ✅ en→zh create 126ms | ✅ |

### 根因分层

1. **非 Chrome 内核、Chrome for Testing、一切 headless 自动化环境**:
   API 根本不暴露(`#1/#2/#3`)。历史会话若用 Playwright/Puppeteer 验证,
   必然得出"不支持"——这是测试环境伪影,不是用户真实环境。
2. **Linux 零售 Chrome 的组件缺口(核心根因,`#4`)**:
   `chrome://components` 显示 `Chrome TranslateKit` **版本 0.0.0.0 /
   Status: New**(基础运行时从未下发),`TranslateKit en-zh` 包已注册但
   同样 New。此状态下 `availability()` 因隐私掩码**一律返回
   "downloadable"**(官方文档明确:所有语言对在任何站点首次 create 前都
   报 downloadable),而 `create()` 在**下载尚未开始时**即抛
   `NotSupportedError`。即:**"downloadable" 不等于语言包真的可得**。
3. **组件拉取后完全可用(`#5`)**:TranslateKit 2025.11.24.0 + en-zh 包
   2024.10.8.1 下载成功后:
   - en→zh:create 126ms(含包下载 0%→100%),首句 cold 22ms,warm 8ms;
     样例:"The model was trained on a large corpus of text." →
     "该模型是在大量文本语料库上训练的。"
   - en→ja:create 5.9s(真实下载),cold 25ms / warm 10ms;
     "このモデルは、大量のテキスト コーパスでトレーニングされました。"
   - 质量:技术文本达到"可用"级,术语(RAG 等)逊于 AI provider。
4. **user activation 语义(次生陷阱)**:一次点击的激活会被 create() 消耗。
   同一 handler 里连续 create 多个语言对,第二个起抛 `NotAllowedError:
   Requires a user gesture`(`#5` 实测 zh→en)。**每个语言对的首次 create
   必须各自对应用户的一次真实点击。**
5. **移动端**:官方文档明确 Translator/LanguageDetector API 不支持任何移动
   设备(Chrome Android/iOS、Safari iOS 均无)。UI 不得宣称移动可用——当前
   LumiRSS 设置文案"Chrome 138+ 桌面版支持"是**正确**的,保留。

### 平台矩阵(写进 UI 文案的最终事实)

| 平台 | 结果 |
|---|---|
| Windows 10/11 桌面 Chrome 138+ | 官方支持(本轮未实测,无 Windows 设备) |
| macOS 13+ 桌面 Chrome 138+ | 官方支持(本轮未实测) |
| Linux 桌面 Chrome 138+ | 支持但**组件可能未自动下发**(见根因 2);组件就绪后完全可用 |
| ChromeOS(Chromebook Plus 144+) | 官方支持 |
| Android / iOS / iPadOS 任何浏览器 | **不支持**(官方明确) |
| Firefox / Safari 桌面 | 不支持 |
| 一切 headless / 自动化 Chromium | 不暴露 |

## 3. 轻量本地替代方案对比(全部有实测或注册表证据)

| 方案 | 实测结果 | 模型/包体积 | 内存 | 延迟(warm) | 质量(en→zh) | 移动 | 维护态 |
|---|---|---|---|---|---|---|---|
| **A. Chrome Translator** | ✅ 本轮真实跑通 | ~30-60MB/对(组件) | 0(并入浏览器) | **8-25ms/句** | 可用,术语弱 | ❌ | Chrome 官方 |
| **B. Bergamot WASM**(browsermt) | ⛔ 阻断:注册表 33 模型**零中文对**;browsermt/bergamot-translator 已归档无 release;Firefox 系模型分发走其私有 infra 本网络不可达 | — | — | — | — | ✅(理论) | 引擎归档 |
| C. TranslateLocally(桌面 companion) | 注册表同 B——**无中文模型**,评估为不可用 | — | — | — | — | — | 活跃但语言集不含 zh |
| **D. CTranslate2 INT8**(opus-mt-en-zh 官方权重自转换) | ✅ 跑通:`ct2-transformers-converter --quantization int8`;模型 **77MB**;load 0.06s;**5 句批 cold 70ms / warm 58ms**;进程 peak RSS **193MB**(含 Python) | 77MB | ~193MB/进程 | 58ms/批 | 连贯;"Local translation keeps article text on the user's device."→"本地翻译保存用户设备上的文章文本。" | ❌ | 活跃(OpenNMT 系) |
| E. LibreTranslate | 未本轮部署(等于 Argos/CT2 + HTTP 服务壳 + 自动语言检测);社区共识常驻 1GB+ | 每语言对数百 MB | >500MB 常驻 | HTTP 往返 | 同级 D | — | AGPL,活跃 |
| F. AI provider(现有 engine=ai) | 生产已有 | 0(云端) | 0 | 网络往返 | 最好 | ✅ | — |

> D 路线注意(实施时必踩的坑,已替你踩过):
> ① Marian 源 token 必须追加 `</s>` EOS,否则输出无限重复(垃圾质量的
> 唯一原因,不是模型问题);② 社区预转换仓库质量参差
> (`jiangzhuo9357/opus-mt-en-zh-ct2` 输出同垃圾——其实是无 EOS 的通病),
> 一律自己从 `Helsinki-NLP/opus-mt-en-zh` 转换;③ sentencepiece 源自
> HF 仓库 `source.spm`。

## 4. 最终推荐(排序)

1. **首选:Chrome Translator(现有 engine=browser,保留并小幅加固)**。
   唯一同时满足"零服务器内存 + 零费用 + 桌面跨平台 + 正文不出设备"的方案,
   且 LumiRSS 已完整集成(能力三态、段缓存、overlay、诚实失败)。
   本轮加固项(下一轮 ZCode 实施,均有本报告证据):
   - **G1 错误语义修正**:`createLocalTranslator` 捕获 `NotSupportedError`
     且 availability 曾为 `downloadable` 时,提示改为"浏览器翻译组件未就绪:
     请打开 chrome://components 更新 TranslateKit 后重试"(Linux 真实故障
     模式),替换现在误导性的"此浏览器不支持该语言对"。
   - **G2 源语言检测**:`createLocalTranslator('en', target)` 硬编码 en
     (`ReaderTranslation.tsx:151`)。改用 `LanguageDetector`(同批内置 API,
     本轮已实证同环境存在)探测文章主语言,探测失败回退 'en'。非英文文章
     现状下翻译结果是错的——这是比"不可用"更糟的静默错误。
   - **G3 下载等待 UX**:create 的 monitor downloadprogress 接到状态栏
     (现在首次下载 5s+ 无反馈,用户会以为卡死)。
   - **G4 重试=新点击**:失败重试按钮必须直接触发 create(新激活),不得
     在 effect 链中自动重试(会 NotAllowedError)。
2. **次选(可选自托管增强,不做默认):CTranslate2 INT8 独立轻服务**。
   77MB 模型 + ~200MB 进程,仅当用户显式开启"服务器本地机器翻译"时启动
   (systemd socket-activation 或 BFF 内 on-demand lazy load + 空闲卸载),
   面向 Safari/Firefox/移动端等无内置 API 的浏览器。**不满足 >500MB 才禁用
   的红线(实测 193MB),但 1.6GB 生产机仍需显式预算审批;默认关闭。**
3. **第三:AI provider(现有 engine=ai)**:质量兜底,与 1/2 并存。
4. **不采用:Bergamot WASM / TranslateLocally**——中文模型缺失是硬阻断;
   引擎本身已归档。重启条件:Bergamot 工具链下出现社区 en→zh intgemm 模型。
5. **不新增:LibreTranslate**——与 D 同底座(Argos=CT2)却多一层 1GB+ 常驻
   HTTP 服务;存量 adapter 保留兼容,不推广。

## 5. Implementation Gates(下一轮 ZCode 顺序执行)

```text
Gate 0: 阅读本报告 + local-translator.ts + ReaderTranslation.tsx + settings 三态文案
Gate 1: G2 源语言检测(LanguageDetector, 回退 en)+ 单测(mock ctor)
Gate 2: G1 错误语义(NotSupportedError + downloadable → 组件指引文案)+ 单测
Gate 3: G3 downloadprogress → TranslationStatusBar 进度 + 单测
Gate 4: G4 重试路径走真实点击;E2E:headless 下断言 unsupported 诚实提示(不许假装可用)
Gate 5: 设置页"本地翻译"说明补平台矩阵表格(§2 表)
回归:pnpm vitest run + 全量 Gate(按 AGENTS.md 里程碑门)
```

## 6. 验收清单

- [x] 三引擎执行位置/费用/隐私/缓存机制文档化(§1)
- [x] Chrome 失败根因 = 组件缺失,有 components 截图级文本证据 + 修复后成功 PoC(§2)
- [x] en→zh / en→ja / zh→en 真机翻译输出记录(§2)
- [x] 平台矩阵含移动端明确不支持(§2)
- [x] CTranslate2 INT8 真实 PoC(质量+内存+延迟)(§3)
- [x] Bergamot 无中文模型如实记录,不伪造(§3)
- [x] LibreTranslate=Argos=CTranslate2 关系源码级确认(§1/§3)
- [x] 最终排序推荐 + 可执行 Gate(§4/§5)
