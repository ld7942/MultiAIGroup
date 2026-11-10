"""牌类游戏公共基类。

统一“桌面最近出牌 / 手牌取牌”的表示与操作，让前端用同一套牌桌界面
（座位手牌、中央出牌区）渲染所有棋牌插件。新增棋牌只需继承
:class:`CardGameEngine`，并保持 ``private_state["hand"]`` 为卡牌列表。
"""
from __future__ import annotations

from .engine import GameEngine, table_play


class CardGameEngine(GameEngine):
    """有牌堆 / 手牌 / 桌面出牌的棋牌基类。"""

    capabilities = {"hand": True, "items": False, "table_cards": True, "hidden_roles": False}

    def __init__(self, seats, config: dict | None = None, rng=None):
        super().__init__(seats, config, rng)
        self.last_play: dict | None = None
        # 桌面展示用：last_play 可能因规则被清空（例如两家过牌），recent_play 保留最近一手。
        self.recent_play: dict | None = None

    def record_play(
        self,
        seat_id: str,
        cards: list,
        *,
        kind: str = "",
        target: str | None = None,
        round_no: int | None = None,
        extra: dict | None = None,
    ) -> dict:
        """记录一次出牌，同时更新桌面展示用的 recent_play。"""
        play = table_play(seat_id, cards, kind=kind, target=target, round_no=round_no)
        if extra:
            play.update(extra)
        self.last_play = play
        self.recent_play = play
        return play

    def clear_play(self) -> None:
        """清空本手牌（例如斗地主两家过牌），recent_play 仍保留给牌桌展示。"""
        self.last_play = None

    @staticmethod
    def take_card(hand: list[dict], card_id: str) -> dict | None:
        """从手牌中取出一张牌，找不到返回 None。"""
        for index, card in enumerate(hand):
            if card.get("id") == card_id:
                return hand.pop(index)
        return None
