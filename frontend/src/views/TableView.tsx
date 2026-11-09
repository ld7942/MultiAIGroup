import { useEffect, useMemo, useRef, useState } from "react";
import { api, WS_BASE } from "../api";
import type {
  AgentLog,
  GameEvent,
  MatchDetail,
  MatchSeat,
  Snapshot,
} from "../types";

const PHASE_LABELS: Record<string, string> = {
  night_start: "天黑请闭眼",
  wolf_chat: "狼人密谈",
  wolf_vote: "狼人选择目标",
  wolf_vote_pending: "狼人投票中",
  seer: "预言家查验",
  witch: "女巫行动",
  resolve_night: "夜晚结算",
  dawn_hunter: "猎人开枪",
  post_night: "天亮了",
  day_discussion: "白天发言",
  day_vote: "白天投票",
  exile_hunter: "猎人开枪",
  post_day: "入夜",
  bidding: "叫地主",
  playing: "出牌",
  turn_start: "回合开始",
  play: "出牌阶段",
  dodge_wait: "等待【闪】",
  duel_wait: "决斗响应",
  dying_wait: "濒死求桃",
  end_turn: "回合结束",
  finished: "对局结束",
};

const STATUS_LABEL: Record<string, string> = {
  created: "待开始",
  running: "进行中",
  finished: "已结束",
  stopped: "已停止",
  interrupted: "已中断",
  error: "异常",
};

const KEY_LABELS: Record<string, string> = {
  role: "身份",
  role_label: "身份",
  camp: "阵营",
  alive: "存活",
  seat_no: "座位号",
  hand: "手牌",
  hand_count: "手牌数",
  teammates: "狼队友",
  checks: "查验记录",
  antidote: "解药",
  poison: "毒药",
  win_goal: "胜利目标",
  all_roles: "全员身份",
  landlord: "地主",
  teammate: "队友",
  bottom: "底牌",
  all_hands: "全员手牌",
  hp: "体力",
  max_hp: "体力上限",
  lord: "主公",
  reads: "身份预测",
};

const EVENT_ICONS: Record<string, string> = {
  game_start: "🏁",
  role_assigned: "🎭",
  phase: "⏱",
  night: "🌙",
  dawn: "🌅",
  speech: "💬",
  vote: "🗳",
  death: "☠",
  game_over: "🏆",
  deal: "🎴",
  play: "🃏",
  pass: "⏭",
  draw: "🎴",
  damage: "⚔",
  heal: "✚",
  agent_reads: "🔮",
  agent_notes: "🧠",
};

function mergeEvents(prev: GameEvent[], next: GameEvent[]): GameEvent[] {
  const map = new Map<number, GameEvent>();
  prev.forEach((ev) => map.set(ev.seq, ev));
  next.forEach((ev) => map.set(ev.seq, ev));
  return Array.from(map.values()).sort((a, b) => a.seq - b.seq);
}

function isRedCard(label: string): boolean {
  return label.includes("♥") || label.includes("♦");
}

function CardChips({ cards }: { cards: any[] }) {
  return (
    <div className="tag-list">
      {cards.map((card, index) => (
        <span
          key={card.id || index}
          className={`card-chip ${isRedCard(String(card.label || "")) ? "red" : ""}`}
          title={String(card.id || "")}
        >
          {card.label}
        </span>
      ))}
      {!cards.length && <span className="muted small">无</span>}
    </div>
  );
}

function ValueView({ field, value }: { field: string; value: any }) {
  if (Array.isArray(value)) {
    if (value.length && typeof value[0] === "object" && value[0] !== null && "label" in value[0]) {
      return <CardChips cards={value} />;
    }
    if (value.length && typeof value[0] === "string") {
      return (
        <div className="tag-list">
          {value.map((item) => (
            <span className="chip" key={item}>{item}</span>
          ))}
        </div>
      );
    }
    if (!value.length) return <span className="muted small">无</span>;
  }
  if (value !== null && typeof value === "object") {
    if (field === "reads") return <ReadsList reads={value} />;
    return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>;
  }
  if (typeof value === "boolean") {
    return <span className={`chip ${value ? "green" : "red"}`}>{value ? "是" : "否"}</span>;
  }
  if (value === null || value === undefined || value === "") {
    return <span className="muted small">—</span>;
  }
  return <span>{String(value)}</span>;
}

