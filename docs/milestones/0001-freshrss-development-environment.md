# Devlog 0001 — FreshRSS Development Environment

> Milestone: 0001 FreshRSS Development Environment
> Phase: Phase 1 — RSS Foundation
> 日期：2026-08-25
> 结果：Completed（提交 `0a6a478`）

## Status

Completed。

- Spec：`docs/specs/0001-freshrss-development-environment.md`（先写 spec，再实现，再验收）
- 结果提交：`0a6a478`（4 个文件：`docker-compose.yml`、spec 0001、`README.md`、`docs/PROJECT_STATE.md`）
- 运行环境：FreshRSS 1.29.1 容器（`freshrss`），绑定 127.0.0.1:8080，数据保存在 named volume `freshrss-data`

## Goal

在本机用 Docker Compose 启动 FreshRSS，通过浏览器完成初始化（开发用户、一个真实 RSS、专用 API Password），再用 Google Reader API 的 ClientLogin 认证后实际读取订阅列表，证明 FreshRSS 数据源链路可用。

## What was implemented

- `docker-compose.yml`：单服务 `freshrss/freshrss:1.29.1`，端口 `127.0.0.1:8080:80`（仅本机可访问），`TZ=Asia/Shanghai`，named volume 持久化。
- 浏览器初始化（凭据不写入仓库）：
  - 安装向导选择 SQLite 数据库（开发期便利，不代表生产数据库决策）；
  - 创建开发用户并登录；
  - 启用 "Allow API access"（Configuration → Authentication）；
  - 订阅真实 RSS：阮一峰的网络日志；
  - 配置专用 API Password（值：`[REDACTED]`，从未写入任何仓库文件）。
- API 验证：
  - ClientLogin 认证成功（HTTP 200，返回 Auth token：`[REDACTED]`）；
  - subscription/list 成功（HTTP 200，JSON 含 2 个订阅：FreshRSS 官方 releases 订阅 + 阮一峰的网络日志）。
- Docker 镜像拉取问题处理：Docker daemon 代理（systemd drop-in）+ 多次重试。
- 文档：spec 0001、README 开发命令、PROJECT_STATE 状态更新。

## Key user ↔ AI dialogue

（以下为该次会话的关键片段摘要，非逐字原文；所有凭据已 `[REDACTED]`）

1. 用户指令：以 FreshRSS 开发环境作为第一个里程碑，先写 Spec 再动手。→ AI 产出 spec 0001，明确 Goal / Scope / Out of scope / 6 条验收标准与验证方式。
2. AI 检查发现本机没有 Docker，给出安装命令；用户自行安装后确认 `docker compose version` 输出 2.40.3。
3. `docker pull` 直连 Docker Hub 超时。AI 依次测试公共镜像源：`docker.m.daocloud.io` 返回 403，`docker.1ms.run` 可用但速度约 20KB/s（371MB 镜像约需 1 小时）。
4. 用户提供 Windows 代理地址（`172.25.x.x:7890`）。AI 给出 systemd drop-in 方案（`/etc/systemd/system/docker.service.d/proxy.conf`）为 Docker daemon 配置代理；用户以 sudo 手动执行并 `systemctl restart docker`。
5. 代理生效后 `auth.docker.io` 可达，但镜像 blob 下载多次 EOF 中断。AI 启动重试循环继续断点拉取，用户接力完成剩余下载，最终 371MB 镜像完整拉取。
6. `docker compose up -d` 后：`docker compose ps` 显示 running；`curl -sI http://localhost:8080` 返回 302（跳转安装向导 `/i/`）。
7. AI 引导用户完成浏览器初始化并订阅真实 RSS；用户提供 API Password 供 ClientLogin 测试（密码值只出现在命令行参数里，从未写入仓库）。两条 curl 验证全部通过，用户确认里程碑完成。

## Commands actually executed

（真实执行过的命令；凭据一律 `[REDACTED]`，无法逐字复原的以等价形式列出）

