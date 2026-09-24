/** MailDetailDialog — 邮件详情（N125 附件 / N126 正文显示模式 /
 * N127 来源身份提示）。
 *
 * - 消息清单（每列表有界 ≤50）→ 点开详情；
 * - N126：文本/HTML 双形态切换。文本取 ingest 时按声明 charset 解码的
 *   纯文本 part；HTML 只渲染 ingest 时的净化产物（渲染前再过一次
 *   DOMPurify——全站渲染终界不变）。切换绝不发起任何远程请求；
 *   被阻止的外链媒体以「被阻止的外链媒体」清单如实列出（≤20）；
 * - N125：附件 chips（名称/大小/类型）+ 安全下载（服务端强制
 *   Content-Disposition: attachment）；oversized/不安全 → 「已跳过」
 *   如实列出并带原因；
 * - N127：中性身份提示（From vs Reply-To 不一致 / 显示名域名不一致）+
 *   明确「客户端不验证 SPF/DKIM，无法确认真实性」——绝无反欺骗断言。
 */

import { useState } from 'react'
import { AlertCircle, FileWarning, Paperclip, ShieldQuestion } from 'lucide-react'
import {
  useMailMessageDetail,
  useMailMessages,
} from '../api/queries'
import { mailAttachmentUrl } from '../api/client'
import { formatTimestamp } from '../lib/date-format'
import { sanitizeArticleHtml } from '../lib/sanitize-article-html'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '未知大小'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** N127：中性提示行（match → 无提示）。 */
function IdentityHints({
  hints,
}: {
  hints: {
    fromAddress?: string
    replyToMismatch?: boolean
    replyToAddress?: string
    displayNameDomainMismatch?: boolean
    displayNameDomains?: string[]
  } | null
}) {
  if (hints == null) return null
  const lines: string[] = []
  if (hints.replyToMismatch === true) {
    lines.push('提示：发件人与回复地址不一致')
    if (hints.replyToAddress) lines.push(`回复地址：${hints.replyToAddress}`)
  }
  if (hints.displayNameDomainMismatch === true) {
    lines.push('提示：发件人显示名中的域名与实际邮箱域不一致')
    if (hints.displayNameDomains?.length) {
      lines.push(`显示名中的域名：${hints.displayNameDomains.join('、')}`)
    }
  }
  if (lines.length === 0) return null
  return (
    <div
      role="note"
      className="flex items-start gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]"
      data-mail-identity-hints=""
    >
      <ShieldQuestion aria-hidden className="mt-0.5 size-3.5 shrink-0" />
      <div className="min-w-0">
        {lines.map((line) => (
          <p key={line}>{line}</p>
        ))}
        <p className="mt-0.5 text-[var(--lumi-text-tertiary)]">
          允许客户端不验证 SPF/DKIM，无法确认真实性。
        </p>
      </div>
    </div>
  )
}

