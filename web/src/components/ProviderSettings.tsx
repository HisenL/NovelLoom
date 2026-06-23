import { FormEvent, useEffect, useMemo, useState } from 'react'
import { KeyRound, Route, ShieldCheck } from 'lucide-react'
import { request } from '../api'

type Profile = {
  id: string
  key: string
  provider: string
  model: string
  base_url: string
  secret_ref: string
  has_secret: boolean
  capabilities: Record<string, unknown>
}

type RouteState = {
  role: string
  primary_profile_id: string
  fallback_profile_ids: string[]
}

type ProviderPreset = {
  id: string
  label: string
  key: string
  provider: string
  model: string
  base_url: string
  secret_ref: string
  structured_output: boolean
  streaming: boolean
  note: string
}

type FormState = {
  preset: string
  key: string
  provider: string
  model: string
  base_url: string
  secret_ref: string
  secret_value: string
  headers_text: string
  structured_output: boolean
  streaming: boolean
  input_rate: string
  output_rate: string
}

const roles = ['world_builder', 'plot_reasoner', 'chapter_planner', 'writer', 'extractor', 'critic']

const roleLabels: Record<string, string> = {
  world_builder: '世界构建',
  plot_reasoner: '事件推演',
  chapter_planner: '章节规划',
  writer: '正文写作',
  extractor: '事实抽取',
  critic: '一致性审核',
}

const presets: ProviderPreset[] = [
  {
    id: 'deepseek',
    label: 'DeepSeek',
    key: 'deepseek-main',
    provider: 'openai_compatible',
    model: 'deepseek-v4-flash',
    base_url: 'https://api.deepseek.com',
    secret_ref: 'env:DEEPSEEK_API_KEY',
    structured_output: true,
    streaming: true,
    note: '官方 OpenAI-compatible endpoint；deepseek-chat 将在 2026-07-24 后废弃，建议新配置使用 v4 系列模型。',
  },
  {
    id: 'qwen',
    label: '通义千问 / 百炼',
    key: 'qwen-main',
    provider: 'openai_compatible',
    model: 'qwen-plus',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    secret_ref: 'env:DASHSCOPE_API_KEY',
    structured_output: true,
    streaming: true,
    note: '阿里百炼 OpenAI-compatible endpoint。',
  },
  {
    id: 'glm',
    label: '智谱 GLM',
    key: 'glm-main',
    provider: 'openai_compatible',
    model: 'glm-5.2',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
    secret_ref: 'env:ZHIPU_API_KEY',
    structured_output: true,
    streaming: true,
    note: '智谱 OpenAI-compatible endpoint；模型名可按账号可用模型调整。',
  },
  {
    id: 'moonshot',
    label: 'Moonshot / Kimi',
    key: 'moonshot-main',
    provider: 'openai_compatible',
    model: 'kimi-k2.6',
    base_url: 'https://api.moonshot.cn/v1',
    secret_ref: 'env:MOONSHOT_API_KEY',
    structured_output: true,
    streaming: true,
    note: 'Moonshot OpenAI-compatible endpoint。',
  },
  {
    id: 'ollama',
    label: 'Ollama 本地',
    key: 'ollama-local',
    provider: 'openai_compatible',
    model: 'qwen2.5:7b',
    base_url: 'http://127.0.0.1:11434/v1',
    secret_ref: '',
    structured_output: false,
    streaming: true,
    note: '本地模型通常不需要 API Key；结构化能力视模型而定。',
  },
  {
    id: 'lmstudio',
    label: 'LM Studio 本地',
    key: 'lmstudio-local',
    provider: 'openai_compatible',
    model: 'local-model',
    base_url: 'http://127.0.0.1:1234/v1',
    secret_ref: '',
    structured_output: false,
    streaming: true,
    note: '适合本地 OpenAI-compatible 服务。',
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    key: 'anthropic-main',
    provider: 'anthropic',
    model: 'claude-sonnet',
    base_url: '',
    secret_ref: 'env:ANTHROPIC_API_KEY',
    structured_output: false,
    streaming: true,
    note: '模型名请按你账号中可用的 Claude 模型填写。',
  },
  {
    id: 'gemini',
    label: 'Google Gemini',
    key: 'gemini-main',
    provider: 'google_gemini',
    model: 'gemini-flash',
    base_url: '',
    secret_ref: 'env:GEMINI_API_KEY',
    structured_output: false,
    streaming: true,
    note: '模型名请按 Google AI Studio / Vertex 中可用模型填写。',
  },
  {
    id: 'mock',
    label: '离线 Mock 演示',
    key: 'mock-demo',
    provider: 'mock',
    model: 'fixture',
    base_url: '',
    secret_ref: '',
    structured_output: true,
    streaming: false,
    note: '不调用真实模型，用于跑通世界、事件、12+4 章节规划和导出冒烟测试。',
  },
  {
    id: 'custom',
    label: '自定义 OpenAI-compatible',
    key: 'custom-main',
    provider: 'openai_compatible',
    model: '',
    base_url: 'https://api.example.com/v1',
    secret_ref: 'env:CUSTOM_LLM_API_KEY',
    structured_output: true,
    streaming: true,
    note: '适合 OpenRouter、vLLM、One API、LiteLLM 等兼容服务。',
  },
]

