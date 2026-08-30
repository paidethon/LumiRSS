# 0003 — Entry Read Path

> Status: **Completed**
> Original spec: Git history (docs/specs/0003-*.md)

---

> Milestone: 0003 Entry Read Path
> Phase: Phase 2 — Backend Core
> 日期：2026-08-27
> 结果：Completed（待人工 Review，未 commit）

## Status

Completed。

- Spec：`docs/specs/0003-entry-read-path.md`（只读探索 → 生成 Spec →
  用户修订 6 点（Detail endpoint 源码已验证、reading-list 语义、
  EntryNotFound 映射规则、File Plan 数量、pagination 未定义参数措辞、
  contentText 措辞）→ 批准 → Build）
- 本里程碑结束时**未 commit**，停在工作区等待人工 Review（按任务指令）

## Goal

把 `FastAPI → FreshRSSAdapter → FreshRSS → Feed list` 扩展成
`FastAPI → FreshRSSAdapter → FreshRSS → Entry list + Entry detail`：
`GET /api/v1/entries` 返回真实文章列表（不含正文），
`GET /api/v1/entries/{entryRef}` 返回单篇文章（contentText 纯文本）。

## What was implemented

- `src/lumirss/entryref.py`（新增）：`encode_entry_ref()` /
  `decode_entry_ref()` 纯函数 + `InvalidEntryReference`。
  格式 `e1.` + base64url(utf-8 upstream id)，无 padding；decode 校验
  前缀 / 字符集 / UTF-8 / 空值 / 512 字符上限。
- `src/lumirss/models.py`（新增）：`EntryListItem` / `EntryListResponse` /
  `EntryDetail`（Pydantic，一个定义点）。
- `src/lumirss/adapters/freshrss.py`（修改）：
  - `list_entries()`：GET reading-list（`n=20`，read+unread，无状态
    filter），归一化列表字段，**主动丢弃正文**；
  - `get_entry(item_id)`：POST stream/items/contents（恰好一个 `i`），
    items==[] → `EntryNotFound`，>1 → 防御性 `UpstreamError`；
  - `html_to_text()`：标准库 HTMLParser 做 text-only normalization
    （tag 剥离 / entity 还原 / 块级换行 / script+style 内容丢弃）；
  - `_common_fields()`：list/detail 共用的字段归一化（title/feedTitle
    缺失回退 `""`，author/url/publishedAt nullable，缺 id 跳过）；
  - 认证/Token/401 一次性重登完全复用 0002 模式。
- `src/lumirss/main.py`（修改）：
  - `GET /api/v1/entries`（envelope `{"items": [...]}`，无伪造
    nextCursor）；
  - `GET /api/v1/entries/{entry_ref}`：先 decode（非法 → 400，不触达
    FreshRSS）再取 Adapter；
  - `_get_adapter()` 抽出懒创建逻辑（feeds/entries 共用）；
  - `_ERROR_RESPONSES` 增加 `InvalidEntryReference`→400、
    `EntryNotFound`→404。
- 测试新增 4 个文件 43 个用例（全部 Mock）：
  `test_entryref.py`（15）、`test_html_to_text.py`（7）、
  `test_entry_adapter.py`（15）、`test_entries_route.py`（6）。
- 文档：README、PROJECT_STATE、progress board、本 devlog。

## Key user ↔ AI dialogue

（摘要，凭据一律 `[REDACTED]`）

1. 用户下发 0003 任务（Spec-driven）。AI 只读探索后发现分支仍在
   `feat/0002-bff-freshrss-adapter`（0002 尚未合入 main），按指令停止
   报告。用户走 PR #6 合入 0002 并切出 `feat/0003-entry-read-path`。
2. AI 生成 Spec 初稿（+626 行）。用户批准方向但要求 Build 前 6 点修订：
   Detail API 从"未知假设"改为"源码已验证 + Live Probe 再确认"
   （POST stream/items/contents + form `i=`）；reading-list 语义修正
   （All except hidden / STATE_ALL / n=20 / r=d）；EntryNotFound 映射
   规则（200+空 items → 404，0/1/>1 分支）；File Plan 数量修正
   （2 modified + 2 new source + 4 tests，文档单独列）；pagination
   未定义参数不契约化；contentText 措辞改为 text-only normalization。
   AI 逐条落实（顺带删除 AC4 中过时的"参数名以 probe 为准"限定词）。
3. 用户批准 → Build。AI 按 14 步顺序执行，每步跑测试。

## Actual API probe（Build 第 1 步，真实容器 FreshRSS 1.29.1）

- List：`GET /api/greader.php/reader/api/0/stream/contents/reading-list?output=json&n=20`
  → 200，13 条（库存 < 20），无 continuation。item 字段：
  id/title/author/published(int 秒)/summary.content(HTML)/
  alternate[{href}]/origin{streamId,htmlUrl,title}/categories/
  canonical/crawlTimeMsec/timestampUsec。
- Detail：`POST /api/greader.php/reader/api/0/stream/items/contents`，
  form `i=<item id>`（单个）→ 200，items 恰 1 条，与 list item 同构。
