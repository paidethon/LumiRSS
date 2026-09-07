# VALIDATION.md — 命令、结果、环境与未验证项

> 分支 `feat/overnight-reader-translation-rsshub-20260907`（基线 e3c4de7 = origin/main 68ded4e 内容）
> 最终核验：2026-09-08（收尾稳定化轮）
> 环境：WSL2 Ubuntu；本地开发栈 FreshRSS(8080)+RSSHub(1200)+宿主机 BFF(8000, --reload)+Vite(5173)
> 截图：`apps/web/test-results/gate6/`（gitignored）；隔离栈证据：`/home/zephyr/projects/LumiRSS-itest*/`

## 1. 自动化验证（A 类证据，数字为 2026-09-08 最终真实值）

| 检查 | 基线（e3c4de7） | 最终（含收尾轮） |
|---|---|---|
| BFF `uv run pytest -q` | 592 passed | **634 passed**（+2 个本轮新增安全回归测试；ruff clean） |
| Web `pnpm test` | 571 passed | **580 passed**（连续 4 轮全绿；偶发负载超时抖动见 §5.8） |
| Web `pnpm lint`（oxlint） | 0 errors | 0 errors |
| `tsc -b`（含于 build） | clean | clean |
| `pnpm build` | clean | clean（chunk>500kB 提示为 shiki 既有体积，informational） |
| `pnpm api:generate` + diff | 一致 | 一致（零 drift） |
| `pnpm settings:check` | 一致 | 一致（零 drift） |
| `docker compose -f docker-compose.prod.yml config` | — | 渲染成功（临时 env 副本；BFF group_add 在位；仅 web 发布 80/443） |

## 2. E2E（真实 dev 栈 5173；ci-smoke 为静态 4173）

| 套件 | 项目 | 结果 |
|---|---|---|
| desktop-journeys J1-J5 | desktop-1440 | **6/6 passed**（串行全量） |
| mobile-journeys M1-M4 | mobile-390 / 430 / 375 | **4/4 passed ×3 视口** |
| a11y（axe wcag2aa） | desktop-1440 首页/Reader/设置 + mobile-390 ×4 | **7 passed**（0 violation） |
| rapid-selection | desktop-1440 | **passed**（最后选择胜出、无过期覆盖；翻译查询以 entryRef 为键 + 组件 key 重挂载 + AbortController） |
| ci-smoke（LUMIRSS_CI_STATIC=1 + LUMIRSS_E2E_BASE_URL=:4173） | desktop-1440 | **2/2 passed** |
| J2 单测复跑（数据依赖回归守护） | desktop-1440 ×3 + desktop-1920 ×1 | **4/4 passed** |
| J4 单测复跑（本轮修复后） | desktop-1440 ×3 | **3/3 passed**（第 1 次经 failed→重试收敛，后 2 次缓存命中） |

### 遗留问题关闭记录（E2E-ISSUES-B-C-20260906 → [E2E-ISSUES-B-C-20260906.md](E2E-ISSUES-B-C-20260906.md)）

- **B（J2 数据依赖）**：修复 `f9e86fb`（J2 自建前置：set 语义 PATCH 置未读，
  幂等）已在分支祖先（经 main PR #34）。本轮真实复跑 ×4 全绿 → **已解决**。
- **C1/C2（对比度 token）**：修复 `6bed703`（selected 表面 tertiary→secondary
  4.85:1；light danger 调深 4.76:1；dark 新增 danger-contrast 6.17:1）已在祖先。
  本轮 axe 实测 desktop+mobile 全绿 → **已解决**。
- **C3（移动 a11y 扫描含抽屉）**：`f9e86fb` 单会话往返 + closeMobileSettings。
  本轮 mobile a11y 全绿 → **已解决**。
