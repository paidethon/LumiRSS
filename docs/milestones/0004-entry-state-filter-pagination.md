# 0004 — Entry State, Filters & Pagination

> Status: **Completed**
> Original spec: Git history (docs/specs/0004-*.md)

---

> Milestone: 0004 Entry State + Filter + Cursor Pagination
> Phase: Phase 2 — Backend Core（收官）
> 日期：2026-08-28
> 结果：Completed（PR #10, `5420f63`）

## Status

Completed。

- Spec 经用户修订 6 点 + 4 个实现级检查后批准（原始 spec 可通过 `git show HEAD~:docs/specs/0004-entry-state-filter-pagination.md` 在 Git 历史中查看）
- PR #10 合入 main（`5420f63`）

## Goal

在 0003 只读路径上补齐 RSS Reader 后端三类能力：State（read/starred
写入）、Filter（all/unread/starred/feed）、Pagination（FreshRSS
continuation → LumiRSS opaque cursor），完成 Phase 2 Backend Core。

## Spec decisions（关键设计）

1. **Cursor 独立翻页 contract**：cursor 携带 `{c: continuation, v: view,
   f: feedUrl}`。请求带 cursor 且未显式提供 view/feedUrl → 直接采用
   cursor scope（`GET /entries?cursor=...` 可独立翻页）；显式提供则必须
   与 cursor scope 一致，否则 400 且不触达 FreshRSS。Route 层区分
   "view 未提供（None）"与"显式 view=all"。
2. **Filter 翻译给上游**：view → `it=` 参数、feedUrl → feed stream path
   （`quote(url, safe="")`），组合筛选在同一上游请求完成，禁止 Python
   post-filter。
3. **State set 语义**：`read=true/false` 表示目标状态，非 toggle —— 写
   API 幂等，客户端可安全重试。
4. **Action Token 与 Auth Token 同生命周期**：任何重登路径同步清两者；
   `/token` 与 `edit-tag` 各自拥有 401 一次性恢复；拒绝空/纯空白/"x"
   token 值（不依赖 FreshRSS 兼容捷径）。
5. **不存在 Entry 的 PATCH**：FreshRSS edit-tag 不保证对不存在 item
   报错，204 只承诺"写请求被接受"，不做 pre-read existence lookup。

## FreshRSS API probe（Build 第 1 步，真实容器 1.29.1）

只读 + 可恢复 write probe 全部通过（脚本用后即删）：

- `it=unread` → 12 items 全部 unread；`it=starred` → 0 items（当前无
  收藏，空集）；
- feed scoped stream：`stream/contents/feed/<percent-encoded url>` →
  10 items 全部属于目标 Feed；源码确认服务端 regex 允许 `%` 并
  urldecode 后查库；
- continuation：当前数据 13 条 < 20 → 无 continuation，如实记录
  "Real continuation unavailable"，pagination 语义由 Mock 测试覆盖；
- state markers：页面 1/13 read、0/13 starred，与固定 mapping 一致；
- `GET /token` → 有效 Action Token（长度 57，实现不硬编码长度）；
- `edit-tag`：单字段与组合写入（一个请求 T/i/r/a 四字段）均返回
  200 + body `"OK"`（源码 `exit('OK')`），状态真实改变；
- **Cleanup**：write probe 后 read/starred 完全恢复原状
  （False/False），再次读取确认。

## Action Token concept

```text
API Password → ClientLogin → Auth Token（身份）
Auth Token   → GET /token  → Action Token（写操作凭证）
```

二者均为 Secret，仅存 Adapter process memory：不写文件/SQLite/.env/
日志/devlog，不返回浏览器。`_get_auth_token()` 重新登录时会同步把
`_action_token` 清空（避免新 Auth Token 配旧 Action Token）。

## Cursor design

```text
c1. + base64url(compact JSON {"c","v","f"})，无 padding，上限 2048 字符
```

校验：前缀 / base64url 字符集 / UTF-8 / JSON / schema（恰好三个 key，
c 为非空数字串，v ∈ all/unread/starred，f 为 string 或 null）/ 长度。
Base64 是编码不是加密，cursor 不是认证也不是授权。

## State write mapping

```text
read=true    → a=user/-/state/com.google/read
read=false   → r=.../read        starred 同理
双字段修改   → 一个 edit-tag 请求携带重复 a=/r= form 字段
```

重复 form 字段生成方式：`urllib.parse.urlencode(list_of_pairs)` +
`content=`（httpx 0.28 AsyncClient 不接受 list-of-tuples `data`）。
edit-tag 成功校验 body strip 后必须为 "OK"，否则 UpstreamError。

## Commands actually executed