function ReadsList({ reads }: { reads: any }) {
  const list = Array.isArray(reads) ? reads : [];
  if (!list.length) return <span className="muted small">该 AI 尚未提交身份预测</span>;
  return (
    <div className="reads">
      {list.map((read: any, index: number) => {
        const confidence = Number(read.confidence ?? 0);
        return (
          <div className="read-item" key={index}>
            <div className="read-head">
              <span className="chip accent">{read.role || "?"}</span>
              <span className="small">{read.name || read.seat}</span>
              <span className="muted tiny right">{Number.isFinite(confidence) ? `${Math.round(confidence * 100)}%` : ""}</span>
            </div>
            {Number.isFinite(confidence) && confidence > 0 && (
              <div className="confidence"><i style={{ width: `${Math.min(100, Math.max(4, confidence * 100))}%` }} /></div>
            )}
            {read.reason && <div className="muted tiny" style={{ marginTop: 4 }}>{read.reason}</div>}
          </div>
        );
      })}
    </div>
  );
}

function PrivatePanel({ data }: { data: Record<string, any> }) {
  const entries = Object.entries(data);
  if (!entries.length) return <div className="muted small">暂无私有信息</div>;
  const role = data.role_label || data.role;
  return (
    <div>
      {role && (
        <div className="row" style={{ marginBottom: 10 }}>
          <span className="chip warn" style={{ fontSize: 12.5, padding: "5px 12px" }}>{role}</span>
          {data.camp && <span className="chip">{data.camp}</span>}
          {data.win_goal && <span className="muted tiny">{data.win_goal}</span>}
        </div>
      )}
      <dl className="kv">
        {entries
          .filter(([key]) => !["role", "role_label", "camp", "win_goal", "notes"].includes(key))
          .map(([key, value]) => (
            <div key={key} style={{ display: "contents" }}>
              <dt>{KEY_LABELS[key] || key}</dt>
              <dd style={{ whiteSpace: "normal" }}>
                <ValueView field={key} value={value} />
              </dd>
            </div>
          ))}
      </dl>
    </div>
  );
}

function LogsModal({
  matchId,
  seats,
  initialSeat,
  onClose,
}: {
  matchId: string;
  seats: MatchSeat[];
  initialSeat: string;
  onClose: () => void;
}) {
  const [seatId, setSeatId] = useState(initialSeat);
  const [logs, setLogs] = useState<AgentLog[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    api
      .logs(matchId, seatId || undefined)
      .then((rows) => alive && setLogs(rows))
      .catch((exc) => alive && setError((exc as Error).message));
    return () => {
      alive = false;
    };
  }, [matchId, seatId]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="card-title">AI 思考记录</div>
            <div className="card-sub">展示每个 AI 收到的提示词、原始输出与校验结果（从新到旧）。</div>
          </div>
          <div className="row right">
            <select style={{ width: 160 }} value={seatId} onChange={(e) => setSeatId(e.target.value)}>
              <option value="">全部座位</option>
              {seats.map((seat) => (
                <option key={seat.id} value={seat.id}>{seat.name}</option>
              ))}
            </select>
            <button className="btn sm ghost" onClick={onClose}>关闭</button>
          </div>
        </div>
        <div className="modal-body">
          {error && <div className="error-banner">{error}</div>}
          {logs.map((log) => {
            const seat = seats.find((s) => s.id === log.seat_id);
            return (
              <div className={`log-card ${log.error ? "error" : ""}`} key={log.id}>
                <div className="log-head">
                  <span className="chip accent">{seat?.name || log.seat_id}</span>
                  <span className="chip">第 {log.attempt} 次尝试</span>
                  <span className="muted tiny">{log.provider}</span>
                  {log.error && <span className="chip red">{log.error.slice(0, 80)}</span>}
                </div>
                <details>
                  <summary>原始输出</summary>
                  <pre>{log.raw_response || "（空）"}</pre>
                </details>
                <details>
                  <summary>发送的上下文</summary>
                  <pre>{log.user_prompt}</pre>
                </details>
              </div>
            );
          })}
          {!logs.length && <div className="empty">还没有调用记录</div>}
        </div>
      </div>
    </div>
  );
}

