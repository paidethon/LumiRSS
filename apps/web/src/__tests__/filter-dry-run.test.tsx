/** F31 规则试运行 — 与真实执行同引擎的匹配预览。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import {
  FilterRulesSection,
  matchesFilterRules,
} from '../components/settings/FilterRulesPage'
import { useAppSettings, DEFAULT_APP_SETTINGS, type FilterRule } from '../store/app-settings'

const RULES: FilterRule[] = [
  { id: 'r1', keyword: '促销', feedId: null, type: 'keyword', enabled: true },
  { id: 'r2', keyword: '^AI\\s周报', feedId: null, type: 'regex', enabled: true },
  { id: 'r3', keyword: '已停用词', feedId: null, type: 'keyword', enabled: false },
]

describe('matchesFilterRules（引擎不变量）', () => {
  beforeEach(() => {
    useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS, filterRules: RULES } })
  })

  it('命中启用规则；停用规则不参与；返回命中的规则对象', () => {
    expect(matchesFilterRules('双11 促销来了', RULES, null)?.id).toBe('r1')
    expect(matchesFilterRules('AI 周报 #1', RULES, null)?.id).toBe('r2')
    expect(matchesFilterRules('包含已停用词的标题', RULES, null)).toBeNull()
    expect(matchesFilterRules('普通技术文章', RULES, null)).toBeNull()
  })
})

describe('FilterDryRun（试运行 UI）', () => {
  function setup() {
    useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS, filterRules: RULES } })
    return render(<FilterRulesSection />)
  }

  it('粘贴样本后显示命中/不匹配与原因，不修改规则状态', () => {
    setup()
    fireEvent.click(screen.getByText(/规则试运行/))
    const input = screen.getByLabelText('试运行样本标题')
    fireEvent.change(input, { target: { value: '双11 促销来了\n普通技术文章' } })
    fireEvent.click(screen.getByRole('button', { name: /试运行（2 条样本）/ }))
    expect(screen.getByText('命中：促销')).toBeInTheDocument()
    expect(screen.getByText('不匹配（保留）')).toBeInTheDocument()
    // 规则列表仍在（试运行无副作用）
    expect(screen.getByText('促销')).toBeInTheDocument()
  })
})
