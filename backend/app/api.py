"""FastAPI 接口层：REST + WebSocket。"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .ai import PRESETS, AIClient, config_from_row
from .engine import Seat
from .plugins import create_engine, get_engine_class, list_games
from .rag import add_memory, load_rag, save_rag, search as rag_search, seed_skills
from .runner import RunnerManager
from .store import Store
from .training import TrainManager
from .voice import load_voice, save_voice, voice_diagnostics

SEAT_COLORS = [
    "#7c9cff", "#ff8f6b", "#4fd1a5", "#d38bff", "#ffd166",
    "#6bd5ff", "#ff7aa2", "#a3e635", "#f0abfc", "#fca5a5",
]


# ---------------- 请求模型 ----------------
class ProviderIn(BaseModel):
    name: str
    kind: str = "openai"
    base_url: str = ""
    model: str = ""
    api_key: str | None = None
    temperature: float = 0.8
    max_tokens: int = 1200
    voice_id: str = ""
    extra: dict = Field(default_factory=dict)


class GroupIn(BaseModel):
    name: str = "我的 AI 群组"
    members: list[dict] = Field(default_factory=list)


class SeatIn(BaseModel):
    name: str
    provider_id: str
    persona: str = ""
    color: str | None = None
    voice_id: str = ""


class MatchIn(BaseModel):
    game_id: str
    title: str = ""
    seats: list[SeatIn]
    config: dict = Field(default_factory=dict)


class VoiceIn(BaseModel):
    enabled: bool | None = None
    provider: str | None = None
    default_voice_id: str | None = None
    narrator_voice_id: str | None = None
    speed: float | None = None
    wait_ms: int | None = None
    voicestudio: dict | None = None


class RagIn(BaseModel):
    enabled: bool | None = None
    top_k: int | None = None
    min_score: float | None = None
    reflect: bool | None = None
    llm_reflect: bool | None = None


class MemoryIn(BaseModel):
    text: str
    game_id: str = ""
    role: str = ""
    faction: str = ""
    kind: str = "manual"


class TrainIn(BaseModel):
    game_id: str
    provider_id: str = ""
    provider_ids: list[str] = Field(default_factory=list)
    games: int = 20
    concurrency: int = 1
    seat_count: int | None = None
    rag_enabled: bool = True
    reflect: bool = True
    llm_reflect: bool = False
    seed: int = 0
    timeout: float | None = None
    config: dict = Field(default_factory=dict)


class Hub:
    def __init__(self) -> None:
        self.channels: dict[str, set[WebSocket]] = {}

    async def join(self, channel: str, ws: WebSocket) -> None:
        self.channels.setdefault(channel, set()).add(ws)

    def leave(self, channel: str, ws: WebSocket) -> None:
        self.channels.get(channel, set()).discard(ws)

    def count(self, channel: str) -> int:
        return len(self.channels.get(channel, set()))

    async def send(self, channel: str, payload: dict) -> None:
        dead = []
        for ws in list(self.channels.get(channel, set())):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.leave(channel, ws)


class SpeechAcks:
    """等待前端播完语音后回执 speech_done，用于“读完再轮到下一个人”。"""

    def __init__(self) -> None:
        self._futures: dict[str, asyncio.Future] = {}

    def prepare(self, speech_id: str) -> None:
        # 必须在广播前注册，避免回执先于等待到达。
        old = self._futures.get(speech_id)
        if old and not old.done():
            old.cancel()
        self._futures[speech_id] = asyncio.get_running_loop().create_future()

    def done(self, speech_id: str) -> None:
        future = self._futures.get(speech_id)
        if future and not future.done():
            future.set_result(True)

    async def wait(self, speech_id: str, timeout: float) -> None:
        future = self._futures.get(speech_id)
        if future is None:
            return
        try:
            await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            self._futures.pop(speech_id, None)


def _build_seats(match: dict, store: Store) -> tuple[list[Seat], dict[str, AIClient]]:
    seats: list[Seat] = []
    clients: dict[str, AIClient] = {}
    for idx, item in enumerate(match.get("seats") or []):
        provider = store.get_provider(item.get("provider_id", ""))
        seat = Seat(
            id=item["id"],
            name=item["name"],
            provider_id=item.get("provider_id", ""),
            persona=item.get("persona", ""),
            provider_name=provider["name"] if provider else "未知 Provider",
            model=provider["model"] if provider else "",
            color=item.get("color") or SEAT_COLORS[idx % len(SEAT_COLORS)],
            # 座位语音优先，其次 Provider 默认音色。
            voice_id=item.get("voice_id") or (provider.get("voice_id", "") if provider else ""),
        )
        seats.append(seat)
        if provider:
            clients[seat.id] = AIClient(config_from_row(provider))
    return seats, clients


def create_app(db: Path | None = None) -> FastAPI:
    store = Store(db)
    hub = Hub()
    try:
        seed_skills(store)
    except Exception:
        pass

    acks = SpeechAcks()

    async def broadcast(payload: dict) -> None:
        await hub.send(str(payload.get("match_id") or "lobby"), payload)

    manager = RunnerManager(
        store,
        broadcast,
        acks=acks,
        has_clients=lambda match_id: hub.count(match_id) > 0,
    )
    trainer = TrainManager(store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await trainer.stop()
        await manager.shutdown()

    app = FastAPI(title="MultiAIGroup", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = store
    app.state.hub = hub
    app.state.manager = manager
    app.state.trainer = trainer

    # ---------------- 基础 ----------------
    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "time": time.time(), "version": "0.1.0"}

    @app.get("/api/provider-presets")
    def provider_presets() -> list[dict]:
        return PRESETS

    @app.get("/api/games")
    def games() -> list[dict]:
        return list_games()

    # ---------------- 语音 ----------------
    @app.get("/api/voice")
    def get_voice() -> dict:
        return load_voice(store)

    @app.put("/api/voice")
    def put_voice(payload: VoiceIn) -> dict:
        return save_voice(store, payload.model_dump(exclude_none=True))

    @app.get("/api/voice/diagnostics")
    async def voice_check() -> dict:
        return await voice_diagnostics(load_voice(store))

    # ---------------- 训练场 / Ollama ----------------
    @app.post("/api/train/start")
    async def train_start(payload: TrainIn) -> dict:
        try:
            return await trainer.start(payload.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/train/status")
    def train_status() -> dict:
        return trainer.status()

    @app.post("/api/train/stop")
    async def train_stop() -> dict:
        return await trainer.stop()

    @app.get("/api/ollama/models")
    async def ollama_models(base_url: str = "http://127.0.0.1:11434") -> dict:
        base = (base_url or "http://127.0.0.1:11434").rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                resp = await client.get(f"{base}/api/tags")
                resp.raise_for_status()
                data = resp.json()
            models = [
                {
                    "name": item.get("name") or item.get("model") or "",
                    "size": item.get("size") or 0,
                }
                for item in (data.get("models") or [])
                if item.get("name") or item.get("model")
            ]
            return {"ok": True, "base_url": base, "models": models}
        except Exception as exc:
            return {"ok": False, "base_url": base, "models": [], "error": f"{type(exc).__name__}: {exc}"}

    # ---------------- RAG 记忆库 ----------------
    @app.get("/api/rag")
    def get_rag() -> dict:
        cfg = load_rag(store)
        return {**cfg, "total": store.count_memories()}

    @app.put("/api/rag")
    def put_rag(payload: RagIn) -> dict:
        cfg = save_rag(store, payload.model_dump(exclude_none=True))
        return {**cfg, "total": store.count_memories()}

    @app.get("/api/rag/memories")
    def list_memories(
        game_id: str | None = None,
        role: str | None = None,
        kind: str | None = None,
        limit: int = 300,
    ) -> list[dict]:
        items = store.list_memories(game_id, role, kind, max(1, min(limit, 1000)))
        for item in items:
            item.pop("embedding", None)
        return items

    @app.post("/api/rag/memories")
    def create_memory(payload: MemoryIn) -> dict:
        if not payload.text.strip():
            raise HTTPException(400, "记忆内容不能为空")
        item = add_memory(
            store,
            payload.text,
            game_id=payload.game_id,
            role=payload.role,
            faction=payload.faction,
            kind=payload.kind or "manual",
            source="manual",
        )
        item.pop("embedding", None)
        return item

    @app.delete("/api/rag/memories/{memory_id}")
    def delete_memory(memory_id: str) -> dict:
        store.delete_memory(memory_id)
        return {"ok": True}

    @app.post("/api/rag/seed")
    def seed() -> dict:
        added = seed_skills(store)
        return {"ok": True, "added": added, "total": store.count_memories()}

    @app.get("/api/rag/search")
    def search_memories(
        q: str,
        game_id: str | None = None,
        role: str | None = None,
        top_k: int = 8,
    ) -> list[dict]:
        items = rag_search(
            store,
            q,
            game_id=game_id or "",
            role=role or "",
            top_k=max(1, min(top_k, 30)),
            min_score=0.0,
        )
        for item in items:
            item.pop("embedding", None)
        return items

    # ---------------- Provider ----------------
    @app.get("/api/providers")
    def list_providers() -> list[dict]:
        return store.list_providers()

    @app.post("/api/providers")
    def create_provider(payload: ProviderIn) -> dict:
        return store.upsert_provider(payload.model_dump())

    @app.put("/api/providers/{provider_id}")
    def update_provider(provider_id: str, payload: ProviderIn) -> dict:
        if not store.get_provider(provider_id):
            raise HTTPException(404, "Provider 不存在")
        return store.upsert_provider(payload.model_dump(), provider_id)

    @app.delete("/api/providers/{provider_id}")
    def delete_provider(provider_id: str) -> dict:
        store.delete_provider(provider_id)
        return {"ok": True}

    @app.post("/api/providers/{provider_id}/test")
    async def test_provider(provider_id: str) -> dict:
        row = store.get_provider(provider_id)
        if not row:
            raise HTTPException(404, "Provider 不存在")
        client = AIClient(config_from_row(row))
        try:
            text = await client.chat(
                [
                    {"role": "system", "content": "你是一个连通性测试助手。"},
                    {"role": "user", "content": '请只输出 JSON：{"ok": true, "msg": "pong"}'},
                ],
                json_mode=True,
                timeout=60,
            )
            return {"ok": True, "response": text[:500]}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # ---------------- 群组 ----------------
    @app.get("/api/groups")
    def list_groups() -> list[dict]:
        return store.list_groups()

    @app.post("/api/groups")
    def create_group(payload: GroupIn) -> dict:
        return store.upsert_group(payload.model_dump())

    @app.put("/api/groups/{group_id}")
    def update_group(group_id: str, payload: GroupIn) -> dict:
        return store.upsert_group(payload.model_dump(), group_id)

    @app.delete("/api/groups/{group_id}")
    def delete_group(group_id: str) -> dict:
        store.delete_group(group_id)
        return {"ok": True}

    # ---------------- 对局 ----------------
    @app.get("/api/matches")
    def list_matches(limit: int = 50) -> list[dict]:
        items = store.list_matches(limit)
        for item in items:
            runner = manager.get(item["id"])
            if runner and runner.is_active():
                item["status"] = "running"
        return items

    @app.post("/api/matches")
    def create_match(payload: MatchIn) -> dict:
        engine_cls = get_engine_class(payload.game_id)
        if engine_cls is None:
            raise HTTPException(400, f"未知游戏 {payload.game_id}")
        count = len(payload.seats)
        allowed = engine_cls.allowed_counts
        if allowed and count not in allowed:
            raise HTTPException(400, f"{engine_cls.name} 支持 {allowed} 人，当前 {count} 人")
        if not (engine_cls.min_players <= count <= engine_cls.max_players):
            raise HTTPException(400, f"{engine_cls.name} 需要 {engine_cls.min_players}-{engine_cls.max_players} 人")

        seats = []
        for idx, seat in enumerate(payload.seats):
            provider = store.get_provider(seat.provider_id)
            if not provider:
                raise HTTPException(400, f"座位 {seat.name} 的 Provider 不存在")
            seats.append(
                {
                    "id": f"s{idx + 1}",
                    "name": seat.name.strip() or f"AI {idx + 1}",
                    "provider_id": seat.provider_id,
                    "provider_name": provider["name"],
                    "model": provider["model"],
                    "persona": seat.persona,
                    "color": seat.color or SEAT_COLORS[idx % len(SEAT_COLORS)],
                    "voice_id": seat.voice_id or provider.get("voice_id", ""),
                }
            )
        title = payload.title.strip() or f"{engine_cls.name} · {time.strftime('%m-%d %H:%M')}"
        return store.create_match(
            {
                "game_id": payload.game_id,
                "title": title,
                "seats": seats,
                "config": payload.config,
            }
        )

    @app.get("/api/matches/{match_id}")
    def get_match(match_id: str) -> dict:
        match = store.get_match(match_id)
        if not match:
            raise HTTPException(404, "对局不存在")
        runner = manager.get(match_id)
        if runner and runner.is_active():
            match["status"] = "running"
            match["state"] = runner.engine.snapshot()
            match["privates"] = {
                seat.id: runner.engine.private_state(seat.id) for seat in runner.seats
            }
        return match

    @app.get("/api/matches/{match_id}/events")
    def get_events(match_id: str) -> list[dict]:
        if not store.get_match(match_id):
            raise HTTPException(404, "对局不存在")
        return store.get_events(match_id)

    @app.get("/api/matches/{match_id}/logs")
    def get_logs(match_id: str, seat_id: str | None = None, limit: int = 200) -> list[dict]:
        if not store.get_match(match_id):
            raise HTTPException(404, "对局不存在")
        return store.get_logs(match_id, seat_id, limit)

    @app.delete("/api/matches/{match_id}")
    async def delete_match(match_id: str) -> dict:
        runner = manager.get(match_id)
        if runner and runner.is_active():
            raise HTTPException(400, "对局正在运行，请先停止")
        if not store.get_match(match_id):
            raise HTTPException(404, "对局不存在")
        manager.runners.pop(match_id, None)
        store.delete_match(match_id)
        return {"ok": True}

    @app.post("/api/matches/{match_id}/start")
    async def start_match(match_id: str) -> dict:
        match = store.get_match(match_id)
        if not match:
            raise HTTPException(404, "对局不存在")
        existing = manager.get(match_id)
        if existing and existing.is_active():
            raise HTTPException(400, "对局已在运行中")
        if match["status"] == "finished":
            raise HTTPException(400, "该对局已结束，请新建对局")
        seats, clients = _build_seats(match, store)
        try:
            create_engine(match["game_id"], seats, match.get("config") or {})
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        manager.launch(match, seats, clients)
        return {"ok": True, "status": "running"}

    @app.post("/api/matches/{match_id}/stop")
    async def stop_match(match_id: str) -> dict:
        if not store.get_match(match_id):
            raise HTTPException(404, "对局不存在")
        stopped = await manager.stop(match_id)
        return {"ok": stopped}

    # ---------------- WebSocket ----------------
    @app.websocket("/ws/matches/{match_id}")
    async def match_socket(ws: WebSocket, match_id: str) -> None:
        await ws.accept()
        await hub.join(match_id, ws)
        try:
            match = store.get_match(match_id)
            if not match:
                await ws.send_json({"type": "error", "message": "对局不存在"})
                return
            runner = manager.get(match_id)
            snapshot = runner.engine.snapshot() if runner else match.get("state") or {}
            privates = (
                {seat.id: runner.engine.private_state(seat.id) for seat in runner.seats}
                if runner
                else match.get("privates") or {}
            )
            await ws.send_json(
                {
                    "type": "snapshot",
                    "match_id": match_id,
                    "status": "running" if runner and runner.is_active() else match.get("status"),
                    "match": {k: match[k] for k in ("id", "game_id", "title", "seats", "config", "result")},
                    "state": snapshot,
                    "privates": privates,
                    "reads": runner.reads if runner else {},
                    "events": store.get_events(match_id),
                }
            )
            while True:
                message = await ws.receive_text()
                if message == "ping":
                    await ws.send_json({"type": "pong", "time": time.time()})
                    continue
                try:
                    data = json.loads(message)
                except (TypeError, ValueError):
                    continue
                if isinstance(data, dict) and data.get("type") == "speech_done":
                    acks.done(str(data.get("speech_id") or ""))
                elif isinstance(data, dict) and data.get("type") == "voice_fallback":
                    # 前端没有浏览器语音引擎（常见于桌面 WebView2），本局改用系统 TTS。
                    runner = manager.get(match_id)
                    if runner is not None and (runner.voice.get("provider") or "browser") == "browser":
                        runner.voice_provider = "system"
        except WebSocketDisconnect:
            pass
        finally:
            hub.leave(match_id, ws)

    return app
