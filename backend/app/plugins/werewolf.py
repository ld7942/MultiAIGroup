from __future__ import annotations

from ..engine import ActionError, ActionOption, ActionRequest, GameEngine, Seat, Visibility

ROLES = {
    "werewolf": {"label": "狼人", "camp": "狼人阵营"},
    "seer": {"label": "预言家", "camp": "好人阵营"},
    "witch": {"label": "女巫", "camp": "好人阵营"},
    "hunter": {"label": "猎人", "camp": "好人阵营"},
    "villager": {"label": "村民", "camp": "好人阵营"},
}

DAY_HINTS = [
    "我先听一轮发言，暂时保留判断。",
    "建议重点听一下信息量少的位置。",
    "我这边没有额外信息，先给个态度：今天我会认真投票。",
    "不要急着冲票，先让每个人把逻辑讲清楚。",
    "我觉得狼人可能藏在发言比较飘的位置。",
]

WOLF_HINTS = [
    "今晚优先刀信息位，别留后患。",
    "我建议刀一个像神职的，先别动边缘位。",
    "听你们的，我跟票。",
    "注意别把队友刀了，报一下目标。",
]

# 角色玩法技能卡：开局随系统提示词注入，相当于每个角色先“调用”自己的玩法。
ROLE_SKILLS = {
    "werewolf": """【狼人】目标：消灭所有村民，或消灭所有神职。
- 白天把自己当成好人来发言，用“找狼逻辑”建立可信度；不要主动提队友。
- 夜间刀人优先级：预言家 > 女巫 > 猎人 > 村民；不要刀队友；空刀只在有明确战术时使用。
- 被查杀时二选一：强势反打对跳，或果断与队友切割；不要含糊其辞。
- 每次狼人密谈都必须发言，给出具体刀人建议与理由。""",
    "seer": """【预言家】目标：用查验信息带领好人放逐狼人。
- 验人优先级：发言强势、带节奏、身份不明的人 > 沉默位；不要重复验已知身份。
- 有查杀时白天要跳身份报验，讲清“第几晚验了谁、结果是什么”。
- 无查杀时可以隐藏或只给暗示，避免首夜被刀。
- 报验后必须给出明确的放逐目标和理由。""",
    "witch": """【女巫】目标：用好解药与毒药，帮助好人阵营。
- 解药：首夜被刀的是关键神职或高价值玩家时优先救；自己能救则救。
- 毒药：只在身份概率较高（约 70% 以上）时使用；绝不能毒自己；不毒已明确跳预言家且逻辑成立的人。
- 同一晚只能用一瓶药；信息不足时宁可不用，留到关键回合。
- 白天尽量隐藏身份，报药信息要服务于带队。""",
    "hunter": """【猎人】目标：活着威慑狼人，出局时带走狼人。
- 白天隐藏身份，避免被狼人针对；发言可以强势，但不要过早暴露猎人。
- 被投票出局或被狼人击杀时可以开枪，优先带走狼概率最高的人。
- 不要枪已确认的好人；被女巫毒杀时不能开枪。
- 没有把握时可以不开枪，避免误伤。""",
    "villager": """【村民】目标：通过发言与投票帮助好人阵营。
- 认真表水：说明自己的视角、怀疑对象与投票意向。
- 优先跟随可信预言家的验人，不要分票。
- 没有信息时听发言、找逻辑矛盾，不要盲目冲票。
- 不要空发言；至少给出 2 个具体怀疑点。""",
}


