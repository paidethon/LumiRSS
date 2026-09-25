/** E3-final 纯逻辑与组件测试 — N079 分栏 / N080 会话汇总 / N110 最近工作区
 * / N199 多步快捷操作 runner / N200 场景向导。
 *
 * 约定：device-local 库（localStorage 键、diff/undo、执行编排）的口径
 * 在这里锁定；服务端口径见 BFF 测试。
 */

import { describe, expect, it, beforeEach, vi } from 'vitest'
import {
  SECTION_KEYS,
  exportNoteMarkdown,
  normalizeSections,
  parseSectionText,
  renderTypedSections,
  sectionTextOf,
  emptySections,
} from '../lib/note-sections'
import {
  clearRecap,
  loadRecapNote,
  recordRecapEvent,
  saveRecapNote,
  sessionRecap,
} from '../lib/session-recap'
import {
  clearRecentWorkspaces,
  listRecentWorkspaces,
  recordRecentWorkspace,
} from '../lib/recent-workspaces'
import { runQuickAction } from '../lib/quick-action-runner'
import {
  BUILTIN_SCENARIOS,
  applyScenario,
  diffScenario,
  hasScenarioUndo,
  undoScenario,
} from '../lib/scenario-wizard'
import { DEFAULT_APP_SETTINGS, type AppSettings } from '../store/app-settings'

beforeEach(() => {
  localStorage.clear()
})

// ---- N079 分栏 ---------------------------------------------------------------

describe('N079 笔记与事实分栏', () => {
  it('AI 面标签：逐条 [事实]/[个人解读]/[待核实]，个人判断不表述为事实', () => {
    const rendered = renderTypedSections({
      facts: ['原文说 A 于 2020 年发布'],
      interpretation: ['我认为 A 是为了 B'],
      toVerify: ['B 需查证'],
    })
    expect(rendered.split('\n')).toEqual([
      '[事实] 原文说 A 于 2020 年发布',
      '[个人解读] 我认为 A 是为了 B',
      '[待核实] B 需查证',
    ])
  })

  it('normalizeSections 诚实降级：未知键丢弃、非法条目过滤', () => {
    const cleaned = normalizeSections({
      facts: [' a ', '', 42, 'b'],
      unknown: ['x'],
      interpretation: 'not-a-list',
    })
    expect(cleaned).toEqual({ facts: ['a', 'b'], interpretation: [], toVerify: [] })
  })

  it('导出保持类型：.md 文本带类型化分栏', () => {
    const markdown = exportNoteMarkdown(
      '标题',
      '正文内容',
      normalizeSections({ facts: ['F1'], toVerify: ['T1'] }),
    )
    expect(markdown).toContain('# 标题')
    expect(markdown).toContain('正文内容')
    expect(markdown).toContain('[事实] F1')
    expect(markdown).toContain('[待核实] T1')
    expect(markdown).not.toContain('[个人解读]')
  })

  it('textarea 文本与条目互逆（每行一条）', () => {
    const text = '第一行\n第二行\n\n  第三行  \n'
    const items = parseSectionText(text)
    expect(items).toEqual(['第一行', '第二行', '第三行'])
    expect(parseSectionText(sectionTextOf(items))).toEqual(items)
    expect(SECTION_KEYS).toEqual(['facts', 'interpretation', 'toVerify'])
    expect(emptySections()).toEqual({ facts: [], interpretation: [], toVerify: [] })
  })
})

// ---- N080 阅读成果汇总 -------------------------------------------------------

