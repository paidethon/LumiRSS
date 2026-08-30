/** BackupSettingsPage — 备份与恢复（0010a F5，AC26/AC27）。
 * OrigRead 配置备份语义复刻（inspired）：
 * - 导出：JSON 信封（schemaVersion/appName/createdAt + 全部设置）下载；
 * - 可选加密：勾选含 API Key → 强制 ≥6 位密码 → Web Crypto
 *   PBKDF2(100k) + AES-256-GCM（密文/盐/IV base64 内嵌信封）；
 * - 导入：inspect 摘要预览 → validate-before-mutate → 合并恢复；
 * - 无密钥备份恢复时不清空本机已存 Key（OrigRead 同语义）。
 * OPML：planned·0012（数据在 FreshRSS 侧）。 */

import { useRef, useState } from 'react'
import { Download, Upload } from 'lucide-react'
import { normalizeSettings, useAppSettings, type AppSettings } from '../../store/app-settings'
import { Button } from '../ui/Button'

const BACKUP_SCHEMA_VERSION = 1

/** 导出信封（不加密时明文；加密时 secrets 密文内嵌）。 */
interface BackupEnvelope {
  schemaVersion: number
  appName: 'LumiRSS'
  createdAt: string
  settings: Omit<AppSettings, 'translationSettings'> & {
    translationSettings?: AppSettings['translationSettings']
  }
  encryptedSecrets?: {
    kdf: 'PBKDF2-SHA256'
    cipher: 'AES-256-GCM'
    iterations: number
    saltBase64: string
    ivBase64: string
    ciphertextBase64: string
  }
}

// ---- Web Crypto（AC27；与 OrigRead 同方案：PBKDF2 + AES-GCM） ----

async function deriveKey(password: string, salt: Uint8Array, iterations: number): Promise<CryptoKey> {
  const baseKey = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveKey'])
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: salt as unknown as BufferSource, iterations, hash: 'SHA-256' },
    baseKey,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  )
}

function b64encode(buf: ArrayBuffer | Uint8Array): string {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf)
  return btoa(String.fromCharCode(...bytes))
}

function b64decode(s: string): Uint8Array {
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0))
}

async function encryptSecrets(payload: string, password: string) {
  const salt = crypto.getRandomValues(new Uint8Array(16))
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const key = await deriveKey(password, salt, 100_000)
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: iv as unknown as BufferSource },
    key,
    new TextEncoder().encode(payload),
  )
  return {
    kdf: 'PBKDF2-SHA256' as const,
    cipher: 'AES-256-GCM' as const,
    iterations: 100_000,
    saltBase64: b64encode(salt),
    ivBase64: b64encode(iv),
    ciphertextBase64: b64encode(ciphertext),
  }
}

async function decryptSecrets(env: NonNullable<BackupEnvelope['encryptedSecrets']>, password: string): Promise<string> {
  const key = await deriveKey(password, b64decode(env.saltBase64), env.iterations)
  const plain = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: b64decode(env.ivBase64) as unknown as BufferSource },
    key,
    b64decode(env.ciphertextBase64) as unknown as BufferSource,
  )
  return new TextDecoder().decode(plain)
}

/** 导出时剥离 API Key（明文部分），密文另行携带。 */
function stripSecrets(settings: AppSettings): BackupEnvelope['settings'] {
  const translation = structuredClone(settings.translationSettings)
  for (const p of translation.providers) p.apiKey = ''
  return { ...settings, translationSettings: translation }
}

