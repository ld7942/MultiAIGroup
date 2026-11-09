from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .paths import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS providers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  base_url TEXT NOT NULL,
  model TEXT NOT NULL,
  api_key TEXT NOT NULL DEFAULT '',
  temperature REAL NOT NULL DEFAULT 0.8,
  max_tokens INTEGER NOT NULL DEFAULT 1200,
  extra TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS groups (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  members TEXT NOT NULL DEFAULT '[]',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
  id TEXT PRIMARY KEY,
  game_id TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  config TEXT NOT NULL DEFAULT '{}',
  seats TEXT NOT NULL DEFAULT '[]',
  privates TEXT NOT NULL DEFAULT '{}',
  state TEXT NOT NULL DEFAULT '{}',
  result TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  started_at REAL,
  finished_at REAL
);
CREATE TABLE IF NOT EXISTS events (
  match_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  ts REAL NOT NULL,
  type TEXT NOT NULL,
  text TEXT NOT NULL DEFAULT '',
  visibility TEXT NOT NULL DEFAULT '{}',
  actor TEXT,
  round INTEGER NOT NULL DEFAULT 0,
  phase TEXT NOT NULL DEFAULT '',
  payload TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (match_id, seq)
);
CREATE TABLE IF NOT EXISTS agent_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id TEXT NOT NULL,
  seat_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  attempt INTEGER NOT NULL DEFAULT 1,
  provider TEXT NOT NULL DEFAULT '',
  system_prompt TEXT NOT NULL DEFAULT '',
  user_prompt TEXT NOT NULL DEFAULT '',
  raw_response TEXT NOT NULL DEFAULT '',
  parsed TEXT NOT NULL DEFAULT '{}',
  error TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_match ON agent_logs(match_id, seat_id);
