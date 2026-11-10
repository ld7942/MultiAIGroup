import asyncio
from pathlib import Path

import pytest

from app.ai import AIClient, config_from_row
from app.engine import Seat
from app.plugins import ENGINES, create_engine
from app.plugins.doudizhu import analyze, beats, make_card
from app.runner import GameRunner
from app.store import Store


def make_seats(count: int) -> list[Seat]:
    return [
        Seat(
            id=f"s{i + 1}",
            name=f"AI {i + 1}",
            provider_id="mock",
            provider_name="mock",
            model="mock-1",
            color="#7c9cff",
        )
        for i in range(count)
    ]


# ---------------- 牌型 ----------------
def test_doudizhu_card_analysis():
    assert analyze([make_card(5, "S")])["kind"] == "single"
    assert analyze([make_card(5, "S"), make_card(5, "H")])["kind"] == "pair"
    assert analyze([make_card(5, s) for s in "SHC"])["kind"] == "triple"
    assert analyze([make_card(5, s) for s in "SHC"] + [make_card(9, "S")])["kind"] == "triple_single"
    assert analyze([make_card(r, "S") for r in range(3, 8)])["kind"] == "straight"
    assert analyze([make_card(r, s) for r in (3, 4, 5) for s in "SH"])["kind"] == "straight_pairs"
    assert analyze([make_card(8, s) for s in "SHCD"])["kind"] == "bomb"
    assert analyze([make_card(16, "J"), make_card(17, "J")])["kind"] == "rocket"
    assert analyze([make_card(3, "S"), make_card(4, "S")]) is None


def test_doudizhu_beats_rules():
    single5 = analyze([make_card(5, "S")])
    single9 = analyze([make_card(9, "S")])
    bomb = analyze([make_card(8, s) for s in "SHCD"])
    rocket = analyze([make_card(16, "J"), make_card(17, "J")])
    assert beats(single9, single5)
    assert not beats(single5, single9)
    assert beats(bomb, single9)
    assert beats(rocket, bomb)
    assert not beats(bomb, rocket)


# ---------------- 可见性 ----------------
def test_werewolf_roles_are_private():
    engine = create_engine("werewolf", make_seats(6))
    engine.start()
    own = [e for e in engine.events_for("s1") if e.type == "role_assigned"]
    other = [e for e in engine.events_for("s2") if e.type == "role_assigned"]
    assert len(own) == 1 and len(other) == 1
    assert own[0].seq != other[0].seq
    assert own[0].visibility.scope == "private"
    assert engine.private_state("s1")["role"] != ""


def test_sanguosha_lord_is_public():
    engine = create_engine("sanguosha", make_seats(4))
    engine.start()
    state = engine.public_state()
    assert state["seats"], "公开状态应包含座位信息"
    lord = [s for s in state["seats"] if s["role"] == "主公"]
    assert len(lord) == 1
    assert engine.private_state(lord[0]["id"])["role"] == "lord"


# ---------------- Mock 全流程 ----------------
async def run_mock_match(game_id: str, count: int, tmp_path: Path) -> GameRunner:
    store = Store(tmp_path / f"{game_id}.db")
    row = store.upsert_provider(
        {
            "name": "测试模拟",
            "kind": "mock",
            "base_url": "",
            "model": "mock-1",
            "api_key": "",
            "extra": {"mock_delay": 0},
        }
    )
    provider = store.get_provider(row["id"])
    assert provider
    seats = make_seats(count)
    for seat in seats:
        seat.provider_id = row["id"]
        seat.provider_name = provider["name"]
    clients = {seat.id: AIClient(config_from_row(provider)) for seat in seats}
    match = store.create_match(
        {
            "game_id": game_id,
            "title": f"测试 {game_id}",
            "seats": [seat.to_dict() for seat in seats],
            "config": {"rng_seed": 20261109},
        }
    )
    runner = GameRunner(
        match_id=match["id"],
        game_id=game_id,
        seats=seats,
        clients=clients,
        store=store,
        config=match["config"],
    )
    runner.start_task()
    assert runner.task is not None
    await asyncio.wait_for(runner.task, timeout=120)
    return runner


@pytest.mark.parametrize(
    ("game_id", "count"),
    [("doudizhu", 3), ("werewolf", 6), ("sanguosha", 4)],
)
@pytest.mark.asyncio
async def test_mock_match_finishes(game_id, count, tmp_path):
    runner = await run_mock_match(game_id, count, tmp_path)
    assert runner.engine.finished, f"{game_id} 未正常结束"
    assert runner.engine.result is not None
    events = runner.engine.events_for("s1")
    assert any(ev.type == "game_over" for ev in events)
    assert len(runner.store.get_events(runner.match_id)) >= 5


@pytest.mark.asyncio
async def test_prompt_isolation(tmp_path):
    """每个座位拿到的上下文不包含其他座位的私有信息。"""
    runner = await run_mock_match("werewolf", 6, tmp_path)
    for seat in runner.seats:
        events = runner.engine.events_for(seat.id)
        for ev in events:
            if ev.type == "role_assigned":
                assert ev.visibility.seats == (seat.id,)