```bash
# 开工检查
git branch --show-current        # feat/0004-entry-state-filter-pagination
git status --short --branch      # clean
docker compose ps                # freshrss Up 2 days

# Build（均在 services/bff 下，逐步执行，每步即时跑测试）
uv run python probe_0004.py                        # probe（用后即删）
uv run pytest tests/test_cursor.py -q              # 16 passed
uv run pytest tests/test_entry_adapter.py tests/test_entries_route.py -q  # 21 passed
uv run pytest tests/test_entry_filters.py -q       # 8 passed
uv run pytest tests/test_entries_pagination.py -q  # 12 passed
uv run pytest tests/test_entry_state.py -q         # 26 passed
uv run pytest                                      # 120 passed（全量回归）

# 真实 Smoke Test
uv run uvicorn lumirss.main:app --port 8000
curl /health/live                                  # 200
curl /api/v1/entries                               # 200，13 条，read 1/13
curl "/api/v1/entries?view=unread"                 # 200，12 条全 unread
curl "/api/v1/entries?view=starred"                # 200，0 条
curl "/api/v1/entries?feedUrl=<real feed>"         # 200，10 条同 Feed
curl "/api/v1/entries?view=unread&feedUrl=<real>"  # 200，10 条全 unread 同 Feed
curl "/api/v1/entries?cursor=not-a-cursor"         # 400 invalid_cursor
curl "...?view=starred&cursor=<unread-scope>"      # 400 invalid_cursor（scope 不匹配）
curl "...?cursor=<valid>"                          # 200（cursor 独立翻页）
curl "...?view=bogus"                              # 422
# state smoke（Python 脚本，逐项断言）：
#   PATCH read=True → 204 → 读回 True → PATCH read=False 恢复 → 读回 False
#   PATCH starred=True → 204 → 读回 True → 恢复 → 读回 False
#   PATCH combined {read,starred} → 204 → 读回双反转 → 恢复 → 读回原状
#   {} / {"read":null} / {"read":1} → 422
# 收尾
git check-ignore services/bff/.env   # 命中（被忽略，未读取）
```

## Tests

新增 5 个测试文件 62 个用例（全部 Mock，无网络无真实 Secret）：

- `test_cursor.py`（16）：round-trip / 确定性 / URL-safe / compact payload /
  全部非法分支（前缀、空 payload、非法 base64url、坏 UTF-8、坏 JSON、
  wrong schema、非数字 continuation、非法 view、非法 f 类型、超长）；
- `test_entry_filters.py`（8）：view→it 映射（all 无 it、unread、
  starred、默认）、feed URL 编码进 stream path（raw_path 断言）、无
  post-filter、组合筛选单请求、state markers 映射；
- `test_entries_pagination.py`（12）：continuation 提取与转发、无
  continuation → None、**空最终页 + 无 continuation 合法**、路由 page1
  产生 nextCursor、**cursor 单独翻页采用 cursor scope**、显式 scope 匹配
  通过、view/feed mismatch → 400 不触达 FreshRSS、cursor feed scope 对无
  feedUrl 请求合法、非法 cursor 400、非法 view 422；
- `test_entry_state.py`（26）：token 获取+缓存复用、空/纯空白/"x" token
  → UpstreamError 且不调 edit-tag、read true/false → a=/r=、starred
  true/false、**组合双 a= / 双 r= 单请求**（repeated form fields 断言）、
  意外 body / 非 200 → UpstreamError、edit-tag 401 一次性恢复（恰好一次
  重试）、401 两次 → AuthenticationError、/token 401 恢复一次、token 同步
  失效、PATCH 路由 204、组合 body、`{}`/单 null/双 null/`{"read":1}`/
  `"true"` 全部 422 不触达、非法 ref 400 不触达、auth 错误 502；
- 更新 0003 既有测试（test_entry_adapter / test_entries_route）适配
  EntryPage 与 read/starred 字段。

回归：0002（15）+ 0003（43）全部继续通过，总计 **120 passed**。

## Real smoke

见上文 Commands。状态写入验证含完整恢复链：original（False/False）→
翻转（读回验证）→ 恢复（读回验证）→ combined 翻转+恢复 → final ==
original。`invalid body {} / null / 1` → 422。**状态恢复是验收标准**，
最终确认恢复成功。

## Problems encountered

1. **现象**：probe 首次 edit-tag POST 抛
   `RuntimeError: Attempted to send an sync request with an AsyncClient`。
   **原因**：httpx 0.28.1 的 AsyncClient 把 list-of-tuples `data` 当作
   同步 stream。**层级**：HTTP 客户端实现层。**解决**：改用
   `urllib.parse.urlencode(fields)` + `content=` + 显式
   `Content-Type: application/x-www-form-urlencoded`（也是生成重复
   form 字段的正确最小方式）。
2. **现象**：feed path 断言失败。**原因**：`httpx.URL.path` 会
   percent-decode。**层级**：测试断言层。**解决**：用
   `url.raw_path` 断言线上真实路径。
3. **现象**：`{"read": 1}` 得到 204 而非 422。**原因**：Pydantic v2
   默认把 1/0 隐式转 bool。**层级**：模型验证层。**解决**：
   `Field(default=None, strict=True)` 实现严格 bool。
4. **现象**：`encode_cursor("not-digits", ...)` 测试未抛错。**原因**：
   encode 侧未校验数字。**层级**：cursor 纯函数层。**解决**：encode
   也校验 continuation 为数字串（保证 encode 产物必可 decode）。

## What I learned

- FreshRSS edit-tag 成功 = HTTP 200 + body `"OK"`（`exit('OK')`）——
  写接口的成功响应体也要校验，不只是状态码；
- 两种 Token 是两条链：Auth Token 证明身份，Action Token 是写操作
  凭证；二者同生命周期，重登必须同步失效 Action Token；
- "set 语义 vs toggle" 是 API 设计的幂等性选择：重试安全靠 SET，toggle
  两次会回到原状态；
- opaque cursor + scope 封装让"cursor 独立翻页"和"scope 混用拒绝"
  同时成立，且不需要签名/数据库表；
- 库的行为细节（httpx list-data、URL.path 解码、Pydantic bool 强转）
  只有测试第一时间暴露——小步快跑的测试节奏本身就是探测器。

## Next milestone

0005 — Web Shell（Phase 3 — Reading Experience 开始）。未启动。
