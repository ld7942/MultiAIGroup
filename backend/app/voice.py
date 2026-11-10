"""语音朗读配置与通用 TTS 适配层。

设计目标：
- 默认关闭：未启用时编排器完全不产生语音事件，行为与之前完全一致；
- ``browser``：只下发文本与 voice_id，由前端 Web Speech API 朗读，零成本、便于测试；
- ``voicestudio``：按配置调用自定义 HTTP 接口，支持返回音频 URL 或 base64 / 二进制音频，
  调用失败时自动退回 ``browser``，不影响对局推进。

配置保存在 SQLite 的 ``settings`` 表（key = ``voice``），每个座位还可以用 ``voice_id``
覆盖 Provider 的默认音色，实现“一人一音色”。
"""
from __future__ import annotations

import asyncio
import base64
import os
import sys
import tempfile

import httpx

DEFAULT_VOICE: dict = {
    "enabled": False,
    "provider": "browser",
    "default_voice_id": "",
    "narrator_voice_id": "",
    "speed": 1.0,
    "wait_ms": 15000,
    "voicestudio": {
        "url": "",
        "api_key": "",
        "headers": {},
        "text_field": "text",
        "voice_field": "voice_id",
        "extra_body": {},
        "audio_field": "audio",
        "audio_url_field": "audio_url",
        "timeout_ms": 20000,
    },
}


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_voice(store) -> dict:
    saved = store.get_setting("voice", {}) or {}
    return _deep_merge(DEFAULT_VOICE, saved if isinstance(saved, dict) else {})


def save_voice(store, data: dict) -> dict:
    merged = _deep_merge(load_voice(store), data or {})
    store.set_setting("voice", merged)
    return merged


def _audio_data_uri(data: bytes, ctype: str) -> str:
    mime = (ctype or "").split(";")[0].strip() or "audio/mpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


async def synthesize_voicestudio(cfg: dict, text: str, voice_id: str = "") -> dict | None:
    """调用 VoiceStudio（或任意兼容 HTTP TTS）。

    返回 ``{"audio": data_uri}`` / ``{"audio_url": url}``；未配置或失败返回 None，
    由前端退回浏览器本地朗读。
    """
    vs = cfg.get("voicestudio") or {}
    url = str(vs.get("url") or "").strip()
    if not url or not text:
        return None
    body = dict(vs.get("extra_body") or {})
    body[str(vs.get("text_field") or "text")] = text
    if voice_id:
        body[str(vs.get("voice_field") or "voice_id")] = voice_id
    headers: dict[str, str] = {"Content-Type": "application/json"}
    for key, value in (vs.get("headers") or {}).items():
        headers[str(key)] = str(value)
    if vs.get("api_key"):
        headers["Authorization"] = f"Bearer {vs['api_key']}"
    try:
        timeout = max(1.0, float(vs.get("timeout_ms") or 20000) / 1000)
    except (TypeError, ValueError):
        timeout = 20.0
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            return None
        ctype = resp.headers.get("content-type", "")
        if ctype.startswith("audio/") or ctype == "application/octet-stream":
            return {"audio": _audio_data_uri(resp.content, ctype)}
        data = resp.json()
        if not isinstance(data, dict):
            return None
        audio = data.get(str(vs.get("audio_field") or "audio"))
        if isinstance(audio, str) and audio:
            if audio.startswith(("data:", "http://", "https://")):
                return {"audio": audio}
            try:
                return {"audio": _audio_data_uri(base64.b64decode(audio), "audio/mpeg")}
            except Exception:
                return None
        remote = data.get(str(vs.get("audio_url_field") or "audio_url"))
        if isinstance(remote, str) and remote:
            return {"audio_url": remote}
    except Exception:
        return None
    return None


# ---------------- Windows 系统语音（SAPI） ----------------
# 桌面包用的是 WebView2，部分机器上 Web Speech API 拿不到任何音色，speak() 会静默失败。
# 后端和桌面端在同一台机器上，因此可以直接用 Windows 自带的 SAPI 朗读，作为最可靠的兜底。

_CREATE_NO_WINDOW = 0x08000000


def _ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def _system_available() -> bool:
    return sys.platform == "win32"


async def _run_powershell(script: str, timeout: float = 20.0) -> tuple[int, str, str]:
    kwargs = {}
    if _system_available():
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    proc = await asyncio.create_subprocess_exec(
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **kwargs,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", "timeout"
    return proc.returncode or 0, out.decode("utf-8", "ignore"), err.decode("utf-8", "ignore")


async def system_voices() -> list[str]:
    """列出 Windows SAPI 已安装音色；非 Windows 或失败时返回空列表。"""
    if not _system_available():
        return []
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name };"
        "$s.Dispose()"
    )
    try:
        code, out, _ = await _run_powershell(script, timeout=8)
    except Exception:
        return []
    if code != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


async def speak_system(cfg: dict, text: str, voice_id: str = "") -> bool:
    """用 Windows SAPI 在本机直接朗读，成功后不需要前端回执。"""
    if not text.strip() or not _system_available():
        return False
    try:
        speed = float(cfg.get("speed") or 1.0)
    except (TypeError, ValueError):
        speed = 1.0
    rate = max(-10, min(10, round((speed - 1.0) * 5)))
    handle, path = tempfile.mkstemp(prefix="multi-ai-tts-", suffix=".txt")
    os.close(handle)
    try:
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(text)
        select = ""
        if voice_id:
            select = (
                f"$v=$s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Name -like "
                f"{_ps_quote('*' + voice_id + '*')} }} | Select-Object -First 1;"
                "if($v){$s.SelectVoice($v.VoiceInfo.Name)};"
            )
        script = (
            "$ErrorActionPreference='Stop';"
            "Add-Type -AssemblyName System.Speech;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            f"$s.Rate={rate};"
            + select
            + f"$t=Get-Content -LiteralPath {_ps_quote(path)} -Raw -Encoding UTF8;"
            "if($t){$s.Speak($t)};"
            "$s.Dispose()"
        )
        code, _, _ = await _run_powershell(script, timeout=max(20.0, len(text) * 0.6))
        return code == 0
    except Exception:
        return False
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


async def voice_diagnostics(cfg: dict) -> dict:
    """返回服务端语音能力，便于前端排查“为什么没有声音”。"""
    voices = await system_voices()
    return {
        "platform": sys.platform,
        "provider": cfg.get("provider") or "browser",
        "enabled": bool(cfg.get("enabled")),
        "system_tts": {
            "available": bool(voices),
            "voices": voices[:20],
            "reason": "" if voices else ("非 Windows 系统" if not _system_available() else "未检测到 SAPI 音色"),
        },
        "voicestudio_configured": bool((cfg.get("voicestudio") or {}).get("url")),
    }
