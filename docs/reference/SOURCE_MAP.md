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
