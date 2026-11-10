"""游戏插件注册表。

插件约定：本目录下的每个模块（或包）导出模块级变量 ``ENGINE``，
值为 :class:`app.engine.GameEngine` 的子类。服务启动时自动扫描本目录并注册，
``game_id`` 必须唯一。

新增游戏只需在本目录放入一个插件模块，无需修改本文件或其它代码：

    ENGINE = MyGameEngine

复杂插件可以做成子包，只要在包的 ``__init__.py`` 中导出 ``ENGINE`` 即可。
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
import random
from dataclasses import dataclass

from ..engine import GameEngine, Seat

logger = logging.getLogger(__name__)

PLUGIN_ATTR = "ENGINE"


@dataclass(frozen=True)
class GamePlugin:
    """一个已加载的游戏插件。"""

    module: str
    engine_cls: type[GameEngine]

    @property
    def game_id(self) -> str:
        return self.engine_cls.game_id

    def info(self) -> dict:
        engine = self.engine_cls
        return {
            "id": engine.game_id,
            "name": engine.name,
            "description": engine.description,
            "min_players": engine.min_players,
            "max_players": engine.max_players,
            "allowed_counts": list(engine.allowed_counts),
            "presets": engine.presets,
            "rules": engine.rules,
            "capabilities": dict(engine.capabilities),
        }


def _discover() -> tuple[dict[str, GamePlugin], dict[str, str]]:
    plugins: dict[str, GamePlugin] = {}
    errors: dict[str, str] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        module_name = f"{__name__}.{info.name}"
        try:
            module = importlib.import_module(module_name)
            engine_cls = getattr(module, PLUGIN_ATTR, None)
            if engine_cls is None:
                continue  # 非插件模块（工具、常量等），忽略
            if not (isinstance(engine_cls, type) and issubclass(engine_cls, GameEngine)):
                raise TypeError(f"{PLUGIN_ATTR} 必须是 GameEngine 的子类")
            game_id = (engine_cls.game_id or "").strip()
            if not game_id:
                raise ValueError("插件缺少 game_id")
            if game_id in plugins:
                raise ValueError(f"game_id {game_id!r} 已被 {plugins[game_id].module} 占用")
        except Exception as exc:  # 单个插件失败不影响其它插件
            message = f"{type(exc).__name__}: {exc}"
            errors[info.name] = message
            logger.warning("游戏插件 %s 加载失败：%s", module_name, message)
            continue
        plugins[game_id] = GamePlugin(module_name, engine_cls)
    return plugins, errors


PLUGINS, PLUGIN_ERRORS = _discover()
ENGINES: dict[str, type[GameEngine]] = {game_id: p.engine_cls for game_id, p in PLUGINS.items()}


def list_plugins() -> list[GamePlugin]:
    return list(PLUGINS.values())


def get_plugin(game_id: str) -> GamePlugin | None:
    return PLUGINS.get(game_id)


def get_engine_class(game_id: str) -> type[GameEngine] | None:
    return ENGINES.get(game_id)


def list_games() -> list[dict]:
    return [plugin.info() for plugin in PLUGINS.values()]


def create_engine(
    game_id: str,
    seats: list[Seat],
    config: dict | None = None,
    rng: random.Random | None = None,
) -> GameEngine:
    plugin = PLUGINS.get(game_id)
    if plugin is None:
        raise ValueError(f"未知游戏 {game_id}，可选：{', '.join(PLUGINS) or '（无）'}")
    return plugin.engine_cls(seats, config, rng)
