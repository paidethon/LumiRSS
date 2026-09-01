/** RenameCategoryDialog — 0013 Gate 3：重命名分类。
 *
 * 真实路径：PATCH /api/v1/categories/{categoryId}（Gate 1，含
 * no-op probe / 重名预检 / 写后回读三重防护）。
 *
 * 诚实边界：默认分类（FreshRSS 管理）不可重命名——前端不硬编码猜测
 * 哪个是默认分类（身份判定不依赖 UI 本地化字符串），交给服务端
 * 409 default_category_immutable 的稳定错误映射来诚实提示。
 * 分类删除 / 多分类不在本 Gate 范围。 */

import { useEffect, useState } from 'react'
import { AlertCircle, Loader2 } from 'lucide-react'
import { useRenameCategoryMutation } from '../api/queries'
import { managementErrorText } from '../lib/management-errors'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'

export default function RenameCategoryDialog({
  open,
  onClose,
  category,
}: {
  open: boolean
  onClose: () => void
  /** 目标分类（由菜单打开时传入；null 时不应渲染内容） */
  category: { id: string; label: string } | null
}) {
  const [label, setLabel] = useState('')
  const mutation = useRenameCategoryMutation()

  // 打开时以当前分类名预填（就地编辑语义）；重置上次的 mutation 状态
  useEffect(() => {
    if (open) {
      setLabel(category?.label ?? '')
      mutation.reset()
    }
    // reset 是稳定引用；依赖只看 open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const busy = mutation.isPending
  const trimmed = label.trim()

  function close() {
    if (busy) return // mutation 进行中不允许误关
    onClose()
  }

  function submit() {
    if (!category || busy) return
    if (!trimmed || trimmed === category.label) return
    mutation.mutate(
      { categoryId: category.id, label: trimmed },
      { onSuccess: onClose },
    )
  }

  const errorText = mutation.isError ? managementErrorText(mutation.error) : null

  return (
    <Dialog
      open={open}
      onClose={close}
      title="重命名分类"
      footer={
        <>
          <Button variant="ghost" onClick={close} disabled={busy}>
            取消
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={busy || !category || trimmed === '' || trimmed === category?.label}
          >
            {busy ? (
              <>
                <Loader2 aria-hidden className="size-4 animate-spin" />
                保存中…
              </>
            ) : (
              '保存'
            )}
          </Button>
        </>
      }
    >
      {category !== null && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
          className="flex flex-col gap-4"
        >
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="rename-category-label"
              className="text-sm font-medium text-[var(--lumi-text-primary)]"
            >
              分类名
            </label>
            <input
              id="rename-category-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              maxLength={128}
              autoFocus
              className="min-h-11 w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5 text-sm text-[var(--lumi-text-primary)] focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]"
            />
          </div>

          {errorText !== null && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]"
            >
              <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
              <span className="min-w-0">
                <span className="block font-medium">{errorText.title}</span>
                {errorText.detail !== null && (
                  <span className="mt-0.5 block text-xs opacity-80">{errorText.detail}</span>
                )}
              </span>
            </div>
          )}
        </form>
      )}
    </Dialog>
  )
}