"""


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return default


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or db_path()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        self._seed()

    def _seed(self) -> None:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) c FROM providers").fetchone()
            if row["c"] == 0:
                self.upsert_provider(
                    {
                        "name": "本地模拟 AI",
                        "kind": "mock",
                        "base_url": "",
                        "model": "mock-1",
                        "api_key": "",
                        "temperature": 0.9,
                        "max_tokens": 800,
                    }
                )
            self._conn.execute(
                "UPDATE matches SET status='interrupted' WHERE status IN ('running','paused')"
            )
            self._conn.commit()

    # ---------------- providers ----------------
    def list_providers(self, include_key: bool = False) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM providers ORDER BY created_at").fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["extra"] = _loads(item.get("extra", "{}"), {})
            item["has_key"] = bool(item.get("api_key"))
            if not include_key:
                item["api_key"] = ""
            out.append(item)
        return out

    def get_provider(self, provider_id: str, include_key: bool = True) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM providers WHERE id=?", (provider_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["extra"] = _loads(item.get("extra", "{}"), {})
        item["has_key"] = bool(item.get("api_key"))
        if not include_key:
            item["api_key"] = ""
        return item

    def upsert_provider(self, data: dict, provider_id: str | None = None) -> dict:
        provider_id = provider_id or data.get("id") or uuid.uuid4().hex[:12]
        existing = self.get_provider(provider_id, include_key=True)
        api_key = data.get("api_key")
        if existing and api_key is None:
            api_key = existing.get("api_key", "")
        payload = {
            "id": provider_id,
            "name": (data.get("name") or existing and existing.get("name") or "未命名 AI").strip(),
            "kind": data.get("kind") or (existing.get("kind") if existing else "openai"),
            "base_url": (data.get("base_url") if data.get("base_url") is not None else (existing or {}).get("base_url", "")).strip(),
            "model": (data.get("model") if data.get("model") is not None else (existing or {}).get("model", "")).strip(),
            "api_key": api_key if api_key is not None else "",
            "temperature": float(data.get("temperature", (existing or {}).get("temperature", 0.8))),
            "max_tokens": int(data.get("max_tokens", (existing or {}).get("max_tokens", 1200))),
            "extra": _j(data.get("extra", (existing or {}).get("extra", {}))),
        }
        with self._lock:
            if existing:
                self._conn.execute(
                    """UPDATE providers SET name=?,kind=?,base_url=?,model=?,api_key=?,
                       temperature=?,max_tokens=?,extra=? WHERE id=?""",
                    (
                        payload["name"], payload["kind"], payload["base_url"], payload["model"],
                        payload["api_key"], payload["temperature"], payload["max_tokens"],
                        payload["extra"], provider_id,
                    ),
                )
            else:
                self._conn.execute(
                    """INSERT INTO providers(id,name,kind,base_url,model,api_key,temperature,max_tokens,extra,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        provider_id, payload["name"], payload["kind"], payload["base_url"],
                        payload["model"], payload["api_key"], payload["temperature"],
                        payload["max_tokens"], payload["extra"], time.time(),
                    ),
                )
            self._conn.commit()
        return self.get_provider(provider_id, include_key=False) or {}

    def delete_provider(self, provider_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM providers WHERE id=?", (provider_id,))
            self._conn.commit()

    # ---------------- groups ----------------
    def list_groups(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM groups ORDER BY created_at DESC").fetchall()
        return [dict(r, members=_loads(r["members"], [])) for r in rows]

    def upsert_group(self, data: dict, group_id: str | None = None) -> dict:
        group_id = group_id or data.get("id") or uuid.uuid4().hex[:12]
        name = (data.get("name") or "我的 AI 群组").strip()
        members = data.get("members") or []
        with self._lock:
            exists = self._conn.execute("SELECT id FROM groups WHERE id=?", (group_id,)).fetchone()
            if exists:
                self._conn.execute(
                    "UPDATE groups SET name=?, members=? WHERE id=?", (name, _j(members), group_id)
                )
            else:
                self._conn.execute(
                    "INSERT INTO groups(id,name,members,created_at) VALUES(?,?,?,?)",
                    (group_id, name, _j(members), time.time()),
                )
            self._conn.commit()
        return {"id": group_id, "name": name, "members": members}

    def delete_group(self, group_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM groups WHERE id=?", (group_id,))
            self._conn.commit()

    # ---------------- matches ----------------
    def create_match(self, data: dict) -> dict:
        match_id = data.get("id") or uuid.uuid4().hex[:12]
        now = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO matches(id,game_id,title,status,config,seats,privates,state,result,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    match_id,
                    data["game_id"],
                    data.get("title") or "未命名对局",
                    "created",
                    _j(data.get("config", {})),
                    _j(data.get("seats", [])),
                    _j({}),
                    _j({}),
                    _j({}),
                    now,
                ),
            )
            self._conn.commit()
        return self.get_match(match_id) or {}

    def update_match(self, match_id: str, **fields: Any) -> None:
        allowed = {"title", "status", "config", "seats", "privates", "state", "result", "started_at", "finished_at"}
        pairs = []
        values = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            pairs.append(f"{key}=?")
            values.append(_j(value) if key in {"config", "seats", "privates", "state", "result"} else value)
        if not pairs:
            return
        values.append(match_id)
        with self._lock:
            self._conn.execute(f"UPDATE matches SET {','.join(pairs)} WHERE id=?", values)
            self._conn.commit()

    def list_matches(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM matches ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._match_row(r) for r in rows]

    def get_match(self, match_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        return self._match_row(row) if row else None

    def delete_match(self, match_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM events WHERE match_id=?", (match_id,))
            self._conn.execute("DELETE FROM agent_logs WHERE match_id=?", (match_id,))
            self._conn.execute("DELETE FROM matches WHERE id=?", (match_id,))
            self._conn.commit()

    def _match_row(self, row: sqlite3.Row) -> dict:
        item = dict(row)
        for key in ("config", "seats", "privates", "state", "result"):
            item[key] = _loads(item.get(key, "{}" if key != "seats" else "[]"), {} if key != "seats" else [])
        return item

    def append_events(self, match_id: str, events: list[dict]) -> None:
        if not events:
            return
        with self._lock:
            self._conn.executemany(
                """INSERT OR REPLACE INTO events(match_id,seq,ts,type,text,visibility,actor,round,phase,payload)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        match_id, ev["seq"], ev["ts"], ev["type"], ev.get("text", ""),
                        _j(ev.get("visibility", {})), ev.get("seat_id"), ev.get("round", 0),
                        ev.get("phase", ""), _j(ev.get("payload", {})),
                    )
                    for ev in events
                ],
            )
            self._conn.commit()

    def get_events(self, match_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE match_id=? ORDER BY seq", (match_id,)
            ).fetchall()
        return [
            {
                "seq": r["seq"], "ts": r["ts"], "type": r["type"], "text": r["text"],
                "visibility": _loads(r["visibility"], {}), "seat_id": r["actor"],
                "round": r["round"], "phase": r["phase"], "payload": _loads(r["payload"], {}),
            }
            for r in rows
        ]

    # ---------------- agent logs ----------------
    def add_log(
        self,
        match_id: str,
        seat_id: str,
        request_id: str,
        attempt: int,
        provider: str,
        system_prompt: str,
        user_prompt: str,
        raw_response: str,
        parsed: dict,
        error: str,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO agent_logs(match_id,seat_id,request_id,attempt,provider,system_prompt,
                   user_prompt,raw_response,parsed,error,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    match_id, seat_id, request_id, attempt, provider, system_prompt, user_prompt,
                    raw_response, _j(parsed), error, time.time(),
                ),
            )
            self._conn.commit()

    def get_logs(self, match_id: str, seat_id: str | None = None, limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM agent_logs WHERE match_id=?"
        args: list[Any] = [match_id]
        if seat_id:
            sql += " AND seat_id=?"
            args.append(seat_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [dict(r, parsed=_loads(r["parsed"], {})) for r in rows]
