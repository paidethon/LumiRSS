/** MoveSubscriptionDialog — 0013 Gate 3：移动订阅到分类。
 *
 * 两条真实路径（FreshRSS control plane，Gate 1 已验证）：
 * - 移动到已有分类：PATCH { categoryId }（服务端 404 预检已存在）；
 * - 新建分类并移入：PATCH { newCategoryLabel }——FreshRSS 的
 *   subscription/edit 会自动创建 a= 目标分类，这是唯一被采用的
 *   create-category 通道；重名/保留名由 BFF 写前预检（409）。
 *
 * 边界：单分类模型（移动即改归属，不存在多分类）；当前分类不可重复
 * 选择；不做拖拽排序/分类删除。mutation 只 server-confirmed →
 * invalidate（无 optimistic updates）。a11y：Escape 关闭、焦点 trap、
 * label 关联、isPending 双击防重。 */

import { useEffect, useState } from 'react'
import { AlertCircle, FolderInput, Loader2 } from 'lucide-react'
import { useCategories, useMoveSubscriptionMutation } from '../api/queries'
import type { Subscription } from '../api/types'
import { managementErrorText } from '../lib/management-errors'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { Select } from './ui/Select'
import { Skeleton } from './ui/Skeleton'

/** Select 里「新建分类」的特殊值（不会与真实 categoryId 冲突：
 * 真实 id 形如 user/-/label/<名>）。 */
const NEW_CATEGORY_VALUE = '__new_category__'

export default function MoveSubscriptionDialog({
  open,
  onClose,
  subscription,
}: {
  open: boolean
  onClose: () => void
  /** 目标订阅（由菜单打开时传入；null 时不应渲染内容） */
  subscription: Subscription | null
}) {
  const [target, setTarget] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const mutation = useMoveSubscriptionMutation()
  const categories = useCategories(open)

  // 打开时重置本地状态（上一次会话不留残留）
  useEffect(() => {
    if (open) {
      setTarget('')
      setNewLabel('')
      mutation.reset()
    }
    // reset 是稳定引用；依赖只看 open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const busy = mutation.isPending

  function close() {
    if (busy) return // mutation 进行中不允许误关
    onClose()
  }

  function submit() {
    if (!subscription || busy) return
    const label = newLabel.trim()
    if (target === NEW_CATEGORY_VALUE) {
      if (!label) return
      mutation.mutate(
        { subscriptionRef: subscription.subscriptionRef, target: { newCategoryLabel: label } },
        { onSuccess: onClose },
      )
    } else {
      if (!target || target === subscription.category?.id) return
      mutation.mutate(
        { subscriptionRef: subscription.subscriptionRef, target: { categoryId: target } },
        { onSuccess: onClose },
      )
    }
  }

  const errorText = mutation.isError ? managementErrorText(mutation.error) : null

  return (
    <Dialog
      open={open}
      onClose={close}
      title="移动到分类"
      footer={
        <>
          <Button variant="ghost" onClick={close} disabled={busy}>
            取消
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={
              busy ||
              !subscription ||
              (target === NEW_CATEGORY_VALUE
                ? newLabel.trim() === ''
                : target === '' || target === subscription?.category?.id)
            }
          >
            {busy ? (
              <>
                <Loader2 aria-hidden className="size-4 animate-spin" />
                移动中…
              </>
            ) : (
              '移动'
            )}
          </Button>
        </>
      }
    >
      {subscription !== null && (
        <div className="flex flex-col gap-4">
          {/* 目标订阅：明确显示 feed 名（操作对象） */}
          <div className="flex items-center gap-2.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
            <span
              aria-hidden
              className="flex size-8 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] text-[var(--lumi-accent-text)]"
            >
              <FolderInput className="size-4" />
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-[var(--lumi-text-primary)]">
                {subscription.title}
              </span>
              <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]">
                {subscription.category !== null ? `当前分类：${subscription.category.label}` : '当前未分组'}
              </span>
            </span>
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="move-subscription-category"
              className="text-sm font-medium text-[var(--lumi-text-primary)]"
            >
              目标分类
            </label>
            {categories.isPending ? (
              <Skeleton className="h-11 w-full" aria-label="分类加载中" />
            ) : categories.isError ? (
              <div className="flex items-center justify-between gap-2 text-sm text-[var(--lumi-text-secondary)]">
                <span>分类加载失败。</span>
                <Button size="sm" onClick={() => categories.refetch()}>
                  重试
                </Button>
              </div>
            ) : (
              <Select
                id="move-subscription-category"
                className="min-h-11 w-full"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                options={[
                  { value: '', label: '选择分类' },
                  ...(categories.data ?? [])
                    .filter((c) => c.id !== subscription.category?.id)
                    .map((c) => ({ value: c.id, label: c.label })),
                  { value: NEW_CATEGORY_VALUE, label: '＋ 新建分类…' },
                ]}
              />
            )}
          </div>

          {/* 新建分类：输入名字（由移动本身创建） */}
          {target === NEW_CATEGORY_VALUE && (
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="move-subscription-new-label"
                className="text-sm font-medium text-[var(--lumi-text-primary)]"
              >
                新分类名
              </label>
              <input
                id="move-subscription-new-label"
                type="text"
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                maxLength={128}
                placeholder="例如：技术"
                className="min-h-11 w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5 text-sm text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]"
              />
              <p className="text-xs text-[var(--lumi-text-tertiary)]">
                将创建该分类并把「{subscription.title}」移入。
              </p>
            </div>
          )}

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
        </div>
      )}
    </Dialog>
  )
}
