# Third-Party Notices

> This file must be kept current with the exact dependencies, images and
> source-derived files included in the repository/distribution. It is not a
> substitute for the root project license (AGPL-3.0-only) or upstream
> license texts.

---

## Project license

LumiRSS is licensed under AGPL-3.0-only (see `LICENSE`).

---

## Runtime services

### FreshRSS

```text
Project: FreshRSS
Version/image: freshrss/freshrss:1.29.1 (official image, unmodified)
License: AGPL-3.0 (upstream project)
Source: https://github.com/FreshRSS/FreshRSS
Modifications: none (used as a separate Docker service)
Distribution method: not redistributed; run as a service
Required notice/source offer: source offer obligations reviewed at
  distribution time (currently none — service usage only)
```

### RSSHub

```text
Project: RSSHub
Version/image: diygod/rsshub@sha256:387fd32ee2d8789154dcf6446a52365976e768d9ede1a7c1e610cf4da9d89fbc
License: AGPL-3.0 (upstream project)
Source: https://github.com/DIYgod/RSSHub
Modifications: none (used as a separate Docker service)
Distribution method: not redistributed; run as a service
Required notice/source offer: source offer obligations reviewed at
  distribution time (currently none — service usage only)
```

---

## Source-derived UI work

Complete from `docs/upstream/SOURCE_MAP.md`.

### Folo

```text
Pinned reference commit: 78f6bd1b745ba5d85027f6ca85ce60b06ca46569 (dev)
Files/components adapted: none yet (0009 Gate 0 — research only)
Classification: inspired (measurements and behavior study)
License: AGPL-3.0 with special icons/mgc redistribution exception
Copyright notices retained: n/a (no code adapted yet)
Special restriction reviewed: icons/mgc content must not be redistributed
```

### OrigRead Desktop

```text
Pinned reference commit: 8b59bcb4ec63c4514e06e3863b1bc527eed861dd (main)
Files/components adapted: none yet (0009 Gate 0 — research only)
Classification: inspired
License: AGPL-3.0-only
Copyright notices retained: n/a (no code adapted yet)
```

### OrigRead Android

```text
Pinned reference commit: 18d3281de241fabc22c94d4cacb965ec1eaa1430 (main)
Files/components adapted: none yet (0009 Gate 0 — research only)
Classification: inspired
License: GPL-3.0
Copyright notices retained: n/a (no code adapted yet)
```

---

## Frontend dependencies

Generate a complete dependency-license report from the locked dependency graph before release. Include new icon/UI/motion packages added during 0009.

| Package | Version | License | Use | Notice required |
|---|---|---|---|---|
| react / react-dom | 19.2.x | MIT | UI framework | no |
| @tanstack/react-query | 5.102.x | MIT | server state | no |
| zustand | 5.0.x | MIT | UI state | no |
| dompurify | 3.4.x | Apache-2.0 / MPL-2.0 dual | HTML sanitization | review at distribution time |
| lucide-react | 1.34.x | ISC | icon library (added 0009 Gate 1, user-approved) | no |
| opencc-js | 1.4.2 | MIT AND Apache-2.0 | 简繁转换词典（0012，dynamic import，含 OpenCC 词典数据） | review at distribution time（词典内容源自 OpenCC 项目） |
| shiki | 4.4.3 | MIT | 代码语法高亮（0012，fine-grained dynamic import；含 TextMate 语法与主题数据） | review at distribution time（grammar/theme 数据源自各自上游） |

---

## Backend dependencies

Generate from `uv.lock` / installed metadata.

| Package | Version | License | Use | Notice required |
|---|---|---|---|---|
| fastapi | >=0.115 | MIT | web framework | no |
| httpx | >=0.27 | BSD-3-Clause | upstream HTTP client | no |
| pydantic-settings | >=2.0 | MIT | typed config | no |
| uvicorn | >=0.30 | BSD-3-Clause | ASGI server | no |
| defusedxml | >=0.7 | PSF-2.0 | XML 解析（0018 WebDAV PROPFIND，defusedxml） | no |

### Web dev dependencies（不进入运行时/发布物）

| Package | Version | License | Use | Notice required |
|---|---|---|---|---|
| @playwright/test | 1.62.x | Apache-2.0 | E2E 测试（0019，dev only） | no |
| @axe-core/playwright | 4.13.x | MIT | 可访问性扫描（0019，dev only） | no |

---

## Assets

| Asset | Origin | License/permission | Modifications | Distribution allowed |
|---|---|---|---|---|
| Lumi branding | Lumi-owned | project license | | yes |
| Reference screenshots | internal design research | verify before public redistribution | none/crops | not automatically |

Do not list or include Folo `icons/mgc` as a redistributable Lumi asset.

