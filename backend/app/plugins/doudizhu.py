from __future__ import annotations

from collections import Counter
from typing import Iterable

from ..engine import ActionError, ActionOption, ActionRequest, GameEngine, Seat, Visibility

SUITS = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
RANK_LABEL = {
    3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10",
    11: "J", 12: "Q", 13: "K", 14: "A", 15: "2", 16: "小王", 17: "大王",
}


def make_card(rank: int, suit: str) -> dict:
    cid = f"{RANK_LABEL[rank]}{suit}" if rank <= 15 else ("SJ" if rank == 16 else "BJ")
    label = "小王" if rank == 16 else "大王" if rank == 17 else f"{SUITS[suit]}{RANK_LABEL[rank]}"
    return {"id": cid, "rank": rank, "suit": suit, "label": label}


def build_deck() -> list[dict]:
    deck = [make_card(rank, suit) for rank in range(3, 16) for suit in "SHDC"]
    deck.append(make_card(16, "J"))
    deck.append(make_card(17, "J"))
    return deck


def card_sort_key(card: dict):
    return (card["rank"], "SHDC".index(card["suit"]) if card["suit"] in "SHDC" else 9)


def _consecutive(ranks: Iterable[int]) -> bool:
    values = sorted(ranks)
    return all(values[i] + 1 == values[i + 1] for i in range(len(values) - 1))


