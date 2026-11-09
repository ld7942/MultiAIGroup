"""公共游戏引擎接口。

所有游戏（狼人杀 / 斗地主 / 三国杀 / 后续新增）只需实现 GameEngine 的
start / advance / apply / public_state / private_state 五个方法。

引擎不感知 AI、网络、数据库：
- 引擎产出 ActionRequest，只发给指定的座位；
- 引擎产出 GameEvent，带 Visibility，编排器按可见性裁剪每个 AI 的上下文；
- 引擎内部维护状态机，advance() 自动推进到下一个需要决策的点。
"""
from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

VisibilityScope = Literal["public", "private", "group"]


class ActionError(Exception):
    """AI 提交了非法动作，编排器会带着错误信息让 AI 重试。"""


@dataclass(frozen=True)
class Visibility:
    scope: VisibilityScope = "public"
    seats: tuple[str, ...] = ()

    @staticmethod
    def public() -> "Visibility":
        return Visibility("public", ())

    @staticmethod
    def private(*seats: str) -> "Visibility":
        return Visibility("private", tuple(seats))

    @staticmethod
    def group(*seats: str) -> "Visibility":
        return Visibility("group", tuple(seats))

    def allows(self, seat_id: str) -> bool:
        return self.scope == "public" or seat_id in self.seats

    def to_dict(self) -> dict:
        return {"scope": self.scope, "seats": list(self.seats)}


@dataclass
class GameEvent:
    seq: int
    ts: float
    type: str
    text: str
    payload: dict
    visibility: Visibility
    seat_id: str | None
    round: int
    phase: str

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "type": self.type,
            "text": self.text,
            "payload": self.payload,
            "visibility": self.visibility.to_dict(),
            "seat_id": self.seat_id,
            "round": self.round,
            "phase": self.phase,
        }


@dataclass
class ActionOption:
    id: str
    label: str
    action: dict
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "action": self.action,
            "description": self.description,
        }


@dataclass
class ActionRequest:
    id: str
    seat_id: str
    kind: str
    title: str
    instruction: str
    options: list[ActionOption] = field(default_factory=list)
    action_schema: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    visibility: str = "private"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "seat_id": self.seat_id,
            "kind": self.kind,
            "title": self.title,
            "instruction": self.instruction,
            "options": [o.to_dict() for o in self.options],
            "action_schema": self.action_schema,
            "meta": self.meta,
            "visibility": self.visibility,
        }


@dataclass
class Seat:
    id: str
    name: str
    provider_id: str
    persona: str = ""
    provider_name: str = ""
    model: str = ""
    color: str = "#7c9cff"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "model": self.model,
            "persona": self.persona,
            "color": self.color,
        }


