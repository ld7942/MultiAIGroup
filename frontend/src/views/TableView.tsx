import { useEffect, useMemo, useRef, useState } from "react";
import { api, WS_BASE } from "../api";
import { isTauri, playVoice, speechStatus, speechSupported, unlockSpeech } from "../speech";
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

const GAME_LABELS: Record<string, string> = {
  werewolf: "狼人杀",
  doudizhu: "斗地主",
  sanguosha: "三国杀",
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
  game: "游戏",
  round: "回合",
  phase: "阶段",
  stage: "阶段",
  day: "天数",
  alive_count: "存活人数",
  last_night: "昨夜结果",
  deaths: "死亡",
  saved: "已使用解药",
  killed: "被袭击",
  last_play: "最近出牌",
  current_bid: "当前叫分",
  bids: "叫分记录",
  bid: "叫分",
  turn: "当前回合",
  seat: "座位",
  cards: "牌",
  labels: "牌面",
  kind: "牌型",
  rank: "大小",
  length: "张数",
  check: "查验",
  result: "结果",
  target: "目标",
  source: "来源",
  action: "动作",
  text: "内容",
  user: "使用者",
  card: "卡牌",
  items: "个人道具",
  uses: "剩余次数",
  description: "说明",
  recent_play: "桌面最近出牌",
  discard_count: "弃牌堆",
  deck_count: "牌堆剩余",
};

