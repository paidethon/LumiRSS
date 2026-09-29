-- 0238: NEW-312 网页选区剪藏包 —— 用户主动提交的选中文字 + 页面 URL
-- + 标题，保留选区而不是自动抓整页。
--
-- package_id 把同一次提交的多段选区绑成一个「剪藏包」；text 是用户
-- 自己选中的纯文本（原样保存、长度受限、JSON 输出转义），服务器绝不
-- 替用户抓取或改写。clip_item_uuid 可空——用户选择把选区挂到已有
-- 剪藏（同页）时由服务端校验存在性。per-user（RoutingDatabase）。

CREATE TABLE IF NOT EXISTS clip_selections (
    id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL,
    url TEXT NOT NULL,
    page_title TEXT NOT NULL DEFAULT '',
    clip_item_uuid TEXT,
    seq INTEGER NOT NULL,
    text TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clip_selections_url
    ON clip_selections (url, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_clip_selections_package
    ON clip_selections (package_id);
