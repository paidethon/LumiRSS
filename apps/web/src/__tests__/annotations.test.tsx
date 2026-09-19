/** F20 批注测试 — 锚点纯函数（含失效）+ 存储 + AnnotationsLayer 渲染。
 *
 * 环境：jsdom 无 CSS Custom Highlight API —— 组件必须无异常降级
 * （无高亮渲染但批注卡列表仍可见），本文件全部用例即在该降级态下通过。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ANNOTATIONS_STORAGE_KEY,
  articleText,
  computeContentVersion,
  createAnchor,
  deleteAnnotation,
  readAllAnnotations,
  readAnnotationsForEntry,
  resolveAnchor,
  saveAnnotation,
  type Annotation,
} from '../lib/annotations'
import AnnotationsLayer from '../components/AnnotationsLayer'

function makeArticle(html = '<p>前奏文字。</p><p>LumiRSS 是一个自托管的阅读器，支持 RSS 与 Atom 订阅。</p><p>结尾文字。</p>'): HTMLElement {
  const div = document.createElement('div')
  div.className = 'lumi-reader-article'
  div.innerHTML = html
  document.body.appendChild(div)
  return div
}

/** 在容器内的第 idx 个 <p> 中按字符区间建选区 */
function selectRange(container: HTMLElement, pIndex: number, start: number, end: number): Range {
  const p = container.querySelectorAll('p')[pIndex]!
  const range = document.createRange()
  const textNode = p.firstChild!
  range.setStart(textNode, start)
  range.setEnd(textNode, end)
  return range
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  // 只移除本测试自建的文章容器（非 React 托管）；React 门户节点交给
  // setup.ts 的 cleanup() 卸载（清空 body.innerHTML 会撕裂 React 卸载）
  document.querySelectorAll('.lumi-reader-article').forEach((el) => el.remove())
  vi.restoreAllMocks()
})

describe('annotations 纯函数', () => {
  it('createAnchor：取选区文本 + 前后各 24 字符上下文', () => {
    const container = makeArticle(
      `<p>${'甲'.repeat(30)}</p><p>LumiRSS 是一个自托管的阅读器。</p><p>${'乙'.repeat(30)}</p>`,
    )
    const range = selectRange(container, 1, 0, 9) // "LumiRSS 是"
    const created = createAnchor(container, range)
    expect(created).not.toBeNull()
    expect(created!.text).toBe('LumiRSS 是')
    expect(created!.anchor.exact).toBe('LumiRSS 是')
    expect(created!.anchor.prefix).toBe('甲'.repeat(24))
    expect(created!.anchor.suffix).toBe('一个自托管的阅读器。' + '乙'.repeat(14))
    expect(created!.anchor.prefix.length).toBeLessThanOrEqual(24)
    expect(created!.anchor.suffix.length).toBeLessThanOrEqual(24)
  })

  it('createAnchor：空选区返回 null（不静默造锚点）', () => {
    const container = makeArticle()
    const range = selectRange(container, 1, 3, 3)
    expect(createAnchor(container, range)).toBeNull()
  })

  it('resolveAnchor：优先 prefix+exact+suffix 整体匹配', () => {
    const container = makeArticle()
    const range = selectRange(container, 1, 0, 9)
    const created = createAnchor(container, range)!
    const hit = resolveAnchor(container, created.anchor)
    expect(hit).not.toBeNull()
    const full = articleText(container)
    expect(full.slice(hit!.start, hit!.end)).toBe('LumiRSS 是')
  })

  it('resolveAnchor：上下文对不上时退化 exact 仍命中', () => {
    const container = makeArticle()
    const hit = resolveAnchor(container, {
      prefix: '完全错误的上下文',
      exact: '自托管的阅读器',
      suffix: '也是错的',
    })
    expect(hit).not.toBeNull()
    const full = articleText(container)
    expect(full.slice(hit!.start, hit!.end)).toBe('自托管的阅读器')
  })

  it('resolveAnchor：正文不含目标文本 → null（锚点失效）', () => {
    const container = makeArticle()
    expect(resolveAnchor(container, { prefix: 'a', exact: '不存在的句子', suffix: 'b' })).toBeNull()
  })

  it('articleText：排除组件注入的覆盖层文本（摘录不污染正文对照）', () => {
    const container = makeArticle()
    const overlay = document.createElement('div')
    overlay.setAttribute('data-lumi-annotations-overlay', 'true')
    overlay.textContent = '批注卡片文字'
    container.appendChild(overlay)
    expect(articleText(container)).not.toContain('批注卡片文字')
  })

  it('computeContentVersion：长度+首32字符 hash；文本变化指纹变化且稳定', () => {
    const a = computeContentVersion('hello world')
    expect(a).toBe(computeContentVersion('hello world'))
    expect(a).not.toBe(computeContentVersion('hello worlds'))
    expect(a).toMatch(/^\d+:[0-9a-f]{8}$/)
  })
})

