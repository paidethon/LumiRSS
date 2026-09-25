/** playback-diagnostics — N100 播放故障自助诊断（附件播放器 + 朗读引擎
 * 共用的故障分型）。
 *
 * 四类故障，各有不同的诊断文案与匹配处置（绝不无限重试）：
 * - network      网络失败   → 允许一次手动重试（有界）；
 * - decode       解码失败   → 有备选音源则切换，否则诚实死路；
 * - missing      音源缺失   → 来源/设置指引（重试无意义）；
 * - unauthorized 未授权     → 重新登录指引（凭据问题，不是网络问题）；
 * - unknown      未分类     → 诚实说明未知（不假装知道原因）。
 *
 * 设计约束：分型是纯函数；网络探测（附件源可达性）只发一次请求、
 * 只对同源地址探测（跨源会被 CORS 干扰，诚实地不做并退回错误码
 * 分型），超时即放弃——整条链路没有任何自动重试循环。 */

export type PlaybackFailureClass =
  | 'network'
  | 'decode'
  | 'missing'
  | 'unauthorized'
  | 'unknown'

export interface PlaybackFailure {
  cls: PlaybackFailureClass
  /** 诊断主文案（面向面板直接展示）。 */
  message: string
  /** 匹配的处置建议。 */
  hint: string
}

export function describePlaybackFailure(
  cls: PlaybackFailureClass,
  override?: { message?: string; hint?: string },
): PlaybackFailure {
  const base: Record<PlaybackFailureClass, { message: string; hint: string }> = {
    network: {
      message: '网络失败：无法下载音频数据。',
      hint: '请检查网络后重试。',
    },
    decode: {
      message: '解码失败：音频数据无法在此浏览器播放（格式可能不受支持）。',
      hint: '可尝试其它音源；没有备选时该附件无法播放。',
    },
    missing: {
      message: '音源缺失：附件地址为空或已失效。',
      hint: '请检查订阅来源的附件设置，或稍后等文章更新。',
    },
    unauthorized: {
      message: '未授权：音源要求登录（401/403）。',
      hint: '登录状态可能已过期，请重新登录后再试。',
    },
    unknown: {
      message: '播放失败：原因未分类。',
      hint: '请稍后重试；持续失败请检查附件地址与网络。',
    },
  }
  return {
    cls,
    message: override?.message ?? base[cls]!.message,
    hint: override?.hint ?? base[cls]!.hint,
  }
}

// ---- 朗读引擎（speechSynthesis）错误分型 ----

/** W3C SpeechSynthesisErrorCode → 故障类。voiceCount 为错误发生时的
 * 系统语音数量：0 个语音时任何错误都按「音源缺失」解释（最常见真因，
 * 诚实优先于含糊）。 */
export function classifySpeechError(
  errorCode: string | null | undefined,
  voiceCount: number,
): PlaybackFailure {
  if (voiceCount === 0) {
    return describePlaybackFailure('missing', {
      message: '音源缺失：此系统没有任何可用的朗读语音。',
      hint: '请在系统设置安装语音（或更换设备）；Lumi 侧无需配置。',
    })
  }
  switch (errorCode) {
    case 'network':
      return describePlaybackFailure('network', {
        message: '网络失败：朗读语音数据需要联网获取。',
        hint: '请检查网络后重试。',
      })
    case 'not-allowed':
      return describePlaybackFailure('unauthorized', {
        message: '未授权：浏览器阻止了语音合成。',
        hint: '请在浏览器站点设置中允许声音后重试。',
      })
    case 'voice-unavailable':
    case 'language-unavailable':
      return describePlaybackFailure('missing', {
        message: '音源缺失：所选语言在系统中没有可用语音。',
        hint: '请在系统设置安装对应语言语音，或在朗读面板换一个声音。',
      })
    case 'synthesis-failed':
    case 'synthesis-unavailable':
    case 'audio-busy':
    case 'audio-hardware':
      return describePlaybackFailure('decode', {
        message: '解码失败：语音合成引擎未能生成或播放音频。',
        hint: '请重试；持续失败可能是系统语音引擎故障。',
      })
    default:
      return describePlaybackFailure('unknown', {
        message: '朗读失败：语音引擎报错但原因未分类。',
        hint: '请重试；持续失败请换一个声音再试。',
      })
  }
}

// ---- 附件播放（HTMLMediaElement）错误分型 ----

/** HTMLMediaElement.error.code → 故障类。
 * 1 MEDIA_ERR_ABORTED（取回被中止）按网络失败处置（重试有意义）；
 * 2 MEDIA_ERR_NETWORK → 网络失败；
 * 3 MEDIA_ERR_DECODE → 解码失败；
 * 4 MEDIA_ERR_SRC_NOT_SUPPORTED → 解码失败（源可达但格式解不动）；
 * 空 src / 404 类由调用方按音源缺失处理。 */
export function classifyMediaErrorCode(
  code: number | null | undefined,
): PlaybackFailure {
  switch (code) {
    case 1:
    case 2:
      return describePlaybackFailure('network')
    case 3:
    case 4:
      return describePlaybackFailure('decode')
    default:
      return describePlaybackFailure('unknown')
  }
}

function sameOrigin(url: string): boolean {
  try {
    return new URL(url, window.location.href).origin === window.location.origin
  } catch {
    return false
  }
}

/** 附件源可达性探测（media error 之后的一次性分类辅助）：
 * - 仅同源地址探测（跨源请求会被 CORS 干扰，结果不可信——诚实跳过，
 *   返回 null 让调用方退回错误码分型）；
 * - HEAD 一次、超时即放弃（默认 5s）；绝不重试；
 * - 401/403 → unauthorized；404 → missing；2xx → decode（源可达但
 *   media 元素解不动）；其它状态 → unknown；
 * - 网络层抛错 → network。 */
export async function probePlaybackSource(
  url: string,
  fetchImpl: typeof fetch = fetch,
  timeoutMs = 5000,
): Promise<PlaybackFailureClass | null> {
  if (typeof window !== 'undefined' && !sameOrigin(url)) return null
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetchImpl(url, {
      method: 'HEAD',
      signal: controller.signal,
    })
    if (response.status === 401 || response.status === 403) return 'unauthorized'
    if (response.status === 404) return 'missing'
    if (response.ok) return 'decode'
    return 'unknown'
  } catch {
    return 'network'
  } finally {
    clearTimeout(timer)
  }
}