function MessageDetailBody({
  listUuid,
  messageId,
}: {
  listUuid: string
  messageId: string
}) {
  const detail = useMailMessageDetail(listUuid, messageId)
  // N126：文本/HTML 切换是纯本地状态——两种形态都已在 ingest 时落库，
  // 切换绝不请求远程内容（也不请求任何代理）。
  const [mode, setMode] = useState<'text' | 'html'>('text')

  if (detail.isPending) {
    return (
      <div aria-label="邮件详情加载中">
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="mt-2 h-24 w-full" />
      </div>
    )
  }
  if (detail.isError) {
    return (
      <p role="alert" className="flex items-start gap-1.5 text-xs text-[var(--lumi-danger)]">
        <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
        {detail.error instanceof Error ? detail.error.message : '详情加载失败。'}
      </p>
    )
  }
  const data = detail.data
  if (data === undefined) return null
  const hasHtml = data.html.trim() !== ''

  return (
    <div className="flex flex-col gap-3 text-sm" data-mail-message-detail="">
      <IdentityHints hints={data.identityHints} />

      {hasHtml && (
        <div className="flex items-center gap-1.5" role="group" aria-label="正文显示模式">
          <Button
            size="sm"
            variant={mode === 'text' ? 'primary' : 'ghost'}
            data-mail-mode="text"
            aria-pressed={mode === 'text'}
            onClick={() => setMode('text')}
          >
            文本
          </Button>
          <Button
            size="sm"
            variant={mode === 'html' ? 'primary' : 'ghost'}
            data-mail-mode="html"
            aria-pressed={mode === 'html'}
            onClick={() => setMode('html')}
          >
            HTML
          </Button>
        </div>
      )}

      {mode === 'text' ? (
        <div
          className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap break-words text-xs leading-relaxed text-[var(--lumi-text-primary)]"
          data-mail-body-text=""
        >
          {data.text || '（无文本内容）'}
        </div>
      ) : hasHtml ? (
        <div className="max-h-[50vh] overflow-y-auto" data-mail-body-html="">
          <article
            className={cx(
              'text-xs leading-relaxed text-[var(--lumi-text-primary)]',
              '[&_a]:text-[var(--lumi-accent-text)] [&_a]:underline [&_a]:underline-offset-2',
              '[&_blockquote]:border-l-2 [&_blockquote]:border-[var(--lumi-border)] [&_blockquote]:pl-3',
              '[&_p]:my-2 [&_table]:my-2 [&_td]:border [&_td]:px-1 [&_th]:border [&_th]:px-1',
            )}
            // 净化产物 + 渲染前 DOMPurify（第二道边界）。
            dangerouslySetInnerHTML={{ __html: sanitizeArticleHtml(data.html) }}
          />
        </div>
      ) : null}

      {data.blockedMedia.length > 0 && (
        <div
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-2 text-xs"
          data-mail-blocked-media=""
        >
          <p className="font-medium text-[var(--lumi-text-primary)]">
            被阻止的外链媒体（{data.blockedMedia.length}）
          </p>
          <p className="mt-0.5 text-[var(--lumi-text-tertiary)]">
            以下远程地址在接收时已被剥离，本机不会加载：
          </p>
          <ul className="mt-1 flex flex-col gap-0.5">
            {data.blockedMedia.map((url) => (
              <li key={url} className="break-all text-[var(--lumi-text-tertiary)]">
                {url}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(data.attachments.length > 0 || data.skippedAttachments.length > 0) && (
        <div className="flex flex-col gap-1.5" data-mail-attachments="">
          <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-primary)]">
            <Paperclip aria-hidden className="size-3.5" />
            附件（{data.attachments.length}）
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {data.attachments.map((attachment) => (
              <li key={attachment.id}>
                <a
                  href={mailAttachmentUrl(attachment.id)}
                  download={attachment.filename}
                  className={cx(
                    'inline-flex max-w-full items-center gap-1.5 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 py-1 text-xs',
                    'text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)]',
                    'hover:bg-[var(--lumi-surface-hover)]',
                    'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  )}
                  data-mail-attachment-download={attachment.filename}
                >
                  <span className="min-w-0 max-w-48 truncate">{attachment.filename}</span>
                  <span className="shrink-0 text-[var(--lumi-text-tertiary)]">
                    {formatBytes(attachment.size)} · {attachment.mime}
                  </span>
                  <span className="shrink-0 text-[var(--lumi-accent-text)]">下载</span>
                </a>
              </li>
            ))}
          </ul>
          {data.skippedAttachments.length > 0 && (
            <ul className="flex flex-col gap-0.5" data-mail-attachments-skipped="">
              {data.skippedAttachments.map((item, index) => (
                <li
                  key={`${item.filename}-${index}`}
                  className="flex items-start gap-1.5 text-xs text-[var(--lumi-text-tertiary)]"
                >
                  <FileWarning aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                  <span>
                    已跳过：{item.filename}（{formatBytes(item.bytes)}）——{item.reason}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

export function MailDetailDialog({
  listUuid,
  onClose,
}: {
  listUuid: string
  onClose: () => void
}) {
  const messages = useMailMessages(listUuid)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  return (
    <Dialog
      open
      onClose={onClose}
      title={selectedId === null ? '邮件详情：选择邮件' : '邮件详情'}
      panelClassName="max-w-2xl"
      footer={
        selectedId !== null ? (
          <Button variant="ghost" size="sm" onClick={() => setSelectedId(null)}>
            返回列表
          </Button>
        ) : (
          <Button variant="primary" size="sm" onClick={onClose}>
            关闭
          </Button>
        )
      }
    >
      {selectedId === null ? (
        <div className="flex flex-col gap-2 text-sm" data-mail-message-list="">
          {messages.isPending && <Skeleton className="h-16 w-full" />}
          {messages.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              {messages.error instanceof Error
                ? messages.error.message
                : '消息清单加载失败。'}
            </p>
          )}
          {messages.isSuccess && messages.data.items.length === 0 && (
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              该入口还没有收到邮件。
            </p>
          )}
          <ul className="flex max-h-[60vh] flex-col gap-1.5 overflow-y-auto">
            {messages.data?.items.map((item) => (
              <li key={item.messageId}>
                <button
                  type="button"
                  onClick={() => setSelectedId(item.messageId)}
                  data-mail-message={item.messageId}
                  className={cx(
                    'w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-2 text-left',
                    'transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
                    'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  )}
                >
                  <span className="block truncate text-xs font-medium text-[var(--lumi-text-primary)]">
                    {item.subject}
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10px] text-[var(--lumi-text-tertiary)]">
                    <span className="truncate">{item.sender}</span>
                    <span>{formatTimestamp(item.receivedAt) || '—'}</span>
                    {item.attachmentCount > 0 && <span>附件 {item.attachmentCount}</span>}
                    {item.skippedAttachments > 0 && (
                      <span>已跳过 {item.skippedAttachments}</span>
                    )}
                    {item.blockedMediaCount > 0 && (
                      <span>外链媒体已阻止 {item.blockedMediaCount}</span>
                    )}
                    {item.hasIdentityHints && <span>身份提示</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <MessageDetailBody listUuid={listUuid} messageId={selectedId} />
      )}
    </Dialog>
  )
}
