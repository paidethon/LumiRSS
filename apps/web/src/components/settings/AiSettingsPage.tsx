/** AiSettingsPage — 设置 → AI：浏览器可管理的多 Profile 配置。
 *
 * 结构（自上而下）：
 * 1. 用途分配：摘要 / 翻译 / AI 对话各自映射到「默认配置」或任一 Profile；
 * 2. AI Profile：多条命名配置（label / Base URL / model / 启用），
 *    每条可单独设置 API Key；
 * 3. 默认配置：全局 Base URL / model / 语言 + 默认 Key；
 * 4. 密钥状态：默认 Key（浏览器设置，存服务端 SecretsStore）与
 *    环境变量回退的存在性。
 *
 * 安全边界（不变式）：
 * - Key 只经 write-only 接口进入服务端 SecretsStore；任何 GET 响应都
 *   只含「已配置」布尔，浏览器不持久化 Key（不入 localStorage/settings）；
 * - 环境变量 AI_API_KEY 保持为默认配置的回退（不回显、不迁移）；
 * - 编辑/保存/切换 Profile 绝不触发 AI 调用；只有阅读页内手动点击
 *   「AI 摘要」「译文」或发送对话消息才产生请求。
 */

import { useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  KeyRound,
  Loader2,
  Pencil,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react'
import {
  useAiProfiles,
  useAiSettings,
  useClearAiProfileSecretMutation,
  useClearDefaultAiSecretMutation,
  useCreateAiProfileMutation,
  useDeleteAiProfileMutation,
  useSetAiProfileSecretMutation,
  useSetDefaultAiSecretMutation,
  useUpdateAiProfileMutation,
  useUpdateAiPurposesMutation,
  useUpdateAiSettingsMutation,
} from '../../api/queries'
import type {
  AiProfile,
  AiPurposeKey,
  AiPurposeStatus,
  AiSettings,
} from '../../api/types'
import type { ApiError } from '../../api/client'
import { Button } from '../ui/Button'
import { Select } from '../ui/Select'
import { Skeleton } from '../ui/Skeleton'
import { Switch } from '../ui/Switch'
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

const PURPOSE_LABELS: Record<AiPurposeKey, string> = {
  summary: '摘要',
  translation: '翻译',
  chat: 'AI 对话',
}

const PURPOSE_HINTS: Record<AiPurposeKey, string> = {
  summary: '阅读页「AI 摘要」使用的配置。',
  translation: '阅读页「译文」使用的配置；目标语言在下方默认配置中选择。',
  chat: '文章 AI 对话使用的配置。',
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? (error as ApiError).message : fallback
}

/** Key 状态徽标：只报布尔，永不出现 key 值。 */
function KeyBadge({ configured }: { configured: boolean }) {
  return (
    <span
      className={cx(
        'inline-flex shrink-0 items-center gap-1 rounded-[var(--lumi-radius-full)] px-2 py-0.5 text-[11px]',
        configured
          ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
          : 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]',
      )}
    >
      <KeyRound aria-hidden className="size-3" />
      {configured ? 'Key 已配置' : 'Key 未配置'}
    </span>
  )
}

/** 有效解析状态行（purposeStatus → 人类可读，不含任何 secret）。 */
function PurposeStatusLine({ status }: { status: AiPurposeStatus }) {
  const name =
    status.source === 'profile'
      ? (status.profileLabel ?? 'Profile')
      : '默认配置'
  const detail = status.configured
    ? status.model
      ? `${status.model} · 就绪`
      : '就绪'
    : status.keyConfigured
      ? '缺少 Base URL / Model'
      : '缺少 API Key'
  return (
    <span
      className={cx(
        'text-[11px] leading-none',
        status.configured
          ? 'text-[var(--lumi-text-tertiary)]'
          : 'text-[var(--lumi-danger)]',
      )}
    >
      {name} · {detail}
    </span>
  )
}

