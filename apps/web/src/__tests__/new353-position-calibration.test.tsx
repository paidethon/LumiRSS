/** NEW-353 阅读位置手动校准 — 纯逻辑 + 面板（jsdom）。
 *
 * 覆盖：段落收集（章节归属 / 标题也是合法锚点 / 空文本块跳过 / 截断
 * 上限）；章节分组（toc 标题回填 / 无章节 → 全文组）；ratio 纯计算钳制；
 * 面板主路径（选章节 → 选段落 → 保存 → loadReadingPosition 命中所选
 * 锚点；恢复端零改动）。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import PositionCalibrationPanel from '../components/new351/PositionCalibrationPanel'
import {
  CALIBRATION_PARAGRAPH_CAP,
  calibrationRatio,
  calibrationRestoreTop,
  collectCalibrationParagraphs,
  groupCalibrationByChapter,
} from '../lib/reading-position-calibration'
import { forgetReadingPositionsForTest, loadReadingPosition } from '../lib/reading-position'
import type { TocEntry } from '../lib/article-toc'

/** 带章节 id 的正文（模拟 withHeadingIds 注入后的产物）。 */
function buildArticle(): HTMLElement {
  const host = document.createElement('div')
  host.innerHTML = `
    <article class="lumi-reader-article">
      <h2 id="toc-intro">第一章 引言</h2>
      <p>引言第一段的完整文本内容</p>
      <p>引言第二段的完整文本内容</p>
      <h3 id="toc-method">第二章 方法</h3>
      <p>方法第一段的完整文本内容</p>
      <blockquote>引用块的完整文本内容</blockquote>
      <p></p>
    </article>`
  document.body.appendChild(host)
  return host.querySelector('article') as HTMLElement
}

/** 无章节 id 的正文（全部归入全文组）。 */
function buildPlainArticle(): HTMLElement {
  const host = document.createElement('div')
  host.innerHTML = `
    <article class="lumi-reader-article">
      <p>甲段的完整文本内容</p>
      <p>乙段的完整文本内容</p>
      <h2>无 id 标题</h2>
      <p>丙段的完整文本内容</p>
      <blockquote>丁块的完整文本内容</blockquote>
    </article>`
  document.body.appendChild(host)
  return host.querySelector('article') as HTMLElement
}

beforeEach(() => {
  document.body.innerHTML = ''
  window.localStorage.clear()
  forgetReadingPositionsForTest()
})

describe('NEW-353 校准纯逻辑', () => {
  it('段落收集：文档序编号 + 章节归属；标题也是合法锚点；空文本块跳过', () => {
    const article = buildArticle()
    const paragraphs = collectCalibrationParagraphs(article)
    expect(paragraphs.map((p) => p.index)).toEqual([0, 1, 2, 3, 4, 5])
    // 章节标题（h2/h3）进入其开启的章节组（= 以本章开头为位置）
    expect(paragraphs[0]).toMatchObject({
      chapterId: 'toc-intro',
      chapterTitle: '第一章 引言',
      anchorText: '第一章 引言',
    })
    expect(paragraphs[2]).toMatchObject({ chapterId: 'toc-intro', anchorText: '引言第二段的完整文本内容' })
    expect(paragraphs[3]).toMatchObject({ chapterId: 'toc-method', chapterTitle: '第二章 方法' })
    expect(paragraphs[5]!.anchorText).toBe('引用块的完整文本内容')
  })

  it('正文未挂载 → 空数组（诚实不可校准）', () => {
    expect(collectCalibrationParagraphs(null)).toEqual([])
  })

  it('章节分组：toc 标题回填；无章节段落归入全文组', () => {
    const host = document.createElement('div')
    host.innerHTML = `<article class="lumi-reader-article"><p>无章节段落甲</p><h2 id="toc-a">章节A</h2><p>章节A段落</p></article>`
    document.body.appendChild(host)
    const paragraphs = collectCalibrationParagraphs(host.querySelector('article'))
    const groups = groupCalibrationByChapter(paragraphs, [
      { id: 'toc-a', text: '章节A标题（toc）', level: 2 },
    ])
    expect(groups.map((g) => g.title)).toEqual(['全文（无章节）', '章节A标题（toc）'])
    // 全文组：p 无章节段落甲；章节A组：h2 标题自身 + p 章节A段落
    expect(groups[0]!.paragraphs.length).toBe(1)
    expect(groups[1]!.paragraphs.length).toBe(2)
  })

  it('收集截断：超过上限停止（诚实提示口径）', () => {
    const host = document.createElement('div')
    host.innerHTML = `<article class="lumi-reader-article">${Array.from(
      { length: CALIBRATION_PARAGRAPH_CAP + 50 },
      (_, i) => `<p>段落${i}</p>`,
    ).join('')}</article>`
    document.body.appendChild(host)
    const paragraphs = collectCalibrationParagraphs(host.querySelector('article'))
    expect(paragraphs.length).toBe(CALIBRATION_PARAGRAPH_CAP)
  })

  it('ratio 纯计算：钳制 0..1；无滚动空间 → 0；restoreTop 公式与恢复端一致', () => {
    expect(calibrationRatio(500, 2000, 1000)).toBe(0.5)
    expect(calibrationRatio(-20, 2000, 1000)).toBe(0)
    expect(calibrationRatio(2000, 2000, 1000)).toBe(1)
    expect(calibrationRatio(100, 500, 500)).toBe(0)
    expect(calibrationRestoreTop(300, 100, 50)).toBe(238)
    expect(calibrationRestoreTop(50, 100, 0)).toBe(0)
  })
})

