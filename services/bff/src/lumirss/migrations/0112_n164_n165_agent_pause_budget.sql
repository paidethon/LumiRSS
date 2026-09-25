-- 0112 (N164/N165): 任务暂停快照 + 线程级预算。
--
-- N164 任务暂停与续接：agent_threads 增加 paused_state_json —— 暂停
-- 时冻结的回合快照 {pausedAt, completedSteps, pendingPlan,
-- pendingApprovalId}。NULL = 未暂停。续接（resume）从快照继续，已
-- 执行的工具步骤以 transcript 中已有结果的 callId 为准，绝不重复执行
-- 副作用。
--
-- N165 任务预算上限：budget_json = {maxToolCalls, maxTurns}（NULL =
-- 不设线程级预算，走 F098 每回合默认）；budget_used_json =
-- {toolCalls, turns, tokens, tokensKnown} —— 消耗计数。token 用量在
-- provider 响应带 usage 时如实累计，否则 tokensKnown=false（展示
-- unknown，绝不谎报 0）。

ALTER TABLE agent_threads ADD COLUMN paused_state_json TEXT;

ALTER TABLE agent_threads ADD COLUMN budget_json TEXT;

ALTER TABLE agent_threads ADD COLUMN budget_used_json TEXT;