class GameEngine(ABC):
    game_id: str = ""
    name: str = ""
    description: str = ""
    min_players: int = 2
    max_players: int = 10
    allowed_counts: tuple[int, ...] = ()
    rules: str = ""
    presets: list[dict] = []

    def __init__(self, seats: list[Seat], config: dict | None = None, rng: random.Random | None = None):
        self.seats = seats
        self.seat_map = {s.id: s for s in seats}
        self.config = config or {}
        self.rng = rng or random.Random()
        self.round = 0
        self.phase = "准备"
        self.finished = False
        self.result: dict | None = None
        self._events: list[GameEvent] = []
        self._history: list[GameEvent] = []
        self._seq = 0
        self._requests: dict[str, ActionRequest] = {}
        self._all_requests: dict[str, ActionRequest] = {}
        self._waiting: set[str] = set()
        self._req_counter = 0

    # ---------- 事件 / 请求 ----------
    def emit(
        self,
        type_: str,
        text: str,
        *,
        visibility: Visibility | None = None,
        seat_id: str | None = None,
        **payload: Any,
    ) -> GameEvent:
        self._seq += 1
        payload = {"text": text, **payload}
        ev = GameEvent(
            seq=self._seq,
            ts=time.time(),
            type=type_,
            text=text,
            payload=payload,
            visibility=visibility or Visibility.public(),
            seat_id=seat_id,
            round=self.round,
            phase=self.phase,
        )
        self._events.append(ev)
        self._history.append(ev)
        return ev

    def say(self, seat_id: str, text: str, visibility: Visibility | None = None) -> None:
        if not text:
            return
        seat = self.seat_map[seat_id]
        self.emit(
            "speech",
            f"{seat.name}：{text}",
            visibility=visibility or Visibility.public(),
            seat_id=seat_id,
            speech=text,
            seat_name=seat.name,
        )

    def take_events(self) -> list[GameEvent]:
        events = self._events
        self._events = []
        return events

    def events_for(self, seat_id: str) -> list[GameEvent]:
        """返回该座位可见的全部历史事件（不消费事件缓冲）。"""
        return [ev for ev in self._history if ev.visibility.allows(seat_id)]

    def request(
        self,
        seat_id: str,
        kind: str,
        title: str,
        instruction: str,
        *,
        options: list[ActionOption] | None = None,
        action_schema: dict | None = None,
        meta: dict | None = None,
    ) -> ActionRequest:
        self._req_counter += 1
        req = ActionRequest(
            id=f"R{self._req_counter}",
            seat_id=seat_id,
            kind=kind,
            title=title,
            instruction=instruction,
            options=options or [],
            action_schema=action_schema or {},
            meta=meta or {},
        )
        self._requests[req.id] = req
        self._all_requests[req.id] = req
        self._waiting.add(req.id)
        return req

    def current_requests(self) -> list[ActionRequest]:
        return list(self._requests.values())

    def has_waiting(self) -> bool:
        return bool(self._waiting)

    def raise_for_waiting(self) -> None:
        if self._waiting:
            raise RuntimeError(f"还有未完成的请求: {sorted(self._waiting)}")

    def get_request(self, request_id: str) -> ActionRequest:
        req = self._all_requests.get(request_id)
        if req is None:
            raise ActionError(f"未知的请求 {request_id}")
        return req

    def validate_action(self, request_id: str, seat_id: str, action: dict) -> None:
        req = self.get_request(request_id)
        if req.seat_id != seat_id:
            raise ActionError("该请求不属于你")
        if request_id not in self._requests:
            raise ActionError("该请求已失效")
        if not isinstance(action, dict):
            raise ActionError("action 必须是 JSON 对象")
        self.validate(req, action)

    def validate(self, req: ActionRequest, action: dict) -> None:
        """子类可覆盖，做动作合法性校验（失败抛 ActionError）。"""

    def submit(self, request_id: str, seat_id: str, action: dict) -> None:
        self.validate_action(request_id, seat_id, action)
        req = self._requests.pop(request_id)
        self._waiting.discard(request_id)
        self.apply(req, action)

    def fallback_action(self, req: ActionRequest) -> dict:
        if req.options:
            return dict(req.options[0].action)
        return self.default_action(req)

    def default_action(self, req: ActionRequest) -> dict:
        return {}

    # ---------- 生命周期 ----------
    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def advance(self) -> None:
        """自动推进，直到产生请求 / 结束 / 需要等待。"""

    @abstractmethod
    def apply(self, req: ActionRequest, action: dict) -> None: ...

    @abstractmethod
    def public_state(self) -> dict: ...

    @abstractmethod
    def private_state(self, seat_id: str) -> dict: ...

    def legal_actions(self, req: ActionRequest) -> list[dict]:
        return [dict(o.action) for o in req.options]

    # ---------- 工具 ----------
    def finish(self, winner: str, reason: str, summary: dict | None = None) -> None:
        if self.finished:
            return
        self.finished = True
        self.phase = "结束"
        self.result = {"winner": winner, "reason": reason, **(summary or {})}
        self.emit(
            "game_over",
            f"对局结束：{winner} 获胜（{reason}）",
            winner=winner,
            reason=reason,
            summary=summary or {},
        )

    def snapshot(self) -> dict:
        return {
            "game_id": self.game_id,
            "name": self.name,
            "round": self.round,
            "phase": self.phase,
            "finished": self.finished,
            "result": self.result,
            "public_state": self.public_state(),
            "requests": [r.to_dict() for r in self.current_requests()],
        }
