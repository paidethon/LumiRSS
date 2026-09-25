-- 0113: N188 数据保留到期提醒——推迟（postpone）状态。
--
-- F114 的保留策略 apply 是「手动应用」；N188 增加到期提醒（notice），
-- 操作者可以把提醒推迟一小段时间。推迟状态是单行运维状态（不是便携
-- 偏好，也不进 lumi_settings KV 的语义），因此放独立单行表：
--   retention_postpone_until：提醒推迟到的时刻（ISO-8601 UTC 文本）；
--   NULL = 未推迟。服务端钳制：最远不超过 now + 30 天。

CREATE TABLE IF NOT EXISTS storage_retention_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  retention_postpone_until TEXT
);
