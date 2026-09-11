/** TranslationSettingsSection — 设置 → 翻译（统一入口）。
 *
 * 翻译专属配置的唯一编辑点（AI 设置页不再重复翻译表单）：
 * - 翻译引擎 + 运行位置如实标注：ai=AI 提供者（云端或自托管）、
 *   libretranslate=自托管服务器（经 BFF 调用）、browser=此浏览器
 *   （本地 Translator API；BFF 零参与，不上传正文）；
 * - 目标语言（参与缓存身份）；
 * - LibreTranslate：地址 + 可选 API Key（服务端 write-only）+ 连接测试；
 * - 按需行为说明：打开文章绝不自动翻译；自动翻译恒关；
 * - AI Profile 管理仍留在「设置 → AI」（同一份 profile 存储），
 *   此处只展示 translation 用途的解析结果，附跳转。
 *
 * 密钥安全：API Key 只写服务端 SecretsStore；UI 只显示已配置状态，
 * 支持替换与清除，不回读明文。 */

import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2, Save } from 'lucide-react'
import {
  useAiSettings,
  useClearLibreTranslateKeyMutation,
  useSaveLibreTranslateKeyMutation,
  useTestLibreTranslateMutation,
  useUpdateAiSettingsMutation,
} from '../../api/queries'
import { Select } from '../ui/Select'
import { Button } from '../ui/Button'
import { cx } from '../ui/cx'

const inputClass = cx(
  'h-9 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]',
  'bg-[var(--lumi-surface)] px-2.5 text-sm text-[var(--lumi-text-primary)]',
  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
)

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
      <p className="text-sm font-medium text-[var(--lumi-text-primary)]">{label}</p>
      {hint !== undefined && (
        <p className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">{hint}</p>
      )}
      <div className="mt-1.5">{children}</div>
    </div>
  )
}

const ENGINE_OPTIONS = [
  { value: 'ai', label: 'AI 翻译 — AI 提供者执行（云端或自托管 OpenAI-compatible）' },
  { value: 'libretranslate', label: '本地机器翻译 — 自托管服务器执行（LibreTranslate，经 BFF）' },
  { value: 'browser', label: '本地翻译 — 此浏览器执行（Chrome Translator API，正文不出设备）' },
] as const

type EngineValue = (typeof ENGINE_OPTIONS)[number]['value']

