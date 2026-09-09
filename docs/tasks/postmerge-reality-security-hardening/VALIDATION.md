# VALIDATION.md — postmerge-reality-security-hardening-20260909

> 分支 `chore/postmerge-reality-security-hardening-20260908`（基线 ad09bb2 = origin/main，PR #36 已合并）
> 核验：2026-09-09
> 环境：WSL2 Ubuntu 24.04（原生 dockerd 29.1.3）；dev 栈 FreshRSS(8080)+RSSHub(1200)+宿主机 BFF(8000)+Vite(5173)
> 真实集成证据目录（仓库外）：`/home/zephyr/projects/LumiRSS-irestore-20260909/`

## 1. 自动化验证（A 类证据，2026-09-09 本轮真实值）

| 检查 | 结果 |
|---|---|
| BFF `uv run pytest -q` | **656 passed**（634 基线 + 22 个本轮新增安全/隔离回归；ruff clean） |
| Web `pnpm test` | **583 passed**（580 基线 + 3 个新增 CSP/冲突回归） |
| Web `pnpm lint`（oxlint） | 0 errors（11 warnings 为既有基线） |
| `pnpm build`（含 tsc -b） | clean |
| `pnpm api:check` / `settings:check` | 生成物零 drift（revision 字段已再生成） |
| E2E desktop-journeys | **12 passed**（desktop-1440/1920） |
| E2E mobile-journeys | **12 passed**（390/430/375） |
| E2E a11y（axe wcag2aa） | **7 passed**（0 violation） |
| E2E rapid-selection | **5 passed** |
| E2E ci-smoke（LUMIRSS_CI_STATIC=1 + 4173） | **10 passed**（5 视口 × 2） |
| E2E webdav / milestone-0018 / mobile-smoke | **4 + 10 + 3 passed** |

Web 负载稳定性：`maxWorkers: 8` 封顶（vitest 4 移除了 poolOptions，旧
threads 配置从未生效——本轮修正）后，冷缓存 + 12 路 CPU 压力 + 并发
BFF pytest 下全量 583 连续全绿（含此前偶发超时的 scroll-mark-unread /
mobile-reader）。

## 2. Phase A — 未验证项逐项关闭