// ---- 用途分配 ----

function PurposeMappingSection({
  settings,
  profiles,
}: {
  settings: AiSettings
  profiles: AiProfile[]
}) {
  const updatePurposes = useUpdateAiPurposesMutation()
  const options = [
    { value: 'default', label: '默认配置' },
    ...profiles
      .filter((p) => p.enabled)
      .map((p) => ({ value: p.id, label: p.label })),
  ]

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">用途分配</h3>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        为每个 AI 功能选择使用哪套配置；同一配置可复用于多个用途。
      </p>
      <div className="mt-3 flex flex-col gap-3">
        {(Object.keys(PURPOSE_LABELS) as AiPurposeKey[]).map((purpose) => (
          <div key={purpose} className="flex flex-col gap-1">
            <div className="flex items-center justify-between gap-3">
              <label
                className="shrink-0 text-sm font-medium text-[var(--lumi-text-primary)]"
                htmlFor={`ai-purpose-${purpose}`}
              >
                {PURPOSE_LABELS[purpose]}
              </label>
              <Select
                id={`ai-purpose-${purpose}`}
                aria-label={`${PURPOSE_LABELS[purpose]}使用的配置`}
                value={settings.purposes[purpose]}
                disabled={updatePurposes.isPending}
                options={options}
                onChange={(e) => {
                  updatePurposes.mutate({ [purpose]: e.target.value })
                }}
              />
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
                {PURPOSE_HINTS[purpose]}
              </span>
              {settings.purposeStatus && (
                <PurposeStatusLine status={settings.purposeStatus[purpose]} />
              )}
            </div>
          </div>
        ))}
      </div>
      {updatePurposes.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          保存失败：{errorMessage(updatePurposes.error, '请稍后重试。')}
        </p>
      )}
    </div>
  )
}

// ---- Profile 卡片 ----

interface ProfileDraft {
  label: string
  baseUrl: string
  model: string
}

