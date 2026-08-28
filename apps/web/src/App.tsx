import EntryList from './components/EntryList'
import ReaderPlaceholder from './components/ReaderPlaceholder'
import Sidebar from './components/Sidebar'

/** Desktop-first 三栏 Web Shell：导航 / 文章列表 / 阅读区（0005 占位）。
 * 100dvh 内三栏各自滚动，页面整体不出现纵向滚动。 */
export default function App() {
  return (
    <div className="grid h-dvh grid-cols-[240px_400px_1fr] max-[1100px]:grid-cols-[220px_360px_1fr]">
      <aside className="min-w-0 overflow-y-auto border-r border-[var(--border)] bg-[var(--surface)]">
        <Sidebar />
      </aside>
      <section className="flex min-w-0 flex-col overflow-hidden border-r border-[var(--border)] bg-[var(--surface)]">
        <EntryList />
      </section>
      <section className="min-w-0 overflow-y-auto bg-[var(--surface)]">
        <ReaderPlaceholder />
      </section>
    </div>
  )
}
