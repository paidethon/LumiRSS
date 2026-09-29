/** NEW-344/345/349/350 隐私与授权中心（二）—— 共享链接（范围 + 次数
 * 上限）、隐私检查向导（无一键全删）、删除范围预览与回执。
 *
 * 诚实口径随 UI 原样展示：预览 = 外部访问者所见；scope 不可变；
 * 耗尽 → 续额且历史保留；向导逐项撤回（没有一键全删）；删除确认需要
 * 密码 + 输入 DELETE，回执只列实际执行的动作与 FreshRSS 边界。
 */

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  confirmDeletion,
  createShareLink,
  getDeletionPreview,
  getPrivacyReview,
  listDeletionReceipts,
  listShareLinkAccesses,
  listShareLinks,
  previewShareLink,
  revokeShareLink,
  setShareLinkLimit,
  topupShareLink,
  withdrawReviewItem,
  type ShareLinkCreated,
} from '../../api/new341'
import { Button } from '../ui/Button'
import {
  NoteText,
  StatusLine,
  SubSection,
  actionButtonClass,
  errorText,
  inputClass,
} from './parts'

export function ShareLinksSection() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['n344-share-links'], queryFn: listShareLinks })
  const [title, setTitle] = useState('')
  const [scope, setScope] = useState('titles')
  const [entryRefs, setEntryRefs] = useState('')
  const [excerptChars, setExcerptChars] = useState('200')
  const [maxUses, setMaxUses] = useState('')
  const [created, setCreated] = useState<ShareLinkCreated | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  const links = query.data

  async function create() {
    setError(null)
    try {
      const result = await createShareLink({
        title: title.trim(),
        scope,
        entryRefs: entryRefs
          .split(/[,\n]/)
          .map((ref) => ref.trim())
          .filter(Boolean),
        excerptChars: Number(excerptChars) || undefined,
        maxUses: maxUses ? Number(maxUses) : null,
      })
      setCreated(result)
      setTitle('')
      setEntryRefs('')
      await queryClient.invalidateQueries({ queryKey: ['n344-share-links'] })
    } catch (err) {
      setError(errorText(err))
    }
  }

  async function revoke(id: number) {
    setError(null)
    try {
      await revokeShareLink(id)
      await queryClient.invalidateQueries({ queryKey: ['n344-share-links'] })
    } catch (err) {
      setError(errorText(err))
    }
  }

  async function showPreview(id: number) {
    setError(null)
    try {
      const view = await previewShareLink(id)
      setPreview(JSON.stringify(view, null, 2))
    } catch (err) {
      setError(errorText(err))
    }
  }

  return (
    <div className="flex flex-col gap-2" data-n344-share-links="">
      {created && (
        <StatusLine tone="ok" testId="created-token">
          链接已创建（仅此一次显示）：{created.path}
        </StatusLine>
      )}
      {links.items.length === 0 ? (
        <StatusLine tone="info" testId="empty">
          还没有共享链接。
        </StatusLine>
      ) : (
        <ul className="flex flex-col gap-2">
          {links.items.map((link) => (
            <li key={link.id} data-n344-link={link.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="min-w-0 text-[var(--lumi-text-primary)]">
                #{link.id} {link.title} · {link.scope} · 已用 {link.useCount}
                {link.maxUses !== null ? `/${link.maxUses}` : '（不限）'}
                {link.revokedAt ? ' · 已撤销' : ''}
              </span>
              <span className="flex gap-1">
                <Button variant="ghost" onClick={() => void showPreview(link.id)}>
                  预览外部所见
                </Button>
                {!link.revokedAt && (
                  <Button variant="ghost" onClick={() => void revoke(link.id)}>
                    撤销
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {preview && (
        <pre
          data-n344-preview=""
          className="max-h-48 overflow-auto rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]"
        >
          {preview}
        </pre>
      )}
      <div className="flex flex-col gap-2">
        <label className="flex flex-col gap-1 text-sm text-[var(--lumi-text-primary)]">
          链接标题
          <input className={inputClass} value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-sm text-[var(--lumi-text-primary)]">
          可见范围
          <select className={inputClass} value={scope} onChange={(event) => setScope(event.target.value)}>
            <option value="titles">仅标题目录</option>
            <option value="excerpt">选段</option>
            <option value="full">完整授权正文（需当前设备信任）</option>
          </select>
        </label>
        {scope === 'excerpt' && (
          <label className="flex flex-col gap-1 text-sm text-[var(--lumi-text-primary)]">
            选段长度（20–1000 字符）
            <input
              className={inputClass}
              type="number"
              min={20}
              max={1000}
              value={excerptChars}
              onChange={(event) => setExcerptChars(event.target.value)}
            />
          </label>
        )}
        <label className="flex flex-col gap-1 text-sm text-[var(--lumi-text-primary)]">
          条目引用（逗号或换行分隔）
          <textarea
            className={inputClass}
            rows={2}
            value={entryRefs}
            onChange={(event) => setEntryRefs(event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-[var(--lumi-text-primary)]">
          使用次数上限（留空 = 不限）
          <input
            className={inputClass}
            type="number"
            min={1}
            value={maxUses}
            onChange={(event) => setMaxUses(event.target.value)}
          />
        </label>
        <Button
          className={actionButtonClass}
          disabled={!title.trim() || !entryRefs.trim()}
          onClick={() => void create()}
        >
          创建共享链接
        </Button>
        <NoteText>{links.note}</NoteText>
      </div>
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}

export function ShareLinkLimitsSection() {
  const linksQuery = useQuery({ queryKey: ['n344-share-links'], queryFn: listShareLinks })
  const [selected, setSelected] = useState<number | null>(null)
  const accessesQuery = useQuery({
    queryKey: ['n345-accesses', selected],
    queryFn: () => listShareLinkAccesses(selected as number),
    enabled: selected !== null,
  })
  const queryClient = useQueryClient()
  const [topup, setTopup] = useState('10')
  const [error, setError] = useState<string | null>(null)
  const links = linksQuery.data?.items ?? []
  async function applyLimit(id: number, maxUses: number | null) {
    setError(null)
    try {
      await setShareLinkLimit(id, maxUses)
      await queryClient.invalidateQueries({ queryKey: ['n344-share-links'] })
    } catch (err) {
      setError(errorText(err))
    }
  }
  async function applyTopup(id: number) {
    setError(null)
    try {
      await topupShareLink(id, Number(topup) || 0)
      await queryClient.invalidateQueries({ queryKey: ['n344-share-links'] })
      await queryClient.invalidateQueries({ queryKey: ['n345-accesses', selected] })
    } catch (err) {
      setError(errorText(err))
    }
  }
  return (
    <div className="flex flex-col gap-2" data-n345-limits="">
      {links.length === 0 ? (
        <StatusLine tone="info" testId="empty">
          先在「共享链接」里创建一条链接。
        </StatusLine>
      ) : (
        <ul className="flex flex-col gap-2">
          {links.map((link) => (
            <li key={link.id} data-n345-limit-row={link.id} className="flex flex-wrap items-center gap-2 text-sm">
              <button
                type="button"
                className={
                  selected === link.id
                    ? 'underline'
                    : 'text-[var(--lumi-accent-text)] hover:underline'
                }
                onClick={() => setSelected(link.id)}
              >
                #{link.id} {link.title}
              </button>
              <span className="text-[var(--lumi-text-secondary)]">
                {link.maxUses === null ? '不限次数' : `${link.useCount}/${link.maxUses}`}
                {link.exhaustedAt ? ' · 已耗尽' : ''}
              </span>
              <Button variant="secondary" onClick={() => void applyLimit(link.id, null)}>
                设为不限
              </Button>
              <Button variant="secondary" onClick={() => void applyLimit(link.id, 1)}>
                限 1 次
              </Button>
              <span className="flex items-center gap-1">
                <label className="text-xs text-[var(--lumi-text-tertiary)]">
                  续额
                  <input
                    className={`${inputClass} w-16`}
                    type="number"
                    min={1}
                    value={topup}
                    onChange={(event) => setTopup(event.target.value)}
                    aria-label={`链接 ${link.id} 续额次数`}
                  />
                </label>
                <Button variant="ghost" onClick={() => void applyTopup(link.id)}>
                  续额
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {selected !== null && (
        <div data-n345-accesses="">
          {accessesQuery.isPending && <StatusLine tone="info">加载访问记录…</StatusLine>}
          {accessesQuery.data && (
            <>
              <ul className="flex flex-col gap-1">
                {accessesQuery.data.items.map((access) => (
                  <li key={access.id} className="text-xs text-[var(--lumi-text-secondary)]">
                    {access.accessedAt} · {access.result}
                  </li>
                ))}
              </ul>
              <NoteText>{accessesQuery.data.note}</NoteText>
            </>
          )}
        </div>
      )}
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}

export function PrivacyReviewSection() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['n349-review'], queryFn: getPrivacyReview })
  const [ref, setRef] = useState('')
  const [error, setError] = useState<string | null>(null)
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  const review = query.data
  async function withdraw(key: string, needsRef: boolean) {
    setError(null)
    try {
      await withdrawReviewItem(key, needsRef ? ref.trim() : '')
      setRef('')
      await queryClient.invalidateQueries({ queryKey: ['n349-review'] })
    } catch (err) {
      setError(errorText(err))
    }
  }
  return (
    <div className="flex flex-col gap-2" data-n349-review="">
      <NoteText>{review.note}</NoteText>
      <ul className="flex flex-col gap-2">
        {review.items.map((item) => (
          <li
            key={item.key}
            data-n349-item={item.key}
            className="flex flex-wrap items-start justify-between gap-2"
          >
            <div className="min-w-0">
              <div className="text-sm text-[var(--lumi-text-primary)]">{item.title}</div>
              <div className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">{item.detail}</div>
            </div>
            {item.withdraw.available ? (
              <Button variant="secondary" onClick={() => void withdraw(item.key, item.withdraw.needsRef)}>
                撤回
              </Button>
            ) : (
              <span className="text-xs text-[var(--lumi-text-tertiary)]">{item.withdraw.how}</span>
            )}
          </li>
        ))}
      </ul>
      <label className="flex flex-col gap-1 text-sm text-[var(--lumi-text-primary)]">
        对象引用（撤回「共享链接 / API 来源 / Webhook / 保存视图」时填 id 或 uuid）
        <input className={inputClass} value={ref} onChange={(event) => setRef(event.target.value)} />
      </label>
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}

export function DeletionPreviewSection() {
  const queryClient = useQueryClient()
  const previewQuery = useQuery({ queryKey: ['n350-deletion-preview'], queryFn: getDeletionPreview })
  const receiptsQuery = useQuery({ queryKey: ['n350-receipts'], queryFn: listDeletionReceipts })
  const [password, setPassword] = useState('')
  const [confirmText, setConfirmText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  if (previewQuery.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (previewQuery.isError) return <StatusLine tone="error">{errorText(previewQuery.error)}</StatusLine>
  const previewData = previewQuery.data

  async function confirm() {
    setError(null)
    try {
      const result = await confirmDeletion(password, confirmText)
      setDone(
        `已处理 ${result.receipt.actions.length} 类动作；到期 ${result.receipt.scheduledDeletionAt ?? '—'}。`,
      )
      setPassword('')
      setConfirmText('')
      await queryClient.invalidateQueries({ queryKey: ['n350-receipts'] })
    } catch (err) {
      setError(errorText(err))
    }
  }

  return (
    <div className="flex flex-col gap-2" data-n350-deletion="">
      <ul className="flex flex-col gap-1">
        {Object.entries(previewData.categories).map(([category, count]) => (
          <li key={category} data-n350-category={category} className="text-sm text-[var(--lumi-text-primary)]">
            {category}：{count}
          </li>
        ))}
      </ul>
      <div className="flex flex-col gap-1">
        {previewData.sharedCopies.map((rule) => (
          <NoteText key={rule.copy}>
            {rule.copy} → {rule.rule}
          </NoteText>
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-sm text-[var(--lumi-text-primary)]">
          登录密码
          <input
            className={inputClass}
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-[var(--lumi-text-primary)]">
          输入 DELETE 确认
          <input
            className={inputClass}
            value={confirmText}
            onChange={(event) => setConfirmText(event.target.value)}
            aria-label="输入 DELETE 确认删除"
          />
        </label>
        <Button
          variant="danger"
          disabled={!password || confirmText !== 'DELETE'}
          onClick={() => void confirm()}
        >
          确认注销并执行处理
        </Button>
      </div>
      <NoteText>确认后逐类执行可执行项并提供实际处理回执；FreshRSS 侧数据不在处理范围。</NoteText>
      {done && <StatusLine tone="ok" testId="receipt">{done}</StatusLine>}
      {receiptsQuery.data && receiptsQuery.data.items.length > 0 && (
        <div data-n350-receipts="">
          {receiptsQuery.data.items.map((receipt) => (
            <NoteText key={receipt.id}>
              回执 #{receipt.id}（{receipt.requestedAt}）：{receipt.actions.length} 类动作
            </NoteText>
          ))}
        </div>
      )}
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}

export function PrivacySharingCenter() {
  const [open, setOpen] = useState(false)
  return (
    <section data-n341-sharing-center="">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 text-sm font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
      >
        共享与删除控制（{open ? '收起' : '展开'}）
      </button>
      {open && (
        <div className="mt-2 flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
          <SubSection id="n344-share-links" label="共享链接：使用范围（NEW-344）">
            <ShareLinksSection />
          </SubSection>
          <SubSection id="n345-limits" label="共享链接：次数上限与访问记录（NEW-345）">
            <ShareLinkLimitsSection />
          </SubSection>
          <SubSection id="n349-review" label="隐私检查向导（逐项保留或撤回）">
            <PrivacyReviewSection />
          </SubSection>
          <SubSection id="n350-deletion" label="删除范围预览与回执">
            <DeletionPreviewSection />
          </SubSection>
        </div>
      )}
    </section>
  )
}
