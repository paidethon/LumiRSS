/** NEW-296 附件条目 / NEW-298 重复复核 / NEW-299 退订卡 — 附件转独立
 * 条目（关系保留）；冲突队列按版本择留；退订信息卡只展示、用户主动
 * 打开且仅记录（LumiRSS 零网络，不代发任何退订请求）。 */

import { useCallback, useEffect, useState } from 'react'
import {
  deleteAttachmentItem,
  getUnsubCard,
  listAttachmentItems,
  listDuplicates,
  promoteAttachment,
  recordUnsubOpen,
  resolveDuplicate,
  type AttachmentItem,
  type DuplicateConflict,
  type UnsubCard,
} from '../../api/new291'
import { NoteText, StatusLine, buttonClass, errorText } from './panel'

export function AttachmentItemsPanel({ materialId }: { materialId: string }) {
  const [items, setItems] = useState<AttachmentItem[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setItems(await listAttachmentItems())
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const material = items.filter((i) => i.materialId === materialId)

  async function promote(ord: number): Promise<void> {
    setBusy(true)
    setError('')
    try {
      await promoteAttachment(materialId, ord)
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new291-attachments="" className="flex flex-col gap-3">
      <StatusLine tone="info">原邮件附件（转出为独立条目，与原邮件关系保留）</StatusLine>
      <ul className="flex flex-col gap-1">
        {material.map((att) => (
          <li key={`${att.materialId}-${att.ord}`} className="flex items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
            <span className="flex-1">
              {att.filename}（{att.contentType}，{att.size} 字节）
            </span>
            <a
              className="text-sm text-[var(--lumi-accent)] underline underline-offset-2"
              href={`/api/v1/email-attachment-items/${encodeURIComponent(att.id)}/download`}
            >
              下载
            </a>
            <button
              type="button"
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-0.5 text-sm hover:bg-[var(--lumi-surface-hover)]"
              onClick={() => {
                void deleteAttachmentItem(att.id).then(refresh).catch((err) => setError(errorText(err)))
              }}
            >
              删除条目
            </button>
          </li>
        ))}
        {material.length === 0 && <li className="text-sm text-[var(--lumi-text-tertiary)]">这封邮件还没有转出的附件条目。</li>}
      </ul>
      <button type="button" className={buttonClass} disabled={busy} onClick={() => void promote(0)}>
        把附件 #0 转出为独立条目
      </button>
      <NoteText>只有导入时存了内容（≤2 MiB）的附件可以转出；转出是复制引用而非移动。</NoteText>
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}

export function DuplicatePanel() {
  const [conflicts, setConflicts] = useState<DuplicateConflict[]>([])
  const [error, setError] = useState('')
  const [notes, setNotes] = useState('')

  const refresh = useCallback(async () => {
    try {
      setConflicts(await listDuplicates())
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function resolve(id: string, choice: string): Promise<void> {
    setError('')
    try {
      const result = await resolveDuplicate(id, choice)
      setNotes(`已按「${choice}」复核${result.resultId ? `，来件成为条目 ${result.resultId}` : ''}。`)
      await refresh()
    } catch (err) {
      setError(errorText(err))
    }
  }

  return (
    <div data-new291-duplicates="" className="flex flex-col gap-3">
      <StatusLine tone="info">待复核冲突 {conflicts.filter((c) => c.status === 'pending').length} 条</StatusLine>
      {notes !== '' && <StatusLine tone="ok">{notes}</StatusLine>}
      <ul className="flex flex-col gap-2">
        {conflicts.map((c) => (
          <li key={c.id} className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
            <span className="text-sm text-[var(--lumi-text-primary)]">
              {c.filename} · Message-ID {c.messageId} · {c.status === 'pending' ? '待复核' : `已复核（${c.status}）`}
            </span>
            {c.status === 'pending' && c.incomingPreview !== undefined && (
              <span className="text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
                来件：{c.incomingPreview.subject || '（无主题）'} — {c.incomingPreview.snippet}
              </span>
            )}
            {c.status === 'pending' && (
              <div className="flex flex-wrap gap-1">
                {(
                  [
                    ['keep_existing', '保留原版'],
                    ['keep_incoming', '保留来件'],
                    ['keep_both', '两个都留'],
                  ] as const
                ).map(([choice, label]) => (
                  <button
                    key={choice}
                    type="button"
                    className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-0.5 text-sm hover:bg-[var(--lumi-surface-hover)]"
                    onClick={() => void resolve(c.id, choice)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </li>
        ))}
        {conflicts.length === 0 && <li className="text-sm text-[var(--lumi-text-tertiary)]">没有待复核的重复冲突。</li>}
      </ul>
      <NoteText>相同 Message-ID 且正文一致 → 导入时已跳过；不同正文才进入这里由你决定。</NoteText>
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}

export function UnsubPanel({ materialId }: { materialId: string }) {
  const [card, setCard] = useState<UnsubCard | null>(null)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      setCard(await getUnsubCard(materialId))
    } catch (err) {
      setError(errorText(err))
    }
  }, [materialId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function open(method: string, target: string): Promise<void> {
    setError('')
    try {
      const result = await recordUnsubOpen(materialId, method, target)
      setNote(result.note)
      await refresh()
    } catch (err) {
      setError(errorText(err))
    }
  }

  if (error !== '') return <StatusLine tone="error">{error}</StatusLine>
  if (card === null) return <StatusLine tone="info">载入中…</StatusLine>
  if (!card.available) {
    return (
      <div data-new291-unsub-none="">
        <StatusLine tone="info">{card.honestyNote}</StatusLine>
      </div>
    )
  }
  return (
    <div data-new291-unsub="" className="flex flex-col gap-3">
      <ul className="flex flex-col gap-1">
        {card.methods.map((m) => (
          <li key={`${m.type}-${m.target}`} className="flex items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
            <span className="flex-1 break-all">{m.type === 'mailto' ? `邮件至 ${m.target}` : m.target}</span>
            <button
              type="button"
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-0.5 text-sm hover:bg-[var(--lumi-surface-hover)]"
              onClick={() => void open(m.type, m.target)}
            >
              记录我主动打开
            </button>
          </li>
        ))}
      </ul>
      {card.oneClickDeclared && (
        <NoteText>原文声明支持 One-Click 一键退订；LumiRSS 绝不代发——请在你自己的邮件客户端完成。</NoteText>
      )}
      {card.listHelp !== '' && <NoteText>帮助页：{card.listHelp}</NoteText>}
      {note !== '' && <StatusLine tone="ok">{note}</StatusLine>}
      <StatusLine tone="info">已记录打开 {card.opens.length} 次</StatusLine>
      <NoteText>{card.honestyNote}</NoteText>
    </div>
  )
}
