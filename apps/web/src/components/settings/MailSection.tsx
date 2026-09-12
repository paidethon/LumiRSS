/** MailSection — phase2 G6：设置 → 邮件简报。
 *
 * 两个子块：
 * - HTTP 转发入口（webhook，P0-06h wave 2 诚实化）：这不是「收信地址」
 *   ——简报出版商无法向它发送电子邮件。它是机器对机器的 HTTP POST
 *   入口：投递方用 ingest 绝对 URL + Bearer 密钥 POST 内容，Lumi 落库
 *   并（在配置了自动订阅时）转投 FreshRSS。密钥只在创建时显示一次；
 *   subscribeFailed 时诚实展示自动订阅失败原因与可订阅的 Atom 路径；
 *   删除立即生效。
 * - 每日摘要（digest）：启用开关 / 发送时刻（0–23）/ 来源（稍后读 /
 *   收藏）/ 条数上限 / SMTP 主机·端口·用户·发件·收件 / SMTP 密码
 *   （write-only：不回显，留空 = 不改动）；保存 → PUT；「发送摘要」
 *   服务端取材（无条目 → 422 no_digest_items 原样透出，绝不发空邮件）；
 *   lastSentAt / lastError 诚实展示。
 *
 * 所有 HTTP 经 src/api/client.ts；loading / empty / error 三态齐备。 */

import { useState } from 'react'
import { AlertCircle, CheckCircle2, Copy, MailPlus, Plus, Send, Trash2 } from 'lucide-react'
import {
  useCreateMailBridgeListMutation,
  useDeleteMailBridgeListMutation,
  useDigestSettings,
  useMailBridgeLists,
  useSendDigestNowMutation,
  useUpdateDigestSettingsMutation,
} from '../../api/queries'
import type { DigestSettings, MailBridgeListCreated } from '../../api/client'
import { formatTimestamp } from '../../lib/date-format'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { IconButton } from '../ui/IconButton'
import { Select } from '../ui/Select'
import { Skeleton } from '../ui/Skeleton'
import { Switch } from '../ui/Switch'
import { cx } from '../ui/cx'

