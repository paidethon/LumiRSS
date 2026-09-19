/** reader-export — F22 导出 Markdown / HTML + Blob 下载。
 *
 * Markdown：标题 + 来源·日期 + 原文链接 + contentText 分段；
 * HTML：干净文档壳（title / meta charset / 来源 / 日期 / 链接）+
 * contentHtml 原文 transport。contentHtml 是**未消毒**的上游 HTML
 * （与浏览器同源信任级别由 DOMPurify 渲染边界承担）；导出文件至少
 * 剥掉 <script> 标签对（regex 级防御，不重写 sanitizer—— sanitizer
 * 仍只在渲染路径唯一存在）。 */

export interface ExportInput {
  title: string
  source: string
  /** 展示用日期（调用方已格式化）；空 = 未知。 */
  date: string
  /** 只放行 safeExternalHttpUrl 通过的地址；null = 省略链接行。 */
  url: string | null
  text: string
  html: string | null
}

/** 剥掉 <script>…</script> 标签对与未闭合的 <script …> 开标签。
 * 注意：这是导出 transport 的最低防御，不是 sanitizer。 */
export function stripScriptTags(html: string): string {
  return html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script\s*>/gi, '')
    .replace(/<script\b[^>]*\/?>/gi, '')
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** contentText 分段：空行分段；没有空行时整段保留（不强制断行）。 */
function splitParagraphs(text: string): string[] {
  return text
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter((p) => p !== '')
}

/** 纯构建：Markdown 导出内容（# 标题 + > 来源·日期 + 链接 + 分段正文）。 */
export function buildMarkdownExport(input: ExportInput): string {
  const lines: string[] = [`# ${input.title}`]
  const meta = [input.source, input.date].filter((v) => v !== '').join(' · ')
  if (meta !== '') lines.push('', `> ${meta}`)
  if (input.url !== null && input.url !== '') {
    lines.push('', `原文链接：${input.url}`)
  }
  for (const paragraph of splitParagraphs(input.text)) {
    lines.push('', paragraph)
  }
  return `${lines.join('\n')}\n`
}

/** 纯构建：独立 HTML 导出文档（语义 table/th/td、结构原样保留）。 */
export function buildHtmlExport(input: ExportInput): string {
  const meta: string[] = []
  if (input.source !== '') meta.push(escapeHtml(input.source))
  if (input.date !== '') meta.push(escapeHtml(input.date))
  const link =
    input.url !== null && input.url !== ''
      ? `\n    <p><a href="${escapeHtml(input.url)}">原文链接</a></p>`
      : ''
  const body = input.html !== null ? stripScriptTags(input.html) : ''
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>${escapeHtml(input.title)}</title>
</head>
<body>
    <article>
    <h1>${escapeHtml(input.title)}</h1>
    ${meta.length > 0 ? `<p class="lumi-export-meta">${meta.join(' · ')}</p>` : ''}${link}
    ${body}
    </article>
</body>
</html>
`
}

/** 文件名净化：去掉路径/非法字符与控制符，限长 80；空回退「文章」。 */
export function sanitizeFileName(name: string): string {
  const cleaned = name
    .replace(/[/\\:*?"<>|]/g, '')
    // eslint-disable-next-line no-control-regex
    .replace(/[\x00-\x1f]/g, '')
    .trim()
    .slice(0, 80)
  return cleaned !== '' ? cleaned : '文章'
}

export interface DownloadDeps {
  createUrl?: (blob: Blob) => string
  revokeUrl?: (url: string) => void
}

/** Blob 下载（a[download] + createObjectURL）；环境不支持（无
 * createObjectURL 等）返回 false——调用方诚实提示，不假装成功。 */
export function downloadTextFile(
  filename: string,
  content: string,
  mime: string,
  deps: DownloadDeps = {},
): boolean {
  try {
    const blob = new Blob([content], { type: `${mime};charset=utf-8` })
    const createUrl =
      deps.createUrl ??
      ((b: Blob) => {
        if (typeof URL.createObjectURL !== 'function') {
          throw new Error('URL.createObjectURL unavailable')
        }
        return URL.createObjectURL(b)
      })
    const revokeUrl = deps.revokeUrl ?? ((u: string) => URL.revokeObjectURL(u))
    const url = createUrl(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => revokeUrl(url), 1000)
    return true
  } catch {
    return false
  }
}

/** 导出 Markdown 并触发下载。 */
export function exportEntryAsMarkdown(input: ExportInput): boolean {
  return downloadTextFile(
    `${sanitizeFileName(input.title)}.md`,
    buildMarkdownExport(input),
    'text/markdown',
  )
}

/** 导出 HTML 并触发下载。 */
export function exportEntryAsHtml(input: ExportInput): boolean {
  return downloadTextFile(
    `${sanitizeFileName(input.title)}.html`,
    buildHtmlExport(input),
    'text/html',
  )
}
