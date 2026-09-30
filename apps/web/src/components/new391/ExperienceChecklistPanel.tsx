/** ExperienceChecklistPanel — NEW-395 版本功能体验清单。
 *
 * 清单来自发布清单（release-notes.json，随发布更新），按当前角色显示
 * 实际上线的功能入口；用户体验后可标记「了解 / 暂不使用」（覆盖式）。
 * 加载不到清单时如实说明，绝不编造条目。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchExperience,
  markExperience,
  type ExperienceFeature,
} from '../../api/new391'
import { Button } from '../ui/Button'
import { NoteText, StatusLine } from './parts'

function FeatureRow({ feature }: { feature: ExperienceFeature }) {
  const queryClient = useQueryClient()
  const mark = useMutation({
    mutationFn: (status: 'learned' | 'later') => markExperience(feature.id, status),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['new391', 'experience'] })
    },
  })
  return (
    <li
      data-n391-feature={feature.id}
      className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3"
    >
      <div className="flex flex-col">
        <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
          {feature.title}
          {feature.adminOnly && (
            <span className="ml-2 text-xs text-[var(--lumi-text-tertiary)]">管理员</span>
          )}
        </span>
        {feature.mark && (
          <span className="text-xs text-[var(--lumi-text-tertiary)]">
            {feature.mark.status === 'learned' ? '已了解' : '暂不使用'}
          </span>
        )}
      </div>
      <span className="flex gap-1">
        <Button
          size="sm"
          loading={mark.isPending && mark.variables === 'learned'}
          onClick={() => mark.mutate('learned')}
        >
          我了解了
        </Button>
        <Button
          size="sm"
          variant="ghost"
          loading={mark.isPending && mark.variables === 'later'}
          onClick={() => mark.mutate('later')}
        >
          暂不使用
        </Button>
      </span>
    </li>
  )
}

export function ExperienceChecklistPanel() {
  const experience = useQuery({
    queryKey: ['new391', 'experience'],
    queryFn: fetchExperience,
  })
  if (experience.isLoading) {
    return (
      <div data-n391-panel="experience">
        <StatusLine tone="info">正在加载体验清单…</StatusLine>
      </div>
    )
  }
  if (experience.isError) {
    return (
      <div data-n391-panel="experience">
        <StatusLine tone="error">体验清单加载失败。</StatusLine>
      </div>
    )
  }
  const data = experience.data
  return (
    <div data-n391-panel="experience" className="flex flex-col gap-3">
      {data && data.version === null ? (
        <StatusLine tone="info">
          {data.note ?? '发布清单不可用，无法展示体验清单。'}
        </StatusLine>
      ) : (
        <NoteText>
          版本 {data?.version} 实际上线的功能（按当前角色过滤）；标记只保存在本人账户。
        </NoteText>
      )}
      {data && data.features.length > 0 && (
        <ul className="flex flex-col gap-2">
          {data.features.map((feature) => (
            <FeatureRow key={feature.id} feature={feature} />
          ))}
        </ul>
      )}
      {data && data.features.length === 0 && data.version !== null && (
        <NoteText>当前清单里没有属于你角色的条目。</NoteText>
      )}
    </div>
  )
}
