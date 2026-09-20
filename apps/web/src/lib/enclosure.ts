/** enclosure — 播放性判定（纯逻辑；bundle 拆分收口）。
 *
 * 自 components/EnclosurePlayer 抽出：Reader 只需要这一个谓词决定是否
 * 渲染播放器，原先整块播放器模块（lucide/ui 依赖）被它拖进首屏 chunk。
 * EnclosurePlayer 保留 re-export 兼容既有引用。 */

export interface EnclosureItem {
  href: string
  type?: string | null
}

/** 该 enclosure 是否可用播放器渲染（audio/* / video/*）。 */
export function isPlayableEnclosure(item: EnclosureItem): boolean {
  const kind = (item.type ?? '').toLowerCase()
  if (kind.startsWith('audio/') || kind.startsWith('video/')) return true
  // 无 type 时按扩展名保守判断
  const path = item.href.split('?')[0] ?? ''
  return /\.(mp3|m4a|aac|ogg|oga|opus|wav|mp4|m4v|webm)$/i.test(path)
}
