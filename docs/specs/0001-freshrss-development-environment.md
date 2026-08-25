# Spec 0001 — FreshRSS Development Environment

> 日期：2026-08-25
> 对应 PRD 阶段：Phase 1 — FreshRSS

## Goal

在本机用 Docker Compose 启动 FreshRSS，通过浏览器完成初始化（开发用户、
一个真实 RSS、专用 API Password），并用 Google Reader API 的 ClientLogin
认证后实际读取订阅列表，证明 FreshRSS 数据源链路可用。

## Scope

- 新增根目录 `docker-compose.yml`：仅一个 FreshRSS 服务
  （官方镜像 `freshrss/freshrss:1.29.1`），绑定 `127.0.0.1:8080`，
  数据用 named volume 持久化。
- FreshRSS 通过浏览器安装向导初始化（凭据不写入仓库）：
  - 创建开发用户；
  - 启用 API 访问；
  - 订阅一个真实 RSS；
  - 配置专用 API Password。
- 用 curl 验证 ClientLogin 与 subscription/list。
- 更新 `docs/PROJECT_STATE.md` 与 `README.md` 的开发环境说明。

## Out of scope

FastAPI、FreshRSSAdapter、React、RSSHub、AI、Caddy、HTTPS、阿里云、
PWA、生产部署、备份、cron 定时刷新、任何 LumiRSS 应用代码。
FreshRSS 内部使用 SQLite 仅为开发期便利，不代表生产数据库决策。

## Acceptance Criteria

1. `docker compose up -d` 后 freshrss 服务运行中。
2. 浏览器可访问 http://localhost:8080 并登录开发用户。
3. 订阅列表包含至少一个真实 RSS，且能浏览其文章。
4. 开发用户已配置专用 API Password。
5. ClientLogin 认证成功（HTTP 200，返回 Auth token）。
6. 用该 token 调用 subscription/list，返回 JSON 中包含该 RSS。

## Verification

- `docker compose ps` 服务 running；`curl -sI http://localhost:8080` 返回 200/302。
- 验收 2–4 由人工在浏览器确认。
- `curl -X POST http://localhost:8080/api/greader.php/accounts/ClientLogin -d 'Email=<用户名>' -d 'Passwd=<API密码>'` 输出含 `Auth=`。
- `curl http://localhost:8080/api/greader.php/reader/api/0/subscription/list?output=json -H 'Authorization: GoogleLogin auth=<token>'` 返回订阅 JSON。