const initialForm: FormState = {
  preset: 'deepseek',
  key: 'deepseek-main',
  provider: 'openai_compatible',
  model: 'deepseek-v4-flash',
  base_url: 'https://api.deepseek.com',
  secret_ref: 'env:DEEPSEEK_API_KEY',
  secret_value: '',
  headers_text: '',
  structured_output: true,
  streaming: true,
  input_rate: '',
  output_rate: '',
}

function parseHeaders(value: string): Record<string, string> {
  const trimmed = value.trim()
  if (!trimmed) return {}
  if (trimmed.startsWith('{')) {
    const parsed = JSON.parse(trimmed) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('自定义请求头必须是 JSON 对象，或每行一个 Header: value。')
    }
    return Object.fromEntries(
      Object.entries(parsed).map(([key, headerValue]) => [key, String(headerValue)]),
    )
  }
  return Object.fromEntries(
    trimmed.split('\n').map((line) => {
      const index = line.indexOf(':')
      if (index < 1) throw new Error('请求头格式应为 Header-Name: value。')
      return [line.slice(0, index).trim(), line.slice(index + 1).trim()]
    }),
  )
}

function applyPresetToState(preset: ProviderPreset): FormState {
  return {
    ...initialForm,
    preset: preset.id,
    key: preset.key,
    provider: preset.provider,
    model: preset.model,
    base_url: preset.base_url,
    secret_ref: preset.secret_ref,
    structured_output: preset.structured_output,
    streaming: preset.streaming,
  }
}