const inputCls = cx(
  'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm',
  'text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]',
  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

function copyText(text: string): void {
  void navigator.clipboard?.writeText(text)
}

function SecretField({
  label,
  value,
  copyLabel,
  mono,
}: {
  label: string
  value: string
  copyLabel: string
  mono?: boolean
}) {
  return (
    <div className="flex items-center gap-1.5">
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-[var(--lumi-text-primary)]">{label}</p>
        <code
          className={cx(
            'mt-0.5 block truncate rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-surface-selected)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]',
            mono === true && 'font-mono',
          )}
        >
          {value}
        </code>
      </div>
      <IconButton
        icon={<Copy aria-hidden className="size-3.5" />}
        label={copyLabel}
        title={copyLabel}
        size="sm"
        onClick={() => copyText(value)}
      />
    </div>
  )
}

// ---- HTTP 转发入口（webhook bridge lists） ----

/** ingest 路径 → 绝对 URL（webhook 是机器对机器入口，投递方需要完整
 * 地址；相对路径复制出去不可用）。 */
function ingestAbsoluteUrl(uuid: string): string {
  return `${window.location.origin}/api/mail/ingest/${uuid}`
}

function BridgeListsBlock() {
  const lists = useMailBridgeLists()
  const createMutation = useCreateMailBridgeListMutation()
  const removeMutation = useDeleteMailBridgeListMutation()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [name, setName] = useState('')
  const [created, setCreated] = useState<MailBridgeListCreated | null>(null)

  const closeDialog = () => {
    setDialogOpen(false)
    setName('')
    setCreated(null)
    createMutation.reset()
  }

  const save = () => {
    createMutation.mutate(name.trim(), { onSuccess: (result) => setCreated(result) })
  }

  return (
    <section aria-label="HTTP 转发入口" className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">HTTP 转发入口（webhook）</h3>
          <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            这是 HTTP POST 转发入口，不是电子邮箱地址：简报出版商无法向它发送电子邮件。
            投递方（自动化脚本 / 机器）用 ingest 绝对 URL 携带 Bearer 密钥 POST
            内容，经 Lumi 落库转投。密钥只在创建时显示一次。
          </p>
        </div>
        <Button
          size="sm"
          variant="secondary"
          className="shrink-0"
          onClick={() => setDialogOpen(true)}
        >
          <Plus aria-hidden className="size-3.5" />
          新增
        </Button>
      </div>

      {lists.isPending && (
        <div className="mt-3 flex flex-col gap-2" aria-label="转发入口加载中">
          <Skeleton className="h-10 w-full" />
        </div>
      )}

      {lists.isError && (
        <div role="alert" className="mt-3 text-sm">
          <p className="flex items-center gap-1.5 text-[var(--lumi-danger)]">
            <AlertCircle aria-hidden className="size-3.5 shrink-0" />
            转发入口加载失败
          </p>
          <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">{lists.error.message}</p>
          <Button size="sm" variant="secondary" className="mt-2" onClick={() => lists.refetch()}>
            重试
          </Button>
        </div>
      )}

      {lists.isSuccess && lists.data.items.length === 0 && (
        <p className="mt-3 text-xs text-[var(--lumi-text-tertiary)]">还没有转发入口。</p>
      )}

      {lists.isSuccess && lists.data.items.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2" aria-label="转发入口列表">
          {lists.data.items.map((item) => (
            <li
              key={item.uuid}
              className="flex items-center gap-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-[var(--lumi-text-primary)]">
                  {item.name}
                </p>
                <p className="mt-0.5 truncate text-xs text-[var(--lumi-text-tertiary)]">
                  {ingestAbsoluteUrl(item.uuid)}
                  {item.createdAt !== '' && ` · 创建于 ${formatTimestamp(item.createdAt)}`}
                </p>
              </div>
              <IconButton
                icon={<Trash2 aria-hidden className="size-4" />}
                label={`删除 ${item.name}`}
                title="删除转发入口"
                onClick={() => removeMutation.mutate(item.uuid)}
                disabled={removeMutation.isPending}
              />
            </li>
          ))}
        </ul>
      )}

      <Dialog
        open={dialogOpen}
        onClose={closeDialog}
        title={created !== null ? '转发入口已创建' : '新增转发入口'}
        footer={
          created !== null ? (
            <Button variant="primary" size="sm" onClick={closeDialog}>
              完成
            </Button>
          ) : (
            <>
              <Button variant="ghost" size="sm" onClick={closeDialog}>
                取消
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={save}
                disabled={name.trim() === '' || createMutation.isPending}
              >
                {createMutation.isPending ? '创建中…' : '创建'}
              </Button>
            </>
          )
        }
      >
        {created !== null ? (
          // 一次性密钥面板：secret 只在创建响应出现，关闭后不可再看。
          <div role="status" className="flex flex-col gap-3">
            <p className="flex items-center gap-1.5 text-sm font-medium text-[var(--lumi-text-primary)]">
              <CheckCircle2 aria-hidden className="size-4 text-[var(--lumi-category-green)]" />
              已创建「{created.name}」
            </p>
            <div className="flex flex-col gap-2.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
              <SecretField
                label="Ingest 地址（绝对 URL，POST 目标）"
                value={ingestAbsoluteUrl(created.uuid)}
                copyLabel="复制 ingest 地址"
                mono
              />
              <SecretField label="Bearer 密钥" value={created.secret} copyLabel="复制密钥" mono />
            </div>
            {/* P0-06i：FreshRSS 自动订阅失败如实呈现——入口本身可用，
                但「转投 FreshRSS」这一段没有发生；给出可手工订阅的 Atom。 */}
            {created.subscribeFailed != null && created.subscribeFailed !== '' && (
              <div
                role="alert"
                className="flex items-start gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-xs leading-relaxed text-[var(--lumi-danger)]"
              >
                <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                <span className="min-w-0">
                  <span className="block font-medium">FreshRSS 自动订阅失败：{created.subscribeFailed}</span>
                  <span className="mt-0.5 block break-all">
                    内容仍会经此入口接收；如需进入 RSS 流，可在 FreshRSS 手工订阅：
                    {created.atomPath != null && created.atomPath !== ''
                      ? `${window.location.origin}${created.atomPath}`
                      : '（Atom 路径未返回）'}
                  </span>
                </span>
              </div>
            )}
            <p className="text-xs leading-relaxed text-[var(--lumi-danger)]">
              密钥仅显示一次，请立即保存；关闭后无法再次查看。
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <label htmlFor="mail-bridge-name" className="block text-xs font-medium text-[var(--lumi-text-primary)]">
              名称
            </label>
            <input
              id="mail-bridge-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：日记投递"
              className={inputCls}
            />
            {createMutation.isError && (
              <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
                <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                {createMutation.error.message}
              </p>
            )}
          </div>
        )}
      </Dialog>
    </section>
  )
}

// ---- 每日摘要（digest） ----

interface DigestFormState {
  enabled: boolean
  hour: number
  source: 'read_later' | 'starred'
  limitCount: number
  smtpHost: string
  smtpPort: number
  smtpUser: string
  fromAddr: string
  toAddr: string
  smtpPassword: string
}

