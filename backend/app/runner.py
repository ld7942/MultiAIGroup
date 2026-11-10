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
from .engine import ActionError, ActionRequest, GameEvent, GameEngine, Seat, Visibility
from .plugins import create_engine
from .rag import (
    add_lesson,
    auto_lessons,
    compress_events,
    key_moments,
    load_rag,
    search as rag_search,
)
from .voice import load_voice, speak_system, synthesize_voicestudio

Broadcast = Callable[[dict], Awaitable[None] | None]
ClientCount = Callable[[str], bool]

MAX_VISIBLE_EVENTS = 120
MAX_ATTEMPTS = 2
MAX_STEPS = 6000

# 用玩家自己的音色朗读的事件（公开、且是该玩家的发言/动作）。
SEAT_VOICE_EVENTS = {"speech", "play", "pass", "bid", "use_card", "respond", "vote"}
# 由“上帝/旁白”音色朗读的系统播报。
NARRATOR_VOICE_EVENTS = {
    "game_start", "phase", "night_result", "death", "vote_result", "game_over",
    "hunter_shot", "landlord", "bid_result", "new_trick", "damage", "dying", "discard",
}


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
        voice: dict | None = None,
        acks=None,
        has_clients: ClientCount | None = None,
        rag: dict | None = None,
        persist: bool = True,
        log_calls: bool = True,
    ):
        self.match_id = match_id
        self.seats = seats
        self.seat_map = {s.id: s for s in seats}
        self.clients = clients
        self.store = store
        self.broadcast = broadcast
        # voice 为 None 时每次朗读前从数据库热加载，运行中修改语音配置立即生效；
        # 显式传入 voice（测试 / 训练）则固定使用该配置。
        self._hot_voice = voice is None
        self.voice = load_voice(store) if voice is None and store is not None else (voice or {})
        # 前端检测到浏览器没有语音引擎时，可要求本局改用系统语音。
        self.voice_provider = ""
        self.rag = rag or load_rag(store)
        self.acks = acks
        self.has_clients = has_clients
        self.persist = persist
        self.log_calls = log_calls
        config = config or {}
        seed = rng_seed if rng_seed is not None else config.get("rng_seed")
        rng = random.Random(int(seed)) if seed is not None else random.Random()
        self.engine: GameEngine = create_engine(game_id, seats, config, rng)
        self.task: asyncio.Task | None = None
        self.status = "running"
        self.error = ""
        self._stop = False
        self.reads: dict[str, list[dict]] = {}
        self.review: dict[str, list[str]] = {}

    # ---------------- 生命周期 ----------------
    def start_task(self) -> None:
        if self.task and not self.task.done():
            return
        self.task = asyncio.create_task(self.run())

    async def run(self) -> None:
        if self.persist:
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
            # 对局结束后把本局压缩成技巧写入 RAG；失败不影响对局结果保存。
            if self.engine.finished and self.rag.get("enabled", True) and self.rag.get("reflect", True):
                try:
                    await self.reflect()
                except Exception:
                    traceback.print_exc()
            if self.review:
                self.engine.result = {**(self.engine.result or {}), "review": self.review}
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
            if self.persist:
                self.store.update_match(self.match_id, **fields)
            await self.emit(
                {
                    "type": "match_status",
                    "match_id": self.match_id,
                    "status": fields["status"],
                    "state": snapshot,
                    "result": self.engine.result or {},
                    "review": self.review,
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
        if self.persist:
            self.store.update_match(self.match_id, status="stopped", state=self.engine.snapshot())

    def is_active(self) -> bool:
        return bool(self.task and not self.task.done())

    # ---------------- 复盘 / RAG ----------------
    async def reflect(self) -> None:
        """把每个座位本局的可见上下文压缩成技巧，写入向量记忆库。"""
        await asyncio.gather(
            *(self._reflect_seat(seat) for seat in self.seats),
            return_exceptions=True,
        )

    async def _reflect_seat(self, seat: Seat) -> None:
        role = self.engine.tactic_tags(seat.id).get("role", "")
        faction = self.engine.tactic_tags(seat.id).get("faction", "")
        events = self.engine.events_for(seat.id)
        transcript = compress_events(events, head=4, tail=40)
        moments = key_moments(events, 6)
        result = self.engine.result or {}
        winner = str(result.get("winner") or "")
        won = bool(
            winner
            and (
                (role and role in winner)
                or (faction and faction in winner)
                or (faction and winner in faction)
            )
        )
        result_text = f"胜方：{winner or '无'}；原因：{result.get('reason') or '无'}"

        lessons: list[str] = []
        client = self.clients.get(seat.id)
        if (
            client is not None
            and client.cfg.kind != "mock"
            and self.rag.get("llm_reflect", True)
        ):
            try:
                raw = await client.chat(
                    [
                        {
                            "role": "system",
                            "content": (
                                "你是资深桌面游戏复盘教练。根据该玩家的可见视角与最终结果，"
                                "提炼 2-3 条可迁移、可执行的技巧，必须具体到「下次遇到什么局面该怎么做」；"
                                "不要评价运气，不要空话。只输出 JSON："
                                '{"lessons": ["技巧1", "技巧2"]}'
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"游戏：{self.engine.name}\n角色：{role or '未知'}\n阵营：{faction or '未知'}\n"
                                f"你的结果：{'获胜' if won else '落败'}（{result_text}）\n"
                                f"你本局的身份预测：{json.dumps(self.reads.get(seat.id, []), ensure_ascii=False)}\n"
                                f"压缩后的对局记录：\n{transcript}"
                            ),
                        },
                    ],
                    json_mode=True,
                    timeout=45,
                )
                data = extract_json(raw)
                items = data.get("lessons")
                if isinstance(items, list):
                    lessons = [str(item).strip() for item in items if str(item).strip()][:3]
            except Exception:
                lessons = []
        if not lessons:
            lessons = auto_lessons(
                self.engine.game_id, role, faction, won, moments
            )
        lessons = list(dict.fromkeys(lessons))[:4]
        if not lessons:
            return
        self.review[seat.id] = lessons
        for text in lessons:
            add_lesson(
                self.store,
                self.engine.game_id,
                role,
                faction,
                self.match_id,
                text,
                source="reflect" if client is not None else "auto",
            )

    def memory_block(self, req: ActionRequest, seat: Seat) -> str:
        """按当前角色与局面检索 RAG 记忆，拼成可注入提示词的一段。"""
        if not self.rag.get("enabled", True):
            return ""
        tags = self.engine.tactic_tags(req.seat_id)
        role = tags.get("role", "")
        faction = tags.get("faction", "")
        recent = "\n".join(ev.text for ev in self.engine.events_for(req.seat_id)[-12:])
        query = " ".join(
            part
            for part in (
                role,
                faction,
                self.engine.skill_for(req.seat_id),
                req.title,
                req.instruction,
                recent,
            )
            if part
        )
        try:
            memories = rag_search(
                self.store,
                query,
                game_id=self.engine.game_id,
                role=role,
                faction=faction,
                top_k=int(self.rag.get("top_k") or 4),
                min_score=float(self.rag.get("min_score") or 0.06),
            )
        except Exception:
            return ""
        # 当前角色的技能卡已经注入系统提示词，这里不再重复占预算。
        memories = [
            item
            for item in memories
            if not (item.get("kind") == "skill" and item.get("role") == role)
        ]
        if not memories:
            return ""
        lines = ["【历史经验与技巧（RAG 记忆库，按相关度检索）】"]
        for item in memories:
            lines.append(f"- [{item.get('kind', 'lesson')}] {item.get('text', '')}")
        lines.append("这些经验只作参考；与当前局势冲突时，以你眼前的信息为准。")
        return "\n".join(lines)

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
                                "请重新对照玩法技能卡与自检清单，严格只输出一个 JSON 对象，"
                                "action 必须是当前可选动作之一。"
                            ),
                        },
                    ]
                    await asyncio.sleep(0)
        action = self.engine.fallback_action(req)
        self.record_log(req, MAX_ATTEMPTS + 1, last_text, action, "已使用兜底动作", messages[-1]["content"])
        return action

    def record_meta(self, req: ActionRequest, seat: Seat, data: dict) -> None:
        notes = str(data.get("notes") or "").strip()
        stance = str(data.get("stance") or "").strip()
        plan = data.get("plan")
        if isinstance(plan, list):
            plan_text = " → ".join(str(item) for item in plan if str(item).strip())
        else:
            plan_text = str(plan or "").strip()
        detail = []
        if plan_text:
            detail.append(f"计划：{plan_text}")
        if notes:
            detail.append(f"判断：{notes}")
        text = "；".join(detail)
        if text:
            prefix = f"[{stance}] " if stance else ""
            self.engine.emit(
                "agent_notes",
                f"{seat.name} 的内心判断：{prefix}{text}",
                visibility=Visibility.private(req.seat_id),
                seat_id=req.seat_id,
                notes=notes,
                plan=plan_text,
                stance=stance,
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
        if not self.log_calls:
            return
        try:
            self.store.add_log(
                self.match_id,
                req.seat_id,
                req.id,
                attempt,
                self.seat_map[req.seat_id].provider_name,
                self.system_prompt(req.seat_id),
                user_prompt,
                raw,
                parsed,
                error,
            )
        except Exception:
            pass

    # ---------------- 提示词 ----------------
    def system_prompt(self, seat_id: str | None = None) -> str:
        engine = self.engine
        lines = [
            f"你是多 AI 对局平台中的一名玩家，正在参与《{engine.name}》。",
            "【游戏规则】",
            engine.rules,
            "",
            engine.decision_protocol(),
        ]
        style = engine.style_for(seat_id) if seat_id else None
        if style:
            lines += [
                "",
                f"【本局性格：{style['name']}】{style['prompt']}",
                "性格只影响你的取舍与表达，不能违反规则，也不能凭空获得未公开的信息。",
            ]
        skill = engine.skill_for(seat_id).strip() if seat_id else ""
        if skill:
            lines += [
                "",
                "【玩法技能卡】把下面这段当作你本局的专属技能说明：先按它和决策流程推演，再行动。",
                skill,
            ]
        lines += [
            "",
            "【输出协议】只输出一个 JSON 对象，不要输出 Markdown 或额外解释：",
            '{"stance": "support|attack|neutral", '
            '"speech": "你要说的话（没有则为空字符串）", '
            '"plan": ["步骤1：观察到什么", "步骤2：为什么选这个动作"], '
            '"action": {当前决策}, '
            '"notes": "你的私密思考，只有你自己能看到", '
            '"reads": [{"seat": "座位ID", "name": "玩家名", "role": "你推测的身份", "confidence": 0.0, "reason": "依据"}]}',
            "reads 用于记录你对其他玩家身份的多重预测，可以写多条，也可以留空数组；它会保留到你的下一次行动。",
            "speech 会被语音朗读，请使用自然、口语化、简短的中文；没有话说时留空字符串（规则要求发言时不能为空）。",
            "出牌或使用卡牌时，speech 应先是一句自然的聊天（挑衅、吐槽、分析都行），系统会先读聊天，再读出你打出的牌。",
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
        ]
        previous_reads = self.reads.get(req.seat_id)
        if previous_reads:
            parts.append(
                "【你之前记录的身份概率】\n" + json.dumps(previous_reads, ensure_ascii=False, indent=1)
            )
        parts.append(f"【你可以看到的历史事件】\n{visible or '（暂无）'}")
        hint = engine.action_hint(req, req.seat_id).strip()
        if hint:
            parts.append(f"【本步策略检查】\n{hint}")
        memory = self.memory_block(req, seat)
        if memory:
            parts.append(memory)
        parts.append(self.describe_request(req))
        user = "\n\n".join(parts)
        return [
            {"role": "system", "content": self.system_prompt(req.seat_id)},
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
        lines.append("输出前自检：目标必须是存活玩家、不能是自己（规则允许除外），且必须是上面列出的合法动作。")
        return "\n".join(lines)

    def render_events(self, seat_id: str) -> str:
        events = self.engine.events_for(seat_id)
        # 长对局保留最近事件，早期大量重复事件压缩成摘要，避免提示词无限膨胀。
        if len(events) > 100:
            return compress_events(events)
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

    # ---------------- 语音 ----------------
    def seat_voice_id(self, seat_id: str | None) -> str:
        seat = self.seat_map.get(seat_id or "")
        return (seat.voice_id if seat else "") or str(self.voice.get("default_voice_id") or "")

    def narrator_voice_id(self) -> str:
        return str(self.voice.get("narrator_voice_id") or self.voice.get("default_voice_id") or "")

    def voice_line(self, ev: GameEvent) -> dict | None:
        """决定一条事件是否朗读、由谁的音色朗读；只朗读公开事件。"""
        if ev.visibility.scope != "public":
            return None
        if ev.type == "speech":
            if not ev.seat_id:
                return None
            text = str(ev.payload.get("speech") or ev.text or "").strip()
            if not text:
                return None
            return {
                "text": text,
                "voice_id": self.seat_voice_id(ev.seat_id),
                "role": "seat",
                "seat_id": ev.seat_id,
            }
        if ev.type in SEAT_VOICE_EVENTS and ev.seat_id:
            seat = self.seat_map.get(ev.seat_id)
            text = ev.text or ""
            if seat:
                text = text.replace(f"{seat.name}：", "", 1)
                if text.startswith(f"{seat.name} "):
                    text = text[len(seat.name) + 1 :]
            text = text.strip()
            if not text:
                return None
            return {
                "text": text,
                "voice_id": self.seat_voice_id(ev.seat_id),
                "role": "seat",
                "seat_id": ev.seat_id,
            }
        if ev.type in NARRATOR_VOICE_EVENTS:
            text = (ev.text or "").strip()
            if not text:
                return None
            return {
                "text": text,
                "voice_id": self.narrator_voice_id(),
                "role": "narrator",
                "seat_id": None,
            }
        return None

    async def speak_events(self, events: list[GameEvent]) -> None:
        """按顺序朗读事件，等待前端回执 speech_done 后再继续。

        未启用语音、没有客户端或事件不可公开朗读时直接跳过，保持原有行为。
        provider 为 system 时由后端调用 Windows SAPI 本机朗读，不依赖浏览器语音引擎。
        """
        if self._hot_voice and self.store is not None:
            try:
                self.voice = load_voice(self.store)
            except Exception:
                pass
        if self.voice_provider and (self.voice.get("provider") or "browser") != "browser":
            # 用户显式切换了语音通道，撤销本局的自动兜底。
            self.voice_provider = ""
        if not self.voice.get("enabled") or not self.broadcast:
            return
        lines: list[tuple[GameEvent, dict]] = []
        for ev in events:
            line = self.voice_line(ev)
            if line:
                lines.append((ev, line))
        if not lines:
            return
        if self.has_clients is not None and not self.has_clients(self.match_id):
            return
        provider = self.voice_provider or str(self.voice.get("provider") or "browser")
        if provider not in {"browser", "voicestudio", "system"}:
            provider = "browser"
        try:
            timeout = max(1.0, float(self.voice.get("wait_ms") or 15000) / 1000)
        except (TypeError, ValueError):
            timeout = 15.0
        speed = self.voice.get("speed", 1.0)
        for ev, line in lines:
            if provider == "system":
                if await speak_system(self.voice, line["text"], line["voice_id"]):
                    continue
                # 系统语音不可用时退回浏览器朗读。
                provider = "browser"
            if self.has_clients is not None and not self.has_clients(self.match_id):
                break
            speech_id = f"{self.match_id}:{ev.seq}"
            payload: dict[str, Any] = {
                "type": "voice",
                "match_id": self.match_id,
                "speech_id": speech_id,
                "seq": ev.seq,
                "text": line["text"],
                "voice_id": line["voice_id"],
                "role": line["role"],
                "seat_id": line["seat_id"],
                "speed": speed,
                "provider": provider,
            }
            if provider == "voicestudio":
                audio = await synthesize_voicestudio(self.voice, line["text"], line["voice_id"])
                if audio:
                    payload.update(audio)
            if self.acks:
                self.acks.prepare(speech_id)
            await self.emit(payload)
            if self.acks:
                await self.acks.wait(speech_id, timeout)

    # ---------------- 广播 / 持久化 ----------------
    async def flush(self) -> None:
        events = self.engine.take_events()
        if not events:
            return
        payload = [ev.to_dict() for ev in events]
        if self.persist:
            self.store.append_events(self.match_id, payload)
        await self.emit({"type": "events", "match_id": self.match_id, "events": payload})
        await self.emit_state()
        await self.speak_events(events)

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
        if not self.persist:
            return
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

    def __init__(
        self,
        store,
        broadcast: Broadcast,
        acks=None,
        has_clients: ClientCount | None = None,
    ):
        self.store = store
        self.broadcast = broadcast
        self.acks = acks
        self.has_clients = has_clients
        self.rag = load_rag(store)
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
            voice=None,
            acks=self.acks,
            has_clients=self.has_clients,
            rag=load_rag(self.store),
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
