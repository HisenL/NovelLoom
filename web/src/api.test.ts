import { afterEach, describe, expect, it, vi } from 'vitest'
import { request } from './api'

describe('API client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('returns JSON for successful requests', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    await expect(request<{ ok: boolean }>('/api/health')).resolves.toEqual({ ok: true })
  })

  it('surfaces domain errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: '预算不足' }), { status: 400, headers: { 'Content-Type': 'application/json' } })))
    await expect(request('/api/run')).rejects.toThrow('预算不足')
  })
})
