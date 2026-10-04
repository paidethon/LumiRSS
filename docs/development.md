# 开发指南（Development）

> 面向贡献者与 coding agent：开发环境、测试与 CI 门禁、生成物规则、
> 复用边界、文档治理与发布检查。项目身份与不变量速览见
> [AGENTS.md](https://github.com/paidethon/LumiRSS#readme)；系统实现见
> [architecture](/architecture)。

## 仓库地图

```text
apps/web/             React Web / PWA（TypeScript, Vite, Tailwind v4）
apps/ios/             SwiftUI 原生 iOS 客户端（XcodeGen 工程定义 + macOS CI）
services/bff/         FastAPI BFF（Python, uv）
docs/                 本文档站（VitePress，源文件即内容）
e2e/                  生产级 e2e 栈（compose + smoke fixtures）
scripts/              仓库维护脚本
tools/                进度看板、负载工具
tests/                部署/CLI 集成测试（shell）
```

开发环境搭建（dev compose → BFF → Web 三步）见
[getting-started](/getting-started#本地开发环境)。

## 测试

| 类型 | 位置 | 说明 |
|---|---|---|
| BFF 单元/集成 | `services/bff/tests/`（pytest） | 上游网络全部 mock，DB 用临时文件；`test_ios_native_compat.py` 钉住原生客户端依赖的服务端行为 |
| Web 单元/组件 | `apps/web/src/**/__tests__/`（vitest） | 含 CSP 哈希漂移、API 契约对齐等钉子测试 |
| iOS 单元 | `apps/ios/Tests/`（XCTest，macOS CI 运行） | 地址规范化、HTML 边界、缓存隔离、状态语义、分页去重 |
| E2E（Playwright） | `apps/web/e2e/` | 桌面/移动 journey × 多视口 × 明暗主题，axe 可访问性门禁；另有确定性 CI smoke |
| 生产级 compose 冒烟 | `e2e/stack/` | 真实拓扑栈（FreshRSS/RSSHub/Mailpit/fixtures/AI 桩/只读 vault），22 项 PASS/FAIL/SKIP；依赖外网的两项需 `LUMIRSS_E2E_ALLOW_NETWORK=1`（未设则如实 SKIP） |

标准命令——开发中只跑受影响的测试：

```bash
cd apps/web && pnpm test -- path/to/test        # Web 单个测试
cd services/bff && uv run pytest tests/test_specific.py
```

里程碑 Gate（或较大改动收口）跑全量：

```bash
cd apps/web && pnpm test && pnpm lint && pnpm build
cd services/bff && uv run pytest && uv run ruff check src tests scripts
```

E2E（Playwright，针对运行中的栈）：

```bash
cd apps/web
LUMIRSS_E2E_BASE_URL=http://127.0.0.1:4173 pnpm test:e2e
pnpm exec playwright test --project=desktop-1440   # 单视口
```

- `LUMIRSS_E2E_BASE_URL` 覆盖目标栈；`LUMIRSS_CI_STATIC=1` 用于静态构建
  的确定性 smoke；BFF 跑在 Docker 里时 WebDAV journey 需设
  `LUMIRSS_E2E_WEBDAV_URL=http://<docker-bridge-ip>:18081/`（私网 IP
  满足 plain-http 策略）。报告/trace/截图落在 gitignored 目录。

### 何时跑什么

| 场景 | 门禁 |
|---|---|
| 日常小改（CSS/文案） | 仅受影响的测试文件 |
| 组件/路由改动 | 该模块 Web 测试 + lint |
| BFF 契约/settings 改动 | 相关 pytest + `pnpm api:generate` / `pnpm settings:generate` 后让编译错误驱动修 Web |
| 里程碑 Gate | Web 全量（test/lint/build）+ BFF 全量（pytest/ruff）+ 相关 E2E |
| 改 `apps/web/index.html` 内联脚本 | 同步更新两个 Caddyfile 的 CSP sha256（漂移会被测试捕获） |

### 性能与内存防回归

CI 内自动（稳定、非计时型）：

- **Bundle 上限**：`pnpm build` 末尾 `apps/web/scripts/check-bundle-size.mjs`
  ——首屏 JS（entry + modulepreload）硬上限 **810 kB raw / 235 kB gzip**，
  并钉死懒加载契约（设置/移动页 chunk 不得回到 index.html 引用）；
- 查询内存契约（无限分页 maxPages 保险丝、read/star 精确缓存补丁）、
  认证/会话契约、PWA 契约各有钉子测试。

发布前手动（真实数字，不进 CI）：

```bash
cd apps/web && pnpm build
node scripts/soak-memory.mjs        # 浏览器内存 soak（--quick 冒烟）
node e2e/perf-measure.mjs           # LCP/CLS/资源体积
```

服务器侧负载/soak 方法论（固定 60/20/10/10 场景权重、warmup→steady→
report、诚实口径）与工程目标（2C/2G：BFF 空闲 ≤1.2 GiB、混合负载峰值
≤1.6 GiB、空闲 CPU ≤5%、轻量 API p95 ≤300ms——**设计目标非实测**）
见 `tools/perf/README.md` 与 `tools/perf/load-soak.mjs`。判定纪律：
"通过"仅说明该场景该时长内未发现退化；逐阶段线性增长才视为可疑泄漏。

## CI（.github/workflows/ci.yml）

| Job | 内容 |
|---|---|
| BFF tests (Python 3.12) | `uv lock --check` → `ruff check src tests scripts` → `pytest -q` |
| Generated contracts drift | 重新生成 `api:generate` + `settings:generate`，`git diff --exit-code` |
| Web tests / lint / build | `pnpm test` → `pnpm lint` → `pnpm build`（含 bundle 上限） |
| Playwright Chromium smoke | 生产 bundle 静态预览跑 `apps/web/e2e/ci-smoke.spec.ts` |
| Production compose config | `docker-compose.prod.yml config` 渲染校验 |
| Production image build (no push) | 本地构建 BFF 与 Web 生产镜像确认可构建 |

文档站 CI（`.github/workflows/docs.yml`）见[下节](#docs-site)。
仓库卫生门禁（repository-checks）：版本单源、必需文档存在、env 模板
结构与 configuration.md 主张窗校验、feature-manifest 校验、镜像元数据、
tracked-secrets 扫描。CI 不使用任何真实凭据。

## iOS 客户端（apps/ios，`.github/workflows/ios.yml`）

iOS 构建只发生在 macOS runner 上——WSL/Linux 从不充当 iOS 构建机。
流水线：契约子集漂移检查（ubuntu）→ XcodeGen 生成工程 → xcodebuild
模拟器构建 + XCTest 单测 → 启动冒烟（simctl 装进真模拟器、截图、进程
存活断言）→ 未签名 iphoneos 归档（dev preview，**不是可安装 IPA**）。

| 操作 | 命令 |
| --- | --- |
| 生成 Xcode 工程（需 macOS + XcodeGen 2.46.0） | `cd apps/ios && xcodegen generate` |
| 本地构建/测试（需 Mac） | `xcodebuild -project LumiRSS.xcodeproj -scheme LumiRSS -destination 'platform=iOS Simulator,name=iPhone 16' -skipPackagePluginValidation test` |
| 重新过滤 iOS 契约子集 | `python3 apps/ios/scripts/filter_openapi.py`（CI `--check` 漂移门禁） |

- 工程源是真源 `apps/ios/project.yml`；`LumiRSS.xcodeproj/` 不入库。
- Swift API 客户端由 [swift-openapi-generator](https://github.com/apple/swift-openapi-generator)
  1.13.1（build plugin，CI 固定版本）从 `LumiRSS/API/openapi.json`
  生成；该 JSON 由脚本从权威导出 `apps/web/src/api/generated/openapi.json`
  过滤而来——不存在第二份手写权威契约。
- 依赖锁定：OpenAPIRuntime 1.12.2 / OpenAPIURLSession 1.3.2 /
  generator 1.13.1 / XcodeGen 2.46.0（project.yml `exactVersion`）。
- 最低 iOS 17.0；客户端版本独立于服务器 VERSION（当前 0.1.0 Preview）。

### iOS 签名（当前未配置——人工补齐清单）

仓库 Secrets 只有 `DOCS_DEPLOY_*`，没有 Apple 签名材料，因此 CI 只产
未签名归档。补齐以下配置后签名 job 即可启用（workflow 已预留结构）：

1. `IOS_P12_BASE64` + `IOS_P12_PASSWORD`：分发证书（Keychain 导出）；
2. `IOS_MOBILEPROVISION_BASE64`：Ad Hoc profile（含目标设备 UDID）；
3. `IOS_KEYCHAIN_PASSWORD`：临时 Keychain 口令（随机即可）；
4. 在 `ios.yml` device-archive job 中替换为签名 archive + export
   （`-exportOptionsPlist` method=ad-hoc），产物即 Ad Hoc IPA；
5. Bundle ID `io.github.paidethon.LumiRSS` 需在开发者账户注册
   （或改成你拥有的 ID：project.yml + Info.plist 一处改）。

TestFlight 另需 App Store Connect API Key（`IOS_ASC_KEY_ID/ISSUER/CONTENT`）
与 App Record；上传成功≠外部测试可用，以 App Store Connect 状态为准。

<a id="generated-artifacts"></a>

## 生成物与复用边界

新增基础设施之前，先查真源归属：上游/框架已拥有的职责，不在 Lumi 里
长出第二份实现；Lumi 只保留真正的产品策略与安全边界。

| Domain | Source of truth |
| --- | --- |
| RSS entries / read / star、订阅 / 分类存储 | FreshRSS（Lumi SQLite 永不 shadow-copy） |
| non-RSS feed 生成 | RSSHub（上游 generator，不是 entry 数据库） |
| 公开 API 契约 | FastAPI / Pydantic（所有路由带 `response_model`；改契约=改模型） |
| Web API 类型 | 生成物 `apps/web/src/api/generated/schema.ts`（types.ts 只是领域别名层） |
| server 可持久化 settings | Pydantic `PortableSettings`（前端消费生成的 `settings-meta.ts`） |
| curated RSSHub 路由暴露 / 配置项 schema | Lumi policy（`rsshub.py CATALOG` / curated allowlist——上游无稳定机器可读 schema） |
| overlay / a11y 行为 | Base UI（只允许在 `components/ui/` 内 import） |
| 服务器状态缓存 | TanStack Query（query keys 集中在 `api/queries.ts`） |
| Lumi 视觉 tokens | `--lumi-*`（见 [design-system](/design-system)） |
| secrets | 服务端 SecretStore（0600 JSON；永不进浏览器/日志/备份） |
| AI 派生缓存 | Lumi SQLite（`ai_artifacts.py` 共享机制） |

### 生成物一览（AUTO-GENERATED — DO NOT EDIT）

| 生成物 | 命令 | Drift 检查 |
| --- | --- | --- |
| `apps/web/src/api/generated/openapi.json` + `schema.ts` | `pnpm api:generate` | `pnpm api:check`（CI 同） |
| `apps/web/src/api/generated/settings-meta.ts` | `pnpm settings:generate` | `pnpm settings:check`（CI 同） |
| `apps/ios/LumiRSS/API/openapi.json`（iOS 契约子集） | `python3 apps/ios/scripts/filter_openapi.py`（输入是上面的权威导出） | 同命令 `--check`（ios.yml CI 同） |
| Swift API 客户端 | swift-openapi-generator build plugin（编译期生成，不入库） | xcodebuild 编译失败即漂移 |
| `apps/ios/LumiRSS.xcodeproj` | `xcodegen generate`（project.yml 为真源，产物不入库） | CI 每次重新生成 |
| `services/bff/src/lumirss/rsshub_routes.generated.json` | `services/bff/scripts/export_rsshub_routes.py`（需本地 docker） | digest 断言测试 |
| `tools/progress-dashboard/dist/` | `npm run build:dashboard` | `npm run check:dashboard` |
| `docs/.vitepress/dist/` | `npm run docs:build`（不入库） | 构建死链 + nav 门禁 |

规则：每个生成物必须有确定性 generator 与 drift 检查；改契约/改
settings 的流程永远是改 BFF 模型 → 重新生成 → 消费编译错误/测试驱动修
Web。新增生成器时在此表登记输出路径（不得覆盖手写文档）。

### Python 静态防护

`services/bff` 使用 ruff（`F/E/W/I/UP/B/SIM`；E501 因历史无行宽约定而
暂缓）。F811 阻止同 class 内重复定义方法的静默覆盖。SQL 一律内联字面量
写在 execute 调用处——静态安全工具拒绝任何间接引用的 SQL。

### KEEP — 有意保留的自研实现

- **WebDAV 客户端（`webdav.py`）**：thin 协议层承载 TLS verify 开关、
  origin-pinned redirects、有界读取、`dir_fd` + 0600、路径禁越、错误
  脱敏——安全属性是产品职责，不是"协议轮子"；
- **AI provider transport（`ai_provider.py`）**：单一 OpenAI-compatible
  POST（~69 LOC）；重量级 SDK 不值得，streaming 需求出现再评估；
- **RSSHub 配置项 schema**：curated allowlist 本身就是安全策略；
- **PaneSeparator**：94 LOC（ARIA + 键盘 ±10px + 双击重置 + 持久化），
  引依赖不划算；
- **EntryRow / EntryCard 双组件**：桌面行/移动卡片的形态分裂是有意的
  响应式策略（共享逻辑已下沉）。

### 反模式（不许再长回来）

- Feature 组件直接 import `@base-ui/react`（必须经 `components/ui/`）；
- 手写 BFF 响应 DTO、手抄 settings 默认值/边界/枚举；
- Web 里拼 BFF 之外的第二条 HTTP 通道（`api/client.ts` 是唯一出口）；
- 第二个 headless UI 库、为几十行代码引入大依赖、把"调研过"的库留在
  依赖清单里。

## 文档治理规则

- **默认禁止创建新的 Markdown 文档。** 如果信息能够归属现有 SSOT，
  必须更新现有文档；只有明确证明现有 Owner 无法承载时才允许增加长期
  文档。`scripts/check_docs_allowlist.py`（CI）对 `docs/**/*.md` 白名单
  外的新文件报错并提示：`Can this information be added to an existing
  SSOT document?`（确有必要时显式扩充白名单）。
- 一个事实只允许一个长期文档拥有；其他文档链接过去。事实有变先改
  代码与测试，再改文档。
- Chat history、旧 task prompt、旧 audit、历史计划不能凌驾于仓库当前
  代码、测试和 authoritative docs。历史由 Git 保存，不建永久归档页。
- 当前活跃 SSOT 全集（白名单即此清单）：

| 文档 | 唯一职责 |
|---|---|
| `/`（index.md） | 文档站首页 + 导航 |
| `getting-started.md` | 安装、首次启动/登录、激活、最短自托管 |
| `usage.md` | 普通用户功能指南 |
| `operations.md` | 部署/升级/回滚/备份/恢复/成员/健康/排障 |
| `configuration.md` | 全部配置键与默认值 |
| `architecture.md` | 系统如何实现（含已稳定架构决策结论） |
| `design-system.md` | UI/UX 规则 |
| `development.md` | 本文 |
| `roadmap.md` | 接下来做什么 / 非目标 |
| `upstreams.md` | FreshRSS/RSSHub 能力覆盖对照 |
| `upstream/*.md` | LEGAL：许可审计/来源归档（不进站点导航） |
| `*.json` | 机读件：feature-manifest（CI 校验）、implementation-status（看板）、release-notes（BFF 运行时消费，**不可移动**） |

## 文档站发布（doc.oouo.top） {#docs-site}

文档站是 VitePress 静态站点，源文件就是 `docs/` 下的同一批 Markdown
（GitHub 渲染什么，站点就发布什么）。两条发布通道由 CI
（`.github/workflows/docs.yml`）自动维护：

| 通道 | 触发 | base | 定位 |
| --- | --- | --- | --- |
| **doc.oouo.top（正式站）** | push 到 `main` 的 `docs/**` | `/`（默认） | 唯一正式文档地址；canonical 指向它 |
| GitHub Pages 项目站 | 同上 | `/LumiRSS/`（CI 显式 `DOCS_BASE`） | GitHub 原生镜像，不作公开主地址 |

正式站链路：GitHub Actions 构建（base `/`）→ 专用受限密钥
（`docs-deploy`，GitHub Secrets：`DOCS_DEPLOY_HOST/USER/KEY/KNOWN_HOSTS`）
rsync 到服务器 `/opt/lumirss-docs/releases/<ts>/` → 原子切换 `current`
符号链接 → 宿主 Caddy `file_server`（`try_files` 支持 cleanUrls，
`handle_errors` 兜底 VitePress 404.html）。Caddy 站点块带
`BEGIN/END LUMIRSS docs-site` hand-managed 标记，位于
`./lumirss caddy-config` 托管块之外（应用重新生成不会覆盖它）。部署后
CI 自动跑 production smoke：按本次构建产物生成路由清单，逐条验证生产
站 200 + 资源可达 + 无旧 base 自引用。

门禁：`npm run docs:build`（内部死链直接失败，唯一豁免是
`docs/public/reference/upstream-feature-matrix.html` 这个独立 HTML
资产）+ `python3 scripts/check_docs_nav.py`（nav/sidebar 路由核验）+
allowlist 检查。本地：`npm run docs:dev` / `docs:build` / `docs:preview`
（preview 与生产同样运行在根 base）。

## 许可与上游引用政策

LumiRSS 采用 **AGPL-3.0-only**（仓库根 `LICENSE`），以便合规适配 AGPL
参考代码；第三方通知见 `THIRD_PARTY_NOTICES.md`。参考仓库（Folo、
OrigRead 等）以只读兄弟目录克隆（`../LumiRSS-reference/`），绝不编辑、
push、vendor 或 submodule 进 LumiRSS。硬规则：

- 不复制 Folo `icons/mgc`；
- OrigRead Android GPL 代码默认只作行为和移动端参考，除非另行确认；
- 视觉启发、独立重写、代码适配、直接复制必须分别记录
  （归档见 `docs/upstream/SOURCE_MAP.md` 与 `docs/upstream/UPSTREAMS.md`，
  许可审计见 `docs/upstream/LICENSE_AUDIT.md`——LEGAL 存档，不在站点
  导航内）。

## UI 人工验收视口

```text
1920 × 1080 · 1440 × 900 · 1024 × 768 · 820 × 1180 (tablet portrait) · 390 × 844 (mobile)
```

明暗两主题；必须覆盖 loading、空 feeds/entries、选中 entry、
unread/read 与 starred/unstarred、网络/API 错误、键盘导航、移动抽屉与
列表→Reader 返回流。视觉规则见 [design-system](/design-system)。