export default function TableView({ matchId, onBack }: { matchId: string; onBack: () => void }) {
  const [match, setMatch] = useState<MatchDetail | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [privates, setPrivates] = useState<Record<string, Record<string, any>>>({});
  const [events, setEvents] = useState<GameEvent[]>([]);
  const [status, setStatus] = useState("loading");
  const [perspective, setPerspective] = useState("god");
  const [selected, setSelected] = useState("");
  const [logsOpen, setLogsOpen] = useState(false);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      ws = new WebSocket(`${WS_BASE}/ws/matches/${matchId}`);
      ws.onopen = () => setConnected(true);
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "snapshot") {
            setMatch(data.match as MatchDetail);
            setStatus(data.status || "created");
            setSnapshot(data.state?.game_id ? data.state : null);
            setPrivates(data.privates || {});
            setEvents(mergeEvents([], data.events || []));
            setSelected((prev) => prev || data.match?.seats?.[0]?.id || "");
            setError("");
          } else if (data.type === "events") {
            setEvents((prev) => mergeEvents(prev, data.events || []));
          } else if (data.type === "state") {
            if (data.state) setSnapshot(data.state);
            if (data.privates) setPrivates(data.privates);
          } else if (data.type === "match_status") {
            setStatus(data.status);
            if (data.state) setSnapshot(data.state);
            setMatch((prev) =>
              prev ? { ...prev, result: data.result || prev.result } : prev,
            );
            if (data.status === "finished" || data.status === "error") {
              api.match(matchId).then((detail) => {
                setMatch(detail);
                if (detail.privates) setPrivates(detail.privates);
              }).catch(() => undefined);
            }
          } else if (data.type === "error") {
            setError(data.message || "连接出错");
          }
        } catch {
          /* ignore malformed */
        }
      };
      ws.onerror = () => setError("WebSocket 连接失败，请确认后端已启动");
      ws.onclose = () => {
        setConnected(false);
        if (!closed) timer = setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, [matchId]);

  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  const seats = match?.seats || [];
  const seatMap = useMemo(() => {
    const map: Record<string, MatchSeat> = {};
    seats.forEach((seat) => (map[seat.id] = seat));
    return map;
  }, [seats]);

  const publicSeats = useMemo(() => {
    const list = snapshot?.public_state?.seats;
    const map: Record<string, any> = {};
    if (Array.isArray(list)) list.forEach((item: any) => (map[item.id] = item));
    return map;
  }, [snapshot]);

  const activeSeatId = perspective === "god" ? selected || seats[0]?.id || "" : perspective;
  const activeSeat = seatMap[activeSeatId];
  const actingSeats = useMemo(
    () => new Set((snapshot?.requests || []).map((req) => req.seat_id)),
    [snapshot],
  );

  const visibleEvents = useMemo(() => {
    if (perspective === "god") return events;
    return events.filter(
      (ev) =>
        ev.visibility.scope === "public" ||
        (ev.visibility.seats || []).includes(perspective),
    );
  }, [events, perspective]);

  const latestReads = useMemo(() => {
    const map: Record<string, any[]> = {};
    events.forEach((ev) => {
      if (ev.type === "agent_reads" && ev.payload?.reads && ev.seat_id) {
        map[ev.seat_id] = ev.payload.reads;
      }
    });
    return map;
  }, [events]);

  const result = snapshot?.result || match?.result || null;
  const finished = snapshot?.finished || status === "finished";
  const phase = snapshot?.phase || (snapshot?.public_state as any)?.phase || "";
  const round = snapshot?.round ?? (snapshot?.public_state as any)?.round ?? 0;

  const stop = async () => {
    try {
      await api.stopMatch(matchId);
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  const start = async () => {
    try {
      await api.startMatch(matchId);
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  return (
    <div className="table-page">
      <div className="table-head">
        <button className="btn sm ghost" onClick={onBack}>← 大厅</button>
        <div>
          <div className="table-title">{match?.title || "对局"}</div>
          <div className="muted tiny">{match?.game_id} · {seats.length} 名玩家</div>
        </div>
        <span className={`chip ${status === "running" ? "green" : status === "finished" ? "accent" : status === "error" ? "red" : ""}`}>
          {STATUS_LABEL[status] || status}
        </span>
        {snapshot && (
          <>
            <span className="chip">第 {round} 轮</span>
            <span className="chip accent">{PHASE_LABELS[phase] || phase || "—"}</span>
          </>
        )}
        {!connected && <span className="chip red">连接中…</span>}
        <div className="row right gap-sm">
          {status === "created" && <button className="btn sm primary" onClick={start}>开始对局</button>}
          {status === "running" && <button className="btn sm danger" onClick={stop}>停止对局</button>}
          <button className="btn sm" onClick={() => setLogsOpen(true)}>AI 思考</button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="table-layout">
        <div className="table-main">
          <div className="table-stage">
            <div className="table-center">
              <div className="center-game">{PHASE_LABELS[phase] || phase || "准备中"}</div>
              <div className="center-phase">
                {finished
                  ? String((result as any)?.winner_label || (result as any)?.winner || "对局结束")
                  : (snapshot?.requests?.length
                    ? `${snapshot.requests.map((req) => seatMap[req.seat_id]?.name || req.seat_id).join("、")} 行动中`
                    : "等待推进")}
              </div>
              <div className="center-round">第 {round} 轮</div>
              <div className="center-status">
                {finished && (result as any)?.reason && (
                  <div className="muted">{String((result as any).reason)}</div>
                )}
                {!finished && (snapshot?.requests || []).slice(0, 3).map((req) => (
                  <div key={req.id} className="muted">{req.title}</div>
                ))}
              </div>
            </div>

            {seats.map((seat, index) => {
              const angle = (-90 + (360 / Math.max(seats.length, 1)) * index) * (Math.PI / 180);
              const left = 50 + Math.cos(angle) * 36;
              const top = 50 + Math.sin(angle) * 33;
              const info = publicSeats[seat.id] || {};
              const dead = info.alive === false;
              return (
                <div
                  key={seat.id}
                  className={`seat-card ${activeSeatId === seat.id ? "selected" : ""} ${dead ? "dead" : ""} ${actingSeats.has(seat.id) ? "acting" : ""}`}
                  style={{ left: `${left}%`, top: `${top}%` }}
                  onClick={() => {
                    setSelected(seat.id);
                    setPerspective(seat.id);
                  }}
                  title={`查看 ${seat.name} 的视角`}
                >
                  <div className="seat-top">
                    <span className="seat-dot" style={{ background: seat.color || "#7c9cff" }} />
                    <div className="flex1">
                      <div className="seat-name">{seat.name}</div>
                      <div className="seat-provider">{seat.provider_name || seat.provider_id}{seat.model ? ` · ${seat.model}` : ""}</div>
                    </div>
                    {perspective === seat.id && <span className="seat-you">当前视角</span>}
                  </div>
                  <div className="seat-stats">
                    <span className="stat">#{info.seat_no ?? index + 1}</span>
                    {info.hp !== undefined && <span className="stat hp">❤ {info.hp}{info.max_hp ? `/${info.max_hp}` : ""}</span>}
                    {info.hand_count !== undefined && <span className="stat cards">🂠 {info.hand_count}</span>}
                    {info.role && <span className="stat role">{info.role}</span>}
                    {dead && <span className="stat">已出局</span>}
                    {perspective === "god" && privates[seat.id]?.role_label && (
                      <span className="stat role">{privates[seat.id].role_label}</span>
                    )}
                    {latestReads[seat.id]?.length > 0 && (
                      <span className="stat">🔮 {latestReads[seat.id].length}</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="card feed">
            <div className="feed-head">
              <span className="card-title">事件流</span>
              <span className="muted tiny">{visibleEvents.length} 条</span>
              <div className="perspective right">
                <button className={perspective === "god" ? "active" : ""} onClick={() => setPerspective("god")}>上帝视角</button>
                {seats.map((seat) => (
                  <button
                    key={seat.id}
                    className={perspective === seat.id ? "active" : ""}
                    onClick={() => {
                      setPerspective(seat.id);
                      setSelected(seat.id);
                    }}
                  >
                    {seat.name} 视角
                  </button>
                ))}
              </div>
            </div>
            <div className="feed-list" ref={feedRef}>
              {visibleEvents.map((ev) => {
                const scope = ev.visibility?.scope || "public";
                const seat = ev.seat_id ? seatMap[ev.seat_id] : null;
                return (
                  <div
                    key={ev.seq}
                    className={`feed-item ${scope !== "public" ? scope : ""} ${["phase", "game_start", "night", "dawn"].includes(ev.type) ? "system" : ""}`}
                  >
                    <span className="feed-seq">{ev.seq}</span>
                    <div className="feed-text">
                      <span style={{ marginRight: 6 }}>{EVENT_ICONS[ev.type] || "•"}</span>
                      {ev.text}
                      <div className="feed-meta">
                        <span className="feed-round">R{ev.round} · {PHASE_LABELS[ev.phase] || ev.phase}</span>
                        {scope !== "public" && (
                          <span className="chip warn" style={{ fontSize: 9.5, padding: "1px 6px" }}>
                            {scope === "private" ? `私密${seat ? ` · ${seat.name}` : ""}` : "阵营可见"}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
              {!visibleEvents.length && <div className="empty">暂无事件</div>}
            </div>
          </div>
        </div>

        <div className="inspector">
          {finished && (
            <div className="result-banner">
              <strong>对局结束：{String((result as any)?.winner_label || (result as any)?.winner || "无结果")}</strong>
              <div className="muted small" style={{ marginTop: 4 }}>
                {String((result as any)?.reason || (result as any)?.summary || "")}
              </div>
            </div>
          )}

          <div className="card inspector-card">
            <div className="row" style={{ marginBottom: 10 }}>
              <div>
                <div className="card-title">
                  {perspective === "god" ? "私有信息（上帝视角）" : `${activeSeat?.name || "AI"} 的私有信息`}
                </div>
                <div className="card-sub">
                  {perspective === "god" ? "本地展示全部身份与手牌，仅你可见。" : "正在以该 AI 的可见范围查看。"}
                </div>
              </div>
            </div>
            {activeSeat && (
              <div className="row" style={{ marginBottom: 10 }}>
                <span className="seat-dot" style={{ background: activeSeat.color || "#7c9cff" }} />
                <span className="small" style={{ fontWeight: 600 }}>{activeSeat.name}</span>
                <span className="muted tiny">{activeSeat.provider_name || activeSeat.provider_id}</span>
              </div>
            )}
            {activeSeat && activeSeat.persona && (
              <div className="muted tiny mb">人设：{activeSeat.persona}</div>
            )}
            <PrivatePanel data={privates[activeSeatId] || {}} />
          </div>

          <div className="card inspector-card">
            <div className="card-title" style={{ marginBottom: 4 }}>身份预测</div>
            <div className="card-sub" style={{ marginBottom: 10 }}>
              AI 在每次行动前提交的推断（来自模型输出 reads）。
            </div>
            <ReadsList reads={latestReads[activeSeatId]} />
          </div>

          <div className="card inspector-card">
            <div className="card-title" style={{ marginBottom: 10 }}>待行动</div>
            {(snapshot?.requests || []).map((req) => (
              <div className="read-item" key={req.id} style={{ marginBottom: 8 }}>
                <div className="row">
                  <span className="chip accent">{seatMap[req.seat_id]?.name || req.seat_id}</span>
                  <span className="small">{req.title}</span>
                </div>
                <div className="muted tiny" style={{ marginTop: 4 }}>{req.instruction}</div>
                <div className="tag-list" style={{ marginTop: 6 }}>
                  {req.options.slice(0, 8).map((option) => (
                    <span className="chip" key={option.id}>{option.label}</span>
                  ))}
                  {req.options.length > 8 && <span className="chip">+{req.options.length - 8}</span>}
                </div>
              </div>
            ))}
            {!(snapshot?.requests || []).length && (
              <div className="muted small">{finished ? "对局已结束" : "等待引擎推进…"}</div>
            )}
          </div>
        </div>
      </div>

      {logsOpen && (
        <LogsModal
          matchId={matchId}
          seats={seats}
          initialSeat={activeSeatId}
          onClose={() => setLogsOpen(false)}
        />
      )}
    </div>
  );
}
