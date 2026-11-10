"""轻量 RAG 记忆库：内置哈希向量 + 余弦检索，零外部依赖。

设计：
- 记忆分为 `skill`（内置玩法技能卡）、`lesson`（对局结束复盘出的技巧）、`manual`（手动录入）；
- 每条记忆带 game_id / role / faction，检索时先按角色与阵营过滤，再按语义相似度排序；
- 向量使用字符 1-2 gram 的 hashing trick，落库为 JSON 数组，几百到几千条记忆的检索开销可以忽略；
- 后续如果想换真实 embedding（bge / text-embedding-3 等），只需替换 `embed()`，其余接口不变。

上下文压缩：
- `compress_events()` 保留开头与最近事件，把中间大量重复事件压成统计摘要和关键节点，
  降低长对局提示词体积；同一份摘要也用于对局结束后的“复盘压缩”。
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

DIM = 256

DEFAULT_RAG: dict = {
    "enabled": True,
    "top_k": 4,
    "min_score": 0.06,
    "reflect": True,
    "llm_reflect": True,
    "max_memories": 800,
}

# 通用策略：不绑定具体游戏，所有角色都能检索到。
GENERAL_SKILLS: list[dict] = [
    {
        "role": "通用",
        "faction": "",
        "text": "先更新身份概率再行动：把每个玩家写成「身份 + 置信度 + 依据」，置信度要随新信息变化，不要凭感觉。",
    },
    {
        "role": "通用",
        "faction": "",
        "text": "行动前做安全自检：目标是否合法、是否会误伤自己或队友、是否会暴露关键身份、是否违反角色禁忌。",
    },
    {
        "role": "通用",
        "faction": "",
        "text": "把姿态分成 support / attack / neutral：需要隐藏时顺势，需要带队时进攻，信息不足时观察，不要每轮都用同一种语气。",
    },
    {
        "role": "通用",
        "faction": "",
        "text": "发言要给出可验证的信息：点名怀疑对象、引用具体事件或票型、说明投票意向；空泛表态会被当成狼或划水。",
    },
]

WEREWOLF_LESSONS: dict[str, str] = {
    "狼人": "狼人失败常见原因：夜间目标分散、白天不敢带队、发言与队友互相踩。下次先统一刀目标，再安排一人主攻、一人附和。",
    "预言家": "预言家失败常见原因：验人没有转化成分票、报验太晚。下次有查杀就当轮带队，明确归票并解释验人逻辑。",
    "女巫": "女巫失败常见原因：毒药凭感觉用、解药救错人。下次毒药只在置信度高时使用，解药优先关键神职。",
    "猎人": "猎人失败常见原因：过早暴露身份、开枪带走好人。下次隐藏到中后期，开枪前确认目标狼概率。",
    "村民": "村民失败常见原因：发言空泛、跟风冲票。下次至少给出两个具体怀疑点和一条可验证依据。",
}

CARD_LESSONS: dict[str, str] = {
    "地主": "地主失败常见原因：过早拆牌、关键回合没有留大牌。下次保留 2/王/炸弹，农民手牌少时优先拦截。",
    "农民": "农民失败常见原因：压队友、没有拦截残血地主。下次队友出牌优先过牌，地主手牌少时果断拦截。",
    "叫地主": "叫地主失败常见原因：手牌散还抢高分。下次只有王、2、炸弹或长顺子齐全时才叫高分。",
    "主公": "主公失败常见原因：盲目集火、残血不回复。下次优先保命，攻击明确跳反的目标。",
    "忠臣": "忠臣失败常见原因：误伤主公、没有替主公挡刀。下次优先攻击反贼，主公残血时主动吸引火力。",
    "反贼": "反贼失败常见原因：输出分散、暴露过早。下次集火主公，身份未明时适当装忠。",
    "内奸": "内奸失败常见原因：过早跳反或让一方过快崩盘。下次前期帮主公清反贼，后期控制双方血线。",
}

KEY_EVENT_TYPES = {
    "death", "vote_result", "night_result", "game_over", "landlord",
    "hunter_shot", "damage", "dying", "new_trick", "wolf_choice",
}


# ---------------- 配置 ----------------
def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_rag(store) -> dict:
    saved = store.get_setting("rag", {}) or {}
    return _deep_merge(DEFAULT_RAG, saved if isinstance(saved, dict) else {})


def save_rag(store, data: dict) -> dict:
    merged = _deep_merge(load_rag(store), data or {})
    store.set_setting("rag", merged)
    return merged


# ---------------- 向量 ----------------
def _tokens(text: str) -> list[str]:
    text = (text or "").lower()
    words = re.findall(r"[a-z0-9_]+", text)
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    grams = [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
    return words + chars + grams


def embed(text: str) -> list[float]:
    vector = [0.0] * DIM
    counts = Counter(_tokens(text))
    if not counts:
        return vector
    for token, count in counts.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % DIM
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign * (1.0 + math.log1p(count))
    norm = math.sqrt(sum(v * v for v in vector))
    if norm:
        vector = [v / norm for v in vector]
    return vector


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


# ---------------- 记忆 CRUD ----------------
def _memory_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(p) for p in parts)
    return f"{prefix}:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def add_memory(
    store,
    text: str,
    *,
    game_id: str = "",
    role: str = "",
    faction: str = "",
    kind: str = "manual",
    source: str = "",
    match_id: str = "",
    unique: bool = True,
) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    mid = _memory_id(kind, game_id, role, faction, text) if unique else ""
    return store.add_memory(
        {
            "id": mid,
            "game_id": game_id,
            "role": role,
            "faction": faction,
            "kind": kind,
            "text": text,
            "embedding": embed(text),
            "source": source,
            "match_id": match_id,
        }
    )


def add_lesson(
    store,
    game_id: str,
    role: str,
    faction: str,
    match_id: str,
    text: str,
    source: str = "reflect",
) -> dict:
    return add_memory(
        store,
        text,
        game_id=game_id,
        role=role,
        faction=faction,
        kind="lesson",
        source=source,
        match_id=match_id,
    )


def seed_skills(store) -> int:
    """把每个游戏插件的角色技能卡与通用策略写入记忆库（幂等）。"""
    from .plugins import list_plugins

    added = 0
    for item in GENERAL_SKILLS:
        add_memory(
            store,
            item["text"],
            game_id="",
            role=item["role"],
            faction=item["faction"],
            kind="skill",
            source="builtin",
        )
        added += 1
    for plugin in list_plugins():
        try:
            cards = plugin.engine_cls.skill_cards()
        except Exception:
            cards = []
        for card in cards:
            add_memory(
                store,
                card.get("text", ""),
                game_id=plugin.game_id,
                role=card.get("role", ""),
                faction=card.get("faction", ""),
                kind="skill",
                source="builtin",
            )
            added += 1
    return added


def search(
    store,
    query: str,
    *,
    game_id: str = "",
    role: str = "",
    faction: str = "",
    top_k: int = 4,
    min_score: float = 0.06,
) -> list[dict]:
    """按角色/阵营过滤后做向量检索。空角色/阵营表示通用记忆。"""
    if not (query or "").strip():
        return []
    candidates = store.list_memories(game_id=game_id or None, limit=1000)
    query_vec = embed(query)
    scored: list[dict] = []
    for item in candidates:
        item_role = str(item.get("role") or "").strip()
        item_faction = str(item.get("faction") or "").strip()
        if item_role and item_role not in {"通用", role}:
            continue
        if item_faction and item_faction not in {faction}:
            continue
        score = cosine(query_vec, item.get("embedding") or [])
        if score >= min_score:
            scored.append({**item, "score": round(score, 4)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[: max(1, top_k)]


# ---------------- 上下文压缩 ----------------
def _line(ev) -> str:
    return f"[R{getattr(ev, 'round', 0)} {getattr(ev, 'phase', '')}] {getattr(ev, 'text', '')}"


def key_moments(events, limit: int = 6) -> list[str]:
    """抽取对局关键节点，用于复盘与压缩摘要。"""
    moments: list[str] = []
    for ev in events:
        if ev.type in KEY_EVENT_TYPES:
            text = (ev.text or "").strip()
            if text:
                moments.append(text)
    return moments[-limit:]


def compress_events(events, head: int = 8, tail: int = 60) -> str:
    """把长事件流压缩成「早期摘要 + 关键节点 + 最近事件」。

    事件量不大时保持原文，避免影响短对局。
    """
    total = len(events)
    if total <= head + tail:
        return "\n".join(_line(ev) for ev in events)

    head_part = events[:head]
    middle = events[head : total - tail]
    tail_part = events[total - tail :]
    counts = Counter(ev.type for ev in middle)
    label = {
        "speech": "发言", "vote": "投票", "play": "出牌", "pass": "过牌",
        "phase": "阶段", "death": "死亡", "draw": "摸牌", "bid": "叫分",
    }
    stat = "、".join(
        f"{label.get(kind, kind)}×{num}" for kind, num in counts.most_common(6)
    )
    moments = key_moments(middle, 8)
    summary = [f"（中间 {len(middle)} 条事件已压缩：{stat or '无'}）"]
    if moments:
        summary.append("关键节点：" + "；".join(moments))
    parts = [_line(ev) for ev in head_part] + summary + [_line(ev) for ev in tail_part]
    return "\n".join(parts)


# ---------------- 复盘 ----------------
def auto_lessons(
    game_id: str,
    role: str,
    faction: str,
    won: bool,
    moments: list[str],
    role_label: str = "",
) -> list[str]:
    """模型复盘失败时的确定性兜底，保证每局都能沉淀经验。"""
    label = role_label or role
    lessons: list[str] = []
    if game_id == "werewolf" and label in WEREWOLF_LESSONS:
        lessons.append(WEREWOLF_LESSONS[label])
    elif game_id == "doudizhu" and label in CARD_LESSONS:
        lessons.append(CARD_LESSONS[label])
    elif game_id == "sanguosha" and label in CARD_LESSONS:
        lessons.append(CARD_LESSONS[label])
    if not lessons and label:
        lessons.append(
            f"作为{label}，本局{'获胜' if won else '落败'}；下次先明确本角色的第一目标，再决定每一步的取舍。"
        )
    if moments:
        lessons.append("本局关键节点：" + "；".join(moments[-3:]))
    if faction:
        lessons.append(f"{faction}的通用要点：保持信息优势，避免在信息不足时做不可逆决策。")
    return lessons
