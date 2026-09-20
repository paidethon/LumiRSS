/** F069 UI — 自测面板：生成（题目渲染绝无答案）→ 单选 → 提交评分
 * （对/错 + 正确答案 + 解析 + 证据引用）→ 再来一次重新生成。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QuizPanel } from '../components/QuizPanel'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const SESSION = {
  quizId: 'quiz-1',
  entryRef: 'e1.a',
  questions: [
    { index: 0, question: '核心主题？', options: ['自测', '烹饪', '旅行', '音乐'] },
    { index: 1, question: '文体接近？', options: ['说明文', '菜谱', '游记', '乐评'] },
  ],
}

const GRADE = {
  quizId: 'quiz-1',
  items: [
    {
      index: 0,
      chosen: 0,
      correct: true,
      answerIndex: 0,
      explanation: '全文围绕自测展开。',
      evidenceQuote: '自测用的长正文。自测用的长正文。',
    },
    {
      index: 1,
      chosen: 3,
      correct: false,
      answerIndex: 0,
      explanation: '这是说明文。',
      evidenceQuote: '证据句子原样出现',
    },
  ],
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <QuizPanel entryRef="e1.a" />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F069 自测面板', () => {
  it('F069: 生成→题目渲染无答案→作答提交→评分渲染对/错+解析+证据', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/quiz')) {
          return Promise.resolve(jsonResponse(SESSION))
        }
        if (url.includes('/grade')) {
          return Promise.resolve(jsonResponse(GRADE))
        }
        return Promise.resolve(jsonResponse({}))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: '自测' }))
    fireEvent.click(screen.getByRole('button', { name: '生成自测' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/entries/e1.a/quiz',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    expect(await screen.findByText(/核心主题/)).toBeInTheDocument()
    expect(screen.getByText(/文体接近/)).toBeInTheDocument()
    // 负向：生成阶段不出现任何答案/解析/证据内容
    expect(screen.queryByText(/全文围绕自测展开/)).toBeNull()
    expect(screen.queryByText(/自测用的长正文/)).toBeNull()

    // 作答：第 1 题选 0（对），第 2 题选 3（错）
    fireEvent.click(screen.getAllByRole('radio')[0])
    fireEvent.click(screen.getByRole('radio', { name: '乐评' }))
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/quiz/quiz-1/grade',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    expect(await screen.findByText('回答正确')).toBeInTheDocument()
    expect(screen.getByText('回答错误')).toBeInTheDocument()
    expect(screen.getByText('解析：这是说明文。')).toBeInTheDocument()
    expect(screen.getAllByText(/证据引用：/).length).toBe(2)
    expect(screen.getAllByText(/查看原文定位此句/).length).toBe(2)
    const body = JSON.parse(
      (fetchMock.mock.calls.find((c) => String(c[0]).includes('/grade'))?.[1] as RequestInit).body as string,
    )
    expect(body.answers).toEqual([0, 3])
  })

  it('F069: 再来一次重新生成（旧结果清除）；会话过期 404 诚实提示', async () => {
    let expired = false
    const fetchMock = vi
      .fn()
      .mockImplementation((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/quiz')) {
          return Promise.resolve(jsonResponse(SESSION))
        }
        if (url.includes('/grade')) {
          return expired
            ? Promise.resolve(
                jsonResponse(
                  { error: { type: 'quiz_not_found', message: '自测会话不存在或已过期。' } },
                  404,
                ),
              )
            : Promise.resolve(jsonResponse(GRADE))
        }
        return Promise.resolve(jsonResponse({}))
      })
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()

    fireEvent.click(screen.getByRole('button', { name: '自测' }))
    fireEvent.click(screen.getByRole('button', { name: '生成自测' }))
    await screen.findByText(/核心主题/)
    fireEvent.click(screen.getAllByRole('radio')[0])
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    expect(await screen.findByText('回答正确')).toBeInTheDocument()

    // 再来一次 → 清空结果重新生成（quiz 端点第二次调用）
    fireEvent.click(screen.getByRole('button', { name: '再来一次' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter((c) => String(c[0]).endsWith('/quiz')).length).toBe(2)
    })
    expect(await screen.findByText(/核心主题/)).toBeInTheDocument()
    expect(screen.queryByText('回答正确')).toBeNull()

    // 会话过期 → 提交 404 诚实提示（不假装评分成功）
    expired = true
    fireEvent.click(screen.getAllByRole('radio')[0])
    fireEvent.click(screen.getByRole('button', { name: '提交答案' }))
    expect(await screen.findByText(/自测会话可能已过期/)).toBeInTheDocument()
    expect(screen.queryByText('回答正确')).toBeNull()
  })
})
