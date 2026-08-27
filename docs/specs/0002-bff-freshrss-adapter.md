# Spec 0002 — BFF + FreshRSSAdapter

> 日期：2026-08-27
> 对应 PRD 阶段：Phase 2 — BFF（Backend Core）
> 状态：**Draft — 等待用户批准，未批准前不开始 Build**

## Goal

把 0001 中人工执行的 curl 调用变成 LumiRSS 自己的 Python 后端代码。打通第一条
项目自有数据链路：

```text
HTTP Client
    ↓
GET /api/v1/feeds
    ↓
FastAPI
    ↓
FreshRSSAdapter
    ↓
ClientLogin
    ↓
Auth Token
    ↓
subscription/list
    ↓
FreshRSS Response
    ↓
Normalize
    ↓
LumiRSS JSON Response
```

最终真实验证：`curl http://127.0.0.1:8000/api/v1/feeds` 返回当前 FreshRSS
中的真实订阅（至少包含 0001 已订阅的 "FreshRSS releases" 与 "阮一峰的网络日志"）。

0001 回答的是 "FreshRSS 能不能工作？"；
0002 回答的是 "LumiRSS 自己能不能通过代码使用 FreshRSS？"

## Context — 这个阶段为什么存在（写给初学者）

### FastAPI 是什么？

FastAPI 是一个 Python Web 框架。它的职责是：接收 HTTP 请求 → 分发给对应的
处理函数（Route）→ 把 Python 数据自动转成 JSON 返回。

在 LumiRSS 中，FastAPI 扮演 BFF 的骨架。它本身不懂 RSS，只负责"接电话"
（收请求）和"传话"（把结果按 LumiRSS 的格式返回）。

### BFF 是什么？

BFF = Backend For Frontend（为前端服务的后端）。它是 LumiRSS 自己写的后端，
也是未来 React 前端唯一允许对话的服务：

```text
React（未来）
   ↓ 只调用 LumiRSS BFF
LumiRSS BFF
   ↓ 通过 Adapter
FreshRSSAdapter
   ↓
FreshRSS
```

为什么 React 以后不应该直接连 FreshRSS？

1. **凭据安全**：调用 FreshRSS 需要 API Password。如果浏览器直连，密码就必须
   存在浏览器里，任何打开开发者工具的人都能看到。经过 BFF，密码永远留在服务器。
2. **解耦**：未来如果 FreshRSS 的 API 格式变化，只需要改 Adapter，前端一行
   都不用动。
3. **统一入口**：以后 AI 摘要、缓存、设置都挂在 BFF 上，前端只需要认识一套
   LumiRSS API。

### Adapter 是什么？

Adapter（适配器）是两个系统之间的"翻译官"。FreshRSSAdapter 只做一件事：
把 FreshRSS 的 API 细节（认证方式、URL 拼接、原始 JSON 字段）翻译成 LumiRSS
自己的最小数据模型。

为什么认证、HTTP 调用、字段转换不该直接写在 FastAPI Route 里？

- Route 的职责是"收请求、调 adapter、回结果"，保持 3 行可读；
- FreshRSS 专属知识（ClientLogin 参数名、`GoogleLogin auth=` 头、`url` 字段
  映射成 `feedUrl`）集中在一个文件里，将来 FreshRSS API 变了只改一处；
- Adapter 可以单独用 Mock 测试，不需要启动 Web 服务器。

### API Password 和 Auth Token 的区别？

```text
API Password（长期凭据，用户手工配置）
    ↓  换取
ClientLogin（一次登录请求）
    ↓  返回
Auth Token（访问凭据，同为 Secret）
```

- **API Password** 是你和 FreshRSS 之间的长期秘密，类似于"密码"，泄露了就
  必须改。
- **Auth Token 同样属于 Secret**：拿到它就等于拿到 FreshRSS 的 API 访问
  权，保护级别与密码相同。
- 注意：**当前 FreshRSS 实现没有基于时间的自动过期** —— token 不会
  "到期"。但 API Password 被修改、FreshRSS 的 system salt 变化等，仍可能
  使旧 token 失效，此时 FreshRSS 返回 401。
