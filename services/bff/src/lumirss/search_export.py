"""F073 引用清单导出 — 服务端 CSV/Markdown 构建 util（可单测）。

CSV 注入防护（与 Web 端 F012 lib/table-export.ts 同源规则，服务端
落地一份）——FIX-327 的「可选择且明确的安全导出编码」约定：

- 公式特征（前导空白（TAB/CR/LF）剥离后以 = + - @ 开头，且剩余部分
  不是纯数字）→ 前置一个撇号（'）作转义前缀；Excel/WPS/Numbers 对
  撇号前缀单元格按文本处理，不再执行公式（TAB/CR/LF 前缀形态同样
  触发——表格软件会剥掉它们再求值）；
- 像数字的值（如 -2,000、+123）不转义：这是有意的约定——数值列保持
  可排序/可求和，且它们不构成公式注入面；
- 原文可追溯：去掉恰好一个前导撇号即还原原值（约定编码，非有损）；
- RFC 4180：含逗号/引号/换行的值整体加引号，内部引号双写。

导出内容只含选中字段（excerpt ≤200 字），绝不含正文全文。
"""

import re as _re

_NUMERIC_RE = _re.compile(r"^[\d,.\s]+%?$")

# 表格软件求值前会剥离的前导空白（OWASP CSV 注入清单里的 TAB/CR 形态）。
_FORMULA_LEAD_WS = "\t\r\n"


def looks_like_formula(value: str) -> bool:
    stripped = value.lstrip(_FORMULA_LEAD_WS)
    if not stripped:
        return False
    first = stripped[0]
    if first not in "=+-@":
        return False
    rest = stripped[1:]
    return not _NUMERIC_RE.fullmatch(rest) or rest.strip() == ""


def guard_cell(value: str) -> str:
    return f"'{value}" if looks_like_formula(value) else value


def csv_escape(value: str) -> str:
    needs_quoting = any(ch in value for ch in (",", '"', "\n", "\r"))
    escaped = value.replace('"', '""')
    return f'"{escaped}"' if needs_quoting else escaped


def build_csv(headers: list[str], rows: list[list[str]]) -> str:
    lines = [",".join(csv_escape(h) for h in headers)]
    for row in rows:
        lines.append(",".join(csv_escape(guard_cell(cell)) for cell in row))
    return "\n".join(lines) + "\n"


def build_markdown_list(
    headers: list[str], rows: list[list[str]], *, truncated_note: str | None = None
) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
    if truncated_note:
        lines.append("")
        lines.append(f"> {truncated_note}")
    return "\n".join(lines) + "\n"
