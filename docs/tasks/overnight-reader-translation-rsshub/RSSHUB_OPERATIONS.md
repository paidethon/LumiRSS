# RSSHUB_OPERATIONS.md — 高级功能清单、自动识别与应用边界、自定义站点凭据、运维

> 版本基线：项目固定 digest `diygod/rsshub@sha256:387fd32e…`（0018 起锁定；配置 schema 在 2026-09-04 于运行容器内核验，git 86516b3）。
> 上游文档：docs.rsshub.app（deploy / guide/parameters / guide/faqs）。能力逐项给出：上游依据 → LumiRSS 现状 → 本次是否落地。

## 1. 高级功能清单

| 能力 | 上游依据 | LumiRSS 现状 | 本次落地 |
|---|---|---|---|
| 路由元数据/发现 | 官方 docs 路由列表；仓库 pinned 快照 | `rsshub_routes.generated.json`（锁定快照）+ `/api/v1/rsshub/routes` + 来源发现（0014） | 否（已存在） |
| Radar 规则（站点→路由推导） | 官方 Radar 机制 | 无 | **未落地**：需要 radar.js 运行时或上游 API，验证成本高；列为候选 |
| 内容过滤（官方 filter 参数） | 路由参数 `filter/filter_title/description/...` | LumiRSS 显示层过滤规则（0017）已覆盖大部分读端诉求；BFF 不做服务端参数过滤 | 否（显示层已足够） |
| 数量限制（limit 参数） | 官方参数 | 订阅后由 FreshRSS 抓取，limit 属路由参数，可在订阅 URL 上手工追加 | 否（文档说明即可） |
| 全文（description/`turbo` 类全文提取） | 官方 parameters | 无 | **未落地**：上游质量参差，优先级低 |
| 缓存与刷新 | CACHE_TYPE/CACHE_EXPIRE/CACHE_CONTENT_EXPIRE | ✅ 控制中心 allow-list 项（0018）+ 本次 env 应用链实测生效（CACHE_EXPIRE=777 隔离验证） | 是（应用链） |
| 访问保护 | ACCESS_KEY | ✅ secret 项（写只读）+ env 应用 | 是（应用链） |
| 代理 | PROXY_URI | ✅ secret 项 | 是（应用链） |
| 浏览器依赖 | PUPPETEER_WS_ENDPOINT/CHROMIUM_EXECUTABLE_PATH | ✅ 配置项（无实例运行） | 配置面就绪 |
| 输出格式/媒体/简繁 | 路由级与输出级参数 | 未集成 | 否（FreshRSS 端消费默认 RSS） |
| 健康监测 | /healthz | ✅ compose healthcheck + operations/status + 本次 detect 探测 | 是 |
| 部署资源限制 | compose mem_limit/cpus | ✅ prod compose（0018） | 已存在 |

注：`limit`/`filter` 等是**路由参数**而非全局参数，不存在"给所有路由统一开启"的开关——文档与 UI 均不这样宣称。

## 2. 自动识别与应用边界（本次实现，commit 9228256）

**区分两类实例：**
- **受管实例**（docker compose 管理的本项目栈）：完整链路 = 保存 desired → 生成 0600 env 文件（服务端，值不回传浏览器）→ 宿主机 `apply_rsshub_config.py`（默认 dry-run）→ `--apply` 重建（`up -d --force-recreate --no-deps`，只 rsshub）→ /healthz 轮询 → Control Center「确认应用完成」写 applied 快照 → UI restartRequired 归零。
- **外部实例**：只做有界探测（见下）；配置导出为 `.env` 片段（secret 只渲染键名）+ 应用说明；**不显示虚假的"一键生效"**。

**自动识别（GET /api/v1/rsshub/detect）**：仅探测三个有界候选——已配置地址、`http://rsshub:1200`（本项目 compose DNS）、`http://127.0.0.1:1200`（宿主回环），2s 超时、只打 /healthz、不读任何认证端点、**绝不扫描局域网**，也绝不尝试从实例"读回"Cookie。

**安全边界（不可妥协项）：**
- BFF 无 Docker socket、无 shell；应用由宿主机脚本执行；
- 脚本 service 名 allow-list（仅 `rsshub`）、argv 列表形式 shell=False、project 名白名单正则、健康 URL 仅允许 127.0.0.1/localhost；
- env 文件权限 0600、位于 BFF 数据目录（git-ignored）、从不进入响应体；
- 自定义凭据 envKey 强制 UPPER_SNAKE_CASE，防注入任意环境键；凭据值不回显。

**关键运维事实**：`docker compose restart` **不会**让新环境变量进入容器——必须重建（`up -d --force-recreate`）。这正是"保存了配置却没生效"的经典根因，脚本与 UI 文案均已写明。

## 3. 自定义站点与凭据

设置 → RSSHub → 自定义站点凭据：
- 字段：站点名称、域名（bare hostname 校验）、路由路径（可选）、envKey（UPPER_SNAKE_CASE、查重）、凭据类型（Cookie/Token/API Key/Bearer/其他）、凭据值（写只读；仅显示 已配置/未配置；可替换与删除）。
- 上限 32 条；值上限 10000 字符；控制字符拒绝。
- 值存 SecretsStore（`rsshub.custom.<id>`），元数据存 lumi KV；env 应用链会把已配置的自定义凭据一并写入 0600 env 文件。
- **诚实边界（UI 明示）**：新增站点 + Cookie ≠ 产生 RSS。RSSHub 输出 RSS 的前提是该站点**已有路由**；envKey 必须是对应路由真实读取的环境变量名（如 `ZHIHU_COOKIES`）。没有路由的网站需要上游新增或自行开发路由——LumiRSS 不会假装"任意站点可抓"。
- 凭据适用范围：值只进入 RSSHub 容器环境变量，仅被对应路由的抓取请求使用；不进订阅 URL、不进日志、不回传浏览器。

## 4. 运维 SOP（脱敏示例）

```bash
# 1) Control Center 保存期望配置后，生成 env 文件（服务端 0600）：
#    设置 → RSSHub → 应用链 → 「生成 env 文件」
#    （宿主机 BFF：services/bff/data/rsshub/rsshub.env；
#      prod BFF 容器：docker compose -f docker-compose.prod.yml cp bff:/data/rsshub/rsshub.env ./rsshub.env）

# 2) 宿主机预检（dry-run，默认）：
python services/bff/scripts/apply_rsshub_config.py \
  --env-file services/bff/data/rsshub/rsshub.env

# 3) 确认计划后应用（只重建 rsshub，不动 FreshRSS/BFF）：
python services/bff/scripts/apply_rsshub_config.py \
  --env-file services/bff/data/rsshub/rsshub.env --apply

# 4) 脚本输出 HEALTHY 后，回到 Control Center 点「确认应用完成」。

# 回滚：用上一个 env 文件重跑步骤 2-3（脚本不自动删除/回滚容器）。
```

隔离验证记录：`/home/zephyr/projects/LumiRSS-itest2`（独立 project 名/端口 18090/合成凭据），`--apply` 后容器内实测 `CACHE_EXPIRE=777`、`WEIBO_COOKIES` 已设置、自定义 `ITEST_CUSTOM_TOKEN` 已设置、/healthz 200。详见 VALIDATION.md。
