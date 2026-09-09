# Testing Reference

> 测试相关命令与门禁只维护在本文。开发流程见仓库根 `AGENTS.md`。

## 测试类型

| 类型 | 位置 | 说明 |
|---|---|---|
| BFF 单元/集成测试 | `services/bff/tests/`（pytest） | 上游网络全部 mock，DB 用临时文件 |
| Web 单元/组件测试 | `apps/web/src/**/__tests__/`（vitest） | 含 CSP 哈希漂移、API 契约对齐等钉子测试 |
| E2E（Playwright） | `apps/web/e2e/` | 桌面/移动完整 journey × 多视口 × 明暗主题，axe 可访问性门禁；另有确定性 CI smoke |
| 生产 compose 校验 | `docker-compose.prod.yml config` | 配置可渲染 |

## 标准命令

开发中只跑受影响的测试：

```bash
# Web — 单个测试文件
cd apps/web && pnpm test -- path/to/test

# BFF — 单个测试文件
cd services/bff && uv run pytest tests/test_specific.py
```

里程碑 Gate（或较大改动收口）跑全量：

```bash
# Web
cd apps/web
pnpm test
pnpm lint          # oxlint + tsc
pnpm build

# BFF
cd services/bff
uv run pytest
uv run ruff check src tests scripts
```

E2E（Playwright，针对运行中的栈；默认 `http://127.0.0.1`，即生产
compose 的 Caddy 入口 80/443）：

```bash
cd apps/web
LUMIRSS_E2E_BASE_URL=http://127.0.0.1:4173 pnpm test:e2e    # 全部项目
pnpm exec playwright test --project=desktop-1440            # 单视口
```

- `LUMIRSS_E2E_BASE_URL` 覆盖目标栈（如 CI 静态预览 `http://127.0.0.1:4173`
  或你的 HTTPS 域名）；`LUMIRSS_CI_STATIC=1` 用于静态构建的确定性 smoke。
- WebDAV journey 启动内存 WebDAV 服务器；BFF 跑在 Docker 里时需设
  `LUMIRSS_E2E_WEBDAV_URL=http://<docker-bridge-ip>:18081/`（compose 网络
  网关，如 `172.19.0.1` —— 私网 IP 满足 BFF 的 plain-http 策略）。
- 报告/trace/截图落在 gitignored 的 `test-results/` 与 `playwright-report/`。

## 何时跑什么

| 场景 | 门禁 |
|---|---|
| 日常小改（CSS/文案） | 仅受影响的测试文件 |
| 组件/路由改动 | 该模块 Web 测试 + lint |
| BFF 契约/settings 改动 | `uv run pytest` 相关文件 + `pnpm api:generate` / `pnpm settings:generate` 后让编译错误驱动修 Web |
| 里程碑 Gate | Web 全量（test/lint/build）+ BFF 全量（pytest/ruff）+ 相关 E2E |
| 改 `apps/web/index.html` 内联脚本 | 同步更新两个 Caddyfile 的 CSP sha256（测试会在漂移时报错） |

## CI jobs（.github/workflows/ci.yml）

| Job | 内容 |
|---|---|
| BFF tests (Python 3.12) | `uv lock --check` → `uv run ruff check src tests scripts` → `uv run pytest -q` |
| Generated contracts drift check | 重新生成 `api:generate` + `settings:generate`，`git diff --exit-code` 防漂移 |
| Web tests / lint / build | `pnpm test` → `pnpm lint` → `pnpm build` |
| Playwright Chromium smoke | 构建生产 bundle，静态预览（`LUMIRSS_E2E_BASE_URL=http://127.0.0.1:4173`，`LUMIRSS_CI_STATIC=1`）跑 `e2e/ci-smoke.spec.ts`（desktop-1440） |
| Production compose config | `docker compose -f docker-compose.prod.yml config` 渲染校验 |
| Production image build (no push) | 本地构建 BFF 与 Web 生产镜像确认可构建（不 push） |

CI 不使用任何真实凭据。

## UI 人工验收视口

```text
1920 × 1080 · 1440 × 900 · 1024 × 768 · 820 × 1180 (tablet portrait) · 390 × 844 (mobile)
```

明暗两种主题都检查；必须覆盖的状态：loading、空 feeds/entries、选中
entry、unread/read 与 starred/unstarred、网络/API 错误、键盘导航、移动
抽屉与列表→Reader 返回流。
