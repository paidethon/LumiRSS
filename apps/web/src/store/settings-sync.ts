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
/** AUDIT-010：未解决的 dirty portable 键持久化于此，跨重载存活；
 * 这样一次失败的 PATCH 不会在下次 hydration 时被陈旧服务端值覆盖。 */
const DIRTY_KEYS_STORAGE_KEY = 'lumirss-settings-dirty'

let initialized = false
let debounceMs = DEFAULT_DEBOUNCE_MS
/** 本会话用户修改过且尚未确认落库的 portable 键（hydration 合并时跳过）。 */
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

/** AUDIT-010：从 localStorage 恢复未解决的 dirty 键（只保留合法 portable 键）。 */
function loadDirtyKeys(): Set<string> {
  if (typeof localStorage === 'undefined') return new Set()
  try {
    const raw = localStorage.getItem(DIRTY_KEYS_STORAGE_KEY)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return new Set()
    const allowed = PORTABLE_KEYS as readonly string[]
    return new Set(
      parsed.filter((k): k is string => typeof k === 'string' && allowed.includes(k)),
    )
  } catch {
    return new Set()
  }
}

/** 持久化当前 dirty 键（空则移除）——尽力而为，写失败不影响本会话。 */
function persistDirtyKeys(): void {
  if (typeof localStorage === 'undefined') return
  try {
    if (dirtyKeys.size === 0) localStorage.removeItem(DIRTY_KEYS_STORAGE_KEY)
    else localStorage.setItem(DIRTY_KEYS_STORAGE_KEY, JSON.stringify([...dirtyKeys]))
  } catch {
    /* 隐私模式 / 配额满：静默 */
  }
}

function scheduleFlush(): void {
  if (debounceTimer !== null) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    debounceTimer = null
    void flush()
  }, debounceMs)
}

/** 串行化的 PATCH：只发最新快照；in-flight 时挂起等待，完成后重发。
 * AUDIT-010：成功时清除本次发送的 dirty 键（已落库）；失败时保留，
 * 使其既不被 hydration 覆盖，又能在下次变更/联网/重载时重试。 */
async function flush(): Promise<void> {
  if (inFlight !== null) {
    queuedFlush = true
    return
  }
  const sending = new Set(dirtyKeys)
  const payload = portableSettings(useAppSettings.getState().settings)
  inFlight = sendPatch(payload)
    .then(() => {
      for (const key of sending) dirtyKeys.delete(key)
      persistDirtyKeys()
    })
    .catch(() => {
      /* 静默：网络/服务端失败不回滚 UI；dirty 键保留 → 后续重试 */
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
      // 首次访问：本地 portable 值作迁移种子 PUSH（幂等）。
      await sendPatch(portableSettings(useAppSettings.getState().settings))
      dirtyKeys.clear()
      persistDirtyKeys()
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
    // AUDIT-010：不清除未解决的 dirty 键。若仍有 dirty（例如上次会话
    // 失败的 PATCH 持久化下来），重试推送一次以达成落库（成功后
    // 由 flush 自行清除）；无 dirty 时不发多余请求。
    if (dirtyKeys.size > 0) void flush()
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

/** AUDIT-010：重新联网时重试未落库的变更（无轮询、无无限循环：
 * 仅当存在未解决 dirty 键时才发一次）。 */
function onOnline(): void {
  if (dirtyKeys.size > 0) void sendNow()
}

/** AUDIT-012：破坏性恢复成功后调用——丢弃未落库的本地 dirty 键与待
 * 发送变更，使随后的重载/hydration 完全采用恢复后的服务端设置，
 * 绝不用陈旧的本地值 PATCH 覆盖刚恢复的数据。 */
export function clearPendingSettingsSync(): void {
  if (debounceTimer !== null) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
  dirtyKeys = new Set()
  persistDirtyKeys()
  flushedFinal = false
}

/** 启动设置同步（main.tsx 调用一次；StrictMode 双调用安全）。 */
export function initSettingsSync(options: SettingsSyncOptions = {}): void {
  if (initialized) return
  initialized = true
  debounceMs = options.debounceMs ?? DEFAULT_DEBOUNCE_MS
  // AUDIT-010：先恢复上次会话未落库的 dirty 键，使本次 hydration
  // 不会用陈旧服务端值覆盖未解决的本地变更。
  dirtyKeys = loadDirtyKeys()

  unsubscribe = useAppSettings.subscribe((state, prev) => {
    if (applyingServerValues) return
    if (state.settings === prev.settings) return
    const keys = changedPortableKeys(prev.settings, state.settings)
    if (keys.length === 0) return
    flushedFinal = false
    for (const key of keys) dirtyKeys.add(key)
    persistDirtyKeys()
    scheduleFlush()
  })

  if (typeof window !== 'undefined') {
    window.addEventListener('pagehide', onPageHide)
    window.addEventListener('online', onOnline)
  }

  void hydrate()
}

/** 测试专用：重置模块状态（vitest 之间模块缓存需要）。 */
export function resetSettingsSyncForTests(): void {
  initialized = false
  debounceMs = DEFAULT_DEBOUNCE_MS
  dirtyKeys = new Set()
  persistDirtyKeys()
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
    window.removeEventListener('online', onOnline)
  }
}

/** 测试专用：立即冲刷 pending 变更（绕开 debounce）。 */
export function flushSettingsSyncForTests(): Promise<void> {
  return sendNow()
}
