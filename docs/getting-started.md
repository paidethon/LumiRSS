# 快速开始（Getting Started）

LumiRSS 是邀请制多账户、自托管、source-first 的信息阅读器。两条最常见
的起步路径：**自托管部署**（运营者）与**本地开发环境**（贡献者）。

## 自托管（推荐路径）

在一台全新的 Ubuntu 22.04/24.04 x86_64 服务器上（需 docker engine +
compose 插件、git、curl），一条命令完成部署：

```bash
git clone https://github.com/paidethon/LumiRSS.git && cd LumiRSS
sudo ./lumirss deploy
```

脚本会生成/引导填写 `.env.prod`（域名、登录账号密码）、拉取 GHCR 预构建
镜像（**prebuilt-only**：拉取失败即中止并保留旧栈）、启动生产栈并等待
健康检查。全部子命令：

```bash
./lumirss --help
```

部署、升级、回滚、备份、排障的完整手册见 [operations](/operations)。

<a id="first-login"></a>

## 首次登录

- **session 模式（主模式）**：部署后用 `sudo ./lumirss set-password`
  安装 owner 密码，然后在站点首页用账号密码登录；
- **basic 模式（兼容可选项）**：用 `.env.prod` 里的
  `LUMIRSS_AUTH_USER` / `LUMIRSS_AUTH_HASH` 凭据登录（bcrypt 哈希经
  `caddy hash-password` 生成，`$` 写成 `$$`）。

登录后进入「设置 → 服务」确认各依赖真实状态（BFF / FreshRSS / RSSHub
五态健康，不做假绿灯）。FreshRSS 初始化完成后 BFF 才会启动
（healthcheck 门控）；首次安装需先在 FreshRSS 完成安装向导。

## 邀请成员（多账户）

LumiRSS 默认邀请制：运营者在 `/admin` 发一次性限时邀请，受邀者自设
用户名密码激活，获得数据完全独立的账号。受邀者只需：

<a id="activate"></a>

1. 打开运营者提供的邀请链接（`/activate?token=…`）；
2. 自设用户名（3–32 字符，小写字母/数字/`-`/`_`）与密码（≥8 字符）；
3. 激活即建立完全独立的账号（订阅、阅读状态、资料库、AI、设置、
   FreshRSS 绑定全部按账号隔离）。

激活时 FreshRSS 账号由池原子分配；池空时账号照常可用、RSS 绑定诚实
显示「待就绪」，运营者补池即可。运营者侧的池准备、暂停/恢复、密码
重置与可选公开注册见 [operations](/operations#member-admin)。

## 本地开发环境

前置：Docker & Compose、Python 3.12+ with `uv`、Node.js 20+ with
`pnpm`（CI 用 Node 24）。

```bash
# 1. FreshRSS + RSSHub（dev compose）
docker compose up -d

# 2. BFF (FastAPI)
cd services/bff
cp .env.example .env    # 填入本地 FreshRSS 凭据
uv sync
uv run pytest           # 验证环境
uv run uvicorn lumirss.main:app --reload

# 3. Web (React) —— 另开终端
cd apps/web
pnpm install
pnpm dev
```

Web 客户端只发相对 `/api/v1/*` 请求，绝不接触 FreshRSS/RSSHub/AI 秘密。

**Seeded dev flow（真实数据走一遍）**：
`docker compose up -d` 后在浏览器完成 FreshRSS 初始化
（`127.0.0.1:8080`），创建开发用户、添加真实 RSS、设置专用 API
Password → 凭据填进 `services/bff/.env` → 启动 BFF → `pnpm dev` 打开
Web 确认 Timeline 出现真实文章 → 需要非 RSS 来源时在 FreshRSS 里订阅
一个 RSSHub 路由（如 `http://rsshub:1200/ithome/ranking/24h`）。

开发命令、测试门禁、生成物与 CI 见 [development](/development)；
配置键见 [configuration](/configuration)。

## 下一步

- 面向日常使用的功能指南：[usage](/usage)
- 部署与运维：[operations](/operations)
- 系统如何实现：[architecture](/architecture)
- 接下来做什么：[roadmap](/roadmap)
