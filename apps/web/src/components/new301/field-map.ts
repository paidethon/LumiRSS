/** API 来源字段映射（五键）共享小模块：向导（创建）与详情抽屉（编辑）
 * 用同一份键位与空态，避免两处漂移。 */

import type { ApiSourceFieldMapInput } from '../../api/client'

export type ApiSourceFieldMapState = ApiSourceFieldMapInput

export const FIELD_MAP_FIELDS: {
  key: keyof ApiSourceFieldMapState
  label: string
}[] = [
  { key: 'id', label: 'id 表达式' },
  { key: 'title', label: 'title 表达式' },
  { key: 'url', label: 'url 表达式' },
  { key: 'published', label: 'published 表达式' },
  { key: 'body', label: 'body 表达式' },
]

export const EMPTY_FIELD_MAP: ApiSourceFieldMapState = {
  id: '',
  title: '',
  url: '',
  published: '',
  body: '',
}

/** 去掉未填写的键后提交（空串 = 未映射，不发给服务端）。 */
export function pruneFieldMap(state: ApiSourceFieldMapState): ApiSourceFieldMapState {
  const pruned = { ...state }
  for (const key of Object.keys(pruned) as (keyof ApiSourceFieldMapState)[]) {
    if (pruned[key].trim() === '') delete pruned[key]
  }
  return pruned
}
