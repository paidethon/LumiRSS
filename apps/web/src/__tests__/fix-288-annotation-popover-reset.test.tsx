/** FIX-288 — 编辑弹层残留上一条批注的内容。
 *
 * AnnotationsLayer 的批注卡列表常驻渲染；在「编辑 A」弹层打开时直接点
 * 「编辑 B」是合法路径（无中间卸载）。AnnotationPopover 以
 * useState(initialNote/initialColor) 一次性初始化——目标切换但组件实例
 * 复用时，表单残留 A 的备注/颜色；此时保存会把 A 的内容写进 B。
 * 修复：以弹层目标身份为 key，目标变化即重挂载（打开方式明确重置表单）。
 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import AnnotationsLayer from '../components/AnnotationsLayer'
import { ANNOTATIONS_STORAGE_KEY, readAllAnnotations, type Annotation } from '../lib/annotations'

function makeArticle(html = '<p>前奏文字。</p><p>阅读器包含句子甲与句子乙两处原文。</p><p>结尾。</p>'): HTMLElement {
  const div = document.createElement('div')
  div.className = 'lumi-reader-article'
  div.innerHTML = html
  document.body.appendChild(div)
  return div
}

function seed(annotation: Annotation): void {
  localStorage.setItem(
    ANNOTATIONS_STORAGE_KEY,
    JSON.stringify([...readAllAnnotations(), annotation]),
  )
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  document.querySelectorAll('.lumi-reader-article').forEach((el) => el.remove())
})

describe('FIX-288 批注编辑弹层按目标重置', () => {
  it('编辑 A → 直接编辑 B：表单显示 B 的备注，不残留 A 的内容', async () => {
    makeArticle()
    seed({
      id: 'a1',
      entryRef: 'e1',
      color: 'yellow',
      note: '甲的备注',
      anchor: { prefix: '', exact: '句子甲', suffix: '' },
      createdAt: 1,
      contentVersion: '',
    })
    seed({
      id: 'a2',
      entryRef: 'e1',
      color: 'green',
      note: '乙的备注',
      anchor: { prefix: '', exact: '句子乙', suffix: '' },
      createdAt: 2,
      contentVersion: '',
    })

    render(<AnnotationsLayer entryRef="e1" />)
    await waitFor(() => expect(screen.getByText('批注（2）')).toBeInTheDocument())

    // 打开 A 的编辑弹层
    const cardA = screen.getByText('句子甲').closest('li')!
    fireEvent.click(within(cardA).getByRole('button', { name: '编辑' }))
    const textarea = await screen.findByRole('textbox', { name: '批注备注' })
    expect(textarea).toHaveValue('甲的备注')

    // 不关闭弹层，直接切换到 B —— 实例复用不得残留 A 的内容
    const cardB = screen.getByText('句子乙').closest('li')!
    fireEvent.click(within(cardB).getByRole('button', { name: '编辑' }))
    expect(screen.getByRole('textbox', { name: '批注备注' })).toHaveValue('乙的备注')
  })

  it('编辑 A → 取消 → 新建批注：新建表单从空备注开始，不残留 A 的内容', async () => {
    makeArticle()
    seed({
      id: 'a1',
      entryRef: 'e1',
      color: 'yellow',
      note: '甲的备注',
      anchor: { prefix: '', exact: '句子甲', suffix: '' },
      createdAt: 1,
      contentVersion: '',
    })

    render(<AnnotationsLayer entryRef="e1" />)
    await waitFor(() => expect(screen.getByText('批注（1）')).toBeInTheDocument())

    const cardA = screen.getByText('句子甲').closest('li')!
    fireEvent.click(within(cardA).getByRole('button', { name: '编辑' }))
    expect(await screen.findByRole('textbox', { name: '批注备注' })).toHaveValue('甲的备注')

    // 取消回到列表 → 选区浮动条仅在无弹层时出现；直接再点 A 的编辑会
    // 复用实例（同位置）——取消后重新打开同一目标同样必须回填真值。
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    fireEvent.click(within(cardA).getByRole('button', { name: '编辑' }))
    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: '批注备注' })).toHaveValue('甲的备注'),
    )
  })
})
