/** N089 离线能力检测 + N088 模型存储管理 —— 本机翻译能力（探测 lib +
 * 设置 UI）。
 *
 * 覆盖：
 * - N089：mock Translator API 成功 → 浏览器模型层「可用」且给出真实
 *   翻译输出；API 缺失 → 诚实不可用；浏览器模型实测成功 + 云端端点
 *   探测失败 → 「离线可用」；探测除端点 HEAD 外零外发（固定短句的
 *   推理走浏览器内置，不发网络请求）；
 * - N088：能力网格逐语言对渲染（含「不支持」对）；存储诚实标注
 *   「浏览器托管，无法精确计量」；清除按钮——接口缺失 → 禁用 +
 *   「无清除接口」指引（诚实）；接口存在 → 真调用并如实回报。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  runOfflineTranslationProbe,
  OFFLINE_PROBE_SAMPLE,
} from '../lib/offline-translation-probe'
import {
  resetLocalTranslatorCache,
  deleteLocalTranslatorModels,
  translatorModelDeletionAvailable,
} from '../lib/local-translator'
import { LocalTranslationCapabilitySection } from '../components/settings/LocalTranslationCapabilitySection'

interface TranslatorCtorStub {
  availability: ReturnType<typeof vi.fn>
  create: ReturnType<typeof vi.fn>
  deleteAll?: ReturnType<typeof vi.fn>
}

function stubTranslatorApi(options: {
  availability?: string
  translateOutput?: string
  translateError?: Error
  deleteAll?: ReturnType<typeof vi.fn>
}): TranslatorCtorStub {
  const instance = {
    translate: options.translateError
      ? vi.fn().mockRejectedValue(options.translateError)
      : vi.fn().mockResolvedValue(options.translateOutput ?? '敏捷的棕色狐狸跳。'),
    destroy: vi.fn(),
  }
  const ctor: TranslatorCtorStub = {
    availability: vi.fn().mockResolvedValue(options.availability ?? 'available'),
    create: vi.fn().mockResolvedValue(instance),
  }
  if (options.deleteAll) ctor.deleteAll = options.deleteAll
  vi.stubGlobal('Translator', ctor)
  return ctor
}

beforeEach(() => {
  resetLocalTranslatorCache()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('N089 runOfflineTranslationProbe（探测 lib）', () => {
  it('mock Translator API 成功：浏览器模型层可用且带真实输出；系统框架层可用', async () => {
    stubTranslatorApi({ availability: 'available', translateOutput: '敏捷的棕色狐狸跳过了。' })
    const cloudFail = vi.fn().mockRejectedValue(new TypeError('offline'))
    const result = await runOfflineTranslationProbe({
      sourceLanguage: 'en',
      targetLanguage: 'zh',
      remoteEndpoint: 'http://ai.local/v1',
      fetchImpl: cloudFail as unknown as typeof fetch,
    })
    expect(result.system.ok).toBe(true)
    expect(result.browser.ok).toBe(true)
    expect(result.browser.output).toBe('敏捷的棕色狐狸跳过了。')
    expect(result.cloud.ok).toBe(false)
    // 离线可用 = 浏览器真实推理成功 且 云端探测失败
    expect(result.offlineAvailable).toBe(true)
    // 探测只发了一次端点请求（HEAD）；固定短句推理走浏览器内置（无网络）
    expect(cloudFail).toHaveBeenCalledTimes(1)
    expect(cloudFail.mock.calls[0]![0]).toBe('http://ai.local/v1')
  })

  it('API 缺失：系统框架与浏览器模型诚实不可用（不假装）', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
    const result = await runOfflineTranslationProbe({
      sourceLanguage: 'en',
      targetLanguage: 'zh',
      remoteEndpoint: 'http://ai.local/v1',
      fetchImpl: fetchMock as unknown as typeof fetch,
    })
    expect(result.system.ok).toBe(false)
    expect(result.browser.ok).toBe(false)
    expect(result.browser.detail).toContain('没有内置 Translator API')
    expect(result.offlineAvailable).toBe(false)
    // API 缺失时唯一外发是云端端点探测
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('云端可达（探测成功）→ 不给「离线可用」（没有离线证据）', async () => {
    stubTranslatorApi({ availability: 'available' })
    const cloudOk = vi.fn().mockResolvedValue(new Response(null, { status: 200 }))
    const result = await runOfflineTranslationProbe({
      sourceLanguage: 'en',
      targetLanguage: 'zh',
      remoteEndpoint: 'http://ai.local/v1',
      fetchImpl: cloudOk as unknown as typeof fetch,
    })
    expect(result.cloud.ok).toBe(true)
    expect(result.offlineAvailable).toBe(false)
  })

  it('语言对不支持 → 系统框架层诚实不可用；端点未配置 → 云端层 null', async () => {
    stubTranslatorApi({ availability: 'unavailable' })
    const result = await runOfflineTranslationProbe({
      sourceLanguage: 'en',
      targetLanguage: 'zh',
      remoteEndpoint: '',
      fetchImpl: vi.fn() as unknown as typeof fetch,
    })
    expect(result.system.ok).toBe(false)
    expect(result.cloud.ok).toBeNull()
    expect(result.offlineAvailable).toBe(false)
  })

  it('固定短句真实发给浏览器推理（样本非空、不经过 fetch）', async () => {
    const ctor = stubTranslatorApi({ availability: 'available', translateOutput: '译文' })
    await runOfflineTranslationProbe({
      sourceLanguage: 'en',
      targetLanguage: 'zh',
      remoteEndpoint: null,
      fetchImpl: vi.fn() as unknown as typeof fetch,
    })
    const instance = await (ctor.create.mock.results[0]!.value as Promise<{ translate: ReturnType<typeof vi.fn> }>)
    // LocalTranslator 适配层会追加 { signal } 选项——首参必须是固定短句
    expect(instance.translate).toHaveBeenCalledWith(OFFLINE_PROBE_SAMPLE, expect.anything())
  })
})

// ---- N088：删除接口的诚实性（lib 级） ----

describe('N088 本机模型删除（诚实）', () => {
  it('接口缺失：deletion 不可用，调用返回 false（不假装清除成功）', async () => {
    stubTranslatorApi({ availability: 'available' })
    expect(translatorModelDeletionAvailable()).toBe(false)
    await expect(deleteLocalTranslatorModels()).resolves.toBe(false)
  })

  it('接口存在：真实调用 deleteAll 并如实回报成功', async () => {
    const deleteAll = vi.fn().mockResolvedValue(undefined)
    stubTranslatorApi({ availability: 'available', deleteAll })
    expect(translatorModelDeletionAvailable()).toBe(true)
    await expect(deleteLocalTranslatorModels()).resolves.toBe(true)
    expect(deleteAll).toHaveBeenCalledTimes(1)
  })
})

// ---- 设置 UI：能力网格 + 检测按钮 ----

describe('N088/N089 设置 UI（本机翻译能力区）', () => {
  it('无 Translator API：网格渲染出「浏览器不支持」语言对；清除按钮禁用 + 无清除接口指引', async () => {
    const { container } = render(<LocalTranslationCapabilitySection remoteEndpoint="" />)
    fireEvent.click(screen.getByRole('button', { name: /检测语言对支持/ }))
    await waitFor(() => {
      expect(container.querySelector('[data-lumi-model-grid]')).not.toBeNull()
    })
    const grid = container.querySelector('[data-lumi-model-grid]')!
    expect(grid).toHaveTextContent('en → zh')
    expect(grid).toHaveTextContent('zh → en')
    expect(grid).toHaveTextContent('浏览器不支持')
    expect(screen.getByText(/浏览器托管，无法精确计量/)).toBeInTheDocument()
    const clear = screen.getByRole('button', { name: /清除本机翻译模型/ })
    expect(clear).toBeDisabled()
    expect(screen.getByText(/无清除接口/)).toBeInTheDocument()
  })

  it('接口存在：清除可点、真实调用并如实回报', async () => {
    const deleteAll = vi.fn().mockResolvedValue(undefined)
    stubTranslatorApi({ availability: 'available', deleteAll })
    render(<LocalTranslationCapabilitySection remoteEndpoint="" />)
    const clear = screen.getByRole('button', { name: /清除本机翻译模型/ })
    expect(clear).toBeEnabled()
    fireEvent.click(clear)
    await waitFor(() => {
      expect(deleteAll).toHaveBeenCalledTimes(1)
    })
    expect(await screen.findByText(/已请求浏览器清除/)).toBeInTheDocument()
  })

  it('离线能力检测（mock API 成功 + 云端不可达）→ 三层结果 + 离线可用徽标', async () => {
    stubTranslatorApi({ availability: 'available', translateOutput: '离线实测输出。' })
    const { container } = render(<LocalTranslationCapabilitySection remoteEndpoint="http://ai.local/v1" />)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('offline')),
    )
    fireEvent.click(screen.getByRole('button', { name: /离线能力检测/ }))
    await waitFor(() => {
      expect(container.querySelector('[data-lumi-offline-probe-result]')).not.toBeNull()
    })
    const result = container.querySelector('[data-lumi-offline-probe-result]')!
    expect(result).toHaveTextContent('系统框架')
    expect(result).toHaveTextContent('浏览器模型')
    expect(result).toHaveTextContent('云端（需网络）')
    expect(container.querySelector('[data-lumi-offline-available]')).not.toBeNull()
    expect(container.querySelector('[data-lumi-offline-available]')).toHaveTextContent('离线可用')
  })

  it('API 缺失时点检测：三层诚实展示（浏览器模型 不可用、无离线徽标）', async () => {
    const { container } = render(<LocalTranslationCapabilitySection remoteEndpoint="" />)
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    fireEvent.click(screen.getByRole('button', { name: /离线能力检测/ }))
    await waitFor(() => {
      expect(container.querySelector('[data-lumi-offline-probe-result]')).not.toBeNull()
    })
    const result = container.querySelector('[data-lumi-offline-probe-result]')!
    expect(result).toHaveTextContent('没有内置 Translator API')
    expect(container.querySelector('[data-lumi-offline-available]')).toBeNull()
  })
})