describe('N080 阅读成果汇总', () => {
  it('只统计窗口内实际创建的事件；entriesTouched 去重', () => {
    clearRecap()
    const now = Date.now()
    recordRecapEvent('annotation', 'e1', now - 5 * 60_000)
    recordRecapEvent('annotation', 'e1', now - 4 * 60_000)
    recordRecapEvent('question', 'e2', now - 10 * 60_000)
    recordRecapEvent('card', 'e3', now - 20 * 60_000)
    // 窗口外（40 分钟前）不计入
    recordRecapEvent('card', 'e4', now - 40 * 60_000)
    const recap = sessionRecap(30, now)
    expect(recap).toEqual({
      windowMinutes: 30,
      newAnnotations: 2,
      questions: 1,
      cards: 1,
      entriesTouched: 3,
    })
  })

  it('会话笔记本机保存并可改写；超限拒绝', () => {
    clearRecap()
    expect(saveRecapNote('第一版笔记')).toBe(true)
    expect(loadRecapNote()).toBe('第一版笔记')
    expect(saveRecapNote('第二版')).toBe(true)
    expect(loadRecapNote()).toBe('第二版')
    expect(saveRecapNote('x'.repeat(2001))).toBe(false)
  })
})

// ---- N110 最近工作区 ---------------------------------------------------------

describe('N110 最近工作区（per-user 键命名空间）', () => {
  it('打开即记录：置顶去重、上限 3、列表更新', () => {
    clearRecentWorkspaces('u1')
    recordRecentWorkspace('u1', { workspaceId: 'w1', name: '论文阅读' })
    recordRecentWorkspace('u1', { workspaceId: 'w2', name: '周报' })
    recordRecentWorkspace('u1', { workspaceId: 'w3', name: '代码追踪' })
    recordRecentWorkspace('u1', { workspaceId: 'w4', name: '第四个' })
    recordRecentWorkspace('u1', { workspaceId: 'w1', name: '论文阅读' }) // 去重置顶

    const list = listRecentWorkspaces('u1')
    expect(list).toHaveLength(3)
    expect(list[0].workspaceId).toBe('w1')
    expect(list.map((w) => w.workspaceId)).toEqual(['w1', 'w4', 'w3'])
  })

  it('per-user 键：另一账号的记录互不可见', () => {
    clearRecentWorkspaces('userA')
    clearRecentWorkspaces('userB')
    recordRecentWorkspace('userA', { workspaceId: 'wa', name: 'A 的' })
    recordRecentWorkspace('userB', { workspaceId: 'wb', name: 'B 的' })
    expect(listRecentWorkspaces('userA').map((w) => w.workspaceId)).toEqual(['wa'])
    expect(listRecentWorkspaces('userB').map((w) => w.workspaceId)).toEqual(['wb'])
    expect(() => {
      const raw = localStorage.getItem('lumirss-recent-workspaces:userA') ?? ''
      expect(raw).not.toContain('wb')
    }).not.toThrow()
  })

  it('点击打开（卡片回调）：记录事件携带 workspaceId（数据契约）', () => {
    clearRecentWorkspaces('u9')
    const next = recordRecentWorkspace('u9', { workspaceId: 'wx', name: 'X' })
    expect(next[0]).toMatchObject({ workspaceId: 'wx', name: 'X' })
    expect(typeof next[0].openedAt).toBe('string')
  })
})

// ---- N199 多步快捷操作 runner ------------------------------------------------

