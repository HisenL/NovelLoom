import { useEffect, useState } from 'react'
import Placeholder from '@tiptap/extension-placeholder'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { Artifact, ArtifactDetail, ArtifactRevision, request } from '../api'

export function Manuscripts({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<Artifact[]>([])
  const [selected, setSelected] = useState<ArtifactDetail | null>(null)
  const [compare, setCompare] = useState<ArtifactRevision | null>(null)
  const [kind, setKind] = useState('chapter_prose')
  const [notice, setNotice] = useState('')
  const editor = useEditor({ extensions: [StarterKit, Placeholder.configure({ placeholder: '正文从这里开始……' })], content: '' })
  const load = async () => { const result = await request<{ items: Artifact[] }>(`/api/projects/${projectId}/artifacts?kind=${kind}`); setItems(result.items) }
  const inspect = async (id: string) => { const detail = await request<ArtifactDetail>(`/api/artifacts/${id}`); setSelected(detail); setCompare(detail.history[1] ?? null) }
  useEffect(() => { setSelected(null); setCompare(null); void load().catch((e) => setNotice(e.message)) }, [projectId, kind])
  useEffect(() => { if (selected && editor) editor.commands.setContent(selected.document as never) }, [selected, editor])
  const save = async () => {
    if (!selected || !editor) return
    await request(`/api/projects/${projectId}/artifacts`, { method: 'POST', body: JSON.stringify({ stable_key: selected.stable_key, kind: selected.kind, title: selected.title, document: editor.getJSON(), markdown: editor.getText({ blockSeparator: '\n\n' }), book_id: selected.book_id, order: selected.order, status: 'approved', dependencies: [] }) })
    setNotice('已保存为新的不可变版本。'); await load(); await inspect(selected.id)
  }
  const rollback = async (revisionId: string) => {
    if (!selected) return
    await request(`/api/artifacts/${selected.id}/rollback`, { method: 'POST', body: JSON.stringify({ revision_id: revisionId }) })
    setNotice('已从所选历史版本创建新的权威版本。'); await load(); await inspect(selected.id)
  }
  return <section className="manuscripts"><div className="toolbar"><div><span className="kicker">MULTI-BOOK MANUSCRIPTS</span><h2>大纲、正文与版本</h2></div><select value={kind} onChange={(e) => setKind(e.target.value)}><option value="chapter_outline">章节大纲</option><option value="chapter_prose">章节正文</option><option value="chapter_summary">章节摘要</option><option value="review">一致性审核</option></select></div>{notice && <div className="notice">{notice}</div>}
    <div className="manuscript-layout"><aside className="chapter-list">{items.map((item) => <button key={item.id} className={selected?.id === item.id ? 'active' : ''} onClick={() => void inspect(item.id).catch((e) => setNotice(e.message))}><span>{String(item.order).padStart(2, '0')}</span><div><b>{item.title}</b><small>v{item.version} · {item.status}{item.stale ? ' · 已过期' : ''}</small></div></button>)}{!items.length && <p>暂无内容。完成图谱与多书规划后，这里会出现章节。</p>}</aside><article className="editor-panel">{selected && editor ? <><div className="editor-head"><div><input value={selected.title} onChange={(e) => setSelected({ ...selected, title: e.target.value })}/><small>{selected.stable_key}{selected.stale ? ` · ${selected.stale_reason}` : ''}</small></div><button onClick={() => void save().catch((e) => setNotice(e.message))}>保存新版本</button></div><div className="editor-tools"><button onClick={() => editor.chain().focus().toggleBold().run()}>粗体</button><button onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}>小标题</button><button onClick={() => editor.chain().focus().toggleBlockquote().run()}>引用</button></div><EditorContent editor={editor}/><div className="manuscript-versions"><div className="version-history"><h4>版本历史</h4>{selected.history.map((revision) => <div key={revision.id}><button className="secondary" onClick={() => setCompare(revision)}>v{revision.version}</button><code>{revision.status}</code><button className="secondary" onClick={() => void rollback(revision.id).catch((e) => setNotice(e.message))}>恢复此版</button></div>)}</div>{compare && <div className="version-diff"><div><b>当前 v{selected.version}</b><pre>{selected.markdown}</pre></div><div><b>对照 v{compare.version}</b><pre>{compare.markdown}</pre></div></div>}</div></> : <div className="editor-empty">选择一个章节开始编辑</div>}</article></div>
  </section>
}
