import type {
  AgentLog,
  GameEvent,
  GameInfo,
  Group,
  MatchDetail,
  MatchSummary,
  Provider,
  ProviderPreset,
  SeatDraft,
} from "./types";

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) || "http://127.0.0.1:8765";
export const WS_BASE = API_BASE.replace(/^http/, "ws");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
}

const post = (path: string, body?: unknown) =>
  request(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => request<{ ok: boolean; time: number }>("/api/health"),
  presets: () => request<ProviderPreset[]>("/api/provider-presets"),
  games: () => request<GameInfo[]>("/api/games"),

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
