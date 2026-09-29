-- 0142: NEW-221..230 队列和阅读计划的用户决策能力（r3 阅读队列家族的延伸）。
--
-- 全部表都在每用户库（与 reading_queue 同一隔离面：RoutingDatabase 按
-- 请求身份路由，行永远只属于当前用户）；ItemRef 只引用不复制内容
-- （ADR 0004）；条目删除/退订后行仍存在，标题等呈现数据由读取侧
-- LEFT JOIN search_entries best-effort，消失的 ref 诚实占位。
--
-- 决策诚实边界（每组能力都遵守）：
--   - 一切「顺延 / 替换 / 归档 / 调换」都是显式用户动作，没有任何
--     后台自动重排或自动置读路径；
--   - 估时/集中度/前置未满足都是建议性数据（basis 标注），绝不强制。
--
-- NEW-221 分时段阅读队列：命名时段 + 成员行。partial UNIQUE 保证一篇
-- 文章同一时刻最多有一个 pending 归属（carried/done 行保留轨迹）。
CREATE TABLE queue_time_slots (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_opened_at TEXT
);

CREATE TABLE queue_time_slot_items (
    id TEXT PRIMARY KEY,
    slot_id TEXT NOT NULL,
    item_ref TEXT NOT NULL,
    added_at TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'done', 'carried')),
    done_at TEXT,
    carried_at TEXT,
    carried_to_slot TEXT
);

CREATE UNIQUE INDEX ux_queue_time_slot_pending_ref
  ON queue_time_slot_items(item_ref) WHERE status = 'pending';
CREATE INDEX ix_queue_time_slot_items_slot
  ON queue_time_slot_items(slot_id, position);

-- NEW-222 队列依赖关系：item_ref 的先读项 prereq_ref（建议性，绝不
-- 强制阻止跳读——没有任何读取路径因依赖存在而拒绝服务）。
CREATE TABLE queue_prereqs (
    id TEXT PRIMARY KEY,
    item_ref TEXT NOT NULL,
    prereq_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (item_ref, prereq_ref)
);

-- NEW-223 队列工作量预览：本人可校正的阅读速度（单行设置；
-- 400 字符/分钟只是缺省粗估，用户显式覆盖后以 updated_at 记账）。
CREATE TABLE reading_speed_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    chars_per_minute INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

-- NEW-224 阅读预约清单：一次性预约，到时只经应用内轮询面提示
-- （无推送/无邮件——提醒面只有 GET due），可改期（reschedule）或取消。
CREATE TABLE reading_reminders (
    id TEXT PRIMARY KEY,
    item_ref TEXT NOT NULL,
    remind_at TEXT NOT NULL,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'done', 'cancelled')),
    created_at TEXT NOT NULL,
    reminded_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX ix_reading_reminders_due ON reading_reminders(status, remind_at);

-- NEW-225 积压处理向导：「保留」决策台账（来源+范围粒度，唯一锚点），
-- 让「这次审过、决定保留未读」可追溯且可从后续预览中排除。归档走
-- 既有 F024/N049 set-read 管线（本迁移不建新读取状态）。
CREATE TABLE backlog_keep_decisions (
    id TEXT PRIMARY KEY,
    feed_url TEXT NOT NULL,
    older_than_days INTEGER NOT NULL,
    decided_at TEXT NOT NULL,
    note TEXT,
    UNIQUE (feed_url, older_than_days)
);

-- NEW-226 队列容量上限：单行设置 + 待确认区。满时新候选进
-- pending_choice；替换 / 暂不加入都是显式裁决（resolved_action 记账）。
CREATE TABLE queue_capacity_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    capacity INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE queue_overflow_candidates (
    id TEXT PRIMARY KEY,
    item_ref TEXT NOT NULL,
    queue_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_choice'
        CHECK (status IN ('pending_choice', 'replaced_in', 'dismissed')),
    resolved_at TEXT,
    resolved_action TEXT
);

CREATE UNIQUE INDEX ux_queue_overflow_pending_ref
  ON queue_overflow_candidates(item_ref) WHERE status = 'pending_choice';

-- NEW-227 章节级阅读计划：一篇长文一个计划（UNIQUE item_ref），章节
-- 行带 session_no（第几次阅读）；完成记账在章节行（不是文章百分比）。
CREATE TABLE section_plans (
    id TEXT PRIMARY KEY,
    item_ref TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE section_plan_sections (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    label TEXT NOT NULL,
    session_no INTEGER,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done')),
    done_at TEXT
);

CREATE INDEX ix_section_plan_sections ON section_plan_sections(plan_id, position);

-- NEW-228 阅读中断便签：一篇一个活跃便签（partial UNIQUE 只约束未归档
-- 行；归档后可写新便签 = 新旅程）。与 N045 reading_notes（段落锚点
-- 一句话便签）互补：这里记「下次从哪里继续 + 正在想什么」，完成后
-- 显式归档。
CREATE TABLE interruption_notes (
    id TEXT PRIMARY KEY,
    item_ref TEXT NOT NULL,
    resume_hint TEXT,
    thought TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE UNIQUE INDEX ux_interruption_notes_active_ref
  ON interruption_notes(item_ref) WHERE archived_at IS NULL;

-- NEW-229 阅读约定卡：pact_key 是双方共持的约定口令（创建方生成，
-- 对方 join 时携带同一 key 在自己库里建对称行）。行只记本人确认
-- （my_status）；对方的确认状态在本部署没有跨账户共享表面，绝不
-- 伪造 —— 读取侧以 unavailable 诚实呈现（见模块 docstring）。
CREATE TABLE reading_pacts (
    id TEXT PRIMARY KEY,
    pact_key TEXT NOT NULL UNIQUE,
    item_ref TEXT NOT NULL,
    material_title TEXT,
    deadline TEXT NOT NULL,
    counterpart_username TEXT NOT NULL,
    my_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (my_status IN ('pending', 'confirmed', 'archived')),
    confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- NEW-230 队列重复主题提醒：主题是用户手动标注（绝不自动推断兴趣）；
-- 集中度报告只在用户主动整理时计算（GET report），允许调换位置，
-- 服务端没有任何自动重排路径。
CREATE TABLE queue_topic_marks (
    id TEXT PRIMARY KEY,
    queue_date TEXT NOT NULL,
    item_ref TEXT NOT NULL,
    topic TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (queue_date, item_ref, topic)
);

CREATE INDEX ix_queue_topic_marks_day ON queue_topic_marks(queue_date, topic);
