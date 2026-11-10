import { useEffect, useState } from "react";
import VoicePicker from "../VoicePicker";
import { api } from "../api";
import { speechStatus, testVoice } from "../speech";
import type { VoiceDiagnostics, VoiceSettings } from "../types";

const EMPTY: VoiceSettings = {
  enabled: false,
  provider: "browser",
  default_voice_id: "",
  narrator_voice_id: "",
  speed: 1,
  wait_ms: 15000,
  voicestudio: {
    url: "",
    api_key: "",
    headers: {},
    text_field: "text",
    voice_field: "voice_id",
    extra_body: {},
    audio_field: "audio",
    audio_url_field: "audio_url",
    timeout_ms: 20000,
  },
};

export default function VoiceView() {
  const [cfg, setCfg] = useState<VoiceSettings>(EMPTY);
  const [headersText, setHeadersText] = useState("{}");
  const [extraBodyText, setExtraBodyText] = useState("{}");
  const [sample, setSample] = useState("天黑请闭眼，狼人请睁眼。");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [diag, setDiag] = useState<VoiceDiagnostics | null>(null);
  const [local, setLocal] = useState(speechStatus());
  const [diagError, setDiagError] = useState("");

  const refreshDiag = () => {
    setLocal(speechStatus());
    api
      .voiceDiagnostics()
      .then((data) => {
        setDiag(data);
        setDiagError("");
      })
      .catch((exc) => setDiagError((exc as Error).message));
  };

  useEffect(() => {
    refreshDiag();
  }, []);

  useEffect(() => {
    api
      .voice()
      .then((data) => {
        const merged: VoiceSettings = {
          ...EMPTY,
          ...data,
          voicestudio: { ...EMPTY.voicestudio, ...(data.voicestudio || {}) },
        };
        setCfg(merged);
        setHeadersText(JSON.stringify(merged.voicestudio.headers || {}, null, 2));
        setExtraBodyText(JSON.stringify(merged.voicestudio.extra_body || {}, null, 2));
      })
      .catch((exc) => setError((exc as Error).message));
  }, []);

  const patch = (data: Partial<VoiceSettings>) => setCfg((prev) => ({ ...prev, ...data }));
  const patchVs = (data: Partial<VoiceSettings["voicestudio"]>) =>
    setCfg((prev) => ({ ...prev, voicestudio: { ...prev.voicestudio, ...data } }));

  const save = async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      let headers: Record<string, string> = {};
      let extraBody: Record<string, unknown> = {};
      try {
        headers = headersText.trim() ? JSON.parse(headersText) : {};
        extraBody = extraBodyText.trim() ? JSON.parse(extraBodyText) : {};
      } catch {
        throw new Error("自定义 Headers / 请求体扩展必须是合法 JSON");
      }
      const saved = await api.saveVoice({
        ...cfg,
        voicestudio: { ...cfg.voicestudio, headers, extra_body: extraBody },
      });
      setCfg(saved);
      setNotice(
        saved.enabled
          ? `语音已启用（${
              saved.provider === "voicestudio"
                ? "VoiceStudio"
                : saved.provider === "system"
                  ? "Windows 系统语音"
                  : "浏览器本地朗读"
            }）`
          : "已保存，语音朗读当前关闭",
      );
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="page-title">语音朗读</div>
          <div className="page-desc">
            开启后，上帝播报、玩家发言与出牌会依次朗读，读完一段才轮到下一个人行动。
            保存后立即生效（进行中的对局也会热加载新配置）。桌面端若浏览器语音引擎不可用，
            可选择「系统语音」由后端直接调用 Windows SAPI 朗读。
          </div>
        </div>
        <button className="btn sm" onClick={save} disabled={busy}>
          {busy ? "保存中…" : "保存配置"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {notice && (
        <div className="card" style={{ marginBottom: 14, color: "var(--accent-2)", fontSize: 12.5 }}>
          {notice}
        </div>
      )}
      {!cfg.enabled && (
        <div
          className="card"
          style={{
            marginBottom: 14,
            borderColor: "var(--warn, #d9a441)",
            color: "var(--warn, #d9a441)",
            fontSize: 12.5,
          }}
        >
          语音朗读当前是关闭状态：下面的「试听」仍会发声，但进入对局不会朗读。
          请勾选「启用语音朗读」并点击右上角「保存配置」。
        </div>
      )}

      <div className="card mb">
        <div className="row" style={{ marginBottom: 14 }}>
          <div>
            <div className="card-title">朗读开关与音色</div>
            <div className="card-sub">
              座位可用各自的 voice_id 覆盖，留空则使用 Provider 默认音色，再回退到这里的默认音色。
            </div>
          </div>
          <label className="checkline right">
            <input
              type="checkbox"
              checked={cfg.enabled}
              onChange={(e) => patch({ enabled: e.target.checked })}
            />
            <span>启用语音朗读</span>
          </label>
        </div>
        <div className="form-grid">
          <label className="field">
            <span>语音通道</span>
            <select value={cfg.provider} onChange={(e) => patch({ provider: e.target.value })}>
              <option value="browser">浏览器本地朗读（Web Speech）</option>
              <option value="system">系统语音（Windows SAPI，后端本机播放）</option>
              <option value="voicestudio">VoiceStudio / 自定义 HTTP TTS</option>
            </select>
          </label>
          <label className="field">
            <span>默认音色 voice_id</span>
            <VoicePicker
              value={cfg.default_voice_id}
              onChange={(value) => patch({ default_voice_id: value })}
              placeholder="留空使用浏览器默认音色"
            />
          </label>
          <label className="field">
            <span>旁白 / 上帝音色 voice_id</span>
            <VoicePicker
              value={cfg.narrator_voice_id}
              onChange={(value) => patch({ narrator_voice_id: value })}
              placeholder="留空回退到默认音色"
            />
          </label>
          <label className="field">
            <span>语速</span>
            <input
              type="number"
              step="0.1"
              min="0.5"
              max="2"
              value={cfg.speed}
              onChange={(e) => patch({ speed: Number(e.target.value) })}
            />
          </label>
          <label className="field">
            <span>等待回执超时（毫秒）</span>
            <input
              type="number"
              min="1000"
              step="1000"
              value={cfg.wait_ms}
              onChange={(e) => patch({ wait_ms: Number(e.target.value) })}
            />
          </label>
        </div>
        <div className="row mt wrap" style={{ gap: 10 }}>
          <input
            style={{ maxWidth: 360 }}
            value={sample}
            onChange={(e) => setSample(e.target.value)}
            placeholder="试听文本"
          />
          <button
            className="btn sm"
            onClick={() => {
              testVoice(sample, cfg.narrator_voice_id || cfg.default_voice_id, cfg.speed);
              if (!cfg.enabled) {
                setNotice("试听成功；但「启用语音朗读」未勾选，进入对局不会朗读，请勾选后保存。");
              }
            }}
          >
            试听
          </button>
          <span className="muted tiny">
            浏览器通道可直接填系统音色名称，例如「Microsoft Xiaoxiao」；不同浏览器列表不同。
          </span>
        </div>
      </div>

      <div className="card mb">
        <div className="row" style={{ marginBottom: 8 }}>
          <div>
            <div className="card-title">语音诊断</div>
            <div className="card-sub">
              声音不出来时先看这里：浏览器是否有语音引擎、后端是否能调用系统语音。
            </div>
          </div>
          <button className="btn sm right" onClick={refreshDiag}>刷新</button>
        </div>
        {diagError && <div className="muted tiny" style={{ marginBottom: 8 }}>后端诊断失败：{diagError}</div>}
        <div className="tag-list">
          <span className={`chip ${local.supported ? "green" : "red"}`}>
            浏览器语音：{local.supported ? "可用" : "不可用"}
          </span>
          <span className={`chip ${local.voices > 0 ? "green" : "red"}`}>
            音色数量：{local.voices}（中文 {local.zhVoices}）
          </span>
          {local.lastError && <span className="chip red">最近错误：{local.lastError}</span>}
          {diag && (
            <span className={`chip ${diag.system_tts.available ? "green" : "red"}`}>
              系统语音：{diag.system_tts.available ? `可用（${diag.system_tts.voices.length} 个音色）` : diag.system_tts.reason || "不可用"}
            </span>
          )}
          {diag && <span className="chip">平台：{diag.platform}</span>}
          {diag && <span className="chip">{diag.enabled ? "后端语音已开启" : "后端语音未开启"}</span>}
        </div>
        {local.supported && local.voices === 0 && (
          <div className="muted tiny" style={{ marginTop: 8 }}>
            浏览器没有返回任何音色（常见于桌面 WebView2）。建议把语音通道切换为「系统语音」，或使用 VoiceStudio。
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-title" style={{ marginBottom: 4 }}>VoiceStudio / 自定义 TTS</div>
        <div className="card-sub" style={{ marginBottom: 14 }}>
          选择 VoiceStudio 通道时，后端会按这里的字段映射发起 POST；返回音频 URL、base64 或二进制音频均可。
          调用失败会自动退回浏览器本地朗读，不影响对局。
        </div>
        <div className="form-grid">
          <label className="field full">
            <span>接口地址</span>
            <input
              value={cfg.voicestudio.url}
              onChange={(e) => patchVs({ url: e.target.value })}
              placeholder="https://your-voice-studio.example.com/tts"
            />
          </label>
          <label className="field">
            <span>API Key（可选）</span>
            <input
              type="password"
              value={cfg.voicestudio.api_key}
              onChange={(e) => patchVs({ api_key: e.target.value })}
              placeholder="以 Bearer 方式发送"
            />
          </label>
          <label className="field">
            <span>超时（毫秒）</span>
            <input
              type="number"
              min="1000"
              step="1000"
              value={cfg.voicestudio.timeout_ms}
              onChange={(e) => patchVs({ timeout_ms: Number(e.target.value) })}
            />
          </label>
          <label className="field">
            <span>文本字段名</span>
            <input
              value={cfg.voicestudio.text_field}
              onChange={(e) => patchVs({ text_field: e.target.value })}
            />
          </label>
          <label className="field">
            <span>音色字段名</span>
            <input
              value={cfg.voicestudio.voice_field}
              onChange={(e) => patchVs({ voice_field: e.target.value })}
            />
          </label>
          <label className="field">
            <span>音频字段名</span>
            <input
              value={cfg.voicestudio.audio_field}
              onChange={(e) => patchVs({ audio_field: e.target.value })}
            />
          </label>
          <label className="field">
            <span>音频 URL 字段名</span>
            <input
              value={cfg.voicestudio.audio_url_field}
              onChange={(e) => patchVs({ audio_url_field: e.target.value })}
            />
          </label>
          <label className="field">
            <span>自定义 Headers（JSON）</span>
            <textarea
              rows={4}
              value={headersText}
              onChange={(e) => setHeadersText(e.target.value)}
            />
          </label>
          <label className="field">
            <span>请求体扩展（JSON）</span>
            <textarea
              rows={4}
              value={extraBodyText}
              onChange={(e) => setExtraBodyText(e.target.value)}
            />
          </label>
        </div>
        <div className="row mt">
          <button className="btn primary" onClick={save} disabled={busy}>
            {busy ? "保存中…" : "保存配置"}
          </button>
        </div>
      </div>
    </div>
  );
}