function formStateOf(settings: DigestSettings): DigestFormState {
  return {
    enabled: settings.enabled,
    hour: settings.hour,
    source: settings.source === 'starred' ? 'starred' : 'read_later',
    limitCount: settings.limitCount,
    smtpHost: settings.smtpHost,
    smtpPort: settings.smtpPort,
    smtpUser: settings.smtpUser,
    fromAddr: settings.fromAddr,
    toAddr: settings.toAddr,
    smtpPassword: '', // write-only：密码永不回显，留空 = 不改动
  }
}

const HOUR_OPTIONS = Array.from({ length: 24 }, (_, h) => ({
  value: String(h),
  label: `${String(h).padStart(2, '0')}:00`,
}))

function DigestForm({ settings }: { settings: DigestSettings }) {
  const saveMutation = useUpdateDigestSettingsMutation()
  const sendMutation = useSendDigestNowMutation()
  const [form, setForm] = useState<DigestFormState>(() => formStateOf(settings))

  // 表单基线 = 挂载时的服务端数据；父组件用 settings 内容作 key：
  // 保存成功重拉后（如 passwordConfigured 翻转）表单整体重挂同步服务端
  // 真值，同时保留「用户编辑中不被无关重拉覆盖」的性质（数据未变 →
  // key 不变 → 不重挂）。

  const update = <K extends keyof DigestFormState>(key: K, value: DigestFormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const save = () => {
    saveMutation.mutate({
      enabled: form.enabled,
      hour: form.hour,
      source: form.source,
      limitCount: form.limitCount,
      smtpHost: form.smtpHost,
      smtpPort: form.smtpPort,
      smtpUser: form.smtpUser,
      fromAddr: form.fromAddr,
      toAddr: form.toAddr,
      ...(form.smtpPassword !== '' ? { smtpPassword: form.smtpPassword } : {}),
    })
  }

  const sendNow = () => {
    // P0-06b：服务端取材——空选择 = 按设置来源/上限取最新条目；
    // 无可发条目时 BFF 返回 422 no_digest_items（错误消息原样透出，
    // 绝不发空邮件）。SMTP 未配置同理原样透出。
    sendMutation.mutate([])
  }

  return (
    <div className="mt-4 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-4">
        <h3 id="digest-enabled-title" className="text-sm font-medium text-[var(--lumi-text-primary)]">
          启用每日摘要
        </h3>
        <Switch
          checked={form.enabled}
          labelledby="digest-enabled-title"
          label="每日摘要开关"
          onCheckedChange={(checked) => update('enabled', checked)}
        />
      </div>

      <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
        <div>
          <label htmlFor="digest-hour" className="mb-1 block text-xs font-medium text-[var(--lumi-text-primary)]">
            发送时刻
          </label>
          <Select
            id="digest-hour"
            aria-label="发送时刻"
            value={String(form.hour)}
            options={HOUR_OPTIONS}
            onChange={(e) => update('hour', Number(e.target.value))}
            className="w-full"
          />
        </div>
        <div>
          <label htmlFor="digest-source" className="mb-1 block text-xs font-medium text-[var(--lumi-text-primary)]">
            摘要来源
          </label>
          <Select
            id="digest-source"
            aria-label="摘要来源"
            value={form.source}
            options={[
              { value: 'read_later', label: '稍后读' },
              { value: 'starred', label: '收藏' },
            ]}
            onChange={(e) => update('source', e.target.value === 'starred' ? 'starred' : 'read_later')}
            className="w-full"
          />
        </div>
        <div>
          <label htmlFor="digest-limit" className="mb-1 block text-xs font-medium text-[var(--lumi-text-primary)]">
            条数上限
          </label>
          <input
            id="digest-limit"
            type="number"
            min={1}
            max={100}
            aria-label="条数上限"
            value={Number.isNaN(form.limitCount) ? '' : form.limitCount}
            onChange={(e) => update('limitCount', Number(e.target.value))}
            className={inputCls}
          />
        </div>
        <div>
          <label htmlFor="digest-smtp-host" className="mb-1 block text-xs font-medium text-[var(--lumi-text-primary)]">
            SMTP 服务器
          </label>
          <input
            id="digest-smtp-host"
            value={form.smtpHost}
            onChange={(e) => update('smtpHost', e.target.value)}
            placeholder="smtp.example.com"
            aria-label="SMTP 服务器"
            className={inputCls}
          />
        </div>
        <div>
          <label htmlFor="digest-smtp-port" className="mb-1 block text-xs font-medium text-[var(--lumi-text-primary)]">
            SMTP 端口
          </label>
          <input
            id="digest-smtp-port"
            type="number"
            min={1}
            max={65535}
            aria-label="SMTP 端口"
            value={Number.isNaN(form.smtpPort) ? '' : form.smtpPort}
            onChange={(e) => update('smtpPort', Number(e.target.value))}
            className={inputCls}
          />
        </div>
        <div>
          <label htmlFor="digest-smtp-user" className="mb-1 block text-xs font-medium text-[var(--lumi-text-primary)]">
            SMTP 用户名
          </label>
          <input
            id="digest-smtp-user"
            value={form.smtpUser}
            onChange={(e) => update('smtpUser', e.target.value)}
            aria-label="SMTP 用户名"
            className={inputCls}
          />
        </div>
        <div>
          <label htmlFor="digest-from" className="mb-1 block text-xs font-medium text-[var(--lumi-text-primary)]">
            发件地址
          </label>
          <input
            id="digest-from"
            type="email"
            value={form.fromAddr}
            onChange={(e) => update('fromAddr', e.target.value)}
            aria-label="发件地址"
            className={inputCls}
          />
        </div>
        <div>
          <label htmlFor="digest-to" className="mb-1 block text-xs font-medium text-[var(--lumi-text-primary)]">
            收件地址
          </label>
          <input
            id="digest-to"
            type="email"
            value={form.toAddr}
            onChange={(e) => update('toAddr', e.target.value)}
            aria-label="收件地址"
            className={inputCls}
          />
        </div>
      </div>

      <div>
        <label htmlFor="digest-smtp-password" className="mb-1 block text-xs font-medium text-[var(--lumi-text-primary)]">
          SMTP 密码
        </label>
        <input
          id="digest-smtp-password"
          type="password"
          autoComplete="new-password"
          value={form.smtpPassword}
          onChange={(e) => update('smtpPassword', e.target.value)}
          placeholder={settings.passwordConfigured ? '已配置（输入可更新，不回显）' : '未配置'}
          aria-label="SMTP 密码"
          className={inputCls}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="primary"
          onClick={save}
          disabled={saveMutation.isPending}
        >
          {saveMutation.isPending ? '保存中…' : '保存'}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={sendNow}
          disabled={sendMutation.isPending}
        >
          <Send aria-hidden className="size-3.5" />
          {sendMutation.isPending ? '发送中…' : '发送测试摘要'}
        </Button>
        {saveMutation.isSuccess && !saveMutation.isPending && (
          <span role="status" className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
            <CheckCircle2 aria-hidden className="size-3.5 text-[var(--lumi-category-green)]" />
            已保存
          </span>
        )}
        {sendMutation.isSuccess && sendMutation.data !== undefined && (
          <span role="status" className="text-xs text-[var(--lumi-text-secondary)]">
            已触发发送（状态：{sendMutation.data.status}）
          </span>
        )}
      </div>

      {saveMutation.isError && (
        <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          {saveMutation.error.message}
        </p>
      )}
      {sendMutation.isError && (
        <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          {sendMutation.error.message}
        </p>
      )}
    </div>
  )
}

function DigestBlock() {
  const settings = useDigestSettings()

  return (
    <section aria-label="每日摘要" className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <div className="flex items-center gap-2">
        <MailPlus aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">每日摘要</h3>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        每天定时把稍后读或收藏汇总成一封邮件。SMTP 密码只写不读：已配置时输入新密码才会更新。
      </p>

      {settings.isPending && (
        <div className="mt-3 flex flex-col gap-2" aria-label="摘要设置加载中">
          <Skeleton className="h-9 w-2/3" />
          <Skeleton className="h-9 w-full" />
        </div>
      )}

      {settings.isError && (
        <div role="alert" className="mt-3 text-sm">
          <p className="flex items-center gap-1.5 text-[var(--lumi-danger)]">
            <AlertCircle aria-hidden className="size-3.5 shrink-0" />
            摘要设置加载失败
          </p>
          <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">{settings.error.message}</p>
          <Button size="sm" variant="secondary" className="mt-2" onClick={() => settings.refetch()}>
            重试
          </Button>
        </div>
      )}

      {settings.isSuccess && settings.data !== undefined && (
        <>
          <DigestForm key={JSON.stringify(settings.data)} settings={settings.data} />
          <p role="status" className="mt-3 text-xs text-[var(--lumi-text-tertiary)]">
            上次发送：{formatTimestamp(settings.data.lastSentAt) === '' ? '从未发送' : formatTimestamp(settings.data.lastSentAt)}
          </p>
          {settings.data.lastError != null && settings.data.lastError !== '' && (
            <p role="alert" className="mt-1 flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
              <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              上次错误：{settings.data.lastError}
            </p>
          )}
        </>
      )}
    </section>
  )
}

export function MailSection() {
  return (
    <div className="flex flex-col gap-4 py-1">
      <BridgeListsBlock />
      <DigestBlock />
    </div>
  )
}
