/** NEW-288 跨期主题追踪 — 主题锚点 + 跨期链（期次位置 + 后续更新链）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { createTopic, fetchTopicChain, listTopics } from '../../api/new281'
import {
  NoteText,
  StatusLine,
  TextField,
  buttonClass,
  errorText,
} from './parts'

export function TopicsPanel() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [openTopicId, setOpenTopicId] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const topics = useQuery({
    queryKey: ['new281-topics'],
    queryFn: ({ signal }) => listTopics(signal),
  })

  const chain = useQuery({
    queryKey: ['new281-topic-chain', openTopicId],
    enabled: Boolean(openTopicId),
    queryFn: ({ signal }) => fetchTopicChain(openTopicId, signal),
  })

  const createMutation = useMutation({
    mutationFn: () => createTopic(name.trim()),
    onSuccess: async (topic) => {
      setNotice(
        topic.created
          ? `主题「${topic.name}」已创建。`
          : `主题「${topic.name}」已存在（同建同取）。`,
      )
      setName('')
      setOpenTopicId(topic.id)
      await queryClient.invalidateQueries({ queryKey: ['new281-topics'] })
    },
    onError: (error) => setNotice(errorText(error)),
  })

  return (
    <div className="flex flex-col gap-3">
      <NoteText>
        在期次编辑里把条目挂到主题（此处建主题、看链）。链上顺序 = 期次确认时间 → 期次内位置；越靠后越是后续更新。
        只含你显式挂载的条目，系统绝不自动归类。
      </NoteText>
      <div className="flex items-end gap-2">
        <TextField label="主题名" value={name} onChange={setName} placeholder="例如：数据中心用水" />
        <button type="button" className={buttonClass} disabled={createMutation.isPending} onClick={() => createMutation.mutate()}>
          创建 / 打开主题
        </button>
      </div>
      {notice && <StatusLine tone={createMutation.isError ? 'error' : 'ok'}>{notice}</StatusLine>}
      {topics.isError && <StatusLine tone="error">{errorText(topics.error)}</StatusLine>}
      {topics.data && topics.data.count === 0 && <NoteText>还没有主题。</NoteText>}
      <ul className="flex flex-col gap-1" data-new281-topics="">
        {topics.data?.topics.map((topic) => (
          <li key={topic.id}>
            <button
              type="button"
              aria-expanded={openTopicId === topic.id}
              className="text-sm text-[var(--lumi-accent)] underline underline-offset-2"
              onClick={() => setOpenTopicId((v) => (v === topic.id ? '' : topic.id))}
            >
              {topic.name}（{topic.entryCount} 条）
            </button>
          </li>
        ))}
      </ul>
      {openTopicId && chain.isLoading && <StatusLine tone="info">加载主题链…</StatusLine>}
      {chain.isError && <StatusLine tone="error">{errorText(chain.error)}</StatusLine>}
      {chain.data && (
        <ol className="flex flex-col gap-2" data-new281-topic-chain="">
          {chain.data.entries.map((entry, index) => (
            <li
              key={entry.itemId}
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]"
            >
              <span className="text-xs text-[var(--lumi-text-tertiary)]">#{index + 1}</span> {entry.title}
              <span className="ml-1 text-xs text-[var(--lumi-text-tertiary)]">
                · 「{entry.issueTitle}」{entry.issueStatus === 'confirmed' ? '已确认' : '草稿'} · 期次内第 {entry.position + 1} 条
              </span>
              {entry.url && (
                <a
                  href={entry.url}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="ml-1 text-xs text-[var(--lumi-accent)] underline underline-offset-2"
                >
                  原文
                </a>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
