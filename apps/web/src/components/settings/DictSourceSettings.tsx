/** DictSourceSettings — N069 选词词典来源配置（设置 → 阅读）。
 *
 * 用户自选词典 API（自托管/自选服务商），Lumi 不内置默认上游：外发
 * 目的地永远由用户显式决定。模板需含 {word} 占位符；查询只发送所选
 * 单词本身（绝不携带选区上下文/文章内容）。非法模板在保存时被归一化
 * 为空（诚实回退「未配置」），并以行内提示说明原因。 */

import { useState } from 'react'
import { DICT_SETUP_HINT, normalizeDictApiUrl } from '../../lib/dict-lookup'
import { useAppSettings } from '../../store/app-settings'
import { Button } from '../ui/Button'

export function DictSourceSettings() {
  const dictApiUrl = useAppSettings((s) => s.settings.dictApiUrl)
  const update = useAppSettings((s) => s.update)
  const [draft, setDraft] = useState(dictApiUrl)
  const [notice, setNotice] = useState<string | null>(null)

  const save = () => {
    const normalized = normalizeDictApiUrl(draft)
    if (draft.trim() !== '' && normalized === '') {
      setNotice('未保存：模板需为 http(s) 地址且包含 {word} 占位符。')
      return
    }
    update({ dictApiUrl: normalized })
    setDraft(normalized)
    setNotice(normalized === '' ? '已清除词典来源（查询将不会发出任何请求）。' : '词典来源已保存。')
  }

  const configured = dictApiUrl !== ''

  return (
    <div className="flex flex-col gap-2 py-3" data-testid="dict-source-settings">
      <div>
        <label
          htmlFor="dict-api-url"
          className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]"
        >
          选词词典来源
        </label>
        <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          {DICT_SETUP_HINT}
        </p>
      </div>
      <div className="flex items-center gap-1.5">
        <input
          id="dict-api-url"
          type="text"
          value={draft}
          placeholder="https://dict.example.com/api?q={word}"
          onChange={(e) => {
            setDraft(e.target.value)
            setNotice(null)
          }}
          className="h-9 min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        />
        <Button size="sm" variant="secondary" className="min-h-11" onClick={save}>
          保存词典来源
        </Button>
      </div>
      <p aria-live="polite" className="text-xs text-[var(--lumi-text-tertiary)]">
        {notice ??
          (configured
            ? `当前来源：${safelyHostOf(dictApiUrl)}（查询仅发送所选单词）`
            : '当前未配置：选词卡片只显示提示，不发出任何请求。')}
      </p>
    </div>
  )
}

function safelyHostOf(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
}

export default DictSourceSettings