export function BackupSettingsSection() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)

  const [includeSecrets, setIncludeSecrets] = useState(false)
  const [password, setPassword] = useState('')
  const [pwError, setPwError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // 导入状态机：idle → inspect（摘要预览）→ done/error
  const [inspect, setInspect] = useState<{ file: File; summary: string; env: BackupEnvelope } | null>(null)
  const [importPassword, setImportPassword] = useState('')
  const [importError, setImportError] = useState<string | null>(null)
  const [importResult, setImportResult] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const hasAnyKey = settings.translationSettings.providers.some((p) => p.apiKey.length > 0)

  // ---- 导出 ----
  const doExport = async () => {
    setPwError(null)
    if (includeSecrets && password.length < 6) {
      setPwError('包含 API Key 时必须设置至少 6 位密码')
      return
    }
    setBusy(true)
    try {
      const env: BackupEnvelope = {
        schemaVersion: BACKUP_SCHEMA_VERSION,
        appName: 'LumiRSS',
        createdAt: new Date().toISOString(),
        settings: stripSecrets(settings),
      }
      if (includeSecrets && hasAnyKey) {
        const secrets = JSON.stringify({
          translationApiKeys: Object.fromEntries(
            settings.translationSettings.providers.filter((p) => p.apiKey).map((p) => [p.type, p.apiKey]),
          ),
        })
        env.encryptedSecrets = await encryptSecrets(secrets, password)
      }
      const blob = new Blob([JSON.stringify(env, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `LumiRSS-config-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setBusy(false)
    }
  }

  // ---- 导入：inspect（只读摘要，validate 信封） ----
  const inspectFile = async (file: File) => {
    setImportError(null)
    setImportResult(null)
    setImportPassword('')
    try {
      const env = JSON.parse(await file.text()) as BackupEnvelope
      // validate-before-mutate：信封校验在任何写入之前
      if (env.schemaVersion !== BACKUP_SCHEMA_VERSION || env.appName !== 'LumiRSS' || !env.settings) {
        throw new Error('envelope')
      }
      const parts = [
        `创建时间 ${new Date(env.createdAt).toLocaleString()}`,
        `设置 ${Object.keys(env.settings).length} 项`,
        `过滤规则 ${env.settings.filterRules?.length ?? 0} 条`,
        `阅读预设 ${env.settings.readerPresets?.length ?? 0} 套`,
        env.encryptedSecrets ? '含加密机密（恢复时需密码）' : '不含机密',
      ]
      setInspect({ file, env, summary: parts.join(' · ') })
    } catch {
      setImportError('导入失败：文件不是有效的 LumiRSS 配置备份')
    }
  }

  // ---- 导入：确认恢复（先全部校验再写入） ----
  const doRestore = async () => {
    if (!inspect) return
    setImportError(null)
    setBusy(true)
    try {
      const env = inspect.env
      let restoredSecrets = false

      // 解密机密（有密文时必须成功才继续；密码错 → 报错不写入）
      let apiKeyPatch: Record<string, string> | null = null
      if (env.encryptedSecrets) {
        if (importPassword.length < 6) {
          throw new Error('此备份包含加密机密，请输入导出时设置的密码')
        }
        const secrets = JSON.parse(await decryptSecrets(env.encryptedSecrets, importPassword)) as {
          translationApiKeys?: Record<string, string>
        }
        apiKeyPatch = secrets.translationApiKeys ?? null
        restoredSecrets = apiKeyPatch !== null && Object.keys(apiKeyPatch).length > 0
      }

      // normalize 全量校验（非法值回退默认——validate 通过才写入）
      const restored = normalizeSettings({ ...env.settings })
      // 机密恢复：仅当备份确实携带且解密成功才替换本机 Key（OrigRead 语义：
      // 无密钥备份不清空本机凭据）
      if (apiKeyPatch) {
        for (const p of restored.translationSettings.providers) {
          const key = apiKeyPatch[p.type]
          if (key) p.apiKey = key
        }
      } else {
        // 无密文：备份里被 strip 掉的 Key 不得覆盖本机已存的 Key
        const current = useAppSettings.getState().settings.translationSettings.providers
        for (const p of restored.translationSettings.providers) {
          const existing = current.find((c) => c.type === p.type)
          if (existing?.apiKey) p.apiKey = existing.apiKey
        }
      }
      // 部分字段保留本机状态：布局宽度/折叠（设备相关，OrigRead 同思路）
      const merged = normalizeSettings({
        ...restored,
        sidebarWidth: settings.sidebarWidth,
        sidebarCollapsed: settings.sidebarCollapsed,
        timelineWidth: settings.timelineWidth,
        timelineCollapsed: settings.timelineCollapsed,
      })
      update(merged)
      setInspect(null)
      setImportResult(
        `恢复完成：${restored.filterRules.length} 条过滤规则、${restored.readerPresets.length} 套自定义预设` +
          (restoredSecrets ? '、翻译 API Key 已恢复' : ''),
      )
    } catch (e) {
      setImportError(e instanceof Error ? e.message : '恢复失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      {/* 导出 */}
      <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
        <p className="text-sm font-medium text-[var(--lumi-text-primary)]">导出配置备份</p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          包含全部本地设置、过滤规则与阅读预设（JSON，可跨设备迁移）。默认不含
          API Key。
        </p>
        <label className="mt-3 flex items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
          <input
            type="checkbox"
            checked={includeSecrets}
            onChange={(e) => {
              setIncludeSecrets(e.target.checked)
              setPwError(null)
            }}
            className="size-4 accent-[var(--lumi-accent)]"
          />
          包含 API Key（加密导出{hasAnyKey ? '' : '——当前未存储任何 Key'}）
        </label>
        {includeSecrets && (
          <div className="mt-2">
            <input
              type="password"
              value={password}
              aria-label="备份加密密码"
              onChange={(e) => {
                setPassword(e.target.value)
                setPwError(null)
              }}
              placeholder="至少 6 位密码（不保存，恢复时需再次输入）"
              className="w-64 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 text-sm text-[var(--lumi-text-primary)]"
            />
          </div>
        )}
        {pwError && <p className="mt-1.5 text-xs text-[var(--lumi-danger)]">{pwError}</p>}
        <div className="mt-3">
          <Button size="sm" onClick={doExport} disabled={busy}>
            <Download aria-hidden className="size-3.5" />
            导出备份
          </Button>
        </div>
      </div>

      {/* 导入 */}
      <div className="mt-4 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
        <p className="text-sm font-medium text-[var(--lumi-text-primary)]">恢复配置</p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          选择备份文件 → 预览摘要 → 确认恢复。恢复不删除任何本机数据
          （合并语义）；未携带机密的备份不影响本机已存的 API Key。
        </p>
        <div className="mt-3">
          <Button size="sm" variant="secondary" onClick={() => fileRef.current?.click()}>
            <Upload aria-hidden className="size-3.5" />
            选择备份文件
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json"
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void inspectFile(f)
              e.target.value = ''
            }}
          />
        </div>

        {/* inspect 摘要预览（写入前） */}
        {inspect && (
          <div className="mt-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-accent)] p-3">
            <p className="text-xs leading-relaxed text-[var(--lumi-text-primary)]">
              {inspect.file.name}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
              {inspect.summary}
            </p>
            {inspect.env.encryptedSecrets && (
              <input
                type="password"
                value={importPassword}
                aria-label="恢复解密密码"
                onChange={(e) => {
                  setImportPassword(e.target.value)
                  setImportError(null)
                }}
                placeholder="解密密码（≥6 位）"
                className="mt-2 w-64 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 text-sm text-[var(--lumi-text-primary)]"
              />
            )}
            <div className="mt-2.5 flex gap-2">
              <Button size="sm" onClick={doRestore} disabled={busy}>
                确认恢复
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setInspect(null)}>
                取消
              </Button>
            </div>
          </div>
        )}

        {importError && <p className="mt-2 text-xs text-[var(--lumi-danger)]">{importError}</p>}
        {importResult && (
          <p className="mt-2 text-xs text-[var(--lumi-text-secondary)]">{importResult}</p>
        )}
      </div>

      {/* OPML：planned·0012 */}
      <div className="mt-4 flex items-center gap-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-[var(--lumi-text-primary)]">订阅列表（OPML）</p>
          <p className="mt-0.5 text-xs text-[var(--lumi-text-secondary)]">
            订阅数据存于 FreshRSS，OPML 导入导出经 BFF 控制平面（0012）。
          </p>
        </div>
        <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
          planned · 0012
        </span>
      </div>
    </div>
  )
}
