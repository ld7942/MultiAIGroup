import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.engine import ActionRequest, GameEvent, Seat, Visibility
from app.rag import (
    add_memory,
    compress_events,
    cosine,
    embed,
    key_moments,
    load_rag,
    save_rag,
    search,
    seed_skills,
)
from app.runner import GameRunner
from app.store import Store


def make_seats(count: int = 9) -> list[Seat]:
    return [
        Seat(id=f"s{i + 1}", name=f"AI {i + 1}", provider_id="mock", provider_name="mock", model="mock-1")
        for i in range(count)
    ]


def test_embed_is_normalized_and_similar():
    vector = embed("女巫毒药不能毒自己")
    assert abs(sum(v * v for v in vector) - 1.0) < 1e-6
    assert cosine(vector, embed("女巫毒药不能毒自己")) > 0.99
    assert cosine(vector, embed("地主应该保留炸弹")) < 0.9


def test_seed_skills_is_idempotent(tmp_path: Path):
    store = Store(tmp_path / "rag.db")
    first = seed_skills(store)
    total = store.count_memories()
    second = seed_skills(store)
    assert first > 0
    assert second == first
    assert store.count_memories() == total
    assert total >= first


def test_search_filters_by_game_and_role(tmp_path: Path):
    store = Store(tmp_path / "rag.db")
    add_memory(
        store,
        "女巫的毒药绝不能毒自己，信息不足时宁可不用。",
        game_id="werewolf",
        role="女巫",
        kind="skill",
    )
    add_memory(
        store,
        "地主应该保留炸弹，农民手牌少时优先拦截。",
        game_id="doudizhu",
        role="地主",
        kind="skill",
    )
    results = search(
        store, "女巫毒药应该给谁", game_id="werewolf", role="女巫", top_k=5, min_score=0.0
    )
    assert results
    assert all(item["game_id"] in {"werewolf", ""} for item in results)
    assert all(item["role"] in {"女巫", "通用", ""} for item in results)
    assert "毒药" in results[0]["text"]


def test_compress_events_keeps_tail_and_summary():
    events = [
        GameEvent(
            seq=i,
            ts=0.0,
            type="speech" if i % 3 else "death",
            text=f"事件 {i}",
            payload={},
            visibility=Visibility.public(),
            seat_id=None,
            round=1,
            phase="day",
        )
        for i in range(200)
    ]
    compressed = compress_events(events, head=5, tail=20)
    assert "已压缩" in compressed
    assert "事件 199" in compressed
    assert "事件 0" in compressed
    assert len(compressed.splitlines()) < 60
    assert key_moments(events, 3)


def test_rag_config_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "rag.db")
    cfg = load_rag(store)
    assert cfg["enabled"] is True
    saved = save_rag(store, {"top_k": 7, "min_score": 0.2})
    assert saved["top_k"] == 7
    assert saved["min_score"] == 0.2
    assert load_rag(store)["top_k"] == 7


def test_runner_injects_memories(tmp_path: Path):
    store = Store(tmp_path / "rag.db")
    add_memory(
        store,
        "狼人每晚要统一袭击目标，优先刀神职，不要刀队友。",
        game_id="werewolf",
        role="狼人",
        kind="manual",
    )
    runner = GameRunner(
        match_id="m1",
        game_id="werewolf",
        seats=make_seats(9),
        clients={},
        store=store,
        rag={"enabled": True, "top_k": 2, "min_score": 0.0},
    )
    runner.engine.start()
    wolf = runner.engine.wolves[0]
    request = ActionRequest(
        id="r1",
        seat_id=wolf,
        kind="werewolf_chat",
        title="狼人密谈",
        instruction="请提出今晚的袭击目标",
    )
    messages = runner.build_messages(request, runner.seat_map[wolf])
    joined = "\n".join(message["content"] for message in messages)
    assert "RAG 记忆库" in joined
    assert "统一袭击目标" in joined


def test_runner_reflect_writes_lessons(tmp_path: Path):
    store = Store(tmp_path / "rag.db")
    runner = GameRunner(
        match_id="m1",
        game_id="werewolf",
        seats=make_seats(9),
        clients={},
        store=store,
        rag={"enabled": True, "reflect": True, "llm_reflect": False},
    )
    runner.engine.start()
    runner.engine.finished = True
    runner.engine.result = {"winner": "好人阵营", "reason": "狼人全部出局"}
    asyncio.run(runner.reflect())
    assert runner.review
    assert any(runner.review.values())
    lessons = store.list_memories(game_id="werewolf", kind="lesson", limit=100)
    assert lessons


def test_rag_api(tmp_path: Path):
    app = create_app(tmp_path / "api.db")
    with TestClient(app) as client:
        cfg = client.get("/api/rag").json()
        assert cfg["enabled"] is True
        assert cfg["total"] >= 16

        hits = client.get(
            "/api/rag/search", params={"q": "女巫的毒药怎么用", "game_id": "werewolf"}
        ).json()
        assert hits
        assert "embedding" not in hits[0]

        created = client.post(
            "/api/rag/memories",
            json={
                "text": "猎人被毒杀时不能开枪。",
                "game_id": "werewolf",
                "role": "猎人",
                "kind": "manual",
            },
        ).json()
        assert created["text"].startswith("猎人")

        listed = client.get(
            "/api/rag/memories", params={"game_id": "werewolf", "role": "猎人"}
        ).json()
        assert any(item["id"] == created["id"] for item in listed)

        assert client.delete(f"/api/rag/memories/{created['id']}").json()["ok"] is True
        saved = client.put("/api/rag", json={"top_k": 6, "reflect": False}).json()
        assert saved["top_k"] == 6
        assert saved["reflect"] is False

