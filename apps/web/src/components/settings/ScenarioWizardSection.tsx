/** ScenarioWizardSection — N200 功能组合场景向导（设置 → 通用）。
 *
 * 三个内置场景；先展示精确 diff（逐键 from → to，只列真正变化的键）
 * → 应用为可整体撤销的批量（应用前快照旧值到 localStorage）→
 * 「整体撤销」逐键还原。纯编排，无新子系统。
 */

import { useMemo, useState } from 'react'
import { RotateCcw, Sparkles } from 'lucide-react'
import { useAppSettings } from '../../store/app-settings'
import {
  BUILTIN_SCENARIOS,
  applyScenario,
  diffScenario,
  hasScenarioUndo,
  undoScenario,
  type BuiltinScenario,
} from '../../lib/scenario-wizard'
import { Button } from '../ui/Button'

function formatValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? '开' : '关'
  if (typeof value === 'number') return String(value)
  if (typeof value === 'string' && value === '') return '（空）'
  return String(value)
}

export function ScenarioWizardSection() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const [selectedId, setSelectedId] = useState<BuiltinScenario['id'] | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [undoAvailable, setUndoAvailable] = useState(hasScenarioUndo())

  const selected = BUILTIN_SCENARIOS.find((s) => s.id === selectedId) ?? null
  const diff = useMemo(
    () => (selected === null ? [] : diffScenario(settings, selected.changes)),
    [settings, selected],
  )

  return (
    <section
      aria-label="功能组合场景向导"
      data-testid="scenario-wizard"
      className="flex flex-col gap-2"
    >
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        一键切换一组预设组合；应用前展示精确改动，可整体撤销（快照保存在本机）。
      </p>
      <div className="flex flex-wrap gap-1.5">
        {BUILTIN_SCENARIOS.map((scenario) => (
          <button
            key={scenario.id}
            type="button"
            aria-pressed={scenario.id === selectedId}
            onClick={() => {
              setSelectedId(scenario.id)
              setNotice(null)
            }}
            className={
              scenario.id === selectedId
                ? 'rounded-[var(--lumi-radius-md)] border border-[var(--lumi-accent)] bg-[var(--lumi-surface-selected)] px-2.5 py-1 text-xs text-[var(--lumi-text-primary)]'
                : 'rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1 text-xs text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]'
            }
          >
            {scenario.title}
          </button>
        ))}
      </div>
      {selected !== null && (
        <>
          <p className="text-xs text-[var(--lumi-text-tertiary)]">{selected.description}</p>
          <div data-testid="scenario-diff" className="flex flex-col gap-1">
            {diff.length === 0 ? (
              <p className="text-xs text-[var(--lumi-text-tertiary)]">
                当前设置已与「{selected.title}」一致，无需改动。
              </p>
            ) : (
              diff.map((line) => (
                <div
                  key={String(line.key)}
                  className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)] px-2 py-1 text-xs"
                >
                  <span className="text-[var(--lumi-text-secondary)]">{line.label}</span>
                  <span className="text-[var(--lumi-text-tertiary)]">
                    {formatValue(line.from)} → <strong className="font-medium text-[var(--lumi-text-primary)]">{formatValue(line.to)}</strong>
                  </span>
                </div>
              ))
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="primary"
              data-testid="scenario-apply"
              disabled={diff.length === 0}
              onClick={() => {
                if (selected === null) return
                const result = applyScenario(settings, selected)
                const patch: Record<string, unknown> = {}
                for (const change of selected.changes) {
                  if (result.appliedKeys.includes(change.key)) patch[change.key as string] = change.value
                }
                update(patch)
                setUndoAvailable(result.undoAvailable)
                setNotice(
                  `已应用 ${result.appliedKeys.length} 项改动${result.undoAvailable ? '，可整体撤销' : '（本机快照不可用，本次无法撤销）'}`,
                )
              }}
            >
              <Sparkles aria-hidden className="size-3.5" /> 应用此场景
            </Button>
            <Button
              size="sm"
              variant="ghost"
              data-testid="scenario-undo"
              disabled={!undoAvailable}
              onClick={() => {
                const patch = undoScenario(settings)
                if (patch === null) {
                  setNotice('没有可撤销的批量应用。')
                  setUndoAvailable(false)
                  return
                }
                update(patch)
                setUndoAvailable(false)
                setNotice('已整体撤销上次场景应用。')
              }}
            >
              <RotateCcw aria-hidden className="size-3.5" /> 整体撤销
            </Button>
          </div>
        </>
      )}
      {notice !== null && (
        <p role="status" data-testid="scenario-notice" className="text-xs text-[var(--lumi-text-secondary)]">
          {notice}
        </p>
      )}
    </section>
  )
}
