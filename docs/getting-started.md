# Getting Started

## Self-hosting quick start（推荐）

在一台全新的 Ubuntu 22.04/24.04 x86_64 服务器上，一条命令完成部署：

```bash
git clone https://github.com/paidethon/LumiRSS.git && cd LumiRSS
sudo ./lumirss deploy
```

脚本会生成/引导填写 `.env.prod`（域名、浏览器登录账号密码）、拉取 GHCR
预构建镜像（不可用时自动本地构建）、启动生产栈并等待健康检查。全部子命令
（update / status / logs / backup / restore / doctor / rollback）见：

```bash
./lumirss --help
```

生产部署、升级与运维的完整说明：[how-to/deploy.md](how-to/deploy.md)。

## 本地开发环境

### Prerequisites

- Docker & Docker Compose（FreshRSS + RSSHub）
- Python 3.12+ with `uv`（BFF）
- Node.js 20+ with `pnpm`（Web；CI 用 Node 24）

### FreshRSS and RSSHub

```bash
docker compose up -d
```

使用仓库内 Compose 文件的精确版本。真实凭据永不进 Git。

### BFF (FastAPI)

```bash
cd services/bff
cp .env.example .env    # 填入本地 FreshRSS 凭据
uv sync
uv run pytest           # 验证环境
uv run uvicorn lumirss.main:app --reload
```

BFF 在本机运行，经配置的 URL 连接 FreshRSS。

### Lumi SQLite and AI

- `LUMIRSS_DB_PATH` — 可选；默认 `<services/bff>/data/lumi.sqlite`
  （首次使用存储时创建，已 git-ignore）。测试始终用临时 DB。
- `AI_API_KEY` — 可选的 OpenAI-compatible API key（仅服务端秘密；
  不入库、不进浏览器）。留空 = AI 未配置，Reader 诚实显示未配置状态。
  也可以在浏览器「设置 → AI」中直接填写（存服务端 SecretsStore）；
  env 变量仅作为默认配置路径的回退。
- 非秘密 AI 设置与 AI profiles（摘要 / 翻译 / AI 对话的 purpose 映射）
  在 Web UI「设置 → AI」管理，持久化于 lumi.sqlite。

配置项完整参考：[reference/configuration.md](reference/configuration.md)。

### Web (React)

```bash
cd apps/web
pnpm install
pnpm dev                # dev server
pnpm test               # 测试
pnpm lint               # lint
pnpm build              # 生产构建
```

Web 客户端只发相对 `/api/v1/*` 请求，绝不接触 FreshRSS/RSSHub/AI 秘密。

### Seeded dev flow（真实数据走一遍）

1. `docker compose up -d` 后在浏览器完成 FreshRSS 初始化
   （`127.0.0.1:8080`），创建开发用户、添加真实 RSS、设置专用 API Password；
2. 把凭据填进 `services/bff/.env`，启动 BFF；
3. `pnpm dev` 打开 Web，确认 Timeline 出现真实文章；
4. 需要非 RSS 来源时，在 FreshRSS 里订阅一个 RSSHub 路由
   （如 `http://rsshub:1200/ithome/ranking/24h`）再回 Lumi 阅读。

### Progress Dashboard

```bash
open tools/progress-dashboard/index.html   # 纯静态页面，零依赖
```

看板读 `project-data.js`，不是事实来源；项目状态以 `docs/README.md`
与 `docs/ROADMAP.md` 为准。

### Reference repositories

UI 研究用参考仓库以只读兄弟目录克隆
（`../LumiRSS-reference/Folo` 等）。绝不编辑、push、vendor 或 submodule
进 LumiRSS。
