/** AiSettingsPage — 0015 Gate 6：设置 → AI 的真实可用部分。
 *
 * 诚实边界：
 * - Provider 固定为 OpenAI-compatible（唯一实现，不伪造多 provider 选择）；
 * - API key 是服务端机密（环境变量），浏览器只看到
 *   「已在服务端配置 / 未配置」状态，绝无 key 输入框、绝不回显 key；
 * - 未配置时直接说明要在服务端设置 AI_API_KEY（环境变量），
 *   不渲染假的「测试连接」按钮（0015 无有界测试通道）；
 * - 编辑字段不会触发任何付费调用；保存只写非机密设置。
 * - 0016 翻译 / AI 对话仍为 planned 占位（不提前实现）。
 */

import { useState } from 'react'
import { AlertCircle, CheckCircle2, KeyRound, Loader2, Save, ShieldCheck } from 'lucide-react'
import { useAiSettings, useUpdateAiSettingsMutation } from '../../api/queries'
import type { ApiError } from '../../api/client'
import { Button } from '../ui/Button'
import { Select } from '../ui/Select'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

function FieldShell({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-[var(--lumi-text-primary)]">
        {label}
      </label>
      {hint !== undefined && (
        <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          {hint}
        </p>
      )}
      <div className="mt-1.5">{children}</div>
    </div>
  )
}

const inputClass = cx(
  'w-full min-h-9 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]',
  'bg-[var(--lumi-surface)] px-2.5 text-sm text-[var(--lumi-text-primary)]',
  'transition-colors duration-[var(--lumi-motion-fast)]',
  'hover:border-[var(--lumi-text-tertiary)]',
  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

/** API key 状态卡：只报告服务端配置状态，永不显示 key 值。 */
function KeyStatusBanner({ configured }: { configured: boolean }) {
  return (
    <div
      className={cx(
        'flex items-start gap-2.5 rounded-[var(--lumi-radius-md)] border px-3.5 py-2.5',
        configured
          ? 'border-[var(--lumi-border)] bg-[var(--lumi-surface)]'
          : 'border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
      )}
    >
      {configured ? (
        <KeyRound aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-accent)]" />
      ) : (
        <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
      )}
      <div>
        <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
          {configured ? 'API 密钥已在服务端配置' : 'API 密钥未配置'}
        </p>
        <p className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          {configured
            ? '密钥保存在服务端环境变量中，浏览器与 Lumi 数据库都不保存、不回显密钥。'
            : '在服务端 .env 中设置 AI_API_KEY（环境变量）后刷新此页。密钥不会、也不能在浏览器中填写。'}
        </p>
      </div>
    </div>
  )
}

export function AiSettingsSection() {
  const settings = useAiSettings()
  const update = useUpdateAiSettingsMutation()

  // 本地草稿：null = 未编辑（直接使用服务端值）；编辑时整体从服务端值
  // 派生，保存成功后重置为 null —— 不在 effect 中 setState。
  const [draft, setDraft] = useState<{
    baseUrl: string
    model: string
    summaryLanguage: 'zh-CN' | 'en'
  } | null>(null)

  if (settings.isError) {
    return (
      <div className="py-3">
        <p role="alert" className="flex items-start gap-1.5 text-sm text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
          AI 设置加载失败：
          {settings.error instanceof Error
            ? (settings.error as ApiError).message
            : '请稍后重试。'}
        </p>
        <Button size="sm" variant="secondary" className="mt-3" onClick={() => settings.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  if (settings.data === undefined) {
    return (
      <div className="flex flex-col gap-3 py-1" aria-label="正在加载 AI 设置">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-5 w-3/5" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-2/5" />
      </div>
    )
  }

  const data = settings.data
  const values = draft ?? {
    baseUrl: data.baseUrl,
    model: data.model,
    summaryLanguage: data.summaryLanguage,
  }
  const dirty =
    values.baseUrl !== data.baseUrl ||
    values.model !== data.model ||
    values.summaryLanguage !== data.summaryLanguage

  const patch = (next: typeof values) => setDraft(next)

  const save = () => {
    update.mutate(values, { onSuccess: () => setDraft(null) })
  }

  return (
    <div className="flex flex-col gap-4 py-1">
      <KeyStatusBanner configured={data.configured} />

      <div className="flex flex-col gap-4 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
        <FieldShell label="Provider" hint="0015 唯一实现：OpenAI-compatible HTTP API。">
          <input
            type="text"
            value="OpenAI compatible"
            disabled
            readOnly
            aria-label="Provider"
            className={inputClass}
          />
        </FieldShell>

        <FieldShell
          label="Base URL"
          hint="OpenAI-compatible 接口地址（如 https://api.openai.com/v1）。留空 = 未配置，摘要不可用。"
        >
          <input
            type="url"
            value={values.baseUrl}
            aria-label="Base URL"
            placeholder="https://api.example.com/v1"
            disabled={update.isPending}
            onChange={(e) => patch({ ...values, baseUrl: e.target.value })}
            className={inputClass}
          />
        </FieldShell>

        <FieldShell label="Model" hint="服务端实际请求的模型名（按你的 provider 文档填写）。">
          <input
            type="text"
            value={values.model}
            aria-label="Model"
            placeholder="deepseek-chat"
            disabled={update.isPending}
            onChange={(e) => patch({ ...values, model: e.target.value })}
            className={inputClass}
          />
        </FieldShell>

        <FieldShell label="摘要语言" hint="生成摘要时使用的语言；语言参与摘要缓存身份。">
          <Select
            aria-label="摘要语言"
            value={values.summaryLanguage}
            disabled={update.isPending}
            options={[
              { value: 'zh-CN', label: '简体中文' },
              { value: 'en', label: 'English' },
            ]}
            onChange={(e) =>
              patch({
                ...values,
                summaryLanguage: e.target.value as 'zh-CN' | 'en',
              })
            }
          />
        </FieldShell>

        <div className="flex items-center gap-2">
          <Button size="sm" onClick={save} disabled={!dirty || update.isPending}>
            {update.isPending ? (
              <Loader2 aria-hidden className="size-3.5 animate-spin" />
            ) : (
              <Save aria-hidden className="size-3.5" />
            )}
            保存
          </Button>
          {update.isSuccess && (
            <span role="status" className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
              <CheckCircle2 aria-hidden className="size-3.5 text-[var(--lumi-accent)]" />
              已保存
            </span>
          )}
        </div>

        {update.isError && (
          <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
            保存失败：{update.error instanceof Error ? update.error.message : '请稍后重试。'}
          </p>
        )}

        <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
          <ShieldCheck aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          修改这些字段不会自动调用付费接口；只有阅读器中手动点击「AI 摘要」才会发起一次生成请求。
        </p>
      </div>
    </div>
  )
}
