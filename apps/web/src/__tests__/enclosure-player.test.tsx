/** F011 enclosure 播放器 —— 显式开始（无 autoplay）、倍速、失败态重试、
 * 续播位置记录（有界 50 条）。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import {
  EnclosurePlayer,
  ENCLOSURE_POSITIONS_KEY,
  ENCLOSURE_POSITIONS_LIMIT,
  isPlayableEnclosure,
  readEnclosurePositions,
  recordEnclosurePosition,
} from '../components/EnclosurePlayer'

const AUDIO = { href: 'https://audio.example/ep12.mp3', type: 'audio/mpeg' }

function renderPlayer(storage: Storage | null = localStorage) {
  return render(
    <EnclosurePlayer enclosure={AUDIO} entryRef="e1.a" storage={storage} />,
  )
}

beforeEach(() => {
  localStorage.clear()
})

describe('F011 EnclosurePlayer', () => {
  it('F011: 未点击前不渲染 media 元素（无 autoplay；显式点击才开始）', () => {
    renderPlayer()
    expect(screen.getByTestId('enclosure-player')).toBeInTheDocument()
    expect(screen.queryByTestId('enclosure-media')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /播放附件/ }))
    const media = screen.getByTestId('enclosure-media') as HTMLMediaElement
    expect(media.tagName).toBe('AUDIO')
    expect(media.getAttribute('autoplay')).toBeNull()
    expect(media.autoplay).toBe(false)
  })

  it('F011: video 附件渲染 video 元素；倍速切换设置 playbackRate', () => {
    render(
      <EnclosurePlayer
        enclosure={{ href: 'https://v.example/x.mp4', type: 'video/mp4' }}
        entryRef="e1.v"
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /播放附件/ }))
    expect((screen.getByTestId('enclosure-media') as HTMLMediaElement).tagName).toBe('VIDEO')
    fireEvent.click(screen.getByRole('button', { name: '1.5x' }))
    expect(screen.getByRole('button', { name: '1.5x' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('F011: 加载失败 → 错误态 + 重试恢复播放器', () => {
    renderPlayer()
    fireEvent.click(screen.getByRole('button', { name: /播放附件/ }))
    const media = screen.getByTestId('enclosure-media')
    fireEvent.error(media)
    expect(screen.getByText(/附件加载失败/)).toBeInTheDocument()
    expect(screen.queryByTestId('enclosure-media')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /重试/ }))
    expect(screen.getByTestId('enclosure-media')).toBeInTheDocument()
  })

  it('F011: isPlayableEnclosure 保守判定（type 或扩展名）', () => {
    expect(isPlayableEnclosure(AUDIO)).toBe(true)
    expect(isPlayableEnclosure({ href: 'https://x.example/f.pdf', type: 'application/pdf' })).toBe(false)
    expect(isPlayableEnclosure({ href: 'https://x.example/f.ogg', type: null })).toBe(true)
  })

  it('F011: 续播位置记录有界（仅保留最近 50 条）且读取稳定', () => {
    for (let i = 0; i < ENCLOSURE_POSITIONS_LIMIT + 5; i += 1) {
      recordEnclosurePosition(`e|https://a.example/${i}.mp3`, i * 10)
    }
    const positions = readEnclosurePositions()
    expect(Object.keys(positions).length).toBe(ENCLOSURE_POSITIONS_LIMIT)
    // 最旧的 5 条被逐出（写入序近似 LRU）
    expect(positions['e|https://a.example/0.mp3']).toBeUndefined()
    expect(positions['e|https://a.example/54.mp3']).toBe(540)
    expect(localStorage.getItem(ENCLOSURE_POSITIONS_KEY)).not.toBeNull()
  })
})
