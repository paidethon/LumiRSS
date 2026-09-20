/** MailToolsPanels — W6 邮件域工具面板（F104/F105/F106/F110）。
 *
 * - ParseDebugDialog（F104）：单封邮件「解析对照」——结构快照树、
 *   附件元数据、正文长度、HTML part 有无、外链跟踪拦截计数；零写入。
 * - ThreadDialog（F110）：沿 In-Reply-To/References 的有序会话链；
 *   缺父（parent_missing）/ 断环（cycle_broken）诚实降级展示。
 * - MailRulesPanel（F105）：接收规则 CRUD / 排序 / 启停 / 样本试跑。
 * - BackfillWizard（F106）：历史回填向导——范围 → dry_run 预览 →
 *   执行 → 结果（uidvalidity 变更中止诚实呈现）。
 *
 * 所有 HTTP 经 src/api/client.ts（queries.ts hooks）；fetch 在测试中
 * 全部 stub。 */

import { useEffect, useState } from 'react'
import { AlertCircle, ArrowDown, ArrowUp, CheckCircle2, Loader2, Plus, Trash2 } from 'lucide-react'

import { ApiError } from '../../api/client'
import type { MailParseDebug, MailRule, MailThread } from '../../api/client'
import {
  useCreateMailRuleMutation,
  useDeleteMailRuleMutation,
  useMailBackfillMutation,
  useMailParseDebugMutation,
  useMailRules,
  useMailThreadMutation,
  useMoveMailRuleMutation,
  usePatchMailRuleMutation,
  useDryRunMailRuleMutation,
} from '../../api/queries'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

const panelInputCls = cx(
  'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm',
  'text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]',
  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
)

function errorText(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return fallback
}

// ---- F104：解析对照 ----------------------------------------------------------

/** 结构快照节点：multipart 树递归；未知结构诚实显示 raw。 */
function StructureNode({ node, depth }: { node: unknown; depth: number }) {
  if (typeof node !== 'object' || node === null) {
    return <p className="text-xs text-[var(--lumi-text-tertiary)]">{String(node)}</p>
  }
  const record = node as Record<string, unknown>
  const label =
    typeof record.type === 'string'
      ? String(record.type)
      : typeof record.disposition === 'string'
        ? String(record.disposition)
        : '（未知节点）'
  const childParts = Array.isArray(record.parts) ? record.parts : []
  const extras = Object.entries(record).filter(
    ([key]) => !['type', 'parts', 'disposition'].includes(key),
  )
  return (
    <div className={cx('flex flex-col gap-0.5', depth > 0 && 'border-l border-[var(--lumi-separator)] pl-2')}>
      <p className="text-xs text-[var(--lumi-text-secondary)]" data-structure-node={label}>
        {label}
        {extras.map(([key, value]) => (
          <span key={key} className="ml-1.5 text-[var(--lumi-text-tertiary)]">
            {key}={typeof value === 'object' ? JSON.stringify(value) : String(value)}
          </span>
        ))}
      </p>
      {childParts.map((child, index) => (
        <StructureNode key={index} node={child} depth={depth + 1} />
      ))}
    </div>
  )
}

