"""Generate the web settings metadata module from the BFF Pydantic model.

PortableSettings (services/bff/src/lumirss/app_settings.py) is the SINGLE
SOURCE OF TRUTH for server-portable settings defaults, enum values, and
numeric bounds. The web UI consumes the generated module instead of
hand-copied defaults/ranges/enums, so the two sides can never drift.

Output: apps/web/src/api/generated/settings-meta.ts

Deterministic output (no timestamps) → CI can regenerate and
``git diff --exit-code`` to detect drift.

Usage (repo root or services/bff):

    uv run python scripts/export_settings_meta.py
"""

import sys
from pathlib import Path

BFF_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BFF_ROOT / "src"))

from lumirss.app_settings import (  # noqa: E402
    _HEX_COLOR_RE,
    _NUMERIC_RANGES,
    SETTINGS_SCHEMA_VERSION,
    PortableSettings,
)

WEB_OUT = (
    BFF_ROOT.parents[1]
    / "apps"
    / "web"
    / "src"
    / "api"
    / "generated"
    / "settings-meta.ts"
)

HEADER = """\
/* AUTO-GENERATED — DO NOT EDIT.
 *
 * Source of truth: services/bff/src/lumirss/app_settings.py
 * (PortableSettings — the strict Pydantic model the BFF persists).
 * The web store imports these values instead of hand-copied
 * defaults/enums/bounds, so frontend and backend cannot drift.
 *
 * Regenerate:   pnpm settings:generate
 * Drift check:  pnpm settings:check
 */
"""


def ts_value(value: object) -> str:
    """Render a Python scalar as a TypeScript literal."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    raise TypeError(f"unsupported scalar: {value!r}")


def ts_record(name: str, fields: dict[str, object], indent: str) -> str:
    lines = [f"export const {name} = {{"]
    for key, value in fields.items():
        lines.append(f"{indent}  {key}: {ts_value(value)},")
    lines.append(f"{indent}}} as const")
    return "\n".join(lines)


def main() -> None:
    document = PortableSettings()
    defaults = document.model_dump()

    enum_fields = {
        key: list(value)
        for key, value in {
            "themeMode": ("system", "light", "dark"),
            "uiFontStack": ("default", "sans", "serif", "mono"),
            "uiFontSize": (15, 16, 18, 20),
            "readerFontFamily": ("system", "sans", "serif", "mono"),
            "readerBackground": ("follow", "sepia", "warm", "paper", "mint", "custom"),
            "readerImageMode": ("all", "grayscale", "hidden"),
            "readerTextIndent": ("off", "2em"),
            "readerChineseConversion": ("off", "s2t", "t2s", "tw", "hk"),
            "readerCodeHighlight": ("auto", "off"),
            "readerCodeTheme": (
                "auto",
                "github-light",
                "github-dark",
                "vitesse-light",
                "vitesse-dark",
            ),
        }.items()
    }
    for key, values in enum_fields.items():
        if defaults.get(key) not in values:
            raise SystemExit(f"default for {key} missing from enum: {defaults.get(key)!r}")

    numeric_lines = []
    for key in sorted(_NUMERIC_RANGES):
        minimum, maximum, step = _NUMERIC_RANGES[key]
        numeric_lines.append(
            f"  {key}: {{ min: {ts_value(minimum)}, max: {ts_value(maximum)}, "
            f"step: {ts_value(step)}, default: {ts_value(defaults[key])} }},"
        )
    numeric_block = "export const NUMERIC_RANGES = {\n" + "\n".join(numeric_lines) + "\n} as const\n"

    defaults_without_version = {
        key: value for key, value in defaults.items() if key != "schemaVersion"
    }
    defaults_block = ts_record(
        "PORTABLE_DEFAULTS", defaults_without_version, ""
    )
    enum_lines = "\n".join(
        f"  {key}: [{', '.join(ts_value(v) for v in values)}],"
        for key, values in enum_fields.items()
    )
    enums_block = (
        "export const SETTING_ENUMS = {\n" + enum_lines + "\n} as const"
    )

    content = "\n".join(
        [
            HEADER,
            f"export const SETTINGS_SCHEMA_VERSION = {SETTINGS_SCHEMA_VERSION} as const",
            "",
            defaults_block,
            "",
            enums_block,
            "",
            numeric_block,
            "/** #RRGGBB hex 颜色（accentColor / readerBackgroundCustom 共用）。 */",
            f"export const HEX_COLOR_PATTERN = {ts_value(_HEX_COLOR_RE)}",
            "",
        ]
    )
    WEB_OUT.parent.mkdir(parents=True, exist_ok=True)
    WEB_OUT.write_text(content, encoding="utf-8")
    print(f"wrote {WEB_OUT.relative_to(BFF_ROOT.parents[1])}")


if __name__ == "__main__":
    main()
