-- 0136: N079 笔记与事实分栏 —— lumi_notes 的类型化小节。
--
-- sections_json = {"facts":[],"interpretation":[],"toVerify":[]}
-- （三栏：原文事实 / 个人解读 / 待核实；均为字符串数组）。NULL =
-- 未分栏的旧笔记（读取侧归一化为三空数组，诚实兼容）。content_md
-- 仍是笔记正文的单一真源——分栏是附加结构，不替换正文。
-- search_library 投影在索引时把三栏以「[事实]/[个人解读]/[待核实]」
-- 标签渲染进 body，AI 消费面因此能区分个人判断与原文事实。

ALTER TABLE lumi_notes ADD COLUMN sections_json TEXT;
