"""FastAPI 接口层：REST + WebSocket。"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .ai import PRESETS, AIClient, config_from_row
from .engine import Seat
from .games import ENGINES, create_engine, list_games
from .runner import RunnerManager
from .store import Store

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
    extra: dict = Field(default_factory=dict)


class GroupIn(BaseModel):
    name: str = "我的 AI 群组"
    members: list[dict] = Field(default_factory=list)


class SeatIn(BaseModel):
    name: str
    provider_id: str
    persona: str = ""
    color: str | None = None


class MatchIn(BaseModel):
    game_id: str
    title: str = ""
    seats: list[SeatIn]
    config: dict = Field(default_factory=dict)


class Hub:
    def __init__(self) -> None:
        self.channels: dict[str, set[WebSocket]] = {}

    async def join(self, channel: str, ws: WebSocket) -> None:
        self.channels.setdefault(channel, set()).add(ws)

    def leave(self, channel: str, ws: WebSocket) -> None:
        self.channels.get(channel, set()).discard(ws)

    async def send(self, channel: str, payload: dict) -> None:
        dead = []
        for ws in list(self.channels.get(channel, set())):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.leave(channel, ws)


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
        )
        seats.append(seat)
        if provider:
            clients[seat.id] = AIClient(config_from_row(provider))
    return seats, clients


def create_app(db: Path | None = None) -> FastAPI:
    store = Store(db)
    hub = Hub()

    async def broadcast(payload: dict) -> None:
        await hub.send(str(payload.get("match_id") or "lobby"), payload)

    manager = RunnerManager(store, broadcast)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
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
        if payload.game_id not in ENGINES:
            raise HTTPException(400, f"未知游戏 {payload.game_id}")
        engine_cls = ENGINES[payload.game_id]
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
                    "events": store.get_events(match_id),
                }
            )
            while True:
                message = await ws.receive_text()
                if message == "ping":
                    await ws.send_json({"type": "pong", "time": time.time()})
        except WebSocketDisconnect:
            pass
        finally:
            hub.leave(match_id, ws)

    return app
