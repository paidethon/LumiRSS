# TRANSLATION_REUSE.md — Read Frog 复用分析与 LumiRSS 翻译数据流

> 对象：https://github.com/mengxi-ream/read-frog （main，HEAD `e3cbe2b`，2026-09-07，**GPL-3.0**）
> 详细模块清单：`/home/zephyr/projects/research/reports/read-frog-research.md`（路径+符号+行数）
> LumiRSS 许可证：**AGPL-3.0**（根 LICENSE）。GPL-3.0 → AGPL-3.0 单向兼容（FSF 明示 GPL-3.0 作品可并入 AGPL-3.0 项目），因此**源码级移植在许可上可行**，需在 THIRD_PARTY_NOTICES.md 登记来源与许可。本任务未复制其代码（维护成本优先），以下为采纳/放弃决策记录。

## 1. 采用 / 借鉴 / 放弃（逐项依据）

| Read Frog 模块 | 决策 | 依据 |
|---|---|---|
| 令牌桶请求队列 / 优先队列 / 重试策略（request/ 五件套） | **借鉴行为，自行实现** | LumiRSS 的翻译发生在 BFF（Python），语言不同；BFF 侧已实现等效约束：有界批次（≤64 块/≤12000 字符）、≤4 并发、每文章串行锁、单批一次尝试（失败成行、显式重试）。Web 端无需重复限流（单用户单文章流）。 |
| 批处理 + `<b>/<i>` 定界符协议 + 数量不匹配降级 | **采纳协议思想**（d3cf014） | `ai_translation_segments.py`：`<<<BLOCK n>>>` 定界符 + `parse_segment_batch` 全量校验——任一标记缺失/为空 → 整批按 invalid_response 诚实失败，绝不静默丢段。与 Read Frog 的 BatchCountMismatchError 同思路。 |
| 双语=段内插 wrapper；仅译文=原地文本交换+快照恢复 | **采纳 DOM 策略思想，简化实现** | LumiRSS `lib/translation-blocks.ts`：双语=`.lb-pair` 包裹（宽屏 grid 双栏、窄屏单列）；仅译文=隐藏有译文的原文块+原位插入译文。未搬 runtime 状态机（extension 场景要对抗站点 DOM 篡改，LumiRSS 渲染自己的 sanitize HTML，无此对抗需求）。 |
| 不翻译内容跳过（PRE/SVG/MathML 不进；空块/纯数字跳过） | **采纳规则子集** | `annotateBlocks`：pre/code 整块跳过、无文本块跳过、嵌套块由最外层代表（避免碎片化）。URL 正则跳过未实现（Read Frog 也没有；目标语言跳过留作后续）。 |
| 稳定块 ID / walkId 追踪 | **采纳** | `data-lb-index` 文档顺序编号 + 每块文本哈希进缓存身份（BFF 端），配对绝不用换行猜测。 |
| Provider zod schema / 20+ provider 工厂 | **放弃** | LumiRSS 边界：API Key 只在服务端（SecretsStore），Web 不建第二套 provider 存储；AI Profile 体系（0017）已覆盖 openai-compatible 通用网关（Ollama/LM Studio 走同一入口）。 |
| 浏览器扩展专属（WXT、消息总线、background fetch、托管 AI） | **不适用** | LumiRSS 是 BFF 架构的普通 Web 应用，无扩展宿主。 |
| 失败段落原地可重试 UI | **采纳**（d3cf014） | 状态栏"N 段失败 + 只重试失败段"，重试请求只含失败块。 |
| IntersectionObserver 视口预翻译 | **放弃** | 与"不批量预翻译、打开页面不付费"的钱规则冲突；按需+缓存命中已足够。 |

## 2. 本地机器翻译：运行位置的落实

- **browser（此浏览器执行）**：`lib/local-translator.ts` 适配 Chrome Translator API。能力三态检测（unsupported / 语言对 unavailable / downloadable 需下载），不支持不装可用；结果仅存内存（不写 localStorage）；**绝不静默回退云翻译**（引擎选择是显式设置，回退即违背用户选择）。设置页如实标注"此浏览器执行（正文不出设备）"。真实浏览器验证受限：无 Chrome 138+ 桌面图形环境，检测与失败路径以 jsdom mock 验证——见 VALIDATION.md 未验证项。
- **libretranslate（自托管服务器执行）**：BFF `ai_translation_segments.py` 经 httpx 调 `/translate`（批量 q 数组、20s 超时、语言映射 zh-CN→zh、可选 API Key 走 SecretsStore、失败成行）。设置页提供地址+Key+连接测试。未连真实 LibreTranslate 服务（模型下载/资源约束），以 MockTransport 验证——标注为未验证真实集成。
- **ai（AI 提供者执行）**：复用 0017 Profile 体系（translation 用途映射），OpenAI-compatible 通用入口天然覆盖 Ollama 等本地网关。
- 引擎选择持久化在服务端设置（`translation.engine`），Reader 据此路由；BFF 对 engine=browser 的 generate 请求直接拒绝（该引擎永远不经过服务器）。

## 3. 翻译数据流（当前实现）

```
Reader 工具栏（原文/双语/仅译文，Reader 持有 viewMode）
  ├─ original: ArticleContent 直渲染。零翻译请求。
  └─ 双语/仅译文（切换动作 = 显式按需请求）:
       ArticleContent(sanitize HTML) → MutationObserver 稳定后
       annotateBlocks（data-lb-index 文档顺序编号）
       ├─ engine=ai/libretranslate:
       │    POST /entries/{ref}/translation/segments/lookup   ← 只读缓存，零 provider
       │    未生成块 → POST …/generate（一次；有界批；缓存命中免费）
       │    失败块 → 状态栏"只重试失败段"（body 仅失败块）
       └─ engine=browser: 本地 Translator API（内存缓存、AbortController）
       applyOverlay: 译文以 textContent 注入（data-lb-t 节点）
         bilingual: .lb-pair 包裹（≥1024px 双栏 grid，窄屏单列）
         translated: 原文块隐藏、译文原位、媒体/代码/无译文块保留
```

缓存身份（每块）：`(entry_ref, block_index, SHA256(normalized 块文本), provider, model, prompt_version, target_language)`。API Key 不进键；双语/仅译文共用同一行（排版切换零成本）。旧版整篇平铺翻译（0016 `/translation`）保留不动——其缓存仍是"仅译文整篇"视图的有效数据；分块数据缺失时诚实显示未生成，不伪造对齐。

## 4. 迁移与兼容

- 旧 `ai_translations` 表与端点保留（0016 语义不变）；新表 `ai_translation_segments`（0005 迁移，可重复执行语义由 migrations 框架保证）。
- 旧配置兼容：`translation.language` 沿用原 `ai.translation_language` 键；`translation.engine` 默认 `ai`，老用户行为不变。
- 密钥：LibreTranslate Key 走 SecretsStore（write-only，UI 只显已配置状态），不进 localStorage、不进日志、不进缓存键。
