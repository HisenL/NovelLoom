import { useEffect, useState } from 'react'
import { Check, Pause, X } from 'lucide-react'
import { request } from '../api'

type Run = { id: string; status: string; current_step: string; created_at: string; error: string }
type Decision = { id: string; run_id: string | null; gate: string; status: string; payload: Record<string, unknown>; note: string; created_at: string }
type Job = { id: string; kind: string; status: string; progress: number; estimated_tokens: number; error: string }

function explainStartError(message: string): string {
  if (message.includes('尚未配置模型角色')) {
    const role = message.split(':').pop()?.trim()
    return `启动前需要先完成模型路由。缺少角色：${role ?? '未知'}。请到“模型设置”保存一个模型配置，并点击“应用到全部角色”。Prompt 工坊不是这里要配置的地方。`
  }
  return message
}

export function Runs({ projectId, onOpenSettings }: { projectId: string; onOpenSettings: () => void }) {
  const [runs, setRuns] = useState<Run[]>([]); const [decisions, setDecisions] = useState<Decision[]>([]); const [jobs, setJobs] = useState<Job[]>([]); const [notice, setNotice] = useState('')
  const load = async () => { const [r, d, j] = await Promise.all([request<{ items: Run[] }>(`/api/projects/${projectId}/runs`), request<{ items: Decision[] }>(`/api/projects/${projectId}/decisions`), request<{ items: Job[] }>(`/api/projects/${projectId}/jobs`)]); setRuns(r.items); setDecisions(d.items); setJobs(j.items) }
  useEffect(() => { void load(); const source = new EventSource(`/api/projects/${projectId}/jobs/stream`); source.addEventListener('jobs', (event) => setJobs(JSON.parse((event as MessageEvent).data).items)); return () => source.close() }, [projectId])
  const start = async () => {
    try {
      await request(`/api/projects/${projectId}/workflow/start`, { method: 'POST' })
      setNotice('已推进至下一个人工审核门。')
      await load()
    } catch (error) {
      setNotice(explainStartError((error as Error).message))
    }
  }
  const decide = async (decision: Decision, approve: boolean) => {
    if (decision.run_id && ['world_final', 'event_final', 'outline_final'].includes(decision.gate)) await request(`/api/runs/${decision.run_id}/resume`, { method: 'POST', body: JSON.stringify({ approve, note: '' }) })
    else if (decision.gate === 'batch_review') await request(`/api/writing/decisions/${decision.id}`, { method: 'POST', body: JSON.stringify({ approve, note: '' }) })
    else await request(`/api/decisions/${decision.id}`, { method: 'POST', body: JSON.stringify({ approve, note: '' }) })
    await load()
  }
  return <section><div className="toolbar"><div><span className="kicker">DURABLE WORKFLOW</span><h2>运行、人工门与恢复</h2></div><div><button className="secondary" onClick={onOpenSettings}>检查模型设置</button><button onClick={() => void start()}>启动规划流程</button></div></div>{notice && <div className="notice">{notice}</div>}
    <div className="run-columns"><div className="run-panel"><h3><Pause/>待审核</h3>{decisions.filter((item) => item.status === 'pending').map((item) => <article key={item.id}><span className="gate">{item.gate}</span><b>{item.gate === 'world_final' ? '世界事实候选' : item.gate === 'event_final' ? '事件因果总纲' : item.gate === 'outline_final' ? '多书章节规划' : '章节批次事实'}</b><small>{new Date(item.created_at).toLocaleString()}</small><pre>{JSON.stringify(item.payload, null, 2).slice(0, 900)}</pre><div><button className="approve" onClick={() => void decide(item, true).catch((e) => setNotice(e.message))}><Check size={15}/>批准并继续</button><button className="reject" onClick={() => void decide(item, false).catch((e) => setNotice(e.message))}><X size={15}/>驳回</button></div></article>)}{!decisions.some((item) => item.status === 'pending') && <p>当前没有等待处理的人工门。</p>}</div>
      <div className="run-panel"><h3>任务状态</h3>{jobs.map((job) => <article key={job.id}><div className="job-line"><b>{job.kind}</b><span className={`pill ${job.status}`}>{job.status}</span></div><div className="progress"><i style={{ width: `${job.progress * 100}%` }}/></div><small>预估 {job.estimated_tokens.toLocaleString()} tokens {job.error}</small></article>)}</div>
      <div className="run-panel"><h3>工作流历史</h3>{runs.map((run) => <article key={run.id}><div className="job-line"><b>{run.current_step || '初始化'}</b><span className={`pill ${run.status}`}>{run.status}</span></div><small>{new Date(run.created_at).toLocaleString()} {run.error}</small></article>)}</div>
    </div>
  </section>
}
