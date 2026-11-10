import { useEffect, useState } from "react";
import VoicePicker from "../VoicePicker";
import { api } from "../api";
import type { Provider, ProviderPreset } from "../types";

const EMPTY = {
  name: "",
  kind: "openai",
  base_url: "",
  model: "",
  api_key: "",
  temperature: 0.8,
  max_tokens: 1200,
  voice_id: "",
};

type FormState = typeof EMPTY & { id?: string; extra?: Record<string, unknown> };

export default function ProvidersView() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [presets, setPresets] = useState<ProviderPreset[]>([]);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);

  const load = async () => {
    try {
      const [ps, prs] = await Promise.all([api.providers(), api.presets()]);
      setProviders(ps);
      setPresets(prs);
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const patch = (data: Partial<FormState>) => setForm((prev) => ({ ...prev, ...data }));

  const applyPreset = (id: string) => {
    const preset = presets.find((p) => p.id === id);
    if (!preset) return;
    patch({ kind: preset.kind, base_url: preset.base_url, model: preset.model, name: form.name || preset.name });
  };

  const save = async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (!form.name.trim()) throw new Error("请填写 Provider 名称");
      const payload = {
        name: form.name.trim(),
        kind: form.kind,
        base_url: form.base_url,
        model: form.model,
        temperature: Number(form.temperature),
        max_tokens: Number(form.max_tokens),
        voice_id: form.voice_id,
        api_key: form.api_key || undefined,
        extra: form.extra || {},
      };
      if (form.id) await api.updateProvider(form.id, payload);
      else await api.createProvider(payload);
      setNotice("已保存");
      setForm(EMPTY);
      await load();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const edit = (p: Provider) => {
    setForm({
      id: p.id,
      name: p.name,
      kind: p.kind,
      base_url: p.base_url,
      model: p.model,
      api_key: "",
      temperature: p.temperature ?? 0.8,
      max_tokens: p.max_tokens ?? 1200,
      voice_id: p.voice_id || "",
      extra: p.extra || {},
    });
    setNotice("");
    setError("");
  };

  const remove = async (id: string) => {
    try {
      await api.deleteProvider(id);
      await load();
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  const test = async (id: string) => {
    setTesting(id);
    setError("");
    setNotice("");
    try {
      const result = await api.testProvider(id);
      if (result.ok) setNotice(`连通成功：${(result.response || "").slice(0, 160)}`);
      else setError(`连通失败：${result.error}`);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setTesting(null);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="page-title">AI Provider</div>
          <div className="page-desc">
            支持 OpenAI 兼容接口（DeepSeek / Kimi / 通义 / 智谱 / OpenRouter / Ollama）、Anthropic、Gemini，以及无需 Key 的本地模拟 AI。
          </div>
        </div>
        <button className="btn sm" onClick={load}>刷新</button>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {notice && <div className="card" style={{ marginBottom: 14, color: "var(--accent-2)", fontSize: 12.5 }}>{notice}</div>}

      <div className="card mb">
        <div className="row" style={{ marginBottom: 14 }}>
          <div>
            <div className="card-title">{form.id ? "编辑 Provider" : "新增 Provider"}</div>
            <div className="card-sub">API Key 只保存在本机 SQLite 中，不会上传。</div>
          </div>
          {form.id && (
            <button className="btn sm ghost right" onClick={() => setForm(EMPTY)}>取消编辑</button>
          )}
        </div>
        <div className="form-grid">
          <label className="field">
            <span>快捷预设</span>
            <select value="" onChange={(e) => applyPreset(e.target.value)}>
              <option value="">选择预设自动填充</option>
              {presets.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>显示名称</span>
            <input value={form.name} onChange={(e) => patch({ name: e.target.value })} placeholder="例如：DeepSeek-V3" />
          </label>
          <label className="field">
            <span>接口类型</span>
            <select value={form.kind} onChange={(e) => patch({ kind: e.target.value })}>
              <option value="openai">OpenAI 兼容</option>
              <option value="anthropic">Anthropic</option>
              <option value="gemini">Gemini</option>
              <option value="mock">本地模拟（无需 Key）</option>
            </select>
          </label>
          <label className="field">
            <span>Base URL</span>
            <input value={form.base_url} onChange={(e) => patch({ base_url: e.target.value })} placeholder="https://api.deepseek.com" />
          </label>
          <label className="field">
            <span>模型名</span>
            <input value={form.model} onChange={(e) => patch({ model: e.target.value })} placeholder="deepseek-chat" />
          </label>
          <label className="field">
            <span>API Key</span>
            <input type="password" value={form.api_key} onChange={(e) => patch({ api_key: e.target.value })} placeholder={form.id ? "留空表示不修改" : "sk-..."} />
          </label>
          <label className="field">
            <span>Temperature</span>
            <input type="number" step="0.1" min="0" max="2" value={form.temperature} onChange={(e) => patch({ temperature: Number(e.target.value) })} />
          </label>
          <label className="field">
            <span>Max Tokens</span>
            <input type="number" min="128" step="128" value={form.max_tokens} onChange={(e) => patch({ max_tokens: Number(e.target.value) })} />
          </label>
          <label className="field">
            <span>默认语音 ID（可选）</span>
            <VoicePicker
              value={form.voice_id}
              onChange={(value) => patch({ voice_id: value })}
              placeholder="选择默认音色，可被座位覆盖"
            />
          </label>
        </div>
        <div className="row mt">
          <button className="btn primary" onClick={save} disabled={busy}>
            {busy ? "保存中…" : form.id ? "保存修改" : "添加 Provider"}
          </button>
        </div>
      </div>

      <div className="provider-grid">
        {providers.map((p) => (
          <div className="card provider-card" key={p.id}>
            <div className="provider-head">
              <div className="provider-avatar">{p.name.slice(0, 2).toUpperCase()}</div>
              <div className="flex1">
                <div className="card-title">{p.name}</div>
                <div className="row gap-sm" style={{ marginTop: 4 }}>
                  <span className="chip accent">{p.kind}</span>
                  {p.model && <span className="chip">{p.model}</span>}
                </div>
              </div>
            </div>
            <dl className="kv">
              <dt>Base URL</dt>
              <dd>{p.base_url || "（内置）"}</dd>
              <dt>API Key</dt>
              <dd>{p.has_key ? "已配置" : "未配置"}</dd>
              <dt>参数</dt>
              <dd>temp {p.temperature} · {p.max_tokens} tokens</dd>
              <dt>语音 ID</dt>
              <dd>{p.voice_id || "（使用全局默认）"}</dd>
            </dl>
            <div className="row gap-sm" style={{ marginTop: 2 }}>
              <button className="btn sm" onClick={() => test(p.id)} disabled={testing === p.id}>
                {testing === p.id ? "测试中…" : "测试连通"}
              </button>
              <button className="btn sm ghost" onClick={() => edit(p)}>编辑</button>
              <button className="btn sm danger right" onClick={() => remove(p.id)}>删除</button>
            </div>
          </div>
        ))}
        {!providers.length && <div className="empty">还没有 Provider</div>}
      </div>
    </div>
  );
}