function ProfileCard({ profile }: { profile: AiProfile }) {
  const updateProfile = useUpdateAiProfileMutation()
  const deleteProfile = useDeleteAiProfileMutation()
  const setSecret = useSetAiProfileSecretMutation()
  const clearSecret = useClearAiProfileSecretMutation()

  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [draft, setDraft] = useState<ProfileDraft>({
    label: profile.label,
    baseUrl: profile.baseUrl,
    model: profile.model,
  })
  const [ keyValue, setKeyValue ] = useState('')
  const [keyError, setKeyError] = useState<string | null>(null)
  const [keySaved, setKeySaved] = useState(false)
  const [showKeyInput, setShowKeyInput] = useState(false)

  const dirty =
    draft.label !== profile.label ||
    draft.baseUrl !== profile.baseUrl ||
    draft.model !== profile.model

  const saveEdit = () => {
    updateProfile.mutate(
      { profileId: profile.id, patch: draft },
      { onSuccess: () => setEditing(false) },
    )
  }

  const saveKey = () => {
    if (!keyValue.trim()) {
      setKeyError('请输入 API Key。')
      return
    }
    setKeyError(null)
    setSecret.mutate(
      { profileId: profile.id, value: keyValue.trim() },
      {
        onSuccess: () => {
          setKeyValue('')
          setShowKeyInput(false)
          setKeySaved(true)
        },
        onError: (err) => setKeyError(errorMessage(err, '保存失败，请重试。')),
      },
    )
  }

  return (
    <li className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-medium text-[var(--lumi-text-primary)]">
              {profile.label}
            </span>
            <KeyBadge configured={profile.keyConfigured} />
            {!profile.enabled && (
              <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
                已停用
              </span>
            )}
          </div>
          {!editing && (
            <p className="mt-1 truncate text-xs text-[var(--lumi-text-secondary)]">
              {profile.baseUrl === '' ? '未设置 Base URL' : profile.baseUrl}
              {profile.model !== '' && ` · ${profile.model}`}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {!editing && (
            <Button
              size="sm"
              variant="ghost"
              aria-label={`编辑 Profile ${profile.label}`}
              onClick={() => {
                setDraft({
                  label: profile.label,
                  baseUrl: profile.baseUrl,
                  model: profile.model,
                })
                setEditing(true)
              }}
            >
              <Pencil aria-hidden className="size-3.5" />
            </Button>
          )}
          <Switch
            label={`启用 Profile ${profile.label}`}
            checked={profile.enabled}
            disabled={updateProfile.isPending}
            onCheckedChange={(v) =>
              updateProfile.mutate({ profileId: profile.id, patch: { enabled: v } })
            }
          />
        </div>
      </div>

      {editing ? (
        <div className="mt-3 flex flex-col gap-2.5">
          <FieldShell label="名称">
            <input
              type="text"
              value={draft.label}
              aria-label="Profile 名称"
              maxLength={80}
              onChange={(e) => setDraft({ ...draft, label: e.target.value })}
              className={inputClass}
            />
          </FieldShell>
          <FieldShell label="Base URL" hint="OpenAI-compatible 接口地址（如 https://api.example.com/v1）。">
            <input
              type="url"
              value={draft.baseUrl}
              aria-label="Profile Base URL"
              placeholder="https://api.example.com/v1"
              onChange={(e) => setDraft({ ...draft, baseUrl: e.target.value })}
              className={inputClass}
            />
          </FieldShell>
          <FieldShell label="Model">
            <input
              type="text"
              value={draft.model}
              aria-label="Profile Model"
              placeholder="模型名"
              onChange={(e) => setDraft({ ...draft, model: e.target.value })}
              className={inputClass}
            />
          </FieldShell>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={saveEdit}
              disabled={!dirty || updateProfile.isPending || draft.label.trim() === ''}
            >
              {updateProfile.isPending ? (
                <Loader2 aria-hidden className="size-3.5 animate-spin" />
              ) : (
                <Save aria-hidden className="size-3.5" />
              )}
              保存
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              取消
            </Button>
          </div>
          {updateProfile.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              保存失败：{errorMessage(updateProfile.error, '请稍后重试。')}
            </p>
          )}
        </div>
      ) : null}

      {/* Key 管理：write-only；输入框不持久化、保存后立即清空 */}
      <div className="mt-3 border-t border-[var(--lumi-separator)] pt-3">
        {showKeyInput ? (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <input
                type="password"
                value={keyValue}
                aria-label={`Profile ${profile.label} 的 API Key`}
                placeholder="粘贴 API Key（保存后不再显示）"
                autoComplete="off"
                onChange={(e) => setKeyValue(e.target.value)}
                className={inputClass}
              />
              <Button
                size="sm"
                onClick={saveKey}
                disabled={setSecret.isPending || keyValue.trim() === ''}
              >
                {setSecret.isPending ? (
                  <Loader2 aria-hidden className="size-3.5 animate-spin" />
                ) : null}
                保存 Key
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label="取消输入 Key"
                onClick={() => {
                  setShowKeyInput(false)
                  setKeyValue('')
                  setKeyError(null)
                }}
              >
                <X aria-hidden className="size-3.5" />
              </Button>
            </div>
            {keyError && (
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                {keyError}
              </p>
            )}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setKeySaved(false)
                setShowKeyInput(true)
              }}
            >
              {profile.keyConfigured ? '更换 Key' : '设置 Key'}
            </Button>
            {profile.keyConfigured && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => clearSecret.mutate(profile.id)}
                disabled={clearSecret.isPending}
              >
                清除 Key
              </Button>
            )}
            {keySaved && (
              <span role="status" className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
                <CheckCircle2 aria-hidden className="size-3.5 text-[var(--lumi-accent-text)]" />
                Key 已保存到服务端
              </span>
            )}
          </div>
        )}
      </div>

      {/* 删除：两步确认 */}
      <div className="mt-3 border-t border-[var(--lumi-separator)] pt-3">
        {confirmDelete ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-[var(--lumi-text-secondary)]">
              删除 Profile「{profile.label}」？其 Key 与用途分配会一并清除。
            </span>
            <Button
              size="sm"
              variant="danger"
              onClick={() => deleteProfile.mutate(profile.id)}
              disabled={deleteProfile.isPending}
            >
              确认删除
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>
              取消
            </Button>
          </div>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            className="text-[var(--lumi-danger)]"
            aria-label={`删除 Profile ${profile.label}`}
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2 aria-hidden className="size-3.5" />
            删除
          </Button>
        )}
        {deleteProfile.isError && (
          <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
            删除失败：{errorMessage(deleteProfile.error, '请稍后重试。')}
          </p>
        )}
      </div>
    </li>
  )
}

