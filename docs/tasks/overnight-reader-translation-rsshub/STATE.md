# STATE.md — overnight-reader-translation-rsshub

- 基线 SHA：`e3c4de7`（= origin/main 68ded4e 的内容，PR #35 已合并）
- 任务分支：`feat/overnight-reader-translation-rsshub-20260907`（自 e3c4de7 创建）
- 启动时间：2026-09-07；**收尾稳定化轮：2026-09-08（本轮）**
- 参考项目 clone：`/home/zephyr/projects/research/`（Folo=Guyungy fork、read-frog、legado；不入 LumiRSS）

> 状态口径：下表所有「完成」均有 commit + 自动化测试 + （如适用）真实集成 /
> 浏览器验收证据支撑；未经真实外部服务验证的子项在 VALIDATION.md §5 逐条列出。

## 七项需求状态（最终）

| # | 需求 | 状态 |
|---|---|---|
| 1 | 长时间任务组织 | 完成（Gate 0-6 + 2026-09-08 收尾轮） |
| 2 | Folo(Guyungy) 深度对比 | 完成（仅调研）：[FOLO_COMPARISON.md](FOLO_COMPARISON.md) |
| 3 | 设置开关重复文字清理 | 完成：1fd589c；7 分类浏览器实测零残留（switch-duplicate-text.json 全空） |
| 4 | 微信读书/Legado 阅读设置调研 | 完成（仅调研）：[READING_SETTINGS_RESEARCH.md](READING_SETTINGS_RESEARCH.md) |
| 5 | 翻译三模式 + 分块双语 + 统一设置 + 本地引擎 | 完成：d3cf014；自动化回归 + 浏览器验收通过 |
| 6 | RSSHub 自动识别 + 自定义凭据 + 应用链 | 完成：9228256；隔离栈实测 + [RSSHUB_OPERATIONS.md](RSSHUB_OPERATIONS.md) |
| 7 | 完整备份修复 | 完成：c8a1bcc；隔离栈备份→恢复→重启全链路实测 |

## 2026-09-08 收尾稳定化轮（本轮新增）

1. **E2E B/C 遗留关闭**：`E2E-ISSUES-B-C-20260906.md` 所记 J2 数据依赖与 a11y
   对比度问题，其修复（`f9e86fb`、`6bed703`）已在分支祖先（经 main PR #34）。
   本轮以真实运行复核：J2 ×4（1440×3 + 1920×1）、a11y 桌面 3 项 + 移动 4 项
   全部通过；问题文档归档至本目录并标注解决状态。
2. **J4/M3 journeys 修复**（本轮唯一测试代码外的缺陷不在产品，在测试与环境）：
   - docker 网络子网漂移：spec 默认网桥 IP 172.19.0.1 已过期（现 172.18.0.1），
     改为运行时从 lumirss compose 网络探测网关（env 可覆盖，127.0.0.1 兜底）；
   - BFF 调任何 OpenAI 兼容端点都要求非空 key：J4/M3 增加幂等自建前置
     （仅在未配置时经 write-only API 写入显式假 key，绝不覆盖真实 key）；
   - 摘要卡状态收敛：not_generated / failed / cached 三种前置态都收敛到断言。
3. **安全审计**（分支新代码，只读外部审计）：无 P0/P1。已修：env 文件物化
   0700 目录 + 建文件即 0600（窗口期消除）、自定义凭据 envKey 不得遮蔽固定
   schema 键、控制字符在写入时拒绝、凭据表单成功后清空。其余 P3 记录为
   0021 candidate（见 VALIDATION.md §6）。
4. **浏览器引擎目标语言修复**：本地翻译器此前硬编码 en→zh-CN，忽略设置中的
   目标语言；现按设置解析并随语言变更重建（ReaderTranslation.tsx）。
5. **Base UI 契约修复**：RadioOption 改渲染 `<span>`（Base UI Radio.Root 期望
   非 `<button>` 目标），消除 3 处 console error；1920 全程 console 零错误。
6. **验收工具修复**：gate6-reader / gate6-mobile-dark 的 `.first()` 点击加可见性
   过滤（390px 下会命中隐藏的桌面渲染节点）；新增 gate6-1920-console.cjs
   （1920 视口 + console error 采集）。

## 最终命令结果（2026-09-08，详见 VALIDATION.md §1）

- BFF：`uv run pytest -q` → **634 passed**；ruff clean
- Web：`pnpm test` → **580 passed**；oxlint 0 errors；`tsc -b` clean；build clean
- api:check / settings:check：生成物零 drift
- E2E：desktop journeys 6/6、mobile journeys 4/4×3 视口、a11y 7 项、
  rapid-selection、ci-smoke 2/2 全部通过（对 dev 栈 5173 / 静态 4173）

## 阻塞 / 未验证（诚实清单）

见 [VALIDATION.md](VALIDATION.md) §5：FreshRSS bind 迁移（人工 1 条命令）、
真实 LibreTranslate、Chrome Translator API 真机、BFF 镜像构建（代理阻断）、
真实付费 AI provider、用户实例深色逐像素复检。
