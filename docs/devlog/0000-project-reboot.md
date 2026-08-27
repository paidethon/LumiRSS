# Devlog 0000 — Project Reboot

> Milestone: 0000 Project Reboot
> Phase: Phase 0 — Foundation
> 日期：2026-08-24 ～ 2026-08-25
> 结果：Completed（提交 `29b03ec`，经 PR #4 合入 main）

## Status

Completed。

- 工作分支：`chore/project-reboot`（自 main `abef74d` 创建）
- 结果提交：`29b03ec`（17 个文件，+864 / −2240），经 PR #4（merge commit `dfe3299`）合入 main
- 旧历史备份：`archive/pre-wsl-reset` 分支（本地与远程均存在，指向 `abef74d`），所有被删除的文件均可从该提交找回

## Goal

把旧的"多文档脚手架"仓库收敛成一个最小、清晰、可以直接继续开发的新基线：

- 采用 PRD v5.0（Reboot Baseline）作为唯一产品依据；
- 删除 Repository Bootstrap 时代的旧文件；
- 重写核心文档，让新的开发 Agent 只靠 Git 仓库（而不是旧聊天记录）就能理解项目。

## What was implemented

（事实来源：提交 `29b03ec` 的 diff 与提交说明）

删除 10 个旧基线文件：

- `.aiignore.md`、`.env.example`
- `.github/ISSUE_TEMPLATE/config.yml`、`.github/ISSUE_TEMPLATE/implementation.yml`
- `.github/dependabot.yml`
- `.lingma/rules/issue-start.md`
- `docs/audits/2026-08-06-repository-baseline.md`
- `specs/0001-repository-bootstrap/STATE.md`、`requirements.md`、`tasks.md`

重写：

- `docs/PRD.md`：v3.3 → v5.0 Reboot Baseline（冻结 MVP 范围与 Phase 0–6 路线）
- `AGENTS.md`：约 300 行企业式规范 → 约 100 行"项目地图"（冻结架构、开发行为、Git 安全）
- `README.md`：极简版，如实标注"尚无应用代码 / 命令未实现"
- `.github/PULL_REQUEST_TEMPLATE.md`：精简为 5 节
- `.github/workflows/repository-checks.yml`：检查收敛为三项（必备文档、敏感文件、冲突标记）

新建：

- `docs/ARCHITECTURE.md`：面向初学者的架构解释（全景图、组件职责与边界、关键数据流、硬性边界）
- `docs/PROJECT_STATE.md`：当前阶段、已实现/未实现清单、下一里程碑

## Key user ↔ AI dialogue

Not recorded（该次会话的逐字对话没有保存下来）。

可以从任务记录确认的核心指令摘要（非逐字原文）：

> 执行 LumiRSS Project Reboot：把 main 分支收敛为最小、清晰、可继续开发的新基线；删除旧 Repository Bootstrap 内容，简化文档结构；用户手动更新的 PRD v5.0 必须保留。

其余对话细节不可复原，不做推测性补写。

## Commands actually executed

（命令清单来自该次会话记录；无法逐字复原的以等价形式列出）

开工只读检查：

```bash
git status --short
git branch -a
git log --oneline --decorate --graph --all -n 30
git diff --stat
```

分支与删除：

```bash
git checkout -b chore/project-reboot   # 自 abef74d 创建
git rm <10 个旧基线文件>                # 删除清单见上文 What was implemented
```

完成验证：

```bash
git status --short
git diff --stat
git diff --check
find . -type f -not -path './.git/*' | sort   # 目录树核对
git grep -n '<旧文件名/旧目录名>'               # 残留扫描（零命中）
python3 -c 'import yaml; yaml.safe_load(open(".github/workflows/repository-checks.yml"))'
```

CI 三步检查（必备文档 / 敏感文件 / 冲突标记）在本地逐条人工模拟执行，全部通过。

## Problems encountered

1. 旧 PRD v3.3 与大量脚手架文档（audits、issue templates、dependabot、.lingma 规则）和 v5.0 的极简方向冲突，保留它们会造成"两个真源"。
2. 工作区里有用户手动更新的 PRD v5.0（未提交），任何重置或覆盖操作都可能毁掉它。
3. 大规模删除前必须确认旧内容真的能从 Git 历史找回。

## How problems were solved

1. 先只读盘点全部现状，再一次性删除；删除清单逐文件列在提交里。
2. 确认 `archive/pre-wsl-reset`（本地与远程均在，指向 `abef74d`）之后才动手；用户 PRD 修改全程未被触碰，随 Reboot 改动一起进入提交。
3. CI 工作流删掉对旧文件的硬编码依赖，改为检查新基线的必备文档。

## Acceptance evidence

- 最终目录结构与目标一致：`README.md`、`AGENTS.md`、`docs/{PRD,ARCHITECTURE,PROJECT_STATE}.md`、`.github/` 基础保护。
- `docs/PRD.md` 确认为 v5.0 Reboot Baseline。
- `git grep` 旧文件名/目录名零残留。
- `git diff --check` 干净（无空白错误）。
- CI 三步本地模拟全部通过；workflow YAML 语法有效。
- PR #4 合入 main（`dfe3299`）。

## What I learned

- "聊天记录不是项目知识库，Git 仓库才是"——PRD v5.0 §2 把这条写成了原则，它本身就是这次 Reboot 的教训。
- 大规模删除并不可怕：先确认备份分支存在，删错了随时能找回。
- 文档体系的复杂度本身就是维护负担；"最小、够用"比"完备"更重要。

## Remaining questions

- 旧 `.aiignore.md` 的 `*secret*` 模式与 `.env.example` 的变量命名没有迁移：当时判断 PRD v5.0 已覆盖安全要求；CI 中已注释说明 `.env.example` 允许在将来真实的配置设计中恢复。

## Next milestone

0001 — FreshRSS Development Environment（Phase 1 — RSS Foundation）。