const KIND_LABELS: Record<string, string> = {
  single: "单张",
  pair: "对子",
  triple: "三张",
  triple_single: "三带一",
  triple_pair: "三带二",
  straight: "顺子",
  straight_pairs: "连对",
  airplane: "飞机",
  airplane_single: "飞机带单",
  airplane_pair: "飞机带对",
  four_two_single: "四带二",
  four_two_pair: "四带两对",
  bomb: "炸弹",
  rocket: "王炸",
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

const MAX_VALUE_DEPTH = 3;

/** 牌桌中央的“最近出牌”，统一读取 public_state.last_play / recent_play。 */
function CenterPile({
  play,
  discardCount,
  names,
}: {
  play: Record<string, any>;
  discardCount?: number;
  names: Record<string, string>;
}) {
  const labels: string[] = Array.isArray(play.labels)
    ? play.labels.map((item: any) => (typeof item === "string" ? item : String(item?.label ?? "")))
    : Array.isArray(play.cards)
      ? play.cards.map((item: any) => (typeof item === "string" ? item : String(item?.label ?? "")))
      : play.card
        ? [String(play.card)]
        : [];
  if (!labels.length) return null;
  const actor = names[play.seat] || play.name || "";
  const target = play.target ? names[play.target] || String(play.target) : "";
  const rawKind = play.kind ? String(play.kind) : "";
  const kind = KIND_LABELS[rawKind] || rawKind;
  const showKind = kind && !(labels.length === 1 && labels[0] === kind);
  return (
    <div className="center-pile">
      <div className="pile-meta">
        {actor}
        {target ? ` → ${target}` : ""}
        {showKind ? ` · ${kind}` : ""}
      </div>
      <div className="pile-cards">
        {labels.map((label, index) => (
          <span className={`pile-card ${isRedCard(label) ? "red" : ""}`} key={`${label}-${index}`}>
            {label}
          </span>
        ))}
      </div>
      {typeof discardCount === "number" && discardCount > 0 && (
        <div className="pile-discard">弃牌堆 {discardCount} 张</div>
      )}
    </div>
  );
}

function scalarText(value: any, key: string, names: Record<string, string>): string {
  if (typeof value === "boolean") return `${KEY_LABELS[key] || key}:${value ? "是" : "否"}`;
  const text = String(value);
  return `${KEY_LABELS[key] || key}:${names[text] || text}`;
}

/** 数组里的对象做紧凑摘要，绝不把原始 JSON 直接丢给用户。 */
function ObjectSummary({ data, names }: { data: Record<string, any>; names: Record<string, string> }) {
  const chips = Object.entries(data)
    .filter(([key, value]) => !["id", "name", "color", "seat", "seat_no"].includes(key))
    .map(([key, value]) => {
      if (value === null || value === undefined || value === "") return null;
      if (typeof value === "object") {
        if (Array.isArray(value)) {
          const parts = value.map((item) =>
            item && typeof item === "object"
              ? String(item.name || item.label || item.role || "对象")
              : names[String(item)] || String(item),
          );
          return <span className="chip" key={key}>{KEY_LABELS[key] || key}:{parts.join(" / ") || "无"}</span>;
        }
        return null;
      }
      return <span className="chip" key={key}>{scalarText(value, key, names)}</span>;
    })
    .filter(Boolean);
  if (!chips.length) return <span className="muted small">—</span>;
  return <div className="tag-list">{chips}</div>;
}

function ObjectView({ data, names, depth }: { data: Record<string, any>; names: Record<string, string>; depth: number }) {
  const entries = Object.entries(data).filter(([key, value]) => {
    if (value === undefined) return false;
    // 出牌记录同时有 cards(内部 id) 和 labels(牌面)，只展示牌面。
    if (key === "cards" && Array.isArray((data as any).labels)) return false;
    return true;
  });
  if (!entries.length) return <span className="muted small">—</span>;
  return (
    <dl className="kv">
      {entries.map(([key, value]) => (
        <div key={key} style={{ display: "contents" }}>
          <dt>{KEY_LABELS[key] || key}</dt>
          <dd style={{ whiteSpace: "normal" }}>
            <ValueView field={key} value={value} names={names} depth={depth + 1} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function ObjectList({ items, names }: { items: any[]; names: Record<string, string> }) {
  return (
    <div className="reads">
      {items.map((item, index) => {
        const title = item?.name || names[item?.seat || item?.id || ""] || `#${index + 1}`;
        return (
          <div className="read-item" key={`${title}-${index}`}>
            <div className="read-head">
              <span className="small" style={{ fontWeight: 600 }}>{title}</span>
              {item?.role && <span className="chip accent">{item.role}</span>}
              {item?.camp && <span className="chip">{item.camp}</span>}
              {typeof item?.alive === "boolean" && (
                <span className={`chip ${item.alive ? "green" : "red"}`}>{item.alive ? "存活" : "出局"}</span>
              )}
              {item?.seat_no !== undefined && <span className="muted tiny">座位 {item.seat_no}</span>}
            </div>
            <div style={{ marginTop: 6 }}>
              <ObjectSummary data={item || {}} names={names} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** 把任意嵌套结构渲染成可读内容；未知字段也使用键值对，不会退回原始 JSON。 */
function ValueView({
  field,
  value,
  names,
  depth = 0,
}: {
  field: string;
  value: any;
  names: Record<string, string>;
  depth?: number;
}) {
  const seatName = (id: string) => names[id] || id;
  if (value === null || value === undefined || value === "") {
    return <span className="muted small">—</span>;
  }
  if (typeof value === "boolean") {
    return <span className={`chip ${value ? "green" : "red"}`}>{value ? "是" : "否"}</span>;
  }
  if (typeof value === "string") {
    if (field === "phase" || field === "stage") {
      return <span>{PHASE_LABELS[value] || value}</span>;
    }
    if (field === "game") {
      const gameName = GAME_LABELS[value] || value;
      return <span>{gameName}</span>;
    }
    return <span>{seatName(value)}</span>;
  }
  if (typeof value === "number") {
    return <span>{value}</span>;
  }
  if (Array.isArray(value)) {
    if (!value.length) return <span className="muted small">无</span>;
    if (value.every((item) => item !== null && typeof item === "object" && "label" in item)) {
      return <CardChips cards={value} />;
    }
    if (value.every((item) => item === null || typeof item !== "object")) {
      return (
        <div className="tag-list">
          {value.map((item, index) => (
            <span className="chip" key={`${String(item)}-${index}`}>{seatName(String(item))}</span>
          ))}
        </div>
      );
    }
    if (value.every((item) => item !== null && typeof item === "object")) {
      return <ObjectList items={value} names={names} />;
    }
    return (
      <div className="tag-list">
        {value.map((item, index) => (
          <span className="chip" key={index}>{seatName(String(item))}</span>
        ))}
      </div>
    );
  }
  if (typeof value === "object") {
    if (field === "reads") return <ReadsList reads={value} />;
    if (depth >= MAX_VALUE_DEPTH) return <ObjectSummary data={value} names={names} />;
    return <ObjectView data={value} names={names} depth={depth} />;
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

function PrivatePanel({ data, names }: { data: Record<string, any>; names: Record<string, string> }) {
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
      {Array.isArray(data.items) && data.items.length > 0 && (
        <div className="tag-list" style={{ marginBottom: 10 }}>
          {data.items.map((item: any) => (
            <span
              className={`chip ${item.available ? "green" : "red"}`}
              key={item.key || item.label}
            >
              {item.label}
              {item.available === false ? "（不可用）" : ""}
            </span>
          ))}
        </div>
      )}
      <dl className="kv">
        {entries
          .filter(([key]) => !["role", "role_label", "camp", "win_goal", "notes", "items"].includes(key))
          .map(([key, value]) => (
            <div key={key} style={{ display: "contents" }}>
              <dt>{KEY_LABELS[key] || key}</dt>
              <dd style={{ whiteSpace: "normal" }}>
                <ValueView field={key} value={value} names={names} />
              </dd>
            </div>
          ))}
      </dl>
    </div>
  );
}

function GodPanel({
  snapshot,
  privates,
  seats,
  reads,
  result,
  names,
}: {
  snapshot: Snapshot | null;
  privates: Record<string, Record<string, any>>;
  seats: MatchSeat[];
  reads: Record<string, any[]>;
  result: Record<string, any> | null;
  names: Record<string, string>;
}) {
  const publicState = (snapshot?.public_state || {}) as Record<string, any>;
  // 桌面最近出牌已在牌桌中央展示，这里不重复。
  const entries = Object.entries(publicState).filter(
    ([key]) => key !== "seats" && key !== "recent_play",
  );
  const publicSeats: any[] = Array.isArray(publicState.seats) ? publicState.seats : [];
  const publicById = new Map(publicSeats.map((item) => [item.id, item]));
  const review = (result?.review || {}) as Record<string, string[]>;
  const reviewSeats = Object.keys(review);
  return (
    <>
      <div className="card inspector-card">
        <div className="card-title">公共信息（上帝视角）</div>
        <div className="card-sub" style={{ marginBottom: 10 }}>
          所有玩家都能看到的状态；私密身份见下方全员身份表。
        </div>
        {entries.length ? (
          <dl className="kv">
            {entries.map(([key, value]) => (
              <div key={key} style={{ display: "contents" }}>
                <dt>{KEY_LABELS[key] || key}</dt>
                <dd style={{ whiteSpace: "normal" }}>
                  <ValueView field={key} value={value} names={names} />
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <div className="muted small">暂无公共状态</div>
        )}
      </div>

      <div className="card inspector-card">
        <div className="card-title" style={{ marginBottom: 10 }}>全员身份与状态</div>
        <div className="reads">
          {seats.map((seat) => {
            const priv = privates[seat.id] || {};
            const pub = publicById.get(seat.id) || {};
            const role = priv.role_label || priv.role || "—";
            const alive = pub.alive ?? priv.alive;
            const hp = pub.hp ?? priv.hp;
            const handCount = pub.hand_count ?? priv.hand_count;
            return (
              <div className="read-item" key={seat.id}>
                <div className="read-head">
                  <span className="seat-dot" style={{ background: seat.color || "#7c9cff" }} />
                  <span className="small" style={{ fontWeight: 600 }}>{seat.name}</span>
                  <span className="chip warn">{role}</span>
                  {priv.camp && <span className="chip">{priv.camp}</span>}
                  {alive === false ? (
                    <span className="chip red right">已出局</span>
                  ) : alive === true ? (
                    <span className="chip accent right">存活</span>
                  ) : null}
                </div>
                {(hp !== undefined || handCount !== undefined) && (
                  <div className="muted tiny" style={{ marginTop: 4 }}>
                    {hp !== undefined && <>体力 {String(hp)}　</>}
                    {handCount !== undefined && <>手牌 {String(handCount)}</>}
                  </div>
                )}
                {Array.isArray(priv.items) && priv.items.length > 0 && (
                  <div className="tag-list" style={{ marginTop: 6 }}>
                    {priv.items.map((item: any) => (
                      <span
                        className={`chip ${item.available ? "green" : "red"}`}
                        key={item.key || item.label}
                        title={item.available ? "可用" : "已使用 / 不可用"}
                      >
                        {item.label}
                        {item.available === false ? "（不可用）" : ""}
                      </span>
                    ))}
                  </div>
                )}
                {Array.isArray(priv.hand) && priv.hand.length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    <div className="muted tiny" style={{ marginBottom: 3 }}>手牌</div>
                    <CardChips cards={priv.hand} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="card inspector-card">
        <div className="card-title" style={{ marginBottom: 4 }}>各 AI 身份预测</div>
        <div className="card-sub" style={{ marginBottom: 10 }}>
          每个 AI 最近一次提交的概率判断，用来观察它们是否在“盘逻辑”。
        </div>
        {seats.map((seat) => {
          const list = reads[seat.id] || [];
          if (!list.length) return null;
          return (
            <div className="read-item" key={seat.id} style={{ marginBottom: 8 }}>
              <div className="read-head">
                <span className="small" style={{ fontWeight: 600 }}>{seat.name}</span>
                <span className="muted tiny right">{list.length} 条</span>
              </div>
              <div className="tag-list" style={{ marginTop: 4 }}>
                {list.slice(0, 3).map((read: any, index: number) => (
                  <span className="chip accent" key={index}>
                    {read.name || read.seat || "?"}: {read.role || "?"}
                    {read.confidence != null ? ` ${Math.round(Number(read.confidence) * 100)}%` : ""}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
        {!seats.some((seat) => (reads[seat.id] || []).length) && (
          <div className="muted small">尚无身份预测</div>
        )}
      </div>

      {reviewSeats.length > 0 && (
        <div className="card inspector-card">
          <div className="card-title" style={{ marginBottom: 4 }}>本局复盘（已写入 RAG）</div>
          <div className="card-sub" style={{ marginBottom: 10 }}>
            对局结束后自动压缩上下文，提炼成下一局可检索的技巧。
          </div>
          {reviewSeats.map((seatId) => (
            <div className="read-item" key={seatId} style={{ marginBottom: 8 }}>
              <div className="read-head">
                <span className="small" style={{ fontWeight: 600 }}>{names[seatId] || seatId}</span>
              </div>
              <ul className="muted tiny" style={{ margin: "4px 0 0 16px" }}>
                {(review[seatId] || []).map((text, index) => (
                  <li key={index}>{text}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </>
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
  const [readsState, setReadsState] = useState<Record<string, any[]>>({});
  const [events, setEvents] = useState<GameEvent[]>([]);
  const [status, setStatus] = useState("loading");
  const [perspective, setPerspective] = useState("god");
  const [selected, setSelected] = useState("");
  const [logsOpen, setLogsOpen] = useState(false);
  const [nowTs, setNowTs] = useState(() => Date.now());
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const [muted, setMuted] = useState(() => {
    try {
      return localStorage.getItem("voice.muted") === "1";
    } catch {
      return false;
    }
  });
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const mutedRef = useRef(muted);
  const feedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    mutedRef.current = muted;
  }, [muted]);

  // 发言气泡只保留最近一段时间，需要每秒刷新一次过期判断。
  useEffect(() => {
    const timer = setInterval(() => setNowTs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    api.voice().then((cfg) => setVoiceEnabled(!!cfg.enabled)).catch(() => undefined);
  }, []);

  // 浏览器要求先有用户手势才允许自动朗读；首次点击页面时解锁一次。
  useEffect(() => {
    const unlock = () => unlockSpeech();
    window.addEventListener("pointerdown", unlock, { once: true, passive: true });
    return () => window.removeEventListener("pointerdown", unlock);
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      ws = new WebSocket(`${WS_BASE}/ws/matches/${matchId}`);
      ws.onopen = () => {
        setConnected(true);
        // 桌面 WebView2 可能完全没有浏览器语音引擎，通知后端本局改用系统语音。
        // 部分环境音色异步加载，先立即判断一次，1.5 秒后再补一次。
        const askFallback = () => {
          const status = speechStatus();
          // 桌面 WebView2 即使报告有音色也可能无声，直接使用后端系统语音。
          if (!isTauri() && status.supported && status.voices > 0) return false;
          try {
            ws?.send(JSON.stringify({ type: "voice_fallback" }));
          } catch {
            /* ignore */
          }
          return true;
        };
        if (!askFallback()) {
          setTimeout(() => {
            if (ws?.readyState === WebSocket.OPEN) askFallback();
          }, 1500);
        }
      };
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "snapshot") {
            setMatch(data.match as MatchDetail);
            setStatus(data.status || "created");
            setSnapshot(data.state?.game_id ? data.state : null);
            setPrivates(data.privates || {});
            if (data.reads) setReadsState(data.reads);
            setEvents(mergeEvents([], data.events || []));
            setSelected((prev) => prev || data.match?.seats?.[0]?.id || "");
            setError("");
          } else if (data.type === "events") {
            setEvents((prev) => mergeEvents(prev, data.events || []));
          } else if (data.type === "state") {
            if (data.state) setSnapshot(data.state);
            if (data.privates) setPrivates(data.privates);
            if (data.reads) setReadsState(data.reads);
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
          } else if (data.type === "voice") {
            const finish = () => {
              try {
                ws?.send(JSON.stringify({ type: "speech_done", speech_id: data.speech_id }));
              } catch {
                /* ignore */
              }
            };
            if (mutedRef.current) finish();
            else playVoice(data, finish);
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
      if (typeof window !== "undefined") window.speechSynthesis?.cancel();
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

  const seatNames = useMemo(() => {
    const map: Record<string, string> = {};
    seats.forEach((seat) => (map[seat.id] = seat.name));
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

  // 每个座位只保留最后一句发言，用于牌桌上的对话气泡。
  const speechBubbles = useMemo(() => {
    const map: Record<string, { text: string; ts: number }> = {};
    visibleEvents.forEach((ev) => {
      const speech = ev.payload?.speech;
      if (ev.type === "speech" && ev.seat_id && typeof speech === "string" && speech.trim()) {
        map[ev.seat_id] = { text: speech.trim(), ts: ev.ts * 1000 };
      }
    });
    return map;
  }, [visibleEvents]);

  const latestReads = useMemo(() => {
    const map: Record<string, any[]> = { ...readsState };
    events.forEach((ev) => {
      if (ev.type === "agent_reads" && ev.payload?.reads && ev.seat_id) {
        map[ev.seat_id] = ev.payload.reads;
      }
    });
    return map;
  }, [events, readsState]);

  const result = snapshot?.result || match?.result || null;
  const finished = snapshot?.finished || status === "finished";
  const phase = snapshot?.phase || (snapshot?.public_state as any)?.phase || "";
  const round = snapshot?.round ?? (snapshot?.public_state as any)?.round ?? 0;

  // 牌桌区域由引擎的 capabilities 决定，前端不再按 game_id 写死。
  const capabilities = useMemo<Record<string, boolean>>(() => {
    const caps = snapshot?.capabilities;
    if (caps && typeof caps === "object") return caps;
    const game = String((snapshot?.public_state as any)?.game || "");
    return {
      hand: game === "doudizhu" || game === "sanguosha",
      items: game === "werewolf",
      table_cards: game === "doudizhu" || game === "sanguosha",
    };
  }, [snapshot]);

  const publicState = (snapshot?.public_state || {}) as Record<string, any>;
  // 斗地主的 last_play 会在两家过牌后清空，recent_play 保留桌面展示用的最近一手。
  const lastPlay = publicState.recent_play || publicState.last_play || null;
  const discardCount =
    typeof publicState.discard_count === "number" ? publicState.discard_count : undefined;

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
          <button
            className="btn sm ghost"
            title={
              !speechSupported()
                ? "当前环境没有浏览器语音引擎，请到「语音朗读」页切换为系统语音或 VoiceStudio"
                : voiceEnabled
                  ? "已开启语音朗读；本机静音后仍会给后端回执，不会拖慢对局"
                  : "全局语音未开启，点击按钮可直接开启"
            }
            onClick={() => {
              if (!voiceEnabled) {
                // 语音全局开关未打开时，点一下直接启用，避免“试听有声、对局无声”的困惑。
                api
                  .saveVoice({ enabled: true })
                  .then((cfg) => {
                    setVoiceEnabled(!!cfg.enabled);
                    unlockSpeech();
                  })
                  .catch(() => undefined);
                return;
              }
              const next = !muted;
              setMuted(next);
              if (!next) unlockSpeech();
              try {
                localStorage.setItem("voice.muted", next ? "1" : "0");
              } catch {
                /* ignore */
              }
              if (next) window.speechSynthesis?.cancel();
            }}
          >
            {muted ? "🔇 已静音" : voiceEnabled ? "🔊 语音已开" : "🔇 语音未启用（点击开启）"}
          </button>
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
              {capabilities.table_cards && lastPlay && (
                <CenterPile play={lastPlay} discardCount={discardCount} names={seatNames} />
              )}
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
              // 手牌/道具直接画在座位上：上帝视角或本人视角亮牌，其他视角只显示牌背。
              const priv = privates[seat.id] || {};
              const handCards: any[] = Array.isArray(priv.hand) ? priv.hand : [];
              const items: any[] = Array.isArray(priv.items) ? priv.items : [];
              const handCount = Number(info.hand_count ?? priv.hand_count ?? handCards.length ?? 0);
              const revealHand = perspective === "god" || perspective === seat.id;
              const bubble = speechBubbles[seat.id];
              const showBubble = Boolean(bubble && nowTs - bubble.ts < 15000);
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
                  {showBubble && (
                    <div className={`seat-bubble ${top > 50 ? "up" : "down"}`}>{bubble!.text}</div>
                  )}
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
                  {capabilities.hand && handCount > 0 && (
                    <div className="seat-hand" title={`手牌 ${handCount} 张`}>
                      {revealHand && handCards.length
                        ? handCards.map((card: any) => (
                            <span
                              className={`mini-card ${isRedCard(String(card.label || "")) ? "red" : ""}`}
                              key={card.id || card.label}
                              title={String(card.label || "")}
                            >
                              {card.label}
                            </span>
                          ))
                        : Array.from({ length: handCount }).map((_, i) => (
                            <span className="mini-card back" key={i} />
                          ))}
                    </div>
                  )}
                  {items.length > 0 && (
                    <div className="seat-items">
                      {items.map((item: any) => (
                        <span
                          className={`mini-item ${item.available === false ? "off" : ""}`}
                          key={item.key || item.label}
                          title={item.description || (item.available === false ? "已使用 / 不可用" : "可用")}
                        >
                          {item.label}
                        </span>
                      ))}
                    </div>
                  )}
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

          {perspective === "god" ? (
            <GodPanel
              snapshot={snapshot}
              privates={privates}
              seats={match?.seats || []}
              reads={latestReads}
              result={result as Record<string, any> | null}
              names={seatNames}
            />
          ) : (
            <>
              <div className="card inspector-card">
                <div className="row" style={{ marginBottom: 10 }}>
                  <div>
                    <div className="card-title">{`${activeSeat?.name || "AI"} 的私有信息`}</div>
                    <div className="card-sub">正在以该 AI 的可见范围查看。</div>
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
                <PrivatePanel data={privates[activeSeatId] || {}} names={seatNames} />
              </div>

              <div className="card inspector-card">
                <div className="card-title" style={{ marginBottom: 4 }}>身份预测</div>
                <div className="card-sub" style={{ marginBottom: 10 }}>
                  AI 在每次行动前提交的推断（来自模型输出 reads）。
                </div>
                <ReadsList reads={latestReads[activeSeatId]} />
              </div>
            </>
          )}

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
