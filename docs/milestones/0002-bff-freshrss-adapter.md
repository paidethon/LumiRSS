# Devlog 0002 — BFF + FreshRSSAdapter

> Milestone: 0002 BFF + FreshRSSAdapter
> Phase: Phase 2 — Backend Core
> 日期：2026-08-27
> 结果：Completed（待人工 Review，未 commit）

## Status

Completed。

- Spec：`docs/specs/0002-bff-freshrss-adapter.md`（先写 spec，经两轮修订后用户批准，再实现）
- 本里程碑结束时**未 commit**，停在工作区等待人工 Review（按任务指令）

## Goal

把 0001 中人工执行的 curl 调用变成 LumiRSS 自己的 Python 后端代码：打通
`curl → FastAPI → FreshRSSAdapter → ClientLogin → subscription/list → 归一化 JSON`，
`GET /api/v1/feeds` 返回真实 FreshRSS 订阅。

## What was implemented

- `services/bff/`：最小 FastAPI BFF 骨架（uv 管理，src 布局，手工编写
  `pyproject.toml`，`uv sync` 生成 `uv.lock`，未使用 `uv init` 模板脚手架）。
- `src/lumirss/adapters/freshrss.py` — FreshRSSAdapter：
  - async ClientLogin（`httpx.AsyncClient`，`Timeout(10.0, connect=5.0)`，
    `trust_env=False` 防 WSL 代理劫持 localhost）；
  - subscription/list 调用 + 归一化为最小 LumiRSS Feed 模型（title + feedUrl）；
  - Auth Token 仅存 Adapter 实例内存；401 时清 token → 重登一次 → 重试一次；
  - 4 类错误：ConfigError / AuthenticationError / UpstreamConnectionError /
    UpstreamError（ClientLogin 401 → 认证错误；连接/超时 → 连接错误；
    5xx / 意外结构 → 上游错误）。
- `src/lumirss/config.py` — pydantic-settings，API Password 用 `SecretStr`，
  空字符串密码视为无效配置；懒校验（首次 /api/v1/feeds 请求时才读取）。
- `src/lumirss/main.py` — lifespan 只创建/关闭共享 `httpx.AsyncClient`；
  Adapter 懒创建并缓存到 `app.state`（`/health/live` 与 FreshRSS 配置彻底解耦）；
  `GET /health/live` + `GET /api/v1/feeds` + 4 类异常 → JSON 错误映射。
- 测试 15 个（全 Mock，无网络无真实密码）：health、ClientLogin 解析与缓存、
  401/500/连接错误映射、subscription 映射、401 一次性重登、JSON 形状异常、
  配置缺失/空值、SecretStr repr 遮蔽、route wiring、route 错误映射。
- 文档：README（BFF 命令）、PROJECT_STATE、progress board、本 devlog。

## Key user ↔ AI dialogue

（摘要，凭据一律 `[REDACTED]`）

1. 用户下发 0002 任务（Spec-driven，批准前禁止 Build）。AI 只读探索后停止：
   当前分支是 `chore/project-progress-board` 而非
   `feat/0002-bff-freshrss-adapter`，且 uv 未安装。用户手动切分支（基于合入
   看板的最新 main `c8ce5ba`）并安装 uv 0.12.6。
2. AI 生成 Spec 初稿。用户第一轮修订 8 点（Auth Token 无时间过期语义、
   Adapter 生命周期、async 模式、timeout/trust_env、SecretStr 与空密码无效、
   Test E/F、uv init 模板、架构图歧义）；AI 全部落实并自查出 2 处残留旧表述。
3. 用户第二轮修订 6 点（`Timeout(10.0, connect=5.0)` 正确构造、懒创建生命周期
   解决 health 与配置校验冲突、commit 前用 git check-ignore 而非 ls-files、
   secret 扫描覆盖 untracked、anyio 测试策略、ClientLogin 非 200 不全是密码错）；
   AI 落实后报告修改点，等待批准。
