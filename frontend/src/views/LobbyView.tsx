import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { GameInfo, Group, MatchSummary, Provider, SeatDraft } from "../types";

const GAME_ICONS: Record<string, string> = {
  werewolf: "🐺",
  doudizhu: "🃏",
  sanguosha: "⚔️",
};
const COLORS = [
  "#7c9cff", "#ff8f6b", "#4fd1a5", "#d38bff", "#ffd166",
  "#6bd5ff", "#ff7aa2", "#a3e635", "#f0abfc", "#fca5a5",
];
const STATUS_LABEL: Record<string, string> = {
  created: "待开始",
  running: "进行中",
  finished: "已结束",
  stopped: "已停止",
  interrupted: "已中断",
  error: "异常",
};

export default function LobbyView({
  onOpenMatch,
  onGoProviders,
}: {
  onOpenMatch: (id: string) => void;
  onGoProviders: () => void;
}) {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [matches, setMatches] = useState<MatchSummary[]>([]);
  const [gameId, setGameId] = useState("");
  const [title, setTitle] = useState("");
  const [count, setCount] = useState(3);
  const [seats, setSeats] = useState<SeatDraft[]>([]);
  const [groupId, setGroupId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const game = useMemo(() => games.find((g) => g.id === gameId), [games, gameId]);

  const load = async () => {
    try {
      const [gs, ps, gps, ms] = await Promise.all([
        api.games(),
        api.providers(),
        api.groups(),
        api.matches(),
      ]);
      setGames(gs);
      setProviders(ps);
      setGroups(gps);
      setMatches(ms);
      setGameId((prev) => prev || gs[0]?.id || "");
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const counts = useMemo(() => {
    if (!game) return [] as number[];
    if (game.allowed_counts?.length) return game.allowed_counts;
    const result: number[] = [];
    for (let i = game.min_players; i <= game.max_players; i += 1) result.push(i);
    return result;
  }, [game]);

  const makeSeats = (n: number, base: SeatDraft[] = [], defaultProvider = ""): SeatDraft[] =>
    Array.from({ length: n }, (_, i) => ({
      name: base[i]?.name || `AI ${i + 1}`,
      provider_id: base[i]?.provider_id || defaultProvider,
      persona: base[i]?.persona || "",
    }));

  // 游戏/人数/Provider 列表就绪后初始化座位
  useEffect(() => {
    if (!game || !counts.length) return;
    setCount((prev) => (counts.includes(prev) ? prev : counts[0]));
  }, [game, counts.join(",")]);

  useEffect(() => {
    setSeats((prev) => {
      const next = makeSeats(count, prev, prev[0]?.provider_id || providers[0]?.id || "");
      if (next.length === prev.length && next.every((s, i) => s.provider_id)) return prev;
      return next;
    });
  }, [count, providers.length]);

  const applyGroup = (id: string) => {
    setGroupId(id);
    const group = groups.find((g) => g.id === id);
    if (!group) return;
    const filled = group.members.map((m) => ({
      name: m.name,
      provider_id: m.provider_id,
      persona: m.persona || "",
    }));
    setSeats(makeSeats(filled.length, filled, providers[0]?.id || ""));
    setCount(filled.length);
  };

  const patchSeat = (index: number, patch: Partial<SeatDraft>) => {
    setSeats((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  };

  const submit = async () => {
    if (!game) return;
    if (seats.some((s) => !s.provider_id)) {
      setError("请为每个座位选择 AI Provider");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const match = await api.createMatch({ game_id: game.id, title, seats, config: {} });
      await api.startMatch(match.id);
      onOpenMatch(match.id);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const startExisting = async (id: string) => {
    setBusy(true);
    setError("");
    try {
      await api.startMatch(id);
      onOpenMatch(id);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const removeMatch = async (id: string) => {
    try {
      await api.deleteMatch(id);
      setMatches((prev) => prev.filter((m) => m.id !== id));
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="page-title">对局大厅</div>
          <div className="page-desc">
            选择一款游戏，把多个 AI 拉进同一张牌桌。身份与手牌会独立发放，每个 AI 只看到自己该看到的信息。
          </div>
        </div>
        <div className="row gap-sm">
          <span className="chip accent">{providers.length} 个 Provider</span>
          <span className="chip green">{games.length} 种游戏</span>
          <button className="btn sm" onClick={load}>刷新</button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {!providers.length && (
        <div className="error-banner">
          还没有可用的 AI Provider。<a onClick={onGoProviders} style={{ textDecoration: "underline", cursor: "pointer" }}>前往配置</a>
        </div>
      )}

      <div className="lobby-grid">
        <div className="col" style={{ gap: 16 }}>
          <div className="card">
            <div className="section-label">1 · 选择游戏</div>
            <div className="game-grid">
              {games.map((g) => (
                <div
                  key={g.id}
                  className={`game-card ${gameId === g.id ? "selected" : ""}`}
                  onClick={() => setGameId(g.id)}
                >
                  <span className="game-emoji">{GAME_ICONS[g.id] || "🎲"}</span>
                  <h4>{g.name}</h4>
                  <p>{g.description}</p>
                  <div className="row gap-sm" style={{ marginTop: 10 }}>
                    <span className="chip">{g.allowed_counts?.length ? `${g.allowed_counts.join("/")} 人` : `${g.min_players}-${g.max_players} 人`}</span>
                  </div>
                </div>
              ))}
              {!games.length && <div className="empty">正在加载游戏列表…</div>}
            </div>
            {game && (
              <div className="row wrap mt" style={{ gap: 12 }}>
                <label className="field" style={{ width: 220 }}>
                  <span>对局名称</span>
                  <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={`${game.name} · 今晚开战`} />
                </label>
                <label className="field" style={{ width: 140 }}>
                  <span>参与人数</span>
                  <select value={count} onChange={(e) => setCount(Number(e.target.value))}>
                    {counts.map((n) => (
                      <option key={n} value={n}>{n} 人</option>
                    ))}
                  </select>
                </label>
                <label className="field" style={{ width: 240, marginLeft: "auto" }}>
                  <span>用群组快速填充</span>
                  <select value={groupId} onChange={(e) => applyGroup(e.target.value)}>
                    <option value="">不使用群组</option>
                    {groups.map((g) => (
                      <option key={g.id} value={g.id}>{g.name}（{g.members.length} 人）</option>
                    ))}
                  </select>
                </label>
              </div>
            )}
          </div>

          <div className="card">
            <div className="row" style={{ marginBottom: 12 }}>
              <div>
                <div className="section-label" style={{ marginBottom: 4 }}>2 · 配置座位</div>
                <div className="card-sub">每个座位代表一个独立 AI，可填写人设影响它的发言风格。</div>
              </div>
              <button className="btn primary right" disabled={busy || !game} onClick={submit}>
                {busy ? "正在开局…" : "创建并开始对局"}
              </button>
            </div>
            <div className="seat-editor">
              {seats.map((seat, index) => (
                <div className="seat-row" key={index}>
                  <div className="seat-badge" style={{ background: COLORS[index % COLORS.length] }}>
                    {index + 1}
                  </div>
                  <input
                    value={seat.name}
                    onChange={(e) => patchSeat(index, { name: e.target.value })}
                    placeholder={`AI ${index + 1}`}
                  />
                  <select
                    value={seat.provider_id}
                    onChange={(e) => patchSeat(index, { provider_id: e.target.value })}
                  >
                    <option value="">选择 Provider</option>
                    {providers.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}{p.model ? ` · ${p.model}` : ""}
                      </option>
                    ))}
                  </select>
                  <input
                    value={seat.persona}
                    onChange={(e) => patchSeat(index, { persona: e.target.value })}
                    placeholder="人设（可选），例如：激进、爱开玩笑"
                  />
                  <div />
                </div>
              ))}
              {!seats.length && <div className="empty">请选择游戏和人数</div>}
            </div>
            {game && (
              <details className="mt">
                <summary>查看 {game.name} 规则摘要</summary>
                <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, color: "var(--muted)", lineHeight: 1.7 }}>{game.rules}</pre>
              </details>
            )}
          </div>
        </div>

        <div className="card">
          <div className="row" style={{ marginBottom: 12 }}>
            <div>
              <div className="section-label" style={{ marginBottom: 4 }}>历史对局</div>
              <div className="card-sub">可回看事件流与每个 AI 的私有信息。</div>
            </div>
            <button className="btn ghost sm right" onClick={load}>刷新</button>
          </div>
          <div className="match-list">
            {matches.map((m) => (
              <div key={m.id} className="match-item" onClick={() => onOpenMatch(m.id)}>
                <div style={{ fontSize: 18 }}>{GAME_ICONS[m.game_id] || "🎲"}</div>
                <div className="flex1">
                  <div className="match-title">{m.title}</div>
                  <div className="match-meta">
                    {(m.seats || []).map((s) => s.name).join(" · ")}
                  </div>
                </div>
                <span className={`chip ${m.status === "running" ? "green" : m.status === "finished" ? "accent" : ""}`}>
                  {STATUS_LABEL[m.status] || m.status}
                </span>
                {m.status === "created" && (
                  <button
                    className="btn sm primary"
                    onClick={(e) => {
                      e.stopPropagation();
                      startExisting(m.id);
                    }}
                  >
                    开始
                  </button>
                )}
                <button
                  className="btn sm ghost"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeMatch(m.id);
                  }}
                >
                  删除
                </button>
              </div>
            ))}
            {!matches.length && <div className="empty">还没有对局，先创建一局吧。</div>}
          </div>
        </div>
      </div>
    </div>
  );
}
