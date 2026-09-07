# STATE.md — overnight-reader-translation-rsshub

- 基线 SHA：`e3c4de7`（= origin/main 68ded4e 的内容，PR #35 已合并）
- 任务分支：`feat/overnight-reader-translation-rsshub-20260907`（自 e3c4de7 创建）
- 启动时间：2026-09-07（本地）
- 任务输入：根目录 `LumiRSS_ZCode_9h_Prompt.md`（未跟踪，保持原样，不提交）
- 参考项目 clone：`/home/zephyr/projects/research/`（Folo=Guyungy fork、read-frog、legado；不入 LumiRSS）

## 运行环境（Gate 0 已核实）

- 本地栈：FreshRSS 容器（`freshrss`，命名卷 `lumirss_freshrss-data` → /var/www/FreshRSS/data，端口 8080）、RSSHub 容器（1200，healthy）、**宿主机 uvicorn BFF**（`services/bff`，--reload，端口 8000，进程 env 无 FRESHRSS_*）、Vite dev（5173）。
- `services/bff/.env` 现有键：FRESHRSS_BASE_URL / FRESHRSS_USERNAME / FRESHRSS_API_PASSWORD（无 FRESHRSS_DATA_DIR）。
- Compose 项目名 `lumirss`（docker-compose.yml）。

## 七项需求状态

| # | 需求 | 状态 |
|---|---|---|
| 1 | 9 小时有效工作组织 | 进行中 |
| 2 | Folo(Guyungy) 深度对比 | 调研完成：`/home/zephyr/projects/research/reports/folo-research.md`（待整理成 FOLO_COMPARISON.md） |
| 3 | 设置开关重复文字清理 | 实施中（根因：SettingItem.tsx:109 + Switch.tsx:54 可见 span） |
| 4 | 微信读书/Legado 阅读设置调研 | 调研完成：`/home/zephyr/projects/research/reports/reading-settings-research.md`（待整理） |
| 5 | 翻译统一设置 + 本地翻译 + 工具栏三模式 + 双语对照 | 调研完成：`/home/zephyr/projects/research/reports/read-frog-research.md`（注意 GPL-3.0；LumiRSS=AGPL-3.0 可并入但控制维护成本）；实施待开始 |
| 6 | RSSHub 自动配置 + 自定义站点凭据 | 待开始 |
| 7 | 完整备份修复 | **完成（隔离栈真实验证）**，commit 待建 |

## Gate 1 结果（已验证）

- 新端点 `GET /api/v1/backups/capabilities`（assess_freshrss_backup 与执行共用同一判定）；UI 备份概览点击前展示组件/原因。
- **修复 os.walk 静默跳过不可读目录的正确性 bug**（FreshRSS users/<u>/ 是 0770）——否则会产出缺用户库的"假完整包"。
- **发现并修复 prod 拓扑隐患**：BFF 容器 uid 10001 无法读 0770 用户目录 → docker-compose.prod.yml BFF 加 `group_add: ["33"]`（uid10001+gid33 读取已实测）。
- dev 栈：交付 opt-in `docker-compose.dev-backup.yml`（bind mount 迁移说明）；`services/bff/.env` 已加 FRESHRSS_DATA_DIR（等用户跑迁移命令后生效）；dev 补救=容器内 `chmod -R a+rX /var/www/FreshRSS/data`。
- 隔离栈（/home/zephyr/projects/LumiRSS-itest，已清理容器）：备份 succeeded → 归档 29 成员校验和全对、含 users/admin/db.sqlite、无 secrets → 另一隔离实例 preview/RESTORE 执行成功（安全备份+freshrss 离线暂存 27/27 校验和匹配）→ 重启后 profile 持久、keyConfigured=false 如实。证据：LumiRSS-itest/lumi-source/backups/lumirss-20260907T154213Z.backup。
- Hook 约束记录：安全 hook 禁止 shell 复制 FreshRSS 数据（含 config.php）到任何位置 → 用户实例的 bind 迁移列为人工步骤（1 条 docker cp + up -d）。
- BFF 镜像构建在本环境被代理阻断（ghcr.io uv 拉取超时）——Docker 构建验证受限，已记录。

## 基线命令与结果

- BFF：`uv run pytest -q` → **608 passed**（Gate1 后）；ruff clean
- Web：`pnpm test` → **574 passed**；lint 0 errors；tsc -b clean
- api:check/settings:check：生成物一致（提交后 drift 检查可通过）

## 已完成 commit

（Gate 1 提交进行中）

## 下一步

1. Gate 1 commit → Gate 2（Switch 可见文字/可访问名分离 + 调用点 + 测试）。
2. Gate 3 翻译大项（Read Frog 报告在 /home/zephyr/projects/research/reports/）。
3. Gate 4 RSSHub → Gate 5 报告整理 → Gate 6 回归+浏览器验收+报告。

## 阻塞/备注

- 无付费 API 预算：AI 翻译只用 mock/既有免费路径验证。
- 浏览器验收用 Playwright + 无头截图（artifacts 目录，不入 Git）。
