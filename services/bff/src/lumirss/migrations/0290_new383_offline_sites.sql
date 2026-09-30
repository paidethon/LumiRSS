-- 0306: NEW-383 离线 HTML 资料集台账。
--
-- 台账只存选中项引用、包内链接自洽终检的违规清单与 zip 摘要；
-- zip 本体即时组装返回（从当前数据重装，内容可能已更新，如实说明），
-- 不在库里囤二进制。只含用户选中的条目——未选内容不进包。

CREATE TABLE IF NOT EXISTS new383_offline_sites (
    id TEXT PRIMARY KEY,
    item_refs_json TEXT NOT NULL DEFAULT '[]',
    item_count INTEGER NOT NULL DEFAULT 0,
    violation_count INTEGER NOT NULL DEFAULT 0,
    violations_json TEXT NOT NULL DEFAULT '[]',
    external_links_json TEXT NOT NULL DEFAULT '[]',
    sha256 TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