- 之后每个 API 请求都带 Token，而不是每次都发密码：这样密码的暴露面
  最小，且万一 token 失效（例如密码已更换），只需重新 ClientLogin 一次。

### Environment Variable 是什么？

环境变量是进程启动时从外部读入的配置值，不写死在源代码里。

为什么真实 FreshRSS API Password 不能写死在 Python 源代码中？

1. 源代码会进 Git，密码就会进 Git 历史，删都删不干净；
2. 开发机和将来生产机的密码可以不同，改密码不需要改代码；
3. `.env` 文件被 `.gitignore` 忽略，天然隔离。

因此本项目约定：密码只存在本机 `.env` 文件，`pydantic-settings` 在启动时读取。

### Mock Test 和真实 Smoke Test 的区别？

- **Mock Test（模拟测试）**：用一个"假的 FreshRSS"（httpx MockTransport，
  在内存里直接返回预设响应）来测我们的代码逻辑。不需要网络、不需要真实
  密码、每次运行结果一致 —— 测的是**程序逻辑**。
- **真实 Smoke Test（冒烟测试）**：启动真的 BFF，连接真的 FreshRSS 容器，
  curl 真的接口 —— 测的是**系统真的能连起来**。

两者缺一不可：Mock 快而稳定但证明不了连通性；Smoke 真实但不能放进自动测试
（依赖本机环境）。所以 0002 的策略是：自动测试全用 Mock，真实验证单独做一次。

## Current verified behavior（0001 已验证的事实）

- FreshRSS 1.29.1 容器运行于 `127.0.0.1:8080`（named volume 持久化）。
- 开发用户已启用 "Allow API access" 并配置专用 API Password。
- ClientLogin 已验证：
  `POST /api/greader.php/accounts/ClientLogin`，表单参数 `Email=<用户名>`、
  `Passwd=<API密码>`，成功返回 HTTP 200，响应体含 `Auth=<token>` 行。
- subscription/list 已验证：
  `GET /api/greader.php/reader/api/0/subscription/list?output=json`，请求头
  `Authorization: GoogleLogin auth=<token>`，返回 JSON 中 `subscriptions`
  数组包含 2 个真实订阅，每项含 `title`、`url`（即 feed 地址）等字段。

## Scope

只做三件事：

1. 最小 FastAPI BFF 骨架（`services/bff`，uv 管理）；
2. FreshRSSAdapter：ClientLogin + subscription/list + 字段归一化；
3. 两个路由：`GET /health/live`、`GET /api/v1/feeds`。

外加配套：`.env.example`、自动化 Mock 测试、一次真实 Smoke Test、
文档更新（README / PROJECT_STATE / progress board / devlog）。

## Non-goals（明确不做）

React、Vite、Tailwind、Article/Entry API、Entry 详情、已读/未读、收藏、
Feed 增删、Category API、分页、Cursor、SQLite、SQLAlchemy、Alembic、AI、
RSSHub、Trafilatura、PWA、Caddy、阿里云 ECS、运行时用户认证、Redis、
Celery、Miniflux、Folo、多 RSS Backend、插件系统、Factory/Registry、
完整 OpenAPI Contract、BFF Dockerfile、生产容器。

特别禁止：为"以后可能支持第二个 RSS Backend"提前创建通用抽象框架。
当前只有一个 Adapter：FreshRSSAdapter。

## Architecture（0002 实现范围）

冻结架构（不可改动）：

```text
Native RSS ─────────────┐
                        ↓
Non-RSS → RSSHub → FreshRSS
                        ↓
                 FreshRSSAdapter
                        ↓
                   FastAPI BFF
                  ↙           ↘
            FreshRSS          SQLite
                         AI / Cache / Settings
                  ↘           ↙
                   React Web
```

数据访问路径语义澄清（只澄清现有语义，不改变冻结架构）：

