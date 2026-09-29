-- 0240: NEW-314 网页快照文字检索层 —— 对已保存的快照建立可查找文本层，
-- 命中后能定位内容；原快照字节保持不变。
--
-- 行 = 快照的一个文本块（asset_uuid + seq 定位）：text 为块文本，
-- anchor 为最近的上级标题（前端滚动定位提示）。文本层是派生数据，
-- 可随时重建；快照本体（library_assets + 落盘文件 + sha256）零改动。
-- per-user（快照本就按账户隔离，文本层同库）。

CREATE TABLE IF NOT EXISTS snapshot_text_layers (
    asset_uuid TEXT NOT NULL,
    seq INTEGER NOT NULL,
    text TEXT NOT NULL,
    anchor TEXT NOT NULL DEFAULT '',
    built_at TEXT NOT NULL,
    PRIMARY KEY (asset_uuid, seq)
);
