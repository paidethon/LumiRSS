/** reader-preset-device — F036 阅读布局预设设备适用。
 *
 * 预设 schema v2 扩展：vars 增加 `readerContentWidth`（宽度）、
 * `readerColumns`（栏数）与 `deviceScope`（'all' | 'desktop'，缺省
 * 'all'）。旧预设迁移：缺字段 → deviceScope='all'，schemaVersion +1。
 * mobile 设备应用 desktop-only 预设时忽略 width/columns 并诚实标注
 * 「桌面端生效」。
 */

export const PRESET_SCHEMA_VERSION = 2

export type DeviceScope = 'all' | 'desktop'

export interface PresetVarsV2 {
  readerFontFamily?: unknown
  readerFontSize?: unknown
  readerLineHeight?: unknown
  readerBackground?: unknown
  readerParagraphSpacing?: unknown
  readerJustify?: unknown
  readerContentWidth?: number
  readerColumns?: number
  deviceScope?: DeviceScope
}

/** 旧预设迁移：缺 deviceScope → 'all'（schemaVersion +1）。 */
export function migrateLegacyPreset<T extends { vars?: PresetVarsV2; schemaVersion?: number }>(
  preset: T,
): T & { vars: PresetVarsV2; schemaVersion: number } {
  const vars = { ...(preset.vars ?? {}) }
  if (vars.deviceScope !== 'desktop') {
    vars.deviceScope = 'all'
  }
  return {
    ...preset,
    vars,
    schemaVersion: Math.max(preset.schemaVersion ?? 1, PRESET_SCHEMA_VERSION),
  }
}

export interface ApplyResult {
  vars: PresetVarsV2
  ignored: string[]
  /** mobile 忽略 desktop-only 的宽度/栏数时的诚实标注 */
  notice: string | null
}

/** 按设备应用预设：mobile + deviceScope='desktop' → 忽略宽度/栏数。 */
export function applyPresetForDevice(
  vars: PresetVarsV2,
  isMobile: boolean,
): ApplyResult {
  if (isMobile && vars.deviceScope === 'desktop') {
    const scoped = { ...vars }
    const ignored: string[] = []
    if (scoped.readerContentWidth !== undefined) ignored.push('宽度')
    if (scoped.readerColumns !== undefined) ignored.push('栏数')
    delete scoped.readerContentWidth
    delete scoped.readerColumns
    return {
      vars: scoped,
      ignored,
      notice:
        ignored.length > 0
          ? `预设为桌面端生效（已忽略：${ignored.join('、')}）`
          : '预设为桌面端生效',
    }
  }
  return { vars, ignored: [], notice: null }
}

export interface PresetLike {
  id: string
  name: string
}

/** 覆盖同名/重名校验：同名不同 id → 报错；同 id → 覆盖。 */
export function upsertPreset<T extends PresetLike>(
  list: readonly T[],
  preset: T,
): { list: T[]; error: 'duplicate-name' | null } {
  const sameName = list.find((p) => p.name === preset.name && p.id !== preset.id)
  if (sameName !== undefined) {
    return { list: [...list], error: 'duplicate-name' }
  }
  const exists = list.some((p) => p.id === preset.id)
  return {
    list: exists ? list.map((p) => (p.id === preset.id ? preset : p)) : [...list, preset],
    error: null,
  }
}

/** 导入/导出往返：序列化含新字段（width/columns/deviceScope）。 */
export function serializePresetV2(preset: {
  id: string
  name: string
  builtin: boolean
  vars: PresetVarsV2
  schemaVersion?: number
}): Record<string, unknown> {
  const migrated = migrateLegacyPreset(preset)
  return {
    id: migrated.id,
    name: migrated.name,
    builtin: migrated.builtin,
    schemaVersion: migrated.schemaVersion,
    vars: {
      ...migrated.vars,
      readerContentWidth: migrated.vars.readerContentWidth,
      readerColumns: migrated.vars.readerColumns,
      deviceScope: migrated.vars.deviceScope ?? 'all',
    },
  }
}