- **唯一 RSS 数据访问路径**：`FastAPI BFF → FreshRSSAdapter → FreshRSS`。
  BFF 不绕过 Adapter 直接连 FreshRSS，也没有第二条平行的 RSS 数据路径。
- SQLite（未来）只与 BFF 相连，不与 FreshRSSAdapter 或 FreshRSS 相连。
- 冻结架构图中 BFF 下方的两个分支指的是“BFF 的两类职责”（经 Adapter
  读写 FreshRSS / 读写 LumiRSS 自己的 SQLite），不是两条平行的 RSS
  路径。

0002 只实现其中：

```text
curl（模拟未来的前端）
   ↓
FastAPI BFF
   ↓
FreshRSSAdapter
   ↓
FreshRSS（唯一 RSS 真源）
```

SQLite、React、RSSHub、AI 全部不出现。

## Data flow

### GET /api/v1/feeds 完整过程

```text
curl GET /api/v1/feeds
   ↓
FastAPI Route（main.py，3 行：收请求 → adapter.list_feeds() → 返回）
   ↓
FreshRSSAdapter.list_feeds()
   ↓
内存里有 Token 吗？
   ├─ 没有 → ClientLogin（POST /api/greader.php/accounts/ClientLogin）
   │          → 解析出 Auth Token → 存进 Adapter 实例内存
   └─ 有   → 直接用
   ↓
GET /api/greader.php/reader/api/0/subscription/list?output=json
   （带 Authorization: GoogleLogin auth=<token>）
   ↓
FreshRSS 返回原始 JSON（subscriptions 数组）
   ↓
Adapter 归一化：每项取 title + url → LumiRSS Feed 模型
   ↓
FastAPI 序列化为 JSON
   ↓
返回给 curl / 浏览器
```

### Token 失效时的行为

如果 subscription/list 返回 401（token 失效，例如 API Password 已被修改或
system salt 已变化）：

```text
清除内存 Token → 重新 ClientLogin 一次 → 重试 subscription/list 一次
```

这只是一层简单的"失效即重登"，不构成 Retry Framework。实现成本约 5 行，
收益是避免 token 失效后（例如密码已更换）BFF 永久报错，因此纳入 0002。

## File plan

```text
services/bff/
├── pyproject.toml          # 手工编写的项目定义 + 依赖（不依赖 uv init 模板）
├── uv.lock                 # uv 自动生成（锁定版本，必须进入 Git）
├── .env.example            # 只有变量名和安全示例值（正常 tracked）
├── src/lumirss/
│   ├── __init__.py         # 空（标记 Python 包）
│   ├── main.py             # FastAPI app + lifespan（创建/关闭共享 AsyncClient）+ 两个 route + 错误映射（Adapter 懒创建并缓存）
│   ├── config.py           # Settings（pydantic-settings，API Password 用 SecretStr）
│   └── adapters/
│       ├── __init__.py     # 空
│       └── freshrss.py     # FreshRSSAdapter：ClientLogin + list_feeds + 归一化（async）
└── tests/
    ├── test_health.py           # Test A + 健康隔离
    ├── test_freshrss_adapter.py # Test B / C / D + 认证失败
    └── test_feeds_route.py      # Test E / F（注入 fake Adapter，不碰真实 FreshRSS）
```

共 10 个新文件（其中 2 个是空的 `__init__.py`，1 个是自动生成的 lock）。

初始化方式约定：**不使用 `uv init` 的隐含默认模板**——手工编写
`pyproject.toml`，用 `uv sync` 解析生成 `uv.lock`；`uv init` 可能生成的
sample app / README 等脚手架一律不保留，最终结构以本 File Plan 为准。
`uv.lock` 进入 Git（可复现安装），`.env.example` 进入 Git，真实 `.env` 不进 Git。

不创建 domain/、repositories/、schemas/、services/、core/ 等任何提前抽象。

## Dependencies

运行时（4 个）：