class WerewolfEngine(GameEngine):
    game_id = "werewolf"
    name = "狼人杀"
    description = "9 人标准局：狼人夜间密谈刀人，预言家查验、女巫解药毒药、猎人开枪，白天发言投票。"
    min_players = 6
    max_players = 12
    allowed_counts = (6, 7, 8, 9, 10, 11, 12)
    capabilities = {"hand": False, "items": True, "table_cards": False, "hidden_roles": True}
    presets = [
        {"id": "standard", "name": "9 人标准局", "players": 9, "description": "3 狼 + 预言家 + 女巫 + 猎人 + 3 村民"},
        {"id": "quick", "name": "6 人快速局", "players": 6, "description": "2 狼 + 预言家 + 女巫 + 2 村民"},
    ]
    rules = """狼人杀（简化标准局）
【阵营】狼人阵营 vs 好人阵营。
【夜晚顺序】
1. 狼人密谈：存活狼人依次在狼人频道发言，然后同时投票选择今晚袭击目标（可空刀）。
2. 预言家查验：选择一名其他存活玩家，得知其阵营（狼人/好人）。
3. 女巫：得知今晚被狼人袭击的玩家。拥有一瓶解药和一瓶毒药，各只能用一次，同一晚不能同时使用；解药可以救被袭击者（包括自己），毒药可以毒杀一名其他存活玩家。
【白天】
1. 公布死讯（不公布身份）。
2. 所有存活玩家依次公开发言一轮。
3. 所有存活玩家同时投票，得票最多者出局；平票则无人出局。
4. 猎人若被狼人击杀或被投票出局，可以开枪带走一名存活玩家；被女巫毒杀则不能开枪。
【胜利条件（屠边）】
- 好人阵营：所有狼人出局。
- 狼人阵营：所有村民出局，或所有神职（预言家/女巫/猎人）出局。
【重要】你只能依据自己可见的信息行动，不要假设自己知道未公开的身份。"""

    def __init__(self, seats: list[Seat], config: dict | None = None, rng=None):
        super().__init__(seats, config, rng)
        self.count = len(seats)
        if self.count not in self.allowed_counts:
            raise ValueError(f"狼人杀支持 {self.allowed_counts} 人，当前 {self.count} 人")
        self.roles: dict[str, str] = {}
        self.alive: set[str] = {s.id for s in seats}
        self.wolves: list[str] = []
        self.witch: str | None = None
        self.seer: str | None = None
        self.hunter: str | None = None
        self.antidote = True
        self.poison = True
        self.seer_checks: list[dict] = []
        self.night: dict = {}
        self.wolf_chat_queue: list[str] = []
        self.speech_queue: list[str] = []
        self.hunter_queue: list[str] = []
        self.votes: dict[str, str | None] = {}
        self.stage = "night_start"
        self.last_night: dict = {}
        self.dead_roles: dict[str, str] = {}

    # ---------------- 初始化 ----------------
    def _composition(self) -> dict[str, int]:
        table = {
            6: {"werewolf": 2, "seer": 1, "witch": 1, "villager": 2},
            7: {"werewolf": 2, "seer": 1, "witch": 1, "hunter": 1, "villager": 2},
            8: {"werewolf": 3, "seer": 1, "witch": 1, "hunter": 1, "villager": 2},
            9: {"werewolf": 3, "seer": 1, "witch": 1, "hunter": 1, "villager": 3},
            10: {"werewolf": 3, "seer": 1, "witch": 1, "hunter": 1, "villager": 4},
            11: {"werewolf": 4, "seer": 1, "witch": 1, "hunter": 1, "villager": 4},
            12: {"werewolf": 4, "seer": 1, "witch": 1, "hunter": 1, "villager": 5},
        }
        return table[self.count]

    def start(self) -> None:
        comp = self._composition()
        deck: list[str] = []
        for role, num in comp.items():
            deck.extend([role] * num)
        self.rng.shuffle(deck)
        for seat, role in zip(self.seats, deck):
            self.roles[seat.id] = role
        self.wolves = [s.id for s in self.seats if self.roles[s.id] == "werewolf"]
        for sid, role in self.roles.items():
            if role == "seer":
                self.seer = sid
            elif role == "witch":
                self.witch = sid
            elif role == "hunter":
                self.hunter = sid

        comp_text = "、".join(f"{ROLES[r]['label']}×{n}" for r, n in comp.items())
        self.emit("game_start", f"狼人杀 {self.count} 人局开始，阵容：{comp_text}")
        for seat in self.seats:
            role = self.roles[seat.id]
            self.emit(
                "role_assigned",
                f"你的身份是【{ROLES[role]['label']}】，属于{ROLES[role]['camp']}。",
                visibility=Visibility.private(seat.id),
                seat_id=seat.id,
                role=role,
                role_label=ROLES[role]["label"],
                camp=ROLES[role]["camp"],
            )
        wolf_names = "、".join(self.seat_map[w].name for w in self.wolves)
        for wolf in self.wolves:
            self.emit(
                "wolf_team",
                f"狼人队友：{wolf_names}。",
                visibility=Visibility.group(*self.wolves),
                seat_id=wolf,
                teammates=self.wolves,
            )
        self.phase = "第1夜"
        self.round = 0
        self.stage = "night_start"

    # ---------------- 主状态机 ----------------
    def advance(self) -> None:
        for _ in range(400):
            if self.finished or self._requests or self._waiting:
                return
            stage = self.stage
            if stage == "night_start":
                self._begin_night()
            elif stage == "wolf_chat":
                self._wolf_chat()
            elif stage == "wolf_vote":
                self._wolf_vote_requests()
            elif stage == "wolf_vote_pending":
                self._resolve_wolf_vote()
            elif stage == "seer":
                self._seer_requests()
            elif stage == "seer_pending":
                self.stage = "witch"
            elif stage == "witch":
                self._witch_requests()
            elif stage == "witch_pending":
                self.stage = "resolve_night"
            elif stage == "resolve_night":
                self._resolve_night()
            elif stage == "dawn_hunter":
                self.stage = "hunter_shot" if self.hunter_queue else "post_night"
            elif stage == "hunter_shot":
                self._hunter_requests("post_night")
            elif stage == "hunter_shot_day":
                self._hunter_requests("post_day")
            elif stage == "post_night_pending":
                self.stage = "post_night"
            elif stage == "post_day_pending":
                self.stage = "post_day"
            elif stage == "post_night":
                if self._check_win():
                    return
                self._begin_day()
            elif stage == "day_discussion":
                self._day_speech()
            elif stage == "day_vote":
                self._day_vote_requests()
            elif stage == "day_vote_pending":
                self._resolve_day_vote()
            elif stage == "exile_hunter":
                self.stage = "hunter_shot_day" if self.hunter_queue else "post_day"
            elif stage == "post_day":
                if self._check_win():
                    return
                self.stage = "night_start"
            else:
                raise RuntimeError(f"未知阶段 {stage}")
        raise RuntimeError("狼人杀状态机步数超限")

    # ---------------- 夜晚 ----------------
    def _begin_night(self) -> None:
        self.round += 1
        self.phase = f"第{self.round}夜"
        self.night = {"wolf_target": None, "saved": False, "poison": None, "cause": {}}
        self.votes = {}
        self.emit("phase", f"第 {self.round} 夜，天黑请闭眼。")
        self.wolf_chat_queue = [w for w in self.wolves if w in self.alive] if len(self.wolves) > 1 else []
        self.stage = "wolf_chat"

    def _wolf_chat(self) -> None:
        if self.wolf_chat_queue:
            sid = self.wolf_chat_queue.pop(0)
            self.phase = f"第{self.round}夜·狼人密谈"
            self.request(
                sid,
                "werewolf_chat",
                "狼人密谈",
                "你是存活狼人。请在狼人频道说一句话（可以提出今晚的袭击建议），然后等待投票。",
                action_schema={"speech": "你在狼人频道说的话"},
                meta={"speech_hints": WOLF_HINTS, "channel": "wolf"},
            )
            return
        self.stage = "wolf_vote"

    def _wolf_vote_requests(self) -> None:
        self.phase = f"第{self.round}夜·狼人袭击"
        living = [s for s in self.seats if s.id in self.alive]
        options = [
            ActionOption(
                f"kill_{s.id}",
                f"袭击 {s.name}",
                {"target": s.id},
                "狼人共同选择今晚的袭击目标",
            )
            for s in living
        ]
        options.append(ActionOption("kill_none", "空刀（不袭击）", {"target": None}))
        for wolf in [w for w in self.wolves if w in self.alive]:
            self.request(
                wolf,
                "werewolf_vote",
                "选择今晚的袭击目标",
                "与其他狼人同时投票。得票最多的存活玩家会被袭击；平票随机，空刀不杀人。",
                options=options,
                action_schema={"target": "存活玩家座位 ID，或 null 表示空刀"},
            )
        self.stage = "wolf_vote_pending"

    def _resolve_wolf_vote(self) -> None:
        tally: dict[str, int] = {}
        for target in self.votes.values():
            if target and target in self.alive:
                tally[target] = tally.get(target, 0) + 1
        target = None
        if tally:
            top = max(tally.values())
            tied = sorted([k for k, v in tally.items() if v == top])
            target = self.rng.choice(tied)
        self.night["wolf_target"] = target
        name = self.seat_map[target].name if target else "空刀"
        self.emit(
            "wolf_choice",
            f"狼人今晚的选择：{name}",
            visibility=Visibility.group(*self.wolves),
            target=target,
        )
        self.stage = "seer"

    def _seer_requests(self) -> None:
        if not self.seer or self.seer not in self.alive:
            self.stage = "witch"
            return
        self.phase = f"第{self.round}夜·预言家查验"
        living = [s for s in self.seats if s.id in self.alive and s.id != self.seer]
        if not living:
            self.stage = "witch"
            return
        self.request(
            self.seer,
            "seer_check",
            "预言家查验",
            "选择一名其他存活玩家查验阵营。结果只有你自己知道。",
            options=[
                ActionOption(f"check_{s.id}", f"查验 {s.name}", {"target": s.id})
                for s in living
            ],
            action_schema={"target": "要查验的存活玩家座位 ID"},
        )
        self.stage = "seer_pending"

    def _witch_requests(self) -> None:
        if not self.witch or self.witch not in self.alive or (not self.antidote and not self.poison):
            self.stage = "resolve_night"
            return
        victim = self.night.get("wolf_target")
        victim_name = self.seat_map[victim].name if victim else "空刀"
        self.emit(
            "witch_info",
            f"今晚狼人袭击的目标是：{victim_name}。你有一瓶解药{'（可用）' if self.antidote else '（已用完）'}，"
            f"一瓶毒药{'（可用）' if self.poison else '（已用完）'}。",
            visibility=Visibility.private(self.witch),
            seat_id=self.witch,
            victim=victim,
        )
        options: list[ActionOption] = []
        if self.antidote and victim:
            options.append(
                ActionOption("save", f"使用解药救 {self.seat_map[victim].name}", {"save": True, "poison": None})
            )
        options.append(ActionOption("save_no", "不使用解药", {"save": False, "poison": None}))
        if self.poison:
            for s in self.seats:
                if s.id in self.alive and s.id != self.witch:
                    options.append(
                        ActionOption(
                            f"poison_{s.id}",
                            f"使用毒药毒 {s.name}",
                            {"save": False, "poison": s.id},
                        )
                    )
        self.phase = f"第{self.round}夜·女巫行动"
        self.request(
            self.witch,
            "witch_action",
            "女巫行动",
            "你可以使用解药救起今晚被袭击的人，或使用毒药毒杀一名其他玩家。同一晚只能用一瓶药，也可以都不用。",
            options=options,
            action_schema={"save": "是否使用解药（true/false）", "poison": "毒杀目标座位 ID，或 null"},
            meta={"victim": victim},
        )
        self.stage = "witch_pending"

    def _resolve_night(self) -> None:
        self.phase = f"第{self.round}天·公布死讯"
        deaths: list[tuple[str, str]] = []
        if self.night.get("wolf_target") and not self.night.get("saved"):
            deaths.append((self.night["wolf_target"], "wolf"))
        if self.night.get("poison"):
            deaths.append((self.night["poison"], "poison"))
        self.last_night = {"deaths": [d for d, _ in deaths], "saved": bool(self.night.get("saved"))}
        dead_names = []
        for sid, cause in deaths:
            if sid in self.alive:
                self._mark_dead(sid, cause, announce=False)
                dead_names.append(self.seat_map[sid].name)
                self.emit(
                    "death",
                    f"{self.seat_map[sid].name} 昨晚出局。",
                    seat_id=sid,
                    cause=cause,
                    role=self.roles[sid] if self.finished else None,
                )
        if dead_names:
            self.emit("night_result", f"昨晚出局：{'、'.join(dead_names)}。", deaths=[d for d, _ in deaths])
        else:
            self.emit("night_result", "昨晚是平安夜，无人出局。", deaths=[])
        self.stage = "dawn_hunter"

    # ---------------- 白天 ----------------
    def _begin_day(self) -> None:
        self.phase = f"第{self.round}天·发言"
        self.emit("phase", f"第 {self.round} 天，天亮了。存活：{'、'.join(self.seat_map[s].name for s in self._living_ids())}")
        self.speech_queue = self._living_ids()
        self.stage = "day_discussion"

    def _day_speech(self) -> None:
        if self.speech_queue:
            sid = self.speech_queue.pop(0)
            self.phase = f"第{self.round}天·发言"
            self.request(
                sid,
                "day_speech",
                "白天公开发言",
                "请结合你掌握的信息（身份、查验、夜晚信息、上一轮发言）公开发言，表明你的怀疑与投票倾向。发言会被所有人看到。",
                action_schema={"speech": "你的公开发言"},
                meta={"speech_hints": DAY_HINTS},
            )
            return
        self.stage = "day_vote"

    def _day_vote_requests(self) -> None:
        self.phase = f"第{self.round}天·投票"
        self.votes = {}
        living = self._living_ids()
        for sid in living:
            options = [
                ActionOption(f"vote_{other}", f"投给 {self.seat_map[other].name}", {"target": other})
                for other in living
                if other != sid
            ]
            options.append(ActionOption("abstain", "弃票", {"target": None}))
            self.request(
                sid,
                "day_vote",
                "放逐投票",
                "同时投票放逐一名存活玩家，也可以弃票。得票最多者出局，平票无人出局。",
                options=options,
                action_schema={"target": "你要投票的存活玩家座位 ID，或 null 表示弃票"},
            )
        self.stage = "day_vote_pending"

    def _resolve_day_vote(self) -> None:
        tally: dict[str, int] = {}
        for target in self.votes.values():
            if target in self.alive:
                tally[target] = tally.get(target, 0) + 1
        for sid, target in self.votes.items():
            self.emit(
                "vote",
                f"{self.seat_map[sid].name} 投给 {self.seat_map[target].name if target else '（弃票）'}",
                seat_id=sid,
                target=target,
            )
        top = max(tally.values()) if tally else 0
        tied = sorted([k for k, v in tally.items() if v == top]) if top else []
        if not tied or len(tied) > 1:
            self.emit("vote_result", "投票平票，本轮无人出局。", tally=tally)
            self.stage = "post_day"
            return
        exiled = tied[0]
        self.emit("vote_result", f"{self.seat_map[exiled].name} 以 {top} 票被放逐。", tally=tally)
        if exiled in self.alive:
            self._mark_dead(exiled, "vote")
            self.emit("death", f"{self.seat_map[exiled].name} 被放逐出局。", seat_id=exiled, cause="vote")
        self.phase = f"第{self.round}天·猎人开枪"
        self.stage = "exile_hunter"

    # ---------------- 猎人 ----------------
    def _hunter_requests(self, next_stage: str) -> None:
        if not self.hunter_queue:
            self.stage = next_stage
            return
        shooter = self.hunter_queue.pop(0)
        living = [s for s in self.seats if s.id in self.alive and s.id != shooter]
        if not living:
            self.stage = next_stage
            return
        self.phase = "猎人开枪"
        self.request(
            shooter,
            "hunter_shot",
            "猎人开枪",
            "你是猎人，已经出局。可以开枪带走一名存活玩家，也可以不开枪。",
            options=[
                ActionOption(f"shoot_{s.id}", f"开枪带走 {s.name}", {"target": s.id}) for s in living
            ]
            + [ActionOption("shoot_none", "不开枪", {"target": None})],
            action_schema={"target": "要带走的存活玩家座位 ID，或 null"},
        )
        self.stage = next_stage + "_pending"

    # ---------------- 动作处理 ----------------
    @classmethod
    def skill_cards(cls) -> list[dict]:
        return [
            {"role": ROLES[role]["label"], "faction": ROLES[role]["camp"], "text": text}
            for role, text in ROLE_SKILLS.items()
        ]

    def tactic_tags(self, seat_id: str) -> dict:
        role = self.roles.get(seat_id, "")
        return {
            "role": ROLES.get(role, {}).get("label", ""),
            "faction": ROLES.get(role, {}).get("camp", ""),
        }

    def skill_for(self, seat_id: str) -> str:
        return ROLE_SKILLS.get(self.roles.get(seat_id, ""), "")

    def action_hint(self, req: ActionRequest, seat_id: str) -> str:
        kind = req.kind
        style = self.style_for(seat_id).get("name", "")
        style_tip = ""
        if style == "激进":
            style_tip = "风格偏激进：可以主动带节奏、强推目标。"
        elif style == "保守":
            style_tip = "风格偏保守：先保命、少树敌，跟随可信好人。"
        elif style == "诡诈":
            style_tip = "风格偏诡诈：可以放烟雾弹、踩队友做身份，但别自相矛盾。"
        elif style == "理性":
            style_tip = "风格偏理性：用票型、发言矛盾等具体证据说服别人。"
        if kind == "werewolf_chat":
            return f"必须发言，不能空字符串。给出今晚具体刀谁、为什么；优先神职，不要刀队友。{style_tip}"
        if kind == "werewolf_vote":
            return "不要空刀（除非有明确战术）；不要投队友；优先预言家、女巫等关键神职。"
        if kind == "seer_check":
            return "优先查验发言强势、带节奏或身份不明的人；不要重复查验已经验过的人。"
        if kind == "witch_action":
            antidote = "可用" if self.antidote else "已用完"
            poison = "可用" if self.poison else "已用完"
            style = self.style_for(seat_id).get("name", "")
            style_tip = {
                "激进": "你偏激进：如果怀疑被杀者是狼自刀，可以故意不救。",
                "保守": "你偏保守：解药优先留给确认的关键神职，救不救由你的判断决定。",
                "诡诈": "你偏诡诈：不救、假救、留药骗刀都是合理选择。",
            }.get(style, "救与不救都可以，取决于你对被杀者身份的判断，不必每局都救。")
            return (
                f"解药{antidote}，毒药{poison}。毒药目标绝不能是自己；"
                f"置信度不足约 70% 时宁可不毒；同一晚不能同时使用两瓶药。{style_tip}"
            )
        if kind == "day_speech":
            return (
                "必须发言。点名至少 2 个怀疑对象，给出具体依据（发言矛盾、票型、夜晚信息），"
                f"并说明投票意向；禁止空话或只报态度。{style_tip}"
            )
        if kind == "day_vote":
            return f"不要轻易弃票；投给你认为狼概率最高的人；如果票型分散，跟随你最信任的好人。{style_tip}"
        if kind == "hunter_shot":
            return "开枪带走狼概率最高的人；不要带已确认的好人；没有把握可以不开枪。"
        return ""

    def validate(self, req: ActionRequest, action: dict) -> None:
        kind = req.kind
        if kind in {"werewolf_chat", "day_speech"}:
            if not str(action.get("speech") or "").strip():
                raise ActionError("必须发言：speech 不能为空")
            return
        target = action.get("target")
        if kind in {"werewolf_vote", "day_vote", "seer_check", "hunter_shot"}:
            if target is not None:
                if target not in self.seat_map or target not in self.alive:
                    raise ActionError(f"目标 {target} 不是存活玩家")
                if target == req.seat_id:
                    raise ActionError("不能选择自己作为目标")
        if kind == "witch_action":
            save = bool(action.get("save"))
            poison = action.get("poison")
            if save and not self.antidote:
                raise ActionError("解药已经用完")
            if save and not self.night.get("wolf_target"):
                raise ActionError("今晚没有被袭击的目标，无法使用解药")
            if save and poison:
                raise ActionError("同一晚不能同时使用解药和毒药")
            if poison:
                if not self.poison:
                    raise ActionError("毒药已经用完")
                if poison not in self.alive or poison == self.witch:
                    raise ActionError("毒药目标必须是其他存活玩家")

    def apply(self, req: ActionRequest, action: dict) -> None:
        kind = req.kind
        speech = str(action.get("speech") or "").strip()
        if kind == "werewolf_chat":
            self.say(req.seat_id, speech, Visibility.group(*self.wolves))
            return
        if kind == "day_speech":
            self.say(req.seat_id, speech or "（沉默）")
            return
        if kind == "werewolf_vote":
            self.votes[req.seat_id] = action.get("target")
            self.emit(
                "wolf_vote",
                f"{self.seat_map[req.seat_id].name} 选择袭击 "
                f"{self.seat_map[action['target']].name if action.get('target') else '（空刀）'}",
                visibility=Visibility.group(*self.wolves),
                seat_id=req.seat_id,
                target=action.get("target"),
            )
            return
        if kind == "seer_check":
            target = action["target"]
            is_wolf = self.roles.get(target) == "werewolf"
            result = "狼人" if is_wolf else "好人"
            self.seer_checks.append({"round": self.round, "target": target, "result": result})
            self.emit(
                "seer_result",
                f"你查验了 {self.seat_map[target].name}，结果是【{result}】。",
                visibility=Visibility.private(req.seat_id),
                seat_id=req.seat_id,
                target=target,
                result=result,
            )
            return
        if kind == "witch_action":
            save = bool(action.get("save"))
            poison = action.get("poison")
            if save:
                self.antidote = False
                self.night["saved"] = True
            if poison:
                self.poison = False
                self.night["poison"] = poison
            parts = []
            if save:
                parts.append(f"使用解药救下 {self.seat_map[self.night['wolf_target']].name}")
            if poison:
                parts.append(f"使用毒药毒杀 {self.seat_map[poison].name}")
            self.emit(
                "witch_action",
                "你" + ("，".join(parts) if parts else "没有使用药水") + "。",
                visibility=Visibility.private(req.seat_id),
                seat_id=req.seat_id,
            )
            return
        if kind == "day_vote":
            self.votes[req.seat_id] = action.get("target")
            return
        if kind == "hunter_shot":
            target = action.get("target")
            if target and target in self.alive:
                self.emit("hunter_shot", f"{self.seat_map[req.seat_id].name} 开枪带走了 {self.seat_map[target].name}。", seat_id=req.seat_id, target=target)
                self._mark_dead(target, "hunter")
                self.emit("death", f"{self.seat_map[target].name} 被猎人带走。", seat_id=target, cause="hunter")
            else:
                self.emit("hunter_shot", f"{self.seat_map[req.seat_id].name} 选择不开枪。", seat_id=req.seat_id, target=None)
            return

    # ---------------- 结算 ----------------
    def _living_ids(self) -> list[str]:
        return [s.id for s in self.seats if s.id in self.alive]

    def _mark_dead(self, seat_id: str, cause: str, announce: bool = True) -> None:
        if seat_id not in self.alive:
            return
        self.alive.discard(seat_id)
        self.dead_roles[seat_id] = self.roles[seat_id]
        if self.roles[seat_id] == "hunter" and cause != "poison":
            self.hunter_queue.append(seat_id)

    def _check_win(self) -> bool:
        if self.finished:
            return True
        wolves_alive = [w for w in self.wolves if w in self.alive]
        if not wolves_alive:
            self.finish("好人阵营", "所有狼人出局", {"roles": self.roles})
            return True
        villagers = [s.id for s in self.seats if self.roles[s.id] == "villager"]
        gods = [s.id for s in self.seats if self.roles[s.id] in {"seer", "witch", "hunter"}]
        if villagers and not any(v in self.alive for v in villagers):
            self.finish("狼人阵营", "屠边：所有村民出局", {"roles": self.roles})
            return True
        if gods and not any(g in self.alive for g in gods):
            self.finish("狼人阵营", "屠边：所有神职出局", {"roles": self.roles})
            return True
        return False

    # ---------------- 视图 ----------------
    def public_state(self) -> dict:
        return {
            "game": "werewolf",
            "round": self.round,
            "phase": self.phase,
            "seats": [
                {
                    "id": s.id,
                    "name": s.name,
                    "alive": s.id in self.alive,
                    "seat_no": idx + 1,
                    "color": s.color,
                }
                for idx, s in enumerate(self.seats)
            ],
            "alive_count": len(self.alive),
            "last_night": self.last_night,
            "stage": self.stage,
        }

    def private_state(self, seat_id: str) -> dict:
        role = self.roles.get(seat_id)
        if not role:
            return {}
        state: dict = {
            "role": role,
            "role_label": ROLES[role]["label"],
            "camp": ROLES[role]["camp"],
            "alive": seat_id in self.alive,
            "win_goal": "找出并放逐所有狼人" if ROLES[role]["camp"] == "好人阵营" else "消灭所有村民或所有神职",
            "seat_no": [s.id for s in self.seats].index(seat_id) + 1,
        }
        if role == "werewolf":
            state["teammates"] = [
                {"id": w, "name": self.seat_map[w].name, "alive": w in self.alive}
                for w in self.wolves
                if w != seat_id
            ]
        if role == "seer":
            state["checks"] = [
                {
                    "round": c["round"],
                    "seat": c["target"],
                    "name": self.seat_map[c["target"]].name,
                    "result": c["result"],
                }
                for c in self.seer_checks
            ]
        if role == "witch":
            state["antidote"] = self.antidote
            state["poison"] = self.poison
        items: list[dict] = []
        if role == "werewolf":
            items.append({"key": "wolf_blade", "label": "狼刀", "available": seat_id in self.alive})
        elif role == "witch":
            items.append({"key": "antidote", "label": "解药", "available": bool(self.antidote)})
            items.append({"key": "poison", "label": "毒药", "available": bool(self.poison)})
        elif role == "hunter":
            items.append(
                {
                    "key": "hunter_shot",
                    "label": "猎枪（出局时可开枪）",
                    "available": seat_id in self.alive or seat_id in self.hunter_queue,
                }
            )
        elif role == "seer":
            items.append({"key": "seer_check", "label": "查验（每夜一次）", "available": seat_id in self.alive})
        if items:
            state["items"] = items
        if self.finished:
            state["all_roles"] = {
                sid: {"role": r, "label": ROLES[r]["label"], "name": self.seat_map[sid].name}
                for sid, r in self.roles.items()
            }
        return state

    def fallback_action(self, req: ActionRequest) -> dict:
        if req.kind == "werewolf_chat":
            return {"speech": self.rng.choice(WOLF_HINTS)}
        if req.kind == "day_speech":
            return {"speech": self.rng.choice(DAY_HINTS)}
        if req.kind == "witch_action":
            # 女巫不一定救人：兜底时也在“用药 / 不用药”之间随机，并保留少量毒人可能。
            plain = [o for o in req.options if not o.action.get("poison")]
            toxic = [o for o in req.options if o.action.get("poison")]
            style = self.style_for(req.seat_id).get("name", "")
            poison_rate = 0.25 if style in {"激进", "诡诈"} else 0.08
            if toxic and self.rng.random() < poison_rate:
                return dict(self.rng.choice(toxic).action)
            if plain:
                return dict(self.rng.choice(plain).action)
            return {"save": False, "poison": None}
        if req.kind == "hunter_shot":
            return {"target": None}
        if req.kind in {"werewolf_vote", "day_vote"}:
            if req.options:
                return dict(self.rng.choice(req.options).action)
            return {"target": None}
        return super().fallback_action(req)


ENGINE = WerewolfEngine