| # | 项目 | Before | Action | Final status | Evidence |
|---|---|---|---|---|---|
| 1 | FreshRSS bind-mount 迁移 | 未执行 | 副本刷新（docker cp，77/77 文件、db.sqlite 校验和一致）+ compose override 应用 | **VERIFIED**：bind mount 生效；`GET /backups/capabilities` → `fullBackupReady=true`（77 文件 + 1 sqlite） | 本轮真实 API 响应 |
| 2 | 真实备份 | 只有历史 itest 证据 | dev 栈真实执行 `POST /api/v1/backups` | **VERIFIED**：succeeded；79 members、78/78 校验和通过、含 users/admin/db.sqlite 与 lumi.sqlite、secrets 排除策略在位、归档无 secret 成员 | `lumirss-20260908T225047Z.backup` |
| 3 | 隔离恢复 | 只有历史 itest 证据 | 独立 BFF(:18080)+独立数据目录：preview(compatible)→RESTORE→重启核对 | **VERIFIED**：lumiRestored=true；重启后设置恢复为源实例值；恢复态无密钥（defaultKeyConfigured=false）；FreshRSS 离线暂存 77/77 校验和匹配 | LumiRSS-irestore-20260909/ |
| 4 | Docker/WSL/代理 | ghcr 拉取失败 | **根因定位**：daemon 级 systemd 代理 override（/etc/systemd/system/docker.service.d/proxy.conf）指向不可达的 Windows 代理 172.25.144.1:7890（TCP 实测 closed）；shell 直连 docker.io/ghcr.io 均正常（401/200） | **FIXED（等价构建）+ 残余外部阻塞**：本地以同版本（0.12.6）uv 二进制构造镜像标签使 COPY --from 本地解析，真实 Dockerfile 完整构建成功（BFF + Web）；daemon 代理 override 移除需 root（sudo 需密码，代理无权执行） | 下方 §5 |
| 5 | 生产 compose 链路 | config 渲染通过 | 隔离 production-like 栈（独立项目名/端口 18080/独立卷）：build→up→health→Caddy 路由→headers→内部隔离→restart→down -v | **VERIFIED**：4 容器 healthy；SPA 200；/api/v1/version 经 Caddy 返回 commit=ad09bb2；仅 web 发布宿主端口；restart 后自动恢复 | /tmp 日志 + 本节 |
| 6 | 真实 LibreTranslate | 仅 MockTransport | 隔离容器（127.0.0.1:15000，LT_LOAD_ONLY=en,zh，v1.9.6）：/languages、单条/批量 en→zh 真实翻译、错误路径（无效目标 400、不可达诚实失败）、BFF 连接测试、经 BFF 的真实分段生成、缓存命中零 provider、浏览器三模式全链路 | **VERIFIED**（含兼容性结论：v1.9.6 接受 `zh` 作为 zh-Hans 别名，现有映射无需变更）；验收后容器已删除 | 本节 + `/tmp/a3-*.png` |
| 7 | Chrome Translator 真机 | 仅 jsdom mock | 真机 Chrome 152（Linux）：`'Translator' in self`=true；availability() 全部 "downloadable"（隐私掩码语义）；create() 对 en→zh / en→zh-Hans / en→es 一律 NotSupportedError（headless/有头/用户激活/组件更新开启均复现）；chrome://components 显示语言包已下发（en-zh 2024.10.8.1）但基础组件 Chrome TranslateKit 停在 0.0.0.0 | **desktop 部分验证 + 平台外部阻塞**：产品侧特征检测与 create() 失败的诚实处理路径在真机验证通过（诚实文案、零 BFF 调用、零 console 错误）；Linux 桌面不分发 TranslateKit 基础组件 → 真实端上翻译需 Windows/macOS Chrome | §6 |
| 8 | 真实 AI provider | 0 预算 | 环境盘点：仅 mock（172.18.0.1:18082 mock-model）与假端点；无 Ollama/LM Studio | **EXTERNAL BLOCKER — requires paid provider authorization**（未做任何付费调用） | §6 |
| 9 | 深色模式逐像素 | 未做 | 判定：无已批准像素基线，不为此临时造 pixel-snapshot 系统 | **NOT APPLICABLE AS PIXEL-DIFF；VERIFIED BY SCREENSHOT + AXE + CONSOLE + THEME TESTS**：深色截图目检 + 深色运行零 console 错误 + axe 0 violation + 15 个既有 theme 单测 | /tmp/accept-dev-1440-dark.png |
| 10 | Web 单测负载抖动 | 偶发超时 | 复现：仅极端并发负载下发生（1/7）；根因 vitest 4 默认 forks pool 无 worker 上限（20 全开），且旧 poolOptions.threads 配置在 vitest 4 已无效 | **FIXED + VERIFIED**：`maxWorkers: 8`；冷缓存 + 12 路压力 + 并发 pytest 全量多轮全绿 | commit d5dbc9c |
| 11 | Folo 性能对比 | 静态推断 | 不属于可本地验证项（跨产品实测需运行 Folo） | **NOT APPLICABLE（调研性质文档）** | — |

## 3. Phase B — Security & Operations Hardening（0021 关闭）

ROADMAP 0021 候选逐项（均含回归测试，commit c2c3b8a / 3725a4b / b9a6aca）：