| 依赖 | 为什么 0002 必须有 |
| --- | --- |
| `fastapi` | BFF 的 Web 框架，Route / JSON 序列化 / 错误处理全靠它 |
| `uvicorn` | 把 FastAPI 应用真正跑起来的 ASGI 服务器；没有它 FastAPI 只是一个对象 |
| `httpx` | Python HTTP 客户端，Adapter 用它的 `AsyncClient` 调 FreshRSS；其 MockTransport 同时支持同步/异步，正是 Mock 测试的关键 |
| `pydantic-settings` | 从环境变量 / .env 读取配置（FastAPI 已依赖 pydantic 本体，此处是设置扩展） |

开发时（1 个）：

| 依赖 | 为什么必须 |
| --- | --- |
| `pytest` | 运行自动化测试 |

不使用 `fastapi[all]`；不安装 SQLAlchemy、Alembic、Redis、Celery、LiteLLM、
数据库驱动、部署 SDK。

## Configuration

### 变量命名（最终决定）

```text
FRESHRSS_BASE_URL      # 例：http://127.0.0.1:8080
FRESHRSS_USERNAME      # 例：admin（FreshRSS 开发用户名）
FRESHRSS_API_PASSWORD  # FreshRSS 中配置的专用 API Password
```

### `services/bff/.env.example`（只含变量名与安全示例）

```text
FRESHRSS_BASE_URL=http://127.0.0.1:8080
FRESHRSS_USERNAME=admin
FRESHRSS_API_PASSWORD=
```

### 安全规则

- `FRESHRSS_API_PASSWORD` 在 Settings 中使用 pydantic `SecretStr`（或等价
  方式）保存，避免 repr / 日志 / 异常信息意外打印明文；
- **空字符串密码视为无效配置**：`FRESHRSS_API_PASSWORD=`（空值）与未设置
  同样触发 ConfigError，绝不静默拿空密码去认证；
- 真实 `.env` 位于 `services/bff/.env`，被根 `.gitignore` 的 `.env` 规则
  忽略。注意：`.gitignore` 只是防误提交，**不是安全边界** —— 真正的规则
  是密码从一开始就不进入任何会被提交、打印或记录的内容；
- **Agent 不得读取、cat 或打印 `services/bff/.env` 的内容**（包括联调
  阶段）。需要真实凭据时由用户自行填写，Agent 暂停等待"已配置"确认，
  密码永不出现在对话中；
- 密码不出现在 README、Spec、测试、日志、错误消息中；
- 配置读取失败（缺变量或空值）时明确报错，绝不使用隐含默认密码。

### 配置校验时机

`Settings` 在**第一次 `GET /api/v1/feeds` 请求时**才读取并校验，不在进程
启动时 —— 因为 `/health/live` 必须始终可用（即使 FreshRSS 没配好）。
缺配置只影响 `/api/v1/feeds`。配置有效后创建的 Adapter 缓存在
`app.state`，后续请求不再重复读配置（详见“Adapter 生命周期”节）。

## Error behavior

Adapter 定义 4 个最小异常，Route 层统一映射为 JSON 错误：

| 异常 | 触发例子 | HTTP 状态 | 错误 type 字段 |
| --- | --- | --- | --- |
| `ConfigError` | `FRESHRSS_API_PASSWORD` 未配置或为空 | 503 | `configuration_error` |
| `AuthenticationError` | ClientLogin 返回 401（凭据被拒绝） | 502 | `authentication_error` |
| `UpstreamConnectionError` | FreshRSS 容器没启动（连接失败 / 超时） | 502 | `connection_error` |
| `UpstreamError` | FreshRSS 5xx、ClientLogin 非 200 非 401、或无法解析的响应结构 | 502 | `upstream_error` |

Adapter 内部的判定规则（不把所有 ClientLogin 非 200 都当密码错误）：

- `httpx.ConnectError` / `httpx.ConnectTimeout` / `httpx.ReadTimeout` 等
  网络/超时异常 → `UpstreamConnectionError`；
- ClientLogin 返回 **401** → `AuthenticationError`（凭据被拒绝）；
- ClientLogin 返回其他非 200（如 5xx）→ `UpstreamError`；
- subscription/list 返回 5xx 或 JSON 结构无法解析 → `UpstreamError`；
- subscription/list 返回 401 → 走“清 token → 重登一次 → 重试一次”，
  重登的 ClientLogin 仍 401 才抛 `AuthenticationError`。

