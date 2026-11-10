export type Visibility = { scope: "public" | "private" | "group"; seats: string[] };

export interface Provider {
  id: string;
  name: string;
  kind: string;
  base_url: string;
  model: string;
  api_key?: string;
  has_key?: boolean;
  temperature: number;
  max_tokens: number;
  voice_id?: string;
  extra: Record<string, unknown>;
  created_at?: number;
}

export interface ProviderPreset {
  id: string;
  name: string;
  kind: string;
  base_url: string;
  model: string;
}

export interface GameInfo {
  id: string;
  name: string;
  description: string;
  min_players: number;
  max_players: number;
  allowed_counts: number[];
  presets: Record<string, unknown>[];
  rules: string;
}

export interface MatchSeat {
  id: string;
  name: string;
  provider_id: string;
  provider_name?: string;
  model?: string;
  persona: string;
  color: string;
  voice_id?: string;
}

export interface MatchSummary {
  id: string;
  game_id: string;
  title: string;
  status: string;
  seats: MatchSeat[];
  config: Record<string, unknown>;
  result: Record<string, unknown>;
  created_at: number;
}

export interface MatchDetail extends MatchSummary {
  state: Snapshot | Record<string, never>;
  privates: Record<string, Record<string, unknown>>;
  started_at?: number;
  finished_at?: number;
}

export interface ActionRequest {
  id: string;
  seat_id: string;
  kind: string;
  title: string;
  instruction: string;
  options: { id: string; label: string; action: Record<string, unknown> }[];
}

export interface Snapshot {
  game_id: string;
  name: string;
  round: number;
  phase: string;
  finished: boolean;
  result: Record<string, unknown> | null;
  capabilities?: Record<string, boolean>;
  public_state: Record<string, any>;
  requests: ActionRequest[];
}

export interface GameEvent {
  seq: number;
  ts: number;
  type: string;
  text: string;
  visibility: Visibility;
  seat_id: string | null;
  round: number;
  phase: string;
  payload: Record<string, any>;
}

export interface AgentLog {
  id: number;
  seat_id: string;
  request_id: string;
  attempt: number;
  provider: string;
  user_prompt: string;
  raw_response: string;
  parsed: Record<string, unknown>;
  error: string;
  created_at: number;
}

export interface Group {
  id: string;
  name: string;
  members: { name: string; provider_id: string; persona?: string; voice_id?: string }[];
}

export interface SeatDraft {
  name: string;
  provider_id: string;
  persona: string;
  voice_id?: string;
}

export interface VoiceSettings {
  enabled: boolean;
  provider: string;
  default_voice_id: string;
  narrator_voice_id: string;
  speed: number;
  wait_ms: number;
  voicestudio: {
    url: string;
    api_key: string;
    headers: Record<string, string>;
    text_field: string;
    voice_field: string;
    extra_body: Record<string, unknown>;
    audio_field: string;
    audio_url_field: string;
    timeout_ms: number;
  };
}

export interface RagSettings {
  enabled: boolean;
  top_k: number;
  min_score: number;
  reflect: boolean;
  llm_reflect: boolean;
  total?: number;
}

export interface MemoryItem {
  id: string;
  game_id: string;
  role: string;
  faction: string;
  kind: string;
  text: string;
  source: string;
  match_id: string;
  created_at: number;
  score?: number;
}

export interface VoiceDiagnostics {
  platform: string;
  provider: string;
  enabled: boolean;
  system_tts: {
    available: boolean;
    voices: string[];
    reason: string;
  };
  voicestudio_configured: boolean;
}

export interface OllamaModel {
  name: string;
  size?: number;
}

export interface OllamaModels {
  ok: boolean;
  base_url: string;
  models: OllamaModel[];
  error?: string;
}

export interface TrainRecent {
  index: number;
  winner: string;
  rounds: number;
  seconds: number;
  error?: string;
}

export interface TrainStatus {
  id?: string;
  status: "idle" | "running" | "finished" | "stopped" | "error";
  game_id?: string;
  game_name?: string;
  total: number;
  done: number;
  failed: number;
  progress: number;
  winners: Record<string, number>;
  avg_rounds: number;
  avg_seconds: number;
  elapsed: number;
  lessons: number;
  recent: TrainRecent[];
  error: string;
  config?: Record<string, unknown>;
}

export interface TrainRequest {
  game_id: string;
  provider_id?: string;
  provider_ids?: string[];
  games?: number;
  concurrency?: number;
  seat_count?: number | null;
  rag_enabled?: boolean;
  reflect?: boolean;
  llm_reflect?: boolean;
  seed?: number;
  timeout?: number | null;
}
