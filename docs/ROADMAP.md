# LumiRSS Roadmap

> What comes next, in order.
> Detailed results for each milestone: [milestones/](milestones/)

---

## Foundation

- [x] 0000 — Project Reboot
- [x] 0001 — FreshRSS Development Environment
- [x] 0002 — BFF & FreshRSS Adapter
- [x] 0003 — Entry Read Path
- [x] 0004 — Entry State, Filters & Pagination
- [x] 0005 — Web Shell
- [x] 0006 — Reader
- [x] 0007 — Mobile & PWA
- [x] 0008 — RSSHub Source Expansion

## Experience

- [x] [0009 — UI Reboot & Reference Lab](milestones/0009-ui-reboot-reference-lab.md)
- [x] [0010 — Settings Center & Adaptive Shell (+0010a)](milestones/0010-settings-center-adaptive-shell.md)
- [x] [0011 — Mobile UI Five-Screen Alignment](milestones/0011-mobile-ui-five-screen-alignment.md)
- [x] [0012 — Reader Style Deep Customization](milestones/0012-reader-style-deep-customization.md)

## Source Control

- [x] [0013 — Unified Subscription Center](milestones/0013-unified-subscription-center.md)
- [x] [0014 — Source Discovery & RSSHub Integration](milestones/0014-source-discovery-rsshub-integration.md)
- [x] [0014a — UI Acceptance & Navigation Consistency](milestones/0014a-ui-acceptance-navigation.md)
- 0014a 是 0014 的 post-implementation 验收 follow-up：关闭真实浏览器
  验收缺口（桌面添加来源入口 / 移动收藏 → 全屏 Reader / 设置 stale
  标签 / Playwright 验收），不重排已完成的编号。

## Intelligence

- [ ] 0015 — AI Foundation, Summary & Lumi SQLite Foundation
- [ ] 0016 — Translation & AI Conversation

## Completion

- [ ] 0017 — Reader Power UX & Unified Settings
- [ ] 0018 — Production, Operations & Backup
- [ ] 0019 — MVP Stabilization & Release

## Phase 2 — Knowledge Workbench (deferred)

Web clipping, structured JSON/API sources, email newsletters, Obsidian library
connector, unified source registry, agent workspace.

---

## Roadmap notes

**0011 renumbering** (2026-08-30): Original 0011 (Reader Style) was replaced
by Mobile UI Navigation; 0012–0019 shifted accordingly. AI Summary (originally
0009) is now 0015.

**0014a insertion + 0015–0019 content revision** (2026-09-02): After 0014,
a real-product acceptance pass found UI gaps; 0014a inserted as a suffix
milestone (historical numbering preserved). 0015–0019 revised per
user-approved decisions:

- 0015 activates **lumi.sqlite** as Lumi-owned application truth
  (FreshRSS remains the RSS-domain source of truth; no shadow copies);
- 0017 **Reader Power UX** requires continuous bounded controls
  (font size / line height / paragraph spacing / content width /
  horizontal margins), not only discrete presets;
- 0018 **Production, Operations & Backup** includes a schema-driven
  **RSSHub Control Center**, FreshRSS operations integration and
  **WebDAV backup/restore**.

**0011a Basic Global Search**: candidate milestone, requires user-approved BFF
search contract. Until then the search page stays honest-empty.

**Rejected for MVP**: Folo product clone, community/social, algorithmic
recommendation, multi-user platform, arbitrary Docker admin from BFF,
duplicating FreshRSS RSS database in SQLite, native mobile app.
