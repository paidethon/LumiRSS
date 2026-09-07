/** RssHubAutoConfigCard — Gate：自动识别 + 自定义站点凭据 + 应用指引。
 *
 * 三块能力，全部诚实边界：
 * - 自动识别：GET /api/v1/rsshub/detect 只探测受限候选
 *   （已配置地址 / compose DNS 名 / 宿主机回环），绝不扫局域网；
 * - 自定义站点凭据：站点 ↔ RSSHub 路由 env 键映射，值写只读。
 *   明确警示：新增站点 + Cookie 不能凭空让没有路由的网站产生 RSS；
 * - 应用链：保存(desired) ≠ 已应用(applied)。BFF 生成 0600 env 文件
 *   （值不回传浏览器），由宿主机 apply_rsshub_config.py（默认
 *   dry-run，固定 --no-deps --force-recreate 只重建 rsshub）执行；
 *   执行成功并验证后再点「标记为已应用」。
 */

import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  Compass,
  KeyRound,
  Loader2,
  Plus,
  Trash2,
} from 'lucide-react'
import {
  useApplyRssHubConfigMutation,
  useCreateRssHubCredentialMutation,
  useDeleteRssHubCredentialMutation,
  useDetectRssHub,
  useRssHubCredentials,
} from '../../api/queries'
import type { RssHubCredentialInput } from '../../api/client'
import { ApiError } from '../../api/client'
import { Button } from '../ui/Button'
import { Select } from '../ui/Select'
import { cx } from '../ui/cx'

const inputClass = cx(
  'w-full min-h-9 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]',
  'bg-[var(--lumi-surface)] px-2.5 text-sm text-[var(--lumi-text-primary)]',
  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
)

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : '请稍后重试。'
}

const SOURCE_LABELS: Record<string, string> = {
  configured: '已配置地址',
  'compose-dns': 'Compose 网络',
  'host-loopback': '宿主机回环',
}

