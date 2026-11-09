from __future__ import annotations

from ..engine import ActionError, ActionOption, ActionRequest, GameEngine, Seat, Visibility

ROLE_LABEL = {"lord": "主公", "loyal": "忠臣", "rebel": "反贼", "spy": "内奸"}
ROLE_CAMP = {"lord": "主公阵营", "loyal": "主公阵营", "rebel": "反贼阵营", "spy": "内奸"}
CARD_LABEL = {
    "slash": "杀",
    "dodge": "闪",
    "peach": "桃",
    "exnihilo": "无中生有",
    "dismantle": "过河拆桥",
    "duel": "决斗",
}
CARD_COUNT = {"slash": 24, "dodge": 16, "peach": 10, "exnihilo": 6, "dismantle": 6, "duel": 4}


class SanguoshaEngine(GameEngine):
    game_id = "sanguosha"
    name = "三国杀"
    description = "简化 4/5 人身份局：杀、闪、桃、无中生有、过河拆桥、决斗，包含响应与濒死。"
    min_players = 4
    max_players = 5
    allowed_counts = (4, 5)
    presets = [
        {"id": "four", "name": "4 人身份局", "players": 4, "description": "主公 / 忠臣 / 反贼 / 内奸"},
        {"id": "five", "name": "5 人身份局", "players": 5, "description": "主公 / 忠臣 / 反贼×2 / 内奸"},
    ]
    rules = """三国杀（简化身份局）
【身份】主公身份公开；忠臣、反贼、内奸身份隐藏，死亡时公开。主公初始 5 点体力，其他人 4 点。
【回合】摸 2 张牌 → 出牌阶段（可出任意张牌，每回合最多使用 1 张【杀】）→ 弃牌至体力上限。
【卡牌】
- 杀：对一名其他存活角色使用，目标需打出【闪】，否则受到 1 点伤害。
- 闪：只能用于响应【杀】。
- 桃：回复 1 点体力（只能对自己使用）；濒死时可用桃自救。
- 无中生有：摸 2 张牌。
- 过河拆桥：弃置一名其他角色的一张随机手牌。
- 决斗：目标需打出【杀】，否则受到 1 点伤害（简化：只交换一次）。
【濒死】体力降到 0 时，若手中有桃可以自救（回复到 1 点），否则死亡。
【胜利】
- 主公阵营：主公存活且所有反贼、内奸出局。
- 反贼阵营：主公出局（若此时只剩内奸存活则内奸胜）。
- 内奸：成为最后唯一存活者。
【简化】不计算距离、装备、锦囊链与无懈可击；弃牌阶段由系统随机弃置超出体力上限的牌。"""

    def __init__(self, seats: list[Seat], config: dict | None = None, rng=None):
        super().__init__(seats, config, rng)
        if len(seats) not in (4, 5):
            raise ValueError("三国杀简化版支持 4 或 5 名玩家")
        self.roles: dict[str, str] = {}
        self.max_hp: dict[str, int] = {}
        self.hp: dict[str, int] = {}
        self.hand: dict[str, list[dict]] = {s.id: [] for s in seats}
        self.alive: set[str] = {s.id for s in seats}
        self.deck: list[dict] = []
        self.discard: list[dict] = []
        self.turn: str | None = None
        self.stage = "turn_start"
        self.slash_used = False
        self.pending: dict = {}
        self.dying_seat: str | None = None
        self.last_action = ""
        self.turn_no = 0
        self.killer: str | None = None

    # ---------------- 初始化 ----------------
    def _build_deck(self) -> None:
        self.deck = []
        idx = 0
        for card_type, count in CARD_COUNT.items():
            for _ in range(count):
                idx += 1
                self.deck.append({"id": f"C{idx}", "type": card_type, "label": CARD_LABEL[card_type]})
        self.rng.shuffle(self.deck)
        self.discard = []

    def start(self) -> None:
        lord = self.rng.choice(self.seats)
        others = [s for s in self.seats if s.id != lord.id]
        role_pool = ["loyal"] + ["rebel"] * (len(self.seats) - 3) + ["spy"]
        self.rng.shuffle(role_pool)
        self.roles = {lord.id: "lord"}
        for seat, role in zip(others, role_pool):
            self.roles[seat.id] = role
        for seat in self.seats:
            self.max_hp[seat.id] = 5 if self.roles[seat.id] == "lord" else 4
            self.hp[seat.id] = self.max_hp[seat.id]
        self._build_deck()
        self.emit("game_start", f"三国杀 {len(self.seats)} 人身份局开始。主公是 {lord.name}。")
        for seat in self.seats:
            role = self.roles[seat.id]
            self.emit(
                "role_assigned",
                f"你的身份是【{ROLE_LABEL[role]}】，体力 {self.max_hp[seat.id]}。",
                visibility=Visibility.private(seat.id),
                seat_id=seat.id,
                role=role,
                role_label=ROLE_LABEL[role],
                camp=ROLE_CAMP[role],
            )
        for seat in self.seats:
            self._draw(seat.id, 4, initial=True)
        self.turn = lord.id
        self.turn_no = 1
        self.phase = f"第{self.turn_no}回合·{lord.name}"
        self.emit("phase", f"主公 {lord.name} 先行动。")
        self.stage = "turn_start"

    # ---------------- 状态机 ----------------
    def advance(self) -> None:
        for _ in range(400):
            if self.finished or self._requests or self._waiting:
                return
            if self.stage == "turn_start":
                self._turn_start()
            elif self.stage == "play":
                self._play_request()
            elif self.stage == "dodge":
                self._dodge_request()
            elif self.stage == "duel":
                self._duel_request()
            elif self.stage == "dying":
                self._dying_request()
            elif self.stage == "end_turn":
                self._end_turn()
            else:
                return
        raise RuntimeError("三国杀状态机步数超限")

    def _turn_start(self) -> None:
        if not self.turn or self.turn not in self.alive:
            self._check_win()
            if self.finished:
                return
            self._next_turn()
            return
        self.turn_no += 1
        self.slash_used = False
        self.phase = f"第{self.turn_no}回合·{self.seat_map[self.turn].name}"
        self.emit("phase", f"── {self.seat_map[self.turn].name} 的回合 ──")
        self._draw(self.turn, 2)
        self.stage = "play"

    def _play_request(self) -> None:
        sid = self.turn
        if not sid or sid not in self.alive:
            self.stage = "end_turn"
            return
        options: list[ActionOption] = []
        others = [s for s in self.seats if s.id in self.alive and s.id != sid]
        for card in self.hand[sid]:
            ctype = card["type"]
            if ctype == "slash" and not self.slash_used:
                for target in others:
                    options.append(
                        ActionOption(
                            f"{card['id']}_{target.id}",
                            f"对 {target.name} 使用【杀】",
                            {"action": "play", "card": card["id"], "target": target.id},
                            card["label"],
                        )
                    )
            elif ctype == "peach" and self.hp[sid] < self.max_hp[sid]:
                options.append(
                    ActionOption(
                        f"{card['id']}_self",
                        "使用【桃】回复 1 点体力",
                        {"action": "play", "card": card["id"], "target": sid},
                        card["label"],
                    )
                )
            elif ctype == "exnihilo":
                options.append(
                    ActionOption(
                        f"{card['id']}_self",
                        "使用【无中生有】摸 2 张牌",
                        {"action": "play", "card": card["id"], "target": sid},
                        card["label"],
                    )
                )
            elif ctype == "dismantle":
                for target in others:
                    if self.hand.get(target.id):
                        options.append(
                            ActionOption(
                                f"{card['id']}_{target.id}",
                                f"对 {target.name} 使用【过河拆桥】",
                                {"action": "play", "card": card["id"], "target": target.id},
                                card["label"],
                            )
                        )
            elif ctype == "duel":
                for target in others:
                    options.append(
                        ActionOption(
                            f"{card['id']}_{target.id}",
                            f"对 {target.name} 使用【决斗】",
                            {"action": "play", "card": card["id"], "target": target.id},
                            card["label"],
                        )
                    )
        options.append(ActionOption("end", "结束出牌阶段", {"action": "end"}))
        self.phase = f"出牌·{self.seat_map[sid].name}"
        self.request(
            sid,
            "sgs_play",
            "出牌阶段",
            "你可以使用手牌：杀（需目标，每回合一次）、桃（自己受伤时）、无中生有、过河拆桥、决斗，或结束出牌。",
            options=options,
            action_schema={"action": "play 或 end", "card": "卡牌 ID（play 时必填）", "target": "目标座位 ID"},
        )

    def _dodge_request(self) -> None:
        target = self.pending.get("target")
        source = self.pending.get("source")
        if not target or target not in self.alive:
            self.stage = "play"
            return
        dodges = [c for c in self.hand[target] if c["type"] == "dodge"]
        if not dodges:
            self._damage(target, 1, source, "受到【杀】的伤害")
            self._after_reaction()
            return
        self.phase = f"响应·{self.seat_map[target].name}"
        self.request(
            target,
            "sgs_dodge",
            "你需要打出【闪】",
            f"{self.seat_map[source].name} 对你使用了【杀】。打出【闪】可以抵消伤害，否则受到 1 点伤害。",
            options=[
                ActionOption(f"dodge_{c['id']}", f"打出【闪】{c['id']}", {"use": True, "card": c["id"]})
                for c in dodges
            ]
            + [ActionOption("take", "不出闪，承受伤害", {"use": False})],
            action_schema={"use": "是否打出闪", "card": "闪的卡牌 ID"},
        )
        self.stage = "dodge_wait"

    def _duel_request(self) -> None:
        target = self.pending.get("target")
        source = self.pending.get("source")
        if not target or target not in self.alive:
            self.stage = "play"
            return
        slashes = [c for c in self.hand[target] if c["type"] == "slash"]
        if not slashes:
            self._damage(target, 1, source, "决斗失败受到 1 点伤害")
            self._after_reaction()
            return
        self.phase = f"决斗·{self.seat_map[target].name}"
        self.request(
            target,
            "sgs_duel",
            "决斗响应",
            f"{self.seat_map[source].name} 对你使用了【决斗】。打出一张【杀】可以化解，否则受到 1 点伤害。",
            options=[
                ActionOption(f"slash_{c['id']}", f"打出【杀】{c['id']}", {"use": True, "card": c["id"]})
                for c in slashes
            ]
            + [ActionOption("take", "不出杀，承受伤害", {"use": False})],
            action_schema={"use": "是否打出杀", "card": "杀的卡牌 ID"},
        )
        self.stage = "duel_wait"

    def _dying_request(self) -> None:
        seat = self.dying_seat
        if not seat or seat not in self.alive:
            self.stage = "play"
            return
        if self.hp.get(seat, 0) > 0:
            self.stage = "play"
            return
        peaches = [c for c in self.hand[seat] if c["type"] == "peach"]
        if not peaches:
            self._die(seat, "濒死且无桃可救")
            return
        self.phase = f"濒死·{self.seat_map[seat].name}"
        self.request(
            seat,
            "sgs_dying",
            "濒死求桃",
            "你已进入濒死状态（体力 0）。使用一张【桃】可以回复到 1 点体力，否则死亡。",
            options=[
                ActionOption(f"peach_{c['id']}", f"使用【桃】{c['id']} 自救", {"use": True, "card": c["id"]})
                for c in peaches
            ]
            + [ActionOption("give_up", "放弃自救", {"use": False})],
            action_schema={"use": "是否使用桃", "card": "桃的卡牌 ID"},
        )
        self.stage = "dying_wait"

    def _end_turn(self) -> None:
        sid = self.turn
        if sid and sid in self.alive:
            excess = len(self.hand[sid]) - max(self.hp.get(sid, 0), 0)
            if excess > 0:
                dropped = self.rng.sample(self.hand[sid], excess)
                dropped_ids = {c["id"] for c in dropped}
                self.hand[sid] = [c for c in self.hand[sid] if c["id"] not in dropped_ids]
                self.discard.extend(dropped)
                self.emit(
                    "discard",
                    f"{self.seat_map[sid].name} 弃置了 {' '.join(c['label'] for c in dropped)}。",
                    seat_id=sid,
                    cards=[c["id"] for c in dropped],
                )
        self._next_turn()
        self.slash_used = False
        if self.finished:
            return
        self.stage = "turn_start"

    def _next_turn(self) -> None:
        order = [s.id for s in self.seats]
        if not self.turn:
            self.turn = order[0]
            return
        idx = order.index(self.turn)
        for step in range(1, len(order) + 1):
            candidate = order[(idx + step) % len(order)]
            if candidate in self.alive:
                self.turn = candidate
                return
        self._check_win()

    # ---------------- 动作 ----------------
    def validate(self, req: ActionRequest, action: dict) -> None:
        if req.kind == "sgs_play":
            if action.get("action") == "end" or action.get("end") is True:
                return
            card_id = action.get("card") or action.get("card_id")
            card = next((c for c in self.hand[req.seat_id] if c["id"] == card_id), None)
            if not card:
                raise ActionError(f"你手中没有卡牌 {card_id}")
            ctype = card["type"]
            target = action.get("target")
            if ctype == "slash" and self.slash_used:
                raise ActionError("本回合已经使用过【杀】")
            if ctype in {"slash", "dismantle", "duel"}:
                if not target or target not in self.alive or target == req.seat_id:
                    raise ActionError("必须选择一名其他存活角色作为目标")
            if ctype == "peach" and self.hp[req.seat_id] >= self.max_hp[req.seat_id]:
                raise ActionError("体力已满，不能使用桃")
            if ctype == "dismantle" and not self.hand.get(target):
                raise ActionError("目标没有手牌")
            if ctype == "dodge":
                raise ActionError("【闪】只能用于响应杀")
            return
        if req.kind in {"sgs_dodge", "sgs_duel", "sgs_dying"}:
            if action.get("use") is not True:
                return
            card_id = action.get("card")
            card = next((c for c in self.hand[req.seat_id] if c["id"] == card_id), None)
            expected = {"sgs_dodge": "dodge", "sgs_duel": "slash", "sgs_dying": "peach"}[req.kind]
            if not card or card["type"] != expected:
                raise ActionError(f"需要打出一张【{CARD_LABEL[expected]}】")

    def apply(self, req: ActionRequest, action: dict) -> None:
        if req.kind == "sgs_play":
            if action.get("action") == "end" or action.get("end") is True:
                self.emit("end_play", f"{self.seat_map[req.seat_id].name} 结束出牌。", seat_id=req.seat_id)
                self.stage = "end_turn"
                return
            card_id = action.get("card") or action.get("card_id")
            card = next(c for c in self.hand[req.seat_id] if c["id"] == card_id)
            target = action.get("target")
            self.hand[req.seat_id] = [c for c in self.hand[req.seat_id] if c["id"] != card_id]
            self.discard.append(card)
            ctype = card["type"]
            if ctype == "slash":
                self.slash_used = True
                self.pending = {"source": req.seat_id, "target": target}
                self.emit(
                    "use_card",
                    f"{self.seat_map[req.seat_id].name} 对 {self.seat_map[target].name} 使用了【杀】。",
                    seat_id=req.seat_id,
                    target=target,
                    card=card["label"],
                )
                self.stage = "dodge"
            elif ctype == "peach":
                healed = min(self.max_hp[req.seat_id], self.hp[req.seat_id] + 1)
                self.hp[req.seat_id] = healed
                self.emit("use_card", f"{self.seat_map[req.seat_id].name} 使用【桃】，回复 1 点体力（{healed}/{self.max_hp[req.seat_id]}）。", seat_id=req.seat_id, card=card["label"])
                self.stage = "play"
            elif ctype == "exnihilo":
                self.emit("use_card", f"{self.seat_map[req.seat_id].name} 使用【无中生有】。", seat_id=req.seat_id, card=card["label"])
                self._draw(req.seat_id, 2)
                self.stage = "play"
            elif ctype == "dismantle":
                if self.hand.get(target):
                    idx = self.rng.randrange(len(self.hand[target]))
                    removed = self.hand[target].pop(idx)
                    self.discard.append(removed)
                    self.emit(
                        "use_card",
                        f"{self.seat_map[req.seat_id].name} 对 {self.seat_map[target].name} 使用【过河拆桥】，弃置了【{removed['label']}】。",
                        seat_id=req.seat_id,
                        target=target,
                        card=card["label"],
                    )
                self.stage = "play"
            elif ctype == "duel":
                self.pending = {"source": req.seat_id, "target": target}
                self.emit("use_card", f"{self.seat_map[req.seat_id].name} 对 {self.seat_map[target].name} 使用【决斗】。", seat_id=req.seat_id, target=target, card=card["label"])
                self.stage = "duel"
            self.say(req.seat_id, str(action.get("speech") or "").strip())
            return
        if req.kind == "sgs_dodge":
            target = req.seat_id
            if action.get("use") is True:
                card = next(c for c in self.hand[target] if c["id"] == action.get("card"))
                self.hand[target] = [c for c in self.hand[target] if c["id"] != card["id"]]
                self.discard.append(card)
                self.emit("respond", f"{self.seat_map[target].name} 打出【闪】，抵消了这次【杀】。", seat_id=target, card="闪")
            else:
                self.emit("respond", f"{self.seat_map[target].name} 没有闪，受到 1 点伤害。", seat_id=target)
                self._damage(target, 1, self.pending.get("source"), "受到【杀】的伤害")
            self._after_reaction()
            return
        if req.kind == "sgs_duel":
            target = req.seat_id
            if action.get("use") is True:
                card = next(c for c in self.hand[target] if c["id"] == action.get("card"))
                self.hand[target] = [c for c in self.hand[target] if c["id"] != card["id"]]
                self.discard.append(card)
                self.emit("respond", f"{self.seat_map[target].name} 打出【杀】，化解了决斗。", seat_id=target, card="杀")
            else:
                self.emit("respond", f"{self.seat_map[target].name} 无法出杀，受到 1 点决斗伤害。", seat_id=target)
                self._damage(target, 1, self.pending.get("source"), "决斗失败")
            self._after_reaction()
            return
        if req.kind == "sgs_dying":
            seat = req.seat_id
            if action.get("use") is True:
                card = next(c for c in self.hand[seat] if c["id"] == action.get("card"))
                self.hand[seat] = [c for c in self.hand[seat] if c["id"] != card["id"]]
                self.discard.append(card)
                self.hp[seat] = 1
                self.dying_seat = None
                self.emit("respond", f"{self.seat_map[seat].name} 使用【桃】自救，回复到 1 点体力。", seat_id=seat, card="桃")
                self.stage = "play"
            else:
                self._die(seat, "濒死放弃自救")
            return

    def _after_reaction(self) -> None:
        if self.finished:
            return
        seat = self.dying_seat
        if seat and seat in self.alive and self.hp.get(seat, 0) <= 0:
            self.stage = "dying"
            return
        self.dying_seat = None
        self.stage = "play"

    def _damage(self, target: str, amount: int, source: str | None, reason: str) -> None:
        if target not in self.alive:
            return
        self.hp[target] = max(0, self.hp[target] - amount)
        self.emit(
            "damage",
            f"{self.seat_map[target].name} 受到 {amount} 点伤害（{reason}），剩余体力 {self.hp[target]}/{self.max_hp[target]}。",
            seat_id=target,
            source=source,
            hp=self.hp[target],
            reason=reason,
        )
        if self.hp[target] <= 0:
            self.dying_seat = target
            self.emit("dying", f"{self.seat_map[target].name} 进入濒死状态。", seat_id=target)
            self.stage = "dying"

    def _die(self, seat_id: str, reason: str) -> None:
        if seat_id not in self.alive:
            return
        self.alive.discard(seat_id)
        lost = self.hand.get(seat_id, [])
        self.hand[seat_id] = []
        self.discard.extend(lost)
        role = self.roles[seat_id]
        self.emit(
            "death",
            f"{self.seat_map[seat_id].name} 出局（{reason}），身份是【{ROLE_LABEL[role]}】。",
            seat_id=seat_id,
            role=role,
            role_label=ROLE_LABEL[role],
        )
        if self._check_win():
            return
        if self.dying_seat == seat_id:
            self.dying_seat = None
        if self.turn == seat_id:
            self.stage = "end_turn"
        else:
            self.stage = "play"

    def _check_win(self) -> bool:
        if self.finished:
            return True
        alive_roles = {sid: self.roles[sid] for sid in self.alive}
        if not alive_roles:
            self.finish("无人", "全场出局", {"roles": self.roles})
            return True
        if "lord" not in alive_roles:
            if set(alive_roles.values()) == {"spy"}:
                self.finish("内奸", "主公出局且内奸成为唯一存活者", {"roles": self.roles})
            else:
                self.finish("反贼阵营", "主公出局", {"roles": self.roles})
            return True
        if not any(role in {"rebel", "spy"} for role in alive_roles.values()):
            self.finish("主公阵营", "所有反贼与内奸出局", {"roles": self.roles})
            return True
        return False

    # ---------------- 抽牌 / 视图 ----------------
    def _draw(self, seat_id: str, count: int, initial: bool = False) -> None:
        drawn: list[dict] = []
        for _ in range(count):
            if not self.deck:
                if self.discard:
                    self.deck = self.discard
                    self.discard = []
                    self.rng.shuffle(self.deck)
                else:
                    break
            drawn.append(self.deck.pop())
        self.hand[seat_id].extend(drawn)
        if drawn:
            self.emit(
                "draw",
                f"你摸到：{'、'.join(c['label'] for c in drawn)}",
                visibility=Visibility.private(seat_id),
                seat_id=seat_id,
                cards=[c["id"] for c in drawn],
            )
            if not initial:
                self.emit("draw_public", f"{self.seat_map[seat_id].name} 摸了 {len(drawn)} 张牌。", seat_id=seat_id)

    def public_state(self) -> dict:
        return {
            "game": "sanguosha",
            "phase": self.phase,
            "round": self.turn_no,
            "turn": self.turn,
            "deck_count": len(self.deck),
            "discard_count": len(self.discard),
            "seats": [
                {
                    "id": s.id,
                    "name": s.name,
                    "seat_no": i + 1,
                    "color": s.color,
                    "alive": s.id in self.alive,
                    "hp": self.hp.get(s.id, 0),
                    "max_hp": self.max_hp.get(s.id, 4),
                    "hand_count": len(self.hand.get(s.id, [])),
                    "role": (
                        "主公" if self.roles.get(s.id) == "lord"
                        else ROLE_LABEL.get(self.roles.get(s.id, ""), "")
                        if s.id not in self.alive or self.finished
                        else None
                    ),
                }
                for i, s in enumerate(self.seats)
            ],
            "stage": self.stage,
        }

    def private_state(self, seat_id: str) -> dict:
        role = self.roles.get(seat_id, "")
        goals = {
            "lord": "消灭所有反贼与内奸，保证自己存活。",
            "loyal": "保护主公，帮助主公消灭反贼与内奸。",
            "rebel": "击杀主公。",
            "spy": "先帮助主公消灭反贼，再成为最后唯一存活者。",
        }
        state = {
            "seat_no": [s.id for s in self.seats].index(seat_id) + 1,
            "role": role,
            "role_label": ROLE_LABEL.get(role, ""),
            "camp": ROLE_CAMP.get(role, ""),
            "alive": seat_id in self.alive,
            "hp": self.hp.get(seat_id, 0),
            "max_hp": self.max_hp.get(seat_id, 4),
            "hand": [
                {"id": c["id"], "type": c["type"], "label": c["label"]}
                for c in self.hand.get(seat_id, [])
            ],
            "win_goal": goals.get(role, ""),
        }
        if role == "loyal":
            state["lord"] = next((sid for sid, r in self.roles.items() if r == "lord"), None)
        if self.finished:
            state["all_roles"] = {
                sid: {"name": self.seat_map[sid].name, "role": ROLE_LABEL[r]} for sid, r in self.roles.items()
            }
        return state

    def fallback_action(self, req: ActionRequest) -> dict:
        if req.kind == "sgs_play":
            return {"action": "end"}
        if req.kind in {"sgs_dodge", "sgs_duel", "sgs_dying"}:
            return {"use": False}
        return super().fallback_action(req)
