# 整理、搜索与数据控制

本页覆盖搜索、工作区、标签整理、批注笔记与数据控制。机读真源：
[feature-manifest.json](https://github.com/paidethon/LumiRSS/blob/main/docs/feature-manifest.json)（`group: "organize"`）。

`<!-- screenshot-pending: <feature-id> -->` 为截图占位标记，截图阶段按 id
替换。

## 搜索

### 全局搜索 {#organize-search}

<!-- screenshot-pending: organize.search -->

跨全部条目的全文搜索（段落级命中）。入口：侧栏「工具 → 搜索」。步骤：
输入关键词 → 查看命中段落 → 点开定位到原文。结果：搜索是 SQLite 上的
派生投影，可重建，不复制 FreshRSS 数据。原理见
[全局搜索原理](../explanation/search)。

### 高级搜索 {#organize-search-advanced}

<!-- screenshot-pending: organize.search.advanced -->

时间刷、拼写建议、语言过滤、排除词。入口：搜索页筛选区。结果：筛选
条件可组合，排除词持久生效。

### 保存的搜索视图 {#organize-search-views}

<!-- screenshot-pending: organize.search.views -->

把一组搜索条件存为视图，可置顶排序，并可导出 Atom 订阅。入口：搜索页 →
保存视图。结果：Atom 地址含密钥 token，泄露即失效面，注意保管。

### 搜索同义词 {#organize-search-synonyms}

<!-- screenshot-pending: organize.search.synonyms -->

自定义同义词让搜索命中变体写法。入口：搜索页 → 同义词管理。

### 搜索命中高亮 {#general-search-highlight}

<!-- screenshot-pending: general.search-highlight -->

搜索结果中高亮命中片段（默认开）。入口：设置 → 通用 → 搜索。

## 工作区

### 工作区 {#organize-workspaces}

<!-- screenshot-pending: organize.workspaces -->

把订阅/标签/筛选组织成不同的阅读场景。入口：侧栏「工具 → 工作区」。
结果：工作区互相独立，可存模板复用。

### 工作区设置 {#organize-workspace-settings}

<!-- screenshot-pending: organize.workspace.settings -->

改名、改说明、归档、导出、删除。入口：设置 → 工作区。限制：后端没有的
能力（图标/颜色、逐工作区默认排序）不做假开关。

### 工作区目标 {#organize-workspace-goals}

<!-- screenshot-pending: organize.workspace.goals -->

给工作区设阅读目标与达成条件。入口：工作区 → 目标。

### 工作区看板 {#organize-workspace-board}

<!-- screenshot-pending: organize.workspace.board -->

工作区条目的看板视图。入口：工作区 → 看板。

## 标签与整理

### 标签与图谱 {#organize-graph}

<!-- screenshot-pending: organize.graph -->

标签管理与关系图谱可视化。入口：侧栏「工具 → 标签 / 图谱」。结果：图谱
视图可保存为自定义视图。

### 标签合并向导 {#organize-tags-merge}

<!-- screenshot-pending: organize.tags.merge -->

把重复/相近标签安全合并：先预览影响，再执行，全程留日志。入口：标签页 →
合并向导。

### 标签组 {#organize-tags-groups}

<!-- screenshot-pending: organize.tags.groups -->

把标签组织成组便于浏览，冲突有提示。入口：标签页 → 标签组。

### 标签同义词 {#organize-tags-synonyms}

<!-- screenshot-pending: organize.tags.synonyms -->

让同义标签在统计与过滤时归一。入口：标签页 → 同义词。

### 文章过滤规则 {#organize-filters}

<!-- screenshot-pending: organize.filters -->

按条件隐藏/降权列表条目（显示层过滤）。入口：设置 → 文章过滤。结果：
过滤是展示层行为，不删除任何数据。

### 个人术语本 {#organize-filters-glossary}

<!-- screenshot-pending: organize.filters.glossary -->

个人译名对照表，翻译时优先采用。入口：设置 → 文章过滤 → 个人术语。
限制：术语本参与翻译管线，需 AI 翻译才有实际效果。

### 快捷键分配 {#organize-shortcuts}

<!-- screenshot-pending: organize.shortcuts -->

捕获按键分配动作、冲突覆盖、恢复默认、导入导出。入口：设置 → 快捷键。
结果：与帮助弹窗同一份动作目录，不会出现文档与实现不同步。

### 多步快捷操作 {#organize-quick-actions}

<!-- screenshot-pending: organize.quick-actions -->

把多个动作串成一条快捷操作，定义在服务端，执行走各动作 NORMAL 端点。
入口：设置 → 快捷键 → 多步快捷操作。

### 阅读队列与阅读计划 {#organize-reading-queue}

<!-- screenshot-pending: organize.reading-queue -->

时段安排、前置条件、工作量、容量、提醒、阅读契约、主题分组。入口：
工作区/首页 → 阅读队列（NEW-221..230 家族）。结果：全部是「用户决策」
模型——系统给建议，排队与计划由你确认。

### 批量归档 {#organize-archive-batches}

<!-- screenshot-pending: organize.archive-batches -->

多选条目按批次归档：先预览范围再执行，支持撤销。入口：列表多选 → 归档。

## 批注与笔记

### 批注与精选篮 {#organize-annotations}

<!-- screenshot-pending: organize.annotations -->

正文选中即批注；批注可回复、分享、导出 Markdown，收进精选篮。入口：
阅读页选中文本。结果：原文变化时批注可重锚定（re-anchor），锚定历史
可查。

### 批注图层 {#organize-annotation-layers}

<!-- screenshot-pending: organize.annotation-layers -->

批注按图层组织，可整层导出与迁移（先预览后应用）。入口：批注面板 →
图层。

### 阅读笔记与模板 {#organize-notes}

<!-- screenshot-pending: organize.notes -->

文章笔记：模板填充、附件、冲突检测、版本历史与回退。入口：文章 → 笔记。
结果：笔记在 Lumi 自有库中，不写 Obsidian vault。

### 原文版本与来源时间线 {#organize-article-versions}

<!-- screenshot-pending: organize.article-versions -->

记录同一文章的原文变化（diff 可看）与来源维度的时间线。入口：文章 →
原文历史。

### 引用与证据清单 {#organize-citations}

<!-- screenshot-pending: organize.citations -->

抽取文中引用、构建引用链、生成证据核对清单。入口：文章 → 引用。

## 数据控制（设置 → 数据控制）

### 离线资料设备配额 {#organize-data-offline-quota}

<!-- screenshot-pending: organize.data.offline-quota -->

管理本设备离线缓存的配额：枚举、用量、清理预览、应用。入口：设置 →
数据控制 → 缓存。限制：只删本设备 Cache Storage 条目，不碰服务器数据。

### 服务端 TTS 缓存管理 {#organize-data-tts-cache}

<!-- screenshot-pending: organize.data.tts-cache -->

查看音频生成缓存的大小/日期，单条或全部删除（服务端 50MB LRU）。
入口：设置 → 数据控制 → 音频生成缓存。

### 设置变更历史与回退 {#organize-data-settings-history}

<!-- screenshot-pending: organize.data.settings-history -->

设置的历史版本可回退，且不覆盖回退之后的新修改。入口：设置 → 数据
控制 → 配置迁移与备份。

### 非敏感偏好迁移 {#organize-data-preferences-migration}

<!-- screenshot-pending: organize.data.preferences-migration -->

导出/导入版本化的偏好 JSON，diff 预览后才应用。入口：设置 → 数据控制。

### 导出 Lumi 数据 {#organize-data-lumi-export}

<!-- screenshot-pending: organize.data.lumi-export -->

工作区、标签、书签笔记与日报配置导出为版本化 JSON。入口：设置 → 数据
控制。限制：不含密钥与 FreshRSS 订阅——这是与完整备份分开的轻量通道。

### 个人数据迁出/迁入向导 {#organize-data-wizard}

<!-- screenshot-pending: organize.data.wizard -->

选择数据范围 → zip 导出 → 在另一实例导入合并。入口：设置 → 数据控制。

### 存储用量与保留策略 {#organize-data-storage}

<!-- screenshot-pending: organize.data.storage -->

只读的存储用量统计（口径明确）；派生数据保留策略默认关，启用后先预览
再应用，到期有提醒横幅。入口：设置 → 数据控制。

### 完整备份与 WebDAV {#organize-data-backup}

<!-- screenshot-pending: organize.data.backup -->

账户数据的完整备份与恢复，支持 WebDAV 远端与备份历史。入口：设置 →
数据控制。前提：用 WebDAV 远端需先配置凭据。运营者级的实例备份见
[备份与恢复](../how-to/backup-restore)。

### 数据外发清单与活动记录清除 {#organize-data-privacy-flows}

<!-- screenshot-pending: organize.data.privacy-flows -->

逐来源列出数据外发去向（未配置 = 不发送）；登录事件/AI 任务日志/搜索
快照可预览后清除。入口：设置 → 数据控制 → 隐私。

### 隐私与授权中心 {#organize-data-privacy-center}

<!-- screenshot-pending: organize.data.privacy-center -->

访问记录与边界、第三方请求清单、敏感资料标记、设备信任期限、授权撤销、
共享链接范围与次数上限、删除范围预览与处理回执。入口：设置 → 数据控制
→ 隐私。限制：隐私检查向导逐项撤回，故意不做「一键全删」。

### 长期保存与格式互通 {#organize-data-preservation}

<!-- screenshot-pending: organize.data.preservation -->

书目导入、离线站点、JSON Feed、格式对照、加密导出、索引导出、分卷、
逐项对账。入口：设置 → 数据控制 → 长期保存（面板两级情境展开，折叠时
零请求）。

### 通知与帮助中心 {#organize-data-notifications}

<!-- screenshot-pending: organize.data.notifications -->

通知收件箱与聚合规则、静默时段、撤销提示、体验清单、服务状态、处理单、
文档反馈。入口：设置 → 数据控制 → 通知与帮助。