describe('annotations 存储（localStorage，设备本地）', () => {
  const base: Annotation = {
    id: 'a1',
    entryRef: 'e1',
    color: 'yellow',
    note: '第一条',
    anchor: { prefix: '', exact: '自托管', suffix: '' },
    createdAt: 1,
    contentVersion: 'x',
  }

  it('保存/读取/upsert/删除', () => {
    saveAnnotation(base)
    saveAnnotation({ ...base, id: 'a2', createdAt: 2 })
    saveAnnotation({ ...base, id: 'a1', note: '改过' }) // upsert
    expect(readAnnotationsForEntry('e1').map((a) => a.id)).toEqual(['a1', 'a2'])
    expect(readAnnotationsForEntry('e1')[0]!.note).toBe('改过')
    deleteAnnotation('a1')
    expect(readAnnotationsForEntry('e1').map((a) => a.id)).toEqual(['a2'])
  })

  it('按 entryRef 索引；损坏 JSON → 空数组不抛错', () => {
    saveAnnotation({ ...base, entryRef: 'other' })
    expect(readAnnotationsForEntry('e1')).toHaveLength(0)
    localStorage.setItem(ANNOTATIONS_STORAGE_KEY, '{broken')
    expect(readAllAnnotations()).toEqual([])
    localStorage.setItem(ANNOTATIONS_STORAGE_KEY, JSON.stringify([{ nope: true }]))
    expect(readAllAnnotations()).toEqual([])
  })

  it('只写自己的 key，不碰其它 localStorage 数据', () => {
    localStorage.setItem('lumirss-settings', '{"keep":true}')
    saveAnnotation(base)
    expect(JSON.parse(localStorage.getItem('lumirss-settings')!)).toEqual({ keep: true })
    expect(localStorage.getItem(ANNOTATIONS_STORAGE_KEY)).not.toBeNull()
  })
})

