/** NEW-251 研究问题拆分 — 父问题/子问题/结论草稿/材料挂接。
 *
 * 子问题结论是用户手写文本（服务端不做任何自动归纳）；open/resolved
 * 是显式 set 切换。材料用 ItemRef 只引用不复制。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  addResearchQuestion,
  addSubquestion,
  addSubquestionMaterial,
  listResearchQuestions,
  patchSubquestion,
} from '../../api/new251'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { ErrorLine, NoticeLine, StatusBadge, TextField } from './parts'

export function ResearchQuestionsPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [question, setQuestion] = useState('')
  const [subDrafts, setSubDrafts] = useState<Record<string, string>>({})
  const [refDrafts, setRefDrafts] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState<string | null>(null)

  const questions = useQuery({
    queryKey: ['new251-questions', projectId],
    queryFn: ({ signal }) => listResearchQuestions(projectId, signal),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['new251-questions', projectId] })

  const addQuestion = useMutation({
    mutationFn: () => addResearchQuestion(projectId, question),
    onSuccess: async () => {
      setQuestion('')
      setNotice('已登记父问题。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '登记失败'),
  })
  const addSub = useMutation({
    mutationFn: (args: { questionId: string; text: string }) => addSubquestion(args.questionId, args.text),
    onSuccess: async () => {
      setNotice('已拆出子问题。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '拆分失败'),
  })
  const patchSub = useMutation({
    mutationFn: (args: { id: string; patch: Parameters<typeof patchSubquestion>[1] }) =>
      patchSubquestion(args.id, args.patch),
    onSuccess: async () => {
      setNotice('子问题已更新。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '更新失败'),
  })
  const addRef = useMutation({
    mutationFn: (args: { subquestionId: string; itemRef: string }) =>
      addSubquestionMaterial(args.subquestionId, args.itemRef),
    onSuccess: async (result) => {
      setNotice(result.outcome === 'duplicate' ? '该材料已挂接过（幂等）。' : '材料已挂接。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '挂接失败'),
  })

  const items = questions.data?.items ?? []
  return (
    <div data-new251-questions="" className="flex flex-col gap-3">
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <TextField label="新父问题" value={question} onChange={setQuestion} placeholder="要正式拆解的阅读问题" />
        </div>
        <Button size="sm" onClick={() => addQuestion.mutate()} disabled={addQuestion.isPending}>
          登记问题
        </Button>
      </div>
      <NoticeLine notice={notice} />
      <ErrorLine error={questions.error} />
      {questions.isPending && <p className="text-xs text-[var(--lumi-text-tertiary)]">加载问题…</p>}
      {questions.data !== undefined && items.length === 0 && (
        <EmptyState title="尚无研究问题" description="先登记一个父问题，再拆成子问题逐个攻克。" />
      )}
      {items.map((item) => (
        <div key={item.id} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
          <p className="text-sm font-medium text-[var(--lumi-text-primary)]">{item.question}</p>
          <ul className="mt-2 flex flex-col gap-2">
            {item.subquestions.map((sub) => (
              <li key={sub.id} className="flex flex-col gap-1.5 border-t border-[var(--lumi-border)] pt-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm text-[var(--lumi-text-primary)]">{sub.text}</span>
                  <StatusBadge status={sub.status} />
                </div>
                {sub.conclusion !== null && (
                  <p className="text-xs text-[var(--lumi-text-secondary)]">结论草稿：{sub.conclusion}</p>
                )}
                <div className="flex flex-wrap items-end gap-2">
                  <div className="min-w-40 flex-1">
                    <TextField
                      label="子问题结论草稿"
                      value={subDrafts[sub.id] ?? ''}
                      onChange={(value) => setSubDrafts((prev) => ({ ...prev, [sub.id]: value }))}
                      placeholder="手写结论（可留空，随写随改）"
                    />
                  </div>
                  <div className="min-w-40 flex-1">
                    <TextField
                      label="挂接材料 ItemRef"
                      value={refDrafts[sub.id] ?? ''}
                      onChange={(value) => setRefDrafts((prev) => ({ ...prev, [sub.id]: value }))}
                      placeholder="rss:… / library:…"
                    />
                  </div>
                  <Button
                    size="sm"
                    onClick={() =>
                      patchSub.mutate({
                        id: sub.id,
                        patch: {
                          conclusion: subDrafts[sub.id] ?? sub.conclusion ?? '',
                          status: 'resolved',
                        },
                      })
                    }
                    disabled={patchSub.isPending}
                  >
                    记结论并标已解决
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      patchSub.mutate({ id: sub.id, patch: { status: 'open' } })
                    }
                    disabled={patchSub.isPending}
                  >
                    重新打开
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => addRef.mutate({ subquestionId: sub.id, itemRef: refDrafts[sub.id] ?? '' })}
                    disabled={addRef.isPending}
                  >
                    挂材料
                  </Button>
                </div>
              </li>
            ))}
          </ul>
          <div className="mt-2 flex items-end gap-2">
            <div className="flex-1">
              <TextField
                label={`拆分子问题（${item.question.slice(0, 10)}…）`}
                value={subDrafts[item.id] ?? ''}
                onChange={(value) => setSubDrafts((prev) => ({ ...prev, [item.id]: value }))}
                placeholder="这个大问题可以拆成…"
              />
            </div>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => addSub.mutate({ questionId: item.id, text: subDrafts[item.id] ?? '' })}
              disabled={addSub.isPending}
            >
              拆分子问题
            </Button>
          </div>
        </div>
      ))}
    </div>
  )
}
