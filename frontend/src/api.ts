import type {
  AgentLog,
  GameEvent,
  GameInfo,
  Group,
  MatchDetail,
  MatchSummary,
  MemoryItem,
  OllamaModels,
  Provider,
  ProviderPreset,
  RagSettings,
  SeatDraft,
  TrainRequest,
  TrainStatus,
  VoiceDiagnostics,
  VoiceSettings,
} from "./types";

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) || "http://127.0.0.1:8765";
export const WS_BASE = API_BASE.replace(/^http/, "ws");

// 后端刚启动时首次请求常常连不上，GET 请求自动重试几轮，避免必须切换页面才恢复。
const RETRY_DELAYS = [500, 1200, 2500, 4000];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || "GET").toUpperCase();
  const attempts = method === "GET" ? RETRY_DELAYS.length + 1 : 1;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (attempt > 0) {
      await new Promise((resolve) => setTimeout(resolve, RETRY_DELAYS[attempt - 1]));
    }
    try {
      const resp = await fetch(`${API_BASE}${path}`, {
        headers: { "Content-Type": "application/json" },
        ...init,
      });
      if (!resp.ok) {
        let detail = `${resp.status} ${resp.statusText}`;
        try {
          const data = await resp.json();
          detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      if (resp.status === 204) return undefined as T;
      return (await resp.json()) as T;
    } catch (err) {
      // 只有网络层失败（后端还没起来）才重试；HTTP 业务错误直接抛出。
      if (!(err instanceof TypeError)) throw err;
    }
  }
  throw new Error(
    `无法连接后端 ${API_BASE}，请确认后端已启动（启动脚本：项目根目录 start.bat）。`,
  );
}

const post = (path: string, body?: unknown) =>
  request(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => request<{ ok: boolean; time: number }>("/api/health"),
  presets: () => request<ProviderPreset[]>("/api/provider-presets"),
  games: () => request<GameInfo[]>("/api/games"),

  voice: () => request<VoiceSettings>("/api/voice"),
  saveVoice: (data: Partial<VoiceSettings>) =>
    request<VoiceSettings>("/api/voice", { method: "PUT", body: JSON.stringify(data) }),
  voiceDiagnostics: () => request<VoiceDiagnostics>("/api/voice/diagnostics"),

  trainStatus: () => request<TrainStatus>("/api/train/status"),
  startTrain: (data: TrainRequest) => post("/api/train/start", data) as Promise<TrainStatus>,
  stopTrain: () => post("/api/train/stop") as Promise<TrainStatus>,
  ollamaModels: (baseUrl?: string) => {
    const query = baseUrl ? `?base_url=${encodeURIComponent(baseUrl)}` : "";
    return request<OllamaModels>(`/api/ollama/models${query}`);
  },

  rag: () => request<RagSettings>("/api/rag"),
  saveRag: (data: Partial<RagSettings>) =>
    request<RagSettings>("/api/rag", { method: "PUT", body: JSON.stringify(data) }),
  memories: (params: { game_id?: string; role?: string; kind?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") query.set(key, String(value));
    });
    const suffix = query.toString();
    return request<MemoryItem[]>(`/api/rag/memories${suffix ? `?${suffix}` : ""}`);
  },
  createMemory: (data: {
    text: string;
    game_id?: string;
    role?: string;
    faction?: string;
    kind?: string;
  }) => post("/api/rag/memories", data) as Promise<MemoryItem>,
  deleteMemory: (id: string) => request(`/api/rag/memories/${id}`, { method: "DELETE" }),
  seedRag: () => post("/api/rag/seed") as Promise<{ ok: boolean; added: number; total: number }>,
  searchMemories: (q: string, game_id?: string, role?: string, top_k = 8) => {
    const query = new URLSearchParams({ q, top_k: String(top_k) });
    if (game_id) query.set("game_id", game_id);
    if (role) query.set("role", role);
    return request<MemoryItem[]>(`/api/rag/search?${query.toString()}`);
  },

  providers: () => request<Provider[]>("/api/providers"),
  createProvider: (data: Partial<Provider>) => post("/api/providers", data) as Promise<Provider>,
  updateProvider: (id: string, data: Partial<Provider>) =>
    request<Provider>(`/api/providers/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteProvider: (id: string) => request(`/api/providers/${id}`, { method: "DELETE" }),
  testProvider: (id: string) =>
    post(`/api/providers/${id}/test`) as Promise<{ ok: boolean; response?: string; error?: string }>,

  groups: () => request<Group[]>("/api/groups"),
  createGroup: (data: { name: string; members: unknown[] }) => post("/api/groups", data) as Promise<Group>,
  deleteGroup: (id: string) => request(`/api/groups/${id}`, { method: "DELETE" }),

  matches: () => request<MatchSummary[]>("/api/matches"),
  match: (id: string) => request<MatchDetail>(`/api/matches/${id}`),
  events: (id: string) => request<GameEvent[]>(`/api/matches/${id}/events`),
  logs: (id: string, seatId?: string) =>
    request<AgentLog[]>(`/api/matches/${id}/logs?limit=120${seatId ? `&seat_id=${seatId}` : ""}`),
  createMatch: (data: {
    game_id: string;
    title: string;
    seats: SeatDraft[];
    config?: Record<string, unknown>;
  }) => post("/api/matches", data) as Promise<MatchDetail>,
  startMatch: (id: string) => post(`/api/matches/${id}/start`),
  stopMatch: (id: string) => post(`/api/matches/${id}/stop`),
  deleteMatch: (id: string) => request(`/api/matches/${id}`, { method: "DELETE" }),
};
