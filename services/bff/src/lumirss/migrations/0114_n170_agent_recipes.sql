-- 0114 (N170): 任务配方（可复用的 agent 任务模板）。
--
-- 配方 = {name, input, toolWhitelist, scope}：name 唯一命名（≤100 字），
-- input 是运行时作为首条用户消息发送的文本，toolWhitelist 是注册表
-- 白名单的子集（运行时落成会话 toolPolicy.allowedTools —— 服务端
-- evaluate_policy 拒绝越权工具，绝不前端隐藏了事），scope 复用 F094
-- 范围结构（{"workspaceId"} 或 {"entryRefs":[...]}，NULL = 不锁定）。
-- 配方是 Lumi 自有元数据，不触碰 FreshRSS 任何数据。

CREATE TABLE agent_recipes (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  input TEXT NOT NULL,
  tool_whitelist_json TEXT NOT NULL,
  scope_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ux_agent_recipes_name ON agent_recipes(name);
