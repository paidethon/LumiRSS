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
| defuddle | 0.19.x | MIT | 网页正文提取（phase2 M2 剪藏，dynamic import，primary） | no |
| @mozilla/readability | 0.6.x | Apache-2.0 | 正文提取降级备选（phase2 M2，dynamic import） | no |
| turndown | 7.2.x | MIT | HTML→Markdown（phase2 M2 剪藏 Markdown 输出，dynamic import） | no |
| sanitize-html | 2.17.x | MIT | 提取后 HTML 白名单净化（phase2 M2） | no |
| cytoscape | 3.x | MIT | 只读关系图谱渲染（phase2 G8，dynamic import，grid 布局/reduced-motion 静止） | no |

---

## Backend dependencies

Generate from `uv.lock` / installed metadata.

| Package | Version | License | Use | Notice required |
|---|---|---|---|---|
| fastapi | >=0.115 | MIT | web framework | no |
| httpx | >=0.27 | BSD-3-Clause | upstream HTTP client | no |
| pydantic-settings | >=2.0 | MIT | typed config | no |
| uvicorn | >=0.30 | BSD-3-Clause | ASGI server | no |
| feedparser | >=6.0.14 | BSD-2-Clause | RSS/Atom 解析（feed 预览/发现） | no |
| defusedxml | >=0.7 | PSF-2.0 | XML 解析（0018 WebDAV PROPFIND，defusedxml） | no |
| ruff | >=0.8 | MIT | Python linter（dev dependency，F/E/W/I/UP/B/SIM） | no |
| jmespath | >=1.1 | MIT | JSON API JMESPath 映射（phase2 M3 API 来源） | no |
| mistune | >=3.3 | MIT | Markdown→HTML（phase2 G6 Obsidian 只读渲染） | no |
| python-frontmatter | >=1.3 | MIT | frontmatter 解析（phase2 G6；依赖 PyYAML BSD） | no |
| PyYAML | 6.x | MIT | frontmatter YAML（python-frontmatter 依赖） | no |
| sqlite-vec | >=0.1.9 | MIT | 向量检索扩展（phase2 G7 RAG，运行时加载） | no |
| fastembed | >=0.7 | MIT | embedding 运行时（phase2 G7 可选 extra `rag`；含 ONNX Runtime MIT 与 BAAI/bge-small-zh-v1.5 权重，模型 MIT，使用 HF 下载+本地缓存） | review at distribution time（随模型分发时需附模型许可） |
| aiosmtpd | >=1.4 | Apache-2.0 | 本地 SMTP 测试 sink（dev dependency only） | no |

### Web dev dependencies（不进入运行时/发布物）

| Package | Version | License | Use | Notice required |
|---|---|---|---|---|
| @playwright/test | 1.62.x | Apache-2.0 | E2E 测试（0019，dev only） | no |
| @axe-core/playwright | 4.13.x | MIT | 可访问性扫描（0019，dev only） | no |
| openapi-typescript | 7.13.x | MIT | OpenAPI → TS 契约生成（dev only，pnpm api:generate） | no |

---

## Assets

