import { FormEvent, useEffect, useState } from 'react'
import { KeyRound, Route, ShieldCheck } from 'lucide-react'
import { request } from '../api'

type Profile = { id: string; key: string; provider: string; model: string; base_url: string; secret_ref: string; has_secret: boolean; capabilities: Record<string, unknown> }
const roles = ['world_builder', 'plot_reasoner', 'chapter_planner', 'writer', 'extractor', 'critic']

export function ProviderSettings({ projectId }: { projectId: string }) {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [adapters, setAdapters] = useState<string[]>([])
  const [notice, setNotice] = useState('')
  const load = async () => {
    const [profileData, adapterData] = await Promise.all([request<{ items: Profile[] }>(`/api/projects/${projectId}/providers`), request<{ items: string[] }>('/api/providers/adapters')])
    setProfiles(profileData.items); setAdapters(adapterData.items)
  }
  useEffect(() => { void load().catch((e) => setNotice(e.message)) }, [projectId])
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const data = new FormData(event.currentTarget)
    await request(`/api/projects/${projectId}/providers`, { method: 'POST', body: JSON.stringify({ key: data.get('key'), provider: data.get('provider'), model: data.get('model'), base_url: data.get('base_url'), secret_ref: data.get('secret_ref'), secret_value: data.get('secret_value') || null, capabilities: { structured_output: true, streaming: true, input_cost_per_million: Number(data.get('input_rate') || 0), output_cost_per_million: Number(data.get('output_rate') || 0) } }) })
    setNotice('Profile 已保存；密钥值未进入数据库。'); event.currentTarget.reset(); await load()
  }
  const setRoute = async (role: string, profileId: string) => { if (!profileId) return; await request(`/api/projects/${projectId}/routes/${role}`, { method: 'PUT', body: JSON.stringify({ primary_profile_id: profileId, fallback_profile_ids: [], parameters: {} }) }); setNotice(`${role} 路由已更新。`) }
  const test = async (id: string) => { const result = await request<{ ok: boolean; content: string }>(`/api/providers/${id}/test`, { method: 'POST' }); setNotice(result.ok ? '连接成功。' : `响应异常：${result.content}`) }
  return <section><div className="toolbar"><div><span className="kicker">MODEL ROUTING & SECRETS</span><h2>模型能力与回退链</h2></div></div>{notice && <div className="notice">{notice}</div>}
    <div className="settings-grid"><form className="settings-card" onSubmit={(e) => void save(e).catch((error) => setNotice(error.message))}><KeyRound/><h3>新增 Provider Profile</h3><label>配置键<input name="key" required placeholder="deepseek-main"/></label><label>协议适配器<select name="provider">{adapters.map((item) => <option key={item}>{item}</option>)}</select></label><label>模型名<input name="model" required placeholder="deepseek-chat"/></label><label>Base URL<input name="base_url" placeholder="https://api.example.com/v1"/></label><label>密钥引用<input name="secret_ref" placeholder="env:DEEPSEEK_API_KEY"/></label><label>或写入系统 Keyring<input name="secret_value" type="password" autoComplete="new-password" placeholder="仅本次提交可见"/></label><div className="row"><label>输入价 / 百万<input name="input_rate" type="number" min="0" step="0.01"/></label><label>输出价 / 百万<input name="output_rate" type="number" min="0" step="0.01"/></label></div><button>保存 Profile</button></form>
      <div className="settings-card"><Route/><h3>角色路由</h3>{roles.map((role) => <label key={role}>{role}<select defaultValue="" onChange={(e) => void setRoute(role, e.target.value).catch((error) => setNotice(error.message))}><option value="">选择主模型</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.key} / {profile.model}</option>)}</select></label>)}</div>
      <div className="settings-card wide"><ShieldCheck/><h3>已保存配置</h3><div className="profile-list">{profiles.map((profile) => <div key={profile.id}><div><b>{profile.key}</b><small>{profile.provider} · {profile.model}</small></div><code>{profile.secret_ref || '无密钥引用'} {profile.has_secret ? '••••••' : ''}</code><button className="secondary" onClick={() => void test(profile.id).catch((error) => setNotice(error.message))}>测试连接</button></div>)}{!profiles.length && <p>尚未添加模型。可先用内置 mock 适配器做离线演示。</p>}</div></div>
    </div>
  </section>
}
