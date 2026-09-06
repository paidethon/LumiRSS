# LumiRSS Design System

> 长期视觉与交互规则（源于 0009 UI Reboot 规格，2026-08-28 用户批准；
> 现为设计权威文档）。历史过程见
> [milestones/0009-ui-reboot-reference-lab.md](../milestones/0009-ui-reboot-reference-lab.md)；
> 阅读器定制研究依据见 [reader-research.md](reader-research.md)。
> 本文描述视觉/交互规则与目标状态；实现细节以源码为准。

---

## 1. Design objective

LumiRSS 的界面必须让人感觉：

```text
quiet
precise
content-first
native-like
soft but not decorative
dense but not crowded
recognizably Lumi
```

目标公式：

```text
Folo structure and interaction
+ OrigRead Desktop settings and reader tools
+ muted palette from the user's color reference
+ Lumi pale blue-indigo identity
```

不是目标：

- a Folo clone;
- a generic AI dashboard;
- a card-heavy SaaS interface;
- a purple OrigRead reskin;
- a desktop layout shrunk onto a phone.

---

## 2. Reference hierarchy

### Primary — Folo

Study: desktop three-pane shell; compact Sidebar; continuous Timeline;
feed/source metadata hierarchy; selected/hover/read/unread states; Reader
title/body hierarchy; toolbar icon treatment; light/dark surface layering;
popover/menu/tooltip details; restrained motion.

### Secondary — OrigRead Desktop

Study: Settings navigation and grouped rows; source discovery UX; reader
appearance controls; resizable panes; dialogs and source switchers.

### Supporting references

- FeedFlow: modern cross-platform timeline and reading modes;
- NetNewsWire: native split-view, keyboard and pane behavior;
- Read You: Material You mobile list/detail adaptation;
- Fluent Reader: desktop settings/grouping/dark-mode patterns;
- NewsFlash: adaptive GNOME reader behavior;
- Readeck: read-later/web-clipping concepts only.

### User palette reference

用户提供的参考图是**配色参考**：warm gray/rose-neutral canvas；muted
blue/green/orange/purple/cyan/rose/red；translucent low-saturation
selected rows；不复制布局。

---

## 3. Product-level UX rules

1. Reading content has the highest visual priority.
2. Sidebar and Timeline are continuous surfaces, not stacks of cards.
3. A card is used only when information has real semantic containment,
   such as AI Summary or a Settings group.
4. Accent color is scarce and meaningful.
5. Selected state normally uses a subtle neutral or tinted surface,
   not a saturated button.
6. Borders are separators, not decoration.
7. Shadows communicate elevation only: popover, dialog, floating panel.
8. AI is available but never visually dominates normal reading.
9. Every desktop behavior has a deliberate tablet/mobile expression.
10. Theme/custom color support is architectural, not a late CSS patch.

---

## 4. Default theme — Lumi Mist / 雾光

### 4.1 Light palette

```css
:root,
[data-theme="lumi-mist-light"] {
  --lumi-canvas: #f6f4f4;
  --lumi-sidebar: #f1eeee;
  --lumi-surface: #fbfafa;
  --lumi-surface-elevated: #ffffff;
  --lumi-reader: #fcfbfb;

  --lumi-surface-hover: #efeced;
  --lumi-surface-selected: #e7e5e9;
  --lumi-surface-pressed: #dfdde2;

  --lumi-text-primary: #29282c;
  --lumi-text-secondary: #77747b;
  --lumi-text-tertiary: #9b979f;
  --lumi-text-disabled: #bbb7be;

  --lumi-border: rgba(52, 47, 57, 0.10);
  --lumi-separator: rgba(52, 47, 57, 0.075);

  --lumi-accent: #6d78e8;
  --lumi-accent-hover: #616cd8;
  --lumi-accent-pressed: #5660c8;
  --lumi-accent-soft: #eceeff;
  --lumi-accent-contrast: #ffffff;
  --lumi-focus-ring: rgba(109, 120, 232, 0.38);
}
```

### 4.2 Dark palette

