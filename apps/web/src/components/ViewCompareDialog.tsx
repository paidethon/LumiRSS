/** ViewCompareDialog — F075 视图对照（SearchPage 视图 chips「比较」入口）。
 *
 * 选第二视图 → 三区（共同/仅A/仅B）各显示计数 + 前 20 条可点击打开；
 * complete:false → 「结果不完整」警示；比较为纯读取零写入。 */

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { compareSavedViews, type ViewCompareResult } from '../api/client'
import { useReaderUi } from '../store/reader-ui'
import type { SavedSearchView } from '../api/types'
import { Dialog } from './ui/Dialog'
import { Button } from './ui/Button'

function RefChip({ ref: entryRef, onClick }: { ref: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={entryRef}
      className="max-w-44 truncate rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2 py-0.5 text-[11px] text-[var(--lumi-accent-text)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
    >
      {entryRef}
    </button>
  )
}

export function ViewCompareDialog({
  open,
  onClose,
  baseView,
  otherViews,
}: {
  open: boolean
  onClose: () => void
  baseView: SavedSearchView | null
  otherViews: SavedSearchView[]
}) {
  const [pickedId, setPickedId] = useState<string | null>(null)
  const [result, setResult] = useState<ViewCompareResult | null>(null)
  const selectEntry = useReaderUi((s) => s.selectEntry)

  const compare = useMutation({
    mutationFn: (bId: string) => compareSavedViews(baseView?.id ?? '', bId),
    onSuccess: (data, bId) => {
      setResult(data)
      setPickedId(bId)
    },
  })

  const close = () => {
    onClose()
    setPickedId(null)
    setResult(null)
  }

  if (baseView === null) return null

  return (
    <Dialog open={open} onClose={close} title={`视图对照 — ${baseView.name}`} panelClassName="max-w-lg">
      <div className="flex flex-col gap-3" data-lumi-view-compare="">
        {otherViews.filter((v) => v.id !== baseView.id).length === 0 ? (
          <p className="text-xs text-[var(--lumi-text-tertiary)]">没有可对照的其他视图。</p>
        ) : (
          <div className="flex flex-wrap items-center gap-1.5">
            {otherViews
              .filter((v) => v.id !== baseView.id)
              .map((v) => (
                <Button
                  key={v.id}
                  size="sm"
                  variant={pickedId === v.id ? 'primary' : 'secondary'}
                  disabled={compare.isPending}
                  onClick={() => compare.mutate(v.id)}
                >
                  {v.name}
                </Button>
              ))}
          </div>
        )}

        {compare.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">对照失败，请稍后重试。</p>
        )}

        {result !== null && (
          <div className="flex flex-col gap-2 text-xs">
            {result.complete ? null : (
              <p role="alert" className="text-[var(--lumi-danger)]">
                结果不完整：至少一个视图超过对照上限（2000 条），以下为部分结果。
              </p>
            )}
            <p className="text-[var(--lumi-text-tertiary)]">
              共同 {result.counts.common} · 仅 A {result.counts.onlyA} · 仅 B {result.counts.onlyB}
            </p>
            {(
              [
                ['共同', result.common],
                ['仅 A', result.onlyA],
                ['仅 B', result.onlyB],
              ] as const
            ).map(([label, refs]) => (
              <section key={label} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
                <h4 className="font-medium text-[var(--lumi-text-primary)]">
                  {label}（{refs.length > 20 ? `前 20 / ${refs.length}` : refs.length}）
                </h4>
                {refs.length === 0 ? (
                  <p className="mt-1 text-[var(--lumi-text-tertiary)]">无</p>
                ) : (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {refs.slice(0, 20).map((ref) => (
                      <RefChip key={ref} ref={ref} onClick={() => selectEntry(ref)} />
                    ))}
                  </div>
                )}
              </section>
            ))}
          </div>
        )}
      </div>
    </Dialog>
  )
}
