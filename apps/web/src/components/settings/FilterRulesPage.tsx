/** FilterRulesPage — 文章过滤（0010a F3，AC24）。
 * OrigRead filter-rules 数据模型 + UI 复刻（inspired）：
 * 统计卡片 + 添加规则（keyword/regex + 行内校验）+ 导入导出 + 规则列表
 * （范围·类型 + 启用开关 + 删除）。本轮语义 = 显示层过滤（BFF 层
 * planned·0013）。 */

import { useRef, useState } from 'react'
import { Download, Trash2, Upload } from 'lucide-react'
import { normalizeSettings, useAppSettings, type FilterRule } from '../../store/app-settings'
import { Button } from '../ui/Button'
import { Switch } from '../ui/Switch'
import { cx } from '../ui/cx'

/** 匹配引擎（OrigRead ArticleFilterEngine 语义：只匹配标题、忽略大小写、
 * 首条命中；feedId 命中优先于全局——显示层过滤在 EntryList 消费）。 */
export function matchesFilterRules(
  title: string,
  rules: FilterRule[],
  feedId: string | null,
): FilterRule | null {
  const feedRules = rules.filter((r) => r.enabled && r.feedId !== null && r.feedId === feedId)
  const globalRules = rules.filter((r) => r.enabled && r.feedId === null)
  for (const rule of [...feedRules, ...globalRules]) {
    if (rule.type === 'keyword') {
      if (title.toLowerCase().includes(rule.keyword.toLowerCase())) return rule
    } else {
      try {
        if (new RegExp(rule.keyword, 'i').test(title)) return rule
      } catch {
        /* normalize 已保证可编译；防御 */
      }
    }
  }
  return null
}

