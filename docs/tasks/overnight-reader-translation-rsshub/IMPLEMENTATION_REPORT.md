# IMPLEMENTATION_REPORT.md — 七项需求逐项实施报告

> 分支：`feat/overnight-reader-translation-rsshub-20260907`（自 e3c4de7 = origin/main 内容创建）
> 本地 commit：`c8a1bcc`（备份）→ `1fd589c`（开关文字）→ `d3cf014`（翻译）→ `9228256`（RSSHub）→ `bef5558`（调研报告）→ `8399ed3`（首版收尾报告）→ 2026-09-08 收尾稳定化轮（E2E 关闭 + 安全修复 + 文档对齐，SHA 见 §收尾轮）
> 任务状态文件：[STATE.md](STATE.md)；验收证据：[VALIDATION.md](VALIDATION.md)

## 七项需求完成表

| # | 需求 | 状态 | 说明 |
|---|---|---|---|
| 1 | 按真实仓库状态组织 ~9h 有效工作 | ✅ 已完成 | Gate 0-6 全部执行；无凑时.spend；预算内收敛 |
| 2 | 指定 Folo 分支深度对比 | ✅ 已完成（仅调研） | [FOLO_COMPARISON.md](FOLO_COMPARISON.md)；静态分析（无实测，明确分栏）；许可证结论已按 LumiRSS=AGPL-3.0 修正 |
| 3 | 删除设置开关右侧重复文字 | ✅ 已实现并通过真实集成验证 | commit 1fd589c；7 分类浏览器实测零残留 |
| 4 | 微信读书/Legado 阅读设置调研 | ✅ 已完成（仅调研） | [READING_SETTINGS_RESEARCH.md](READING_SETTINGS_RESEARCH.md)；含 P1/P2 路线 |
| 5 | 翻译统一设置 + 本地翻译 + 工具栏三模式 + 双语对照 | ✅ 已实现（自动化测试通过；真实外部服务未验证的部分见下） | commit d3cf014 |
| 6 | RSSHub 自动识别/配置 + 自定义站点凭据 | ✅ 已实现并隔离栈实测 | commit 9228256 + [RSSHUB_OPERATIONS.md](RSSHUB_OPERATIONS.md) |
| 7 | 修复完整备份报错 | ✅ 根因修复 + 隔离栈备份→恢复→重启全链路实测 | commit c8a1bcc |

状态口径（按任务要求）：无一项使用"已完成"夸口——第 5/6/7 项中所有未经真实外部服务验证的子项在 VALIDATION.md §5 逐条列出。

## 2026-09-08 收尾稳定化轮

七项交付之后，本轮把分支从"功能完成"推进到"可信、可 review、PR-ready"：

1. **E2E 遗留（B/C 类）关闭**：J2 数据依赖与 a11y 对比度问题的修复
   （`f9e86fb`/`6bed703`）已在分支祖先；本轮真实复跑 J2 ×4、a11y 7 项全绿，
   历史问题文档归档至本目录并标注解决。
2. **J4/M3 journeys 修复**：docker 网桥网关漂移改运行时探测；AI key 幂等
   自建前置（write-only API，不覆盖真实 key）；摘要卡三状态收敛。属测试/
   环境缺陷，产品代码与基线零差异。
3. **安全审计**：分支新代码无 P0/P1；修复 env 物化权限窗口期、envKey 遮蔽
   固定 schema 键、控制字符写入时拒绝、凭据表单残留（含 BFF 回归测试 ×2）。
4. **浏览器翻译目标语言修复**：本地引擎按设置目标语言创建（原硬编码
   en→zh-CN），语言变更时重建。
5. **Base UI 契约修复**：RadioOption 改渲染 `<span>`，console error 清零
   （1920 全程采集为证）。
6. **验收工具修复**：gate6 脚本可见性过滤 + 新增 1920/console 采集脚本。
7. **文档对齐**：STATE/VALIDATION/IMPLEMENTATION_REPORT 三者一致，四类
   证据（自动化/真实集成/浏览器/未验证）分开列明。

## 最重要的根因与变更