describe('NEW-353 校准面板', () => {
  it('主路径：选章节 → 选段落 → 保存 → 本机位置记忆命中所选锚点', () => {
    const article = buildArticle()
    const scroller = document.createElement('div')
    document.body.appendChild(scroller)
    const toc: TocEntry[] = [
      { id: 'toc-intro', text: '第一章 引言', level: 2 },
      { id: 'toc-method', text: '第二章 方法', level: 3 },
    ]
    render(
      <PositionCalibrationPanel
        entryRef="rss:e1"
        toc={toc}
        getArticle={() => article}
        getScroller={() => scroller}
        onClose={() => {}}
      />,
    )
    const select = screen.getByTestId('n353-chapter-select') as HTMLSelectElement
    expect(select.value).toBe('toc-intro')
    // 第一章组：h2 标题 / 引言第一段 / 引言第二段 → 第 3 项 = 引言第二段
    fireEvent.click(screen.getByLabelText('第 3 段'))
    fireEvent.click(screen.getByTestId('n353-save'))
    expect(screen.getByText('已保存到本机位置记忆')).toBeTruthy()
    const saved = loadReadingPosition('rss:e1')
    expect(saved).not.toBeNull()
    expect(saved!.anchorText).toBe('引言第二段的完整文本内容')
  })

  it('未选段落时保存禁用；选择后可保存（全文组亦然）', () => {
    const article = buildPlainArticle()
    render(
      <PositionCalibrationPanel
        entryRef="rss:e1"
        toc={[]}
        getArticle={() => article}
        getScroller={() => null}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText(/全文（无章节）/)).toBeTruthy()
    expect((screen.getByTestId('n353-save') as HTMLButtonElement).disabled).toBe(true)
    // 全文组：甲 / 乙 / 无id标题 / 丙 / 丁 → 第 5 项 = 丁块
    fireEvent.click(screen.getByLabelText('第 5 段'))
    expect((screen.getByTestId('n353-save') as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(screen.getByTestId('n353-save'))
    expect(loadReadingPosition('rss:e1')!.anchorText).toBe('丁块的完整文本内容')
  })

  it('正文未挂载 → 诚实提示不可校准', () => {
    render(
      <PositionCalibrationPanel
        entryRef="rss:e1"
        toc={[]}
        getArticle={() => null}
        getScroller={() => null}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText(/正文尚未挂载或没有可校准的段落/)).toBeTruthy()
  })
})
