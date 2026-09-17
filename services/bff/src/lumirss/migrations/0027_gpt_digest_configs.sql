-- 0027: GPT 日报多配置（F01）——多个主题日报各自独立调度与选材。
--
-- gpt_digest_configs：一行 = 一份主题日报（技术/开源/…），字段与原
-- 单行配置一致 + 来源白名单（feed_url_allow：换行/逗号分隔的子串，
-- 空 = 全部订阅；不同配置材料互不串用）+ 各自的调度标记
-- （last_issue_key / last_error 随配置走，重启幂等按配置计）。
-- 原 gpt_digest_settings（单行）作为「默认日报」迁入 id=1 并保留表
-- （旧端点兼容读取配置 1）。
-- gpt_digest_issues 增加 config_id；唯一约束从全局 issue_key 改为
-- (config_id, issue_key)——两份配置同日各生成一期互不覆盖。

CREATE TABLE IF NOT EXISTS gpt_digest_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    hour INTEGER NOT NULL DEFAULT 8,
    timezone TEXT NOT NULL DEFAULT '',
    window_hours INTEGER NOT NULL DEFAULT 24,
    limit_count INTEGER NOT NULL DEFAULT 12,
    per_source_cap INTEGER NOT NULL DEFAULT 2,
    feed_url_allow TEXT NOT NULL DEFAULT '',
    last_issue_key TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

INSERT INTO gpt_digest_configs (id, name, enabled, hour, timezone, window_hours, limit_count, per_source_cap, feed_url_allow, last_issue_key, last_error)
SELECT 1, '默认日报', enabled, hour, timezone, window_hours, limit_count, per_source_cap, '', last_issue_key, last_error
FROM gpt_digest_settings WHERE id = 1;

INSERT INTO gpt_digest_configs (name)
SELECT '默认日报' WHERE NOT EXISTS (SELECT 1 FROM gpt_digest_configs WHERE id = 1);

CREATE TABLE IF NOT EXISTS gpt_digest_issues_migrated (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER NOT NULL DEFAULT 1,
    issue_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'published',
    title TEXT NOT NULL,
    body_html TEXT NOT NULL,
    sections_json TEXT NOT NULL,
    refs_json TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    published_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (config_id, issue_key)
);

INSERT INTO gpt_digest_issues_migrated (id, config_id, issue_key, status, title, body_html, sections_json, refs_json, model, note, created_at, published_at, updated_at)
SELECT id, 1, issue_key, status, title, body_html, sections_json, refs_json, model, note, created_at, published_at, updated_at
FROM gpt_digest_issues;

DROP TABLE gpt_digest_issues;
ALTER TABLE gpt_digest_issues_migrated RENAME TO gpt_digest_issues;

CREATE INDEX IF NOT EXISTS idx_gpt_digest_issues_config_key
    ON gpt_digest_issues (config_id, issue_key DESC);