// ---- Profile 列表 + 新建 ----

function ProfilesSection({ profiles }: { profiles: AiProfile[] }) {
  const createProfile = useCreateAiProfileMutation()
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState<ProfileDraft>({ label: '', baseUrl: '', model: '' })
  const [createError, setCreateError] = useState<string | null>(null)

  const submitCreate = () => {
    if (draft.label.trim() === '') {
      setCreateError('请填写 Profile 名称。')
      return
    }
    setCreateError(null)
    createProfile.mutate(
      { label: draft.label.trim(), baseUrl: draft.baseUrl.trim(), model: draft.model.trim() },
      {
        onSuccess: () => {
          setDraft({ label: '', baseUrl: '', model: '' })
          setCreating(false)
        },
        onError: (err) => setCreateError(errorMessage(err, '创建失败，请重试。')),
      },
    )
  }

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">AI Profile</h3>
          <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            为不同用途准备不同的服务地址 / 模型 / API Key。
          </p>
        </div>
        {!creating && (
          <Button size="sm" variant="secondary" onClick={() => setCreating(true)}>
            <Plus aria-hidden className="size-3.5" />
            新建 Profile
          </Button>
        )}
      </div>

      {creating && (
        <div className="mt-3 flex flex-col gap-2.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-accent)] p-3">
          <FieldShell label="名称" hint="例如「GLM 摘要」「DeepSeek 翻译」。">
            <input
              type="text"
              value={draft.label}
              aria-label="新 Profile 名称"
              maxLength={80}
              autoFocus
              onChange={(e) => setDraft({ ...draft, label: e.target.value })}
              className={inputClass}
            />
          </FieldShell>
          <FieldShell label="Base URL">
            <input
              type="url"
              value={draft.baseUrl}
              aria-label="新 Profile Base URL"
              placeholder="https://api.example.com/v1"
              onChange={(e) => setDraft({ ...draft, baseUrl: e.target.value })}
              className={inputClass}
            />
          </FieldShell>
          <FieldShell label="Model">
            <input
              type="text"
              value={draft.model}
              aria-label="新 Profile Model"
              placeholder="模型名"
              onChange={(e) => setDraft({ ...draft, model: e.target.value })}
              className={inputClass}
            />
          </FieldShell>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={submitCreate}
              disabled={createProfile.isPending || draft.label.trim() === ''}
            >
              {createProfile.isPending ? (
                <Loader2 aria-hidden className="size-3.5 animate-spin" />
              ) : (
                <Plus aria-hidden className="size-3.5" />
              )}
              创建
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setCreating(false)
                setCreateError(null)
              }}
            >
              取消
            </Button>
          </div>
          {createError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              {createError}
            </p>
          )}
        </div>
      )}

      {profiles.length > 0 && (
        <ul className="mt-3 flex flex-col gap-3">
          {profiles.map((profile) => (
            <ProfileCard key={profile.id} profile={profile} />
          ))}
        </ul>
      )}
      {profiles.length === 0 && !creating && (
        <p className="mt-3 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          还没有 Profile。所有用途当前使用下方「默认配置」。
        </p>
      )}
    </div>
  )
}