function DetectSection() {
  const detect = useDetectRssHub()

  return (
    <section className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <div className="flex items-center gap-2">
        <Compass aria-hidden className="size-4 text-[var(--lumi-text-tertiary)]" />
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">实例自动识别</h3>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
        仅探测受限候选（已配置地址 / Compose 网络 / 宿主机回环），不扫描局域网。
      </p>
      {detect.isPending && (
        <p role="status" className="mt-2 flex items-center gap-1.5 text-sm text-[var(--lumi-text-secondary)]">
          <Loader2 aria-hidden className="size-3.5 animate-spin" />
          探测中…
        </p>
      )}
      {detect.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          探测失败：{errorText(detect.error)}
        </p>
      )}
      {detect.data !== undefined && (
        <ul className="mt-2 divide-y divide-[var(--lumi-separator)] text-sm">
          {detect.data.candidates.map((candidate) => (
            <li key={candidate.url + candidate.source} className="flex items-center justify-between gap-3 py-1.5">
              <span className="min-w-0">
                <span className="font-mono text-xs text-[var(--lumi-text-primary)]">{candidate.url}</span>
                <span className="ml-2 text-[11px] text-[var(--lumi-text-tertiary)]">
                  {SOURCE_LABELS[candidate.source] ?? candidate.source}
                </span>
              </span>
              <span
                className={cx(
                  'shrink-0 text-xs',
                  candidate.reachable ? 'text-[var(--lumi-accent-text)]' : 'text-[var(--lumi-text-tertiary)]',
                )}
              >
                {candidate.reachable ? `可达 · ${candidate.latencyMs}ms` : '不可达'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

const KIND_OPTIONS = [
  { value: 'cookie', label: 'Cookie' },
  { value: 'token', label: 'Token' },
  { value: 'api_key', label: 'API Key' },
  { value: 'bearer', label: 'Bearer Token' },
  { value: 'other', label: '其他' },
] as const

const EMPTY_FORM: RssHubCredentialInput = {
  name: '',
  domain: '',
  route: '',
  envKey: '',
  kind: 'cookie',
  value: '',
}

function CredentialsSection() {
  const credentials = useRssHubCredentials()
  const create = useCreateRssHubCredentialMutation()
  const remove = useDeleteRssHubCredentialMutation()
  const [form, setForm] = useState<RssHubCredentialInput>(EMPTY_FORM)

  const submit = () => {
    create.mutate(form)
  }

  return (
    <section className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <div className="flex items-center gap-2">
        <KeyRound aria-hidden className="size-4 text-[var(--lumi-text-tertiary)]" />
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">自定义站点凭据</h3>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
        站点 ↔ RSSHub 路由凭据映射（值写只读，仅显示配置状态）。重要：新增站点 + Cookie
        不能凭空产生 RSS——该站点必须已有 RSSHub 路由（或自行开发路由）；envKey
        必须是对应路由真实读取的环境变量名。
      </p>

      {credentials.isPending && (
        <p role="status" className="mt-2 text-xs text-[var(--lumi-text-secondary)]">加载中…</p>
      )}
      {credentials.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          加载失败：{errorText(credentials.error)}
        </p>
      )}
      {credentials.data !== undefined && credentials.data.length === 0 && (
        <p className="mt-2 text-xs text-[var(--lumi-text-secondary)]">还没有自定义凭据。</p>
      )}
      {credentials.data !== undefined && credentials.data.length > 0 && (
        <ul className="mt-2 divide-y divide-[var(--lumi-separator)]">
          {credentials.data.map((entry) => (
            <li key={entry.id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm text-[var(--lumi-text-primary)]">
                  {entry.name}
                  <span className="ml-2 font-mono text-[11px] text-[var(--lumi-text-tertiary)]">{entry.envKey}</span>
                </p>
                <p className="truncate text-[11px] text-[var(--lumi-text-tertiary)]">
                  {entry.domain}
                  {entry.route !== '' && <span> · {entry.route}</span>}
                  <span> · {KIND_OPTIONS.find((k) => k.value === entry.kind)?.label ?? entry.kind}</span>
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className={cx('text-xs', entry.configured ? 'text-[var(--lumi-accent-text)]' : 'text-[var(--lumi-text-tertiary)]')}>
                  {entry.configured ? '已配置' : '未配置'}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`删除凭据 ${entry.name}`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(entry.id)}
                >
                  <Trash2 aria-hidden className="size-3.5" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 grid grid-cols-2 gap-2">
        <input
          className={inputClass}
          aria-label="站点名称"
          placeholder="站点名称（如 微博）"
          value={form.name}
          maxLength={80}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <input
          className={inputClass}
          aria-label="域名"
          placeholder="域名（如 weibo.com）"
          value={form.domain}
          onChange={(e) => setForm({ ...form, domain: e.target.value })}
        />
        <input
          className={inputClass}
          aria-label="路由路径（可选）"
          placeholder="路由路径（可选，如 /weibo/...）"
          value={form.route}
          onChange={(e) => setForm({ ...form, route: e.target.value })}
        />
        <input
          className={inputClass}
          aria-label="环境变量键名"
          placeholder="envKey（如 WEIBO_COOKIES）"
          value={form.envKey}
          onChange={(e) => setForm({ ...form, envKey: e.target.value.toUpperCase() })}
        />
        <Select
          aria-label="凭据类型"
          value={form.kind}
          options={KIND_OPTIONS.map((k) => ({ value: k.value, label: k.label }))}
          onChange={(e) => setForm({ ...form, kind: e.target.value as RssHubCredentialInput['kind'] })}
        />
        <input
          className={inputClass}
          type="password"
          aria-label="凭据值"
          placeholder="凭据值（写只读）"
          autoComplete="off"
          value={form.value}
          onChange={(e) => setForm({ ...form, value: e.target.value })}
        />
      </div>
      <div className="mt-2 flex items-center gap-2">
        <Button size="sm" disabled={create.isPending} onClick={submit}>
          {create.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : <Plus aria-hidden className="size-3.5" />}
          添加凭据
        </Button>
        {create.isError && (
          <span role="alert" className="text-xs text-[var(--lumi-danger)]">{errorText(create.error)}</span>
        )}
      </div>
    </section>
  )
}

/** 应用链说明 + 标记已应用（BFF env 文件物化 + 宿主机脚本）。 */
function ApplyChainSection() {
  const queryClient = useQueryClient()
  const markApplied = useApplyRssHubConfigMutation()
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const materialize = async () => {
    setBusy(true)
    setNote(null)
    try {
      const { materializeRssHubEnvFile } = await import('../../api/client')
      const result = await materializeRssHubEnvFile()
      setNote(
        `已生成 rsshub/${result.fileName}（${result.lineCount} 行，含敏感键 ${result.secretCount} 个、自定义 ${result.customCredentialCount} 个；0600，不回传浏览器）。请在宿主机运行 apply_rsshub_config.py --env-file <BFF数据目录>/rsshub/${result.fileName}（默认 dry-run，加 --apply 生效），健康检查通过后即已应用。`,
      )
      void queryClient.invalidateQueries({ queryKey: ['rsshub-config'] })
    } catch (error) {
      setNote(error instanceof ApiError ? error.message : '生成失败，请稍后重试。')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">应用链（保存 ≠ 已应用）</h3>
      <ol className="mt-2 list-decimal space-y-1 pl-4 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        <li>此页保存期望配置，UI 如实显示「待应用」；重启不会带入新环境变量。</li>
        <li>
          点击
          <Button size="sm" variant="ghost" className="mx-1" disabled={busy} onClick={() => void materialize()}>
            {busy ? <Loader2 aria-hidden className="size-3 animate-spin" /> : '生成 env 文件'}
          </Button>
          —— BFF 服务端写出 0600 的 rsshub/rsshub.env（含秘密值，绝不回传浏览器）。
        </li>
        <li>
          宿主机运行 services/bff/scripts/apply_rsshub_config.py（默认 dry-run；--apply
          才以 up -d --force-recreate --no-deps 只重建 rsshub），健康检查通过后配置真实生效。
        </li>
      </ol>
      {note !== null && (
        <p role="status" className="mt-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] p-2.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          {note}
        </p>
      )}
      <div className="mt-2">
        <Button size="sm" variant="secondary" disabled={markApplied.isPending} onClick={() => markApplied.mutate()}>
          {markApplied.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : null}
          确认应用完成（写入 applied 快照）
        </Button>
      </div>
    </section>
  )
}

export function RssHubAutoConfigCard() {
  return (
    <div className="flex flex-col gap-3">
      <DetectSection />
      <CredentialsSection />
      <ApplyChainSection />
    </div>
  )
}
