# 阅读与时间线

本页覆盖时间线与文章阅读的全部成员功能。功能清单的机读真源是
[feature-manifest.json](https://github.com/paidethon/LumiRSS/blob/main/docs/feature-manifest.json)（`group: "reading"`），
本页逐条展开：能做什么 / 在哪里 / 最短步骤 / 结果 / 限制。

`<!-- screenshot-pending: <feature-id> -->` 标记表示截图尚未生成，截图阶段
会按标记替换为真实截图（可用脚本按 id 定位）。

## 导航入口

### 全部信息源（首页时间线） {#reading-nav-home}

<!-- screenshot-pending: reading.nav.home -->

按时间倒序展示你有权限阅读的全部来源条目。入口：侧栏「阅读 → 全部信息源」，
移动端为底部 tab「首页」。步骤：登录后默认进入；点列表项打开阅读页。结果：
打开文章不会自动标记已读——已读永远由你显式操作（或开启下文的自动已读选项）。
限制：排序默认最新优先，可在设置中改为最早优先。

### 稍后读 {#reading-nav-read-later}

<!-- screenshot-pending: reading.nav.read-later -->

把想晚点看的文章收进独立的稍后读队列。入口：侧栏「阅读 → 稍后读」。步骤：
在列表项或阅读页选择「加入稍后读」，之后从该入口统一消化。结果：与收藏
互相独立，处理完可移除。

### 收藏（视图与底部 tab） {#reading-nav-starred}

<!-- screenshot-pending: reading.nav.starred -->

星标文章的统一视图。入口：侧栏「阅读 → 收藏」；移动端另有底部 tab「收藏」。
步骤：在列表或阅读页点星形收藏，回到该入口查看。结果：收藏跨来源聚合，
不受订阅增删影响。

## Reader 工具栏

工具栏动作的排布与显隐可在「更多操作」里自定义，桌面与移动端各自记忆
（动作语义不变，只调排布）。锁定动作（收藏、更多操作）不可移除。

### 收藏（工具栏） {#reading-toolbar-star}

<!-- screenshot-pending: reading.toolbar.star -->

给当前文章加星/取消星标。入口：阅读页工具栏星形按钮（锁定常显）。步骤：
点击切换。结果：写入 FreshRSS 的星标状态（set 语义，不做盲目 toggle）。

### 打开原文 {#reading-toolbar-open-original}

<!-- screenshot-pending: reading.toolbar.open-original -->

在新标签页打开文章原始网页。入口：阅读页工具栏外链按钮。结果：外链使用
安全协议并带适当 `rel` 值；Lumi 不代理原文页面。

### 保存快照 {#reading-toolbar-snapshot}

<!-- screenshot-pending: reading.toolbar.snapshot -->

把当前文章保存为网页快照，防原文失效。入口：阅读页工具栏相机按钮。
结果：快照归入「来源 → 网页快照」，可回看历史版本。

### AI 对话 {#reading-toolbar-ai-chat}

<!-- screenshot-pending: reading.toolbar.ai-chat -->

针对当前文章与 AI 追问对话。入口：阅读页工具栏对话按钮。前提：设置 → AI
已配置 Profile 并分配 chat 用途（未配置时入口诚实提示不可用，不会假装
能用）。详见 [AI 功能](./features-ai)。

### 语言视图 {#reading-toolbar-language-view}

<!-- screenshot-pending: reading.toolbar.language-view -->

切换当前文章的原文/译文视图。入口：阅读页工具栏语言按钮。结果：切换的是
展示层，不改动原文与译文数据；翻译本身见 [AI 功能](./features-ai)。

### 文内查找 {#reading-toolbar-find}

<!-- screenshot-pending: reading.toolbar.find -->

在当前文章正文内查找关键词并逐个跳转。入口：阅读页工具栏搜索按钮。结果：
命中处高亮，可上下切换；不改动阅读位置记忆。

### 文中链接 {#reading-toolbar-links}

<!-- screenshot-pending: reading.toolbar.links -->

列出当前文章全部链接，集中处理外链。入口：阅读页工具栏链接按钮。结果：
可逐条打开或复制；追踪参数按隐私设置清理。

### 朗读 {#reading-toolbar-speech}

<!-- screenshot-pending: reading.toolbar.speech -->

把正文转成语音朗读。入口：阅读页工具栏喇叭按钮。前提：设置 → AI 已分配
tts 用途（OpenAI 兼容 /audio/speech）。结果：音频经服务端缓存（50MB LRU），
可在「数据控制 → 音频生成缓存」清理。限制：可导出听读音频（N099）目前
不可用，实现台账中为 blocked。

### 分享 {#reading-toolbar-share}

<!-- screenshot-pending: reading.toolbar.share -->

分享当前文章链接。入口：阅读页工具栏分享按钮。结果：优先调系统分享，
不支持时回退为复制链接（F21 回退路径诚实降级，不假装成功）。

### 复制引用 {#reading-toolbar-quote}

<!-- screenshot-pending: reading.toolbar.quote -->

把文章整理成「标题 / 来源 / 链接 + 选区引文」的引用文本。入口：阅读页
工具栏引用按钮，支持纯文本与 Markdown 两种格式。结果：写入剪贴板；
选区超过 500 字自动截断。

### 打印 {#reading-toolbar-print}

<!-- screenshot-pending: reading.toolbar.print -->

用浏览器打印/另存 PDF 当前文章。入口：阅读页工具栏打印按钮。结果：打印
视图只保留正文与元信息，去掉界面 chrome。

### 位置校准 {#reading-toolbar-calibrate}

<!-- screenshot-pending: reading.toolbar.calibrate -->

手动校正本机的阅读位置记忆（章节 + 段落显式选择）。入口：阅读页工具栏
准星按钮。结果：写回本机位置记忆，下次打开恢复到校正位置。限制：位置
记忆按设备本地存储，不跨设备同步。

### 媒体预算 {#reading-toolbar-budget}

<!-- screenshot-pending: reading.toolbar.budget -->

查看并限制单篇文章的媒体流量（已知体积 + 只读文字/按次加载）。入口：
阅读页工具栏仪表按钮。结果：大图/视频按次确认加载，节省流量。

### 更多操作 {#reading-toolbar-more}

<!-- screenshot-pending: reading.toolbar.more -->

收纳低频动作并提供工具栏自定义对话框。入口：阅读页工具栏「⋯」（锁定
常显）。步骤：点开菜单使用收纳的动作，或进入「自定义工具栏」重排/隐藏。
结果：桌面与移动端各存一套次序；全隐藏会被拒绝（至少保留一个动作）。

## 阅读工具

### 按屏翻页 {#reading-tool-paged}

<!-- screenshot-pending: reading.tool.paged -->

以约一屏为单位翻页（步长 0.9 屏高，保留阅读参照）。入口：阅读页滚动
控制。结果：开启「减少动效」时瞬时翻页，不做平滑动画。

### 自动滚屏 {#reading-tool-autoscroll}

<!-- screenshot-pending: reading.tool.autoscroll -->

按慢/中/快三档自动向下滚动正文。入口：阅读页滚动控制。结果：可暂停/
恢复；切出页面自动停止。

### 回到顶部 {#reading-tool-back-to-top}

<!-- screenshot-pending: reading.tool.back-to-top -->

长文滚动超过 600px 后出现悬浮按钮，一键回顶。入口：阅读页右下悬浮按钮。

### 宽表格展开 {#reading-tool-table-expand}

<!-- screenshot-pending: reading.tool.table-expand -->

正文里横向溢出的表格出现展开控件，可全宽查看。入口：正文内表格右上。
限制：只对实际溢出（超出 24px 以上）的表格出现，避免抖动误判。

## 阅读行为（设置 → 阅读）

### 正文读到底自动已读 {#reading-behavior-auto-mark-read}

<!-- screenshot-pending: reading.behavior.auto-mark-read -->

读到正文末尾并停留约 1 秒后自动标为已读。入口：设置 → 阅读 → 阅读行为，
默认关。结果：只有主动滚动算进度（恢复位置、图片加载、自动滚屏不算）；
短文提供「读完了」按钮；手动设为未读的文章本次不再自动标记。

### 滚动时标记已读 {#reading-behavior-scroll-mark-read}

<!-- screenshot-pending: reading.behavior.scroll-mark-read -->

文章完全滚出列表上方后才自动标为已读（默认关）。入口：设置 → 阅读 →
阅读行为。结果：离开后短暂停顿确认；手动未读保护，同一轮滚动不会二次
标记。

### 分页阅读模式与点按翻页区 {#reading-behavior-paged-mode}

<!-- screenshot-pending: reading.behavior.paged-mode -->

正文滚动阅读或分页阅读（CSS 多栏整页翻页）。入口：设置 → 阅读 → 阅读
模式；分页时可配点按翻页方向（左右/上下）与命中区大小（关/22%/40%）。
结果：点按链接、选择文字、横滚表格时不会误翻页。

### 纯键盘阅读定位 {#reading-behavior-key-nav}

<!-- screenshot-pending: reading.behavior.key-nav -->

Alt+↑/↓ 在标题/链接/代码块/批注间跳转，Alt+Shift+↑/↓ 切换类别。入口：
设置 → 阅读 → 阅读行为（设备本地开关）。结果：只定位，不改动已读状态；
顺序按会话记忆。

### 阅读进度条 {#reading-behavior-progress}

<!-- screenshot-pending: reading.behavior.progress -->

阅读页顶部显示当前进度。入口：设置 → 阅读 → 阅读行为。

### 卡片滑动操作（移动端） {#reading-behavior-card-swipe}

<!-- screenshot-pending: reading.behavior.card-swipe -->

列表卡片左右滑触发 已读/稍后读/收藏（可关）。入口：设置 → 通用 → 卡片
滑动操作。限制：仅移动端触摸；屏幕左缘 24px 保留给返回手势。

### 外接键盘阅读模式 {#reading-behavior-keyboard-reading-mode}

<!-- screenshot-pending: reading.behavior.keyboard-reading-mode -->

外接键盘下的当前页命令目录与会话级启用。入口：设置 → 快捷键 → 外接
键盘。结果：含只显示不执行的按键测试，方便核对映射。

### 时间线列表设置 {#reading-behavior-timeline-list}

<!-- screenshot-pending: reading.behavior.timeline-list -->

列表密度（紧凑/标准/舒适）、摘要、封面、相对/绝对时间、排序默认值、
按日期/来源分组、已读变暗、启动仅看未读。入口：设置 → 通用 →
时间线。限制：按来源分组只对已加载条目分组（诚实标注，不假装全量）。
搜索命中高亮属于设置 → 通用 → 搜索，见
[整理、搜索与数据控制](./features-organize)。

### 阅读手势训练与练习区 {#reading-gesture-training}

<!-- screenshot-pending: reading.gesture.training -->

在合成文章上演练侧滑返回等手势，动作只记台账不真实执行。入口：设置 →
通用 → 手势。结果：先练后用，降低误触成本。

## 阅读样式（设置 → 阅读）

### 排版与中文深度排版 {#reading-style-typography}

<!-- screenshot-pending: reading.style.typography -->

字号/行距/边距的连续调节（可恢复默认），中文首行缩进、标点悬挂、简繁
转换、阅读时间、词首强调。入口：设置 → 阅读 → 排版 / 中文排版。结果：
与 Reader 内 Aa 面板共用同一份设置，处处一致。

### 正文字体管理 {#reading-style-fonts}

<!-- screenshot-pending: reading.style.fonts -->

上传 WOFF2 自定义字体或填字体 URL，四档字族可选。入口：设置 → 阅读 →
背景与字体。

### 排版预设与阅读背景 {#reading-style-presets-background}

<!-- screenshot-pending: reading.style.presets-background -->

排版预设一键切换/派生/导入导出；阅读背景色板 + 自定义 hex，文字色随
背景 WCAG 自适应。入口：设置 → 阅读 → 背景与字体。

### 正文自定义 CSS {#reading-style-custom-css}

<!-- screenshot-pending: reading.style.custom-css -->

只作用于正文的自定义样式，自动加前缀避免影响全局。入口：设置 → 阅读 →
自定义。限制：改不了界面 chrome，只影响文章渲染区。

### 主题包（.lumitheme） {#reading-style-theme-pack}

<!-- screenshot-pending: reading.style.theme-pack -->

把阅读样式打包导出/导入/预览，方便分享排版方案。入口：设置 → 阅读 →
自定义。

### 选词词典 {#reading-dict}

<!-- screenshot-pending: reading.dict -->

正文中选词查词典。入口：设置 → 阅读 → 选词词典。前提：需要你自配词典
查询端点；未配置 = 零外发（不向任何第三方发请求），入口会如实说明。

### 连续阅读护眼提醒 {#reading-rhythm}

<!-- screenshot-pending: reading.rhythm -->

连续阅读一定时长后提醒休息。入口：设置 → 阅读 → 阅读行为。结果：计时
在设备本地完成，不上报服务器。

## 界面与通用（设置 → 外观 / 通用）

### 界面外观 {#appearance-interface}

<!-- screenshot-pending: appearance.interface -->

主题模式（浅色/深色/跟随系统）、强调色板与自定义取色、界面字号与字体、
玻璃效果、侧滑返回、减少动效。入口：设置 → 外观。结果：整体缩放只作用于
界面文字，正文排版在「阅读」分类单独设置；减少动效与系统偏好叠加。

### 功能组合场景向导 {#general-scenario-wizard}

<!-- screenshot-pending: general.scenario-wizard -->

按使用场景（如通勤听读）一键组合多项设置。入口：设置 → 通用 → 功能组合
场景向导。步骤：选场景 → 查看 diff 预览 → 应用。结果：改动可整体撤销，
不会偷偷改设置。
