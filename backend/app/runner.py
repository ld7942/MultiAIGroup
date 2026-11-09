"""对局编排器：把引擎状态机、AI Provider、事件广播与持久化串起来。

职责：
1. 循环推进引擎，直到产生 ActionRequest；
2. 为每个请求的座位构造「只包含它可见信息」的上下文，调用对应 AI；
3. 校验 AI 输出，非法则带错误重试，最终失败时使用引擎兜底动作；
4. 把引擎事件写入 SQLite 并通过 WebSocket 广播。
"""
from __future__ import annotations

import asyncio
import inspect
import json
import random
import time
import traceback
from typing import Any, Awaitable, Callable

from .ai import AIClient, ProviderError, extract_json, normalize_envelope
from .engine import ActionError, ActionRequest, GameEngine, Seat, Visibility
from .games import create_engine

Broadcast = Callable[[dict], Awaitable[None] | None]

MAX_VISIBLE_EVENTS = 120
MAX_ATTEMPTS = 2
MAX_STEPS = 6000


class GameRunner:
    def __init__(
        self,
        match_id: str,
        game_id: str,
        seats: list[Seat],
        clients: dict[str, AIClient],
        store,
        broadcast: Broadcast | None = None,
        config: dict | None = None,
        rng_seed: int | None = None,
    ):
        self.match_id = match_id
        self.seats = seats
        self.seat_map = {s.id: s for s in seats}
        self.clients = clients
        self.store = store
        self.broadcast = broadcast
        config = config or {}
        seed = rng_seed if rng_seed is not None else config.get("rng_seed")
        rng = random.Random(int(seed)) if seed is not None else random.Random()
        self.engine: GameEngine = create_engine(game_id, seats, config, rng)
        self.task: asyncio.Task | None = None
        self.status = "running"
        self.error = ""
        self._stop = False
        self.reads: dict[str, list[dict]] = {}

    # ---------------- 生命周期 ----------------
    def start_task(self) -> None:
        if self.task and not self.task.done():
            return
        self.task = asyncio.create_task(self.run())

    async def run(self) -> None:
        self.store.update_match(self.match_id, status="running", started_at=time.time())
        started = time.time()
        try:
            self.engine.start()
            await self.flush()
            self._save_private()
            steps = 0
            while not self.engine.finished and not self._stop:
                steps += 1
                if steps > MAX_STEPS:
                    self.engine.finish("无结果", "对局步数超过上限，已中止")
                    break
                if not self.engine.has_waiting():
                    self.engine.advance()
                    await self.flush()
                    if self.engine.finished:
                        break
                    if not self.engine.has_waiting():
                        self.engine.finish("无结果", "引擎无法继续推进")
                        break
                    continue
                requests = self.engine.current_requests()
                if not requests:
                    break
                actions = await asyncio.gather(
                    *(self.resolve(req) for req in requests), return_exceptions=True
                )
                for req, action in zip(requests, actions):
                    if self.engine.finished:
                        break
                    if isinstance(action, BaseException):
                        action = self.engine.fallback_action(req)
                    try:
                        self.engine.submit(req.id, req.seat_id, action)
                    except Exception as exc:  # 兜底：确保状态机能继续
                        self.record_log(req, 0, f"提交动作失败：{exc}", {}, str(exc))
                        self.engine.submit(req.id, req.seat_id, self.engine.fallback_action(req))
                await self.flush()
            await self.flush()
            self.status = "finished" if self.engine.finished else "stopped"
        except asyncio.CancelledError:
            self.status = "stopped"
            raise
        except Exception as exc:
            self.status = "error"
            self.error = f"{exc}"
            traceback.print_exc()
            if not self.engine.finished:
                self.engine.finish("无结果", f"对局异常：{exc}")
            await self.flush()
        finally:
            self._save_private()
            snapshot = self.engine.snapshot()
            fields: dict[str, Any] = {
                "status": self.status,
                "state": snapshot,
                "result": self.engine.result or {},
                "privates": {
                    s.id: self.engine.private_state(s.id) for s in self.seats
                },
                "finished_at": time.time(),
            }
            if self.engine.finished:
                fields["status"] = "finished"
            self.store.update_match(self.match_id, **fields)
            await self.emit(
                {
                    "type": "match_status",
                    "match_id": self.match_id,
                    "status": fields["status"],
                    "state": snapshot,
                    "result": self.engine.result or {},
                    "error": self.error,
                    "elapsed": round(time.time() - started, 1),
                }
            )

    async def stop(self) -> None:
        self._stop = True
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
        self.status = "stopped"
        self.store.update_match(self.match_id, status="stopped", state=self.engine.snapshot())

    def is_active(self) -> bool:
        return bool(self.task and not self.task.done())

    # ---------------- AI 决策 ----------------
    async def resolve(self, req: ActionRequest) -> dict:
        seat = self.seat_map[req.seat_id]
        client = self.clients.get(req.seat_id)
        messages = self.build_messages(req, seat)
        if client is None:
            action = self.engine.fallback_action(req)
            self.record_log(req, 0, "未找到可用的 AI Provider，使用兜底动作", {}, "missing-client", messages[-1]["content"])
            return action
        last_text = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                raw = await client.chat(messages, json_mode=True, meta=self.mock_meta(req))
                last_text = raw
                data = normalize_envelope(extract_json(raw))
                action = data.get("action") or {}
                self.engine.validate_action(req.id, req.seat_id, action)
                self.record_log(req, attempt, last_text, data, "", messages[-1]["content"])
                self.record_meta(req, seat, data)
                return action
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.record_log(req, attempt, last_text, {}, f"{type(exc).__name__}: {exc}", messages[-1]["content"])
                if attempt < MAX_ATTEMPTS:
                    messages = messages + [
                        {"role": "assistant", "content": last_text or "（空输出）"},
                        {
                            "role": "user",
                            "content": (
                                f"你的上一条输出无法使用：{exc}。\n"
                                "请严格只输出一个 JSON 对象，action 必须是当前可选动作之一。"
                            ),
                        },
                    ]
                    await asyncio.sleep(0)
        action = self.engine.fallback_action(req)
        self.record_log(req, MAX_ATTEMPTS + 1, last_text, action, "已使用兜底动作", messages[-1]["content"])
        return action

    def record_meta(self, req: ActionRequest, seat: Seat, data: dict) -> None:
        notes = str(data.get("notes") or "").strip()
        if notes:
            self.engine.emit(
                "agent_notes",
                f"{seat.name} 的内心判断：{notes}",
                visibility=Visibility.private(req.seat_id),
                seat_id=req.seat_id,
                notes=notes,
            )
        reads = data.get("reads")
        if isinstance(reads, list) and reads:
            cleaned = [r for r in reads if isinstance(r, dict)][:12]
            self.reads[req.seat_id] = cleaned
            self.engine.emit(
                "agent_reads",
                f"{seat.name} 更新了身份预测",
                visibility=Visibility.private(req.seat_id),
                seat_id=req.seat_id,
                reads=cleaned,
            )

    def record_log(
        self,
        req: ActionRequest,
        attempt: int,
        raw: str,
        parsed: dict,
        error: str,
        user_prompt: str = "",
    ) -> None:
        try:
            self.store.add_log(
                self.match_id,
                req.seat_id,
                req.id,
                attempt,
                self.seat_map[req.seat_id].provider_name,
                self.system_prompt(),
                user_prompt,
                raw,
                parsed,
                error,
            )
        except Exception:
            pass

    # ---------------- 提示词 ----------------
    def system_prompt(self) -> str:
        engine = self.engine
        lines = [
            f"你是多 AI 对局平台中的一名玩家，正在参与《{engine.name}》。",
            "【游戏规则】",
            engine.rules,
            "",
            "【输出协议】只输出一个 JSON 对象，不要输出 Markdown 或额外解释：",
            '{"speech": "你要说的话（没有则为空字符串）", '
            '"action": {当前决策}, '
            '"notes": "你的私密思考，只有你自己能看到", '
            '"reads": [{"seat": "座位ID", "name": "玩家名", "role": "你推测的身份", "confidence": 0.0, "reason": "依据"}]}',
            "reads 用于记录你对其他玩家身份的多重预测，可以写多条，也可以留空数组。",
            "你只能依据下方提供给你的信息行动，不要假设自己知道未公开的身份或他人手牌。",
        ]
        return "\n".join(lines)

    def build_messages(self, req: ActionRequest, seat: Seat) -> list[dict]:
        engine = self.engine
        visible = self.render_events(req.seat_id)
        public_state = json.dumps(engine.public_state(), ensure_ascii=False, indent=1)
        private_state = json.dumps(engine.private_state(req.seat_id), ensure_ascii=False, indent=1)
        parts = [
            f"【你的角色】{seat.name}（座位 {self.seat_index(seat.id) + 1}）"
            + (f"，人设：{seat.persona}" if seat.persona else ""),
            f"【当前阶段】第 {engine.round} 轮 / {engine.phase}",
            f"【公开局势】\n{public_state}",
            f"【你的私有信息】\n{private_state}",
            f"【你可以看到的历史事件】\n{visible or '（暂无）'}",
            self.describe_request(req),
        ]
        user = "\n\n".join(parts)
        return [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": user},
        ]

    def describe_request(self, req: ActionRequest) -> str:
        lines = [f"【现在轮到你行动】{req.title}", req.instruction]
        if req.options:
            lines.append("可选动作（action 必须与其中一项一致）：")
            for opt in req.options:
                lines.append(f"- {opt.label} => {json.dumps(opt.action, ensure_ascii=False)}")
        else:
            lines.append("本次只需要发言，action 输出空对象 {} 即可。")
        if req.action_schema:
            lines.append(f"action 字段说明：{json.dumps(req.action_schema, ensure_ascii=False)}")
        return "\n".join(lines)

    def render_events(self, seat_id: str) -> str:
        events = self.engine.events_for(seat_id)
        return "\n".join(
            f"[R{ev.round} {ev.phase}] {ev.text}" for ev in events[-MAX_VISIBLE_EVENTS:]
        )

    def seat_index(self, seat_id: str) -> int:
        for idx, seat in enumerate(self.seats):
            if seat.id == seat_id:
                return idx
        return 0

    def mock_meta(self, req: ActionRequest) -> dict:
        return {
            "options": [o.to_dict() for o in req.options],
            "speech_hints": req.meta.get("speech_hints") or [],
            "request_kind": req.kind,
        }

    # ---------------- 广播 / 持久化 ----------------
    async def flush(self) -> None:
        events = self.engine.take_events()
        if not events:
            return
        payload = [ev.to_dict() for ev in events]
        self.store.append_events(self.match_id, payload)
        await self.emit({"type": "events", "match_id": self.match_id, "events": payload})
        await self.emit_state()

    async def emit_state(self) -> None:
        await self.emit(
            {
                "type": "state",
                "match_id": self.match_id,
                "state": self.engine.snapshot(),
                "privates": {s.id: self.engine.private_state(s.id) for s in self.seats},
                "reads": self.reads,
            }
        )

    async def emit(self, payload: dict) -> None:
        if not self.broadcast:
            return
        try:
            result = self.broadcast(payload)
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass

    def _save_private(self) -> None:
        try:
            self.store.update_match(
                self.match_id,
                privates={s.id: self.engine.private_state(s.id) for s in self.seats},
                state=self.engine.snapshot(),
            )
        except Exception:
            pass


class RunnerManager:
    """全局对局运行器管理。"""

    def __init__(self, store, broadcast: Broadcast):
        self.store = store
        self.broadcast = broadcast
        self.runners: dict[str, GameRunner] = {}

    def get(self, match_id: str) -> GameRunner | None:
        return self.runners.get(match_id)

    def launch(
        self,
        match: dict,
        seats: list[Seat],
        clients: dict[str, AIClient],
    ) -> GameRunner:
        runner = GameRunner(
            match_id=match["id"],
            game_id=match["game_id"],
            seats=seats,
            clients=clients,
            store=self.store,
            broadcast=self.broadcast,
            config=match.get("config") or {},
        )
        self.runners[match["id"]] = runner
        runner.start_task()
        return runner

    async def stop(self, match_id: str) -> bool:
        runner = self.runners.get(match_id)
        if not runner:
            return False
        await runner.stop()
        return True

    async def shutdown(self) -> None:
        for runner in list(self.runners.values()):
            await runner.stop()
        self.runners.clear()
