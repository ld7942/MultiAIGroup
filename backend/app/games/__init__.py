"""游戏注册表：新增游戏只需实现 GameEngine 并在这里注册。"""
from __future__ import annotations

import random

from ..engine import GameEngine, Seat
from .doudizhu import DoudizhuEngine
from .sanguosha import SanguoshaEngine
from .werewolf import WerewolfEngine

ENGINES: dict[str, type[GameEngine]] = {
    engine.game_id: engine for engine in (WerewolfEngine, DoudizhuEngine, SanguoshaEngine)
}


def list_games() -> list[dict]:
    return [
        {
            "id": engine.game_id,
            "name": engine.name,
            "description": engine.description,
            "min_players": engine.min_players,
            "max_players": engine.max_players,
            "allowed_counts": list(engine.allowed_counts),
            "presets": engine.presets,
            "rules": engine.rules,
        }
        for engine in ENGINES.values()
    ]


def create_engine(
    game_id: str,
    seats: list[Seat],
    config: dict | None = None,
    rng: random.Random | None = None,
) -> GameEngine:
    engine_cls = ENGINES.get(game_id)
    if engine_cls is None:
        raise ValueError(f"未知游戏 {game_id}，可选：{', '.join(ENGINES)}")
    return engine_cls(seats, config, rng)
