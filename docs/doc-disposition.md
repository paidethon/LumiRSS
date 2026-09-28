# Doc Disposition（文档处置台账 v1）

> 治理索引：全仓库文档承载文件的处置结论与单一事实源（SSOT）归属。
> 依据 2026-09-28 只读全量审计（44 个文档承载文件）；处置落地见
> `feat/r2-docs` 分支 commit 历史。事实有变时先改活跃文档，再回来更新
> 本表的处置结论；本表不是内容索引——找文档看 [README.md](README.md)。

## 处置表

| path | disposition | evidence（一行） |
|---|---|---|
| README.md | UPDATE→done | 快速启动 `cd ../web` 指向不存在的 services/web → 已改 `../../apps/web` |
| AGENTS.md | UPDATE→done | §1 "no public registration" 与 ADR 0006 矛盾 → 已改为默认关闭的可选注册；§3 补 e2e//scripts//tests/ |
| CHANGELOG.md | KEEP-VERIFIED | 2.0.1 未发布节与 VERSION 一致；2.0.0 与部署证据一致 |
| LICENSE | KEEP-VERIFIED | AGPL-3.0-only；与 README、LICENSE_AUDIT 一致 |
| THIRD_PARTY_NOTICES.md | KEEP-VERIFIED | 头部与 AGPL-3.0-only 一致；依赖升级时自证 |
| VERSION | KEEP-VERIFIED | scripts/check-version.py 单源；apps/web/package.json=2.0.1 一致 |
| .github/PULL_REQUEST_TEMPLATE.md | KEEP-VERIFIED | 通用流程模板 |
| apps/web/README.md | UPDATE→done | 引用已删除的 docs/milestones/0005-web-shell.md → 已改指 docs/README.md，去掉"0005 起步"定位 |
| docs/README.md | KEEP-VERIFIED | ~20 索引链接全部可达 |
| docs/ROADMAP.md | UPDATE→done | "Current state" 成第二份 changelog → 已精简为一段 + 链接 CHANGELOG/implementation-status.json；Next/Deferred 保留 |
| docs/getting-started.md | KEEP-VERIFIED | 路径正确；Node 24 与 ci.yml 一致 |
| docs/how-to/deploy.md | KEEP + FLAG→done | 13 个子命令/flags 核实一致；§8 生产域名 → 已示例化为 rss.example.com；backup 行同步 FIX-192/201 |
| docs/how-to/invite-members.md | KEEP-VERIFIED | 与 ADR 0006、/admin API、freshrss_pool.sh 一致 |
| docs/how-to/backup-restore.md | KEEP→updated | 卷备份布局已变（FIX-192/209）：快照树 + MANIFEST.txt + LATEST，备份失败中止 update → 本文已重写同步 |
| docs/how-to/troubleshoot.md | UPDATE→done | 一处断行链接 → 已修复；2.0.0 回滚说明仍为当前 |
| docs/how-to/optional-services.md | KEEP-VERIFIED | 与 translate compose/CLI/端口一致 |
| docs/explanation/architecture.md | KEEP-VERIFIED | 控制库/用户库拆分与 user_scope.py、owner_migration.py 一致 |
| docs/explanation/project-map.md | KEEP-VERIFIED | 数据归属表与 architecture.md 一致 |
| docs/explanation/search.md | KEEP-VERIFIED | 投影机制 + 60s 同步间隔与配置一致 |
| docs/explanation/reuse-policy.md | KEEP-VERIFIED | 生成物表 + ruff/内联 SQL 规则与 AGENTS §7 一致 |
| docs/product/PRD.md | KEEP-VERIFIED | 多账户 + 默认关闭注册（ADR 0006）已更新 |
| docs/reference/configuration.md | KEEP→updated | 抽查键值一致；LUMIRSS_BACKUP_IMAGE 默认值过时（alpine:3.20）→ 已改为 BFF 镜像缺省 + python3+tar 约束 |
| docs/reference/freshrss-coverage.md | UPDATE→done | 用户管理行"无公开注册"过时 → 已按 ADR 0006 修正；`lumirss/…` 简写已规范为全路径 |
| docs/reference/testing.md | UPDATE→done | e2e 路径过时 → 已按 git ls-files 修正为 apps/web/e2e/…；CI 表与 ci.yml 一致 |
| docs/reference/performance.md | KEEP-VERIFIED | 与 tools/perf 一致 |
| docs/history/milestones.md | ARCHIVE→done | 加 frozen 横幅；0.2.0 笔误以〔勘误〕注记修正（实为 2.0.0），原文照录 |
| docs/audits/phase2-recovery.md | ARCHIVE（自声明冻结）+ FLAG→done | 自带"已冻结（2026-09-15）"横幅，未另加；生产域名+IP → 已脱敏为占位符并留脱敏说明 |
| docs/design/README.md | KEEP-VERIFIED | 文件表与设计系统摘要一致 |
| docs/design/design-system.md | KEEP-VERIFIED | §19 与 AGENTS §7 实质一致 |
| docs/design/reader-research.md | ARCHIVE→done | 2026-08-30 时点调研 → 加 frozen 横幅 |
| docs/upstream/UPSTREAMS.md | ARCHIVE→done | Gate 0C（2026-08-28）基线 → 加 frozen 横幅 |
| docs/upstream/SOURCE_MAP.md | ARCHIVE（自声明） | 自声明"historical source/attribution snapshot"，未另加横幅 |
| docs/upstream/LICENSE_AUDIT.md | ARCHIVE→done | Gate 0 清单 → 加 frozen 横幅；README 许可节链接保留 |
| docs/decisions/0001–0006 | KEEP-VERIFIED | 6 份 ADR 状态与不变量核对一致 |
| docs/implementation-status.json | KEEP-VERIFIED + FLAG（保留原样） | 机读台账带漂移守卫（`pnpm check:dashboard` 对照已提交的 dist/）；脱敏会破坏守卫且 dist/ 不属文档批次所有 → 本批次不改 |
| docs/release-notes.json | KEEP-VERIFIED | 2.0.0 与已发布一致；供应用内版本差异功能消费 |
| docs/.vitepress/config.ts | UPDATE→done | 站点描述"单用户"过时 → 已改"邀请制多账户" |
| docs/doc-disposition.md | NEW | 本表（治理索引） |
| tools/perf/README.md | KEEP-VERIFIED | 与 performance.md 方法一致；凭据声明为测试专用 |
| e2e/stack/fixtures/vault/AI/transformer.md | EXCLUDE | 测试夹具内容，不是文档，不改写 |

## 重复簇 → 单一事实源（SSOT）

1. 功能/发布清单：CHANGELOG（用户）+ implementation-status.json（机读）为 SSOT；ROADMAP 只链接；milestones/release-notes 为冻结存档
2. 部署步骤：how-to/deploy.md 为 SSOT；README/getting-started 只留最小入口
3. 版本号：VERSION 为 SSOT（scripts/check-version.py 强制派生一致）
4. 架构不变量 + 图：explanation/architecture.md 为 SSOT；README/AGENTS 只留摘要 + 链接
5. 认证/会话语义：configuration.md（键）+ deploy.md（流程）
6. 邀请/池运维：how-to/invite-members.md
7. 测试命令：reference/testing.md
