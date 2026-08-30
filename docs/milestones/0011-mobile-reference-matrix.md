# 0011 Mobile Reference Matrix（参考图对照矩阵 · 草案）

> 状态：Gate 0 草案，随各 Gate 填充"目标组件"与"验证证据"列。
> 优先级：交互语义与信息架构 > 视觉层级与节奏 > 响应式关系 > 精确像素。
> 原则：参考图是设计意图，不是复刻对象——不复制状态栏/9:41/固定 390px/示例数据/第三方资产。

| 页面/区域 | 参考图意图 | 当前实现 | 真实数据来源 | 目标组件 | 响应式规则 | 允许偏差 | 验证证据 |
|---|---|---|---|---|---|---|---|
| 侧边栏-品牌区 | LumiRSS + 流光阅源 副标题；右上角圆形设置按钮 | 品牌区只有标题+副标题，设置在侧栏底部整行按钮 | — | SidebarHeader（Gate 1 已实现） | 同一组件用于移动抽屉与桌面侧栏 | 设置图标样式细节 | Gate 1 浏览器截图 ✓（390 抽屉 + 1440 桌面） |
| 侧边栏-全部信息流 | 独立选中项，高亮背景 | 已实现（NavItem active） | view=all+selectedFeedUrl=null | 保留 | — | — | 既有测试 |
| 侧边栏-RSS 根节点 | disclosure 可折叠（默认收起），右侧计数 | 平铺：点击"RSS 订阅"无折叠语义，feeds 永久摊开 | useFeeds（无分类字段） | RssDisclosure（Gate 1 已实现，默认收起） | 默认收起，每会话重置 | 无分类契约→只显示"未分组"组，不显示设计/AI 等假分类 | Gate 1 浏览器验证 ✓（aria-expanded + 展开列 4 真实 feed） |
| 侧边栏-分类分组 | 柔彩文件夹 + 分类名 + feed 数 + 展开箭头 | 无（Feed 契约仅 title/feedUrl） | 无契约 | 不实现（诚实降级为未分组） | — | 整块区域允许偏差（契约缺口，记录给 0013+） | Gate 1 ✓（仅未分组） |
| 侧边栏-Phase 2 项 | 可见 + Phase 2 徽标 | 已实现（PlannedItem） | — | 保留 | — | — | 既有测试 |
| 侧边栏-工作区 | 简洁入口：时间线/收藏 | "ME 时间线 · 未读 / ME 时间线 · 收藏" 冗余标签 | view 语义 | 去重为 时间线 / 收藏（Gate 1 已实现；未读为过滤子项） | — | 未读入口形态按现有语义最清晰方式 | Gate 1 浏览器截图 ✓ |
| 移动抽屉 | 保留右侧内容上下文、backdrop dim、圆角 | 已有（85% 宽、backdrop、Escape/✕/导航关闭） | — | MobileNavigationDrawer（Gate 2 已升级完整 modal，基于增强 Sheet） | w-[min(85vw,20rem)] + rounded-r-xl + safe-area；scroll lock + focus trap + 焦点恢复 | 具体 inset/圆角值用 Lumi token | Gate 2 浏览器验证 ✓（modal 链 4/4 + 390/768/360 无溢出） |
| 底部导航 | 悬浮圆角导航岛，四等宽 tab（首页/订阅/搜索/收藏），active 蓝色 | 贴边矩形条，三 tab（时间线/收藏/设置） | — | MobileTabBar 重构（Gate 1 已实现） | <768 显示；safe-area；≥44px | 具体圆角/阴影用 Lumi token，非复刻 | Gate 1 浏览器截图 ✓ + gate-d 测试 |
| 共用 Header | 三列 grid：菜单 / 居中页面标题 / 右侧操作 | 左对齐 LumiRSS + scope 副标题两行 | — | MobilePageHeader（Gate 1 已实现） | sticky + 滚动阴影 + safe-area | 右侧只放真实可用操作，无则占位 | Gate 1 浏览器验证 ✓（360/390 headerGrid 44/1fr/44） |
| 首页-卡片 | 来源→时间/状态→标题→摘要→分类/阅读时长→右侧缩略图 | 纯文本两行行（EntryRow） | 契约无摘要/缩略图/分类/阅读时长 | EntryCard 文本退化版（Gate 3 已实现，移动端 max-lg） | 无图自动文本布局，不留空洞 | 摘要/缩略图/分类/阅读时长全部缺失（契约缺口，不做假） | Gate 3 浏览器截图 ✓（390 卡片 + 桌面 Row 密度不变） |
| 首页-日期分组 | 今天 / 昨天 分节 | 已实现（entry-groups，0010a） | publishedAt | 保留 | — | — | 既有测试 |
| 首页-scope 标题 | 居中动态 scope + 下拉 | 左对齐副标题 | view/selectedFeedUrl | MobilePageHeader 居中（Gate 1/3 已实现，390 实测动态 scope） | 超长降级为通用标题 | 下拉切换器延后（右侧真实过滤入口替代） | Gate 3 浏览器验证 ✓（首页标题动态 scope） |
| 订阅页 | Header（菜单/订阅/+）+ 搜索订阅源 + 添加RSS/OPML/分组管理 + 分类折叠 feed 列表（favicon/说明/未读数/更多菜单） | 不存在该页面 | useFeeds（仅 title/feedUrl；无 favicon/说明/未读数） | SubscriptionsPage（Gate 4 已实现：只读列表+本地过滤+未分组折叠） | 复用 app shell | CRUD 动作禁用+0013 徽标；统一 RSS 图标；无未读数不显示 | Gate 4 浏览器截图 ✓（4 真实 feed + 过滤 + feed 导航回首页） |
| 搜索页 | 搜索框 + 范围 chips + 搜索历史 + 热门搜索 + 结果(128)/相关度 | 不存在该页面 | BFF 无 search 端点 | SearchPage（Gate 4 已实现：壳+历史+诚实空态，决策 2） | — | chips 不渲染（无契约）；热门搜索省略；结果数/相关度不显示 | Gate 4 浏览器验证 ✓（Enter 提交+历史持久化 localStorage 实测） |
| 收藏页 | Header + 搜索框 + 全部/文章/稍后读/已标星 chips + 最近收藏/更早分组 + 清空 | 不存在独立页面（starred 是 view） | useEntries('starred') | FavoritesPage（Gate 3 已实现：复用 starred 查询 + EntryCard + 最近收藏/更早分组） | 复用 EntryCard | 搜索框/chips 不渲染（无契约）；无"稍后读"不伪造；无清空 API 不显示 | Gate 3 浏览器截图 ✓（分组+星标+进入 Reader+返回） |
| 状态矩阵 | loading/empty/error/长文本/无图/dark/reduced-motion | 部分已有 | — | Playground 扩展 | dev-only | fixture 与生产 API 类型分离 | Gate 5 截图矩阵 |

## 契约缺口登记（不造假，留给后续里程碑）

| 缺口 | 影响区域 | 处理 | 归属 |
|---|---|---|---|
| Feed 无 category | 侧边栏/订阅页分组 | 仅显示真实"未分组" | 0013（订阅中心可扩展 FreshRSSControlAdapter 时评估） |
| Feed 无 favicon/描述 | 订阅页 feed 行 | 统一 RSS 图标或确定性首字母占位 | 同上 |
| Feed/列表无未读数 | 侧边栏/订阅页徽标 | 不显示数量 | 0012+ 评估 unread-count 契约 |
| EntryListItem 无摘要/缩略图/阅读时长 | 首页/收藏卡片 | 文本退化 | 未来 reader/list 增强（需用户批准 BFF 变更） |
| 无全局搜索 API | 搜索页 | 页面壳 + 诚实空态；可选 0011a | 0011a（若批准） |
