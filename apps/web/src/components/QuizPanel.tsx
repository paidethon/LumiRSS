/** QuizPanel — F069 文章阅读自测（阅读工具区，折叠面板）。
 *
 * 生成（3-5 题）→ 逐题单选 → 提交 → 结果列表（对/错 + 正确答案 +
 * 解析 + 证据引用）→「再来一次」重新生成 /「丢弃」关闭。
 * 生成响应只含题目（服务端契约：答案永不随生成出站）。 */

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ClipboardCheck } from 'lucide-react'
import { generateQuiz, gradeQuiz, type QuizGradeResult, type QuizSession } from '../api/client'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

export function QuizPanel({ entryRef }: { entryRef: string }) {
  const [open, setOpen] = useState(false)
  const [count, setCount] = useState(3)
  const [session, setSession] = useState<QuizSession | null>(null)
  const [choices, setChoices] = useState<Map<number, number>>(new Map())
  const [grade, setGrade] = useState<QuizGradeResult | null>(null)

  const generate = useMutation({
    mutationFn: () => generateQuiz(entryRef, count),
    onSuccess: (result) => {
      setSession(result)
      setGrade(null)
      setChoices(new Map())
    },
  })
  const submit = useMutation({
    mutationFn: (quizId: string) =>
      gradeQuiz(
        quizId,
        (session?.questions ?? []).map((q) => choices.get(q.index) ?? null),
      ),
    onSuccess: (result) => setGrade(result),
  })

  const reset = () => {
    setSession(null)
    setGrade(null)
    setChoices(new Map())
  }
  const discard = () => {
    reset()
    setOpen(false)
  }

  return (
    <section
      data-lumi-quiz-panel=""
      className="mt-4 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2"
    >
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="inline-flex items-center gap-1 text-xs font-medium text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          <ClipboardCheck aria-hidden className="size-3.5" />
          自测
        </button>
        {open && (
          <>
            {!session && (
              <label className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
                题数
                <select
                  aria-label="题目数量"
                  value={count}
                  onChange={(e) => setCount(Number(e.target.value))}
                  className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-1 text-xs"
                >
                  {[3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <Button
              size="sm"
              variant="primary"
              disabled={generate.isPending || submit.isPending}
              onClick={() => (session !== null && grade === null ? submit.mutate(session.quizId) : generate.mutate())}
            >
              {generate.isPending
                ? '生成中…'
                : session === null
                  ? '生成自测'
                  : grade === null
                    ? '提交答案'
                    : '再来一次'}
            </Button>
            {(session !== null || grade !== null) && (
              <Button size="sm" variant="ghost" onClick={discard}>
                丢弃
              </Button>
            )}
          </>
        )}
      </div>

      {open && (
        <div className="mt-2 flex flex-col gap-2">
          {generate.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              {generate.error instanceof Error ? generate.error.message : '生成失败，请稍后重试。'}
            </p>
          )}
          {submit.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              提交失败：自测会话可能已过期，请「再来一次」。
            </p>
          )}

          {session !== null &&
            session.questions.map((q) => {
              const graded = grade?.items.find((item) => item.index === q.index)
              return (
                <fieldset key={q.index} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
                  <legend className="px-1 text-xs font-medium text-[var(--lumi-text-primary)]">
                    {q.index + 1}. {q.question}
                  </legend>
                  <div className="flex flex-col gap-1">
                    {q.options.map((option, optionIndex) => {
                      const chosen = choices.get(q.index)
                      const showGrade = graded !== undefined && grade !== null
                      const isAnswer = graded !== undefined && graded.answerIndex === optionIndex
                      return (
                        <label
                          key={optionIndex}
                          className={cx(
                            'flex min-h-8 items-center gap-2 rounded-[var(--lumi-radius-md)] px-2 text-xs',
                            showGrade && isAnswer && 'bg-[var(--lumi-surface-selected)]',
                            showGrade && chosen === optionIndex && !isAnswer && 'text-[var(--lumi-danger)]',
                          )}
                        >
                          <input
                            type="radio"
                            name={`quiz-${q.index}`}
                            checked={chosen === optionIndex}
                            disabled={grade !== null}
                            onChange={() =>
                              setChoices((prev) => new Map(prev).set(q.index, optionIndex))
                            }
                          />
                          {option}
                          {showGrade && isAnswer && (
                            <span className="text-[11px] text-[var(--lumi-text-tertiary)]">正确答案</span>
                          )}
                          {showGrade && chosen === optionIndex && !isAnswer && (
                            <span className="text-[11px] text-[var(--lumi-danger)]">你的选择</span>
                          )}
                        </label>
                      )
                    })}
                  </div>
                  {graded !== undefined && (
                    <div className="mt-1.5 flex flex-col gap-0.5 text-xs">
                      <span className={graded.correct ? 'text-[var(--lumi-text-secondary)]' : 'text-[var(--lumi-danger)]'}>
                        {graded.correct ? '回答正确' : '回答错误'}
                      </span>
                      {graded.explanation !== '' && (
                        <span className="text-[var(--lumi-text-tertiary)]">解析：{graded.explanation}</span>
                      )}
                      {graded.evidenceQuote !== '' && (
                        <span className="text-[var(--lumi-text-tertiary)]">证据引用：“{graded.evidenceQuote}”（查看原文定位此句）</span>
                      )}
                    </div>
                  )}
                </fieldset>
              )
            })}
        </div>
      )}
    </section>
  )
}
