/** P16 导出到 Obsidian —— 交接执行与诚实文案（纯逻辑，可测）。
 *
 * 服务端已裁决 handoff 结果：
 * - mode='uri'  → window.location 跳官方 obsidian://new 链接。文案必须是
 *   「已打开 Obsidian（请在 Obsidian 确认保存）」—— Lumi 没写 Vault
 *   （ADR 0004），写入只发生在用户于 Obsidian 中确认保存时；严禁任何
 *   「已写入」字样。
 * - mode='file' → 内容超出 URI 预算（reason='tooLong'）→ 下载 .md +
 *   复制剪贴板双通道；文案如实说明走了哪条路。
 * 复制失败时返回内容让调用方诚实降级（只读文本框），不假装已复制。
 * 两条路径都会同时把内容放入剪贴板（尽力而为）：即使 Obsidian 打开
 * 失败，用户也能手动粘贴。 */

import { downloadTextFile } from './reader-export'

export interface HandoffResultLike {
  mode: 'uri' | 'file'
  uri: string | null
  reason: string | null
  filename: string
  content: string
  unknownVars?: string[]
  deviceLabel?: string
}

export interface HandoffDeps {
  /** 默认 window.location 赋值；测试注入观察。返回 false 模拟不可用。 */
  openUri?: (uri: string) => boolean
  /** 默认 navigator.clipboard.writeText；拒绝/失败返回 false。 */
  copyText?: (text: string) => Promise<boolean>
  /** 默认 downloadTextFile（lib/reader-export）。 */
  download?: (filename: string, content: string, mime: string) => boolean
}

export interface HandoffOutcome {
  kind: 'uri-opened' | 'file-fallback' | 'clipboard-only' | 'error'
  /** 直接展示给用户的诚实状态文案（绝不含「已写入」）。 */
  message: string
  /** 复制失败时携带完整内容，调用方以只读文本框诚实降级。 */
  fallbackContent: string | null
}

export const URI_OPENED_MESSAGE = '已打开 Obsidian（请在 Obsidian 确认保存）。内容同时已复制到剪贴板备用。'
export const URI_OPEN_FAILED_MESSAGE = '无法自动打开 Obsidian（链接可能被浏览器拦截）。内容已复制到剪贴板，请在 Obsidian 新建笔记后粘贴保存。'
export const FILE_FALLBACK_MESSAGE = '内容超过 URI 长度上限，已下载 .md 文件并复制到剪贴板——请在 Obsidian 中粘贴或打开该文件后保存。'
export const FILE_DOWNLOAD_FAILED_MESSAGE = '内容超过 URI 长度上限，且下载失败。内容已复制到剪贴板，请手动粘贴到 Obsidian 保存。'
export const COPY_FAILED_MESSAGE = '复制到剪贴板失败，请手动复制下方内容。'

async function tryCopy(deps: HandoffDeps, text: string): Promise<boolean> {
  if (deps.copyText) return deps.copyText(text)
  try {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) return false
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

/** 执行一次交接，返回诚实结果。从不抛错（失败也是 outcome）。 */
export async function runObsidianHandoff(
  result: HandoffResultLike,
  deps: HandoffDeps = {},
): Promise<HandoffOutcome> {
  // 模板里的未知变量不阻塞交接，但必须如实告知（不静默）。
  const unknownNote =
    result.unknownVars && result.unknownVars.length > 0
      ? `（注意：模板含未支持变量 ${result.unknownVars.map((v) => `{{${v}}}`).join('、')}，已按空值渲染）`
      : ''

  if (result.mode === 'uri' && result.uri) {
    let opened = true
    try {
      if (deps.openUri) {
        opened = deps.openUri(result.uri)
      } else if (typeof window !== 'undefined') {
        window.location.href = result.uri
      }
    } catch {
      opened = false
    }
    const copied = await tryCopy(deps, result.content)
    if (!opened) {
      return {
        kind: copied ? 'clipboard-only' : 'error',
        message: `${URI_OPEN_FAILED_MESSAGE}${unknownNote}`,
        fallbackContent: copied ? null : result.content,
      }
    }
    return {
      kind: 'uri-opened',
      message: `${URI_OPENED_MESSAGE}${unknownNote}`,
      fallbackContent: copied ? null : result.content,
    }
  }

  // file 回退：下载 + 剪贴板（which path used 必须如实说明）。
  const copied = await tryCopy(deps, result.content)
  const downloaded =
    deps.download !== undefined
      ? deps.download(result.filename, result.content, 'text/markdown')
      : downloadTextFile(result.filename, result.content, 'text/markdown')
  if (downloaded) {
    return {
      kind: 'file-fallback',
      message: `${FILE_FALLBACK_MESSAGE}${unknownNote}`,
      fallbackContent: copied ? null : result.content,
    }
  }
  return {
    kind: copied ? 'clipboard-only' : 'error',
    message: `${FILE_DOWNLOAD_FAILED_MESSAGE}${unknownNote}`,
    fallbackContent: copied ? null : result.content,
  }
}
