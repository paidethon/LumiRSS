/** 代码块复制按钮（pool #04）——对渲染后的正文 <pre> 做 DOM 装饰。
 *
 * 为什么不是 React 子组件：正文经 dangerouslySetInnerHTML 注入，管线
 * 输出是纯 HTML；装饰用 DOM API 在渲染后追加按钮（幂等：已有按钮的
 * <pre> 跳过）。复制内容取 <pre><code> 的 textContent（Shiki 输出无
 * 行号，天然无行号污染），剥离按钮自身文本与结尾换行。
 *
 * 反馈：成功「已复制 ✓」/ 失败「复制失败」，1.6s 后还原——失败可见，
 * 不假装成功。 */

export interface CodeCopyDeps {
  writeText?: (text: string) => Promise<void>
  /** 测试注入的定时器（默认 setTimeout）。 */
  scheduleRevert?: (fn: () => void, delayMs: number) => void
}

const REVERT_MS = 1600
const BUTTON_CLASS = 'code-copy-btn'

export function decorateCodeCopyButtons(
  container: HTMLElement,
  deps: CodeCopyDeps = {},
): void {
  const writeText =
    deps.writeText ??
    ((text: string) =>
      navigator.clipboard?.writeText(text) ?? Promise.reject(new Error('clipboard unavailable')))
  const scheduleRevert =
    deps.scheduleRevert ?? ((fn: () => void, delayMs: number) => setTimeout(fn, delayMs))

  for (const pre of container.querySelectorAll('pre')) {
    if (pre.querySelector(`.${BUTTON_CLASS}`) !== null) continue
    const code = pre.querySelector('code')
    const source = (code ?? pre).textContent ?? ''
    if (source.trim() === '') continue

    const button = container.ownerDocument.createElement('button')
    button.type = 'button'
    button.className = BUTTON_CLASS
    button.textContent = '复制'
    button.setAttribute('aria-label', '复制代码')
    button.addEventListener('click', () => {
      const text = ((code ?? pre).textContent ?? '').replace(/\n$/, '')
      writeText(text)
        .then(() => {
          button.textContent = '已复制 ✓'
        })
        .catch(() => {
          button.textContent = '复制失败'
        })
        .finally(() => {
          button.disabled = true
          scheduleRevert(() => {
            button.textContent = '复制'
            button.disabled = false
          }, REVERT_MS)
        })
    })
    pre.appendChild(button)
  }
}