export function ParseDebugDialog({
  listUuid,
  messageId,
  onClose,
}: {
  listUuid: string
  messageId: string
  onClose: () => void
}) {
  const debug = useMailParseDebugMutation()
  useEffect(() => {
    debug.mutate({ listUuid, messageId })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 挂载/目标变化时拉取一次
  }, [listUuid, messageId])
  const data: MailParseDebug | undefined = debug.data
  return (
    <Dialog
      open
      onClose={onClose}
      title={`解析对照：${messageId}`}
      footer={
        <Button variant="primary" size="sm" onClick={onClose}>
          关闭
        </Button>
      }
    >
      <div className="flex flex-col gap-3 text-sm" data-mail-parse-debug="">
        {debug.isPending && (
          <div aria-label="解析对照加载中">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="mt-2 h-6 w-full" />
          </div>
        )}
        {debug.isError && (
          <p role="alert" className="flex items-start gap-1.5 text-xs text-[var(--lumi-danger)]">
            <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            {errorText(debug.error, '解析对照加载失败。')}
          </p>
        )}
        {data && (
          <>
            <ul className="grid grid-cols-2 gap-1.5 text-xs text-[var(--lumi-text-secondary)]" data-parse-stats="">
              <li>主题存在：{data.subjectPresent ? '是' : '否'}</li>
              <li>发件人（脱敏）：{data.fromDisplay || '—'}</li>
              <li>正文长度：{data.textLen} 字符</li>
              <li>HTML part：{data.htmlPartPresent ? '有' : '无'}</li>
              <li>条目标题一致：{data.itemDiffSummary.titleMatches ? '是' : '否'}</li>
              <li>跟踪像素拦截：{data.itemDiffSummary.trackingPixelsBlocked}</li>
            </ul>
            <div>
              <p className="text-xs font-medium text-[var(--lumi-text-primary)]">附件（{data.attachmentMeta.length}）</p>
              <ul className="mt-0.5 flex flex-col gap-0.5">
                {data.attachmentMeta.map((item) => (
                  <li key={item.filename} className="text-xs text-[var(--lumi-text-tertiary)]">
                    {item.filename} · {item.bytes} B
                  </li>
                ))}
                {data.attachmentMeta.length === 0 && (
                  <li className="text-xs text-[var(--lumi-text-tertiary)]">无附件。</li>
                )}
              </ul>
            </div>
            <div>
              <p className="text-xs font-medium text-[var(--lumi-text-primary)]">结构快照</p>
              {data.structure ? (
                <div className="mt-1" data-structure-tree="">
                  <StructureNode node={data.structure} depth={0} />
                </div>
              ) : (
                <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">（该邮件没有结构快照——落库于快照功能之前。）</p>
              )}
            </div>
          </>
        )}
      </div>
    </Dialog>
  )
}

// ---- F110：查看会话 ----------------------------------------------------------

export function ThreadDialog({
  listUuid,
  messageId,
  onClose,
}: {
  listUuid: string
  messageId: string
  onClose: () => void
}) {
  const thread = useMailThreadMutation()
  useEffect(() => {
    thread.mutate({ listUuid, messageId })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 挂载/目标变化时拉取一次
  }, [listUuid, messageId])
  const data: MailThread | undefined = thread.data
  return (
    <Dialog
      open
      onClose={onClose}
      title={`查看会话：${messageId}`}
      footer={
        <Button variant="primary" size="sm" onClick={onClose}>
          关闭
        </Button>
      }
    >
      <div className="flex flex-col gap-2 text-sm" data-mail-thread="">
        {thread.isPending && (
          <div aria-label="会话加载中">
            <Skeleton className="h-6 w-full" />
            <Skeleton className="mt-2 h-6 w-2/3" />
          </div>
        )}
        {thread.isError && (
          <p role="alert" className="flex items-start gap-1.5 text-xs text-[var(--lumi-danger)]">
            <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            {errorText(thread.error, '会话加载失败。')}
          </p>
        )}
        {data && (
          <>
            <ol className="flex flex-col gap-1" data-thread-chain="">
              {data.chain.map((node) => (
                <li
                  key={node.id}
                  className={cx(
                    'rounded-[var(--lumi-radius-md)] border px-2 py-1.5 text-xs',
                    node.current
                      ? 'border-[var(--lumi-accent)]/40 bg-[var(--lumi-accent-soft)]'
                      : 'border-[var(--lumi-border)]',
                  )}
                  data-thread-node={node.id}
                >
                  <span className="block truncate text-[var(--lumi-text-primary)]">
                    {node.subject}
                    {node.current ? '（当前）' : ''}
                  </span>
                  <span className="text-[var(--lumi-text-tertiary)]">{node.date}</span>
                </li>
              ))}
            </ol>
            {data.reason === 'parent_missing' && (
              <p className="text-xs text-[var(--lumi-text-tertiary)]" data-thread-note="">
                会话根缺失（父邮件不在本入口）——链从本封开始。
              </p>
            )}
            {data.cycleBroken && (
              <p className="text-xs text-[var(--lumi-text-tertiary)]" data-thread-note="">
                检测到引用环，已断开展示。
              </p>
            )}
          </>
        )}
      </div>
    </Dialog>
  )
}