4. 用户批准 Spec → Build。Smoke Test 阶段，AI 按约定暂停，请用户自行在
   `services/bff/.env` 配置真实凭据（AI 全程未读取该文件内容），用户确认
   "已配置" 后完成真实联调。

## Commands actually executed

```bash
# 开工检查
git branch --show-current        # feat/0002-bff-freshrss-adapter
git status --short --branch      # clean
uv --version                     # 0.12.6
python3 --version                # 3.12.3

# BFF 初始化与测试（均在 services/bff 下）
uv sync                          # 首次超时，重试后成功（25 packages）
uv run pytest                    # 15 passed
uv run pytest tests/test_health.py -v
uv run pytest tests/test_freshrss_adapter.py -v

# 真实 Smoke Test（FreshRSS 容器 Up 2 days）
docker compose ps                # freshrss Up
uv run uvicorn lumirss.main:app --port 8000
curl http://127.0.0.1:8000/health/live   # 200 {"status":"ok"}
curl http://127.0.0.1:8000/api/v1/feeds  # 200 真实订阅（2 个 feed）

# 故障验证（临时环境变量假密码，未改 .env）
FRESHRSS_API_PASSWORD=<fake> uv run uvicorn lumirss.main:app --port 8001
curl http://127.0.0.1:8001/api/v1/feeds  # 502 authentication_error
curl http://127.0.0.1:8001/health/live   # 200（进程未崩溃）

# 收尾验证
git check-ignore services/bff/.env          # 命中（被忽略）
git check-ignore services/bff/.env.example  # 无输出（不被忽略）
```

## Problems encountered

1. `uv sync` 首次运行 5 分钟超时：PyPI 直连慢，依赖解析成功但拉取
   hatchling 构建依赖时连接中断。
2. 首个 adapter 测试暴露真实 bug：ClientLogin 请求本身的连接错误未被
   try/except 覆盖（只有 subscription/list 包了），`ConnectError` 直接
   冒出而不是映射为 `UpstreamConnectionError`。
3. route 测试初版在 `TestClient(app)` 启动前注入 fake adapter，被 lifespan
   启动逻辑重置为 None，导致 3 个测试失败（503 而非预期 200/502）。

## How problems were solved

1. 属于网络层。不改系统配置，利用 uv 缓存 + 重试循环，第二次尝试即完成
   安装（24 packages installed）。
2. 属于 Adapter 层。给 ClientLogin 的 POST 请求补上同一组网络异常映射
   （ConnectError / ConnectTimeout / ReadTimeout → UpstreamConnectionError），
   修复后 15/15 通过。
3. 属于测试层。将 fake adapter 注入移到 `with TestClient(app)` 语句块内
   （lifespan 启动之后），问题解决。

## Acceptance evidence

Spec 0002 的 AC1–AC10 全部达成（详见最终报告）；关键证据：

- 15 个自动化测试全部通过（无网络、无真实密码）；
- `curl /api/v1/feeds` 真实返回 2 个订阅：FreshRSS releases、
  阮一峰的网络日志；
- 无效凭据 → 502 `authentication_error`，响应与日志中无密码、无 Token；
- secret 扫描零命中（扫描范围含 untracked 待提交文件，排除 gitignored
  的真实 `.env`）。

## What I learned

- Auth Token 与 API Password 同为 Secret；当前 FreshRSS 实现没有基于
  时间的自动过期，失效来源是密码修改 / system salt 变化。
- 懒创建 Adapter + lifespan 只管共享 AsyncClient，是"health 永远可用"与
  "配置懒校验"两个需求的干净解法。
- `httpx.AsyncClient(trust_env=False)` 在 WSL + Windows 代理环境是必须的，
  否则 localhost 请求可能被系统代理劫持。
- `TestClient` 的 with 语句会触发 lifespan —— 测试中注入依赖必须在启动后。
- pydantic `SecretStr` 让 repr/日志天然遮蔽密码；空字符串必须显式判无效。

## Next milestone

0003 — Entry Read Path（文章列表 + 文章详情 API，Phase 2 继续）。
