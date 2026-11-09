"""AI Provider 适配层：统一 chat(messages) -> text 接口。

支持：
- OpenAI 兼容（OpenAI / DeepSeek / Kimi / 通义 / 智谱 / OpenRouter / Ollama / vLLM …）
- Anthropic Messages
- Google Gemini
- Mock（本地模拟，无需 Key，用于演示与测试）
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import dataclass, field
from typing import Any

import httpx


class ProviderError(Exception):
    pass


PRESETS: list[dict] = [
    {"id": "deepseek", "name": "DeepSeek", "kind": "openai", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    {"id": "openai", "name": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    {"id": "moonshot", "name": "Kimi / Moonshot", "kind": "openai", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    {"id": "qwen", "name": "通义千问", "kind": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    {"id": "zhipu", "name": "智谱 GLM", "kind": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash"},
    {"id": "openrouter", "name": "OpenRouter", "kind": "openai", "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4o-mini"},
    {"id": "ollama", "name": "Ollama 本地", "kind": "openai", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b"},
    {"id": "anthropic", "name": "Anthropic Claude", "kind": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-3-5-sonnet-latest"},
    {"id": "gemini", "name": "Google Gemini", "kind": "gemini", "base_url": "https://generativelanguage.googleapis.com", "model": "gemini-2.0-flash"},
]


@dataclass
class ProviderConfig:
    id: str
    name: str
    kind: str
    base_url: str
    model: str
    api_key: str = ""
    temperature: float = 0.8
    max_tokens: int = 1200
    extra: dict = field(default_factory=dict)


def config_from_row(row: dict) -> ProviderConfig:
    return ProviderConfig(
        id=row.get("id", ""),
        name=row.get("name", ""),
        kind=row.get("kind", "openai"),
        base_url=row.get("base_url", ""),
        model=row.get("model", ""),
        api_key=row.get("api_key", ""),
        temperature=float(row.get("temperature", 0.8)),
        max_tokens=int(row.get("max_tokens", 1200)),
        extra=row.get("extra") or {},
    )


class AIClient:
    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg

    @property
    def label(self) -> str:
        return f"{self.cfg.name} / {self.cfg.model}"

    async def chat(
        self,
        messages: list[dict],
        *,
        json_mode: bool = True,
        meta: dict | None = None,
        timeout: float = 120.0,
    ) -> str:
        if self.cfg.kind == "mock":
            return await self._mock(messages, meta or {})
        if not self.cfg.api_key.strip() and "localhost" not in self.cfg.base_url and "127.0.0.1" not in self.cfg.base_url:
            raise ProviderError(f"{self.cfg.name} 未配置 API Key")
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                if self.cfg.kind == "anthropic":
                    return await self._anthropic(messages, json_mode, timeout)
                if self.cfg.kind == "gemini":
                    return await self._gemini(messages, json_mode, timeout)
                return await self._openai(messages, json_mode, timeout)
            except ProviderError as exc:
                last_error = exc
                msg = str(exc)
                retryable = any(x in msg for x in ("429", "500", "502", "503", "504", "timeout", "超时"))
                if attempt == 0 and retryable:
                    await asyncio.sleep(1.2)
                    continue
                raise
            except httpx.HTTPError as exc:
                last_error = ProviderError(f"网络错误：{exc}")
                if attempt == 0:
                    await asyncio.sleep(1.0)
                    continue
                raise last_error from exc
        raise last_error or ProviderError("未知错误")

    # ---------------- OpenAI 兼容 ----------------
    async def _openai(self, messages: list[dict], json_mode: bool, timeout: float) -> str:
        base = (self.cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        if base.endswith("/chat/completions"):
            url = base
        elif base.endswith("/v1") or re.search(r"/v\d+$", base):
            url = base + "/chat/completions"
        else:
            url = base + "/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        extra_headers = self.cfg.extra.get("headers") if isinstance(self.cfg.extra, dict) else None
        if isinstance(extra_headers, dict):
            headers.update({str(k): str(v) for k, v in extra_headers.items()})
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        extra_body = self.cfg.extra.get("body") if isinstance(self.cfg.extra, dict) else None
        if isinstance(extra_body, dict):
            payload.update(extra_body)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 400 and json_mode and "response_format" in payload:
                payload.pop("response_format", None)
                resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:400]}")
            data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"响应格式异常：{str(data)[:400]}") from exc
        if isinstance(content, list):
            content = "".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        return str(content or "")

    # ---------------- Anthropic ----------------
    async def _anthropic(self, messages: list[dict], json_mode: bool, timeout: float) -> str:
        base = (self.cfg.base_url or "https://api.anthropic.com").rstrip("/")
        url = base + "/v1/messages" if not base.endswith("/v1/messages") else base
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        convo = [
            {"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]}
            for m in messages
            if m.get("role") in {"user", "assistant"}
        ]
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "max_tokens": self.cfg.max_tokens,
            "temperature": self.cfg.temperature,
            "system": "\n\n".join(system_parts),
            "messages": convo,
        }
        headers = {
            "x-api-key": self.cfg.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:400]}")
            data = resp.json()
        parts = data.get("content") or []
        return "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict) and p.get("type") == "text")

    # ---------------- Gemini ----------------
    async def _gemini(self, messages: list[dict], json_mode: bool, timeout: float) -> str:
        base = (self.cfg.base_url or "https://generativelanguage.googleapis.com").rstrip("/")
        url = f"{base}/v1beta/models/{self.cfg.model}:generateContent"
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        contents = []
        for m in messages:
            if m.get("role") in {"user", "assistant"}:
                contents.append(
                    {
                        "role": "user" if m["role"] == "user" else "model",
                        "parts": [{"text": m["content"]}],
                    }
                )
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.cfg.temperature,
                "maxOutputTokens": self.cfg.max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.cfg.api_key}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:400]}")
            data = resp.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"响应格式异常：{str(data)[:400]}") from exc
        return "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))

    # ---------------- Mock ----------------
    async def _mock(self, messages: list[dict], meta: dict) -> str:
        rng = random.Random()
        delay = self.cfg.extra.get("mock_delay") if isinstance(self.cfg.extra, dict) else None
        await asyncio.sleep(float(delay) if delay is not None else rng.uniform(0.25, 0.9))
        options = meta.get("options") or []
        speech_hints = meta.get("speech_hints") or []
        chosen = rng.choice(options) if options else None
        action = dict(chosen.get("action", {})) if chosen else {}
        speech = ""
        if speech_hints:
            speech = rng.choice(speech_hints)
        elif chosen:
            speech = rng.choice(
                [
                    f"我选择：{chosen.get('label', '这一项')}。",
                    f"按我的判断，先走「{chosen.get('label', '这一步')}」。",
                    f"我想了想，还是{chosen.get('label', '这样')}。",
                ]
            )
        notes = f"（模拟AI）本回合选择：{chosen.get('label') if chosen else '保持观望'}。"
        payload = {
            "speech": speech,
            "action": action,
            "notes": notes,
            "reads": [],
        }
        return json.dumps(payload, ensure_ascii=False)


# ---------------- JSON 解析 ----------------
def extract_json(text: str) -> dict:
    if not text or not text.strip():
        raise ValueError("模型返回为空")
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    candidates = [cleaned]
    start = cleaned.find("{")
    if start >= 0:
        depth = 0
        in_str = False
        escape = False
        for idx in range(start, len(cleaned)):
            ch = cleaned[idx]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(cleaned[start : idx + 1])
                    break
    for candidate in candidates:
        for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
            try:
                data = json.loads(attempt)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
    raise ValueError("无法从模型输出中解析 JSON")


def normalize_envelope(data: dict) -> dict:
    """兼容模型把 action 字段平铺在顶层的情况。"""
    if not isinstance(data, dict):
        raise ValueError("输出必须是 JSON 对象")
    speech = data.get("speech")
    notes = data.get("notes")
    reads = data.get("reads")
    if isinstance(data.get("action"), dict):
        action = dict(data["action"])
    else:
        reserved = {"speech", "notes", "reads", "thought", "reasoning"}
        action = {k: v for k, v in data.items() if k not in reserved}
    if speech is not None and "speech" not in action:
        action["speech"] = speech
    if not isinstance(action, dict):
        raise ValueError("action 必须是 JSON 对象")
    return {
        "speech": str(speech) if speech is not None else "",
        "action": action,
        "notes": str(notes) if notes is not None else "",
        "reads": reads if isinstance(reads, list) else [],
    }