export function FilterRulesSection() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const rules = settings.filterRules
  const stats = settings.filterStats

  // 添加对话框状态
  const [showAdd, setShowAdd] = useState(false)
  const [type, setType] = useState<'keyword' | 'regex'>('keyword')
  const [pattern, setPattern] = useState('')
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const setRules = (next: FilterRule[]) => update({ filterRules: next })

  const addRule = () => {
    const kw = pattern.trim()
    if (!kw) {
      setError('规则内容不能为空')
      return
    }
    if (type === 'regex') {
      try {
        new RegExp(kw, 'i')
      } catch (e) {
        setError(`正则无法编译：${(e as Error).message.slice(0, 60)}`)
        return
      }
    }
    // 去重（feedId,type,keyword 小写语义——OrigRead 同）
    if (
      rules.some(
        (r) => r.type === type && r.keyword.toLowerCase() === kw.toLowerCase() && r.feedId === null,
      )
    ) {
      setError('已存在相同规则')
      return
    }
    setRules([...rules, { id: crypto.randomUUID(), keyword: kw, feedId: null, type, enabled: true }])
    setShowAdd(false)
    setPattern('')
    setError(null)
  }

  const exportRules = () => {
    const blob = new Blob(
      [JSON.stringify({ schemaVersion: 1, rules: rules.map(({ id, ...rest }) => ({ id, ...rest })) }, null, 2)],
      { type: 'application/json' },
    )
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `LumiRSS-filter-rules-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const importRules = (file: File) => {
    file
      .text()
      .then((text) => {
        const data = JSON.parse(text) as { rules?: unknown }
        if (!Array.isArray(data.rules)) throw new Error('bad')
        // 走 normalize 归一化 + 去重（按 id 合并覆盖——OrigRead 同语义）
        const existing = new Map(rules.map((r) => [r.id, r]))
        for (const r of data.rules as FilterRule[]) {
          if (r && typeof r === 'object' && typeof r.id === 'string') existing.set(r.id, r)
        }
        const merged = normalizeSettings({
          ...useAppSettings.getState().settings,
          filterRules: [...existing.values()],
        })
        update({ filterRules: merged.filterRules })
      })
      .catch(() => alert('导入失败：文件不是有效的过滤规则 JSON'))
  }

  return (
    <div>
      {/* 统计卡片（OrigRead「累计过滤 N 篇」） */}
      <div className="mb-4 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3.5 py-2.5">
        <p className="text-xs text-[var(--lumi-text-secondary)]">
          累计过滤 <strong className="text-[var(--lumi-text-primary)]">{stats.totalFiltered}</strong>{' '}
          篇
          {stats.lastMatchedRule && (
            <>
              {' '}· 最近命中规则「{stats.lastMatchedRule}」
            </>
          )}
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
          当前为显示层过滤（列表渲染时隐藏匹配项，不改动 FreshRSS 数据）；
          BFF 读取层过滤将在 0013 订阅中心提供。设置页仅添加全局规则，
          来源级规则从订阅管理侧入口添加（0013）。
        </p>
      </div>

      {/* 操作行 */}
      <div className="mb-3 flex items-center gap-2">
        <Button size="sm" onClick={() => setShowAdd(true)}>
          添加过滤规则
        </Button>
        <Button size="sm" variant="ghost" onClick={exportRules} disabled={rules.length === 0}>
          <Download aria-hidden className="size-3.5" /> 导出
        </Button>
        <Button size="sm" variant="ghost" onClick={() => fileRef.current?.click()}>
          <Upload aria-hidden className="size-3.5" /> 导入
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="application/json"
          className="sr-only"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) importRules(f)
            e.target.value = ''
          }}
        />
      </div>

      {/* 添加对话框（内联展开，OrigRead AlertDialog 语义简化为行内表单） */}
      {showAdd && (
        <div className="mb-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-accent)] p-3.5">
          <div className="flex gap-1.5">
            {(
              [
                ['keyword', '关键词'],
                ['regex', '正则'],
              ] as const
            ).map(([v, label]) => (
              <button
                key={v}
                type="button"
                aria-pressed={type === v}
                onClick={() => {
                  setType(v)
                  setError(null)
                }}
                className={cx(
                  'rounded-[var(--lumi-radius-md)] border px-3 py-1.5 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
                  type === v
                    ? 'border-[var(--lumi-accent)] bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
                    : 'border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <input
            type="text"
            value={pattern}
            aria-label="规则内容"
            autoFocus
            onChange={(e) => {
              setPattern(e.target.value)
              setError(null)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') addRule()
            }}
            placeholder={type === 'keyword' ? '如：推广 / 广告 / 赞助' : '如：^(?=.*(广告))'}
            className="mt-2 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 text-sm text-[var(--lumi-text-primary)]"
          />
          {error && <p className="mt-1.5 text-xs text-[var(--lumi-danger)]">{error}</p>}
          <div className="mt-2.5 flex gap-2">
            <Button size="sm" onClick={addRule}>
              添加
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setShowAdd(false)
                setPattern('')
                setError(null)
              }}
            >
              取消
            </Button>
          </div>
        </div>
      )}

      {/* 规则列表 */}
      {rules.length === 0 ? (
        <p className="py-6 text-center text-xs text-[var(--lumi-text-tertiary)]">
          还没有过滤规则
        </p>
      ) : (
        <ul className="divide-y divide-[var(--lumi-separator)] rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]">
          {rules.map((r) => (
            <li key={r.id} className="flex items-center gap-3 px-3.5 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate font-mono text-sm text-[var(--lumi-text-primary)]">
                  {r.keyword}
                </p>
                <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
                  {r.feedId === null ? '全局规则' : '来源规则'} · {r.type === 'keyword' ? '关键词' : '正则'}
                </p>
              </div>
              <Switch
                checked={r.enabled}
                onCheckedChange={(v) =>
                  setRules(rules.map((x) => (x.id === r.id ? { ...x, enabled: v } : x)))
                }
                label={`启用规则 ${r.keyword}`}
              />
              <button
                type="button"
                aria-label={`删除规则 ${r.keyword}`}
                onClick={() => setRules(rules.filter((x) => x.id !== r.id))}
                className="flex size-8 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-danger)]"
              >
                <Trash2 aria-hidden className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
