import { useEffect, useState } from "react";
import { api } from "./api";
import LobbyView from "./views/LobbyView";
import ProvidersView from "./views/ProvidersView";
import GroupsView from "./views/GroupsView";
import TableView from "./views/TableView";
import VoiceView from "./views/VoiceView";
import MemoryView from "./views/MemoryView";
import TrainView from "./views/TrainView";

type View = "lobby" | "providers" | "groups" | "voice" | "memory" | "train" | "table";

export default function App() {
  const [view, setView] = useState<View>("lobby");
  const [matchId, setMatchId] = useState<string | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const check = async () => {
      try {
        await api.health();
        if (!alive) return;
        setOnline(true);
        timer = window.setTimeout(check, 5000);
      } catch {
        if (!alive) return;
        setOnline(false);
        // 后端可能还在启动，未连接时加快轮询，连上后回到 5 秒。
        timer = window.setTimeout(check, 1500);
      }
    };
    check();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  const openMatch = (id: string) => {
    setMatchId(id);
    setView("table");
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">AI</div>
          <div>
            <div className="brand-title">MultiAIGroup</div>
            <div className="brand-sub">多 AI 群组对局</div>
          </div>
        </div>
        <nav className="nav">
          <button
            className={`nav-item ${view === "lobby" || view === "table" ? "active" : ""}`}
            onClick={() => setView("lobby")}
          >
            <span className="nav-icon">◈</span>
            <span>对局大厅</span>
          </button>
          <button
            className={`nav-item ${view === "providers" ? "active" : ""}`}
            onClick={() => setView("providers")}
          >
            <span className="nav-icon">⚙</span>
            <span>AI Provider</span>
          </button>
          <button
            className={`nav-item ${view === "groups" ? "active" : ""}`}
            onClick={() => setView("groups")}
          >
            <span className="nav-icon">✦</span>
            <span>AI 群组</span>
          </button>
          <button
            className={`nav-item ${view === "voice" ? "active" : ""}`}
            onClick={() => setView("voice")}
          >
            <span className="nav-icon">🔊</span>
            <span>语音朗读</span>
          </button>
          <button
            className={`nav-item ${view === "memory" ? "active" : ""}`}
            onClick={() => setView("memory")}
          >
            <span className="nav-icon">🧠</span>
            <span>AI 记忆库</span>
          </button>
          <button
            className={`nav-item ${view === "train" ? "active" : ""}`}
            onClick={() => setView("train")}
          >
            <span className="nav-icon">🏋</span>
            <span>训练场</span>
          </button>
        </nav>
        <div className="sidebar-foot">
          <div className="health">
            <i className={`health-dot ${online ? "on" : ""}`} />
            <span>后端 {online === null ? "连接中…" : online ? "已连接" : "未连接"}</span>
          </div>
          <div style={{ marginTop: 6 }}>127.0.0.1:8765</div>
          <div style={{ marginTop: 2 }}>v0.1.0</div>
        </div>
      </aside>
      <main className="main">
        {view === "lobby" && (
          <LobbyView onOpenMatch={openMatch} onGoProviders={() => setView("providers")} />
        )}
        {view === "providers" && <ProvidersView />}
        {view === "groups" && <GroupsView />}
        {view === "voice" && <VoiceView />}
        {view === "memory" && <MemoryView />}
        {view === "train" && <TrainView />}
        {view === "table" && matchId && (
          <TableView matchId={matchId} onBack={() => setView("lobby")} />
        )}
      </main>
    </div>
  );
}