export function TranslationSettingsSection() {
  const queryClient = useQueryClient()
  const settings = useAiSettings()
  const update = useUpdateAiSettingsMutation()

  const [engine, setEngine] = useState<EngineValue>('ai')
  const [language, setLanguage] = useState<'zh-CN' | 'en'>('zh-CN')
  const [libreUrl, setLibreUrl] = useState('')
  const [keyInput, setKeyInput] = useState('')
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    const s = settings.data
    if (s === undefined || dirty) return
    setEngine(s.translationEngine as EngineValue)
    setLanguage(s.translationLanguage === 'en' ? 'en' : 'zh-CN')
    setLibreUrl(s.libretranslateUrl)
  }, [settings.data, dirty])

  const saveKey = useSaveLibreTranslateKeyMutation()
  const clearKey = useClearLibreTranslateKeyMutation()
  const test = useTestLibreTranslateMutation()
  const [testResult, setTestResult] = useState<string | null>(null)

  if (settings.isPending) {
    return (
      <p className="py-3 text-sm text-[var(--lumi-text-secondary)]" role="status">
        正在加载翻译设置…
      </p>
    )
  }
  if (settings.isError || settings.data === undefined) {
    return (
      <p className="py-3 text-sm text-[var(--lumi-danger)]" role="alert">
        翻译设置加载失败，请稍后重试。
      </p>
    )
  }

  const s = settings.data

  return (
    <div className="flex flex-col gap-4 py-3">
      <section className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">翻译引擎与目标语言</h3>
        <div className="mt-3 flex flex-col gap-4">
          <FieldShell label="翻译引擎" hint="运行位置如实标注：云端 / 自托管服务器 / 此浏览器。">
            <Select
              aria-label="翻译引擎"
              value={engine}
              disabled={update.isPending}
              options={ENGINE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
              onChange={(e) => {
                setDirty(true)
                setEngine(e.target.value as EngineValue)
              }}
            />
          </FieldShell>
          <FieldShell label="目标语言" hint="译文的目标语言；语言参与翻译缓存身份。">
            <Select
              aria-label="目标语言"
              value={language}
              disabled={update.isPending}
              options={[
                { value: 'zh-CN', label: '简体中文' },
                { value: 'en', label: 'English' },
              ]}
              onChange={(e) => {
                setDirty(true)
                setLanguage(e.target.value as 'zh-CN' | 'en')
              }}
            />
          </FieldShell>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={!dirty || update.isPending}
              onClick={() =>
                update.mutate(
                  {
                    translationEngine: engine,
                    translationLanguage: language,
                    libretranslateUrl: libreUrl,
                  },
                  {
                    onSuccess: () => {
                      setDirty(false)
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
            按需翻译：打开文章绝不自动翻译；在阅读工具栏选择「双语 / 仅译文」即是一次显式请求。
            自动批量翻译恒关，不会在无指示时调用付费引擎。
          </p>
        </div>
      </section>

      {engine === 'libretranslate' && (
        <section className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
          <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">LibreTranslate（自托管）</h3>
          <div className="mt-3 flex flex-col gap-4">
            <FieldShell label="服务地址" hint="例如 http://127.0.0.1:5000（BFF 服务器可达的地址）。">
              <input
                type="url"
                value={libreUrl}
                aria-label="LibreTranslate 服务地址"
                placeholder="http://127.0.0.1:5000"
                disabled={update.isPending}
                onChange={(e) => {
                  setDirty(true)
                  setLibreUrl(e.target.value)
                }}
                className={inputClass}
              />
            </FieldShell>
            <FieldShell
              label="API Key（可选）"
              hint={s.libretranslateKeyConfigured ? '已配置（只写不读；可替换或清除）。' : '未配置；多数自托管实例无需鉴权，不必填写假 Key。'}
            >
              <div className="flex items-center gap-2">
                <input
                  type="password"
                  value={keyInput}
                  aria-label="LibreTranslate API Key"
                  placeholder={s.libretranslateKeyConfigured ? '已保存（输入新值可替换）' : '留空即可（无鉴权实例）'}
                  autoComplete="off"
                  disabled={saveKey.isPending}
                  onChange={(e) => setKeyInput(e.target.value)}
                  className={inputClass}
                />
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={keyInput === '' || saveKey.isPending}
                  onClick={() =>
                    saveKey.mutate(keyInput, {
                      onSuccess: () => {
                        setKeyInput('')
                        void queryClient.invalidateQueries({ queryKey: ['ai-settings'] })
                      },
                    })
                  }
                >
                  {saveKey.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : '保存 Key'}
                </Button>
                {s.libretranslateKeyConfigured && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={clearKey.isPending}
                    onClick={() =>
                      clearKey.mutate(undefined, {
                        onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['ai-settings'] }),
                      })
                    }
                  >
                    清除
                  </Button>
                )}
              </div>
            </FieldShell>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={test.isPending || libreUrl === ''}
                onClick={() =>
                  test.mutate(undefined, {
                    onSuccess: (result) => setTestResult(result.message ?? ''),
                    onError: (error) =>
                      setTestResult(error instanceof Error ? error.message : '连接失败。'),
                  })
                }
              >
                {test.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : '测试连接'}
              </Button>
              {testResult !== null && (
                <span className="text-xs text-[var(--lumi-text-secondary)]">{testResult}</span>
              )}
            </div>
          </div>
        </section>
      )}

      {engine === 'browser' && (
        <section className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
          <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">本地翻译（此浏览器）</h3>
          <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            使用浏览器内置 Translator API。正文不出设备、不经过 BFF、不消耗任何 API
            额度；首次使用某语言对时浏览器可能需要下载语言包（下载进度在阅读器状态条显示）。
            源语言由浏览器自动探测，探测失败时按英语处理。
          </p>
          <table className="mt-2 w-full text-xs text-[var(--lumi-text-secondary)]">
            <caption className="sr-only">本地翻译平台支持矩阵</caption>
            <thead>
              <tr className="text-left text-[var(--lumi-text-tertiary)]">
                <th scope="col" className="py-1 pr-2 font-normal">平台</th>
                <th scope="col" className="py-1 font-normal">支持情况</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="py-1 pr-2">Windows / macOS / ChromeOS 桌面 Chrome 138+</td>
                <td className="py-1">支持</td>
              </tr>
              <tr>
                <td className="py-1 pr-2">Linux 桌面 Chrome 138+</td>
                <td className="py-1">
                  支持，但翻译组件可能未自动下发——组件未就绪时打开 chrome://components 更新 TranslateKit
                </td>
              </tr>
              <tr>
                <td className="py-1 pr-2">Android / iOS / iPadOS 任何浏览器</td>
                <td className="py-1">不支持（如实提示，不假装可用）</td>
              </tr>
              <tr>
                <td className="py-1 pr-2">Firefox / Safari 桌面</td>
                <td className="py-1">不支持</td>
              </tr>
            </tbody>
          </table>
        </section>
      )}

      <section className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">AI 提供者与模型</h3>
        <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          翻译用途当前解析：
          <span className="ml-1 font-medium text-[var(--lumi-text-primary)]">
            {s.purposeStatus.translation === undefined
              ? '默认配置'
              : s.purposeStatus.translation.profileId === 'default'
                ? '默认配置'
                : `Profile「${s.purposes.translation ?? s.purposeStatus.translation.profileId}」`}
            {s.purposeStatus.translation?.keyConfigured ? '' : ' · 密钥未配置'}
          </span>
        </p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          Profile 的创建 / 编辑 / 用途分配统一在「设置 → AI」进行；翻译与摘要共享同一份
          Profile 存储，修改会影响所有使用该 Profile 的用途。
        </p>
      </section>
    </div>
  )
}
