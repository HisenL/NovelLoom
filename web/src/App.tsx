import { lazy, Suspense, useEffect, useState } from 'react'
import { BookOpen, Boxes, GitFork, Library, Play, Settings2 } from 'lucide-react'
import { Project, request } from './api'

const Dashboard = lazy(() => import('./components/Dashboard').then((module) => ({ default: module.Dashboard })))
const GraphStudio = lazy(() => import('./components/GraphStudio').then((module) => ({ default: module.GraphStudio })))
const Manuscripts = lazy(() => import('./components/Manuscripts').then((module) => ({ default: module.Manuscripts })))
const ProviderSettings = lazy(() => import('./components/ProviderSettings').then((module) => ({ default: module.ProviderSettings })))
const PromptSettings = lazy(() => import('./components/PromptSettings').then((module) => ({ default: module.PromptSettings })))
const Runs = lazy(() => import('./components/Runs').then((module) => ({ default: module.Runs })))

type Page = 'dashboard' | 'world' | 'events' | 'books' | 'runs' | 'prompts' | 'settings'
const nav: { key: Page; label: string; icon: typeof Boxes }[] = [
  { key: 'dashboard', label: '项目驾驶舱', icon: Boxes },
  { key: 'world', label: '世界图谱', icon: GitFork },
  { key: 'events', label: '事件因果图', icon: Play },
  { key: 'books', label: '多书与正文', icon: Library },
  { key: 'runs', label: '运行与审核', icon: BookOpen },
  { key: 'prompts', label: 'Prompt 工坊', icon: BookOpen },
  { key: 'settings', label: '模型设置', icon: Settings2 },
]

export function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [page, setPage] = useState<Page>('dashboard')
  const [error, setError] = useState('')

  const reload = async () => {
    try {
      const result = await request<{ items: Project[] }>('/api/projects')
      setProjects(result.items)
      if (!projectId && result.items[0]) setProjectId(result.items[0].id)
    } catch (e) { setError((e as Error).message) }
  }
  useEffect(() => { void reload() }, [])
  const project = projects.find((item) => item.id === projectId)

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">NL</span><div><b>NovelLoom</b><small>故事不是写出来的，是织出来的</small></div></div>
      <label className="project-picker">当前项目
        <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
          <option value="">选择项目</option>
          {projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <nav>{nav.map(({ key, label, icon: Icon }) => <button className={page === key ? 'active' : ''} key={key} onClick={() => setPage(key)}><Icon size={18}/>{label}</button>)}</nav>
      <div className="sidebar-foot"><span className="status-dot"/>本地模式 · SQLite</div>
    </aside>
    <main>
      <header><div><span className="eyebrow">NOVELLOOM / {page.toUpperCase()}</span><h1>{project?.name ?? '创建你的第一部作品'}</h1></div><div className="budget">{project ? `${project.tokens_used.toLocaleString()} / ${project.token_budget.toLocaleString()} tokens` : '未选择项目'}</div></header>
      {error && <div className="notice error" onClick={() => setError('')}>{error}</div>}
      <Suspense fallback={<div className="notice">正在展开故事织机…</div>}>
      {page === 'dashboard' && <Dashboard project={project} onCreated={reload}/>}
      {page === 'world' && projectId && <GraphStudio projectId={projectId} mode="world"/>}
      {page === 'events' && projectId && <GraphStudio projectId={projectId} mode="events"/>}
      {page === 'books' && projectId && <Manuscripts projectId={projectId}/>}
      {page === 'runs' && projectId && <Runs projectId={projectId}/>}
      {page === 'prompts' && projectId && <PromptSettings projectId={projectId}/>}
      {page === 'settings' && projectId && <ProviderSettings projectId={projectId}/>}
      </Suspense>
    </main>
  </div>
}
