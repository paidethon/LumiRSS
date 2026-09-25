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
/** 当前活跃观察器（模块级持有：关闭/清理时统一断开——测试环境里
 * 泄漏的观察器会在后续文件的 React commit 期间被触发，跨文件污染）。 */
let activeObserver: MutationObserver | null = null

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

/** N182：文本级遮罩 —— 遮罩开启时，复制/导出等「离开屏幕面」的文本
 * 路径（剪贴板写入、Markdown/HTML 导出）先经此变换；遮罩关闭时原样
 * 返回（零成本直通）。与 DOM 遮罩同一替换语义：整段替换为 ▮，原文
 * 不进入剪贴板/导出文件（负向断言覆盖）。 */
export function maskPlainTextIfActive(text: string): string {
  if (!isPrivacyEnabled()) return text
  if (text === '') return text
  return maskText(text)
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

/** 元素鸭子判断：不用 instanceof HTMLElement——测试环境拆卸后该全局
 * 可能已不存在，instanceof 会抛 ReferenceError 并打断 React commit。 */
function isElementNode(node: Node): boolean {
  return node.nodeType === 1
}

/** 开启：挂根 class + 遮蔽现有 DOM；返回清理函数（MutationObserver）。
 * 观察器回调整体 try/catch——遮罩是纯展示增强，任何失败（含环境拆卸
 * 竞态）都绝不外溢。 */
export function enablePrivacyMask(): () => void {
  if (typeof document === 'undefined') return () => {}
  document.documentElement.classList.add(PRIVACY_CLASS)
  try {
    applyMask(document)
  } catch {
    /* 遮罩失败静默 */
  }
  activeObserver?.disconnect()
  const observer = new MutationObserver((mutations) => {
    try {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (isElementNode(node) && node instanceof Element) {
            const el = node as HTMLElement
            if (el.hasAttribute('data-privacy-text')) applySingle(el)
            applyMask(el)
          }
        }
        const target = mutation.target
        if (
          isElementNode(target) &&
          target instanceof Element &&
          target.hasAttribute('data-privacy-text') &&
          !originals.has(target)
        ) {
          applySingle(target as HTMLElement)
        }
      }
    } catch {
      /* 遮罩失败静默（绝不打断宿主渲染/commit） */
    }
  })
  observer.observe(document.body, { childList: true, subtree: true })
  activeObserver = observer
  return () => {
    observer.disconnect()
    if (activeObserver === observer) activeObserver = null
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

/** 关闭：恢复已遮蔽元素的原文（同一次会话内）；断开活跃观察器；刷新
 * 则天然恢复。 */
export function disablePrivacyMask(): void {
  if (typeof document === 'undefined') return
  document.documentElement.classList.remove(PRIVACY_CLASS)
  activeObserver?.disconnect()
  activeObserver = null
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
