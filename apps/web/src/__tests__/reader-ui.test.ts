import { beforeEach, describe, expect, it } from 'vitest'
import { useReaderUi } from '../store/reader-ui'

beforeEach(() => {
  // zustand store 是模块级单例：每个测试前重置回初始状态。
  useReaderUi.setState({
    view: 'all',
    selectedFeedUrl: null,
    selectedEntryRef: null,
  })
})

describe('Test D — UI store', () => {
  it('初始状态：all / 无 feed / 无 entry', () => {
    const state = useReaderUi.getState()
    expect(state.view).toBe('all')
    expect(state.selectedFeedUrl).toBeNull()
    expect(state.selectedEntryRef).toBeNull()
  })

  it('selectView 生效', () => {
    useReaderUi.getState().selectView('unread')
    expect(useReaderUi.getState().view).toBe('unread')
  })

  it('selectFeed 生效（null = All Feeds）', () => {
    useReaderUi.getState().selectFeed('https://example.com/feed.xml')
    expect(useReaderUi.getState().selectedFeedUrl).toBe('https://example.com/feed.xml')
    useReaderUi.getState().selectFeed(null)
    expect(useReaderUi.getState().selectedFeedUrl).toBeNull()
  })

  it('selectEntry 生效且不影响 view/feed', () => {
    useReaderUi.getState().selectView('unread')
    useReaderUi.getState().selectFeed('https://example.com/feed.xml')
    useReaderUi.getState().selectEntry('e1.fake')

    const state = useReaderUi.getState()
    expect(state.selectedEntryRef).toBe('e1.fake')
    expect(state.view).toBe('unread')
    expect(state.selectedFeedUrl).toBe('https://example.com/feed.xml')
  })

  it('切 view → selectedEntryRef 清空', () => {
    useReaderUi.getState().selectEntry('e1.fake')
    useReaderUi.getState().selectView('starred')
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
  })

  it('切 feed → selectedEntryRef 清空', () => {
    useReaderUi.getState().selectEntry('e1.fake')
    useReaderUi.getState().selectFeed('https://example.com/feed.xml')
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
  })

  it('重复选择同一 view/feed 是幂等 no-op（不清空已有 entry selection）', () => {
    useReaderUi.getState().selectView('unread')
    useReaderUi.getState().selectFeed('https://example.com/feed.xml')
    useReaderUi.getState().selectEntry('e1.fake')

    useReaderUi.getState().selectView('unread')
    useReaderUi.getState().selectFeed('https://example.com/feed.xml')

    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.fake')
  })
})
