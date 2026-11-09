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
  members: { name: string; provider_id: string; persona?: string }[];
}

export interface SeatDraft {
  name: string;
  provider_id: string;
  persona: string;
}
