/** ReadingPreviewPane — 阅读设置实时预览（P14）。
 *
 * 完整设置 → 阅读 分类的 side-by-side 预览：
 * - 桌面（SettingsModal）：右栏固定宽度 aside（list flex 收缩）；
 * - 移动（MobileSettingsScreen 子页）：顶部「折叠预览」可折叠块。
 *
 * 真实性契约：样例文章复用真实 Reader 的结构类（.lumi-reader +
 * .article-content），内联变量与 applyReaderTypography 同源
 * （readerTypographyVars 共享映射）——字号/行高/段距/缩进/两端对齐/
 * 字体族/背景调色板与真实正文走同一组 CSS 规则；标点悬挂与图片模式
 * 经 html data 属性全局生效，样例天然继承。背景图片/遮罩由
 * .lumi-reader-bg-image 分层类消费全局变量，预览与 Reader 一致。
 *
 * 数据源 = settings store（useAppSettings 订阅）：任何控件改动立即
 * 重渲染预览（store.update 已同步应用副作用，预览只是同一事实源的
 * 另一个消费者，不存在第二份状态）。 */

import { useState } from 'react'
import { useAppSettings, readerTypographyVars } from '../../../store/app-settings'
import { cx } from '../../ui/cx'

/** 短样例文章：覆盖真实正文的典型结构（标题/段落/列表/引用/代码/表格），
 * 类名与 ArticleContent 渲染产物一致（.article-content 直系子代规则、
 * 首行缩进 > p 选择器均可如实预览）。 */
export function ReaderSampleArticle({ className }: { className?: string }) {
  const settings = useAppSettings((s) => s.settings)
  // 与 applyReaderTypography 同源映射：内联在样例根上，预览自包含
  //（即便 html 级变量缺失也如实反映当前设置）。
  const vars = readerTypographyVars(settings) as React.CSSProperties
  return (
    <div className={cx('lumi-reader', className)} style={vars}>
      <div className="article-content" data-reading-preview-article="">
        <h2>示例标题：深空里的信标</h2>
        <p>
          这是一段用于实时预览的示例正文——字号、行高、段距与两端对齐都会
          在这里如实呈现。调整右侧控件时，本预览即时更新。
        </p>
        <h3>小节标题</h3>
        <p>另一个段落，用于观察段距与首行缩进的实际效果。</p>
        {/* N055/N056：列表与引用样例（列表缩进/引用缩进开关）+ 中英混排
            标点样例（避头尾开关：行首标点、行末前括号的断行观察点）。 */}
        <ul>
          <li>列表项一：检查项目符号与行距</li>
          <li>
            列表项二：开启「列表缩进」后，列表项首行与段落一样缩进两字符
          </li>
        </ul>
        <blockquote>
          引用块：检查左边框、缩进与弱化文字颜色；开启「引用缩进」后首行
          随段落缩进。
        </blockquote>
        <p>
          中英混排样例 Mixed Text：示例 3.14 倍、「引号」与（全角括号），
          English words、numbers 42 与中文混排——检查避头尾（行首不落
          句号/逗号/后引号）与标点悬挂是否各自独立生效。
        </p>
        <pre>
          <code>{'const reader = { preview: true }'}</code>
        </pre>
        <table>
          <tbody>
            <tr>
              <td>表格</td>
              <td>检查边框与内边距</td>
            </tr>
            <tr>
              <td>示例</td>
              <td>第二行</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** 预览面板（桌面右栏内容 / 移动折叠块内容共用）。 */
export function ReadingPreviewPane({ className }: { className?: string }) {
  return (
    <section aria-label="实时预览" data-reading-preview="" className={className}>
      <p className="text-xs font-medium uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
        实时预览
      </p>
      <div className="lumi-reader-bg-image mt-2 max-h-[70vh] overflow-y-auto rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-reader-bg)] p-4">
        <ReaderSampleArticle />
      </div>
      <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
        预览与真实正文使用同一组样式规则与背景（含背景图片与遮罩）。
      </p>
    </section>
  )
}

/** 移动端折叠预览块（默认收起；展开后与桌面同一预览内容）。 */
export function MobileReadingPreview() {
  const [open, setOpen] = useState(false)
  return (
    <div className="py-2" data-mobile-reading-preview="">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-11 w-full items-center justify-between rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-2 text-sm text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      >
        {open ? '折叠预览' : '展开预览'}
        <span
          aria-hidden
          className={cx(
            'text-[var(--lumi-text-tertiary)] transition-transform duration-[var(--lumi-motion-fast)]',
            open && 'rotate-180',
          )}
        >
          ▾
        </span>
      </button>
      {open && <ReadingPreviewPane className="mt-2" />}
    </div>
  )
}
