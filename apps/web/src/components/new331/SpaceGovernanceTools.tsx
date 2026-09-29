/** NEW-331..340 共读空间协作工具组 — 组合面板（两级情境展开）。
 *
 * - 基底（NEW-331）：空间选择 + 成员/栏目；会议资料单（显式添加资料 →
 *   结束 → 结论与出处）；
 * - NEW-332 投稿审批（pending 不公开给全体；退回原因可见）；
 * - NEW-333 版本通知（报告新版本 → 讨论参与者待核对）；
 * - NEW-334 成员到期（到期只撤销空间权限）；
 * - NEW-335 分歧记录（并列结论 + 证据，不强制统一结论）；
 * - NEW-336 讨论待答/已解答（发起者选中有用、标记解决，讨论保留）；
 * - NEW-337 活动摘要（自选时间段；仅共享面事件）；
 * - NEW-338 附件共享清单（管理者逐项撤销；不触碰私人文件）；
 * - NEW-339 共读模板（不含成员与内容；先预览再创建）；
 * - NEW-340 归档（未完成任务盘点 → force → 只读 → 恢复重确认成员）。
 *
 * 服务真源在 BFF（routers/new33*.py / new340*.py）；本组件只做真实
 * 调用 + 诚实状态（loading/error/empty），折叠 = 不挂载 = 零查询。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import * as api from '../../api/new331'
import { Button } from '../ui/Button'
import { NoteText, StatusLine, SubSection, errorText, inputClass } from '../new311/parts'

export function SpaceGovernanceTools() {
  const [open, setOpen] = useState(false)
  const [spaceId, setSpaceId] = useState('')
  const [newSpaceName, setNewSpaceName] = useState('')
  const [requireApproval, setRequireApproval] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const qc = useQueryClient()

  const spacesQuery = useQuery({
    queryKey: ['new331', 'spaces'],
    queryFn: () => api.listSpaces(),
    enabled: open,
  })

  const createSpaceMutation = useMutation({
    mutationFn: () =>
      api.createSpace({ name: newSpaceName, requireApproval }),
    onSuccess: (space) => {
      setSpaceId(space.id)
      setNewSpaceName('')
      setCreateError(null)
      void qc.invalidateQueries({ queryKey: ['new331', 'spaces'] })
    },
    onError: (error) => setCreateError(errorText(error)),
  })

  const spaces = spacesQuery.data?.items ?? []

  return (
    <section data-new331-space-tools="">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 text-sm font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
      >
        共读空间协作工具（{open ? '收起' : '展开'}）
      </button>
      {open && (
        <div className="mt-2 flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
          <div className="flex flex-col gap-1">
            <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
              选择空间
              <select
                value={spaceId}
                onChange={(event) => setSpaceId(event.target.value)}
                className={inputClass}
              >
                <option value="">{spaces.length === 0 ? '（暂无空间）' : '— 选择 —'}</option>
                {spaces.map((space) => (
                  <option key={space.id} value={space.id}>
                    {space.name}
                    {space.archivedAt ? '（已归档）' : ''}
                  </option>
                ))}
              </select>
            </label>
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
                新空间名
                <input
                  value={newSpaceName}
                  onChange={(event) => setNewSpaceName(event.target.value)}
                  className={`${inputClass} w-44`}
                />
              </label>
              <label className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
                <input
                  type="checkbox"
                  checked={requireApproval}
                  onChange={(event) => setRequireApproval(event.target.checked)}
                />
                开启投稿审批
              </label>
              <Button
                size="sm"
                disabled={!newSpaceName.trim() || createSpaceMutation.isPending}
                onClick={() => createSpaceMutation.mutate()}
              >
                创建空间
              </Button>
            </div>
            {createError && <StatusLine tone="error">{createError}</StatusLine>}
            {spacesQuery.isError && (
              <StatusLine tone="error">{errorText(spacesQuery.error)}</StatusLine>
            )}
          </div>
          {spaceId ? (
            <>
              <MembersSection spaceId={spaceId} />
              <MeetingsSection spaceId={spaceId} />
              <ContributionsSection spaceId={spaceId} />
              <VersionNoticesSection spaceId={spaceId} />
              <DiscussionsSection spaceId={spaceId} />
              <DisagreementsSection spaceId={spaceId} />
              <ActivitySection spaceId={spaceId} />
              <AttachmentSharesSection spaceId={spaceId} />
              <TemplatesSection spaceId={spaceId} />
              <ArchiveSection spaceId={spaceId} />
            </>
          ) : (
            <NoteText>
              选择或创建一个空间后展开各组工具。空间内容只来自成员的显式共享——
              私人阅读记录绝不进入空间视图。
            </NoteText>
          )}
        </div>
      )}
    </section>
  )
}

// ---- 基底：成员与栏目 + NEW-334 到期 ---------------------------------------

function MembersSection({ spaceId }: { spaceId: string }) {
  const qc = useQueryClient()
  const [username, setUsername] = useState('')
  const [error, setError] = useState<string | null>(null)
  const detailQuery = useQuery({
    queryKey: ['new331', 'space', spaceId],
    queryFn: () => api.getSpace(spaceId),
  })
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['new331'] })

  const addMutation = useMutation({
    mutationFn: () => api.addSpaceMember(spaceId, username.trim()),
    onSuccess: () => {
      setUsername('')
      setError(null)
      invalidate()
    },
    onError: (err) => setError(errorText(err)),
  })
  const expiryMutation = useMutation({
    mutationFn: ({ memberId, days }: { memberId: string; days: number | null }) =>
      api.setMemberExpiry(
        spaceId,
        memberId,
        days === null
          ? null
          : new Date(Date.now() + days * 86_400_000).toISOString(),
      ),
    onSuccess: invalidate,
    onError: (err) => setError(errorText(err)),
  })
  const sweepMutation = useMutation({
    mutationFn: () => api.sweepMemberExpiry(spaceId),
    onSuccess: invalidate,
    onError: (err) => setError(errorText(err)),
  })

  const members = detailQuery.data?.members ?? []
  const isManager = detailQuery.data?.myRole === 'manager'

  return (
    <SubSection id="members" label="成员与权限到期">
      {detailQuery.isLoading && <StatusLine tone="info">加载中…</StatusLine>}
      {detailQuery.isError && <StatusLine tone="error">{errorText(detailQuery.error)}</StatusLine>}
      <ul className="flex flex-col gap-1" data-new331-members="">
        {members.map((member) => (
          <li key={member.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-[var(--lumi-text-primary)]">
              {member.username}
              {member.role === 'manager' ? '（管理者）' : ''}
            </span>
            {member.expired && <span className="text-[var(--lumi-danger)]">已到期</span>}
            {!member.active && !member.expired && (
              <span className="text-[var(--lumi-text-tertiary)]">已移除</span>
            )}
            {member.expiresAt && !member.expired && (
              <span className="text-[var(--lumi-text-tertiary)]">
                到期：{member.expiresAt.slice(0, 10)}
              </span>
            )}
            {isManager && member.role !== 'manager' && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => expiryMutation.mutate({ memberId: member.id, days: 7 })}
                >
                  设 7 天到期
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => expiryMutation.mutate({ memberId: member.id, days: null })}
                >
                  清除到期
                </Button>
              </>
            )}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
          添加成员（用户名）
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            className={`${inputClass} w-36`}
          />
        </label>
        <Button
          size="sm"
          disabled={!username.trim() || addMutation.isPending}
          onClick={() => addMutation.mutate()}
        >
          添加
        </Button>
        {isManager && (
          <Button
            size="sm"
            variant="ghost"
            disabled={sweepMutation.isPending}
            onClick={() => sweepMutation.mutate()}
          >
            到期清扫
          </Button>
        )}
      </div>
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </SubSection>
  )
}

// ---- NEW-331 会议资料单 -------------------------------------------------------

function MeetingsSection({ spaceId }: { spaceId: string }) {
  const qc = useQueryClient()
  const [title, setTitle] = useState('')
  const [itemRef, setItemRef] = useState('')
  const [question, setQuestion] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [outcome, setOutcome] = useState('')
  const [error, setError] = useState<string | null>(null)

  const listQuery = useQuery({
    queryKey: ['new331', 'meetings', spaceId],
    queryFn: () => api.listMeetings(spaceId),
  })
  const detailQuery = useQuery({
    queryKey: ['new331', 'meeting', spaceId, selected],
    queryFn: () => api.getMeeting(spaceId, selected ?? ''),
    enabled: selected !== null,
  })
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['new331', 'meetings', spaceId] })
  const invalidateDetail = () =>
    void qc.invalidateQueries({ queryKey: ['new331', 'meeting', spaceId, selected] })

  const createMutation = useMutation({
    mutationFn: () => api.createMeeting(spaceId, title.trim()),
    onSuccess: () => {
      setTitle('')
      setError(null)
      invalidate()
    },
    onError: setError_,
  })
  const itemMutation = useMutation({
    mutationFn: () =>
      api.addMeetingItem(spaceId, selected ?? '', {
        entryRef: itemRef.trim(),
        title: itemRef.trim(),
        question: question.trim() || undefined,
      }),
    onSuccess: () => {
      setItemRef('')
      setQuestion('')
      setError(null)
      invalidateDetail()
    },
    onError: setError_,
  })
  const closeMutation = useMutation({
    mutationFn: () => api.closeMeeting(spaceId, selected ?? ''),
    onSuccess: () => {
      setError(null)
      invalidate()
      invalidateDetail()
    },
    onError: setError_,
  })
  const outcomeMutation = useMutation({
    mutationFn: () => api.addMeetingOutcome(spaceId, selected ?? '', { summary: outcome.trim() }),
    onSuccess: () => {
      setOutcome('')
      setError(null)
      invalidateDetail()
    },
    onError: setError_,
  })

  function setError_(err: unknown) {
    setError(errorText(err))
  }

  const meetings = listQuery.data?.items ?? []
  const detail = detailQuery.data

  return (
    <SubSection id="meetings" label="会议资料单">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
          会议标题
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className={`${inputClass} w-44`}
          />
        </label>
        <Button
          size="sm"
          disabled={!title.trim() || createMutation.isPending}
          onClick={() => createMutation.mutate()}
        >
          发起会议
        </Button>
      </div>
      {meetings.length === 0 && !listQuery.isLoading && (
        <StatusLine tone="info">暂无会议。</StatusLine>
      )}
      <ul className="flex flex-col gap-1">
        {meetings.map((meeting) => (
          <li key={meeting.id} className="flex items-center gap-2 text-sm">
            <button
              type="button"
              className="text-[var(--lumi-accent-text)] underline-offset-2 hover:underline"
              onClick={() => setSelected(meeting.id)}
            >
              {meeting.title}
            </button>
            <span className="text-xs text-[var(--lumi-text-tertiary)]">
              {meeting.status === 'open' ? '进行中' : '已结束'}
            </span>
          </li>
        ))}
      </ul>
      {detail && (
        <div className="flex flex-col gap-2 border-t border-[var(--lumi-border)] pt-2">
          <NoteText>
            资料项只来自成员显式添加（快照）；结论在会议结束后保存。
          </NoteText>
          <ul className="flex flex-col gap-0.5 text-sm" data-new331-meeting-items="">
            {(detail.items ?? []).map((item) => (
              <li key={item.id}>
                {item.title}
                {item.question ? `（问：${item.question}）` : ''} — {item.addedByUsername}
              </li>
            ))}
          </ul>
          {detail.status === 'open' ? (
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
                资料条目 ref
                <input
                  value={itemRef}
                  onChange={(event) => setItemRef(event.target.value)}
                  className={`${inputClass} w-40`}
                />
              </label>
              <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
                待讨论问题（可选）
                <input
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  className={`${inputClass} w-52`}
                />
              </label>
              <Button
                size="sm"
                disabled={!itemRef.trim() || itemMutation.isPending}
                onClick={() => itemMutation.mutate()}
              >
                添加资料
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={closeMutation.isPending}
                onClick={() => closeMutation.mutate()}
              >
                结束会议
              </Button>
            </div>
          ) : (
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
                结论与出处
                <input
                  value={outcome}
                  onChange={(event) => setOutcome(event.target.value)}
                  className={`${inputClass} w-72`}
                />
              </label>
              <Button
                size="sm"
                disabled={!outcome.trim() || outcomeMutation.isPending}
                onClick={() => outcomeMutation.mutate()}
              >
                保存结论
              </Button>
            </div>
          )}
          <ul className="flex flex-col gap-0.5 text-sm text-[var(--lumi-text-secondary)]">
            {(detail.outcomes ?? []).map((entry) => (
              <li key={entry.id}>
                结论：{entry.summary}
                {entry.entryRef ? `（出处 ${entry.entryRef}）` : ''} — {entry.createdByUsername}
              </li>
            ))}
          </ul>
        </div>
      )}
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </SubSection>
  )
}

// ---- NEW-332 投稿审批 -------------------------------------------------------

function ContributionsSection({ spaceId }: { spaceId: string }) {
  const qc = useQueryClient()
  const [ref, setRef] = useState('')
  const [title, setTitle] = useState('')
  const [reviewNote, setReviewNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const visibleQuery = useQuery({
    queryKey: ['new331', 'contributions', spaceId, 'visible'],
    queryFn: () => api.listContributions(spaceId, 'visible'),
  })
  const mineQuery = useQuery({
    queryKey: ['new331', 'contributions', spaceId, 'mine'],
    queryFn: () => api.listContributions(spaceId, 'mine'),
  })
  const invalidate = () =>
    void qc.invalidateQueries({ queryKey: ['new331', 'contributions', spaceId] })
  const submitMutation = useMutation({
    mutationFn: () => api.submitContribution(spaceId, { entryRef: ref.trim(), title: title.trim() }),
    onSuccess: () => {
      setRef('')
      setTitle('')
      setError(null)
      invalidate()
    },
    onError: (err) => setError(errorText(err)),
  })
  const reviewMutation = useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) =>
      api.reviewContribution(spaceId, id, { approve, reviewNote: reviewNote.trim() || undefined }),
    onSuccess: () => {
      setReviewNote('')
      setError(null)
      invalidate()
    },
    onError: (err) => setError(errorText(err)),
  })

  const visible = visibleQuery.data?.items ?? []
  const mine = mineQuery.data?.items ?? []

  return (
    <SubSection id="contributions" label="投稿与审批">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
          条目 ref
          <input
            value={ref}
            onChange={(event) => setRef(event.target.value)}
            className={`${inputClass} w-36`}
          />
        </label>
        <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
          标题
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className={`${inputClass} w-40`}
          />
        </label>
        <Button
          size="sm"
          disabled={!ref.trim() || !title.trim() || submitMutation.isPending}
          onClick={() => submitMutation.mutate()}
        >
          投稿
        </Button>
      </div>
      <NoteText>开启审批时投稿先入队列（仅你与管理者可见）；退回原因在「我的投稿」中可见。</NoteText>
      {visible.length === 0 ? (
        <StatusLine tone="info">当前对全体可见的投稿为空。</StatusLine>
      ) : (
        <ul className="flex flex-col gap-1" data-new331-contributions="">
          {visible.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span>{item.title}</span>
              <span className="text-xs text-[var(--lumi-text-tertiary)]">
                {item.status === 'approved'
                  ? '已批准'
                  : item.status === 'pending'
                    ? '待审（你可见）'
                    : '已退回'}
                {' · '}
                {item.submittedByUsername}
              </span>
              {item.status === 'pending' && (
                <>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => reviewMutation.mutate({ id: item.id, approve: true })}
                  >
                    批准
                  </Button>
                  <label className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
                    退回原因
                    <input
                      value={reviewNote}
                      onChange={(event) => setReviewNote(event.target.value)}
                      className={`${inputClass} w-40`}
                    />
                  </label>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={!reviewNote.trim()}
                    onClick={() => reviewMutation.mutate({ id: item.id, approve: false })}
                  >
                    退回
                  </Button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <NoteText>我的投稿（含待审/退回原因）：</NoteText>
      <ul className="flex flex-col gap-0.5 text-sm text-[var(--lumi-text-secondary)]">
        {mine.map((item) => (
          <li key={item.id}>
            {item.title} — {item.status}
            {item.reviewNote ? `（原因：${item.reviewNote}）` : ''}
          </li>
        ))}
      </ul>
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </SubSection>
  )
}

// ---- NEW-333 版本通知 -------------------------------------------------------

function VersionNoticesSection({ spaceId }: { spaceId: string }) {
  const qc = useQueryClient()
  const [ref, setRef] = useState('')
  const [label, setLabel] = useState('')
  const [error, setError] = useState<string | null>(null)
  const pendingQuery = useQuery({
    queryKey: ['new331', 'notices', spaceId, 'pending'],
    queryFn: () => api.listVersionNotices(spaceId, 'pending'),
  })
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['new331', 'notices', spaceId] })
  const reportMutation = useMutation({
    mutationFn: () =>
      api.reportVersionNotice(spaceId, { entryRef: ref.trim(), versionLabel: label.trim() }),
    onSuccess: () => {
      setRef('')
      setLabel('')
      setError(null)
      invalidate()
    },
    onError: (err) => setError(errorText(err)),
  })
  const ackMutation = useMutation({
    mutationFn: (noticeId: string) => api.acknowledgeVersionNotice(spaceId, noticeId),
    onSuccess: () => invalidate(),
    onError: (err) => setError(errorText(err)),
  })

  const pending = pendingQuery.data?.items ?? []
  return (
    <SubSection id="notices" label="版本通知">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
          条目 ref
          <input
            value={ref}
            onChange={(event) => setRef(event.target.value)}
            className={`${inputClass} w-36`}
          />
        </label>
        <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
          新版本标签
          <input
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            className={`${inputClass} w-36`}
          />
        </label>
        <Button
          size="sm"
          disabled={!ref.trim() || !label.trim() || reportMutation.isPending}
          onClick={() => reportMutation.mutate()}
        >
          报告新版本
        </Button>
      </div>
      <NoteText>该条目的讨论参与者会收到「待核对」提醒；正文不跨账户复制，请在本库重新核对引用。</NoteText>
      {pending.length === 0 ? (
        <StatusLine tone="info">没有待核对的版本通知。</StatusLine>
      ) : (
        <ul className="flex flex-col gap-1" data-new331-notices="">
          {pending.map((notice) => (
            <li key={notice.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span>
                {notice.entryRef} — {notice.versionLabel}（{notice.reportedByUsername} 报告）
              </span>
              <Button size="sm" variant="ghost" onClick={() => ackMutation.mutate(notice.id)}>
                已重新核对
              </Button>
            </li>
          ))}
        </ul>
      )}
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </SubSection>
  )
}

// ---- NEW-336 讨论待答/已解答 ------------------------------------------------

function DiscussionsSection({ spaceId }: { spaceId: string }) {
  const qc = useQueryClient()
  const [title, setTitle] = useState('')
  const [question, setQuestion] = useState('')
  const [reply, setReply] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const listQuery = useQuery({
    queryKey: ['new331', 'discussions', spaceId],
    queryFn: () => api.listDiscussions(spaceId),
  })
  const detailQuery = useQuery({
    queryKey: ['new331', 'discussion', spaceId, selected],
    queryFn: () => api.getDiscussion(spaceId, selected ?? ''),
    enabled: selected !== null,
  })
  const invalidate = () =>
    void qc.invalidateQueries({ queryKey: ['new331', 'discussions', spaceId] })
  const invalidateDetail = () =>
    void qc.invalidateQueries({ queryKey: ['new331', 'discussion', spaceId, selected] })
  const askMutation = useMutation({
    mutationFn: () => api.askDiscussion(spaceId, { title: title.trim(), question: question.trim() }),
    onSuccess: () => {
      setTitle('')
      setQuestion('')
      setError(null)
      invalidate()
    },
    onError: (err) => setError(errorText(err)),
  })
  const replyMutation = useMutation({
    mutationFn: () => api.replyDiscussion(spaceId, selected ?? '', reply.trim()),
    onSuccess: () => {
      setReply('')
      invalidateDetail()
    },
    onError: (err) => setError(errorText(err)),
  })
  const helpfulMutation = useMutation({
    mutationFn: ({ replyId, helpful }: { replyId: string; helpful: boolean }) =>
      api.setReplyHelpful(spaceId, selected ?? '', replyId, helpful),
    onSuccess: invalidateDetail,
    onError: (err) => setError(errorText(err)),
  })
  const resolveMutation = useMutation({
    mutationFn: (replyId: string | null) => api.resolveDiscussion(spaceId, selected ?? '', replyId),
    onSuccess: () => {
      invalidate()
      invalidateDetail()
    },
    onError: (err) => setError(errorText(err)),
  })

  const items = listQuery.data?.items ?? []
  const detail = detailQuery.data
  return (
    <SubSection id="discussions" label="讨论（待答/已解答）">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
          问题标题
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className={`${inputClass} w-40`}
          />
        </label>
        <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
          问题正文
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            className={`${inputClass} w-56`}
          />
        </label>
        <Button
          size="sm"
          disabled={!title.trim() || !question.trim() || askMutation.isPending}
          onClick={() => askMutation.mutate()}
        >
          提问
        </Button>
      </div>
      {items.length === 0 && <StatusLine tone="info">暂无讨论。</StatusLine>}
      <ul className="flex flex-col gap-1">
        {items.map((item) => (
          <li key={item.id} className="flex items-center gap-2 text-sm">
            <button
              type="button"
              className="text-[var(--lumi-accent-text)] underline-offset-2 hover:underline"
              onClick={() => setSelected(item.id)}
            >
              {item.title}
            </button>
            <span className="text-xs text-[var(--lumi-text-tertiary)]">
              {item.status === 'open' ? '待答' : '已解答'}
            </span>
          </li>
        ))}
      </ul>
      {detail && (
        <div className="flex flex-col gap-2 border-t border-[var(--lumi-border)] pt-2">
          <NoteText>{detail.question}</NoteText>
          <ul className="flex flex-col gap-1" data-new331-discussion-replies="">
            {(detail.replies ?? []).map((entry) => (
              <li key={entry.id} className="flex flex-wrap items-center gap-2 text-sm">
                <span>
                  {entry.body} — {entry.authorUsername}
                  {entry.helpful ? '（有用）' : ''}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    helpfulMutation.mutate({ replyId: entry.id, helpful: !entry.helpful })
                  }
                >
                  {entry.helpful ? '取消有用' : '选中有用'}
                </Button>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
              回复
              <input
                value={reply}
                onChange={(event) => setReply(event.target.value)}
                className={`${inputClass} w-56`}
              />
            </label>
            <Button
              size="sm"
              disabled={!reply.trim() || replyMutation.isPending}
              onClick={() => replyMutation.mutate()}
            >
              回复
            </Button>
            {detail.status === 'open' ? (
              <Button
                size="sm"
                variant="ghost"
                disabled={resolveMutation.isPending}
                onClick={() =>
                  resolveMutation.mutate(
                    (detail.replies ?? []).find((entry) => entry.helpful)?.id ?? null,
                  )
                }
              >
                标记解决
              </Button>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                disabled={resolveMutation.isPending}
                onClick={() => resolveMutation.mutate(null)}
              >
                重新打开
              </Button>
            )}
          </div>
          <NoteText>解决只选中回复引用，完整讨论保留。</NoteText>
        </div>
      )}
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </SubSection>
  )
}

// ---- NEW-335 分歧记录 -------------------------------------------------------

function DisagreementsSection({ spaceId }: { spaceId: string }) {
  const qc = useQueryClient()
  const [title, setTitle] = useState('')
  const [conclusion, setConclusion] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [evidence, setEvidence] = useState('')
  const [error, setError] = useState<string | null>(null)
  const listQuery = useQuery({
    queryKey: ['new331', 'disagreements', spaceId],
    queryFn: () => api.listDisagreements(spaceId),
  })
  const detailQuery = useQuery({
    queryKey: ['new331', 'disagreement', spaceId, selected],
    queryFn: () => api.getDisagreement(spaceId, selected ?? ''),
    enabled: selected !== null,
  })
  const invalidateDetail = () =>
    void qc.invalidateQueries({ queryKey: ['new331', 'disagreement', spaceId, selected] })
  const createMutation = useMutation({
    mutationFn: () => api.createDisagreement(spaceId, { title: title.trim() }),
    onSuccess: () => {
      setTitle('')
      setError(null)
      void qc.invalidateQueries({ queryKey: ['new331', 'disagreements', spaceId] })
    },
    onError: (err) => setError(errorText(err)),
  })
  const positionMutation = useMutation({
    mutationFn: () =>
      api.upsertMyPosition(spaceId, selected ?? '', { conclusion: conclusion.trim() }),
    onSuccess: () => {
      setConclusion('')
      setError(null)
      invalidateDetail()
    },
    onError: (err) => setError(errorText(err)),
  })
  const evidenceMutation = useMutation({
    mutationFn: () => api.addEvidence(spaceId, selected ?? '', { note: evidence.trim() }),
    onSuccess: () => {
      setEvidence('')
      setError(null)
      invalidateDetail()
    },
    onError: (err) => setError(errorText(err)),
  })

  const items = listQuery.data?.items ?? []
  const detail = detailQuery.data
  return (
    <SubSection id="disagreements" label="分歧记录">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
          分歧标题
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className={`${inputClass} w-44`}
          />
        </label>
        <Button
          size="sm"
          disabled={!title.trim() || createMutation.isPending}
          onClick={() => createMutation.mutate()}
        >
          记录分歧
        </Button>
      </div>
      <ul className="flex flex-col gap-1">
        {items.map((item) => (
          <li key={item.id} className="flex items-center gap-2 text-sm">
            <button
              type="button"
              className="text-[var(--lumi-accent-text)] underline-offset-2 hover:underline"
              onClick={() => setSelected(item.id)}
            >
              {item.title}
            </button>
            <span className="text-xs text-[var(--lumi-text-tertiary)]">
              {item.status === 'open' ? '开放' : '已闭合'}
            </span>
          </li>
        ))}
      </ul>
      {detail && (
        <div className="flex flex-col gap-2 border-t border-[var(--lumi-border)] pt-2">
          <ul className="flex flex-col gap-0.5 text-sm" data-new331-positions="">
            {(detail.positions ?? []).map((position) => (
              <li key={position.id}>
                {position.authorUsername}：{position.conclusion}
                {position.citations.length > 0
                  ? `（引用 ${position.citations.map((c) => c.ref || c.note).join('；')}）`
                  : ''}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
              我的结论（并列保存）
              <input
                value={conclusion}
                onChange={(event) => setConclusion(event.target.value)}
                className={`${inputClass} w-64`}
              />
            </label>
            <Button
              size="sm"
              disabled={!conclusion.trim() || positionMutation.isPending}
              onClick={() => positionMutation.mutate()}
            >
              保存我的立场
            </Button>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
              补充证据
              <input
                value={evidence}
                onChange={(event) => setEvidence(event.target.value)}
                className={`${inputClass} w-56`}
              />
            </label>
            <Button
              size="sm"
              variant="ghost"
              disabled={!evidence.trim() || evidenceMutation.isPending}
              onClick={() => evidenceMutation.mutate()}
            >
              补充
            </Button>
          </div>
          <NoteText>分歧永远并列呈现，不强制统一结论。</NoteText>
        </div>
      )}
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </SubSection>
  )
}

// ---- NEW-337 活动摘要 -------------------------------------------------------

function ActivitySection({ spaceId }: { spaceId: string }) {
  const [days, setDays] = useState(7)
  return (
    <SubSection id="activity" label="活动摘要">
      <div className="flex flex-col gap-2">
        <label className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
          时间段
          <select
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
            className={`${inputClass} w-28`}
          >
            <option value={1}>最近 1 天</option>
            <option value={7}>最近 7 天</option>
            <option value={30}>最近 30 天</option>
          </select>
        </label>
        <ActivityBody spaceId={spaceId} days={days} />
      </div>
    </SubSection>
  )
}

function ActivityBody({ spaceId, days }: { spaceId: string; days: number }) {
  const query = useQuery({
    queryKey: ['new331', 'activity', spaceId, days],
    queryFn: () =>
      api.getActivity(
        spaceId,
        new Date(Date.now() - days * 86_400_000).toISOString(),
        new Date().toISOString(),
      ),
  })
  const counts = query.data?.counts ?? {}
  return (
    <div className="flex flex-col gap-1 text-sm" data-new331-activity="">
      {query.isLoading && <StatusLine tone="info">汇总中…</StatusLine>}
      {query.isError && <StatusLine tone="error">{errorText(query.error)}</StatusLine>}
      {query.data && (
        <>
          <NoteText>{query.data.note}</NoteText>
          {Object.entries(counts).map(([bucket, entries]) => (
            <div key={bucket}>
              {bucket}：
              {Object.entries(entries)
                .map(([key, value]) => `${key} ${value}`)
                .join('，')}
            </div>
          ))}
        </>
      )}
    </div>
  )
}

// ---- NEW-338 附件共享清单 ---------------------------------------------------

function AttachmentSharesSection({ spaceId }: { spaceId: string }) {
  const qc = useQueryClient()
  const [ref, setRef] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [includeRevoked, setIncludeRevoked] = useState(false)
  const listQuery = useQuery({
    queryKey: ['new331', 'attachments', spaceId, includeRevoked],
    queryFn: () => api.listAttachmentShares(spaceId, includeRevoked),
  })
  const invalidate = () =>
    void qc.invalidateQueries({ queryKey: ['new331', 'attachments', spaceId] })
  const shareMutation = useMutation({
    mutationFn: () => api.shareAttachment(spaceId, { attachmentRef: ref.trim(), name: name.trim() }),
    onSuccess: () => {
      setRef('')
      setName('')
      setError(null)
      invalidate()
    },
    onError: (err) => setError(errorText(err)),
  })
  const revokeMutation = useMutation({
    mutationFn: (shareId: string) => api.revokeAttachmentShare(spaceId, shareId),
    onSuccess: () => invalidate(),
    onError: (err) => setError(errorText(err)),
  })
  const items = listQuery.data?.items ?? []
  return (
    <SubSection id="attachments" label="共享附件清单">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
          附件 ref
          <input
            value={ref}
            onChange={(event) => setRef(event.target.value)}
            className={`${inputClass} w-40`}
          />
        </label>
        <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
          名称
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            className={`${inputClass} w-36`}
          />
        </label>
        <Button
          size="sm"
          disabled={!ref.trim() || !name.trim() || shareMutation.isPending}
          onClick={() => shareMutation.mutate()}
        >
          共享元数据
        </Button>
        <label className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
          <input
            type="checkbox"
            checked={includeRevoked}
            onChange={(event) => setIncludeRevoked(event.target.checked)}
          />
          含已撤销
        </label>
      </div>
      {items.length === 0 && <StatusLine tone="info">清单为空。</StatusLine>}
      <ul className="flex flex-col gap-1" data-new331-attachments="">
        {items.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span>
              {item.name}（{item.ownerUsername}
              {item.sizeBytes !== null ? ` · ${item.sizeBytes}B` : ''}）
            </span>
            {item.revokedAt ? (
              <span className="text-xs text-[var(--lumi-text-tertiary)]">
                已撤销（{item.revokedByUsername}）
              </span>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => revokeMutation.mutate(item.id)}
              >
                撤销授权
              </Button>
            )}
          </li>
        ))}
      </ul>
      <NoteText>清单只含元数据；撤销不删除所有者的私人文件。</NoteText>
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </SubSection>
  )
}

// ---- NEW-339 模板 ----------------------------------------------------------

function TemplatesSection({ spaceId }: { spaceId: string }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [tpl, setTpl] = useState('')
  const [preview, setPreview] = useState<api.SpaceTemplate | null>(null)
  const [error, setError] = useState<string | null>(null)
  const listQuery = useQuery({
    queryKey: ['new331', 'templates'],
    queryFn: () => api.listSpaceTemplates(),
  })
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['new331', 'templates'] })
  const createMutation = useMutation({
    mutationFn: () =>
      api.createTemplateFromSpace(spaceId, {
        name: name.trim(),
        discussionTemplates: tpl.trim() ? [tpl.trim()] : [],
      }),
    onSuccess: () => {
      setName('')
      setTpl('')
      setError(null)
      invalidate()
    },
    onError: (err) => setError(errorText(err)),
  })
  const previewMutation = useMutation({
    mutationFn: (templateId: string) => api.previewSpaceTemplate(templateId),
    onSuccess: (view) => {
      setPreview(view)
      setError(null)
    },
    onError: (err) => setError(errorText(err)),
  })
  const applyMutation = useMutation({
    mutationFn: (templateId: string) =>
      api.createSpaceFromTemplate(templateId, { name: `来自模板 ${preview?.name ?? ''}` }),
    onSuccess: () => {
      setError(null)
      void qc.invalidateQueries({ queryKey: ['new331', 'spaces'] })
    },
    onError: (err) => setError(errorText(err)),
  })
  const templates = listQuery.data?.items ?? []
  return (
    <SubSection id="templates" label="共读模板">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
          模板名
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            className={`${inputClass} w-36`}
          />
        </label>
        <label className="flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
          讨论开场模板
          <input
            value={tpl}
            onChange={(event) => setTpl(event.target.value)}
            className={`${inputClass} w-52`}
          />
        </label>
        <Button
          size="sm"
          disabled={!name.trim() || createMutation.isPending}
          onClick={() => createMutation.mutate()}
        >
          从本空间生成
        </Button>
      </div>
      <ul className="flex flex-col gap-1">
        {templates.map((template) => (
          <li key={template.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span>{template.name}</span>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => previewMutation.mutate(template.id)}
            >
              预览
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={applyMutation.isPending}
              onClick={() => applyMutation.mutate(template.id)}
            >
              用它建空间
            </Button>
          </li>
        ))}
      </ul>
      {preview && (
        <div className="flex flex-col gap-0.5 text-sm text-[var(--lumi-text-secondary)]" data-new331-template-preview="">
          <NoteText>{preview.previewNote}</NoteText>
          <span>栏目：{preview.sections.map((s) => s.name).join('、') || '（无）'}</span>
          <span>角色规则：投稿审批 {preview.roleRules.requireApproval ? '开' : '关'}</span>
          <span>讨论模板：{preview.discussionTemplates.join('；') || '（无）'}</span>
        </div>
      )}
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </SubSection>
  )
}

// ---- NEW-340 归档 ----------------------------------------------------------

function ArchiveSection({ spaceId }: { spaceId: string }) {
  const qc = useQueryClient()
  const [preview, setPreview] = useState<api.ArchivePreview | null>(null)
  const [result, setResult] = useState<api.ArchiveResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['new331'] })
  }
  const previewMutation = useMutation({
    mutationFn: () => api.previewArchive(spaceId),
    onSuccess: (view) => {
      setPreview(view)
      setError(null)
    },
    onError: (err) => setError(errorText(err)),
  })
  const archiveMutation = useMutation({
    mutationFn: (force: boolean) => api.archiveSpace(spaceId, force),
    onSuccess: (view) => {
      setResult(view)
      setError(null)
      invalidate()
    },
    onError: (err) => setError(errorText(err)),
  })
  const restoreMutation = useMutation({
    mutationFn: () => api.restoreSpace(spaceId, []),
    onSuccess: (view) => {
      setResult(view)
      setError(null)
      invalidate()
    },
    onError: (err) => setError(errorText(err)),
  })
  return (
    <SubSection id="archive" label="归档">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="ghost" disabled={previewMutation.isPending} onClick={() => previewMutation.mutate()}>
          盘点未完成任务
        </Button>
        <Button size="sm" variant="ghost" disabled={archiveMutation.isPending} onClick={() => archiveMutation.mutate(false)}>
          归档（有任务则拒绝）
        </Button>
        <Button size="sm" variant="ghost" disabled={archiveMutation.isPending} onClick={() => archiveMutation.mutate(true)}>
          确认跳过并归档
        </Button>
        <Button size="sm" variant="ghost" disabled={restoreMutation.isPending} onClick={() => restoreMutation.mutate()}>
          恢复（仅留管理者）
        </Button>
      </div>
      {preview && (
        <div className="flex flex-col gap-0.5 text-sm" data-new331-archive-preview="">
          <NoteText>{preview.note}</NoteText>
          <span>未完成任务 {preview.openTaskCount} 项。</span>
          <ul className="flex flex-col gap-0.5 text-[var(--lumi-text-secondary)]">
            {preview.openTasks.map((task) => (
              <li key={task.kind + task.id}>
                {task.kind}：{task.title}
              </li>
            ))}
          </ul>
        </div>
      )}
      {result && (
        <StatusLine tone="info" >
          {result.action === 'archived'
            ? `已归档（处理任务 ${result.tasks.length} 项${result.forced ? '，force 确认跳过' : ''}）。归档后空间只读。`
            : `已恢复（保留成员 ${result.keptMembers.length} 人；未确认者已撤销空间权限）。`}
        </StatusLine>
      )}
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </SubSection>
  )
}
