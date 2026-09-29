/** NEW-282 简报去重审批 — 后续清单（defer = 仅列后续）与决定语义说明。
 * 决定本身在编排台内联完成；这里读回「列后续」的条目并说明三种决定的
 * 后果，绝不静默重收。 */

import { useQuery } from '@tanstack/react-query'
import { fetchFollowups } from '../../api/new281'
import { ErrorLine, NoteText, StatusLine } from './parts'

export function DuplicateReviewPanel() {
  const followups = useQuery({
    queryKey: ['new281-followups'],
    queryFn: ({ signal }) => fetchFollowups(signal),
  })

  return (
    <div className="flex flex-col gap-3">
      <NoteText>
        收录已刊出条目前必须逐条决定：<strong>重收</strong>（再进本期正文）、
        <strong>仅列后续</strong>（不进正文，出现在下面的后续清单，之后任何一期重新收录即从清单消失）、
        <strong>跳过</strong>（明确不要）。缺决定的提交会被 409 拦截。
      </NoteText>
      {followups.isError && <ErrorLine error={followups.error} />}
      {followups.data && followups.data.count === 0 && (
        <StatusLine tone="info">后续清单为空——没有待跟进的 defer 条目。</StatusLine>
      )}
      {followups.data && followups.data.count > 0 && (
        <ul className="flex flex-col gap-2" data-new281-followups="">
          {followups.data.followups.map((entry) => (
            <li
              key={entry.entryRef}
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]"
            >
              {entry.title || '(无标题)'}
              <span className="ml-1 text-xs text-[var(--lumi-text-tertiary)]">
                来自「{entry.priorIssue}」· defer 于 {entry.deferredAt}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
