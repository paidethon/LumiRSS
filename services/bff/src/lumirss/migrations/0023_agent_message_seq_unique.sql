-- 0023: Agent message ordering gets a database guarantee (pool #38).
--
-- seq was assigned as MAX(seq)+1 serialized only by an in-process
-- asyncio lock (single-process invariant). Across processes two writers
-- could both read MAX=N and both insert N+1 — (thread_id, seq) had only
-- a plain index, so both rows landed and messages_after/SSE cursors
-- lost their meaning.
--
-- Repair: threads that actually contain duplicate seqs are resequenced
-- 1..N in (created_at, rowid) order — no row is deleted (lossless);
-- rowid breaks timestamp ties with true insertion order. Only affected
-- threads are touched. Then (thread_id, seq) becomes UNIQUE and the
-- redundant non-unique index is dropped.
-- Forward-only: fresh and pre-unique databases both end at v23.

UPDATE agent_messages
SET seq = (
  SELECT COUNT(*) FROM agent_messages other
  WHERE other.thread_id = agent_messages.thread_id
    AND (other.created_at < agent_messages.created_at
         OR (other.created_at = agent_messages.created_at AND other.rowid < agent_messages.rowid))
) + 1
WHERE thread_id IN (
  SELECT thread_id FROM agent_messages GROUP BY thread_id, seq HAVING COUNT(*) > 1
);

CREATE UNIQUE INDEX ux_agent_messages_thread_seq
  ON agent_messages(thread_id, seq);

DROP INDEX IF EXISTS ix_agent_messages_thread;
