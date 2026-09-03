/** settings-sync — local-first + server-durable portable 设置同步（0017）。
 *
 * 职责边界（AD-0017-2）：
 * - useAppSettings 是唯一客户端状态源；本模块只是耐久同步层，
 *   绝不阻塞 UI（slider 拖动永远即时生效）；
 * - 变更 → 600ms debounce → PATCH 最新快照（请求串行化，最新值必胜）；
 * - 启动 hydration：server 无文档（stored=false）→ 本地值作迁移种子
 *   PUSH；server 有文档 → server 值覆盖本地（本会话用户已改过的
 *   dirty key 除外，防止覆盖正在拖动的 slider）；
 * - 失败静默（不打扰用户、不回滚 UI）；下一次变更自然重试；
 *   pagehide 时用 keepalive 补发最终值（不丢最后一次调整）。 */

import {
  getServerSettings,
  patchServerSettings,
} from '../api/client'
import {
  portableSettings,
  PORTABLE_KEYS,
  useAppSettings,
  type AppSettings,
  type PortableValues,
} from './app-settings'

const DEFAULT_DEBOUNCE_MS = 600

let initialized = false
let debounceMs = DEFAULT_DEBOUNCE_MS
/** 本会话用户修改过的 portable 键（hydration 合并时跳过）。 */
let dirtyKeys = new Set<string>()
/** hydration 应用 server 值时置位，避免被 subscribe 误判为用户修改。 */
let applyingServerValues = false
let debounceTimer: ReturnType<typeof setTimeout> | null = null
let inFlight: Promise<void> | null = null
let queuedFlush = false
/** pagehide 后的最终补发（keepalive；不改变 serialization）。 */
let flushedFinal = false
/** store 订阅的退订句柄（测试重置用）。 */
let unsubscribe: (() => void) | null = null

export interface SettingsSyncOptions {
  /** 测试注入：debounce 时长（0 = 立即）。 */
  debounceMs?: number
}

function changedPortableKeys(prev: AppSettings, next: AppSettings): string[] {
  const keys: string[] = []
  for (const key of PORTABLE_KEYS) {
    if (prev[key] !== next[key]) keys.push(key)
  }
  return keys
}

function scheduleFlush(): void {
  if (debounceTimer !== null) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    debounceTimer = null
    void flush()
  }, debounceMs)
}

/** 串行化的 PATCH：只发最新快照；in-flight 时挂起等待，完成后重发。 */
async function flush(): Promise<void> {
  if (inFlight !== null) {
    queuedFlush = true
    return
  }
  const payload = portableSettings(useAppSettings.getState().settings)
  inFlight = sendPatch(payload)
    .catch(() => {
      /* 静默：网络/服务端失败不回滚 UI，下次变更重试 */
    })
    .finally(() => {
      inFlight = null
      if (queuedFlush) {
        queuedFlush = false
        void flush()
      }
    })
  await inFlight
}

function sendPatch(payload: PortableValues): Promise<void> {
  return patchServerSettings(payload).then(() => undefined)
}

async function sendNow(): Promise<void> {
  if (debounceTimer !== null) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
  await flush()
}

async function hydrate(): Promise<void> {
  try {
    const server = await getServerSettings()
    if (!server.stored) {
      // 首次访问：本地 portable 值作为迁移种子 PUSH（幂等）。
      await sendPatch(portableSettings(useAppSettings.getState().settings))
      dirtyKeys.clear()
      return
    }
    // server 有明确值 → server 优先；本会话已改过的 key 不覆盖。
    const patch: Record<string, unknown> = {}
    for (const key of PORTABLE_KEYS) {
      if (dirtyKeys.has(key)) continue
      if (key in server) patch[key] = server[key]
    }
    if (Object.keys(patch).length > 0) {
      applyingServerValues = true
      try {
        useAppSettings.getState().update(patch)
      } finally {
        applyingServerValues = false
      }
    }
    dirtyKeys.clear()
  } catch {
    /* 启动 hydration 失败静默：本地设置照常工作，下次启动重试 */
  }
}

function onPageHide(): void {
  if (flushedFinal || debounceTimer === null) return
  flushedFinal = true
  // keepalive 补发最终值：不 await，让浏览器在卸载时完成发送。
  const payload = JSON.stringify(portableSettings(useAppSettings.getState().settings))
  void fetch('/api/v1/settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: payload,
    keepalive: true,
  }).catch(() => {
    /* 尽力而为 */
  })
}

/** 启动设置同步（main.tsx 调用一次；StrictMode 双调用安全）。 */
export function initSettingsSync(options: SettingsSyncOptions = {}): void {
  if (initialized) return
  initialized = true
  debounceMs = options.debounceMs ?? DEFAULT_DEBOUNCE_MS

  unsubscribe = useAppSettings.subscribe((state, prev) => {
    if (applyingServerValues) return
    if (state.settings === prev.settings) return
    const keys = changedPortableKeys(prev.settings, state.settings)
    if (keys.length === 0) return
    flushedFinal = false
    for (const key of keys) dirtyKeys.add(key)
    scheduleFlush()
  })

  if (typeof window !== 'undefined') {
    window.addEventListener('pagehide', onPageHide)
  }

  void hydrate()
}

/** 测试专用：重置模块状态（vitest 之间模块缓存需要）。 */
export function resetSettingsSyncForTests(): void {
  initialized = false
  debounceMs = DEFAULT_DEBOUNCE_MS
  dirtyKeys = new Set()
  applyingServerValues = false
  if (debounceTimer !== null) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
  inFlight = null
  queuedFlush = false
  flushedFinal = false
  if (unsubscribe !== null) {
    unsubscribe()
    unsubscribe = null
  }
  if (typeof window !== 'undefined') {
    window.removeEventListener('pagehide', onPageHide)
  }
}

/** 测试专用：立即冲刷 pending 变更（绕开 debounce）。 */
export function flushSettingsSyncForTests(): Promise<void> {
  return sendNow()
}