```css
[data-theme="lumi-mist-dark"] {
  --lumi-canvas: #18181a;
  --lumi-sidebar: #1d1d20;
  --lumi-surface: #222226;
  --lumi-surface-elevated: #28282d;
  --lumi-reader: #1b1b1e;

  --lumi-surface-hover: #29292d;
  --lumi-surface-selected: #303036;
  --lumi-surface-pressed: #38383f;

  --lumi-text-primary: #ececef;
  --lumi-text-secondary: #aaa8b0;
  --lumi-text-tertiary: #77757d;
  --lumi-text-disabled: #5f5d64;

  --lumi-border: rgba(255, 255, 255, 0.10);
  --lumi-separator: rgba(255, 255, 255, 0.07);

  --lumi-accent: #8993f5;
  --lumi-accent-hover: #98a1ff;
  --lumi-accent-pressed: #7782e6;
  --lumi-accent-soft: rgba(137, 147, 245, 0.14);
  --lumi-accent-contrast: #15151a;
  --lumi-focus-ring: rgba(137, 147, 245, 0.48);
}
```

### 4.3 Category palette

```css
--lumi-category-blue: #79a9d6;
--lumi-category-green: #76a08b;
--lumi-category-orange: #c98d59;
--lumi-category-purple: #8b79b8;
--lumi-category-cyan: #6f9fae;
--lumi-category-rose: #b87d91;
--lumi-category-red: #b8656b;
```

Usage: small icons/dots; category labels; 6–12% tinted selected/hover
surfaces; never a full rainbow dashboard.

---

## 5. Theme model

### 5.1 App appearance（已实现）

```text
Mode      system / light / dark（themeMode）
Palette   Lumi Mist（默认）
Accent    Lumi Indigo 默认；AccentColorPicker 自定义取色，
          hover/pressed/soft/focus 派生色自动生成并做对比度校验
字号      uiFontSize 15/16/18/20
界面字体  uiFontStack
动效      reduceMotion 尊重系统偏好
```

### 5.2 Reader appearance（已实现，独立于 App 外观）

```text
排版       五个连续滑杆：字号 / 行距 / 段距 / 内容宽度 / 页边距（即时生效）
预设       内置排版预设（默认 Lumi Mist、纸感 Reeder、期刊衬线、
           AMOLED 真黑、高对比）+ 派生自定义预设
背景       Reader 独立背景（跟随/纸白/暖白/sepia/柔绿/自定义）
主题包     .lumitheme 导入导出分享（schema v1，白名单字段）
字体       自定义字体（WOFF2 导入 IndexedDB 或 URL 模式）
中文排版   首行缩进 / 标点悬挂（实验） / OpenCC 简繁转换（仅展示层）
内容元素   图片三模式（含灰度）、代码高亮（Shiki，主题白名单）、
           阅读时长、bionic 强调（实验）
自定义 CSS 自动加 .lumi-reader 前缀，仅作用正文
```

### 5.3 Persistence

- 客户端唯一真源是 `useAppSettings`（localStorage 本地优先，改动即时
  生效）；
- 便携键经 debounce 同步到服务端 `/api/v1/settings`（`app.settings`
  JSON 文档，跨设备）；布局宽度、自定义字体、过滤规则等设备本地键
  永不上传；
- secrets 永不进入设置存储。架构细节见
  [architecture/README.md](../architecture/README.md) §9。

---

## 6. Typography

Start from a reliable system sans stack. Do not bundle proprietary fonts.

| Token | Size | Line height | Use |
|---|---:|---:|---|
| `text-xs` | 11–12 | 16 | timestamps, source metadata |
| `text-sm` | 13 | 18 | Sidebar, controls, secondary text |
| `text-md` | 14–15 | 20 | Timeline title/body UI |
| `text-lg` | 17–18 | 26 | Reader body base |
| `heading-sm` | 20–22 | 28 | pane/page heading |
| `heading-lg` | 32–38 | 1.15–1.25 | Reader title desktop |
| `heading-mobile` | 26–30 | 1.2 | Reader title mobile |

Rules:

- avoid excessive bold weights; titles can use 600–700;
- metadata should be visually quiet without becoming unreadable;
- article body line-height target around 1.7–1.8;
- long Chinese and English titles must wrap gracefully.

---

## 7. Spacing, radii and elevation

### 7.1 Spacing scale

```text
2 / 4 / 6 / 8 / 10 / 12 / 16 / 20 / 24 / 32 / 40 / 48
```

### 7.2 Radius scale

```text
4px   tiny badge/detail
6px   thumbnail/small control
8px   nav item/button/icon button
10px  input/select/menu/popover item group
12px  settings group/dialog body
14px  AI summary/large content card
16px  floating panel/major overlay
999px true pill/switch only
```

Do not use one radius everywhere.

### 7.3 Elevation