export function ProviderSettings({ projectId }: { projectId: string }) {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [adapters, setAdapters] = useState<string[]>([])
  const [routes, setRoutes] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState('')
  const [form, setForm] = useState<FormState>(initialForm)

  const selectedPreset = useMemo(
    () => presets.find((preset) => preset.id === form.preset) ?? presets[0],
    [form.preset],
  )

  const load = async () => {
    const [profileData, adapterData, routeData] = await Promise.all([
      request<{ items: Profile[] }>(`/api/projects/${projectId}/providers`),
      request<{ items: string[] }>('/api/providers/adapters'),
      request<{ items: RouteState[] }>(`/api/projects/${projectId}/routes`),
    ])
    setProfiles(profileData.items)
    setAdapters(adapterData.items)
    setRoutes(Object.fromEntries(routeData.items.map((route) => [route.role, route.primary_profile_id])))
  }

  useEffect(() => {
    void load().catch((error) => setNotice(error.message))
  }, [projectId])

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const headers = parseHeaders(form.headers_text)
    await request(`/api/projects/${projectId}/providers`, {
      method: 'POST',
      body: JSON.stringify({
        key: form.key,
        provider: form.provider,
        model: form.model,
        base_url: form.base_url,
        secret_ref: form.secret_ref,
        secret_value: form.secret_value || null,
        headers,
        capabilities: {
          structured_output: form.structured_output,
          streaming: form.streaming,
          input_cost_per_million: Number(form.input_rate || 0),
          output_cost_per_million: Number(form.output_rate || 0),
        },
      }),
    })
    setNotice('Profile 已保存；API Key 未进入数据库，响应中只保留 env:/keyring: 引用。')
    setForm((current) => ({ ...current, secret_value: '' }))
    await load()
  }

  const setRoute = async (role: string, profileId: string) => {
    if (!profileId) return
    await request(`/api/projects/${projectId}/routes/${role}`, {
      method: 'PUT',
      body: JSON.stringify({ primary_profile_id: profileId, fallback_profile_ids: [], parameters: {} }),
    })
    setRoutes((current) => ({ ...current, [role]: profileId }))
    setNotice(`${roleLabels[role] ?? role} 路由已更新。`)
  }

  const applyAllRoutes = async (profileId: string) => {
    for (const role of roles) {
      await request(`/api/projects/${projectId}/routes/${role}`, {
        method: 'PUT',
        body: JSON.stringify({ primary_profile_id: profileId, fallback_profile_ids: [], parameters: {} }),
      })
    }
    setRoutes(Object.fromEntries(roles.map((role) => [role, profileId])))
    setNotice('已将该模型应用到全部创作角色；现在可以启动世界构建流程。')
  }

  const test = async (id: string) => {
    const result = await request<{ ok: boolean; content: string }>(`/api/providers/${id}/test`, {
      method: 'POST',
    })
    setNotice(result.ok ? '连接成功。' : `连接失败：${result.content}`)
  }

  return (
    <section>
      <div className="toolbar">
        <div>
          <span className="kicker">MODEL ROUTING & SECRETS</span>
          <h2>模型能力与回退链</h2>
        </div>
      </div>
      {notice && <div className="notice">{notice}</div>}
      <div className="settings-grid">
        <form className="settings-card" onSubmit={(event) => void save(event).catch((error) => setNotice(error.message))}>
          <KeyRound/>
          <h3>新增 Provider Profile</h3>
          <label>常用服务预设
            <select
              value={form.preset}
              onChange={(event) => setForm(applyPresetToState(presets.find((preset) => preset.id === event.target.value) ?? presets[0]))}
            >
              {presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}
            </select>
          </label>
          <p className="form-hint">{selectedPreset.note}</p>
          <label>配置键
            <input value={form.key} onChange={(event) => setForm({ ...form, key: event.target.value })} required placeholder="deepseek-main"/>
          </label>
          <label>协议适配器
            <select value={form.provider} onChange={(event) => setForm({ ...form, provider: event.target.value })}>
              {adapters.length ? adapters.map((item) => <option key={item}>{item}</option>) : <option>{form.provider}</option>}
            </select>
          </label>
          <label>模型名
            <input value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} required placeholder="deepseek-v4-flash / qwen-plus / glm-5.2"/>
          </label>
          <label>Base URL
            <input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} placeholder="https://api.example.com/v1"/>
          </label>
          <label>API Key（推荐，可直接粘贴；只写入系统 Keyring）
            <input
              value={form.secret_value}
              onChange={(event) => setForm({ ...form, secret_value: event.target.value })}
              type="password"
              autoComplete="new-password"
              placeholder="sk-... / 留空则使用下面的引用"
            />
          </label>
          <label>高级：密钥引用（不是 API Key）
            <input
              value={form.secret_ref}
              onChange={(event) => setForm({ ...form, secret_ref: event.target.value })}
              placeholder="env:DEEPSEEK_API_KEY 或 keyring:novelloom/deepseek-main"
            />
          </label>
          <label>自定义请求头（可选，不要填 Authorization）
            <textarea
              value={form.headers_text}
              onChange={(event) => setForm({ ...form, headers_text: event.target.value })}
              placeholder={'HTTP-Referer: http://127.0.0.1:8123\nX-Title: NovelLoom'}
            />
          </label>
          <div className="row">
            <label>输入价 / 百万 tokens
              <input value={form.input_rate} onChange={(event) => setForm({ ...form, input_rate: event.target.value })} type="number" min="0" step="0.01"/>
            </label>
            <label>输出价 / 百万 tokens
              <input value={form.output_rate} onChange={(event) => setForm({ ...form, output_rate: event.target.value })} type="number" min="0" step="0.01"/>
            </label>
          </div>
          <div className="checkbox-row">
            <label><input type="checkbox" checked={form.structured_output} onChange={(event) => setForm({ ...form, structured_output: event.target.checked })}/> 支持结构化 JSON 输出</label>
            <label><input type="checkbox" checked={form.streaming} onChange={(event) => setForm({ ...form, streaming: event.target.checked })}/> 支持流式输出</label>
          </div>
          <button>保存 Profile</button>
        </form>
        <div className="settings-card">
          <Route/>
          <h3>角色路由</h3>
          <p className="form-hint">先用同一个模型应用到全部角色跑通；稳定后再把世界构建、事件推演、正文写作拆到不同模型。</p>
          {roles.map((role) => (
            <label key={role}>{roleLabels[role] ?? role}
              <select value={routes[role] ?? ''} onChange={(event) => void setRoute(role, event.target.value).catch((error) => setNotice(error.message))}>
                <option value="">选择主模型</option>
                {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.key} / {profile.model}</option>)}
              </select>
            </label>
          ))}
        </div>
        <div className="settings-card wide">
          <ShieldCheck/>
          <h3>已保存配置</h3>
          <div className="profile-list">
            {profiles.map((profile) => (
              <div key={profile.id}>
                <div>
                  <b>{profile.key}</b>
                  <small>{profile.provider} · {profile.model}</small>
                </div>
                <code>{profile.secret_ref || '无密钥引用'} {profile.has_secret ? '••••••' : ''}</code>
                <div className="profile-actions">
                  <button className="secondary" onClick={() => void test(profile.id).catch((error) => setNotice(error.message))}>测试连接</button>
                  <button className="secondary" onClick={() => void applyAllRoutes(profile.id).catch((error) => setNotice(error.message))}>应用到全部角色</button>
                </div>
              </div>
            ))}
            {!profiles.length && <p>尚未添加模型。可先选择“离线 Mock 演示”跑通流程，再配置真实第三方 API。</p>}
          </div>
        </div>
      </div>
    </section>
  )
}
