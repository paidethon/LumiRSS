-- 0028: F25 工作区说明 —— 让工作区不只是另一个文章列表。
--
-- description：目标/范围/入口说明（纯文本，客户端转义渲染，上限 500
-- 字符由 API 层收敛）；旧工作区默认空串（无说明 = 不渲染说明区）。

ALTER TABLE workspaces ADD COLUMN description TEXT NOT NULL DEFAULT '';