```text
flat surfaces       no shadow
popover/menu        soft small shadow
modal/dialog        medium diffuse shadow
floating panel      medium large diffuse shadow
```

Selected Timeline/Sidebar rows should not float.

---

## 8. Motion

```text
hover/focus feedback       100–120ms
menu/popover               120–160ms
modal                      160–180ms
sidebar/pane transition    180–220ms
bottom sheet               200–260ms
```

Use CSS transitions for simple micro-interactions; motion libraries only
after dependency review.

Allowed: opacity; 1–3px translate; subtle scale 0.98→1 for overlays;
width/pane transitions without content jitter.

Avoid: list row lift/scale; bounce; glow; decorative continuous
animation; motion that ignores `prefers-reduced-motion`.

---

## 9. Desktop App Shell

### 9.1 Layout

```text
Sidebar: 220–260px（可折叠/可调宽）
Timeline: 360–440px（可调宽/可折叠）
Reader:  minmax(0, 1fr)
```

Use CSS Grid or an equivalent resilient layout; the Reader must keep
`min-width: 0` to prevent overflow. Pane widths/collapse state persist
as device-local settings.

### 9.2 Pane hierarchy

```text
Sidebar background
  < Timeline surface
  < Reader surface/content
  < Popover/dialog elevation
```

Separate panes with subtle 1px separators, not boxed cards.

---

## 10. Sidebar

### 10.1 Structure

```text
Brand / compact actions
Primary views
  All / Unread / Starred
Subscriptions
  folders/categories
  feeds
Bottom utility
  Add source
  Settings
```

Do not copy Folo-specific content-type/community navigation unless it
maps to an approved Lumi feature.

### 10.2 Dimensions and states

```text
item height       34–36px desktop
icon              17–18px
row radius        8px
section label     11–12px
```

- default: transparent; hover: subtle neutral surface;
- selected: subtle neutral/tinted surface; focus: visible ring;
- unread counts: tertiary text or small badge;
- category color: icon/dot and soft tint only;
- expanded folder: clear chevron + accessible disclosure semantics;
- 已读条目变暗（`dimRead`）可配置；未读圆点是固定视觉语义
  （状态不只靠颜色），无开关。

### 10.3 Mobile

The same navigation content appears in a Drawer, not a second duplicate
implementation. Focus must be trapped and restored; swipe behavior is
optional, not required.

---

## 11. Timeline

### 11.1 Continuous list

Do not render each entry as a floating card. Use one continuous pane
with selected/hover surfaces and optional separators.

### 11.2 Information hierarchy

```text
[favicon] Source · time                       [optional thumbnail]
          Article title
          Short excerpt / metadata
```

Fallbacks: no favicon → generated neutral mark; no excerpt → omit
cleanly; no thumbnail → text layout expands; no author → no empty
separators; long source/title → clamp/wrap per viewport.

### 11.3 Density and states

- Target row height ≈ 82–112px comfortable desktop; never a single
  fixed height that clips multilingual titles;
- 未读标记：title weight + 固定小圆点（不只靠颜色）；星标为次要状态，
  不压过标题；`groupByDate` 按日期分组、`unreadOnly` 启动仅未读可配；
- Selected state: quiet neutral/tinted surface, no thick borders;
- Hover-revealed actions must also be keyboard reachable and available
  through a more menu; mobile must not depend on hover.

---

## 12. Reader

### 12.1 Content layout

```text
Reader toolbar
article metadata
article title
optional AI summary
article content（原文/译文切换）
```

### 12.2 Width and rhythm

```text
normal content width: 560–1080px 连续可调（默认 760px）
body font: 12–28px 连续可调（默认 17px）
body line height: 1.2–2.4 连续可调（默认 1.85）
```

The Reader centers content inside a fluid pane; it should not look like
a giant card. Reader theme is independent from the app theme.

### 12.3 Toolbar

- compact icon buttons; 30–34px visual control size on desktop;
- accessible name/tooltip;
- safe actions: mark read, star, open original, reader settings, AI;
- destructive actions separated and confirmed where applicable.

### 12.4 HTML boundary

Preserve the DOMPurify-based sanctioned HTML boundary. Visual work must
never relax sanitization for prettier embeds. Pipeline detail:
[architecture/README.md](../architecture/README.md) §8.

### 12.5 AI surfaces（已实现：内嵌于 Reader）

- **摘要**：`ReaderSummary` — 标题/元数据之后的轻语义卡片（14px
  radius、subtle border、small accent icon），provider/model/时间/缓存
  状态安静呈现，失败可重试；