- 不存在 item：200 + `{"items": []}`（确认源码行为）。
- 只读性：detail 调用前后同一 item 的 categories 一致（无 read 状态
  变化）；全程只调用三个读取 endpoint。

## Commands actually executed

```bash
# 开工检查
git branch --show-current        # feat/0003-entry-read-path（基于 main@008bb81）
git status --short --branch      # clean
docker compose ps                # freshrss Up 2 days

# Build（均在 services/bff 下，逐步执行）
uv run python probe_0003.py      # 只读 probe（脚本用后即删，不打印秘密/正文）
uv run pytest tests/test_entryref.py -v        # 15 passed
uv run pytest tests/test_entry_adapter.py -v   # 8 → 15 passed
uv run pytest tests/test_entries_route.py -v   # 3 → 6 passed
uv run pytest tests/test_html_to_text.py -v    # 7 passed
uv run pytest                                  # 58 passed（全量回归）

# 真实 Smoke Test
uv run uvicorn lumirss.main:app --port 8000
curl http://127.0.0.1:8000/health/live             # 200 {"status":"ok"}
curl http://127.0.0.1:8000/api/v1/feeds            # 200 真实订阅（0002 回归）
curl http://127.0.0.1:8000/api/v1/entries          # 200，13 条真实文章
curl http://127.0.0.1:8000/api/v1/entries/<entryRef>  # 200，contentText 5804 字
curl http://127.0.0.1:8000/api/v1/entries/not-a-valid-ref      # 400
curl http://127.0.0.1:8000/api/v1/entries/e1.<fabricated-id>   # 404

# 收尾
git check-ignore services/bff/.env   # 命中（被忽略）
```

## Problems encountered

1. 首个 adapter 测试失败：手写期望时间戳算错（1787270034 我算成
   08-17，实际 UTC 是 2026-08-20T23:53:54Z）。
2. 编辑事故 ×2：一次替换把 docstring 行与 `try:` 粘连；另一次误删了
   `UpstreamError` 类定义（test_entries_route.py 收集时 ImportError
   暴露）。
3. `kill %1` 无法停止后台终端启动的 uvicorn（不同 shell 会话），改用
   PID 停止。

## How problems were solved

1. 测试层。以 `datetime.fromtimestamp(1787270034, tz=timezone.utc)` 的
   输出为准修正期望值，代码逻辑本身正确。
2. 代码层。均立即用精确替换修复；教训是多段替换后应立即跑一次可
   快速暴露语法/导入错误的测试（确实第一时间暴露了）。
3. 运维层。用启动日志中的 PID（551464）kill，确认 8000 端口释放。

## Acceptance evidence

Spec 0003 的 AC1–AC14 全部达成（详见最终报告）；关键证据：

- `uv run pytest` → **58 passed**（0002 的 15 个全部在内，无回归）；
- 真实列表：13 条真实文章（含"科技爱好者周刊（第 409 期）：程序员的
  职业未来"等），item keys 恰为
  author/entryRef/feedTitle/publishedAt/title/url（无正文字段）；
- 真实详情：200，title/feedTitle/publishedAt 正确，contentText 非空
  （5804 字符），无 HTML 标签；
- invalid ref → 400 `invalid_entry_reference`（fake adapter 调用数为
  0）；合法但不存在 → 404 `entry_not_found`；
- MockTransport 断言 list/detail 只触达
  ClientLogin/reading-list/items/contents；
- secret 扫描（tracked + untracked 非 ignored，排除 gitignored `.env`）：
  命中均为文档描述/代码模板/明显 fake 测试值，真实秘密零命中。

## What I learned

- FreshRSS `stream/items/contents` 对不存在 item 返回 200 + 空 items
  而非上游 404 —— "上游语义"与"HTTP 状态码"不能画等号，Adapter 要
  做显式映射（空即 404；请求一个 i 却返回多个 → 防御性 UpstreamError）。
- reading-list 的确切语义（All except hidden；无 it/xt 时 STATE_ALL；
  n 默认 20；r 默认 d newest first）来自源码 + Live Probe 双确认，
  不靠旧 Google Reader 文档猜。
- entryRef 版本前缀（`e1.`）+ base64url 是"不透明引用"的最小实现：
  URL-safe、确定性、可逆、非法输入在 decode 层拒绝 —— 无签名、无
  HMAC、无数据库映射表就足够，不过度设计。
- List 接口即使上游已带正文也必须主动丢弃，否则列表接口会退化成
  正文批量下载器（Test B 用 fixture 正文标记验证了这一点）。
- 标准库 `html.parser` 足够做 text-only normalization（明确：不是
  HTML sanitizer）：tags 剥离 + entity 还原 + 块级换行 + script/style
  内容丢弃，7 个测试覆盖。
- RFC 3339 UTC 转换直接用 `datetime.fromtimestamp(..., tz=timezone.utc)`
  格式化；手算时间戳不可靠。

## Next milestone

0004 — State / Filter / Pagination（已读/收藏写入、筛选、分页，
Phase 2 收官）。
