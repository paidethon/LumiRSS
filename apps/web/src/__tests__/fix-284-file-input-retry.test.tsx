/** FIX-284 — 上传输入选择同一文件可重试。
 *
 * 契约：文件导入失败后，input 必须被组件重置回「未选择」状态
 * （onChange 内 value=''），使再次选择同一文件仍触发导入——绝不因
 * 浏览器 same-file no-op 卡死重试路径。
 *
 * 基线现状（BASELINE_OK 验证）：代码库全部 type="file" 均在 onChange
 * 内无条件 `e.target.value = ''`（与导入成败无关）。本文件以
 * FilterRulesSection（纯客户端 JSON 导入，可确定性失败）为代表性
 * 表面验证该机制。jsdom 的 file input value 与 programmatic files
 * 不联动——直接断言 input.value 无法区分「已重置/未重置」，故侦听
 * value setter 观察组件的写入（机制本身）。
 */

import { fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FilterRulesSection } from '../components/settings/FilterRulesPage'
import { useAppSettings, DEFAULT_APP_SETTINGS } from '../store/app-settings'

function makeFile(text: string, name = 'rules.json'): File {
  return new File([text], name, { type: 'application/json' })
}

/** 记录组件对 input.value 的全部写入，返回读取函数。 */
function spyValueWrites(input: HTMLInputElement): () => string[] {
  const writes: string[] = []
  const proto = Object.getPrototypeOf(input) as object
  const descriptor = Object.getOwnPropertyDescriptor(proto, 'value')!
  Object.defineProperty(input, 'value', {
    configurable: true,
    get() {
      return descriptor.get?.call(input) ?? ''
    },
    set(v: string) {
      writes.push(v)
      descriptor.set?.call(input, v)
    },
  })
  return () => writes
}

function selectFile(input: HTMLInputElement, file: File): void {
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  fireEvent.change(input)
}

beforeEach(() => {
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  vi.stubGlobal('alert', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-284 文件导入失败后同一文件可重选', () => {
  it('无效 JSON 导入失败：输入重置为未选择；重选同一文件再次触发导入', async () => {
    const alertMock = vi.mocked(window.alert)
    const { container } = render(<FilterRulesSection />)
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!
    expect(input).not.toBeNull()
    const valueWrites = spyValueWrites(input)

    const bad = makeFile('{broken json')
    selectFile(input, bad)

    // 失败反馈（诚实报错），且 onChange 内已把输入重置为「未选择」
    await waitFor(() => expect(alertMock).toHaveBeenCalledWith(expect.stringContaining('导入失败')))
    expect(valueWrites()).toContain('')

    // 同一文件对象再次选择 → onChange 再次触发（重试路径畅通）
    selectFile(input, bad)
    await waitFor(() => expect(alertMock).toHaveBeenCalledTimes(2))
    expect(valueWrites().filter((v) => v === '').length).toBeGreaterThanOrEqual(2)
  })

  it('有效 JSON 导入成功：规则落库，输入同样重置', async () => {
    render(<FilterRulesSection />)
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!
    const valueWrites = spyValueWrites(input)
    const good = makeFile(
      JSON.stringify({
        schemaVersion: 1,
        rules: [{ id: 'r9', keyword: '推广', feedId: null, type: 'keyword', enabled: true }],
      }),
    )
    selectFile(input, good)
    expect(valueWrites()).toContain('')
    await waitFor(() => {
      const settings = useAppSettings.getState().settings
      expect(settings.filterRules.some((r) => r.keyword === '推广')).toBe(true)
    })
  })
})