错误响应体（最小、非 RFC9457）：

```json
{
  "error": {
    "type": "authentication_error",
    "message": "FreshRSS rejected the credentials. Check FRESHRSS_API_PASSWORD."
  }
}
```

安全约束：message 不含密码、不含完整 Token、不含 FreshRSS 原始敏感内容；
开发者只看 type 就知道问题出在哪一层。不做 Circuit Breaker、Tracing、
Metrics、Backoff、Error Registry。

## Adapter 生命周期与 Auth Token 策略

### 生命周期（重要：Build 前定死）

Token 缓存在 Adapter 实例内，因此 Adapter **不能每个 HTTP request 新建一次**
（否则每次请求都要重新 ClientLogin，token 复用就失去意义）。0002 采用
**懒创建 + 缓存**的生命周期：

- **lifespan 启动时**：只创建一个共享的 `httpx.AsyncClient`（process
  scoped，挂到 `app.state`），**不读取、不校验 FreshRSS Settings** ——
  这样 `/health/live` 在 FreshRSS 完全未配置时也必须可用；
- **第一次 `GET /api/v1/feeds` 请求时**：才读取并验证 FreshRSS Settings
  （缺变量 / 空密码 → ConfigError）；配置有效后创建 FreshRSSAdapter
  （注入共享 AsyncClient），缓存到 `app.state`；
- **后续请求**：复用 `app.state` 里的同一个 Adapter 及其内存 Token；
- **lifespan shutdown 时**：调用共享 AsyncClient 的 `aclose()`，避免连接
  资源泄漏；
- `--reload` 模式下 uvicorn 重启进程时，旧实例随之销毁并重新走一遍
  lifespan（Adapter 重新懒创建），无需额外处理。

### Token 策略

```text
第一次请求 → 没有 token → ClientLogin → token 存 Adapter 实例内存 → 后续复用
401 时    → 清除内存 token → 重新 ClientLogin 一次 → 重试一次
```

- Token 只存在进程内存（Adapter 实例属性）；
- 不写文件、不进数据库、不完整记录日志、不返回给浏览器、不进测试快照；
- 401 重登是一次性的（清 token → ClientLogin → 重试一次），再失败即抛
  AuthenticationError，不循环；
- 不用 Redis、分布式锁、Token persistence framework。

### HTTP I/O 模式（Build 前定死，不允许 Build 阶段临时决定）

采用 **async 全链路**：

- FastAPI route 声明为 `async def`；
- FreshRSSAdapter 的方法为 `async def`；
- HTTP 客户端使用 `httpx.AsyncClient`。

理由：async 是 FastAPI 的原生模型；0003+ 的文章列表读取量更大，async
链路可以在同一进程内并发多个上游请求，现在采用就不必中途翻新；httpx 的
MockTransport 对 async 用法与同步一致，测试不增加成本。同步实现对 0002
的单接口虽然也够用，但会在 uvicorn 中退化为线程池执行，且未来翻新成本
高于现在直接采用 —— 因此选 async。

### HTTP client 参数

- **显式 timeout**：`httpx.Timeout(10.0, connect=5.0)`（默认 10 秒、
  连接 5 秒），不用默认值兜底，避免 FreshRSS 卡死时请求无限挂起；
- **`trust_env=False`**：不读取系统 `HTTP_PROXY` / `HTTPS_PROXY` 等环境
  变量。原因：本机是 WSL 环境，Windows 侧代理可能意外代理发往 localhost /
  Docker 内部 FreshRSS 的请求（devlog 0001 已有代理踩坑记录）；
- **不建立 retry framework**：唯一的重试是上面 401 的一次性重登。

## Testing strategy

### 自动化测试（全 Mock，不需要网络 / 真实密码 / 真实 FreshRSS）