// ---- F105：接收规则 ----------------------------------------------------------

export function MailRulesPanel({ listUuid, onClose }: { listUuid: string; onClose: () => void }) {
  const rules = useMailRules(listUuid)
  const create = useCreateMailRuleMutation(listUuid)
  const patch = usePatchMailRuleMutation(listUuid)
  const move = useMoveMailRuleMutation(listUuid)
  const del = useDeleteMailRuleMutation(listUuid)
  const dryRun = useDryRunMailRuleMutation(listUuid)

  const [field, setField] = useState<'from' | 'subject'>('from')
  const [op, setOp] = useState<'contains' | 'equals'>('contains')
  const [value, setValue] = useState('')
  const [action, setAction] = useState<'allow' | 'deny'>('allow')
  const [createError, setCreateError] = useState<string | null>(null)
  const [sampleField, setSampleField] = useState<'from' | 'subject'>('from')
  const [sampleValue, setSampleValue] = useState('')

  const submitCreate = () => {
    setCreateError(null)
    create.mutate(
      { field, op, value: value.trim(), action },
      {
        onSuccess: () => setValue(''),
        onError: (error) => setCreateError(errorText(error, '规则创建失败。')),
      },
    )
  }

  const items = rules.data?.items ?? []

  return (
    <Dialog
      open
      onClose={onClose}
      title="接收规则"
      footer={
        <Button variant="primary" size="sm" onClick={onClose}>
          完成
        </Button>
      }
    >
      <div className="flex flex-col gap-3 text-sm" data-mail-rules-panel="">
        <p className="text-xs text-[var(--lumi-text-secondary)]">
          规则按优先级自上而下生效，首条命中决定接收/拒绝；无规则 = 全部接收。deny
          命中的邮件会被丢弃（不入库）。
        </p>

        {rules.isPending && <Skeleton className="h-16 w-full" />}
        {rules.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {errorText(rules.error, '规则加载失败。')}
          </p>
        )}
        {rules.isSuccess && items.length === 0 && (
          <p className="text-xs text-[var(--lumi-text-tertiary)]" data-rules-empty="">
            还没有规则。
          </p>
        )}
        <ul className="flex flex-col gap-1.5" data-rules-list="">
          {items.map((rule: MailRule, index: number) => (
            <li
              key={rule.id}
              className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5"
              data-rule-id={rule.id}
            >
              <span
                className={cx(
                  'shrink-0 rounded-[var(--lumi-radius-full)] px-1.5 py-0.5 text-[10px]',
                  rule.enabled
                    ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
                    : 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]',
                )}
              >
                {index + 1}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-secondary)]">
                {rule.field === 'from' ? '发件人' : '主题'} {rule.op === 'contains' ? '包含' : '等于'}
                「{rule.value}」→ {rule.action === 'deny' ? '拒绝' : '接收'}
              </span>
              <label className="flex shrink-0 items-center gap-1 text-[10px] text-[var(--lumi-text-tertiary)]">
                <input
                  type="checkbox"
                  aria-label={`启用规则 ${rule.id}`}
                  checked={rule.enabled}
                  disabled={patch.isPending}
                  onChange={(event) => patch.mutate({ ruleId: rule.id, patch: { enabled: event.target.checked } })}
                  className="size-3.5 accent-[var(--lumi-accent)]"
                />
                启用
              </label>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`上移规则 ${rule.id}`}
                disabled={index === 0 || move.isPending}
                onClick={() => move.mutate({ ruleId: rule.id, direction: 'up' })}
              >
                <ArrowUp aria-hidden className="size-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`下移规则 ${rule.id}`}
                disabled={index === items.length - 1 || move.isPending}
                onClick={() => move.mutate({ ruleId: rule.id, direction: 'down' })}
              >
                <ArrowDown aria-hidden className="size-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`删除规则 ${rule.id}`}
                disabled={del.isPending}
                onClick={() => del.mutate(rule.id)}
              >
                <Trash2 aria-hidden className="size-3.5" />
              </Button>
            </li>
          ))}
        </ul>

        <div className="flex flex-col gap-1.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5">
          <p className="text-xs font-medium text-[var(--lumi-text-primary)]">新增规则</p>
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <select
              aria-label="新规则字段"
              value={field}
              onChange={(event) => setField(event.target.value === 'subject' ? 'subject' : 'from')}
              className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
            >
              <option value="from">发件人</option>
              <option value="subject">主题</option>
            </select>
            <select
              aria-label="新规则匹配方式"
              value={op}
              onChange={(event) => setOp(event.target.value === 'equals' ? 'equals' : 'contains')}
              className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
            >
              <option value="contains">包含</option>
              <option value="equals">等于</option>
            </select>
            <input
              aria-label="新规则匹配值"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder="匹配值"
              className={cx(panelInputCls, 'min-w-0 flex-1')}
            />
            <select
              aria-label="新规则动作"
              value={action}
              onChange={(event) => setAction(event.target.value === 'deny' ? 'deny' : 'allow')}
              className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
            >
              <option value="allow">接收</option>
              <option value="deny">拒绝</option>
            </select>
            <Button
              variant="secondary"
              size="sm"
              data-rule-create=""
              disabled={value.trim() === '' || create.isPending}
              onClick={submitCreate}
            >
              <Plus aria-hidden className="size-3.5" />
              {create.isPending ? '添加中…' : '添加'}
            </Button>
          </div>
          {createError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              {createError}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5">
          <p className="text-xs font-medium text-[var(--lumi-text-primary)]">样本试跑（零写入）</p>
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <select
              aria-label="试跑字段"
              value={sampleField}
              onChange={(event) => setSampleField(event.target.value === 'subject' ? 'subject' : 'from')}
              className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
            >
              <option value="from">发件人</option>
              <option value="subject">主题</option>
            </select>
            <input
              aria-label="试跑样本值"
              value={sampleValue}
              onChange={(event) => setSampleValue(event.target.value)}
              placeholder="样本"
              className={cx(panelInputCls, 'min-w-0 flex-1')}
            />
            <Button
              variant="secondary"
              size="sm"
              data-rule-dryrun=""
              disabled={sampleValue.trim() === '' || dryRun.isPending}
              onClick={() => dryRun.mutate({ field: sampleField, value: sampleValue.trim() })}
            >
              {dryRun.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : '试跑'}
            </Button>
          </div>
          {dryRun.data && (
            <p role="status" className="text-xs text-[var(--lumi-text-secondary)]" data-dryrun-result="">
              {dryRun.data.matchedRule === null
                ? dryRun.data.explanation
                : `命中第 ${dryRun.data.matchedRule.priority + 1} 条 → ${dryRun.data.matchedRule.action === 'deny' ? '拒绝' : '接收'}；${dryRun.data.explanation}`}
            </p>
          )}
          {dryRun.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              {errorText(dryRun.error, '试跑失败。')}
            </p>
          )}
        </div>
      </div>
    </Dialog>
  )
}

