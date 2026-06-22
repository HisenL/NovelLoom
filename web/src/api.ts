export type Project = {
  id: string; name: string; premise: string; language: string
  token_budget: number; cost_budget: number | null; tokens_used: number; cost_used: number
  books?: Book[]
}
export type Book = { id: string; key: string; type: string; title: string; order: number }
export type GraphNode = { id: string; revision_id: string; stable_key: string; kind: string; label: string; payload: Record<string, unknown>; status: string; version: number }
export type GraphEdge = { id: string; revision_id: string; stable_key: string; source: string; target: string; kind: string; label: string; payload: Record<string, unknown>; status: string; version: number }
export type NodeRevision = { id: string; version: number; label: string; payload: Record<string, unknown>; status: string; author: string; created_at: string }
export type EdgeRevision = { id: string; version: number; label: string; payload: Record<string, unknown>; status: string; author: string; created_at: string }
export type GraphNodeDetail = GraphNode & { history: NodeRevision[] }
export type GraphEdgeDetail = GraphEdge & { history: EdgeRevision[] }
export type Artifact = { id: string; revision_id: string; stable_key: string; kind: string; title: string; document: Record<string, unknown>; markdown: string; book_id: string | null; order: number; status: string; version: number; stale: boolean; stale_reason: string }
export type ArtifactRevision = { id: string; version: number; title: string; document: Record<string, unknown>; markdown: string; status: string; author: string; created_at: string }
export type ArtifactDetail = Artifact & { history: ArtifactRevision[] }

export async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(body.detail ?? `HTTP ${response.status}`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