- **Test A — Health**：`GET /health/live` → 200 → `{"status":"ok"}`。
- **Test B — ClientLogin parsing**：MockTransport 返回
  `HTTP 200` + `Auth=fake-test-token-0002`（明显是测试数据），验证 Adapter
  正确解析并保存 token。
- **Test C — Subscription mapping**：MockTransport 对 subscription/list
  返回固定 fixture JSON（含 2 个订阅），验证 Adapter 输出
  `[{title, feedUrl}, ...]`。
- **Test D — Secret/config behavior**：缺少 `FRESHRSS_API_PASSWORD` 等必要
  配置（含空字符串）时，Settings 校验明确失败（pydantic ValidationError
  包成 ConfigError），绝不落到隐含默认值。
- **Test E — Route wiring**：向 app 注入 fake/mock Adapter（返回预设
  `[{"title": ..., "feedUrl": ...}]`，不访问真实 FreshRSS），
  `GET /api/v1/feeds` → 200，最终 JSON shape 正确（数组、每项恰含
  `title` 与 `feedUrl`）。
- **Test F — Route-level error mapping**：fake Adapter 抛
  `AuthenticationError`，验证 route 返回 502 +
  `{"error": {"type": "authentication_error", ...}}`（复用 Test E 的
  注入方式，成本极低，一并纳入）。
- **补充 — 认证失败**：Mock ClientLogin 返回 401 → Adapter 抛
  `AuthenticationError`，且异常文本不含密码。
- **补充 — 健康隔离**：FreshRSS 不可达时 `/health/live` 依然 200。

测试隔离：构造 Settings 时显式禁用 env_file / 清空相关环境变量，
避免读到本机真实 `.env` 导致测试依赖真实秘密。

async 测试策略（不新增任何测试框架）：

- Adapter 的 async 测试使用 `@pytest.mark.anyio`（anyio 随 httpx /
  starlette 已作为传递依赖存在，其自带 pytest 插件随之可用）；
- Route / lifespan 测试优先使用 `with TestClient(app) as client:`
  （with 语句触发 lifespan 启动/关闭，TestClient 属于 starlette，
  已随 FastAPI 安装）；
- 不新增 `pytest-asyncio`，不新增 `asgi-lifespan`。

### 真实 Smoke Test（自动测试全过后执行一次）

1. `docker compose ps` 确认 freshrss running；
2. 用户在 `services/bff/.env` 配置真实凭据（Agent 暂停等待"已配置"）；
3. `cd services/bff && uv run uvicorn lumirss.main:app --reload` 启动 BFF；
4. `curl http://127.0.0.1:8000/health/live` → `{"status":"ok"}`；
5. `curl http://127.0.0.1:8000/api/v1/feeds` → 返回真实订阅
   （含 "FreshRSS releases" 与 "阮一峰的网络日志"）。

### 故障验证（Smoke 之后做一次，不破坏 FreshRSS 数据）

用无效凭据（如临时环境变量覆盖成假密码，不改 .env 不动 FreshRSS）：
`/api/v1/feeds` 返回可理解的认证错误，且响应中不含真实密码、不含 Auth
Token，进程不崩溃。

## Acceptance Criteria

- **AC1 — Branch isolation**：所有 0002 修改都位于
  `feat/0002-bff-freshrss-adapter`，未直接开发 main。
- **AC2 — BFF starts**：存在明确且真实验证过的启动命令，FastAPI 成功启动。
- **AC3 — Health**：`GET /health/live` 返回 200 `{"status":"ok"}`。
- **AC4 — Configuration**：FreshRSS URL / username / API Password 来自环境
  配置；真实 Secret 不进 Git。
- **AC5 — ClientLogin**：Adapter 能真实 ClientLogin 取得 Auth Token；Token
  memory only 且不泄漏。
- **AC6 — Subscription read**：Adapter 能真实调用 subscription/list 并转换成
  LumiRSS Feed 数据。
- **AC7 — BFF feed API**：`GET /api/v1/feeds` 真实返回至少一个当前
  FreshRSS Feed。
- **AC8 — Automated tests**：health / ClientLogin parsing / subscription
  mapping / configuration-error 四类测试实际运行并通过；不使用真实互联网
  或真实密码。
