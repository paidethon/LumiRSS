"""F073 引用清单导出 — 服务端 CSV/Markdown 构建 util（可单测）。

CSV 注入防护（与 Web 端 F012 lib/table-export.ts 同源规则，服务端
落地一份）：
- 公式特征（以 = + - @ 开头且剩余部分不是纯数字）→ 前置撇号；
- RFC 4180：含逗号/引号/换行的值整体加引号，内部引号双写。
导出内容只含选中字段（excerpt ≤200 字），绝不含正文全文。
"""

import re as _re

_NUMERIC_RE = _re.compile(r"^[\d,.\s]+%?$")


def looks_like_formula(value: str) -> bool:
    if value == "":
        return False
    first = value[0]
    if first not in "=+-@":
        return False
    rest = value[1:]
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
