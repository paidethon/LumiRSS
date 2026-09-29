#!/usr/bin/env python3
"""Validate this task package, not the state of LumiRSS or its deployment."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

def load_object(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: expected JSON object")
    return value

def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)

def main() -> int:
    base = Path(__file__).resolve().parent
    plan = load_object(base / "tasks.json")
    tools = load_object(base / "tools.json")
    tasks = plan.get("tasks", [])
    require(isinstance(tasks, list), "tasks must be a list")
    require(len(tasks) == 800, f"Expected 800 tasks, got {len(tasks)}")
    ids = [t["id"] for t in tasks]
    require(len(set(ids)) == len(ids), "Duplicate task IDs")
    for prefix, kind in (("FIX", "fix"), ("NEW", "new")):
        actual = {t["id"] for t in tasks if t["kind"] == kind}
        expected = {f"{prefix}-{i:03d}" for i in range(1, 401)}
        require(actual == expected, f"{kind}: wrong ID set")
    descriptions = [t["description"].strip() for t in tasks]
    require(all(descriptions), "Empty task description")
    duplicates = [s for s, n in Counter(descriptions).items() if n > 1]
    require(not duplicates, "Exact duplicate task descriptions")
    text = (base / "TASKS-800.md").read_text(encoding="utf-8")
    rows = re.findall(r"^- \[ \] \*\*((?:FIX|NEW)-\d{3})\*\* (.+)$", text, re.M)
    require(len(rows) == 800, "Markdown must contain exactly 800 task rows")
    require(dict(rows) == {t["id"]: t["description"] for t in tasks},
            "Markdown and JSON task descriptions differ")
    for name, count in (("skills", 20), ("mcps", 10), ("agents", 10)):
        values = tools.get(name, [])
        require(len(values) == count, f"{name}: expected {count}")
        require(len({v["name"] for v in values}) == count,
                f"{name}: duplicate names")
        require(len({v["source"] for v in values}) == count,
                f"{name}: duplicate source entries")
        require(all(v["source"].startswith("https://") for v in values),
                f"{name}: missing HTTPS source")
    old_skill_names = {
        "frontend-design", "webapp-testing", "theme-factory",
        "react-best-practices", "web-design-guidelines",
        "composition-patterns", "impeccable", "ui-ux-pro-max",
        "design-system-patterns", "interaction-design", "responsive-design",
        "visual-design-foundations", "web-component-design",
        "accessibility-compliance", "baseline-ui", "fixing-accessibility",
        "fixing-metadata", "fixing-motion-performance", "improve-ui",
        "create-design-md",
    }
    require(not (old_skill_names & {s["name"] for s in tools["skills"]}),
            "New skill names overlap old 20")
    for filename in ("MASTER.md", "START.md", "README.md"):
        require((base / filename).is_file(), f"Missing {filename}")
    print("PLAN_OK: FIX=400, NEW=400, Skills=20, MCP=10, Agents=10.")
    print("ID sets, exact descriptions, Markdown/JSON parity and source entries checked.")
    print("NOT A DELIVERY CHECK: semantic novelty, defects, tool use, tests and")
    print("production deployment still require real execution and independent review.")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"PLAN_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
