"""自对弈训练场：后台批量跑对局，只统计结果，不做实时观战与日志落库。

用途：
- 让同一批 AI（尤其是 Ollama 本地模型）连续自对弈，快速积累技巧与胜率统计；
- 复用 :class:`GameRunner`，但关闭事件持久化、AI 调用日志与语音，避免训练时数据库膨胀；
- 前端只展示进度、局数、胜率与最近结果，不进入完整牌桌流程。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from .ai import AIClient, config_from_row
from .engine import Seat
from .plugins import get_engine_class
from .rag import load_rag
from .runner import GameRunner


DEFAULT_TIMEOUT = 900.0


class TrainManager:
    def __init__(self, store) -> None:
        self.store = store
        self.job: dict[str, Any] | None = None
        self.task: asyncio.Task | None = None

    # ---------------- 生命周期 ----------------
    async def start(self, payload: dict) -> dict:
        if self.task and not self.task.done():
            raise ValueError("已有训练任务在运行，请先停止")
        job = self._build_job(payload)
        self.job = job
        self.task = asyncio.create_task(self._run(job))
        return self.status()

    async def stop(self) -> dict:
        job = self.job
        if not job or not self.task or self.task.done():
            return self.status()
        job["stopping"] = True
        self.task.cancel()
        try:
            await self.task
        except (asyncio.CancelledError, Exception):
            pass
        if job["status"] == "running":
            job["status"] = "stopped"
            job["finished_at"] = time.time()
        return self.status()

    async def shutdown(self) -> None:
        await self.stop()

    def status(self) -> dict:
        job = self.job
        if not job:
            return {
                "status": "idle",
                "total": 0,
                "done": 0,
                "failed": 0,
                "progress": 0.0,
                "winners": {},
                "avg_rounds": 0,
                "avg_seconds": 0,
                "elapsed": 0,
                "lessons": 0,
                "recent": [],
                "error": "",
            }
        total = max(1, int(job["total"]))
        done = int(job["done"])
        elapsed = (job.get("finished_at") or time.time()) - job["started_at"]
        return {
            "id": job["id"],
            "status": job["status"],
            "game_id": job["game_id"],
            "game_name": job["game_name"],
            "total": job["total"],
            "done": done,
            "failed": job["failed"],
            "progress": round(min(1.0, done / total), 3),
            "winners": dict(job["winners"]),
            "avg_rounds": round(job["rounds"] / done, 1) if done else 0,
            "avg_seconds": round(job["elapsed"] / done, 2) if done else 0,
            "elapsed": round(elapsed, 1),
            "lessons": job["lessons"],
            "recent": job["recent"][:20],
            "error": job["error"],
            "config": job["config"],
        }

    # ---------------- 内部 ----------------
    def _build_job(self, payload: dict) -> dict:
        game_id = str(payload.get("game_id") or "").strip()
        engine_cls = get_engine_class(game_id)
        if engine_cls is None:
            raise ValueError(f"未知游戏 {game_id}")

        provider_ids = [str(x) for x in (payload.get("provider_ids") or []) if str(x).strip()]
        if not provider_ids:
            single = str(payload.get("provider_id") or "").strip()
            if single:
                provider_ids = [single]
        if not provider_ids:
            raise ValueError("请至少选择一个 Provider")
        providers = []
        for pid in provider_ids:
            row = self.store.get_provider(pid)
            if not row:
                raise ValueError(f"Provider {pid} 不存在")
            providers.append(row)

        allowed = list(engine_cls.allowed_counts or ())
        default_seats = allowed[0] if allowed else engine_cls.min_players
        seat_count = int(payload.get("seat_count") or default_seats)
        if allowed and seat_count not in allowed:
            raise ValueError(f"{engine_cls.name} 支持 {allowed} 人")
        if not (engine_cls.min_players <= seat_count <= engine_cls.max_players):
            raise ValueError(f"{engine_cls.name} 需要 {engine_cls.min_players}-{engine_cls.max_players} 人")

        total = int(payload.get("games") or 20)
        total = max(1, min(total, 500))
        concurrency = int(payload.get("concurrency") or 1)
        concurrency = max(1, min(concurrency, 8))
        rag = load_rag(self.store)
        rag_enabled = bool(payload.get("rag_enabled", True))
        reflect = bool(payload.get("reflect", True))
        llm_reflect = bool(payload.get("llm_reflect", False))
        return {
            "id": uuid.uuid4().hex[:10],
            "game_id": game_id,
            "game_name": engine_cls.name,
            "engine_cls": engine_cls,
            "providers": providers,
            "provider_names": [p["name"] for p in providers],
            "seat_count": seat_count,
            "total": total,
            "concurrency": concurrency,
            "rag": {**rag, "enabled": rag_enabled, "reflect": reflect, "llm_reflect": llm_reflect},
            "rag_enabled": rag_enabled,
            "config": {**(payload.get("config") or {}), "rng_seed": int(payload.get("seed") or 0) or None},
            "seed": int(payload.get("seed") or 0) or int(time.time()),
            "timeout": float(payload.get("timeout") or DEFAULT_TIMEOUT),
            "status": "running",
            "done": 0,
            "failed": 0,
            "winners": {},
            "rounds": 0.0,
            "elapsed": 0.0,
            "lessons": 0,
            "recent": [],
            "error": "",
            "stopping": False,
            "started_at": time.time(),
            "finished_at": None,
            "_lock": asyncio.Lock(),
        }

    async def _run(self, job: dict) -> None:
        try:
            before = self.store.count_memories()
            sem = asyncio.Semaphore(job["concurrency"])

            async def one(index: int) -> None:
                async with sem:
                    if job["stopping"]:
                        return
                    await self._play_one(job, index)

            tasks = [asyncio.create_task(one(i)) for i in range(job["total"])]
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
            if job["stopping"]:
                job["status"] = "stopped"
            else:
                job["status"] = "finished"
            job["lessons"] = max(0, self.store.count_memories() - before)
        except asyncio.CancelledError:
            job["status"] = "stopped"
            raise
        except Exception as exc:
            job["status"] = "error"
            job["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            job["finished_at"] = time.time()

    async def _play_one(self, job: dict, index: int) -> None:
        started = time.time()
        engine_cls = job["engine_cls"]
        providers = job["providers"]
        seats: list[Seat] = []
        clients: dict[str, AIClient] = {}
        for i in range(job["seat_count"]):
            row = providers[i % len(providers)]
            seat = Seat(
                id=f"s{i + 1}",
                name=f"{row['name']}-{i + 1}",
                provider_id=row["id"],
                persona="",
                provider_name=row["name"],
                model=row["model"],
            )
            seats.append(seat)
            cfg = config_from_row(row)
            if cfg.kind == "mock":
                # 训练场追求速度：Mock 默认几乎不等待。
                cfg.extra = {**(cfg.extra or {}), "mock_delay": 0.01}
            clients[seat.id] = AIClient(cfg)

        config = dict(job["config"])
        config["rng_seed"] = int(job["seed"] + index)
        runner = GameRunner(
            match_id=f"train-{job['id']}-{index}",
            game_id=job["game_id"],
            seats=seats,
            clients=clients,
            store=self.store,
            broadcast=None,
            config=config,
            voice={"enabled": False},
            rag=job["rag"],
            persist=False,
            log_calls=False,
        )
        winner = "异常"
        rounds = 0
        try:
            await asyncio.wait_for(runner.run(), timeout=job["timeout"])
            result = runner.engine.result or {}
            winner = str(result.get("winner") or "无结果")
            rounds = int(getattr(runner.engine, "round", 0) or 0)
            if not runner.engine.finished:
                winner = "未完成"
        except asyncio.TimeoutError:
            winner = "超时"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            winner = "异常"
            runner.error = f"{type(exc).__name__}: {exc}"
        finally:
            async with job["_lock"]:
                job["done"] += 1
                if winner in {"异常", "超时", "未完成"}:
                    job["failed"] += 1
                job["winners"][winner] = job["winners"].get(winner, 0) + 1
                job["rounds"] += rounds
                job["elapsed"] += time.time() - started
                job["recent"].insert(
                    0,
                    {
                        "index": index + 1,
                        "winner": winner,
                        "rounds": rounds,
                        "seconds": round(time.time() - started, 2),
                        "error": runner.error if winner in {"异常", "超时"} else "",
                    },
                )
                del job["recent"][20:]
