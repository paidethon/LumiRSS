/** ReaderSplitOriginal — F077 正文/原网页分屏（≥1024px）。
 *
 * 左栏 = 既有正文滚动容器（Reader 结构不动），右栏 = 原网页 iframe：
 * - sandbox 严格：`sandbox=""`（空值 = 全部限制）——无脚本、无
 *   same-origin、无表单/弹窗；referrerPolicy no-referrer；
 * - url 只放行 safeExternalHttpUrl 校验过的 http/https 绝对地址；
 * - 原文不可得（url 非法/缺失）时诚实提示，不渲染 iframe；
 * - 仅桌面（≥1024px）提供：移动端由调用方（Reader）不渲染本组件。
 * 纯展示层：沙箱语义由浏览器执行，本组件不向 iframe 注入任何内容。 */

import { X } from 'lucide-react'
import { IconButton } from './ui/IconButton'

export interface ReaderSplitOriginalProps {
  /** 已通过 safeExternalHttpUrl 校验的原网页地址；null = 原文不可得。 */
  url: string | null
  onClose: () => void
}

export function ReaderSplitOriginal({ url, onClose }: ReaderSplitOriginalProps) {
  return (
    <aside
      data-lumi-split-pane=""
      className="hidden min-h-0 flex-col border-l border-[var(--lumi-border)] bg-[var(--lumi-canvas)] lg:flex lg:w-1/2"
      aria-label="原网页分屏"
    >
      <div className="flex items-center gap-2 border-b border-[var(--lumi-border)] px-3 py-1.5">
        <span className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-secondary)]">
          {url !== null ? '原网页（沙箱预览：无脚本、无站点凭据）' : '原文链接不可用'}
        </span>
        <IconButton
          size="sm"
          icon={<X aria-hidden className="size-4" />}
          label="关闭原文分屏"
          touch
          onClick={onClose}
        />
      </div>
      {url !== null ? (
        <iframe
          data-lumi-split-frame=""
          src={url}
          title="原网页"
          sandbox=""
          referrerPolicy="no-referrer"
          className="min-h-0 w-full flex-1 border-0 bg-white"
        />
      ) : (
        <div className="flex flex-1 items-center justify-center p-8">
          <p role="status" className="max-w-xs text-center text-sm text-[var(--lumi-text-secondary)]">
            这篇文章没有可用的原文链接，无法分屏展示原网页。
          </p>
        </div>
      )}
    </aside>
  )
}

export default ReaderSplitOriginal
