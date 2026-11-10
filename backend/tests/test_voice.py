import asyncio
from pathlib import Path

from app.ai import AIClient, config_from_row
from app.api import _build_seats
from app.engine import Seat, Visibility
from app.runner import GameRunner
from app.store import Store
from app.voice import load_voice, save_voice


def make_seats(count: int) -> list[Seat]:
    return [
        Seat(id=f"s{i + 1}", name=f"AI {i + 1}", provider_id="mock", provider_name="mock", model="mock-1")
        for i in range(count)
    ]


def test_voice_defaults_and_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "voice.db")
    cfg = load_voice(store)
    assert cfg["enabled"] is False
    assert cfg["provider"] == "browser"

    saved = save_voice(
        store,
        {"enabled": True, "narrator_voice_id": "narr", "voicestudio": {"url": "http://tts.local"}},
    )
    assert saved["enabled"] is True
    assert saved["voicestudio"]["url"] == "http://tts.local"
    # 深合并保留未提交的默认字段
    assert saved["voicestudio"]["text_field"] == "text"
    assert load_voice(store)["narrator_voice_id"] == "narr"


def test_seat_voice_overrides_provider(tmp_path: Path):
    store = Store(tmp_path / "seats.db")
    provider = store.upsert_provider(
        {
            "name": "带音色的模拟",
            "kind": "mock",
            "base_url": "",
            "model": "mock-1",
            "api_key": "",
            "voice_id": "provider-voice",
        }
    )
    seats, clients = _build_seats(
        {
            "seats": [
                {"id": "a", "name": "A", "provider_id": provider["id"], "voice_id": ""},
                {"id": "b", "name": "B", "provider_id": provider["id"], "voice_id": "seat-voice"},
            ]
        },
        store,
    )
    assert seats[0].voice_id == "provider-voice"
    assert seats[1].voice_id == "seat-voice"
    assert set(clients) == {"a", "b"}


def test_voice_lines_are_public_and_role_aware(tmp_path: Path):
    store = Store(tmp_path / "runner.db")
    seats = make_seats(6)
    seats[0].voice_id = "seat-voice"
    runner = GameRunner(
        match_id="m1",
        game_id="werewolf",
        seats=seats,
        clients={},
        store=store,
        voice={"enabled": True, "default_voice_id": "default-voice", "narrator_voice_id": "narrator-voice"},
    )
    runner.engine.start()
    events = runner.engine.take_events()

    start = [ev for ev in events if ev.type == "game_start"][0]
    line = runner.voice_line(start)
    assert line and line["role"] == "narrator" and line["voice_id"] == "narrator-voice"
    assert all(
        runner.voice_line(ev) is None for ev in events if ev.type == "role_assigned"
    )

    runner.engine.say("s1", "我怀疑 3 号")
    line = runner.voice_line(runner.engine.take_events()[-1])
    assert line == {"text": "我怀疑 3 号", "voice_id": "seat-voice", "role": "seat", "seat_id": "s1"}

    runner.engine.say("s1", "今晚杀他", Visibility.group("s1"))
    assert runner.voice_line(runner.engine.take_events()[-1]) is None


def test_voice_api_roundtrip(tmp_path: Path):
    from fastapi.testclient import TestClient

    from app.api import create_app

    app = create_app(tmp_path / "api.db")
    with TestClient(app) as client:
        data = client.get("/api/voice").json()
        assert data["enabled"] is False
        saved = client.put(
            "/api/voice", json={"enabled": True, "narrator_voice_id": "narr"}
        ).json()
        assert saved["enabled"] is True
        assert saved["narrator_voice_id"] == "narr"


class FakeAcks:
    def __init__(self) -> None:
        self.prepared: list[str] = []

    def prepare(self, speech_id: str) -> None:
        self.prepared.append(speech_id)

    async def wait(self, speech_id: str, timeout: float) -> None:
        return None


async def test_voice_events_are_broadcast_in_order(tmp_path: Path):
    store = Store(tmp_path / "voice-match.db")
    row = store.upsert_provider(
        {
            "name": "模拟",
            "kind": "mock",
            "base_url": "",
            "model": "mock-1",
            "api_key": "",
            "extra": {"mock_delay": 0},
        }
    )
    provider = store.get_provider(row["id"])
    assert provider
    seats = make_seats(3)
    for seat in seats:
        seat.provider_id = row["id"]
        seat.provider_name = provider["name"]
    clients = {seat.id: AIClient(config_from_row(provider)) for seat in seats}
    voices: list[dict] = []

    async def broadcast(payload: dict) -> None:
        if payload.get("type") == "voice":
            voices.append(payload)

    acks = FakeAcks()
    runner = GameRunner(
        match_id="m-voice",
        game_id="doudizhu",
        seats=seats,
        clients=clients,
        store=store,
        broadcast=broadcast,
        config={"rng_seed": 20261109},
        voice={"enabled": True, "default_voice_id": "all", "narrator_voice_id": "narr"},
        acks=acks,
        has_clients=lambda match_id: True,
    )
    runner.start_task()
    assert runner.task is not None
    await asyncio.wait_for(runner.task, timeout=120)

    assert runner.engine.finished
    assert voices, "开启语音后应产生 voice 事件"
    assert len(acks.prepared) == len(voices)
    assert any(v["role"] == "narrator" and v["voice_id"] == "narr" for v in voices)
    assert any(v["role"] == "seat" and v["voice_id"] == "all" for v in voices)
    assert all(v["text"].strip() for v in voices)
    # 聊天先于出牌：同一座位存在 speech 的 seq 小于 play 的 seq
    order = [(v["seat_id"], v["seq"], v["text"]) for v in voices]
    assert order == sorted(order, key=lambda item: item[1])


def test_speech_bus_waits_for_ack(tmp_path: Path):
    from app.api import SpeechAcks

    async def scenario():
        acks = SpeechAcks()
        acks.prepare("sp1")
        task = asyncio.create_task(acks.wait("sp1", timeout=5))
        await asyncio.sleep(0.05)
        acks.done("sp1")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())
