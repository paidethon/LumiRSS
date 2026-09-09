# LumiRSS Documentation

> Single entry point for humans and AI agents working on LumiRSS.

---

## Current state

**Last completed milestone**: 0020 — MVP Release Remediation
→ [milestones/0020-release-remediation.md](milestones/0020-release-remediation.md)

**Post-0020 maintenance** (2026-09-05, merged via PR #28, no milestone number):
settings control-plane rework — AI profiles with purpose mapping,
「备份与恢复」merged into「数据控制」, honest RSSHub control chain,
version provenance.

**Active milestone**: —（0021 Security & Operations Hardening 的候选范围已由
维护分支实施，见下方任务分支；里程碑编号仍空闲，是否立项由用户决定）

**Active task branch** (PR-ready, awaiting review):
`chore/postmerge-reality-security-hardening-20260908`
→ post-merge 真实运行闭环（备份/恢复、Docker 代理根因、真实 LibreTranslate、
Chrome Translator 真机、flaky 根治）+ 0021 安全与运维硬化（内部 token、
CSP/HSTS、请求体上限、限流、设置冲突语义），2026-09-09。
Status / evidence: [tasks/postmerge-reality-security-hardening/STATE.md](tasks/postmerge-reality-security-hardening/STATE.md)
· [VALIDATION.md](tasks/postmerge-reality-security-hardening/VALIDATION.md)

**Next candidate**: 0021 — Security & Operations Hardening（编号尚未占用）
→ scope and priority: [ROADMAP.md](ROADMAP.md)

---

## Documentation map

| Topic | Entry point |
|---|---|
| **Product definition (WHAT/WHY)** | [product/PRD.md](product/PRD.md) |
| **System architecture (HOW)** | [architecture/README.md](architecture/README.md) |
| **Build vs Reuse boundaries** | [architecture/reuse-policy.md](architecture/reuse-policy.md) |
| **Architecture decisions** | [architecture/decisions/](architecture/decisions/) |
| **Design system & research** | [design/](design/) |
| **Development / testing / operations** | [development/](development/) |
| **Roadmap** | [ROADMAP.md](ROADMAP.md) |
| **Milestone history** | [milestones/](milestones/) |
| **Upstream & licensing** | [upstream/](upstream/) |

### Need → read

| 你要做什么 | 读什么 |
|---|---|
| 了解产品范围与原则 | [product/PRD.md](product/PRD.md) |
| 改数据路径 / API / 边界 | [architecture/README.md](architecture/README.md)（+ 相关 ADR） |
| 改 API 契约 / settings / 生成物 | [architecture/reuse-policy.md](architecture/reuse-policy.md)（再生成 + drift 检查） |
| 部署 / 升级 / 备份恢复 | [development/operations.md](development/operations.md) |
| 搭建本地环境 | [development/setup.md](development/setup.md) |
| 跑测试 | [development/testing.md](development/testing.md) |
| 改 UI / 视觉与交互 | [design/design-system.md](design/design-system.md) |
| 查历史回归 / 决策过程 | [milestones/](milestones/) |
| 许可证 / 上游引用 | [upstream/](upstream/) |

---

## Reading paths

### Normal feature task

1. This file (`docs/README.md`);
2. Active milestone document (if any);
3. Directly affected source files and tests;
4. Architecture docs only when touching data paths or boundaries.

### Architecture task

1. [architecture/README.md](architecture/README.md);
2. Relevant ADR in [architecture/decisions/](architecture/decisions/);
3. Source and tests.

### Design task

1. [design/design-system.md](design/design-system.md);
2. [design/reader-research.md](design/reader-research.md) if relevant.

### Historical debugging

1. Relevant milestone in [milestones/](milestones/);
2. `git log` / `git blame`;
3. Source and tests.

### Do NOT preload for ordinary work

- Completed milestones (unless debugging a regression);
- Full PRD (unless product scope is unclear);
- Upstream studies (unless working on licensing);
- Reference repositories.

---

## Milestones

Completed milestones are archived in [milestones/](milestones/); release
history in [milestones/RELEASE-NOTES-MVP.md](milestones/RELEASE-NOTES-MVP.md).
The table below is the complete historical index for quick lookup — do not
preload these files during normal development.

| Milestone | Title | Status |
|---|---|---|
| 0000 | Project Reboot | Completed |
| 0001 | FreshRSS Development Environment | Completed |
| 0002 | BFF & FreshRSS Adapter | Completed |
| 0003 | Entry Read Path | Completed |
| 0004 | Entry State, Filters & Pagination | Completed |
| 0005 | Web Shell | Completed |
| 0006 | Reader | Completed |
| 0007 | Mobile & PWA | Completed |
| 0008 | RSSHub Source Expansion | Completed |
| 0009 | UI Reboot & Reference Lab | Completed |
| 0010 | Settings Center & Adaptive Shell (+0010a) | Completed |
| 0011 | Mobile UI Five-Screen Alignment | Completed |
| 0012 | Reader Style Deep Customization | Completed |
| 0013 | Unified Subscription Center | Completed |
| 0014 | Source Discovery & RSSHub | Completed |
| 0014a | UI Acceptance & Navigation Consistency | Completed |
| 0015 | AI Foundation, Summary & Lumi SQLite Foundation | Completed |
| 0016 | Translation & AI Conversation | Completed |
| 0017 | Reader Power UX & Unified Settings | Completed |
| 0018 | Production, Operations & Backup | Completed |
| 0019 | MVP Stabilization & Release | Completed |
| 0020 | MVP Release Remediation | Completed |
| — | Post-0020 settings control-plane maintenance | Completed (no number) |