- **J4/M3（2026-09-08 新发现，环境+测试前置缺陷）**：root cause = docker 网络
  子网漂移（spec 硬编码 172.19.0.1 → 实际 172.18.0.1，BFF 够不到 mock AI →
  摘要 failed 态残留）+ BFF 要求非空 key（合理安全设计，开发机恰好没有）。
  修复：BRIDGE 运行时探测 compose 网关 + J4/M3 幂等自建 mock key + 三状态
  收敛。非产品代码缺陷；`require_ai_configured`/provider 层与基线零差异。

## 3. 真实集成验证（B 类证据；2026-09-07 隔离部署，非 mock）

### 备份/恢复（LumiRSS-itest，独立 compose 项目/端口/目录）
1. 全新 FreshRSS 容器（FRESHRSS_INSTALL 自动安装）+ 宿主机 BFF（独立 DB/数据目录）+ bind mount 数据目录。
2. BFF 播种：订阅（合成 feed 4 条目）→ set 语义状态（2 读、2 收藏）→ AI Profile + Key（入 SecretsStore）。
3. `GET /api/v1/backups/capabilities`：770 目录修复前 `fileCount=6`（假绿）→ 修复后 27 文件/1 sqlite，`fullBackupReady=true`。
4. `POST /api/v1/backups` → succeeded；归档 29 成员、manifest 校验和 29/29 全对、含 `users/admin/db.sqlite`、无 secrets 成员。
5. 第二隔离实例 `POST /restore/preview`（compatible）→ `POST /restore`（confirmation=RESTORE）→ lumiRestored=true、freshrss 离线暂存 27/27 校验和匹配、暂存库条目状态逐条核对。
6. 重启恢复侧 BFF：profile 持久、`keyConfigured=false`（密钥按策略排除）、job 账本诚实。
7. prod 权限修复单独实测：`docker run -u 10001 --group-add 33`（挂 itest 数据卷 RO）→ 可遍历 `users/admin/` 并读取 db.sqlite。
8. 证据归档仍在：`LumiRSS-itest/lumi-source/backups/lumirss-20260907T154213Z.backup`。
9. 本轮（09-08）对 dev 栈复测 `GET /backups/capabilities`：`fullBackupReady=false` + `path_missing` 诚实原因（bind 迁移待用户执行，见 §5.1）。

### RSSHub 应用链（LumiRSS-itest2，独立 project/端口 18090）
- BFF 同款路径物化 env（0600；CACHE_EXPIRE=777、WEIBO_COOKIES=合成值、自定义 ITEST_CUSTOM_TOKEN）。
- `apply_rsshub_config.py` dry-run（无变更）→ `--apply` → 容器重建 → 容器内实测三个变量生效 → /healthz 200。
- 本轮（09-08）live 复测 `GET /api/v1/rsshub/detect`：仅三个固定候选
  （configured / compose-dns / host-loopback）、2s 超时、只打 /healthz，
  无局域网扫描；`_probe_rsshub` 与 allow-list 与文档一致。

## 4. 浏览器验收（C 类证据；Playwright chromium 对 dev 栈）

| 检查 | 结果 | 证据 |
|---|---|---|
| 设置 7 分类无"XX开关"重复文字 | ✅ 全空 | `switch-duplicate-text.json` |
| 设置 7 分类截图（1440） | ✅ 布局/明暗/禁用态正常 | `02/03-settings-*.png` |
| Reader 工具栏三态控件在位、旧正文开关已移除 | ✅ 1/1/1 + group=0 | `reader-toolbar.json` + `04-reader-after-select.png` |
| 双语模式：原文保留 + 引擎/状态行如实（"1 段失败·只重试失败段"） | ✅ | `05-reader-bilingual.png` + `reader-bilingual.json` |
| 仅译文模式 | ✅ | `05b-reader-translated.png` |
| 移动端 390：桌面分段隐藏、紧凑语言菜单、无横向溢出 | ✅ | `mobile-toolbar.json` + `09/10-mobile-*.png` |
| 深色 Reader（应用自管主题） | ✅ 目视复检 | `06/11-dark-*.png` |
| 1920 视口：home/Reader/7 分类/双语 + 全程 console | ✅ **console error = 0** | `12-15-1920-*.png` + `console-errors-1920.json` |
| RadioOption 渲染目标修复后（外观色板/阅读背景/字体列表） | ✅ 单测 38 + 截图复检 | `primitives/settings.test.tsx` + `03-settings-外观.png` |

