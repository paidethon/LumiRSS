# AI 功能

本页覆盖全部 AI 能力。共同前提：在「设置 → AI」配置至少一个 Profile
（OpenAI 兼容端点 + 密钥）并把用途（摘要 / 翻译 / 对话 / TTS）分配给它。
未配置时相关入口诚实提示不可用，不会假装能用。机读真源：
[feature-manifest.json](https://github.com/paidethon/LumiRSS/blob/main/docs/feature-manifest.json)（`group: "ai"`）。

`<!-- screenshot-pending: <feature-id> -->` 为截图占位标记，截图阶段按 id
替换。

## 配置与治理

### AI 配置（Profile 与用途分配） {#ai-profiles}

<!-- screenshot-pending: ai.profiles -->

自备 API 端点与密钥：每个 Profile 有自己的模型与密钥，四个用途
（summary / translation / chat / tts）分别映射到 Profile。入口：设置 →
AI → AI 配置。结果：密钥只存服务端，永不下发浏览器、不回显。限制：
仅支持 OpenAI 兼容协议；Gemini 多提供方日报（P17）当前 blocked。

### AI 任务日志与重试 {#ai-task-log}

<!-- screenshot-pending: ai.task-log -->

全部 AI 任务的台账：状态、失败原因、可重试、可回放诊断。入口：设置 →
AI 或 Agent 工作台 → 任务。结果：失败诚实可见，重试只对安全操作。

### AI 用量配额 {#ai-quota}

<!-- screenshot-pending: ai.quota -->

按用途的用量桶与配额窗口（日/月）。入口：设置 → AI → 用量。结果：
配额超限时任务被拒并如实报告。

## 阅读增强

### 文章摘要 {#ai-summary}

<!-- screenshot-pending: ai.summary -->

为当前文章生成摘要，保留多版本并可指定激活版本。入口：阅读页 → AI
摘要。结果：失败可重试（J4 旅程覆盖「失败诚实」路径）。

### 文章翻译（AI / 浏览器） {#ai-translation}

<!-- screenshot-pending: ai.translation -->

两种引擎：AI 翻译（需 translation 用途）与浏览器内置翻译。入口：阅读页
语言视图，或设置 → 翻译。限制：R21 重写后只有这两种方式（LibreTranslate
已移除）；浏览器翻译在不支持的浏览器里诚实提示 unsupported，不假装可用
（J7 旅程）。

### 分段翻译与修订 {#ai-segments}

<!-- screenshot-pending: ai.segments -->

按段落生成与修订译文：单段重译、修订历史、免翻段标记。入口：阅读页
翻译段落操作。结果：修订可回滚，历史可追溯。

### 文章对话（追问） {#ai-conversation}

<!-- screenshot-pending: ai.conversation -->

针对当前文章的多轮追问，支持批量提问与多篇对比。入口：阅读页工具栏
AI 对话。

### 阅读测验 {#ai-quiz}

<!-- screenshot-pending: ai.quiz -->

按文章内容出题并判分。入口：文章 → 测验。

### 朗读（TTS） {#ai-tts}

<!-- screenshot-pending: ai.tts -->

OpenAI 兼容 /audio/speech 语音合成朗读。入口：阅读页工具栏朗读按钮。
结果：服务端缓存（LRU 50MB）。限制：可导出听读音频（N099）blocked。

## 检索与自动化

### 语义检索 RAG {#ai-rag}

<!-- screenshot-pending: ai.rag -->

对全部条目建语义索引（sqlite-vec 单文件实现，无外部向量库）并问答，
答案带证据。入口：设置 → AI → 语义检索（启用/重建/状态），侧栏「RAG
索引」看覆盖与排错。前提：AI 配置就绪并显式启用。结果：索引可暂停/
恢复/收敛/修复，排除目录可控。

### Agent 工作台 {#ai-agent}

<!-- screenshot-pending: ai.agent -->

AI 会话 + 工具调用审批：每个工具调用先展示再批准，作用域受限。入口：
侧栏「工具 → Agent 工作台」。结果：审批制，无静默执行。

### Agent 配方 {#ai-agent-recipes}

<!-- screenshot-pending: ai.agent-recipes -->

把常用 Agent 流程存为配方复用。入口：Agent 工作台 → 配方。

### GPT 日报 {#ai-gpt-digest}

<!-- screenshot-pending: ai.gpt-digest -->

按配置定期把选题池生成日报，可订阅其 Atom。入口：设置 → 邮件简报 →
GPT 日报。结果：日报以 Atom feed 输出，任何阅读器可订。限制：OpenAI
兼容通道可用；Gemini 多提供方（P17）blocked，实现台账中标记为部分。

### 简报工作台 {#ai-briefings}

<!-- screenshot-pending: ai.briefings -->

人工策展 + AI 起草的简报：选题、生成、修订溯源、确认、导出 eml、
Atom 订阅。入口：工作区 → 简报。结果：生成只是草稿，发布需显式确认。