1. **备份报错（#7）**：表层根因是 dev 栈宿主机 BFF 读不到命名卷里的 FreshRSS 数据；更深的两个隐患：(a) FreshRSS 把 `users/<user>/` 建为 0770 root:www-data，`os.walk` 默认静默跳过 → 可能产出**缺用户库的假完整包**（预检与采集双双改为遇不可遍历目录诚实失败）；(b) prod BFF（uid 10001）同样读不了 → compose 加 `group_add: ["33"]`（实测生效）。dev 栈交付 opt-in bind-mount 迁移（数据保留、可回滚）。
2. **开关重复文字（#3）**：`SettingItem` 把 `${label}开关` 传给 Switch 的可见 span。改为 Switch 只渲染控件、`label`=可访问名、行标题经 `aria-labelledby`+`htmlFor` 关联（点击标题可切换、读屏名称=标题）。
3. **翻译（#5）**：从"整篇平铺"扩展为"稳定块 ID 分块"——客户端 DOM 分块（data-lb-index），BFF 按块哈希缓存（有界批、定界符协议、失败成行、只重试失败块）；工具栏三态控件替代正文内旧开关；浏览器本地翻译引擎（执行位置如实标注）；翻译设置统一入「设置 → 翻译」，AI 页去除重复表单。
4. **RSSHub（#6）**：有界探测自动识别；自定义站点凭据 CRUD（值写只读）；服务端物化 0600 env 文件 + 宿主机 apply 脚本（dry-run 默认、只重建 rsshub）——修正"restart 不带新 env"的经典误区。

## 代码导航（commit 固定链接，行号免漂移）

- 备份预检/采集/端点：`c8a1bcc` services/bff/src/lumirss/backup.py、models.py、main.py；UI BackupOverview.tsx
- Switch/SettingItem：`1fd589c` apps/web/src/components/ui/Switch.tsx、settings/SettingItem.tsx
- 分块翻译：`d3cf014` services/bff/src/lumirss/ai_translation_segments.py、migrations/0005；web lib/translation-blocks.ts、lib/local-translator.ts、ReaderTranslation.tsx、ReaderHeader.tsx、TranslationSettingsSection.tsx
- RSSHub：`9228256` services/bff/src/lumirss/rsshub_control.py、scripts/apply_rsshub_config.py；web settings/RssHubAutoConfigCard.tsx
- 契约：openapi.json/schema.ts 随各 commit 再生成（api:check 通过）

## 尚需人工处理的最小步骤

```bash
# A. 让你本机的完整备份真正生效（数据保留，1-2 分钟）：
docker cp freshrss:/var/www/FreshRSS/data/. /home/zephyr/projects/LumiRSS/data/freshrss-data/
cd /home/zephyr/projects/LumiRSS
docker compose -f docker-compose.yml -f docker-compose.dev-backup.yml up -d freshrss
docker exec freshrss sh -c 'chmod -R a+rX /var/www/FreshRSS/data'
# 之后 设置 → 数据控制 → 备份概览 应显示 fullBackupReady（或刷新页面）
# 回滚：撤掉 override 重新 up -d freshrss（旧命名卷未删）

# B. RSSHub 配置应用（下次改配置时）：
# 设置 → RSSHub → 生成 env 文件 → 运行 services/bff/scripts/apply_rsshub_config.py（见 RSSHUB_OPERATIONS.md SOP）

# C. prod 已部署环境升级权限修复（下次部署时）：
# docker compose -f docker-compose.prod.yml up -d --force-recreate bff   （group_add 已入 compose）
```

## 未完成内容与继续入口

- LibreTranslate / Chrome Translator API 真机验证：待有服务/环境后按 VALIDATION.md §5.2/5.3 复验（代码与失败路径已就绪）。
- BFF 镜像构建：网络代理解除后 `docker build services/bff` 常规执行即可（ghcr.io uv 拉取仍被代理阻断，2026-09-08 复现）。
- 安全审计 0021 candidates：VALIDATION.md §6。
- 阅读设置 P1/P2 路线（背景双主题、Web Speech 朗读等）：READING_SETTINGS_RESEARCH.md §2。
- Folo 可复用项（fuse.js 搜索、react-virtual）：FOLO_COMPARISON.md §3，建议各立小任务。
