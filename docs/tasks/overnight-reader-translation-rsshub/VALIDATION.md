# VALIDATION.md — 命令、结果、环境与未验证项

> 分支 `feat/overnight-reader-translation-rsshub-20260907`（基线 e3c4de7 = origin/main 68ded4e 内容）
> 环境：WSL2 Ubuntu；本地开发栈 FreshRSS(8080)+RSSHub(1200)+宿主机 BFF(8000, --reload)+Vite(5173)
> 截图：`apps/web/test-results/gate6/`（gitignored）；隔离栈证据：`/home/zephyr/projects/LumiRSS-itest*/`

## 1. 基线与最终状态

| 检查 | 基线（e3c4de7） | 最终（9228256+） |
|---|---|---|
| BFF `uv run pytest -q` | 592 passed | **632 passed**（ruff clean） |
| Web `pnpm test` | 571 passed | **580 passed**（1 例既有负载超时抖动，复跑即绿） |
| Web `pnpm lint`（oxlint） | 0 errors | 0 errors |
| `tsc -b` | clean | clean |
| `pnpm api:generate` + diff | 一致 | 一致（本次契约变更已再生成并提交） |
| `pnpm settings:check` | 一致 | 一致（本任务未改 portable settings） |

e2e：
- `rapid-selection`（desktop-1440，对 dev 栈 5173）：**passed**（3.1s）——连续切换文章过期覆盖守卫。
- `ci-smoke`（LUMIRSS_CI_STATIC=1，vite preview :4173）：**10 passed**——静态构建 + API 降级诚实态。
- 其余 journeys/a11y 套件：按仓库设计需手动对全栈运行；既有已知问题见 `E2E-ISSUES-B-C-20260906.md`（J2 数据依赖、a11y 对比度 token）——**非本次引入，未回退，留待原修复任务**。

## 2. 真实集成验证（隔离部署，非 mock）

### Gate 1 备份/恢复（LumiRSS-itest，独立 compose 项目/端口 18080/18081/18083/独立目录）
1. 全新 FreshRSS 容器（FRESHRSS_INSTALL 自动安装）+ 宿主机 BFF（独立 DB/数据目录）+ bind mount 数据目录。
2. BFF 播种：订阅（合成 feed 4 条目）→ set 语义状态（2 读、2 收藏）→ AI Profile + Key（入 SecretsStore）。
3. `GET /api/v1/backups/capabilities`：770 目录修复前 `fileCount=6`（假绿）→ 修复后 27 文件/1 sqlite，`fullBackupReady=true`。
4. `POST /api/v1/backups` → succeeded；归档 29 成员、manifest 校验和 29/29 全对、含 `users/admin/db.sqlite`、无 secrets 成员。
5. 第二个隔离实例 `POST /restore/preview`（compatible）→ `POST /restore`（confirmation=RESTORE）→ lumiRestored=true、freshrss 离线暂存 27/27 校验和匹配、暂存库条目状态逐条核对（2 read/2 favorite）。
6. 重启恢复侧 BFF：profile 持久、`keyConfigured=false`（密钥按策略排除）、job 账本诚实（restore succeeded；fixture job "Superseded by a restore"）。
7. prod 拓扑权限修复单独实测：`docker run -u 10001 --group-add 33`（挂 itest 数据卷 RO）→ 可遍历 `users/admin/` 并读取 db.sqlite。

### Gate 4 RSSHub 应用链（LumiRSS-itest2，端口 18090/独立 project）
- BFF 同款路径物化 env（0600；CACHE_EXPIRE=777、WEIBO_COOKIES=合成值、自定义 ITEST_CUSTOM_TOKEN）。
- `apply_rsshub_config.py` dry-run（无变更）→ `--apply` → 容器重建 → 容器内实测三个变量生效 → /healthz 200。

## 3. 浏览器视觉验收（Playwright chromium，dev 栈 5173）

| 检查 | 结果 | 证据 |
|---|---|---|
| 设置 7 分类无"XX开关"重复文字 | ✅ 全空 | `switch-duplicate-text.json`（通用/外观/阅读/翻译/AI/RSSHub/数据控制） |
| Reader 工具栏三态控件在位 | ✅ 原文/双语/仅译文各 1 | `reader-toolbar.json` + `04-reader-after-select.png` |
| 旧正文内"原文/译文"控件已移除 | ✅ `文章语言视图` group=0 | 同上 |
| 双语模式：原文保留 + 引擎/状态行如实 | ✅ | `05-reader-bilingual.png`（"AI 翻译（AI 提供者执行）· 翻译中…"） |
| 翻译设置页（引擎/运行位置/目标语言/按需说明/Profile 指引） | ✅ | `03-settings-翻译.png` |
| 备份概览点击前诚实显示（历史失败保留 + path_missing 原因） | ✅ | `03-settings-数据控制.png` |
| 移动端 390：桌面分段隐藏、紧凑菜单在、无横向溢出 | ✅ | `mobile-toolbar.json` + `10-mobile-language-menu.png` |
| 移动端工具栏溢出缺陷（打开原文竖排） | ✅ 已修复（flex-wrap + whitespace-nowrap） | `09-mobile-reader.png`（修复后） |
| 深色模式逐像素复检 | ⚠️ 未完成 | 应用主题为自管 setting；token 体系由既有 15 个 theme 单测覆盖 |

## 4. 性能复查（同条件，改前 vs 改后 limited）

- `rapid-selection` e2e（连续快速选择 5 篇，断言最后选择胜出、无过期覆盖）：passed——8.4 要求的"翻译中切换文章/过期请求覆盖"守卫在位（TranslationSegment 查询以 entryRef 为键 + 组件 key 重挂载 + AbortController）。
- 依赖与 bundle：**零新增 npm 依赖**；BFF 零新增 Python 依赖（httpx 复用）。bundle 增量 = 本次自有代码。
- 原文模式/缓存命中/纯排版切换零请求：由单元测试断言（ai-translation.test.tsx 三个用例）。

## 5. 未验证 / 受限项（诚实清单）

1. **用户实例的 FreshRSS bind-mount 迁移未执行**：安全 Hook 禁止本代理用 shell 复制 FreshRSS 数据（含 config.php）。修复以 opt-in `docker-compose.dev-backup.yml` + 文档命令交付；用户跑 1 条 docker cp + `up -d` 后备份即生效（`.env` 已预置 FRESHRSS_DATA_DIR）。
2. **真实 LibreTranslate 服务未连**（无服务/模型资源）：适配以 httpx MockTransport 验证；连接测试端点已备。
3. **浏览器 Translator API 真机验证未做**（需 Chrome 138+ 图形环境）：jsdom mock 验证检测/失败路径；不支持态如实提示。
4. **BFF Docker 镜像构建未跑通**：ghcr.io uv 拉取被代理阻断（网络限制）；prod 权限修复以 uid10001+gid33 实测 + compose config 渲染验证。
5. **AI 翻译真实 provider 未调用**（0 预算约束）：provider 交互以 fake provider 单测覆盖；UI 状态行在真实栈显示"翻译中→失败（未配置）"的诚实路径已目验。
6. **深色模式逐像素复检**：见上表 ⚠️。
7. Folo 性能为静态推断（FOLO_COMPARISON.md），无跨项目实测对比。