// ---- F106：历史回填向导 -------------------------------------------------------

export function BackfillWizard() {
  const backfill = useMailBackfillMutation()
  // step: range → preview(dry_run) → done
  const [since, setSince] = useState('')
  const [step, setStep] = useState<'range' | 'done'>('range')

  const runPreview = () => {
    backfill.mutate(
      { since: since.trim() === '' ? undefined : since.trim(), dryRun: true },
      { onSuccess: () => setStep('done') },
    )
  }
  const runExecute = () => {
    backfill.mutate({ since: since.trim() === '' ? undefined : since.trim(), dryRun: false })
  }

  const preview = backfill.data
  return (
    <div
      className="mt-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
      data-mail-backfill=""
    >
      <p className="text-xs font-medium text-[var(--lumi-text-primary)]">历史回填（IMAP）</p>
      <p className="mt-0.5 text-xs text-[var(--lumi-text-tertiary)]">
        把邮箱中既有新闻邮件按范围拉回（同步有界 ≤200 封）；先试运行预览，再执行。重复邮件自动去重。
      </p>
      {step === 'range' ? (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <label className="flex items-center gap-1.5">
            <span className="text-[var(--lumi-text-secondary)]">起始日期</span>
            <input
              type="date"
              aria-label="回填起始日期"
              value={since}
              onChange={(event) => setSince(event.target.value)}
              className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
            />
          </label>
          <Button variant="secondary" size="sm" data-backfill-preview="" disabled={backfill.isPending} onClick={runPreview}>
            {backfill.isPending ? '试运行中…' : '试运行预览'}
          </Button>
        </div>
      ) : (
        <div className="mt-2 flex flex-col gap-1.5" data-backfill-result="">
          {preview?.dryRun === true && (
            <>
              <p className="text-xs text-[var(--lumi-text-secondary)]">
                预览：匹配 {preview.matched ?? preview.sample?.length ?? 0} 封
                {preview.uidvalidity != null && preview.uidvalidity !== '' ? ` · uidvalidity ${preview.uidvalidity}` : ''}
                {preview.note ? ` · ${preview.note}` : ''}
              </p>
              <ul className="flex flex-col gap-0.5">
                {(preview.sample ?? []).slice(0, 8).map((item) => (
                  <li key={item.uid} className="truncate text-xs text-[var(--lumi-text-tertiary)]">
                    #{item.uid} {item.subject} · {item.date}
                  </li>
                ))}
              </ul>
              <div className="flex gap-2">
                <Button
                  variant="danger"
                  size="sm"
                  data-backfill-execute=""
                  disabled={backfill.isPending}
                  onClick={runExecute}
                >
                  {backfill.isPending ? '回填中…' : '执行回填'}
                </Button>
                <Button variant="ghost" size="sm" disabled={backfill.isPending} onClick={() => setStep('range')}>
                  重选范围
                </Button>
              </div>
            </>
          )}
          {preview?.dryRun !== true && preview && (
            <div className="text-xs text-[var(--lumi-text-secondary)]">
              {preview.aborted ? (
                <p role="alert" className="text-[var(--lumi-danger)]">
                  已中止：{preview.reason === 'uidvalidity_changed' ? '邮箱 uidvalidity 已变更（服务器端邮件有变动）' : (preview.reason ?? '未知原因')}
                </p>
              ) : (
                <p role="status" className="flex items-center gap-1.5">
                  <CheckCircle2 aria-hidden className="size-3.5 text-[var(--lumi-success)]" />
                  处理 {preview.processed ?? 0} 封：新建 {preview.created ?? 0}，重复跳过 {preview.skippedDup ?? 0}
                  {(preview.failed ?? []).length > 0 ? `，失败 ${(preview.failed ?? []).length}` : ''}
                </p>
              )}
              <Button variant="ghost" size="sm" className="mt-1" onClick={() => setStep('range')}>
                再跑一次
              </Button>
            </div>
          )}
        </div>
      )}
      {backfill.isError && (
        <p role="alert" className="mt-2 flex items-start gap-1.5 text-xs text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          {errorText(backfill.error, '回填失败。')}
        </p>
      )}
    </div>
  )
}