describe('AnnotationsLayer 组件', () => {
  it('已有批注：挂载后解析并渲染批注卡（localStorage 恢复，无高亮 API 也不抛错）', () => {
    const container = makeArticle()
    saveAnnotation({
      id: 'a1',
      entryRef: 'e1',
      color: 'green',
      note: '重点句',
      anchor: { prefix: '', exact: '自托管的阅读器', suffix: '' },
      createdAt: 1,
      contentVersion: computeContentVersion(articleText(container)),
    })
    // jsdom 无 CSS.highlights：render 不抛异常即降级成立
    expect(() => render(<AnnotationsLayer entryRef="e1" />)).not.toThrow()
    expect(screen.getByText('批注（1）')).toBeInTheDocument()
    expect(screen.getByText('重点句')).toBeInTheDocument()
    // 卡片列表注入在正文容器末尾（带 overlay 标记，不污染锚点对照文本）
    expect(container.querySelector('[data-lumi-annotations-cards]')).not.toBeNull()
  })

  it('锚点失效：诚实标注「锚点失效」，跳回按钮禁用', () => {
    makeArticle('<p>正文已经完全变了。</p>')
    saveAnnotation({
      id: 'lost',
      entryRef: 'e1',
      color: 'pink',
      note: '',
      anchor: { prefix: '', exact: '原文里才有的一句话', suffix: '' },
      createdAt: 1,
      contentVersion: '',
    })
    render(
      <AnnotationsLayer
        entryRef="e1"
        containerRef={{ current: document.querySelector('.lumi-reader-article') }}
      />,
    )
    expect(screen.getByText(/锚点失效/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '跳回原文' })).toBeDisabled()
  })

  it('选区 → 浮动条 → Popover 备注/颜色 → 保存（localStorage 落盘 + 列表渲染）', async () => {
    const container = makeArticle()
    render(<AnnotationsLayer entryRef="e1" />)
    const sel = window.getSelection()!
    sel.removeAllRanges()
    sel.addRange(selectRange(container, 1, 0, 9)) // "LumiRSS 是"
    fireEvent.mouseUp(container)

    fireEvent.click(screen.getByRole('button', { name: '创建批注' }))
    const dialog = screen.getByRole('dialog', { name: '批注' })
    expect(dialog).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('批注备注'), { target: { value: '很关键' } })
    fireEvent.click(screen.getByRole('radio', { name: '绿色' }))
    fireEvent.click(screen.getByRole('button', { name: '保存批注' }))

    await waitFor(() => {
      expect(screen.getByText('批注（1）')).toBeInTheDocument()
    })
    expect(screen.getByText('很关键')).toBeInTheDocument()
    const stored = readAllAnnotations()
    expect(stored).toHaveLength(1)
    expect(stored[0]).toMatchObject({ entryRef: 'e1', color: 'green', note: '很关键' })
    expect(stored[0]!.anchor.exact).toBe('LumiRSS 是')
  })

  it('删除：列表移除且 localStorage 同步清空', async () => {
    const container = makeArticle()
    saveAnnotation({
      id: 'a1',
      entryRef: 'e1',
      color: 'yellow',
      note: '待删',
      anchor: { prefix: '', exact: '自托管的阅读器', suffix: '' },
      createdAt: 1,
      contentVersion: computeContentVersion(articleText(container)),
    })
    render(<AnnotationsLayer entryRef="e1" />)
    expect(screen.getByText('批注（1）')).toBeInTheDocument()
    // 删除有确认语义的按钮文案（直接删，本设备数据可重建）
    fireEvent.click(screen.getByRole('button', { name: '删除' }))
    await waitFor(() => {
      expect(screen.getByText(/本文还没有批注/)).toBeInTheDocument()
    })
    expect(readAllAnnotations()).toHaveLength(0)
  })

  it('刷新后恢复：重新 mount（模拟再次打开文章）批注仍在', () => {
    const container = makeArticle()
    saveAnnotation({
      id: 'a1',
      entryRef: 'e1',
      color: 'yellow',
      note: '第一次会话',
      anchor: { prefix: '', exact: '自托管的阅读器', suffix: '' },
      createdAt: 1,
      contentVersion: computeContentVersion(articleText(container)),
    })
    const first = render(<AnnotationsLayer entryRef="e1" />)
    first.unmount()
    render(<AnnotationsLayer entryRef="e1" />)
    expect(screen.getByText('批注（1）')).toBeInTheDocument()
    expect(screen.getByText('第一次会话')).toBeInTheDocument()
  })

  it('跳回原文：滚动到命中位置（scrollIntoView 被 stub 调用）', () => {
    makeArticle()
    saveAnnotation({
      id: 'a1',
      entryRef: 'e1',
      color: 'yellow',
      note: '',
      anchor: { prefix: '', exact: '自托管的阅读器', suffix: '' },
      createdAt: 1,
      contentVersion: '',
    })
    const spy = vi.fn()
    Element.prototype.scrollIntoView = spy
    render(<AnnotationsLayer entryRef="e1" />)
    fireEvent.click(screen.getByRole('button', { name: '跳回原文' }))
    expect(spy).toHaveBeenCalled()
  })
})
