/** TranslationSettingsSection — 设置 → 翻译（R21 前端重写）。
 *
 * 引擎只剩两种，按执行位置如实标注：
 * - ai：AI 提供者执行（云端或自托管 OpenAI-compatible / Gemini）——
 *   在此选择 translation 用途的 Profile（与摘要共享同一份 Profile
 *   存储，管理仍在「设置 → AI」）+ 目标语言；
 * - browser：此浏览器执行（Translator API）——运行时探测可用才可选；
 *   正文不出设备、不经 BFF；语言边界：仅浏览器支持的语言对，源语言
 *   自动探测。
 * LibreTranslate 自托管引擎已从 BFF 移除（PUT libretranslateUrl /
 * engine=libretranslate 会 422），相关 UI 全部删除；迁移横幅只在
 * portable 键 translationMigratedFromLibre=true 时出现一次，用户确认
 * 后写回 false。
 * 按需行为不变：打开文章绝不自动翻译；自动批量翻译恒关。 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Info, Loader2, Save } from 'lucide-react'
import {
  getServerSettings,
  patchServerSettings,
} from '../../api/client'
import {
  useAiProfiles,
  useAiSettings,
  useUpdateAiPurposesMutation,
  useUpdateAiSettingsMutation,
} from '../../api/queries'
import { localTranslatorAvailable } from '../../lib/local-translator'
import { LocalTranslationCapabilitySection } from './LocalTranslationCapabilitySection'
import { useSettingsDirtySection } from './settings-dirty'
import { Button } from '../ui/Button'
import { Select } from '../ui/Select'

type EngineValue = 'ai' | 'browser'

function MigrationBanner({ onConfirm, busy }: { onConfirm: () => void; busy: boolean }) {
  return (
    <div
      role="status"
      data-lumi-translation-migration=""
      className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-[var(--lumi-accent-text)]" />
      <p className="min-w-0 flex-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        自托管翻译已移除，请选择 AI 或浏览器翻译。
      </p>
      <Button size="sm" variant="secondary" className="shrink-0" loading={busy} onClick={onConfirm}>
        知道了
      </Button>
    </div>
  )
}

export function TranslationSettingsSection() {
  const queryClient = useQueryClient()
  const settings = useAiSettings()
  const update = useUpdateAiSettingsMutation()
  const profiles = useAiProfiles()
  const assignProfile = useUpdateAiPurposesMutation()

  // portable 键 translationMigratedFromLibre（settings-meta 生成契约）。
  const serverSettings = useQuery({
    queryKey: ['server-settings'],
    queryFn: ({ signal }) => getServerSettings(signal),
  })
  const dismissMigration = useMutation({
    mutationFn: () => patchServerSettings({ translationMigratedFromLibre: false }),
    onSuccess: (server) => {
      queryClient.setQueryData(['server-settings'], server)
    },
  })

  // 表单编辑值：null = 跟随服务端值（渲染期派生，无需 effect 同步）。
  // 旧快照可能残留 libretranslate —— 引擎域已收敛为 ai|browser，
  // 未知值一律归一为 ai（服务端迁移同步做了同样的事）。
  const [edit, setEdit] = useState<{ engine: EngineValue; language: 'zh-CN' | 'en' } | null>(null)
  const s = settings.data
  const engine: EngineValue = edit?.engine ?? (s?.translationEngine === 'browser' ? 'browser' : 'ai')
  const language: 'zh-CN' | 'en' = edit?.language ?? (s?.translationLanguage === 'en' ? 'en' : 'zh-CN')
  const dirty = edit !== null
  // FIX-057：向设置中心登记脏状态——切分类 / 关闭设置前统一守护。
  useSettingsDirtySection('translation', dirty)

  // 浏览器翻译：运行时探测（Translator API 存在才可选）。
  const [browserReady] = useState(() => localTranslatorAvailable())

  if (settings.isPending) {
    return (
      <p className="py-3 text-sm text-[var(--lumi-text-secondary)]" role="status">
        正在加载翻译设置…
      </p>
    )
  }
  if (s === undefined) {
    return (
      <p className="py-3 text-sm text-[var(--lumi-danger)]" role="alert">
        翻译设置加载失败，请稍后重试。
      </p>
    )
  }

  const showMigration = serverSettings.data?.translationMigratedFromLibre === true
  const translationProfileId = s.purposeStatus.translation?.profileId ?? 'default'
  const enabledProfiles = (profiles.data ?? []).filter((p) => p.enabled)

  return (
    <div className="flex flex-col gap-4 py-3">
      {showMigration && (
        <MigrationBanner busy={dismissMigration.isPending} onConfirm={() => dismissMigration.mutate()} />
      )}

      <section className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">翻译方式与目标语言</h3>
        <div className="mt-3 flex flex-col gap-4">
          <div>
            <p className="text-sm font-medium text-[var(--lumi-text-primary)]">翻译方式</p>
            <div className="mt-1.5">
              <Select
                aria-label="翻译方式"
                value={engine}
                disabled={update.isPending}
                options={[
                  { value: 'ai', label: 'AI 翻译' },
                  {
                    // 运行时探测可用才可选：此浏览器无 Translator API 时禁用。
                    value: 'browser',
                    label: browserReady
                      ? '浏览器翻译'
                      : '浏览器翻译（此浏览器不支持）',
                    disabled: !browserReady,
                  },
                ]}
                onChange={(e) => {
                  setEdit({ engine: e.target.value === 'browser' ? 'browser' : 'ai', language })
                }}
              />
            </div>
            {/* 位置说明放选项下方：当前所选方式在哪里执行。 */}
            <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
              {engine === 'ai'
                ? '由 AI 提供者执行（云端或自托管）；在下方选择翻译 Profile 与目标语言。'
                : '由本浏览器内置翻译执行，正文不出设备、不经服务端。'}
            </p>
            {engine === 'browser' && !browserReady && (
              <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
                此浏览器不支持浏览器翻译，选择不会生效；请改用 AI 翻译。
              </p>
            )}
          </div>

          {engine === 'ai' && (
            <div>
              <p className="text-sm font-medium text-[var(--lumi-text-primary)]">翻译 Profile</p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
                选择后立即生效；Profile 在「设置 → AI」管理。
              </p>
              <div className="mt-1.5 flex items-center gap-2">
                <Select
                  aria-label="翻译 Profile"
                  value={translationProfileId}
                  disabled={assignProfile.isPending || profiles.isPending}
                  options={[
                    { value: 'default', label: '默认配置（默认模型与密钥）' },
                    ...enabledProfiles.map((p) => ({
                      value: p.id,
                      label: `${p.label}（${p.model}）${p.keyConfigured ? '' : ' · 密钥未配置'}`,
                    })),
                  ]}
                  onChange={(e) => {
                    const profileId = e.target.value
                    if (profileId === translationProfileId) return
                    assignProfile.mutate(
                      { translation: profileId },
                      {
                        onSuccess: () => {
                          void queryClient.invalidateQueries({ queryKey: ['ai-settings'] })
                        },
                      },
                    )
                  }}
                />
              </div>
              {translationProfileId !== 'default' && s.purposeStatus.translation?.keyConfigured === false && (
                <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
                  当前 Profile 密钥未配置，翻译会失败；可在「设置 → AI」补齐。
                </p>
              )}
            </div>
          )}

          <div>
            <p className="text-sm font-medium text-[var(--lumi-text-primary)]">目标语言</p>
            <p className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
              译文语言；语言不同缓存相互独立。
            </p>
            <div className="mt-1.5">
              <Select
                aria-label="目标语言"
                value={language}
                disabled={update.isPending}
                options={[
                  { value: 'zh-CN', label: '简体中文' },
                  { value: 'en', label: 'English' },
                ]}
                onChange={(e) => {
                  setEdit({ engine, language: e.target.value === 'en' ? 'en' : 'zh-CN' })
                }}
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={!dirty || update.isPending || (engine === 'browser' && !browserReady && s.translationEngine !== 'browser')}
              onClick={() =>
                update.mutate(
                  {
                    translationEngine: engine,
                    translationLanguage: language,
                  },
                  {
                    onSuccess: () => {
                      setEdit(null)
                      void queryClient.invalidateQueries({ queryKey: ['ai-settings'] })
                    },
                  },
                )
              }
            >
              {update.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : <Save aria-hidden className="size-3.5" />}
              保存
            </Button>
          </div>
          <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
            打开文章绝不自动翻译；阅读工具栏选「双语 / 仅译文」才调用付费引擎，且不批量翻译。
          </p>
        </div>
      </section>

      {engine === 'browser' && (
        <section className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
          <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">隐私与语言边界</h3>
          <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            正文在本浏览器内翻译，不出设备、不消耗 API 额度。
            仅支持浏览器提供的语言对；源语言自动探测，失败按英语处理。
            首次使用某语言对可能下载语言包。
          </p>
        </section>
      )}

      {/* N088/N089：本机翻译能力（离线能力检测 + 语言对支持与模型存储）。
          独立于当前引擎选择——检测的是「此设备」的能力，任何引擎下都诚实可得。 */}
      <LocalTranslationCapabilitySection remoteEndpoint={s.baseUrl} />
    </div>
  )
}
