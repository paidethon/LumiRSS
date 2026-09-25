-- 0113 (N167/N168/N169): 审批修订（supersede）+ 写工具台账（幂等键 + 撤销差异）。
--
-- N167 批准内容修改：批准前用户可编辑参数。修订产生一条 NEW 审批行
-- （绑定新 args_hash），旧行标记 status='superseded'（superseded_by
-- 指向新行）；对旧行 take → 410。status 枚举扩展无法 ALTER CHECK，
-- 沿用 0096 的前向重建法（建新表 → 拷贝 → 换名 → 重建索引）。
--
-- N168 失败步骤单独重试 / N169 任务结果差异撤销：写工具执行台账
-- agent_tool_writes —— 每次真实写副作用一行：
--   idempotency_key = tool || ':' || args_hash || ':' || turn_key
--   （args_hash + 回合 turn_key；同回合同参数的成功写重放返回缓存
--   结果，绝不重复执行——N168）；
--   before_json / after_json = 差异撤销所需的逐对象前后快照（N169，
--   仅可撤销工具记录）；undoable = 该工具是否支持撤销；
--   undone_at = 已撤销时刻（NULL = 未撤销）。
-- 台账行随线程级联删除；不 shadow-copy 任何 FreshRSS RSS 域数据。

CREATE TABLE agent_approvals_n167 (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL REFERENCES agent_threads(id) ON DELETE CASCADE,
  call_id TEXT NOT NULL,
  tool TEXT NOT NULL,
  args_json TEXT NOT NULL,
  args_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','expired','superseded')),
  superseded_by TEXT,
  created_at TEXT NOT NULL,
  decided_at TEXT
);

INSERT INTO agent_approvals_n167 (id, thread_id, call_id, tool, args_json, args_hash, status, superseded_by, created_at, decided_at)
  SELECT id, thread_id, call_id, tool, args_json, args_hash, status, NULL, created_at, decided_at FROM agent_approvals;

DROP TABLE agent_approvals;

ALTER TABLE agent_approvals_n167 RENAME TO agent_approvals;

CREATE INDEX ix_agent_approvals_thread ON agent_approvals(thread_id, status);

CREATE TABLE agent_tool_writes (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL REFERENCES agent_threads(id) ON DELETE CASCADE,
  call_id TEXT NOT NULL,
  tool TEXT NOT NULL,
  args_json TEXT NOT NULL,
  args_hash TEXT NOT NULL,
  turn_key TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  before_json TEXT,
  after_json TEXT,
  undoable INTEGER NOT NULL DEFAULT 0,
  result_json TEXT,
  undone_at TEXT,
  created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ux_agent_tool_writes_idem ON agent_tool_writes(idempotency_key);

CREATE INDEX ix_agent_tool_writes_thread ON agent_tool_writes(thread_id, created_at);