## 5. 未验证 / 受限项（D 类证据，诚实清单）

1. **用户实例的 FreshRSS bind-mount 迁移未执行**：安全 Hook 禁止本代理用 shell 复制 FreshRSS 数据（含 config.php）。修复以 opt-in `docker-compose.dev-backup.yml` + 文档命令交付；用户跑 1 条 docker cp + `up -d` 后备份即生效（`.env` 已预置 FRESHRSS_DATA_DIR）。
2. **真实 LibreTranslate 服务未连**（无服务/模型资源）：适配以 httpx MockTransport 验证；连接测试端点已备。
3. **浏览器 Translator API 真机验证未做**（需 Chrome 138+ 图形环境）：jsdom mock 验证检测/失败路径；本轮修复了目标语言透传（F-9），真机复验时顺带确认。
4. **BFF Docker 镜像构建未跑通**：ghcr.io uv 拉取被代理阻断（`proxyconnect tcp: dial tcp 172.25.144.1:7890: i/o timeout`，2026-09-08 复现）；compose config 渲染验证通过，Dockerfile 未为绕过网络而改动。
5. **AI 翻译真实 provider 未调用**（0 预算约束）：provider 交互以 fake provider 单测覆盖；真实栈 UI 诚实失败路径已目验。
6. **深色模式逐像素复检**：以截图目视 + 15 个既有 theme 单测覆盖；未做逐像素 diff。
7. Folo 性能为静态推断（FOLO_COMPARISON.md），无跨项目实测对比。
8. **Web 单测负载抖动**：`scroll-mark-unread` / `mobile-reader` 在全量并发负载下偶发超时（复跑即绿；本轮 4 连绿）。属已知基线行为，非本分支引入；如频发可单独立项降低单文件负载敏感度。

## 6. 安全审计记录（2026-09-08，只读外部审计）

范围：分支相对 merge-base 的全部 57 个变更文件。**无 P0/P1**。

已修复（本轮，含回归测试）：
- env 文件物化：目录 0700 + `os.open(..., 0o600)` 建文件，消除 secrets 短暂经默认权限落盘的窗口期（main.py）。
- 自定义凭据 envKey 拒绝与固定 schema 键同名（防 env 文件 last-wins 静默遮蔽 ACCESS_KEY 等）（rsshub_control.py + 测试）。
- 凭据值/机密值控制字符在写入时拒绝（原先等到渲染才 fail-closed，会卡死物化）（rsshub_control.py + 测试）。
- 凭据表单成功后清空（值不滞留 DOM 状态）（RssHubAutoConfigCard.tsx）。

0021 candidates（记录，不在本分支实施）：
- 翻译批量协议标记可用行首锚定+单调位置校验或每批随机定界符（fail-closed 已保证无注入）。
- `_article_locks` 改用有界锁池（复用 GenerationLockPool 语义）；批量并发信号量提升到服务级。
- `RssHubUnknownKey` 消息里回显超长 key 的长度上限；两个新端点 raw `request.json()` 改 pydantic 模型（malformed JSON → 稳定 400）。
- `SecretValuePut` 增加 max_length。
- 固定 schema secret 的 set_secret 渲染期校验已前移（本轮已做）——其余渲染层防御保持。

清洁区（审计确认）：翻译缓存身份不含 API Key（有回归测试）、lookup 永不触 provider、browser 引擎 generate 被服务端拒绝；RSSHub apply 脚本 dry-run 默认/argv 列表/服务 allow-list/健康 URL 限回环；备份 restore 的 zip-slip 防护与 checksum 校验在 merge-base 即完备；Web 侧译文注入全部走 createElement+textContent（无 innerHTML）；无 secret 入 localStorage；0005 迁移静态 DDL。