/** 输入 Message-ID 后进入 解析对照 / 查看会话 的门（邮件标识不在
 * bridge list 行上——由用户从邮件详情/通知粘贴）。 */
export function MessageIdGateDialog({
  kind,
  listUuid,
  onClose,
}: {
  kind: 'parse' | 'thread'
  listUuid: string
  onClose: () => void
}) {
  const [messageId, setMessageId] = useState('')
  const [submitted, setSubmitted] = useState<string | null>(null)
  if (submitted !== null) {
    return kind === 'parse' ? (
      <ParseDebugDialog listUuid={listUuid} messageId={submitted} onClose={onClose} />
    ) : (
      <ThreadDialog listUuid={listUuid} messageId={submitted} onClose={onClose} />
    )
  }
  return (
    <Dialog
      open
      onClose={onClose}
      title={kind === 'parse' ? '解析对照：输入邮件 Message-ID' : '查看会话：输入邮件 Message-ID'}
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={messageId.trim() === ''}
            onClick={() => setSubmitted(messageId.trim())}
          >
            确定
          </Button>
        </>
      }
    >
      <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
        Message-ID（形如 m1@example.com）
        <input
          value={messageId}
          onChange={(event) => setMessageId(event.target.value)}
          aria-label="邮件 Message-ID"
          className={panelInputCls}
        />
      </label>
    </Dialog>
  )
}
