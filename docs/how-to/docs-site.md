# 文档站部署（GitHub Pages 与 doc.oouo.top）

LumiRSS 文档站是 VitePress 静态站点，源文件就是 `docs/` 下的同一批
Markdown（GitHub 渲染什么，站点就发布什么，没有第二份正文）。

选型说明：文档站框架选了 **VitePress 而不是 Starlight**。`docs/` 下的
Markdown 同时被 GitHub 渲染与站点构建，VitePress 直接消费这批文件，
复用既有导航结构（`check_docs_nav.py` 门禁）、本地搜索与 CI 死链门禁；
换 Starlight 意味着第二套目录约定与 frontmatter 语义，同一批正文要为
两个渲染器维持两份兼容性，失步风险大于收益。

- 构建即门禁：`npm run docs:build`（无 ignore，内部死链直接失败）；
- 当前发布通道：CI（`.github/workflows/docs.yml`）在
  `main` 分支构建并发布到 **GitHub Pages 项目站**，站点前缀
  `/LumiRSS/`（`docs/.vitepress/config.ts` 的 `base`，可用
  `DOCS_BASE` 覆盖）；
- 导航守卫：`python3 scripts/check_docs_nav.py` 校验 config.ts 里每个
  nav/sidebar 路由都有源文件（构建后还会核验 dist 产物）。

本文说明第二条承载路径：把同一份构建产物发布到 **doc.oouo.top**
（自托管宿主 Caddy，静态文件直出）。实际修改生产 Caddy 属于上线切换
动作，由运营者在切换阶段执行；本文只负责把前置条件、配置样例与同步
方式写清楚。

## 前置条件

1. **DNS**：`doc.oouo.top` 的 A/AAAA 记录指向宿主 Caddy 所在机器
   （与 `rss.oouo.top` 同一宿主时即同一 IP）。
2. **TLS**：宿主 Caddy 已对该域名具备签发条件（80/443 可达，宿主
   Caddy 以 system service 运行）。Caddy 会在站点块首次生效时自动
   申请证书，无需手工操作。
3. **构建产物同步目录**：在宿主准备一个目录，例如
   `/var/www/lumirss-docs`，运行 Caddy 的用户对其有读权限。

## 构建产物

在仓库根目录构建（Node 24，`npm ci` 后）：

```bash
npm run docs:build
# 产物目录：docs/.vitepress/dist/
```

产物为纯静态文件。因为发布到独立域名，`base` 必须是 `/`：

```bash
DOCS_BASE=/ npm run docs:build
```

GitHub Pages 通道保持默认 `base=/LumiRSS/` 不变；两个通道各按各的
base 构建，互不影响。

## Caddy 配置样例

在宿主 Caddyfile 新增独立站点块。`BEGIN/END` 托管块模式与
`./lumirss caddy-config` 生成的 `rss.oouo.top` 块一致（标记之间是
生成器管理区，本站点块全为手工区，标记仅用于风格统一与将来的工具化）：

```caddyfile
doc.oouo.top {
    # BEGIN LUMIRSS docs-site — static docs; managed by hand, keep markers.
    root * /var/www/lumirss-docs
    encode zstd gzip
    file_server
    # END LUMIRSS
}
```

要点：

- `root` 指向**同步目录**（不是仓库检出的 dist），仓库路径不进入
  Caddy 配置——与 [deploy.md §8a](./deploy) 的看板接法同款；
- 纯静态、无反代、无后端依赖；不要把任何 LumiRSS 服务的凭据或端口
  暴露进该块；
- 站点必须挂在独立域名/子域名上，不要挂在 `rss.oouo.top` 的路径
  之下：`base=/` 的产物挂在子路径会出现资源 404。

校验并重载（校验失败不会影响现有站点）：

```bash
caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy
```

自检：

```bash
curl -fsS -o /dev/null -w '%{http_code}\n' https://doc.oouo.top/
# 期望 200；再抽一个深层路由确认 cleanUrls 生效：
curl -fsS -o /dev/null -w '%{http_code}\n' https://doc.oouo.top/guide/features-reading
```

## 同步方式

文档站没有机密，同步用最朴素的通道即可（与看板同步方式相同）：

```bash
# 本地（或 CI runner）构建后推送
rsync -av --delete docs/.vitepress/dist/ host:/var/www/lumirss-docs/
```

- `--delete` 保持产物与 dist 一致，防止旧版本页面残留造成内容漂移；
- 静态文件同步后立即生效，无需 reload Caddy；
- 也可在 CI 里加一个 docs 发布 job（构建 `DOCS_BASE=/` 产物 + rsync
  到宿主）；当前阶段先手动同步，切换稳定后再固化 CI。

## 两条通道的关系

| 通道 | 触发 | base | 用途 |
| --- | --- | --- | --- |
| GitHub Pages（现状） | push 到 `main` 的 `docs/**` | `/LumiRSS/` | 默认公开文档站 |
| doc.oouo.top（本文） | 手动/CI rsync 同步 | `/` | 自有域名承载；切换后可作为主站 |

切换到 doc.oouo.top 作为主站后，GitHub Pages 通道**保留不删**（deprecate
而非移除），直到确认新通道稳定。
