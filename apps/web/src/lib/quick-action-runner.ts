/** quick-action-runner — N199 多步快捷操作执行器（纯逻辑核心）。
 *
 * 铁律：每一步都走该动作的**既有 NORMAL 端点/客户端函数**——本模块
 * 只做顺序编排，绝不绕过任何鉴权/确认路径：
 * - 步骤顺序执行；任一步失败 → 立即停止（stop-on-error），后续步骤
 *   不再执行（真的不调用，不是吞错误）；
 * - 标记为 write 的动作必须先经过 confirm 钩子（与手动的确认路径
 *   同一语义）；confirm 返回 false → 该步以 'cancelled' 结束并停。
 */

export type QuickActionExecutor = (params: Record<string, unknown>) => Promise<unknown>

export interface QuickActionStepDef {
  action: string
  params?: Record<string, unknown>
  /** write 步骤执行前必须 confirm（与该动作手动路径的确认语义一致）。 */
  write?: boolean
}

export interface QuickActionRunOptions {
  /** write 步骤的确认钩子（返回 false = 用户取消）。 */
  confirm?: (step: QuickActionStepDef, index: number) => Promise<boolean> | boolean
  /** 每步完成后的回调（UI 进度条/提示）。 */
  onStepDone?: (step: QuickActionStepDef, index: number) => void
}

export type QuickActionStepOutcome = 'ok' | 'cancelled'

export interface QuickActionRunResult {
  status: 'completed' | 'stopped' | 'cancelled'
  steps: { action: string; outcome: QuickActionStepOutcome }[]
  /** 失败的步骤（stopped 时指向首个失败步骤）。 */
  failedIndex: number | null
  error: unknown
}

/** 顺序执行一个动作定义：stop-on-error + write 必经 confirm。 */
export async function runQuickAction(
  steps: QuickActionStepDef[],
  executors: Record<string, QuickActionExecutor>,
  options: QuickActionRunOptions = {},
): Promise<QuickActionRunResult> {
  const done: { action: string; outcome: QuickActionStepOutcome }[] = []
  for (let index = 0; index < steps.length; index += 1) {
    const step = steps[index]
    if (step === undefined) break
    const executor = executors[step.action]
    if (executor === undefined) {
      return {
        status: 'stopped',
        steps: done,
        failedIndex: index,
        error: new Error(`未知动作：${step.action}`),
      }
    }
    if (step.write === true && options.confirm !== undefined) {
      const allowed = await options.confirm(step, index)
      if (!allowed) {
        return {
          status: 'cancelled',
          steps: [...done, { action: step.action, outcome: 'cancelled' as const }],
          failedIndex: index,
          error: null,
        }
      }
    }
    try {
      await executor(step.params ?? {})
      done.push({ action: step.action, outcome: 'ok' })
      options.onStepDone?.(step, index)
    } catch (error) {
      return { status: 'stopped', steps: done, failedIndex: index, error }
    }
  }
  return { status: 'completed', steps: done, failedIndex: null, error: null }
}
