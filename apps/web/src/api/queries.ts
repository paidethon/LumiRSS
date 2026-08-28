/** TanStack Query hooks —— server state 的唯一入口。
 * useFeeds/useEntries 在 Sidebar / EntryList / ReaderPlaceholder 间共享
 * （同 query key 命中同一份 cache，不会重复请求）。 */

import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { getEntries, getFeeds } from './client'
import type { EntryView } from './types'

export function useFeeds() {
  return useQuery({
    queryKey: ['feeds'],
    queryFn: ({ signal }) => getFeeds(signal),
  })
}

export function useEntries(view: EntryView, feedUrl: string | null) {
  return useInfiniteQuery({
    queryKey: ['entries', { view, feedUrl }],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      getEntries({ view, feedUrl, cursor: pageParam }, signal),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  })
}
