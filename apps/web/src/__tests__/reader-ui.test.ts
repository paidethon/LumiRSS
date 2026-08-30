import { beforeEach, describe, expect, it } from 'vitest'
import { useReaderUi } from '../store/reader-ui'

beforeEach(() => {
  // zustand store 是模块级单例：每个测试前重置回初始状态。
  useReaderUi.setState({
    section: 'home',
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
})

describe('Test D — UI store（0011 scope 模型）', () => {
  it('初始状态：all / 全部信息源 / 无 entry', () => {
    const state = useReaderUi.getState()
    expect(state.view).toBe('all')
    expect(state.scope).toEqual({ kind: 'all' })
    expect(state.selectedEntryRef).toBeNull()
  })

  it('selectView 生效', () => {
    useReaderUi.getState().selectView('unread')
    expect(useReaderUi.getState().view).toBe('unread')
  })

  it('selectScope 生效（四级：all/rss/category/feed）', () => {
    useReaderUi.getState().selectScope({ kind: 'rss' })
    expect(useReaderUi.getState().scope).toEqual({ kind: 'rss' })
    useReaderUi.getState().selectScope({ kind: 'rss-category', categoryId: 'user/-/label/技术', categoryLabel: '技术' })
    expect(useReaderUi.getState().scope).toEqual({ kind: 'rss-category', categoryId: 'user/-/label/技术', categoryLabel: '技术' })
    useReaderUi.getState().selectScope({ kind: 'rss-feed', feedUrl: 'https://example.com/feed.xml' })
    expect(useReaderUi.getState().scope).toEqual({ kind: 'rss-feed', feedUrl: 'https://example.com/feed.xml' })
    useReaderUi.getState().selectScope({ kind: 'all' })
    expect(useReaderUi.getState().scope).toEqual({ kind: 'all' })
  })

  it('selectEntry 生效且不影响 view/scope', () => {
    useReaderUi.getState().selectView('unread')
    useReaderUi.getState().selectScope({ kind: 'rss-feed', feedUrl: 'https://example.com/feed.xml' })
    useReaderUi.getState().selectEntry('e1.fake')

    const state = useReaderUi.getState()
    expect(state.selectedEntryRef).toBe('e1.fake')
    expect(state.view).toBe('unread')
    expect(state.scope).toEqual({ kind: 'rss-feed', feedUrl: 'https://example.com/feed.xml' })
  })

  it('切 view → selectedEntryRef 清空', () => {
    useReaderUi.getState().selectEntry('e1.fake')
    useReaderUi.getState().selectView('starred')
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
  })

  it('切 scope → selectedEntryRef 清空（§15）', () => {
    useReaderUi.getState().selectEntry('e1.fake')
    useReaderUi.getState().selectScope({ kind: 'rss-feed', feedUrl: 'https://example.com/feed.xml' })
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
  })

  it('重复选择同一 view/scope 是幂等 no-op（不清空已有 entry selection）', () => {
    useReaderUi.getState().selectView('unread')
    useReaderUi.getState().selectScope({ kind: 'rss-feed', feedUrl: 'https://example.com/feed.xml' })
    useReaderUi.getState().selectEntry('e1.fake')

    useReaderUi.getState().selectView('unread')
    useReaderUi.getState().selectScope({ kind: 'rss-feed', feedUrl: 'https://example.com/feed.xml' })

    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.fake')
  })
})
