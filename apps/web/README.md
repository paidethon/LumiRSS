# LumiRSS Web

LumiRSS 的 React Web 客户端（0005 — Web Shell 起步）。

技术栈：React + TypeScript + Vite + Tailwind CSS v4 + TanStack Query +
Zustand。开发时所有 API 请求走相对 `/api/v1/*` 路径，由 Vite dev
proxy 转发给 BFF（`http://127.0.0.1:8000`）。

```bash
pnpm install    # 安装依赖
pnpm dev        # 开发服务器 http://localhost:5173（需先启动 BFF :8000）
pnpm test       # Vitest 测试（全 mock，无真实网络）
pnpm lint       # oxlint
pnpm build      # 生产构建（tsc -b + vite build → dist/）
```

完整说明见仓库根 `README.md` 与 `docs/specs/0005-web-shell.md`。
