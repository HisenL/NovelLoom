import { useCallback, useEffect, useMemo, useState } from 'react'
import ELK from 'elkjs/lib/elk.bundled.js'
import { Background, Connection, Controls, Edge, MiniMap, Node, ReactFlow, addEdge, useEdgesState, useNodesState } from '@xyflow/react'
import { GraphEdge, GraphEdgeDetail, GraphNode, GraphNodeDetail, request } from '../api'

const elk = new ELK()
const colors: Record<string, string> = { character: '#d7a85b', location: '#68a990', organization: '#8b78c8', world_rule: '#d7766b', event: '#6d9fd1', item: '#b5a47a' }

export function GraphStudio({ projectId, mode }: { projectId: string; mode: 'world' | 'events' }) {
  const [rawNodes, setRawNodes] = useState<GraphNode[]>([])
  const [rawEdges, setRawEdges] = useState<GraphEdge[]>([])
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selectedNode, setSelectedNode] = useState<GraphNodeDetail | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<GraphEdgeDetail | null>(null)
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    const graph = await request<{ nodes: GraphNode[]; edges: GraphEdge[] }>(`/api/projects/${projectId}/graph`)
    const visible = graph.nodes.filter((node) => mode === 'events' ? node.kind === 'event' : node.kind !== 'event')
    const ids = new Set(visible.map((node) => node.id))
    const visibleEdges = graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target))
    setRawNodes(visible); setRawEdges(visibleEdges)
    const layout = await elk.layout({ id: 'root', layoutOptions: { 'elk.algorithm': 'layered', 'elk.direction': mode === 'events' ? 'RIGHT' : 'DOWN', 'elk.spacing.nodeNode': '55' }, children: visible.map((node) => ({ id: node.id, width: 180, height: 64 })), edges: visibleEdges.map((edge) => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })) })
    setNodes((layout.children ?? []).map((item) => { const source = visible.find((node) => node.id === item.id)!; return { id: source.id, position: { x: item.x ?? 0, y: item.y ?? 0 }, data: { label: <div className="graph-node"><small>{source.kind}</small><b>{source.label}</b><em>v{source.version} · {source.status}</em></div> }, style: { borderColor: colors[source.kind] ?? '#8aa', '--node-color': colors[source.kind] ?? '#8aa' } as React.CSSProperties } }))
    setEdges(visibleEdges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, label: edge.label || edge.kind, animated: edge.status === 'draft', type: 'smoothstep' })))
  }, [mode, projectId, setEdges, setNodes])
  useEffect(() => { void load().catch((e) => setNotice(e.message)) }, [load])

  const inspectNode = async (id: string) => { setSelectedEdge(null); setSelectedNode(await request<GraphNodeDetail>(`/api/graph/nodes/${id}`)) }
  const inspectEdge = async (id: string) => { setSelectedNode(null); setSelectedEdge(await request<GraphEdgeDetail>(`/api/graph/edges/${id}`)) }
  const onConnect = async (connection: Connection) => {
    if (!connection.source || !connection.target) return
    const kind = mode === 'events' ? 'causes' : 'relationship'
    try {
      await request(`/api/projects/${projectId}/graph/edges`, { method: 'POST', body: JSON.stringify({ stable_key: `${kind}:${connection.source}:${connection.target}:${Date.now()}`, source_node_id: connection.source, target_node_id: connection.target, kind, label: kind === 'causes' ? '导致' : '关联', payload: {}, approved: true }) })
      setEdges((current) => addEdge(connection, current)); await load()
    } catch (error) { setNotice((error as Error).message) }
  }
  const addNode = async () => {
    const label = window.prompt(mode === 'events' ? '事件名称' : '节点名称')?.trim(); if (!label) return
    const kind = mode === 'events' ? 'event' : (window.prompt('类型：character / location / organization / item / world_rule', 'character') || 'character')
    await request(`/api/projects/${projectId}/graph/nodes`, { method: 'POST', body: JSON.stringify({ stable_key: `${kind}:${Date.now()}`, kind, label, payload: {}, approved: true }) })
    await load()
  }
  const saveNode = async () => {
    if (!selectedNode) return
    const label = (document.getElementById('node-label') as HTMLInputElement).value
    const payload = JSON.parse((document.getElementById('node-payload') as HTMLTextAreaElement).value || '{}')
    await request(`/api/graph/nodes/${selectedNode.id}`, { method: 'PUT', body: JSON.stringify({ label, payload, approved: true }) })
    setNotice('新权威版本已保存；相关下游已进入重算。'); setSelectedNode(null); await load()
  }
  const saveEdge = async () => {
    if (!selectedEdge) return
    const label = (document.getElementById('edge-label') as HTMLInputElement).value
    const payload = JSON.parse((document.getElementById('edge-payload') as HTMLTextAreaElement).value || '{}')
    await request(`/api/graph/edges/${selectedEdge.id}`, { method: 'PUT', body: JSON.stringify({ label, payload, approved: true }) })
    setNotice('关系新版本已保存。'); setSelectedEdge(null); await load()
  }
  const rollback = async (type: 'nodes' | 'edges', id: string, revisionId: string) => {
    await request(`/api/graph/${type}/${id}/rollback`, { method: 'POST', body: JSON.stringify({ revision_id: revisionId }) })
    setNotice('已从历史版本创建新的权威版本。'); setSelectedNode(null); setSelectedEdge(null); await load()
  }
  const nodeById = useMemo(() => new Map(rawNodes.map((node) => [node.id, node])), [rawNodes])
  const edgeById = useMemo(() => new Map(rawEdges.map((edge) => [edge.id, edge])), [rawEdges])

  return <section className="studio">
    <div className="toolbar"><div><span className="kicker">{mode === 'events' ? 'CAUSAL EVENT DAG' : 'SHARED WORLD GRAPH'}</span><h2>{mode === 'events' ? '事件因果画布' : '世界关系画布'}</h2></div><div><button className="secondary" onClick={() => void load()}>自动布局</button><button onClick={() => void addNode()}>＋ 新建节点</button></div></div>
    {notice && <div className="notice" onClick={() => setNotice('')}>{notice}</div>}
    <div className="graph-layout"><div className="graph-canvas"><ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={(value) => void onConnect(value)} onNodeClick={(_, node) => { if (nodeById.has(node.id)) void inspectNode(node.id).catch((error) => setNotice(error.message)) }} onEdgeClick={(_, edge) => { if (edgeById.has(edge.id)) void inspectEdge(edge.id).catch((error) => setNotice(error.message)) }} fitView><Background gap={24} color="#30413c"/><MiniMap nodeColor={(node) => String(node.style?.borderColor ?? '#68a990')}/><Controls/></ReactFlow></div>
      <aside className="inspector">
        {selectedNode && <><span className="kicker">NODE INSPECTOR</span><h3>{selectedNode.stable_key}</h3><label>显示名称<input id="node-label" key={`label-${selectedNode.revision_id}`} defaultValue={selectedNode.label}/></label><label>结构化属性<textarea id="node-payload" key={`payload-${selectedNode.revision_id}`} defaultValue={JSON.stringify(selectedNode.payload, null, 2)}/></label><div className="version-line">当前 v{selectedNode.version} · {selectedNode.status}</div><button onClick={() => void saveNode().catch((e) => setNotice(e.message))}>保存新版本</button><VersionHistory history={selectedNode.history} onRollback={(id) => rollback('nodes', selectedNode.id, id)}/></>}
        {selectedEdge && <><span className="kicker">EDGE INSPECTOR</span><h3>{selectedEdge.stable_key}</h3><label>关系名称<input id="edge-label" key={`label-${selectedEdge.revision_id}`} defaultValue={selectedEdge.label}/></label><label>结构化属性<textarea id="edge-payload" key={`payload-${selectedEdge.revision_id}`} defaultValue={JSON.stringify(selectedEdge.payload, null, 2)}/></label><div className="version-line">{selectedEdge.kind} · v{selectedEdge.version}</div><button onClick={() => void saveEdge().catch((e) => setNotice(e.message))}>保存新版本</button><VersionHistory history={selectedEdge.history} onRollback={(id) => rollback('edges', selectedEdge.id, id)}/></>}
        {!selectedNode && !selectedEdge && <div className="inspector-empty"><NetworkGlyph/><b>选择节点或关系</b><p>查看属性、版本历史，并从任意旧版本创建新的权威版本。</p></div>}
      </aside>
    </div>
  </section>
}

function VersionHistory({ history, onRollback }: { history: { id: string; version: number; status: string; author: string }[]; onRollback: (id: string) => Promise<void> }) {
  return <div className="version-history"><h4>版本历史</h4>{history.map((revision) => <div key={revision.id}><span>v{revision.version} · {revision.author}</span><code>{revision.status}</code><button className="secondary" onClick={() => void onRollback(revision.id)}>恢复</button></div>)}</div>
}

function NetworkGlyph() { return <div className="network-glyph"><i/><i/><i/><i/></div> }