describe('N199 多步快捷操作 runner', () => {
  it('两步序列按序走各动作执行器（NORMAL 端点由执行器承载）', async () => {
    const calls: string[] = []
    const executors = {
      add_to_queue: async () => {
        calls.push('add_to_queue')
        return undefined
      },
      open_reader: async () => {
        calls.push('open_reader')
        return undefined
      },
    }
    const result = await runQuickAction(
      [
        { action: 'add_to_queue', params: { entryRef: 'e1' } },
        { action: 'open_reader' },
      ],
      executors,
    )
    expect(result.status).toBe('completed')
    expect(calls).toEqual(['add_to_queue', 'open_reader'])
    expect(result.steps.map((s) => s.outcome)).toEqual(['ok', 'ok'])
  })

  it('写步骤必须先确认：确认拒绝 → 该步 cancelled 且不再执行后续', async () => {
    const calls: string[] = []
    const confirm = vi.fn().mockResolvedValue(false)
    const result = await runQuickAction(
      [
        { action: 'open_reader' },
        { action: 'add_to_queue', write: true },
        { action: 'open_reader' },
      ],
      {
        open_reader: async () => {
          calls.push('open_reader')
        },
        add_to_queue: async () => {
          calls.push('add_to_queue')
        },
      },
      { confirm },
    )
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(calls).toEqual(['open_reader'])
    expect(result.status).toBe('cancelled')
    expect(result.steps[1]?.outcome).toBe('cancelled')
  })

  it('stop-on-error：第二步失败 → 第三步不执行', async () => {
    const calls: string[] = []
    const result = await runQuickAction(
      [
        { action: 'a' },
        { action: 'b' },
        { action: 'c' },
      ],
      {
        a: async () => {
          calls.push('a')
        },
        b: async () => {
          calls.push('b')
          throw new Error('queue 409')
        },
        c: async () => {
          calls.push('c')
        },
      },
    )
    expect(calls).toEqual(['a', 'b'])
    expect(result.status).toBe('stopped')
    expect(result.failedIndex).toBe(1)
    expect((result.error as Error).message).toBe('queue 409')
  })
})

// ---- N200 场景向导 -----------------------------------------------------------

describe('N200 功能组合场景向导', () => {
  const current = (patch: Partial<AppSettings> = {}): AppSettings => ({
    ...DEFAULT_APP_SETTINGS,
    ...patch,
  })

  it('三个内置场景各有具体键值组合', () => {
    expect(BUILTIN_SCENARIOS.map((s) => s.id)).toEqual([
      'commute-listening',
      'technical-reading',
      'material-organizing',
    ])
    for (const scenario of BUILTIN_SCENARIOS) {
      expect(scenario.changes.length).toBeGreaterThanOrEqual(3)
      for (const change of scenario.changes) {
        expect(change.label).not.toBe('')
      }
    }
  })

  it('diff 预览列出精确键（只含会变的键）', () => {
    const technical = BUILTIN_SCENARIOS.find((s) => s.id === 'technical-reading')!
    const diff = diffScenario(current({ readerCodeWrap: true }), technical.changes)
    const keys = diff.map((d) => d.key)
    expect(keys).toContain('readerFontFamily')
    expect(keys).toContain('readerContentWidth')
    expect(keys).not.toContain('readerCodeWrap') // 已同值 → 不出现在 diff
  })

  it('应用：快照旧值 → 设置真的变化；整体撤销逐键还原', () => {
    const scenario = BUILTIN_SCENARIOS.find((s) => s.id === 'commute-listening')!
    let settings = current({ speechSkipCode: true }) // 与场景部分重合
    const result = applyScenario(settings, scenario)
    expect(result.undoAvailable).toBe(true)

    // 模拟 settings.update(patch) 后的设置状态
    const patch: Record<string, unknown> = {}
    for (const change of scenario.changes) {
      if (result.appliedKeys.includes(change.key)) patch[change.key as string] = change.value
    }
    settings = { ...settings, ...patch } as AppSettings
    expect(settings.speechSleepTimerMinutes).toBe(30)
    expect(settings.speechSkipCode).toBe(true)

    // 整体撤销：每个键恢复到快照值（同值键不出现在 patch，少写为净）
    const undoPatch = undoScenario(settings)
    expect(undoPatch).not.toBeNull()
    settings = { ...settings, ...undoPatch } as AppSettings
    expect(settings.speechSleepTimerMinutes).toBe(
      DEFAULT_APP_SETTINGS.speechSleepTimerMinutes,
    )
    expect(settings.speechSkipCode).toBe(true) // 快照里本来就是 true
    expect(hasScenarioUndo()).toBe(false) // 撤销后清空快照
  })
})
