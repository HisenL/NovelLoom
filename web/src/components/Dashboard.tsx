import { FormEvent, useState } from 'react'
import { ArrowRight, Coins, Network, Sparkles } from 'lucide-react'
import { Project, request } from '../api'

function modelSetupHint(message: string): string {
  if (message.includes('尚未配置模型角色')) {
    const role = message.split(':').pop()?.trim()
    return `还没有给“${role ?? '创作角色'}”绑定模型。请先进入“模型设置”：保存一个 Provider Profile，然后点击“应用到全部角色”。Prompt 工坊不用管，它只是改提示词模板。`
  }
  return message
}

export function Dashboard({ project, onCreated, onOpenSettings }: { project?: Project; onCreated: () => Promise<void>; onOpenSettings: () => void }) {
  const [creating, setCreating] = useState(false)
  const [message, setMessage] = useState('')

  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    setCreating(true)
    try {
      const biography = String(data.get('biography') ?? '').trim()
      const books: { key: string; type: string; title: string; source_book: string | null }[] = [{ key: 'main', type: 'main', title: String(data.get('title')), source_book: null }]
      if (biography) books.push({ key: 'biography_1', type: 'biography', title: biography, source_book: 'main' })
      await request('/api/projects', { method: 'POST', body: JSON.stringify({ name: data.get('name'), premise: data.get('premise'), language: 'zh-CN', token_budget: 1_000_000, books }) })
      await onCreated()
      setMessage('项目已创建，可以开始编织世界。')
      event.currentTarget.reset()
    } catch (e) { setMessage((e as Error).message) } finally { setCreating(false) }
  }

  if (!project) return <section className="empty-state">
    <div><span className="kicker">NEW STORY UNIVERSE</span><h2>从一粒故事种子，织出彼此呼应的多本书。</h2><p>正本、人物传记与外传共享同一份事实账本。模型先提出候选，人来决定什么成为真实。</p></div>
    <form className="create-form" onSubmit={create}>
      <input name="name" required placeholder="项目名称，例如：雾港纪事"/>
      <input name="title" required placeholder="正本书名"/>
      <input name="biography" placeholder="首本人物传记（可选）"/>
      <textarea name="premise" required placeholder="故事梗概、主题、禁区与期望气质……"/>
      <button disabled={creating}>{creating ? '正在创建…' : '创建故事宇宙'}<ArrowRight size={16}/></button>
      {message && <small>{message}</small>}
    </form>
  </section>

  const remaining = Math.max(0, project.token_budget - project.tokens_used)
  return <div className="dashboard-grid">
    <section className="hero-card"><span className="kicker">STORY CONTROL ROOM</span><h2>{project.premise}</h2><p>先稳定事实，再推进事件；先批准结构，再生成正文。</p><div className="hero-actions"><button onClick={() => request(`/api/projects/${project.id}/workflow/start`, { method: 'POST' }).then(() => setMessage('世界构建已运行至人工审核门。')).catch((e) => setMessage(modelSetupHint(e.message)))}><Sparkles size={17}/>启动图谱推演</button><button className="secondary" onClick={onOpenSettings}>先配置模型</button></div>{message && <small>{message}</small>}</section>
    <section className="metric-card"><Network/><span>共享账本</span><strong>SQLite</strong><small>不可变版本 · 可回滚</small></section>
    <section className="metric-card"><Coins/><span>剩余预算</span><strong>{remaining.toLocaleString()}</strong><small>tokens 硬上限</small></section>
    <section className="principle-card"><span>01</span><div><b>事实先于叙述</b><p>LLM 输出只进入候选区，批准后才成为共享事实。</p></div></section>
    <section className="principle-card"><span>02</span><div><b>结构自动重算</b><p>图谱编辑会精确失效下游，已批准正文绝不静默覆盖。</p></div></section>
  </div>
}
