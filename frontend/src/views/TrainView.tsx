import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { GameInfo, OllamaModel, Provider, TrainStatus } from "../types";

const IDLE: TrainStatus = {
  status: "idle",
  total: 0,
  done: 0,
  failed: 0,
  progress: 0,
  winners: {},
  avg_rounds: 0,
  avg_seconds: 0,
  elapsed: 0,
  lessons: 0,
  recent: [],
  error: "",
};

function normalize(data: TrainStatus): TrainStatus {
  return {
    ...IDLE,
    ...data,
    winners: data.winners || {},
    recent: data.recent || [],
  };
}

function formatSize(size?: number): string {
  if (!size) return "";
  const gb = size / 1024 / 1024 / 1024;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${(size / 1024 / 1024).toFixed(0)} MB`;
}

export default function TrainView() {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [gameId, setGameId] = useState("");
  const [providerId, setProviderId] = useState("");
  const [seatCount, setSeatCount] = useState<number | null>(null);
  const [rounds, setRounds] = useState(20);
  const [concurrency, setConcurrency] = useState(1);
  const [ragEnabled, setRagEnabled] = useState(true);
  const [reflect, setReflect] = useState(true);
  const [status, setStatus] = useState<TrainStatus>(IDLE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [modelError, setModelError] = useState("");

  const game = useMemo(() => games.find((item) => item.id === gameId) || null, [games, gameId]);
  const provider = useMemo(
    () => providers.find((item) => item.id === providerId) || null,
    [providers, providerId],
  );
  const allowedCounts = game?.allowed_counts?.length ? game.allowed_counts : [];
  const running = status.status === "running";

  useEffect(() => {
    Promise.all([api.games(), api.providers(), api.trainStatus()])
      .then(([gameList, providerList, current]) => {
        setGames(gameList);
        setProviders(providerList);
        setStatus(normalize(current));
        setGameId((prev) => prev || gameList[0]?.id || "");
        setProviderId((prev) => prev || providerList[0]?.id || "");
        setSeatCount((prev) => prev ?? gameList[0]?.allowed_counts?.[0] ?? null);
      })
      .catch((exc) => setError((exc as Error).message));
  }, []);

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => {
      api.trainStatus().then((data) => setStatus(normalize(data))).catch(() => undefined);
    }, 1200);
    return () => clearInterval(timer);
  }, [running]);

  const chooseProvider = (id: string) => {
    setProviderId(id);
    setModels([]);
    setModelError("");
  };

  const detectOllama = async () => {
    const base = provider?.base_url || "http://127.0.0.1:11434";
    setModelError("");
    try {
      const data = await api.ollamaModels(base);
      setModels(data.models);
      setModelError(data.ok ? "" : data.error || "未检测到 Ollama 服务");
      if (data.ok && data.models.length) setNotice(`检测到 ${data.models.length} 个本地模型`);
    } catch (exc) {
      setModelError((exc as Error).message);
    }
  };

  const useModel = async (name: string) => {
    if (!provider) return;
    try {
      const saved = await api.updateProvider(provider.id, { ...provider, model: name });
      setProviders((prev) => prev.map((item) => (item.id === saved.id ? saved : item)));
      setNotice(`已把 ${provider.name} 的模型切换为 ${name}`);
    } catch (exc) {
      setError((exc as Error).message);
    }
  };

  const start = async () => {
    if (!gameId || !providerId) {
      setError("请选择游戏与 Provider");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const started = await api.startTrain({
        game_id: gameId,
        provider_id: providerId,
        games: rounds,
        concurrency,
        seat_count: seatCount,
        rag_enabled: ragEnabled,
        reflect,
      });
      setStatus(normalize(started));
      setNotice(`训练已开始：${started.game_name || gameId} × ${started.total} 局`);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    try {
      setStatus(normalize(await api.stopTrain()));
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
          <div className="page-title">训练场 · 自对弈</div>
          <div className="page-desc">
            后台快速跑多局对局，只统计胜负与回合数，不进入牌桌、不写对局日志。开着 RAG 复盘时，
            每局结束会把可复用技巧写入记忆库，越跑越聪明。Ollama 本地模型可在下方一键检测与切换。
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn sm" onClick={start} disabled={busy || running}>
            {running ? "训练中…" : "开始训练"}
          </button>
          <button className="btn sm" onClick={stop} disabled={busy || !running}>
            停止
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {notice && (
        <div className="card" style={{ marginBottom: 14, color: "var(--accent-2)", fontSize: 12.5 }}>
          {notice}
        </div>
      )}

      <div className="card mb">
        <div className="card-title" style={{ marginBottom: 12 }}>训练设置</div>
        <div className="form-grid">
          <label className="field">
            <span>游戏</span>
            <select
              value={gameId}
              onChange={(e) => {
                const next = games.find((item) => item.id === e.target.value);
                setGameId(e.target.value);
                setSeatCount(next?.allowed_counts?.[0] ?? null);
              }}
              disabled={running}
            >
              {games.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Provider</span>
            <select value={providerId} onChange={(e) => chooseProvider(e.target.value)} disabled={running}>
              {providers.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · {item.model || item.kind}
                </option>
              ))}
            </select>
          </label>
          {allowedCounts.length > 1 && (
            <label className="field">
              <span>人数</span>
              <select
                value={seatCount ?? allowedCounts[0]}
                onChange={(e) => setSeatCount(Number(e.target.value))}
                disabled={running}
              >
                {allowedCounts.map((count) => (
                  <option key={count} value={count}>{count} 人</option>
                ))}
              </select>
            </label>
          )}
          <label className="field">
            <span>对弈局数</span>
            <input
              type="number"
              min="1"
              max="500"
              value={rounds}
              onChange={(e) => setRounds(Math.max(1, Math.min(500, Number(e.target.value) || 1)))}
              disabled={running}
            />
          </label>
          <label className="field">
            <span>并发数</span>
            <input
              type="number"
              min="1"
              max="8"
              value={concurrency}
              onChange={(e) => setConcurrency(Math.max(1, Math.min(8, Number(e.target.value) || 1)))}
              disabled={running}
            />
          </label>
        </div>
        <div className="row wrap mt" style={{ gap: 18 }}>
          <label className="checkline">
            <input
              type="checkbox"
              checked={ragEnabled}
              onChange={(e) => setRagEnabled(e.target.checked)}
              disabled={running}
            />
            <span>训练时读取 RAG 技能卡</span>
          </label>
          <label className="checkline">
            <input
              type="checkbox"
              checked={reflect}
              onChange={(e) => setReflect(e.target.checked)}
              disabled={running}
            />
            <span>每局结束复盘写入记忆库</span>
          </label>
          <span className="muted tiny">
            Mock Provider 可高并发快速验证流程；真实模型建议并发 1-2，避免本地显存或 API 限流。
          </span>
        </div>

        <div className="row wrap mt" style={{ gap: 10 }}>
          <button className="btn sm" onClick={detectOllama} disabled={running}>
            检测 Ollama 模型
          </button>
          <span className="muted tiny">
            {provider?.base_url?.includes("11434")
              ? "当前 Provider 指向本地 Ollama，可直接检测并切换模型。"
              : "先选择一个 Ollama Provider（默认 http://127.0.0.1:11434/v1）。"}
          </span>
        </div>
        {modelError && <div className="muted tiny" style={{ marginTop: 8, color: "var(--danger)" }}>{modelError}</div>}
        {models.length > 0 && (
          <div className="tag-list" style={{ marginTop: 10 }}>
            {models.map((model) => (
              <button
                key={model.name}
                className="chip"
                style={{ cursor: "pointer" }}
                onClick={() => useModel(model.name)}
                title={formatSize(model.size)}
              >
                {model.name}{model.size ? ` · ${formatSize(model.size)}` : ""}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="card mb">
        <div className="row" style={{ marginBottom: 10 }}>
          <div className="card-title">训练进度</div>
          <span className={`chip right ${running ? "warn" : status.status === "finished" ? "green" : ""}`}>
            {status.status === "running" && "进行中"}
            {status.status === "finished" && "已完成"}
            {status.status === "stopped" && "已停止"}
            {status.status === "error" && "异常"}
            {status.status === "idle" && "空闲"}
          </span>
        </div>
        <div className="confidence" style={{ height: 10 }}>
          <i style={{ width: `${Math.round((status.progress || 0) * 100)}%` }} />
        </div>
        <div className="row wrap" style={{ gap: 10, marginTop: 10 }}>
          <span className="chip">对弈 {status.done} / {status.total} 局</span>
          <span className="chip">失败 {status.failed}</span>
          <span className="chip">平均 {status.avg_rounds} 回合</span>
          <span className="chip">平均 {status.avg_seconds}s / 局</span>
          <span className="chip">耗时 {status.elapsed}s</span>
          <span className="chip">新增/命中记忆 {status.lessons}</span>
        </div>
        {status.error && <div className="error-banner" style={{ marginTop: 10 }}>{status.error}</div>}
        <div className="tag-list" style={{ marginTop: 10 }}>
          {Object.entries(status.winners || {}).map(([winner, count]) => (
            <span className="chip accent" key={winner}>{winner}：{count}</span>
          ))}
          {!Object.keys(status.winners || {}).length && <span className="muted tiny">暂无结果</span>}
        </div>
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <div className="card-title">最近对局</div>
          <span className="muted tiny right">{status.recent.length} 条</span>
        </div>
        {status.recent.length ? (
          <div className="reads">
            {status.recent.map((item) => (
              <div className="read-item" key={item.index}>
                <div className="read-head">
                  <span className="small" style={{ fontWeight: 600 }}>第 {item.index} 局</span>
                  <span className="chip accent">{item.winner}</span>
                  <span className="muted tiny">{item.rounds} 回合</span>
                  <span className="muted tiny right">{item.seconds}s</span>
                </div>
                {item.error && <div className="muted tiny" style={{ marginTop: 4, color: "var(--danger)" }}>{item.error}</div>}
              </div>
            ))}
          </div>
        ) : (
          <div className="muted small">还没有训练记录，先在上面开始一次训练。</div>
        )}
      </div>
    </div>
  );
}
