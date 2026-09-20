/** privacy-mask — F113 演示隐私遮罩（device-local）。
 *
 * 开启后根元素挂 class `lumi-privacy-on`，数据驱动组件对
 * `[data-privacy-text]` 元素做真实文本替换（▮）并清空 aria-label——
 * 不是 CSS 模糊：DOM 中不残留原文（负向断言覆盖）。
 *
 * 生命周期：开启 → 应用遮罩；关闭/刷新 → 重挂载即恢复原渲染
 * （替换只作用于当前 DOM，不写入任何持久状态）。工具提示与搜索建议
 * 使用同一 `data-privacy-text` 属性即被一并遮蔽。 */

export const PRIVACY_CLASS = 'lumi-privacy-on'
const MASK_CHAR = '▮'
/** key → 原文（关闭时恢复；刷新即丢弃）。 */
const originals = new Map<Element, { text: string; ariaLabel: string | null }>()

export function isPrivacyEnabled(): boolean {
  if (typeof localStorage === 'undefined') return false
  try {
    return localStorage.getItem('lumirss-privacy-demo') === '1'
  } catch {
    return false
  }
}

function maskText(text: string): string {
  return MASK_CHAR.repeat(Math.max(1, Math.min([...text].length, 24)))
}

function applyMask(root: ParentNode): void {
  const nodes = root.querySelectorAll<HTMLElement>('[data-privacy-text]')
  for (const node of nodes) {
    if (!originals.has(node)) {
      originals.set(node, {
        text: node.textContent ?? '',
        ariaLabel: node.getAttribute('aria-label'),
      })
      node.textContent = maskText(node.textContent ?? '')
      node.setAttribute('aria-label', '')
      node.removeAttribute('aria-label')
    }
  }
}

/** 开启：挂根 class + 遮蔽现有 DOM；返回清理函数（MutationObserver）。 */
export function enablePrivacyMask(): () => void {
  if (typeof document === 'undefined') return () => {}
  document.documentElement.classList.add(PRIVACY_CLASS)
  applyMask(document)
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node instanceof HTMLElement) {
          if (node.hasAttribute('data-privacy-text')) applySingle(node)
          applyMask(node)
        }
      }
      if (
        mutation.target instanceof HTMLElement &&
        mutation.target.hasAttribute('data-privacy-text') &&
        !originals.has(mutation.target)
      ) {
        applySingle(mutation.target)
      }
    }
  })
  observer.observe(document.body, { childList: true, subtree: true })
  return () => {
    observer.disconnect()
  }
}

function applySingle(node: HTMLElement): void {
  originals.set(node, {
    text: node.textContent ?? '',
    ariaLabel: node.getAttribute('aria-label'),
  })
  node.textContent = maskText(node.textContent ?? '')
  node.removeAttribute('aria-label')
}

/** 关闭：恢复已遮蔽元素的原文（同一次会话内）；刷新则天然恢复。 */
export function disablePrivacyMask(): void {
  if (typeof document === 'undefined') return
  document.documentElement.classList.remove(PRIVACY_CLASS)
  for (const [node, original] of originals) {
    node.textContent = original.text
    if (original.ariaLabel !== null) node.setAttribute('aria-label', original.ariaLabel)
  }
  originals.clear()
}

/** 全局开关（App 挂载点调用；返回清理函数供卸载/测试）。 */
export function setPrivacyMask(on: boolean): () => void {
  try {
    if (typeof localStorage !== 'undefined') {
      if (on) localStorage.setItem('lumirss-privacy-demo', '1')
      else localStorage.removeItem('lumirss-privacy-demo')
    }
  } catch {
    /* 隐私模式：静默 */
  }
  if (on) return enablePrivacyMask()
  disablePrivacyMask()
  return () => {}
}

/** F113：刷新即重置——App 模块加载（早于任何组件首渲染）时清掉上次
 * 会话残留的开启标记；DOM 已随页面重挂载，无需恢复原文。 */
export function resetPrivacyOnBoot(): void {
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem('lumirss-privacy-demo')
    }
  } catch {
    /* 隐私模式：静默 */
  }
}