// ---- 默认 Key ----

function DefaultKeyCard({ settings }: { settings: AiSettings }) {
  const setSecret = useSetDefaultAiSecretMutation()
  const clearSecret = useClearDefaultAiSecretMutation()
  const [keyValue, setKeyValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [showInput, setShowInput] = useState(false)

  const save = () => {
    if (!keyValue.trim()) {
      setError('请输入 API Key。')
      return
    }
    setError(null)
    setSecret.mutate(keyValue.trim(), {
      onSuccess: () => {
        setKeyValue('')
        setShowInput(false)
        setSaved(true)
      },
      onError: (err) => setError(errorMessage(err, '保存失败，请重试。')),
    })
  }

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">默认 API Key</h3>
        <KeyBadge configured={settings.defaultKeyConfigured} />
        {settings.envKeyConfigured && (
          <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
            环境变量备用配置已存在
          </span>
        )}
      </div>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        供未单独分配 Profile 的用途使用。Key 保存在服务端（加密文件，权限 600），
        浏览器与数据库都不保存、不回显；环境变量 AI_API_KEY 仍作为回退。
      </p>
      {showInput ? (
        <div className="mt-3 flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <input
              type="password"
              value={keyValue}
              aria-label="默认 API Key"
              placeholder="粘贴 API Key（保存后不再显示）"
              autoComplete="off"
              onChange={(e) => setKeyValue(e.target.value)}
              className={inputClass}
            />
            <Button size="sm" onClick={save} disabled={setSecret.isPending || keyValue.trim() === ''}>
              {setSecret.isPending ? (
                <Loader2 aria-hidden className="size-3.5 animate-spin" />
              ) : null}
              保存 Key
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label="取消输入默认 Key"
              onClick={() => {
                setShowInput(false)
                setKeyValue('')
                setError(null)
              }}
            >
              <X aria-hidden className="size-3.5" />
            </Button>
          </div>
          {error && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              {error}
            </p>
          )}
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setSaved(false)
              setShowInput(true)
            }}
          >
            {settings.defaultKeyConfigured ? '更换 Key' : '设置 Key'}
          </Button>
          {settings.defaultKeyConfigured && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => clearSecret.mutate()}
              disabled={clearSecret.isPending}
            >
              清除 Key
            </Button>
          )}
          {saved && (
            <span role="status" className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
              <CheckCircle2 aria-hidden className="size-3.5 text-[var(--lumi-accent-text)]" />
              Key 已保存到服务端
            </span>
          )}
        </div>
      )}
    </div>
  )
}

// ---- 默认（全局）配置 ----