| Asset | Origin | License/permission | Modifications | Distribution allowed |
|---|---|---|---|---|
| Lumi branding | Lumi-owned | project license | | yes |
| Reference screenshots | internal design research | verify before public redistribution | none/crops | not automatically |
| 思源黑体 Source Han Sans CN Regular | [adobe-fonts/source-han-sans](https://github.com/adobe-fonts/source-han-sans) tag `2.005R`（SubsetOTF/CN/SourceHanSansCN-Regular.otf） | SIL OFL 1.1（Reserved Font Name “Source Han”；完整许可文本随字体存于 `apps/web/public/fonts/source-han-sans/LICENSE.txt`） | 子集化（见下方分片说明）；仅 400 一档 | yes（OFL 1.1 允许再分发与子集修改，随附许可与声明） |
| 思源宋体 Source Han Serif CN Regular | [adobe-fonts/source-han-serif](https://github.com/adobe-fonts/source-han-serif) tag `2.003R`（SubsetOTF/CN/SourceHanSerifCN-Regular.otf） | SIL OFL 1.1（RFN “Source Han”；`apps/web/public/fonts/source-han-serif/LICENSE.txt`） | 同上分片子集化；仅 400 | yes |
| 霞鹜文楷 LXGW WenKai Regular | [lxgw/LxgwWenKai](https://github.com/lxgw/LxgwWenKai) release `v1.522`（LXGWWenKai-Regular.ttf） | SIL OFL 1.1（`apps/web/public/fonts/lxgw-wenkai/LICENSE.txt`） | 同上分片子集化；仅 400 | yes |
| 朱雀仿宋 Zhuque Fangsong Regular | [TrionesType/zhuque](https://github.com/TrionesType/zhuque) release `v0.212`（ZhuqueFangsong-Regular.ttf） | SIL OFL 1.1（`apps/web/public/fonts/zhuque-fangsong/LICENSE.txt`） | 同上分片子集化；仅 400（上游为 beta，缺字分片按实际 cmap 反推） | yes |
| 站酷小薇 ZCOOL XiaoWei Regular | [google/fonts `ofl/zcoolxiaowei`](https://github.com/google/fonts/tree/main/ofl/zcoolxiaowei)（ZCOOLXiaoWei-Regular.ttf） | SIL OFL 1.1（`apps/web/public/fonts/zcool-xiaowei/LICENSE.txt`） | 整包单文件子集（GB2312 全集+拉丁+标点） | yes |
| 马善政楷体 Ma Shan Zheng Regular | [google/fonts `ofl/mashanzheng`](https://github.com/google/fonts/tree/main/ofl/mashanzheng)（MaShanZheng-Regular.ttf） | SIL OFL 1.1（`apps/web/public/fonts/ma-shan-zheng/LICENSE.txt`） | 整包单文件子集（常用集：GB2312 一级+拉丁+标点，笔画繁密收窄以守 2MB 预算；次常用走系统栈回退） | yes |
| Source Sans 3（latin） | [adobe-fonts/source-sans](https://github.com/adobe-fonts/source-sans) release `3.052R`（WOFF2-source-sans-3.052R.zip，latin 400/700/400i） | SIL OFL 1.1（RFN “Source”；`apps/web/public/fonts/source-sans-3/LICENSE.txt`） | latin 字符集子集化（pyftsubset 重切） | yes |
| Source Serif 4（latin） | [adobe-fonts/source-serif](https://github.com/adobe-fonts/source-serif) release `4.005R`（source-serif-4.005_WOFF2.zip，latin 400/700/400i） | SIL OFL 1.1（RFN “Source”；`apps/web/public/fonts/source-serif-4/LICENSE.txt`） | latin 字符集子集化（pyftsubset 重切） | yes |

### 内置字体分片说明（R08）

- 产物位置：`apps/web/public/fonts/<family>/`（woff2 + LICENSE.txt），声明表
  `apps/web/src/styles/fonts.css`（AUTO-GENERATED，@font-face + unicode-range）。
  全部自托管相对路径，不引用任何外部字体 CDN；默认零 preload，仅当用户
  在阅读设置选中该字体或渲染其样张时，浏览器按 unicode-range 拉取命中分片。
  思源两款源文件为官方 CN 区域子集（内部名 "Source Han Sans/Serif CN"），
  @font-face family 按消费端约定使用 SC 别名（"Source Han Sans SC"/
  "Source Han Serif SC"）——family 别名与字体内部名无耦合，仅影响匹配。
- 字符集推导（构建期，纯标准库编码表，可复现）：
  - 常用分片 `p0-common` = ASCII + Latin-1 + 通用标点/货币/箭头/数学/圈数字 +
    CJK 标点/全角（固定码位区间）∪ GB2312 符号区（行 0xA1-0xA9）∪
    GB2312 一级常用字（行 0xB0-0xD7，3755 字）；
  - 次常用分片 `p1-freq2` = GB2312 二级（行 0xD8-0xF7，3008 字）；
  - 简繁混排分片 `p2-trad-a/b` = Big5 常用字区（0xA440-0xC67E）剔除
    GB2312 与拉丁交集后对半，两片；
  - 各分片码位两两不相交；unicode-range 从各分片 WOFF2 的实际 cmap 反推
    （字体缺字不虚报，避免豆腐块）。
  - 展示体（站酷小薇/马善政）= 整包单文件；站酷小薇覆盖 GB2312 全集+拉丁+标点，
    马善政收窄为常用集（GB2312 一级+拉丁+标点）；
    英文两款 = latin 子集（400/700/400i）。
- 子集化配方：fonttools/pyftsubset + brotli（构建期临时 venv，不入项目
  依赖）；`--flavor=woff2 --no-hinting --drop-tables+=BASE,DSIG
  --name-IDs=0,1,2,3,6 --name-languages=0x409,0x804 --notdef-outline`，
  CFF（思源两款）另加 `--desubroutinize`；layout features 保留
  `kern,liga,ccmp,mark,mkmk,locl,vert,vrt2,vkrn`。
- 未内置（走 reader 字体栈系统同族回退，真机验收补充）：CJK 扩展 A/B 区、
  通用规范汉字表 8105 中 GB2312 之外的罕用字；内置中文字体仅 400 一档，
  600/700 由浏览器合成加粗。

Do not list or include Folo `icons/mgc` as a redistributable Lumi asset.

