/** Reader 背景偏好纯逻辑 — 0009 Gate 4。
 *
 * App Theme 与 Reader Theme 分离的持久化侧（AC14）：
 * - 偏好存 localStorage（lumirss-reader-bg：follow/sepia/warm）；
 * - 挂载点 = Reader 滚动容器（.bg-[var(--lumi-reader-bg)]），
 *   themes.css 的 [data-reader="sepia|warm"] 选择器消费。
 * follow = 不挂属性（--lumi-reader-bg 默认指向 --lumi-reader）。 */

export type ReaderBg = 'follow' | 'sepia' | 'warm'

export const READER_BG_STORAGE_KEY = 'lumirss-reader-bg'

export function isReaderBg(value: unknown): value is ReaderBg {
  return value === 'follow' || value === 'sepia' || value === 'warm'
}

export function readStoredReaderBg(): ReaderBg {
  try {
    const raw = localStorage.getItem(READER_BG_STORAGE_KEY)
    return isReaderBg(raw) ? raw : 'follow'
  } catch {
    return 'follow'
  }
}

/** 写偏好 + 立即应用到当前 Reader 容器（无容器时只持久化，
 * 下次 Reader 渲染由 initReaderBg 恢复）。 */
export function applyReaderBg(bg: ReaderBg): void {
  try {
    if (bg === 'follow') localStorage.removeItem(READER_BG_STORAGE_KEY)
    else localStorage.setItem(READER_BG_STORAGE_KEY, bg)
  } catch {
    /* 写失败不影响本会话 */
  }
  const el = document.querySelector('.bg-\\[var\\(--lumi-reader-bg\\)\\]')
  if (el) {
    if (bg === 'follow') el.removeAttribute('data-reader')
    else el.setAttribute('data-reader', bg)
  }
}

/** 启动路径：恢复持久化的 Reader 背景（main.tsx 调一次）。 */
export function initReaderBg(): void {
  const bg = readStoredReaderBg()
  if (bg !== 'follow') applyReaderBg(bg)
}
