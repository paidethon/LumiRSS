/** scenario-wizard — N200 功能组合场景向导（纯逻辑核心）。
 *
 * 三个内置场景，每个 = 一组**具体的** device-local 设置键值变化；
 * UI 展示精确 diff（逐键 from → to，只列真正变化的键）→ 以可撤销
 * 批量应用：应用前把每个键的旧值快照进 localStorage（单槽位），
 * 「整体撤销」逐键还原。没有新子系统——只是既有 app-settings 的
 * 读写编排。
 */

import type { AppSettings } from '../store/app-settings'

export interface ScenarioChange {
  key: keyof AppSettings
  /** 设置项的人类标签（diff 预览行首）。 */
  label: string
  value: AppSettings[keyof AppSettings]
}

export interface BuiltinScenario {
  id: 'commute-listening' | 'technical-reading' | 'material-organizing'
  title: string
  description: string
  changes: ScenarioChange[]
}

function bool(key: keyof AppSettings, label: string, value: boolean): ScenarioChange {
  return { key, label, value }
}

function num(key: keyof AppSettings, label: string, value: number): ScenarioChange {
  return { key, label, value }
}

function str(
  key: keyof AppSettings,
  label: string,
  value: NonNullable<AppSettings[keyof AppSettings]>,
): ScenarioChange {
  return { key, label, value }
}

/** 三个内置场景（全部是既有设置键的具体值——不发明新开关）。 */
export const BUILTIN_SCENARIOS: BuiltinScenario[] = [
  {
    id: 'commute-listening',
    title: '通勤听读',
    description: '听读优先：30 分钟睡眠定时 + 朗读排除代码块/表格。',
    changes: [
      num('speechSleepTimerMinutes', '睡眠定时（分钟）', 30),
      bool('speechSkipCode', '朗读排除代码块', true),
      bool('speechSkipTables', '朗读排除表格', true),
      bool('speechSkipLinkOnly', '朗读排除纯链接段落', true),
    ],
  },
  {
    id: 'technical-reading',
    title: '技术文阅读',
    description: '等宽字体 + 代码换行 + 行宽收窄，代码阅读优先。',
    changes: [
      str('readerFontFamily', '正文字体', 'mono'),
      bool('readerCodeWrap', '代码块自动换行', true),
      bool('readerCodeLineNumbers', '代码行号', true),
      num('readerContentWidth', '正文行宽（px）', 640),
    ],
  },
  {
    id: 'material-organizing',
    title: '材料整理',
    description: '列表按日期分组 + 收起摘要 + 连续滚动，整理批量材料。',
    changes: [
      bool('groupByDate', '列表按日期分组', true),
      bool('listShowSnippet', '列表显示摘要', false),
      str('readerReadingMode', '阅读模式', 'scroll'),
      bool('pauseReadingProgress', '暂停阅读进度记录', true),
    ],
  },
]

/** 一行 diff：只包含值真的会变的键（精确键列表；值相同的键不出现）。 */
export interface ScenarioDiffLine {
  key: keyof AppSettings
  label: string
  from: unknown
  to: unknown
}

export function diffScenario(
  current: AppSettings,
  changes: ScenarioChange[],
): ScenarioDiffLine[] {
  return changes
    .filter((change) => !Object.is(current[change.key], change.value))
    .map((change) => ({
      key: change.key,
      label: change.label,
      from: current[change.key],
      to: change.value,
    }))
}

// ---- 应用 / 整体撤销（快照进 localStorage，单槽位） -------------------------

const SNAPSHOT_KEY = 'lumi.scenario-wizard-undo'

interface UndoSnapshot {
  scenarioId: BuiltinScenario['id']
  ts: number
  /** 应用前每个键的旧值（原样 JSON——撤销时逐键还原）。 */
  prior: Record<string, unknown>
}

function readSnapshot(): UndoSnapshot | null {
  if (typeof localStorage === 'undefined') return null
  try {
    const raw = localStorage.getItem(SNAPSHOT_KEY)
    if (raw === null) return null
    const parsed = JSON.parse(raw) as UndoSnapshot
    if (typeof parsed !== 'object' || parsed === null || typeof parsed.prior !== 'object') {
      return null
    }
    return parsed
  } catch {
    return null
  }
}

/** 是否存在可整体撤销的批量应用。 */
export function hasScenarioUndo(): boolean {
  return readSnapshot() !== null
}

export interface ApplyResult {
  appliedKeys: (keyof AppSettings)[]
  unchangedKeys: (keyof AppSettings)[]
  undoAvailable: boolean
}

/** 应用一个场景：先快照全部涉及键的旧值（覆盖旧快照——单槽位，
 * 语义 = 最近一次批量应用才可整体撤销），再返回要写入的 patch
 * （UI 用 settings.update(patch) 落盘；本函数自身不写设置）。 */
export function applyScenario(
  current: AppSettings,
  scenario: BuiltinScenario,
  now: number = Date.now(),
): ApplyResult {
  const prior: Record<string, unknown> = {}
  const patch: Record<string, unknown> = {}
  const unchangedKeys: (keyof AppSettings)[] = []
  for (const change of scenario.changes) {
    prior[change.key as string] = current[change.key]
    if (!Object.is(current[change.key], change.value)) {
      patch[change.key as string] = change.value
    } else {
      unchangedKeys.push(change.key)
    }
  }
  const snapshot: UndoSnapshot = {
    scenarioId: scenario.id,
    ts: now,
    prior,
  }
  if (typeof localStorage !== 'undefined') {
    try {
      localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(snapshot))
    } catch {
      // 存储失败：仍可应用，但「整体撤销」本次不可用（诚实返回）
    }
  }
  return {
    appliedKeys: Object.keys(patch) as (keyof AppSettings)[],
    unchangedKeys,
    undoAvailable: readSnapshot() !== null,
  }
}

/** 整体撤销：返回恢复 patch（旧值逐键还原）；无可撤销 → null。
 * 同值键不出现在 patch 里（调用方 update 幂等，少写为净）。 */
export function undoScenario(current: AppSettings): Record<string, unknown> | null {
  const snapshot = readSnapshot()
  if (snapshot === null) return null
  const patch: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(snapshot.prior)) {
    if (!Object.is(current[key as keyof AppSettings], value)) {
      patch[key] = value
    }
  }
  clearScenarioUndo()
  return patch
}

export function clearScenarioUndo(): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.removeItem(SNAPSHOT_KEY)
  } catch {
    // 静默
  }
}
