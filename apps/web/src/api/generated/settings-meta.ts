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

export const SETTINGS_SCHEMA_VERSION = 1 as const

export const PORTABLE_DEFAULTS = {
  themeMode: 'system',
  accentColor: '#6d78e8',
  uiFontStack: 'default',
  uiFontSize: 16,
  reduceMotion: false,
  readerFontFamily: 'system',
  readerFontSize: 17.0,
  readerLineHeight: 1.85,
  readerParagraphSpacing: 0.85,
  readerContentWidth: 760.0,
  readerPageMargin: 32.0,
  readerBackground: 'follow',
  readerBackgroundCustom: '#eef7ee',
  readerJustify: false,
  readerImageMode: 'all',
  readerTextIndent: 'off',
  readerHangingPunctuation: false,
  readerChineseConversion: 'off',
  readerShowReadingTime: false,
  readerCodeHighlight: 'auto',
  readerCodeTheme: 'auto',
  scrollMarkUnread: false,
} as const

export const SETTING_ENUMS = {
  themeMode: ['system', 'light', 'dark'],
  uiFontStack: ['default', 'sans', 'serif', 'mono'],
  uiFontSize: [15, 16, 18, 20],
  readerFontFamily: ['system', 'sans', 'serif', 'mono'],
  readerBackground: ['follow', 'sepia', 'warm', 'paper', 'mint', 'custom'],
  readerImageMode: ['all', 'grayscale', 'hidden'],
  readerTextIndent: ['off', '2em'],
  readerChineseConversion: ['off', 's2t', 't2s', 'tw', 'hk'],
  readerCodeHighlight: ['auto', 'off'],
  readerCodeTheme: ['auto', 'github-light', 'github-dark', 'vitesse-light', 'vitesse-dark'],
} as const

export const NUMERIC_RANGES = {
  readerContentWidth: { min: 560.0, max: 1080.0, step: 20.0, default: 760.0 },
  readerFontSize: { min: 12.0, max: 28.0, step: 1.0, default: 17.0 },
  readerLineHeight: { min: 1.2, max: 2.4, step: 0.05, default: 1.85 },
  readerPageMargin: { min: 12.0, max: 64.0, step: 4.0, default: 32.0 },
  readerParagraphSpacing: { min: 0.0, max: 2.0, step: 0.05, default: 0.85 },
} as const

/** #RRGGBB hex 颜色（accentColor / readerBackgroundCustom 共用）。 */
export const HEX_COLOR_PATTERN = '^#[0-9a-fA-F]{6}$'
