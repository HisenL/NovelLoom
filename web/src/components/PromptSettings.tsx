import { FormEvent, useEffect, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import { request } from '../api'

type Prompt = {
  id: string; key: string; revision_id: string; version: number
  system_prompt: string; user_prompt: string; status: string; history?: Prompt[]
}

export function PromptSettings({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<Prompt[]>([])
  const [selected, setSelected] = useState<Prompt | null>(null)
  const [notice, setNotice] = useState('')
  const load = async () => {
    const data = await request<{ items: Prompt[] }>(`/api/projects/${projectId}/prompts`)
    setItems(data.items)
  }
  useEffect(() => { void load().catch((error) => setNotice(error.message)) }, [projectId])
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    await request(`/api/projects/${projectId}/prompts`, {
      method: 'POST',
      body: JSON.stringify({ key: data.get('key'), system_prompt: data.get('system_prompt'), user_prompt: data.get('user_prompt'), status: 'approved' }),
    })
    setNotice('Prompt 已保存为新的批准版本。')
    await load()
  }
  const inspect = async (id: string) => setSelected(await request<Prompt>(`/api/prompts/${id}`))
  const rollback = async (prompt: Prompt) => {
    await request(`/api/prompts/${prompt.id}/rollback`, { method: 'POST', body: JSON.stringify({ revision_id: prompt.revision_id }) })
    setNotice(`已从 v${prompt.version} 创建新的回滚版本。`); await load()
  }
  return <section><div className="toolbar"><div><span className="kicker">VERSIONED PROMPT WORKBENCH</span><h2>Prompt 工坊</h2></div></div>{notice && <div className="notice">{notice}</div>}
    <div className="settings-grid"><form key={selected?.revision_id ?? 'new'} className="settings-card" onSubmit={(event) => void save(event).catch((error) => setNotice(error.message))}><h3>复制或编辑模板</h3><label>角色键<select name="key" defaultValue={selected?.key ?? 'world_builder'}><option>world_builder</option><option>plot_reasoner</option><option>chapter_planner</option><option>writer</option><option>extractor</option><option>critic</option></select></label><label>System Prompt<textarea name="system_prompt" required defaultValue={selected?.system_prompt} rows={9}/></label><label>User Prompt<textarea name="user_prompt" required defaultValue={selected?.user_prompt ?? '{context}'} rows={7}/></label><small>模板变量使用 {'{name}'} 语法；变量错误会在调用前中止。</small><button>保存新版本</button></form>
      <div className="settings-card"><h3>项目模板</h3><div className="profile-list prompt-list">{items.map((item) => <div key={item.id}><button className="secondary" onClick={() => void inspect(item.id)}><b>{item.key}</b> · v{item.version}</button><code>{item.status}</code><button className="secondary" onClick={() => void rollback(item).catch((error) => setNotice(error.message))}><RotateCcw size={14}/>回滚</button></div>)}{!items.length && <p>当前使用内置模板。保存后只影响本项目。</p>}</div>{selected?.history && <><h3>版本历史</h3><div className="profile-list">{selected.history.map((revision) => <div key={revision.revision_id}><span>v{revision.version}</span><code>{revision.status}</code><button className="secondary" onClick={() => void rollback({ ...selected, ...revision }).catch((error) => setNotice(error.message))}><RotateCcw size={14}/>恢复此版</button></div>)}</div></>}</div>
    </div>
  </section>
}
