/** offline-translation-probe — N089 翻译离线能力检测（本设备真实探测）。
 *
 * 诚实设计（绝不伪造离线）：脚本无法拦截/伪造网络，所以探测从不假装
 * 断网。它只做三件真实的事并把结果按层标注：
 *
 * - (a) 系统框架  ：Chrome 内置 Translator API 是否存在 + 目标语言对
 *   在此浏览器是否受支持（既有 capability 探测，不触发下载）；
 * - (b) 浏览器模型：对固定短句做一次 REAL 的浏览器内置翻译推理；
 * - (c) 云端(需网络)：对已配置的 AI 端点做一次有界可达性探测（超时
 *   4s，一次性，不重试）。未配置端点 → 诚实「未配置」。
 *
 * 「离线可用」只在 (b) 真实推理成功 且 (c) 端点探测失败 时给出——
 * 即「云端不可达时本设备仍能翻译」的实际证据。检测范围是「此设备
 * 此刻」，不做任何跨设备推断。 */

import {
  createLocalTranslator,
  localTranslatorAvailable,
  localTranslatorPairStatus,
  LocalTranslatorActivationError,
  LocalTranslatorComponentError,
  LocalTranslatorLanguagePairError,
  LocalTranslatorUnsupportedError,
  type LocalTranslatorAvailability,
} from './local-translator'

/** 固定探测短句（短、真实、覆盖基础词序）。 */
export const OFFLINE_PROBE_SAMPLE = 'The quick brown fox jumps.'

const CLOUD_PROBE_TIMEOUT_MS = 4000

export interface OfflineProbeLayerResult {
  ok: boolean
  /** 面板直接展示的诚实说明。 */
  detail: string
  /** (b) 成功时的真实翻译输出（证据，非占位文案）。 */
  output?: string
}

/** 云端层：ok=null 表示未配置端点（诚实三态，而非真/假二值）。 */
export interface OfflineProbeCloudLayerResult {
  ok: boolean | null
  detail: string
}

export interface OfflineProbeResult {
  /** 系统框架 = Translator API 存在且语言对非 unsupported/unavailable。 */
  system: OfflineProbeLayerResult
  /** 浏览器模型 = 固定短句的真实内置翻译推理。 */
  browser: OfflineProbeLayerResult
  /** 云端(需网络) = ok: true 可达 / false 不可达 / null 未配置。 */
  cloud: OfflineProbeCloudLayerResult
  /** 离线可用 = 浏览器模型真实推理成功 且 云端端点探测失败。 */
  offlineAvailable: boolean
  navigatorOnline: boolean
}

export interface OfflineProbeOptions {
  sourceLanguage: string
  targetLanguage: string
  /** 已配置的云端 AI 端点（AI 设置的 baseUrl）；空 = 未配置。 */
  remoteEndpoint?: string | null
  fetchImpl?: typeof fetch
  sampleText?: string
}

function describeBrowserError(error: unknown): string {
  if (error instanceof LocalTranslatorUnsupportedError) {
    return '此浏览器不支持本地翻译（需要 Chrome 内置 Translator API）。'
  }
  if (error instanceof LocalTranslatorComponentError) {
    return '浏览器翻译组件未就绪（chrome://components 更新 TranslateKit）。'
  }
  if (error instanceof LocalTranslatorActivationError) {
    return '需要一次新的点击授权才能下载语言包，请再点一次重试。'
  }
  if (error instanceof LocalTranslatorLanguagePairError) {
    return '此浏览器不支持该语言对的本地翻译。'
  }
  return '浏览器内置翻译创建失败。'
}

async function probeCloudEndpoint(
  endpoint: string,
  fetchImpl: typeof fetch,
): Promise<OfflineProbeCloudLayerResult> {
  if (endpoint.trim() === '') {
    return { ok: null, detail: '未配置云端 AI 端点（无法探测云端可用性）。' }
  }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), CLOUD_PROBE_TIMEOUT_MS)
  try {
    await fetchImpl(endpoint, { method: 'HEAD', signal: controller.signal })
    return { ok: true, detail: '云端端点可达（翻译需联网）。' }
  } catch {
    return { ok: false, detail: '云端端点不可达（离线或地址有误）。' }
  } finally {
    clearTimeout(timer)
  }
}

/** 三层探测（见模块注释）。除语言对 capability 探测、一次固定短句的
 * 浏览器推理与一次云端 HEAD 外，不做任何其它网络请求。 */
export async function runOfflineTranslationProbe(
  options: OfflineProbeOptions,
): Promise<OfflineProbeResult> {
  const fetchImpl = options.fetchImpl ?? fetch
  const sample = options.sampleText ?? OFFLINE_PROBE_SAMPLE
  const navigatorOnline =
    typeof navigator !== 'undefined' ? navigator.onLine : true

  // (a) 系统框架：API 存在 + 语言对支持（既有探测；不触发下载）。
  const apiPresent = localTranslatorAvailable()
  let pairStatus: LocalTranslatorAvailability | null = null
  if (apiPresent) {
    pairStatus = await localTranslatorPairStatus(
      options.sourceLanguage,
      options.targetLanguage,
    )
  }
  const systemOk =
    apiPresent && pairStatus !== 'unsupported' && pairStatus !== 'unavailable'
  const system: OfflineProbeLayerResult = {
    ok: systemOk,
    detail: !apiPresent
      ? '此浏览器没有内置 Translator API。'
      : `语言对 ${options.sourceLanguage}→${options.targetLanguage} 状态：${pairStatus ?? '未知'}。`,
  }

  // (b) 浏览器模型：真实推理固定短句。
  let browser: OfflineProbeLayerResult = {
    ok: false,
    detail: '此浏览器没有内置 Translator API。',
  }
  if (apiPresent) {
    try {
      const translator = await createLocalTranslator(
        options.sourceLanguage,
        options.targetLanguage,
      )
      const output = await translator.translate(sample)
      translator.destroy()
      if (output.trim() !== '') {
        browser = {
          ok: true,
          detail: `实测翻译成功：「${output}」`,
          output,
        }
      } else {
        browser = { ok: false, detail: '浏览器返回了空翻译结果。' }
      }
    } catch (error) {
      browser = { ok: false, detail: describeBrowserError(error) }
    }
  }

  // (c) 云端(需网络)：一次有界可达性探测。
  const cloud = await probeCloudEndpoint(
    options.remoteEndpoint ?? '',
    fetchImpl,
  )

  const offlineAvailable =
    browser.ok && options.remoteEndpoint != null && options.remoteEndpoint !== '' && cloud.ok === false

  return { system, browser, cloud, offlineAvailable, navigatorOnline }
}