```bash
# 开工检查
git status --short --branch
git branch -a
git log --oneline --decorate -8

# Docker 环境
docker compose version                              # 2.40.3
sudo apt-get install docker.io docker-compose-v2    # 用户自行执行

# 镜像拉取（多次失败与重试）
docker pull freshrss/freshrss:1.29.1                # 直连 Docker Hub 超时
curl -I https://docker.m.daocloud.io/v2/            # 403
# docker.1ms.run 可用但约 20KB/s
sudo systemctl restart docker                       # 配置 daemon 代理后（用户执行）
docker pull freshrss/freshrss:1.29.1                # 代理下多次 EOF，重试循环最终成功

# 启动与验证
docker compose up -d
docker compose ps                                   # freshrss Up
curl -sI http://localhost:8080                      # 302 → /i/

# Google Reader API 验证
curl -X POST 'http://localhost:8080/api/greader.php/accounts/ClientLogin' \
  -d 'Email=[REDACTED]' -d 'Passwd=[REDACTED]'
# → HTTP 200，输出含 Auth=[REDACTED]

curl 'http://localhost:8080/api/greader.php/reader/api/0/subscription/list?output=json' \
  -H 'Authorization: GoogleLogin auth=[REDACTED]'
# → HTTP 200，JSON 含 2 个订阅

# 收尾
grep -riE 'Passwd=|GoogleLogin auth=|Auth=' README.md docs docker-compose.yml   # 敏感信息扫描，零命中
```

## Problems encountered

1. Docker Hub（`registry-1.docker.io`）从本地网络直连超时。
2. 公共镜像源不可用或极慢：`docker.m.daocloud.io` 返回 403；`docker.1ms.run` 约 20KB/s。
3. 配置代理后 `auth.docker.io` 可达，但大 blob 传输多次 EOF 中断。
4. systemd 代理配置需要 sudo，Agent 无法自动执行。
5. WSL2 环境下代理需要指向 Windows 宿主机地址。

## How problems were solved

1. 通过 systemd drop-in 为 Docker daemon 配置 HTTP/HTTPS 代理（系统级配置，改完 `systemctl restart docker`）。
2. 代理链路不稳定 → 用"多次重试 + 断点续传"策略对冲，最终完整拉下 371MB 镜像。
3. 需要 sudo 的步骤明确交给用户手动执行，Agent 不越权。
4. 凭据安全：API Password 与 Auth token 只存在于浏览器会话与 Docker volume；收尾用 grep 扫描确认仓库零命中。

## Acceptance evidence

Spec 0001 的 6 条验收全部达成：

1. `docker compose up -d` 后 freshrss 服务运行中（`docker compose ps`：Up）。
2. 浏览器可访问 http://localhost:8080 并登录开发用户。
3. 订阅列表包含真实 RSS（阮一峰的网络日志），且能浏览其文章。
4. 开发用户已配置专用 API Password。
5. ClientLogin 认证成功（HTTP 200 + Auth token）。
6. subscription/list 返回的 JSON 包含该 RSS（共 2 个订阅）。

其中 2–4 由用户在浏览器人工确认；1、5、6 有命令行输出证据。

## What I learned

- Google Reader API 的认证流：`ClientLogin(Email + Passwd)` → 拿到 `Auth` token → 后续请求带 `Authorization: GoogleLogin auth=<token>`。
- Docker daemon 的代理是系统级配置（systemd drop-in + restart），与给 shell 设置 `HTTP_PROXY` 不是一回事。
- 镜像拉取失败时，优先"重试 + 断点续传"，而不是清空重来。
- FreshRSS 1.29.1 经 GitHub API 确认为当时（2026-05-20 发布）最新稳定版。
- 凭据从进入仓库的第一道关就该挡住：写完立刻 grep 扫描。

## Remaining questions

- 生产环境（Phase 6）部署到阿里云 ECS 时，镜像拉取是否仍需代理或镜像源——留到 0011/0012 再解决。
- FreshRSS 开发期用 SQLite 只图便利，生产数据库选型已在 spec 0001 中标记为 out of scope，留待真实需求出现。

## Next milestone

0002 — BFF + FreshRSSAdapter（Phase 2 — Backend Core）。
