# 内容来源

本页覆盖九类内容来源与来源运维。机读真源：
[feature-manifest.json](https://github.com/paidethon/LumiRSS/blob/main/docs/feature-manifest.json)（`group: "sources"`）。

`<!-- screenshot-pending: <feature-id> -->` 为截图占位标记，截图阶段按 id
替换。

## 来源类型

### RSS 订阅 {#sources-nav-rss}

<!-- screenshot-pending: sources.nav.rss -->

原生 RSS/Atom 订阅，经 FreshRSS 拉取与管理。入口：侧栏「内容来源 →
RSS 订阅」。步骤：设置 → 订阅与来源添加订阅，或来源中心选「RSS 订阅」。
结果：feeds/entries/已读/星标由 FreshRSS 持有，Lumi 不复制 RSS 域数据。
限制：Feed 必须可从实例网络访问（私网地址受 SSRF 策略诚实拒绝，见 J3a
旅程）。

### 来源中心 {#sources-center}

<!-- screenshot-pending: sources.center -->

九类来源的统一入口与分组总览（RSS 订阅 / RSSHub 路由 / API 来源 / 邮件桥
/ 收件箱 / Obsidian / 书签 / 网页剪藏 / 网页快照）。入口：侧栏「内容来源 →
来源」。结果：每类直达各自管理位置。

### 书签 {#sources-bookmarks}

<!-- screenshot-pending: sources.bookmarks -->

保存 URL 供以后读，附链接有效性检查。入口：侧栏「内容来源 → 书签」。
结果：书签是独立来源类型，与收藏（星标）无关。

### 网页剪藏 {#sources-clips}

<!-- screenshot-pending: sources.clips -->

抓取网页正文存为剪藏（服务端经 SSRF 代理抓取，正文经清洗管线）。入口：
侧栏「内容来源 → 网页剪藏」。结果：可重新抓取、保留修订版本。

### 网页快照 {#sources-snapshots}

<!-- screenshot-pending: sources.snapshots -->

把文章或 URL 存为网页快照防失效。入口：侧栏「内容来源 → 网页快照」或
阅读页工具栏「保存快照」。结果：快照有版本，可回看。

### 收件箱 {#sources-inbox}

<!-- screenshot-pending: sources.inbox -->

暂存待整理的条目，配规则自动分流。入口：侧栏「内容来源 → 收件箱」。
结果：规则（GET/POST /api/v1/inbox/rules）按条件自动归位。

### API 来源 {#sources-api-sources}

<!-- screenshot-pending: sources.api-sources -->

把 JSON API 变成 Atom 订阅：JMESPath 映射 → Atom → FreshRSS 订阅。入口：
侧栏「内容来源 → API 来源」（设置深链）或设置 → API 来源。结果：适合
无 RSS 的结构化数据源。

### API 来源映射调试 {#sources-api-mapping}

<!-- screenshot-pending: sources.api-mapping -->

映射采样、预览、分页探测，先验证再落配置。入口：设置 → API 来源 → 具体
来源 → 映射样本。结果：绑定前能看到真实映射输出，降低配置错误。

### 邮件简报（Newsletter 归档） {#sources-newsletter}

<!-- screenshot-pending: sources.newsletter -->

邮件列表/简报的归档视图。入口：侧栏「内容来源 → 邮件简报」。限制：收信
依赖实例的邮件桥配置（见下条）。

### 邮件桥 {#sources-mail-bridge}

<!-- screenshot-pending: sources.mail-bridge -->

实例级邮件收信：收信地址、导入规则、消息线程与解析调试。入口：设置 →
邮件简报。前提：运营者已配置实例邮件收信（IMAP）。结果：邮件材料可导入
归档并生成 Atom 供订阅。

### Obsidian 库（只读投影 + 受限导出） {#sources-obsidian}

<!-- screenshot-pending: sources.obsidian -->

浏览 Obsidian vault：笔记、反链、断链报告。入口：侧栏「内容来源 →
Obsidian 库」。前提：账户已绑定库目录。读面限制：vault 投影保持只读；
唯一的写面是显式的「导出到 Obsidian」（阅读页「更多操作」→
`POST /api/v1/obsidian/export`）：只写独立挂载的导出目录内
`<子目录>/<账户id>/` 下的新文件——绝不覆盖既有文件、content-id 幂等、
每日写入配额（前提：运营者已用
`docker-compose.obsidian-export.yml` overlay 挂出
`LUMIRSS_OBSIDIAN_EXPORT_HOST_DIR`，见
[ADR 0007](../decisions/0007-obsidian-server-side-export.md)）。
多设备同步（P16）为 partial，见实现台账。

### RSSHub 路由订阅 {#sources-rsshub-routes}

<!-- screenshot-pending: sources.rsshub.routes -->

用 RSSHub 把非 RSS 站点变成订阅源。入口：来源中心 → RSSHub 路由分组。
前提：实例配置了 `RSSHUB_BASE_URL`。结果：RSSHub 只是把上游内容变成
feed 的生成器，条目库仍在 FreshRSS。

### RSSHub 控制中心 {#sources-rsshub-control}

<!-- screenshot-pending: sources.rsshub.control -->

服务端 RSSHub 地址/密钥配置与应用内引导。入口：设置 → RSSHub。前提：
实例已部署 RSSHub。结果：配置即真实生效；浏览器侧假控制（参考实例清单）
已退役。

## 来源管理

### OPML 导入 / 导出 {#sources-opml}

<!-- screenshot-pending: sources.opml -->

批量迁移订阅。入口：设置 → 订阅与来源。步骤：导出现有订阅为 OPML，或
导入 OPML（可选分类/选择性导入），导入有日志可查。结果：RSSHub 路由
映射随导出保留；导入时按内置路由元数据自动识别 RSSHub 路由（先实测
有效再替换，原始地址留台账，可撤销）。

### 统一来源注册表 {#sources-registry}

<!-- screenshot-pending: sources.registry -->

全部来源类型总览 + 健康状态 + 深链到各自管理位置。入口：设置 → 订阅与
来源 → 统一来源注册表。

### 来源显示别名 {#sources-aliases}

<!-- screenshot-pending: sources.aliases -->

给订阅起只影响本机的展示名。入口：设置 → 订阅与来源 → 来源显示别名。
结果：设备本地替换展示层，真实订阅名不变，有历史可回退。

### 来源健康 {#sources-health}

<!-- screenshot-pending: sources.health -->

陈旧来源检测与刷新状态总览。入口：设置 → 订阅与来源 → 注册表健康列。
结果：能发现长期无更新或拉取失败的来源。

### 来源接管 {#sources-takeover}

<!-- screenshot-pending: sources.takeover -->

把订阅在分类/归属之间做批次迁移。入口：来源中心 → 来源运维。结果：
批次化执行，可追溯。

### 来源暂停计划 {#sources-pause}

<!-- screenshot-pending: sources.pause -->

按计划暂停/恢复某来源的刷新。入口：来源中心 → 来源运维。结果：暂停
期间不再产生新条目，恢复后接续。
