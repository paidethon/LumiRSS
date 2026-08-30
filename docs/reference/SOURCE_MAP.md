# LumiRSS Upstream Source Map

> Record every material upstream influence before merge. Visual
> inspiration and source-derived code are not the same category.
>
> Status: after 0009 implementation — all realized upstream influences are
> **inspired-level** (measurements/architecture study; zero lines of Folo or
> OrigRead source copied or adapted). Every entry below is traceable to the
> pinned SHA. `rewritten`/`adapted`/`copied` remain unused.

---

## 1. Classification

| Classification | Meaning | License action |
|---|---|---|
| `inspired` | behavior/visual concept observed; implementation not based on source text | cite reference in design docs when material |
| `rewritten` | source studied, then independently implemented in Lumi's architecture | record source path/SHA; review similarity |
| `adapted` | implementation is derived from upstream source with meaningful edits | license compatibility and attribution required |
| `copied` | source is substantially copied | explicit license/notice/per-file review required |
| `asset` | icon/image/font/text copied or transformed | asset license and redistribution review required |

When uncertain, choose the more conservative classification.

---

## 2. Source map table

| Lumi area/file | Upstream project | Upstream SHA | Upstream path/screen | Classification | What was taken | Changes made | License/notice action | Reviewer/status |
|---|---|---|---|---|---|---|---|---|
| `docs/reference/UPSTREAMS.md` §7 | Folo (live web app) | `78f6bd1b` | desktop Sidebar/Timeline/Reader, dark+light | inspired | layout dimensions, states, semantic token architecture (measured, not copied) | translated into measurement notes | design attribution only | Gate 0, recorded |
| `apps/web/src/styles/themes.css` | Folo | `78f6bd1b` | `--fo-*` theme variables / `html[data-theme]` mechanism | inspired | theme variable architecture + oklab-translucency selection idea (values are Lumi's own palette) | independent implementation, Lumi Mist colors | design attribution only | Gate 1–4, recorded |
| `apps/web/src/components/Sidebar.tsx` | Folo | `78f6bd1b` | sidebar nav rows (measured 32px/6px-radius/14px/500) | inspired | row density & three-state patterns | Lumi tokens/icons/category dots | design attribution only | Gate 2, recorded |
| `apps/web/src/components/EntryRow.tsx` | Folo | `78f6bd1b` | timeline item composition (measured two-level hierarchy) | inspired | source-line + title hierarchy, weight-based read state | Lumi fields/API (no excerpt/favicon/thumbnail — graceful degradation) | design attribution only | Gate 2, recorded |
| `apps/web/src/components/Reader*.tsx` | Folo | `78f6bd1b` | reader headline 27.2px/700, toolbar 32×32 buttons | inspired | hierarchy & toolbar proportions | Lumi IconButton primitive + 46rem width | design attribution only | Gate 3, recorded |
| scrollbar styles (`styles/tokens.css`) | Folo | `78f6bd1b` | 6px thumb pattern | inspired | slim-thumb scrollbar pattern | token colors (dual theme) | design attribution only | Gate 4, recorded |
| `components/settings/SettingItem.tsx` | Folo | `78f6bd1b` | `helper/setting-builder.tsx` declarative item model | inspired | declarative row types (title/toggle/select/action→control mapping) | Lumi primitives + tokens; independent implementation | design attribution only | 0010 Gate A, recorded |
| `components/settings/SettingsModal.tsx` | Folo | `78f6bd1b` | `modal/layout.tsx` (950×800) + live audit §Settings modal measurements | inspired | left-nav + content layout, row/section metrics | Lumi 9 categories (not Folo's 13), token styling | design attribution only | 0010 Gate A, recorded |
| `components/ui/PaneSeparator.tsx` | OrigRead-Desktop | `8b59bcb4` | `shared/settings.ts` pane width constraints; Folo separator aria pattern | inspired | clamp bounds (220–300/360–460) + role=separator semantics | native pointer events (no re-resizable dep) | design attribution only | 0010 Gate C, recorded |
| `components/MobileTabBar.tsx` | Folo | `78f6bd1b` | mobile bottom-tab navigation pattern | inspired | 3-tab bottom nav + hidden-while-reading | Lumi views (timeline/starred/settings) | design attribution only | 0010 Gate D, recorded |
| `components/MobileSettingsScreen.tsx` | Folo mobile | `78f6bd1b` | `apps/mobile` SettingsList/GroupedInsetList + routes/<Category> push 模式 | inspired | full-screen grouped list → push subpages (back button + sticky title), shared data layer | Lumi shared CategoryPage components; web implementation, no RN | design attribution only | 0010a Gate E, recorded |
| `components/settings/AppearanceControls.tsx`（AccentColorPicker） | Folo | `78f6bd1b` | `tabs/appearance` AccentColorSelector | inspired | 8-preset swatches + custom color input → accent CSS vars | Lumi derives hover/pressed/soft by mixing | design attribution only | 0010a Gate F, recorded |
| `components/settings/AppearanceControls.tsx`（ReaderBackgroundPicker/CustomCssEditor） | OrigRead-Desktop | `8b59bcb4` | `SettingsPanel.tsx` GeneralSettings 阅读分组 + `App.tsx` resolveReaderColors/resolveReaderBackground | inspired | 5-preset swatch palette + custom hex + auto-switch; WCAG luminance <0.42 adaptive text (same algorithm & palette values) | Lumi CSS-variable injection via store | design attribution only | 0010a Gate F, recorded |
| `components/settings/AppearanceControls.tsx`（ReaderPresetPicker） | NetNewsWire / TTRSS feedly theme | public repos | `.nnwtheme` theme pack / theme CSS variants | inspired | typography preset = vars snapshot; derive + import/export | Lumi JSON envelope, web-first | design attribution only | 0010a Gate F, recorded |
| `components/settings/TranslationSettingsPage.tsx` | OrigRead-Desktop | `8b59bcb4` | `SettingsPanel.tsx` L419–477 provider-card 模式 + `shared/translation.ts` 字段 | inspired | provider cards (radio default / enable / endpoint / region / secret editor with save-state), ≥1-enabled invariant, endpoint normalization | Lumi providers: microsoft/deepl/dlx only | design attribution only | 0010a Gate F, recorded |
| `components/settings/FilterRulesPage.tsx` | OrigRead | `18d3281` | `ArticleFilterRepository`/`ArticleFilterEngine` + filter settings page | inspired | rule model (keyword/regex, global/feed-scoped, enabled), title-only matching, first-match, dedupe; list CRUD + import/export + stats | Lumi applies display-layer filtering (data source is FreshRSS) | design attribution only | 0010a Gate F, recorded |
| `components/settings/RssHubSettingsPage.tsx` | OrigRead | `18d3281` | `RssHubSettingsRepository` + rsshub settings page | inspired | instance model + 16 built-in public instances (same list), enable/delete/restore-defaults, re-enable-on-re-add | Lumi: connectivity test planned·0013 via BFF proxy | design attribution only | 0010a Gate F, recorded |
| `components/settings/BackupSettingsPage.tsx` | OrigRead | `18d3281` | `ConfigurationBackupService` + configuration-backup crypto | inspired | JSON envelope (schemaVersion/appName), inspect-before-restore, validate-before-mutate, no-secret-restore-keeps-local-keys, PBKDF2+AES-256-GCM encrypted secrets | Lumi uses Web Crypto API (browser-native) | design attribution only | 0010a Gate F, recorded |
| `lib/reader-style.ts`（字体栈/背景色板/文字套） | OrigRead-Desktop | `8b59bcb4` | `shared/reader-font.ts` + `App.tsx` L2774–2804 | inspired | four font stacks (same CSS values), dual-theme background palette values, dark/light text palettes | Lumi independent implementation | design attribution only | 0010a Gate F, recorded |
| general timeline toggles（dimRead/groupByDate 等） | Folo | `78f6bd1b` | `tabs/general.tsx` Timeline 分组 | inspired | dimRead / groupByDate / unreadOnly / scrollMarkUnread 语义 | Lumi IntersectionObserver conservative policy | design attribution only | 0010a Gate E, recorded |
| `components/ReaderAaPanel.tsx` | Readwise Reader / Instapaper（公开 Aa 菜单形态，调研项 #2/#9） | n/a（产品调研，非源码） | Aa 快速阅读样式菜单 | inspired | 桌面 popover / 移动底部 sheet 的快速排版控件组合（字体/字号/行高/宽度/背景/缩进/简繁/图片） | Lumi primitives + useAppSettings 直连（无第二 store） | design attribution only | 0012 Gate 7, recorded |
| `lib/theme-pack.ts`（.lumitheme 信封） | NetNewsWire .nnwtheme（调研项 #6，Web 端无先例） | n/a（产品调研） | 主题包导入/导出/分享 | inspired | 主题包=可分享的阅读配置快照 + parse→validate→preview→confirm→apply 导入流 | Lumi 自有 JSON schema（schemaVersion/appName/type/reader 白名单字段）；兼容 0010a reader-presets | design attribution only | 0012 Gate 6, recorded |
| `lib/article-pipeline.ts`（简繁转换 transform） | Legado 阅读3.0（调研项 #13，简繁转换） | n/a（产品调研） | 展示层简繁转换 | inspired | 简繁转换只作用于展示层、不修改原文数据 | Lumi：OpenCC（opencc-js）TreeWalker text-node transform，位于 DOMPurify 终点之前 | design attribution only（词典数据经 opencc-js 分发，见 THIRD_PARTY_NOTICES） | 0012 Gate 4, recorded |
| `lib/reading-time.ts`（CJK 感知时长） | 无直接上游（调研结论：英文产品均未做好 CJK 时长） | n/a | 阅读时间估算 | inspired | 「中英混排加权」算法思路 | Lumi 独立实现（Han 计数 300 字/分 + Latin 词数 220 词/分，纯函数可测） | none | 0012 Gate 5, recorded |
| `lib/code-highlight.ts`（Shiki 集成） | Shiki 官方文档（fine-grained bundle 模式） | n/a（官方用法） | `createHighlighterCore` + JS regex engine + 按语言/主题 lazy chunk | inspired（官方推荐用法） | fine-grained 加载策略；token→CSS class 映射（适配 Lumi 的 no-inline-style sanitize 策略）为 Lumi 独立实现 | none（MIT） | 0012 Gate 8, recorded |
| future `apps/web/src/components/ui/*` | Folo | `78f6bd1b` | `packages/internal/components/` | `<decide at later gate>` | primitives behavior | Lumi tokens/theme/a11y | `<review before implementation>` | not started (0009 primitives were implemented independently; no Folo component code studied line-by-line) |
| future Settings groups | OrigRead-Desktop | `8b59bcb4` | settings UI (`src/`) | `<decide at 0014>` | grouped settings layout | adapted to Web and Lumi settings | `<review>` | not implemented (0009 SettingsDialog is an independent shell; user's Folo settings screenshots informed the grouped-row layout) |
| future resizable panes | OrigRead-Desktop | `8b59bcb4` | pane interaction | `<decide>` | pane interaction idea | keyboard/a11y/Lumi state | `<review>` | not implemented |

Delete or replace planning rows only when real entries are available; do
not turn examples into false attribution claims.

---

## 3. Required per-entry evidence

For `rewritten`, `adapted`, `copied` or `asset`:

```text
Upstream repository:
Exact commit SHA:
Exact path:
Relevant line range or symbol:
Lumi destination:
Classification rationale:
License identified:
Copyright header/notice needed:
Tests and behavioral differences:
```

For screenshots/UI measurements:

```text
Reference screen/state:
Viewport/theme:
Measured properties:
Private data present? yes/no
Stored in Git? yes/no
```

---

## 4. Prohibited mappings

Do not create entries for:

- Folo `icons/mgc` assets intended for redistribution;
- browser cookies/session/localStorage;
- private subscription/account screenshots;
- copied product copy, branding or mascot assets;
- entire upstream CSS files without a line-by-line reason and license
  review;
- upstream secrets/config files.

---

## 5. Review checklist

Before merging source-derived work:

- [ ] exact upstream SHA is pinned;
- [ ] classification is honest;
- [ ] project license is compatible;
- [ ] notices/headers are present;
- [ ] restricted assets are absent;
- [ ] implementation fits Lumi architecture instead of importing upstream
      coupling;
- [ ] behavior is tested;
- [ ] private reference data is absent;
- [ ] `THIRD_PARTY_NOTICES.md` is updated where required.