- **翻译**：`ReaderTranslation` — 原文/译文分段切换；译文为纯文本
  渲染（绝不进 HTML 路径），带「缓存」徽标区分缓存命中与新生成；
- **对话**：`ArticleConversation` — 当前文章上下文对话，共享同一
  chat purpose 配置。

AI 未配置时各能力诚实呈现引导，而不是假装可用。

---

## 13. Settings shell

### 13.1 Structure

```text
Settings modal（桌面）/ 全屏页（移动）
├── left navigation（桌面）/ 分类列表（移动）
└── content
    ├── page title/description
    └── grouped settings sections
```

当前分类（与实现一致的 13 个）：

```text
通用 · 外观 · 阅读 · 快捷键 · 翻译 · 文章过滤 · RSSHub
订阅与来源 · AI · 数据控制（含备份/恢复/WebDAV） · 账户与服务
工作区（占位，诚实标注） · 关于（含版本溯源）
```

### 13.2 Setting group

- one 12px-radius group; subtle border; no ordinary shadow;
- internal separators; row 56–68px depending on description;
- label + explanatory text left; control right; mobile stacks when needed.

### 13.3 Honesty rules

- 未实现的能力标注占位（如工作区），不做假控件；
- secret 输入只写不回显；需要重启生效的配置明确展示
  （如 RSSHub「重启后生效」）；
- 上游 UI（FreshRSS/RSSHub）入口保留为高级逃生通道。

---

## 14. Menus, popovers and micro-details

- 6–8px outer padding; row height around 36–40px; 7–8px row radius;
- selected state neutral rather than saturated;
- secondary values aligned right and lower contrast;
- separators only between semantic groups;
- one shadow on the popover, no row shadows;
- footer action separated cleanly.

Every menu/select/feed chooser shares the same primitive.

---

## 15. Responsive design

| Viewport | Navigation | Timeline/Reader |
|---|---|---|
| ≥1440 | fixed sidebar | 三栏，Reader 宽裕 |
| 1200–1439 | compact sidebar | 三栏（紧凑） |
| 1024–1199 | collapsible sidebar | Timeline + Reader 为主 |
| 768–1023 | drawer | list/detail |
| <768 | mobile navigation | 单栏列表 ↔ 全屏 Reader |

- Breakpoints are behavioral guides, not permission for hard-coded
  device assumptions; container queries may be considered where useful;
- Mobile timeline: compact source/time row; title wraps 2–3 lines;
  thumbnail on right when available; swipe actions optional and must
  have button alternatives;
- Mobile reader: title 26–30px; controls reachable; sticky toolbar only
  if it does not obscure content; safe-area insets honored;
- 无异常横向滚动；图片、表格、代码、长链接不撑破页面。

---

## 16. Accessibility

Mandatory:

- all icon buttons have labels;
- keyboard selection can move through navigation/list safely;
- focus ring is visible in every theme;
- dialogs/drawers/sheets trap focus; focus returns to the trigger on close;
- `Escape` closes overlays;
- selected/unread state has non-color cues;
- minimum contrast is checked;
- reduced motion is honored;
- primary mobile targets are around 44px;
- Reader headings/links/lists retain semantic structure;
- loading states use accessible status where helpful.

---

## 17. Standing prohibitions

- 不重设计 FastAPI 契约来做视觉改动；
- 不给 BFF 增加 Docker socket 或任意容器控制；
- 不复制 Folo `icons/mgc`；不整段粘贴上游 CSS/组件树；
- 不引入未批准的重型 UI 框架；
- 不把未实现的设置控件标为可用；
- 不提交含私密订阅/凭据的截图；
- 不在没有测量证据时声称像素级对齐。

---

## 18. Visual verification

UI 改动至少覆盖以下视口（明暗两主题）：

```text
1920 × 1080   1440 × 900   1024 × 768
820 × 1180 (tablet portrait)   390 × 844 (mobile)
```

必须检查的状态：loading / empty / error / selected / unread-read /
starred / 长标题 / 无图 / 键盘导航 / 移动 drawer 与 list→reader 返回流。

命令与 CI 视角见 [development/testing.md](../development/testing.md)。

### Behavior regression guard

- Feeds/filters/pagination 经 BFF 正常工作；
- 打开文章不标已读；显式 read/star 正常；
- 查询失效反映 FreshRSS 状态；原文链接校验保持安全；
- HTML sanitization 测试保持绿色；
- PWA manifest 保持有效。
