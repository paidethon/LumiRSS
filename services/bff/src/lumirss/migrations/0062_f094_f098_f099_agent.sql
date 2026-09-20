-- 0062: W5 agent 会话扩展（F094 资料范围 / F098 工具权限 / F099 分支）。
-- 全部可空：NULL = 行为与既有完全一致（不锁定 / 默认全权限 / 非分支）。

-- F094：{"workspaceId": "..."} 或 {"entryRefs": ["rss:...", ...]}；
-- NULL = 全库不锁定。服务端在工具执行处过滤，资料文本无法绕过。
ALTER TABLE agent_threads ADD COLUMN scope_json TEXT;

-- F098：{"mode": "all"|"readonly", "allowedTools": [...],
-- "maxOpsPerTurn": 1..50}；NULL = 默认 all。
ALTER TABLE agent_threads ADD COLUMN tool_policy_json TEXT;

-- F099：分支来源会话 id；NULL = 非分支。
ALTER TABLE agent_threads ADD COLUMN branch_of TEXT;
