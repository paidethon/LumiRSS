/** InteractionModePrefsPanel — NEW-396 新功能回退偏好。
 *
 * 只在明确可并存的新旧交互间二选一；classic 必带兼容期限（到期自动
 * 回到新交互并如实标注），旧实现没有无限期保留。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchInteractionModes,
  putInteractionMode,
  type InteractionModeSurface,
} from '../../api/new391'
import { Button } from '../ui/Button'
import { NoteText, StatusLine } from './parts'

function SurfaceRow({ surface }: { surface: InteractionModeSurface }) {
  const queryClient = useQueryClient()
  const setMode = useMutation({
    mutationFn: (mode: 'new' | 'classic') => putInteractionMode(surface.key, mode),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['new391', 'modes'] })
    },
  })
  return (
    <li
      data-n391-surface={surface.key}
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
          {surface.label}
        </span>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">
          当前生效：{surface.effectiveMode === 'new' ? '新交互' : '旧交互'}
        </span>
      </div>
      <NoteText>新：{surface.newLabel}</NoteText>
      <NoteText>旧：{surface.classicLabel}</NoteText>
      {surface.expired && (
        <StatusLine tone="info">
          旧交互偏好已过兼容期限，自动回到新交互；可重新选择。
        </StatusLine>
      )}
      {!surface.expired && surface.chosenMode === 'classic' && surface.expiresAt && (
        <NoteText>兼容期限至 {surface.expiresAt}（{surface.compatDays} 天）。</NoteText>
      )}
      <span className="flex gap-1">
        <Button
          size="sm"
          variant={surface.chosenMode === 'new' ? 'primary' : 'secondary'}
          loading={setMode.isPending && setMode.variables === 'new'}
          onClick={() => setMode.mutate('new')}
        >
          用新交互
        </Button>
        <Button
          size="sm"
          variant={surface.chosenMode === 'classic' ? 'primary' : 'secondary'}
          loading={setMode.isPending && setMode.variables === 'classic'}
          onClick={() => setMode.mutate('classic')}
        >
          暂用旧交互
        </Button>
      </span>
    </li>
  )
}

export function InteractionModePrefsPanel() {
  const modes = useQuery({
    queryKey: ['new391', 'modes'],
    queryFn: fetchInteractionModes,
  })
  if (modes.isLoading) {
    return (
      <div data-n391-panel="interaction-modes">
        <StatusLine tone="info">正在加载交互面…</StatusLine>
      </div>
    )
  }
  if (modes.isError) {
    return (
      <div data-n391-panel="interaction-modes">
        <StatusLine tone="error">交互面加载失败。</StatusLine>
      </div>
    )
  }
  return (
    <div data-n391-panel="interaction-modes" className="flex flex-col gap-3">
      <NoteText>{modes.data?.note}</NoteText>
      <ul className="flex flex-col gap-2">
        {modes.data?.surfaces.map((surface) => (
          <SurfaceRow key={surface.key} surface={surface} />
        ))}
      </ul>
    </div>
  )
}