1. **翻译批量协议**（fix(security)）：解析器改为行首锚定 + 与请求序列严格单调一致（多副本/乱序/多余标记 → 整批 invalid_response）；正文内回显的标记不再分块。恶意 provider 响应测试 ×5。
2. **`_article_locks`**：改用 GenerationLockPool（256 上限，语义同摘要生成）。
3. **批量并发**：semaphore 提升到服务级（跨文章共享 4 配额，判别性测试证明峰值 4 而非 6）。
4. **RssHubUnknownKey**：错误消息回显上限 64 字符。
5. **raw request.json()**：两个凭据端点改 pydantic 模型 → malformed JSON 稳定 422 invalid_request（原 500）。
6. **SecretValuePut**：max_length 对齐 MAX_SECRET_LENGTH(10000) + 输入期控制字符拒绝。
7. **BFF 内部鉴权（B3）**：`LUMIRSS_INTERNAL_TOKEN`（opt-in）+ 中间件；/api/* 必须带 X-Lumi-Token，/health/* 豁免；Caddy 由 entrypoint 渲染 header_up 注入。生产栈实测：经 Caddy 200、直连无/错 token 401、正确 token 200、容器内 health 200。
8. **CSP/HSTS（B4）**：两个 Caddyfile 增加 CSP（script-src 以 sha256 pin 内联主题脚本——vitest 漂移测试守护；style 保留 unsafe-inline 以容纳净化后的文章 style 属性；img/media 允许远端）、HSTS、Permissions-Policy、frame-ancestors 'none'。生产栈真机验证：CSP 零违规。
9. **Rate limit（B5）**：固定窗口 + 稳定 429 rate_limited 信封 + Retry-After；仅覆盖昂贵控制面（restore 10/min、backups 12/min、outbound 30/min、AI/MT 120/min、RSSHub 变更 60/min）；读路径不限。
10. **请求体上限（B6）**：全局 4 MiB 纯 ASGI 中间件（Content-Length 快路径 + 流式守卫）→ 稳定 413 request_too_large；路由级边界（OPML 2 MiB、pydantic 上限）保持权威。
11. **SSRF/DNS rebinding（B2）**：审计确认三层信任分类均有既有防护——不可信 feed URL：scheme 白名单 + 凭据拒绝 + DNS 解析公网校验（含 NAT64/CGNAT/IPv4-mapped）+ 逐跳重定向再校验 + 有界响应体；管理员配置端点（AI/LibreTranslate/WebDAV）：http(s) 白名单 + 无凭据/query/fragment 校验 + WebDAV origin pinning 重定向；内部生成 URL：受信基础设施。无需新代码。
12. **多设备设置冲突（B8）**：settings 文档暴露内容哈希 revision；PATCH 可带 baseRevision，不匹配 → 稳定 409 app_settings_conflict；Web 同步层带 baseRevision 发送、409 时 re-hydrate（dirty 键保留）+ 重试一次；无 baseRevision 的旧客户端保持 last-write-wins。
13. **运维审计（B9/B10）**：生产 compose 已有 json-file 轮转 10MB×3、mem/cpus 限制、healthcheck、restart 策略、仅 Caddy 发布端口（本轮生产栈实测复核）；秘密扫描：本次 diff 无真实凭据，.env 全部 gitignored。

## 4. 本轮发现的 Bugs（root cause → fix → test）

| Symptom | Root cause | Fix | Commit |
|---|---|---|---|
| BFF test_full_backup_requires_freshrss_when_missing 失败 | 测试依赖宿主 .env/真实目录状态（非隔离；此前"碰巧"以失败路径通过） | conftest autouse 隔离 FRESHRSS_DATA_DIR | 641530d |
| Web 全量在负载下超时级联 | vitest 4 默认 forks pool 无上限；旧 poolOptions.threads 配置在 vitest 4 无效（从未生效） | `maxWorkers: 8` | d5dbc9c |
| ci-smoke "数据控制降级态" 5 视口全红 | vite preview 默认继承 server.proxy——dev BFF 在 :8000 运行时"无 API"前提被静默破坏 | preview.proxy 显式清空 | b9a6aca |
| webdav E2E 连接失败 | 硬编码网桥 172.19.0.1 过期（J4/M3 同类根因，上轮修复遗漏此处） | resolveBridgeIp 运行时探测提取至 helpers 复用 | b9a6aca |
| docs/README.md 状态漂移 | PR #36 已合并但状态仍为 "awaiting review" | 文档更新（本轮） | — |

## 5. 残余外部阻塞（唯一一项，含最小人工步骤）

**Docker daemon 代理 override（172.25.144.1:7890，不可达）**

- 命令证据：`docker pull` 任何镜像 → `proxyconnect tcp: dial tcp 172.25.144.1:7890: i/o timeout`；`timeout 5 bash -c 'echo > /dev/tcp/172.25.144.1/7890'` → CLOSED。
- 网络层已验证：WSL shell 直连 internet 正常（registry-1.docker.io 401、ghcr.io 401、update.googleapis.com 等均可达）。
- 为什么 repo 内无法修：override 位于宿主机 systemd（/etc/systemd/system/docker.service.d/proxy.conf），修改 + `systemctl daemon-reload && systemctl restart docker` 需要 root；本代理 sudo 需密码。
- 最小人工步骤：
  ```bash
  sudo rm /etc/systemd/system/docker.service.d/proxy.conf
  sudo systemctl daemon-reload && sudo systemctl restart docker
  docker pull ghcr.io/astral-sh/uv:0.12.6   # 验证
  ```
  （若 Windows 侧代理确有需要，应改用 Docker Desktop 代理设置或动态网关探测，不要硬编码 IP。）
- 影响评估：在用户执行前，镜像拉取被阻塞；构建验证已用等价本地标签完成（见 §2.4），repo 的 Dockerfile 与 compose 无需任何改动。

**Chrome Translator 端上模型（补充 §2.7）**：Linux 桌面 Chrome 不分发
TranslateKit 基础组件（chrome://components 中基础组件 0.0.0.0 而语言包已
下发）。人工验收步骤（Windows Chrome 138+）：打开 LumiRSS → 设置 → 翻译
→ 引擎=此浏览器 → 打开文章切"双语"→ 首次触发语言包下载 → 真实译文。
