import random
from pathlib import Path

import pytest

from app.engine import ActionError, Seat
from app.plugins import create_engine
from app.runner import GameRunner
from app.store import Store


def make_seats(count: int) -> list[Seat]:
    return [
        Seat(id=f"s{i + 1}", name=f"AI {i + 1}", provider_id="mock", provider_name="mock", model="mock-1")
        for i in range(count)
    ]


def test_werewolf_role_skill_and_speech_validation(tmp_path: Path):
    seats = make_seats(6)
    engine = create_engine("werewolf", seats, {}, random.Random(7))
    engine.start()

    witch = next(seat_id for seat_id, role in engine.roles.items() if role == "witch")
    wolf = next(seat_id for seat_id, role in engine.roles.items() if role == "werewolf")

    witch_skill = engine.skill_for(witch)
    assert "绝不能毒自己" in witch_skill
    assert "毒药" in witch_skill

    chat = engine.request(wolf, "werewolf_chat", "狼人密谈", "讨论今晚目标")
    assert "必须发言" in engine.action_hint(chat, wolf)
    assert "不要刀队友" in engine.action_hint(chat, wolf)

    whisper = engine.request(wolf, "day_speech", "白天发言", "表水")
    with pytest.raises(ActionError):
        engine.validate(whisper, {"speech": "   "})
    fallback = engine.fallback_action(whisper)
    engine.validate(whisper, fallback)
    assert str(fallback["speech"]).strip()

    wolf_chat = engine.request(wolf, "werewolf_chat", "狼人密谈", "讨论今晚目标")
    with pytest.raises(ActionError):
        engine.validate(wolf_chat, {"speech": ""})
    fallback = engine.fallback_action(wolf_chat)
    engine.validate(wolf_chat, fallback)
    assert str(fallback["speech"]).strip()


def test_witch_cannot_poison_self(tmp_path: Path):
    seats = make_seats(6)
    engine = create_engine("werewolf", seats, {}, random.Random(7))
    engine.start()
    witch = next(seat_id for seat_id, role in engine.roles.items() if role == "witch")
    req = engine.request(witch, "witch_action", "女巫行动", "选择用药")
    with pytest.raises(ActionError):
        engine.validate(req, {"save": False, "poison": witch})


def test_card_games_expose_skill_and_hint(tmp_path: Path):
    doudizhu = create_engine("doudizhu", make_seats(3), {}, random.Random(3))
    doudizhu.start()
    bid = doudizhu.request("s1", "bid", "叫地主", "选择叫分")
    assert "叫分" in doudizhu.action_hint(bid, "s1")
    assert "叫地主" in doudizhu.skill_for("s1")

    sanguosha = create_engine("sanguosha", make_seats(4), {}, random.Random(3))
    sanguosha.start()
    seat_id = sanguosha.seats[0].id
    play = sanguosha.request(seat_id, "sgs_play", "出牌阶段", "选择一张牌")
    assert "杀" in sanguosha.action_hint(play, seat_id)
    assert sanguosha.skill_for(seat_id)


def test_system_prompt_contains_skill_card_and_protocol(tmp_path: Path):
    store = Store(tmp_path / "strategy.db")
    seats = make_seats(6)
    runner = GameRunner(
        match_id="m-strategy",
        game_id="werewolf",
        seats=seats,
        clients={},
        store=store,
    )
    runner.engine.start()
    prompt = runner.system_prompt(seats[0].id)
    assert "玩法和决策流程" in prompt or "决策流程" in prompt
    assert "玩法技能卡" in prompt
    assert "plan" in prompt and "stance" in prompt