function GlobalSettingsCard({ settings }: { settings: AiSettings }) {
  const update = useUpdateAiSettingsMutation()
  const [draft, setDraft] = useState<{
    baseUrl: string
    model: string
    summaryLanguage: 'zh-CN' | 'en'
    translationLanguage: 'zh-CN' | 'en'
  } | null>(null)

  const values = draft ?? {
    baseUrl: settings.baseUrl,
    model: settings.model,
    summaryLanguage: settings.summaryLanguage,
    translationLanguage: settings.translationLanguage,
  }
  const dirty =
    values.baseUrl !== settings.baseUrl ||
    values.model !== settings.model ||
    values.summaryLanguage !== settings.summaryLanguage ||
    values.translationLanguage !== settings.translationLanguage

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">默认配置</h3>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        未分配 Profile 的用途使用的全局服务地址与模型；Profile 的 Provider 均为 OpenAI-compatible。
      </p>
      <div className="mt-3 flex flex-col gap-4">
        <FieldShell
          label="Base URL"
          hint="OpenAI-compatible 接口地址（如 https://api.openai.com/v1）。留空 = 未配置。"
        >
          <input
            type="url"
            value={values.baseUrl}
            aria-label="默认 Base URL"
            placeholder="https://api.example.com/v1"
            disabled={update.isPending}
            onChange={(e) => setDraft({ ...values, baseUrl: e.target.value })}
            className={inputClass}
          />
        </FieldShell>

        <FieldShell label="Model" hint="服务端实际请求的模型名（按你的 provider 文档填写）。">
          <input
            type="text"
            value={values.model}
            aria-label="默认 Model"
            placeholder="deepseek-chat"
            disabled={update.isPending}
            onChange={(e) => setDraft({ ...values, model: e.target.value })}
            className={inputClass}
          />
        </FieldShell>

        <FieldShell label="摘要语言" hint="生成摘要时使用的语言；语言参与摘要缓存身份。AI 对话回复语言沿用摘要语言。">
          <Select
            aria-label="摘要语言"
            value={values.summaryLanguage}
            disabled={update.isPending}
            options={[
              { value: 'zh-CN', label: '简体中文' },
              { value: 'en', label: 'English' },
            ]}
            onChange={(e) =>
              setDraft({ ...values, summaryLanguage: e.target.value as 'zh-CN' | 'en' })
            }
          />
        </FieldShell>

        <FieldShell label="翻译语言" hint="译文的目标语言；语言参与翻译缓存身份。">
          <Select
            aria-label="翻译语言"
            value={values.translationLanguage}
            disabled={update.isPending}
            options={[
              { value: 'zh-CN', label: '简体中文' },
              { value: 'en', label: 'English' },
            ]}
            onChange={(e) =>
              setDraft({ ...values, translationLanguage: e.target.value as 'zh-CN' | 'en' })
            }
          />
        </FieldShell>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => update.mutate(values, { onSuccess: () => setDraft(null) })}
            disabled={!dirty || update.isPending}
          >
            {update.isPending ? (
              <Loader2 aria-hidden className="size-3.5 animate-spin" />
            ) : (
              <Save aria-hidden className="size-3.5" />
            )}
            保存
          </Button>
          {update.isSuccess && draft === null && (
            <span role="status" className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
              <CheckCircle2 aria-hidden className="size-3.5 text-[var(--lumi-accent-text)]" />
              已保存
            </span>
          )}
        </div>

        {update.isError && (
          <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
            保存失败：{errorMessage(update.error, '请稍后重试。')}
          </p>
        )}
      </div>
    </div>
  )
}

// ---- 顶层 ----

export function AiSettingsSection() {
  const settings = useAiSettings()
  const profiles = useAiProfiles()

  if (settings.isError) {
    return (
      <div className="py-3">
        <p role="alert" className="flex items-start gap-1.5 text-sm text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
          AI 设置加载失败：
          {errorMessage(settings.error, '请稍后重试。')}
        </p>
        <Button size="sm" variant="secondary" className="mt-3" onClick={() => settings.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  if (settings.data === undefined || profiles.data === undefined) {
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

  return (
    <div className="flex flex-col gap-4 py-1">
      <PurposeMappingSection settings={data} profiles={profiles.data} />
      <ProfilesSection profiles={profiles.data} />
      <DefaultKeyCard settings={data} />
      <GlobalSettingsCard settings={data} />

      <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
        <ShieldCheck aria-hidden className="mt-0.5 size-3.5 shrink-0" />
        API Key 只保存在服务端，任何页面都不会显示完整 Key；修改这些配置不会自动调用付费接口——
        只有阅读页中手动点击「AI 摘要」「译文」或发送对话消息才会发起请求。
      </p>
      {profiles.isError && (
        <p role="alert" className="flex items-start gap-1.5 text-xs text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          Profile 列表加载失败：{errorMessage(profiles.error, '请稍后重试。')}
        </p>
      )}
    </div>
  )
}