- **AC9 — Secret safety**：Git tracked files / diff 中不存在真实 password、
  完整 Auth Token、Authorization Header、`.env`。
- **AC10 — Scope**：不存在 React、Entries API、Read/star、SQLite、RSSHub、
  AI、Caddy、PWA、Production 等越界实现。

## Tasks（Build 顺序，批准后执行）

1. 初始化 BFF 项目：手工编写 `pyproject.toml`（不用 `uv init` 隐含模板，
   不保留 sample app / 生成 README 等脚手架，结构以 File Plan 为准），
   `uv sync` 生成 `uv.lock`（进 Git）
2. `GET /health/live` + main.py 骨架
3. 自动 health test（Test A）
4. `config.py`：Settings + `.env.example`
5. Adapter ClientLogin
6. ClientLogin mock test（Test B）
7. Adapter subscription/list + 归一化
8. mapping test（Test C）+ 配置/错误测试（Test D 及补充）
9. `GET /api/v1/feeds` route + 错误映射（Test E / F）
10. 真实 FreshRSS smoke test（需用户先配置 .env）
11. 故障验证（无效凭据）
12. README 更新（只写实际验证过的命令）
13. PROJECT_STATE / progress board / devlog 0002 更新
14. 最终 `git diff` 检查 + secret 扫描

每完成一小步立即运行对应测试，不攒到最后。

## Verification

- `cd services/bff && uv run pytest` 全绿（Mock 测试）；
- `docker compose ps` freshrss Up；
- `curl http://127.0.0.1:8000/health/live` → `{"status":"ok"}`；
- `curl http://127.0.0.1:8000/api/v1/feeds` → 真实订阅 JSON；
- 故障验证：无效凭据 → 502 authentication_error，无秘密泄漏；
- commit 前（工作区阶段）的 Git 验证（此时尚未 commit，新文件还不在
  `git ls-files` 里）：
  - `git check-ignore services/bff/.env` 有输出（真实 .env 被 gitignore）；
  - `git check-ignore services/bff/.env.example` 无输出且退出码非 0
    （example 不被 gitignore）；
  - `git status --short` 中 `services/bff/uv.lock` 与
    `services/bff/.env.example` 属于待提交的新文件（untracked 或已 add）；
  - `git ls-files` 的 tracked 验证留到 commit 之后（属用户 review/
    commit 阶段，不在 0002 Build 范围内）；
- `git status` / `git diff --stat` / `git diff --check`：无越界文件；
- secret 扫描范围：**所有准备提交的文件 = tracked 修改 + untracked 但
  未被 gitignore 的新文件**（例如 `git ls-files --cached --others
  --exclude-standard`），**必须排除 gitignored 的真实 `.env`**，Agent
  不得读取 `.env` 内容；对上述范围执行
  `grep -riE '(Passwd=|GoogleLogin auth=|Auth=)'`：仅测试 fixture 中
  明显标注的 fake token 允许出现，真实秘密零命中。

## Risks / Unknowns

- **FreshRSS token 失效场景**：当前实现没有基于时间的自动过期，但 API
  Password 修改、system salt 变化等会使旧 token 失效（表现为 401）；已由
  "清 token → 重登一次 → 重试一次" 覆盖，不做定时刷新。
- **subscription/list 字段差异**：0001 已人工确认字段（`title`、`url`），
  风险低；若出现意外结构，按 `UpstreamError` 处理并在联调时修正映射。
- **uv 网络拉取依赖**：本机此前有网络代理经验（见 devlog 0001）；如
  `uv sync` 拉包失败，按"现象→证据→层级→原因→建议"流程报告，不擅自
  改系统配置。
- **.env 读取路径**：约定从 `services/bff/` 目录启动，`.env` 与
  `.env.example` 同放在该目录，避免相对路径歧义。

---

**本 Spec 为 Draft。在用户明确回复"批准 Spec，可以开始 Build"之前，不修改
任何仓库文件、不安装依赖、不运行初始化命令。**