def analyze(cards: list[dict]) -> dict | None:
    """识别牌型，返回 {kind, rank, length}；非法牌型返回 None。"""
    if not cards:
        return None
    counts = Counter(c["rank"] for c in cards)
    ranks = sorted(counts)
    n = len(cards)
    if n == 2 and ranks == [16, 17]:
        return {"kind": "rocket", "rank": 99, "length": 1}
    if n == 4 and len(counts) == 1:
        return {"kind": "bomb", "rank": ranks[0], "length": 1}
    if n == 1:
        return {"kind": "single", "rank": ranks[0], "length": 1}
    if n == 2 and len(counts) == 1:
        return {"kind": "pair", "rank": ranks[0], "length": 1}
    if n == 3 and len(counts) == 1:
        return {"kind": "triple", "rank": ranks[0], "length": 1}
    if n == 4 and len(counts) == 2 and max(counts.values()) == 3:
        return {"kind": "triple_single", "rank": ranks[0] if counts[ranks[0]] == 3 else ranks[1], "length": 1}
    if n == 5 and sorted(counts.values()) == [2, 3]:
        triple = [r for r, v in counts.items() if v == 3][0]
        return {"kind": "triple_pair", "rank": triple, "length": 1}
    if n >= 5 and all(v == 1 for v in counts.values()) and ranks[-1] <= 14 and _consecutive(ranks):
        return {"kind": "straight", "rank": ranks[-1], "length": n}
    if n >= 6 and n % 2 == 0 and all(v == 2 for v in counts.values()) and ranks[-1] <= 14 and _consecutive(ranks):
        return {"kind": "straight_pairs", "rank": ranks[-1], "length": n // 2}
    if n >= 6 and n % 3 == 0 and all(v == 3 for v in counts.values()) and ranks[-1] <= 14 and _consecutive(ranks):
        return {"kind": "airplane", "rank": ranks[-1], "length": n // 3}
    if n == 6 and max(counts.values()) == 4:
        quad = [r for r, v in counts.items() if v == 4][0]
        return {"kind": "four_two_single", "rank": quad, "length": 1}
    if n == 8 and max(counts.values()) == 4 and sorted(counts.values()) == [2, 2, 4]:
        quad = [r for r, v in counts.items() if v == 4][0]
        return {"kind": "four_two_pair", "rank": quad, "length": 1}
    # 飞机带翅膀
    triple_ranks = sorted(r for r, v in counts.items() if v >= 3 and r <= 14)
    for size in (2, 3, 4):
        for i in range(len(triple_ranks) - size + 1):
            run = triple_ranks[i : i + size]
            if not _consecutive(run):
                continue
            if n == size * 4:
                rest = []
                for r in counts:
                    rest.extend([r] * (counts[r] - (3 if r in run else 0)))
                if len(rest) == size and all(r not in run for r in rest):
                    return {"kind": "airplane_single", "rank": run[-1], "length": size}
            if n == size * 5:
                rest = []
                for r in counts:
                    rest.extend([r] * (counts[r] - (3 if r in run else 0)))
                rc = Counter(rest)
                if len(rest) == size * 2 and all(v == 2 for v in rc.values()) and len(rc) == size and all(r not in run for r in rc):
                    return {"kind": "airplane_pair", "rank": run[-1], "length": size}
    return None


def beats(candidate: dict, last: dict | None) -> bool:
    if not last:
        return True
    if candidate["kind"] == "rocket":
        return True
    if last["kind"] == "rocket":
        return False
    if candidate["kind"] == "bomb" and last["kind"] != "bomb":
        return True
    if last["kind"] == "bomb" and candidate["kind"] != "bomb":
        return False
    if candidate["kind"] != last["kind"] or candidate["length"] != last["length"]:
        return False
    return candidate["rank"] > last["rank"]


def enumerate_plays(hand: list[dict]) -> list[dict]:
    """枚举手牌中所有可出牌型，返回 [{cards, kind, rank, length}]。"""
    by_rank: dict[int, list[dict]] = {}
    for card in sorted(hand, key=card_sort_key):
        by_rank.setdefault(card["rank"], []).append(card)
    plays: list[dict] = []

    def add(cards: list[dict]):
        info = analyze(cards)
        if info:
            plays.append({**info, "cards": cards})

    for rank, group in by_rank.items():
        add(group[:1])
        if len(group) >= 2:
            add(group[:2])
        if len(group) >= 3:
            add(group[:3])
            others = [c for c in hand if c["rank"] != rank]
            singles = sorted(others, key=card_sort_key)
            if singles:
                add(group[:3] + singles[:1])
            pairs = [c for r, g in by_rank.items() if r != rank and len(g) >= 2 for c in g[:2]]
            pairs.sort(key=card_sort_key)
            if len(pairs) >= 2:
                add(group[:3] + pairs[:2])
        if len(group) >= 4:
            add(group[:4])
            others = sorted([c for c in hand if c["rank"] != rank], key=card_sort_key)
            if len(others) >= 2:
                add(group[:4] + others[:2])
            pair_groups = [g[:2] for r, g in sorted(by_rank.items()) if r != rank and len(g) >= 2]
            if len(pair_groups) >= 2:
                add(group[:4] + pair_groups[0] + pair_groups[1])

    if 16 in by_rank and 17 in by_rank:
        add([by_rank[16][0], by_rank[17][0]])

    # 顺子
    straight_ranks = [r for r in sorted(by_rank) if r <= 14]
    for i in range(len(straight_ranks)):
        run = [straight_ranks[i]]
        for r in straight_ranks[i + 1 :]:
            if r == run[-1] + 1:
                run.append(r)
            else:
                break
        for size in range(5, len(run) + 1):
            add([by_rank[r][0] for r in run[:size]])
    # 连对
    pair_ranks = [r for r in sorted(by_rank) if len(by_rank[r]) >= 2 and r <= 14]
    for i in range(len(pair_ranks)):
        run = [pair_ranks[i]]
        for r in pair_ranks[i + 1 :]:
            if r == run[-1] + 1:
                run.append(r)
            else:
                break
        for size in range(3, len(run) + 1):
            add([c for r in run[:size] for c in by_rank[r][:2]])
    # 飞机
    triple_ranks = [r for r in sorted(by_rank) if len(by_rank[r]) >= 3 and r <= 14]
    for i in range(len(triple_ranks)):
        run = [triple_ranks[i]]
        for r in triple_ranks[i + 1 :]:
            if r == run[-1] + 1:
                run.append(r)
            else:
                break
        for size in range(2, len(run) + 1):
            core = run[:size]
            core_cards = [c for r in core for c in by_rank[r][:3]]
            add(core_cards)
            rest = sorted([c for c in hand if c["rank"] not in core], key=card_sort_key)
            if len(rest) >= size:
                add(core_cards + rest[:size])
            rest_pairs = [g[:2] for r, g in sorted(by_rank.items()) if r not in core and len(g) >= 2]
            if len(rest_pairs) >= size:
                add(core_cards + [c for g in rest_pairs[:size] for c in g])
    # 去重
    unique: dict[tuple, dict] = {}
    for play in plays:
        key = tuple(sorted(c["id"] for c in play["cards"]))
        unique[key] = play
    return list(unique.values())


BID_SKILL = """【叫地主】先评价手牌强度：有王、2 多、炸弹或长顺子可以叫高分；牌散、缺大牌则不叫。
- 叫分必须高于当前最高分；不确定时叫 1 分试探。
- 不要为了抢地主而叫超过手牌承受能力的分。"""

LANDLORD_SKILL = """【地主】目标：先出完手牌。
- 主动控场：优先走小牌和单张，保留 2、王、炸弹应对关键回合。
- 记牌：关注两位农民已经出过的大牌，判断自己的牌是否最大。
- 不要为了压一手小牌拆散对子、顺子或飞机；能一次走多张就一次走。
- 农民手牌少时要果断拦截，必要时用炸弹。"""

FARMER_SKILL = """【农民】目标：配合队友，让任意一个农民先出完。
- 队友出牌时尽量过牌，不要压队友；只有能直接走完或必须压制地主时才接。
- 地主手牌少时必须拦截，优先出能压制地主的最小牌型。
- 记住队友出过什么，尽量给队友创造走牌机会。
- 炸弹留给地主即将走完或队友需要接力的关键回合。"""


class DoudizhuEngine(GameEngine):
    game_id = "doudizhu"
    name = "斗地主"
    description = "三人斗地主：叫地主、抢底牌，完整牌型与炸弹王炸判定。"
    min_players = 3
    max_players = 3
    allowed_counts = (3,)
    presets = [{"id": "classic", "name": "经典三人局", "players": 3, "description": "地主 vs 两位农民"}]
    rules = """斗地主（经典三人规则）
【发牌】一副 54 张牌，每人 17 张，留 3 张底牌。
【叫地主】按顺序叫分（0=不叫，1/2/3 分），叫分最高者成为地主并获得 3 张底牌；若无人叫地主则重新发牌。
【出牌】地主先出。每轮可以出比上家更大的同类型牌，或炸弹/王炸，也可以过牌；连续两家过牌后，由最后出牌者重新领出。
【牌型】单张、对子、三张、三带一、三带二、顺子（≥5 张连续单牌）、连对（≥3 组连续对子）、飞机（连续三张，可带同数量单牌或对子）、四带二（两单或两对）、炸弹（四张相同）、王炸（双王）。
【比较】同类型同长度比较点数；炸弹大过普通牌型，炸弹之间比点数，王炸最大。2 不能参与顺子/连对/飞机。
【胜利】地主先出完牌则地主胜；任意一位农民先出完则农民方胜。"""

    def __init__(self, seats: list[Seat], config: dict | None = None, rng=None):
        super().__init__(seats, config, rng)
        if len(seats) != 3:
            raise ValueError("斗地主需要 3 名玩家")
        self.hands: dict[str, list[dict]] = {s.id: [] for s in seats}
        self.bottom: list[dict] = []
        self.landlord: str | None = None
        self.turn: str | None = None
        self.last_play: dict | None = None
        self.last_player: str | None = None
        self.passes = 0
        self.bid_queue: list[str] = []
        self.bids: dict[str, int] = {}
        self.current_bid = 0
        self.highest_bidder: str | None = None
        self.redeals = 0
        self.stage = "bid"
        self.bid_seq = 0

    # ---------------- 发牌 ----------------
    def _deal(self) -> None:
        deck = build_deck()
        self.rng.shuffle(deck)
        for idx, seat in enumerate(self.seats):
            self.hands[seat.id] = sorted(deck[idx * 17 : (idx + 1) * 17], key=card_sort_key)
        self.bottom = sorted(deck[51:], key=card_sort_key)
        self.landlord = None
        self.turn = None
        self.last_play = None
        self.last_player = None
        self.passes = 0
        self.bids = {}
        self.current_bid = 0
        self.highest_bidder = None
        for seat in self.seats:
            self.emit(
                "hand_dealt",
                f"你的手牌：{' '.join(c['label'] for c in self.hands[seat.id])}",
                visibility=Visibility.private(seat.id),
                seat_id=seat.id,
                cards=[c["id"] for c in self.hands[seat.id]],
            )

    def start(self) -> None:
        self.emit("game_start", "斗地主开始，正在发牌。")
        self._deal()
        start_index = self.rng.randrange(3)
        self.bid_queue = [self.seats[(start_index + i) % 3].id for i in range(3)]
        self.phase = "叫地主"
        self.emit("phase", f"叫地主阶段：从 {self.seat_map[self.bid_queue[0]].name} 开始叫分。")
        self.stage = "bid"

    # ---------------- 状态机 ----------------
    def advance(self) -> None:
        for _ in range(400):
            if self.finished or self._requests or self._waiting:
                return
            if self.stage == "bid":
                if self.current_bid >= 3:
                    self.stage = "assign"
                    continue
                if self.bid_queue:
                    sid = self.bid_queue.pop(0)
                    options = [ActionOption("bid_0", "不叫", {"bid": 0})]
                    for value in range(self.current_bid + 1, 4):
                        options.append(ActionOption(f"bid_{value}", f"叫 {value} 分", {"bid": value}))
                    self.phase = "叫地主"
                    self.request(
                        sid,
                        "bid",
                        "叫地主",
                        f"当前最高叫分：{self.current_bid}。选择叫分（必须高于当前最高分）或不叫。",
                        options=options,
                        action_schema={"bid": "0-3 的整数，0 表示不叫"},
                    )
                    return
                if not self.highest_bidder:
                    self.redeals += 1
                    if self.redeals >= 3:
                        self.highest_bidder = self.rng.choice([s.id for s in self.seats])
                        self.emit("bid_result", f"连续无人叫地主，随机指定 {self.seat_map[self.highest_bidder].name} 为地主。")
                        self.stage = "assign"
                    else:
                        self.emit("bid_result", "无人叫地主，重新发牌。")
                        self._deal()
                        start_index = self.rng.randrange(3)
                        self.bid_queue = [self.seats[(start_index + i) % 3].id for i in range(3)]
                        self.stage = "bid"
                    continue
                self.stage = "assign"
            elif self.stage == "assign":
                self._assign_landlord()
            elif self.stage == "play":
                if not self.turn:
                    return
                self._play_request()
                return
            else:
                return
        raise RuntimeError("斗地主状态机步数超限")

    def _assign_landlord(self) -> None:
        self.landlord = self.highest_bidder or self.seats[0].id
        self.hands[self.landlord] = sorted(self.hands[self.landlord] + self.bottom, key=card_sort_key)
        self.turn = self.landlord
        self.phase = "出牌"
        self.emit(
            "landlord",
            f"{self.seat_map[self.landlord].name} 成为地主（{self.current_bid} 分），底牌：{' '.join(c['label'] for c in self.bottom)}",
            landlord=self.landlord,
            bottom=[c["id"] for c in self.bottom],
        )
        for seat in self.seats:
            role = "地主" if seat.id == self.landlord else "农民"
            self.emit(
                "role_assigned",
                f"你的身份是【{role}】。",
                visibility=self._private(seat.id),
                seat_id=seat.id,
                role=role,
            )
        self.emit("phase", f"地主先出牌：{self.seat_map[self.landlord].name}。")
        self.stage = "play"

    def _private(self, seat_id: str):
        return Visibility.private(seat_id)

    def _play_request(self) -> None:
        sid = self.turn
        assert sid
        hand = self.hands[sid]
        last = self.last_play
        plays = [p for p in enumerate_plays(hand) if beats(p, last)]
        bombs = {"bomb", "rocket"}
        plays.sort(key=lambda p: (p["kind"] in bombs, len(p["cards"]), p["rank"]))
        options: list[ActionOption] = []
        if last:
            options.append(ActionOption("pass", "过牌", {"pass": True}, "不要这一手"))
        for idx, play in enumerate(plays[:48]):
            label = " ".join(c["label"] for c in play["cards"])
            kind = play["kind"]
            options.append(
                ActionOption(
                    f"play_{idx}",
                    f"出 {label}（{kind}）",
                    {"cards": [c["id"] for c in play["cards"]]},
                    kind,
                )
            )
        self.phase = "出牌"
        last_text = "你是本轮领出者，必须出牌。" if not last else (
            f"上家 {self.seat_map[last['seat']].name} 出了 {' '.join(last['labels'])}。"
        )
        self.request(
            sid,
            "play_cards",
            "出牌",
            f"{last_text} 你可以出更大的同类型牌、炸弹/王炸，或过牌。",
            options=options,
            action_schema={"cards": "要出的牌 ID 数组，例如 ['3S','3H']；或 {\"pass\": true} 过牌"},
            meta={"hand_count": len(hand), "last": last["cards"] if last else []},
        )

    # ---------------- 玩法提示 ----------------
    @classmethod
    def skill_cards(cls) -> list[dict]:
        return [
            {"role": "叫地主", "faction": "", "text": BID_SKILL},
            {"role": "地主", "faction": "", "text": LANDLORD_SKILL},
            {"role": "农民", "faction": "", "text": FARMER_SKILL},
        ]

    def tactic_tags(self, seat_id: str) -> dict:
        if not self.landlord:
            return {"role": "叫地主", "faction": ""}
        return {"role": "地主" if seat_id == self.landlord else "农民", "faction": ""}

    def skill_for(self, seat_id: str) -> str:
        if not self.landlord:
            return BID_SKILL
        return LANDLORD_SKILL if seat_id == self.landlord else FARMER_SKILL

    def action_hint(self, req: ActionRequest, seat_id: str) -> str:
        style = self.style_for(seat_id).get("name", "")
        style_tip = {
            "激进": "你的风格偏激进：牌型不差时可以抢高分、主动压制。",
            "保守": "你的风格偏保守：牌散或缺少大牌时果断不叫、优先过牌。",
            "诡诈": "你的风格偏诡诈：可以用叫分和出牌节奏误导对手。",
            "理性": "你的风格偏理性：按手牌强度与剩余牌数计算收益，不情绪化。",
        }.get(style, "")
        if req.kind == "bid":
            return f"根据手牌强度决定叫分：有王/2/炸弹/长顺子可叫高，牌散或缺少大牌就不叫。{style_tip}"
        if req.kind == "play_cards":
            tips = ["优先出能压制上家的最小牌型，不要轻易拆散对子、顺子或飞机。"]
            last = self.last_play
            if last and self.last_player and self.landlord:
                last_seat = self.last_player
                teammate = (
                    seat_id != self.landlord
                    and last_seat != self.landlord
                    and last_seat != seat_id
                )
                if teammate:
                    tips.append("上家是你的农民队友：除非能直接走完或必须压制地主，否则优先过牌。")
                landlord_cards = len(self.hands.get(self.landlord, []))
                if seat_id != self.landlord and landlord_cards <= 5:
                    tips.append(f"地主只剩 {landlord_cards} 张牌，必须尽量拦截，必要时用炸弹。")
            elif self.landlord and seat_id == self.landlord:
                tips.append("你是地主，目标是尽快走完；保留 2、王和炸弹应对关键回合。")
            tips.append("炸弹留给地主即将走完或队友需要接力的关键回合。")
            if style_tip:
                tips.append(style_tip)
            return " ".join(tips)
        return ""

    # ---------------- 动作 ----------------
    def validate(self, req: ActionRequest, action: dict) -> None:
        if req.kind == "bid":
            bid = action.get("bid")
            if not isinstance(bid, int) or bid < 0 or bid > 3:
                raise ActionError("bid 必须是 0-3 的整数")
            if bid != 0 and bid <= self.current_bid:
                raise ActionError(f"叫分必须高于当前最高分 {self.current_bid}")
            return
        if req.kind == "play_cards":
            sid = req.seat_id
            if action.get("pass") is True or action.get("action") == "pass":
                if not self.last_play:
                    raise ActionError("你是领出者，不能过牌")
                return
            ids = self._action_cards(action)
            if not ids:
                raise ActionError("请给出要出的牌，或选择过牌")
            cards = self._resolve_cards(sid, ids)
            info = analyze(cards)
            if not info:
                raise ActionError("不是合法牌型")
            if not beats(info, self.last_play):
                raise ActionError("这手牌无法大过上一手")

    def _action_cards(self, action: dict) -> list[str]:
        raw = action.get("cards") or action.get("play") or action.get("action")
        if isinstance(raw, list):
            return [str(x) for x in raw]
        if isinstance(raw, str):
            return [x for x in raw.replace(",", " ").split() if x]
        return []

    def _resolve_cards(self, seat_id: str, ids: list[str]) -> list[dict]:
        hand = self.hands[seat_id]
        by_id = {c["id"]: c for c in hand}
        by_label = {c["label"]: c for c in hand}
        cards = []
        used = set()
        for raw in ids:
            card = by_id.get(raw) or by_label.get(raw)
            if not card:
                raise ActionError(f"你手里没有牌 {raw}")
            if card["id"] in used:
                raise ActionError(f"重复使用牌 {raw}")
            used.add(card["id"])
            cards.append(card)
        return cards

    def apply(self, req: ActionRequest, action: dict) -> None:
        if req.kind == "bid":
            bid = int(action["bid"])
            self.bids[req.seat_id] = bid
            if bid > self.current_bid:
                self.current_bid = bid
                self.highest_bidder = req.seat_id
            label = "不叫" if bid == 0 else f"叫 {bid} 分"
            # 先聊天，再播报叫分，语音会按这个顺序朗读。
            self.say(req.seat_id, str(action.get("speech") or "").strip())
            self.emit("bid", f"{self.seat_map[req.seat_id].name} {label}。", seat_id=req.seat_id, bid=bid)
            if bid == 3:
                self.bid_queue = []
            return
        if req.kind == "play_cards":
            if action.get("pass") is True or action.get("action") == "pass":
                self.passes += 1
                self.say(req.seat_id, str(action.get("speech") or "").strip())
                self.emit("pass", f"{self.seat_map[req.seat_id].name} 过牌。", seat_id=req.seat_id)
                if self.passes >= 2 and self.last_player:
                    leader = self.last_player
                    self.last_play = None
                    self.last_player = None
                    self.passes = 0
                    self.turn = leader
                    self.emit("new_trick", f"两家过牌，{self.seat_map[leader].name} 重新领出。")
                else:
                    self.turn = self._next_alive(req.seat_id)
                return
            cards = self._resolve_cards(req.seat_id, self._action_cards(action))
            info = analyze(cards)
            assert info
            self.hands[req.seat_id] = [c for c in self.hands[req.seat_id] if c["id"] not in {x["id"] for x in cards}]
            self.last_play = {
                "seat": req.seat_id,
                "cards": [c["id"] for c in cards],
                "labels": [c["label"] for c in cards],
                "kind": info["kind"],
                "rank": info["rank"],
                "length": info["length"],
            }
            self.last_player = req.seat_id
            self.passes = 0
            # 先聊天，再播报出的牌。
            self.say(req.seat_id, str(action.get("speech") or "").strip())
            self.emit(
                "play",
                f"{self.seat_map[req.seat_id].name} 出牌：{' '.join(c['label'] for c in cards)}（{info['kind']}）",
                seat_id=req.seat_id,
                cards=[c["id"] for c in cards],
                labels=[c["label"] for c in cards],
                kind=info["kind"],
            )
            if not self.hands[req.seat_id]:
                if req.seat_id == self.landlord:
                    self.finish("地主", f"地主 {self.seat_map[req.seat_id].name} 出完手牌", {"landlord": self.landlord})
                else:
                    self.finish("农民", f"农民 {self.seat_map[req.seat_id].name} 出完手牌", {"landlord": self.landlord})
                return
            self.turn = self._next_alive(req.seat_id)

    def _next_alive(self, seat_id: str) -> str:
        idx = [s.id for s in self.seats].index(seat_id)
        return self.seats[(idx + 1) % 3].id

    # ---------------- 视图 ----------------
    def public_state(self) -> dict:
        return {
            "game": "doudizhu",
            "phase": self.phase,
            "round": self.round,
            "landlord": self.landlord,
            "bottom": [{"id": c["id"], "label": c["label"]} for c in self.bottom] if self.landlord else [],
            "current_bid": self.current_bid,
            "turn": self.turn,
            "seats": [
                {
                    "id": s.id,
                    "name": s.name,
                    "seat_no": i + 1,
                    "color": s.color,
                    "hand_count": len(self.hands.get(s.id, [])),
                    "role": ("地主" if s.id == self.landlord else "农民") if self.landlord else None,
                    "bid": self.bids.get(s.id),
                }
                for i, s in enumerate(self.seats)
            ],
            "last_play": self.last_play,
            "stage": self.stage,
        }

    def private_state(self, seat_id: str) -> dict:
        hand = self.hands.get(seat_id, [])
        state = {
            "seat_no": [s.id for s in self.seats].index(seat_id) + 1,
            "role": ("地主" if seat_id == self.landlord else "农民") if self.landlord else "待定",
            "hand": [{"id": c["id"], "label": c["label"], "rank": c["rank"]} for c in hand],
            "hand_count": len(hand),
            "bottom": [{"id": c["id"], "label": c["label"]} for c in self.bottom] if self.landlord else [],
        }
        if self.landlord and seat_id != self.landlord:
            state["landlord"] = self.landlord
            state["teammate"] = [s.id for s in self.seats if s.id not in {seat_id, self.landlord}]
        if self.finished:
            state["all_hands"] = {
                s.id: [c["label"] for c in self.hands.get(s.id, [])] for s in self.seats
            }
        return state

    def fallback_action(self, req: ActionRequest) -> dict:
        style = self.style_for(req.seat_id).get("name", "")
        if req.kind == "bid":
            options = req.options
            if not options:
                return {"bid": 0}
            if style in {"保守", "稳健"}:
                return {"bid": 0}
            if style == "激进":
                return dict(max(options, key=lambda o: int(o.action.get("bid") or 0)).action)
            return dict(self.rng.choice(options).action)
        if req.kind == "play_cards":
            passes = [o for o in req.options if o.action.get("pass")]
            plays = [o for o in req.options if not o.action.get("pass")]
            if plays and (not passes or style in {"激进", "直觉"} or self.rng.random() < 0.5):
                return dict(self.rng.choice(plays).action)
            if passes:
                return dict(passes[0].action)
            if req.options:
                return dict(req.options[0].action)
        return super().fallback_action(req)


ENGINE = DoudizhuEngine
