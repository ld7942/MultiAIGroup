import { useEffect, useState } from "react";
import { api } from "../api";
import type { GameInfo, MemoryItem, RagSettings } from "../types";

const KIND_LABEL: Record<string, string> = {
  skill: "技能卡",
  lesson: "复盘技巧",
  manual: "手动录入",
};

const EMPTY_MEMORY = { text: "", game_id: "", role: "", faction: "", kind: "manual" };

export default function MemoryView() {
  const [cfg, setCfg] = useState<RagSettings | null>(null);
  const [games, setGames] = useState<GameInfo[]>([]);
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [game, setGame] = useState("");
  const [role, setRole] = useState("");
  const [kind, setKind] = useState("");
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState(EMPTY_MEMORY);

  const loadList = async (
    filters: { game_id?: string; role?: string; kind?: string } = {},
  ) => {
    try {
      const list = await api.memories({ ...filters, limit: 300 });
      setItems(list);
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  const load = async () => {
    try {
      const [rag, gs] = await Promise.all([api.rag(), api.games()]);
      setCfg(rag);
      setGames(gs);
      await loadList();
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filters = () => ({
    game_id: game || undefined,
    role: role || undefined,
    kind: kind || undefined,
  });

  const refresh = async () => {
    setError("");
    setNotice("");
    await loadList(filters());
  };

  const saveConfig = async () => {
    if (!cfg) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const saved = await api.saveRag({
        enabled: cfg.enabled,
        top_k: Number(cfg.top_k),
        min_score: Number(cfg.min_score),
        reflect: cfg.reflect,
        llm_reflect: cfg.llm_reflect,
      });
      setCfg(saved);
      setNotice("已保存。新配置在下一局开始时生效。");
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const seed = async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api.seedRag();
      setNotice(`已导入玩法技能卡：${result.added} 条，当前共 ${result.total} 条记忆。`);
      await loadList(filters());
      const rag = await api.rag();
      setCfg(rag);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const search = async () => {
    if (!query.trim()) {
      await refresh();
      return;
    }
    try {
      const list = await api.searchMemories(query.trim(), game || undefined, role || undefined, 12);
      setItems(list);
      setNotice(`语义检索命中 ${list.length} 条（按相似度排序）。`);
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  const addMemory = async () => {
    if (!form.text.trim()) {
      setError("记忆内容不能为空");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.createMemory({
        text: form.text.trim(),
        game_id: form.game_id,
        role: form.role,
        faction: form.faction,
        kind: "manual",
      });
      setForm(EMPTY_MEMORY);
      setNotice("已写入记忆库。");
      await loadList(filters());
      setCfg(await api.rag());
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm("删除这条记忆？")) return;
    try {
      await api.deleteMemory(id);
      await loadList(filters());
      setCfg(await api.rag());
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="page-title">AI 记忆库（RAG）</div>
          <div className="page-desc">
            内置玩法技能卡 + 每局复盘技巧，按角色/阵营向量检索后注入提示词。对局结束会自动压缩上下文并沉淀新技巧。
          </div>
        </div>
        <button className="btn sm" onClick={load}>刷新</button>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {notice && (
        <div className="card" style={{ marginBottom: 14, color: "var(--accent-2)", fontSize: 12.5 }}>
          {notice}
        </div>
      )}

      {cfg && (
        <div className="card mb">
          <div className="row" style={{ marginBottom: 14 }}>
            <div>
              <div className="card-title">检索与复盘设置</div>
              <div className="card-sub">关闭后不检索记忆，也不在对局结束时写入复盘。</div>
            </div>
            <span className="chip right">共 {cfg.total ?? items.length} 条记忆</span>
          </div>
          <div className="form-grid">
            <label className="field">
              <span>启用 RAG</span>
              <select
                value={cfg.enabled ? "1" : "0"}
                onChange={(e) => setCfg({ ...cfg, enabled: e.target.value === "1" })}
              >
                <option value="1">开启</option>
                <option value="0">关闭</option>
              </select>
            </label>
            <label className="field">
              <span>对局结束自动复盘</span>
              <select
                value={cfg.reflect ? "1" : "0"}
                onChange={(e) => setCfg({ ...cfg, reflect: e.target.value === "1" })}
              >
                <option value="1">开启</option>
                <option value="0">关闭</option>
              </select>
            </label>
            <label className="field">
              <span>使用模型复盘</span>
              <select
                value={cfg.llm_reflect ? "1" : "0"}
                onChange={(e) => setCfg({ ...cfg, llm_reflect: e.target.value === "1" })}
              >
                <option value="1">开启（失败自动用规则兜底）</option>
                <option value="0">关闭（只用规则）</option>
              </select>
            </label>
            <label className="field">
              <span>每步检索条数</span>
              <input
                type="number"
                min={1}
                max={12}
                value={cfg.top_k}
                onChange={(e) => setCfg({ ...cfg, top_k: Number(e.target.value) })}
              />
            </label>
            <label className="field">
              <span>最低相似度</span>
              <input
                type="number"
                step="0.01"
                min={0}
                max={1}
                value={cfg.min_score}
                onChange={(e) => setCfg({ ...cfg, min_score: Number(e.target.value) })}
              />
            </label>
          </div>
          <div className="row mt gap-sm">
            <button className="btn primary" onClick={saveConfig} disabled={busy}>
              {busy ? "保存中…" : "保存设置"}
            </button>
            <button className="btn sm ghost" onClick={seed} disabled={busy}>
              重新导入玩法技能卡
            </button>
          </div>
        </div>
      )}

      <div className="card mb">
        <div className="card-title" style={{ marginBottom: 10 }}>新增记忆</div>
        <div className="form-grid">
          <label className="field">
            <span>游戏</span>
            <select value={form.game_id} onChange={(e) => setForm({ ...form, game_id: e.target.value })}>
              <option value="">通用</option>
              {games.map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>角色</span>
            <input
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value })}
              placeholder="例如：狼人 / 地主 / 主公，留空表示通用"
            />
          </label>
          <label className="field">
            <span>阵营（可选）</span>
            <input
              value={form.faction}
              onChange={(e) => setForm({ ...form, faction: e.target.value })}
              placeholder="例如：狼人阵营"
            />
          </label>
          <label className="field" style={{ gridColumn: "1 / -1" }}>
            <span>技巧内容</span>
            <input
              value={form.text}
              onChange={(e) => setForm({ ...form, text: e.target.value })}
              placeholder="写成可执行的建议，例如：狼人首夜优先刀发言强势的信息位。"
            />
          </label>
        </div>
        <div className="row mt">
          <button className="btn primary" onClick={addMemory} disabled={busy}>写入记忆库</button>
        </div>
      </div>

      <div className="card mb">
        <div className="row" style={{ marginBottom: 12 }}>
          <div>
            <div className="card-title">记忆列表</div>
            <div className="card-sub">可按游戏 / 角色 / 类型筛选，或输入一句话做语义检索。</div>
          </div>
        </div>
        <div className="form-grid">
          <label className="field">
            <span>游戏</span>
            <select
              value={game}
              onChange={(e) => {
                setGame(e.target.value);
                loadList({ game_id: e.target.value || undefined, role: role || undefined, kind: kind || undefined });
              }}
            >
              <option value="">全部</option>
              {games.map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>角色</span>
            <input
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="例如：女巫"
              onBlur={() => refresh()}
            />
          </label>
          <label className="field">
            <span>类型</span>
            <select
              value={kind}
              onChange={(e) => {
                setKind(e.target.value);
                loadList({ game_id: game || undefined, role: role || undefined, kind: e.target.value || undefined });
              }}
            >
              <option value="">全部</option>
              <option value="skill">技能卡</option>
              <option value="lesson">复盘技巧</option>
              <option value="manual">手动录入</option>
            </select>
          </label>
          <label className="field">
            <span>语义检索</span>
            <div className="row gap-sm">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="例如：女巫毒药该给谁"
                onKeyDown={(e) => e.key === "Enter" && search()}
              />
              <button className="btn sm" onClick={search}>检索</button>
            </div>
          </label>
        </div>
      </div>

      <div className="provider-grid">
        {items.map((item) => (
          <div className="card" key={item.id}>
            <div className="row" style={{ marginBottom: 6 }}>
              <span className={`chip ${item.kind === "skill" ? "accent" : item.kind === "lesson" ? "warn" : ""}`}>
                {KIND_LABEL[item.kind] || item.kind}
              </span>
              {item.game_id && <span className="chip">{item.game_id}</span>}
              {item.role && <span className="chip">{item.role}</span>}
              {item.faction && <span className="chip">{item.faction}</span>}
              {item.score != null && <span className="chip right">{Math.round(item.score * 100)}%</span>}
            </div>
            <div className="small" style={{ lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{item.text}</div>
            <div className="row mt">
              <span className="muted tiny">{item.source || "—"}{item.match_id ? ` · ${item.match_id.slice(0, 12)}` : ""}</span>
              <button className="btn sm danger right" onClick={() => remove(item.id)}>删除</button>
            </div>
          </div>
        ))}
        {!items.length && <div className="empty">还没有记忆，点「重新导入玩法技能卡」开始。</div>}
      </div>
    </div>
  );
}
