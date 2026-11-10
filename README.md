# MultiAIGroup · 多 AI 群组对局

让多个大语言模型各自扮演一个玩家，在同一张桌子上打牌、发言、推理。

后端是 FastAPI + SQLite 的游戏编排服务：由游戏引擎驱动状态机，按座位裁剪可见信息后调用各自的 AI Provider，收集动作并广播事件。游戏逻辑以插件形式组织，新增游戏只需往插件目录放入一个模块。前端是 React + TypeScript + Vite，桌面端通过 Tauri 2 打包。

## 已支持的游戏

| 游戏 | game_id | 人数 | 说明 |
| --- | --- | --- | --- |
| 狼人杀 | `werewolf` | 6–12 | 狼人夜间密谈刀人，预言家查验、女巫解药毒药、猎人开枪，白天发言投票 |
| 斗地主 | `doudizhu` | 3 | 叫地主、抢底牌，完整牌型与炸弹 / 王炸判定 |
| 三国杀 | `sanguosha` | 4–5 | 简化身份局：杀、闪、桃、无中生有、过河拆桥、决斗，包含响应与濒死 |

## 功能概览

- **Provider 管理**：统一适配 OpenAI 兼容接口、Anthropic Messages、Google Gemini，以及无需 Key 的本地 Mock。
- **AI 群组**：把若干 Provider + 人设（persona）保存为可复用的座位模板。
- **对局大厅**：选择游戏、人数与座位，创建、启动、停止、删除对局。
- **实时观战**：WebSocket 推送事件、公开状态与每个座位的私有视角。
- **信息隔离**：引擎事件带 `Visibility`（`public` / `private` / `group`），编排器按座位裁剪上下文，AI 只能看到自己该看到的信息。
- **决策留痕**：AI 的发言、内心判断（`notes`）、身份预测（`reads`）、原始返回与重试错误都写入数据库，可在前端查看。
- **游戏插件**：三个内置游戏都是独立插件，启动时自动发现；新增游戏无需改动注册表或前端代码。
- **语音朗读（可选）**：上帝播报、玩家发言与出牌可依次朗读，支持一人一音色；支持浏览器 Web Speech、Windows 系统语音（SAPI）与自定义 HTTP TTS，保存后立即生效。
- **RAG 记忆库**：内置玩法技能卡与每局复盘技巧写入向量库，每步行动按角色/阵营检索后注入提示词；长对局自动压缩上下文。
- **上帝视角公共面板**：右侧展示公共状态、全员身份与各 AI 的身份概率，而不是单个座位的私有视角。
- **随机性格**：每局为每个座位随机分配激进 / 稳健 / 保守 / 诡诈 / 理性 / 直觉性格，结合角色策略卡改变取舍，女巫不再固定救人。
- **训练场（自对弈）**：后台快速跑多局对局，只统计局数、胜率、回合与耗时，不进入牌桌；可读取 RAG 并在每局结束后沉淀技巧。
- **Ollama 联动**：可一键检测本机 Ollama 模型并切换 Provider 模型，适合本地模型长期自对弈。

## 技术栈

- 后端：Python 3.10+、FastAPI、Uvicorn、httpx、Pydantic v2、SQLite
- 前端：React 18、TypeScript 5、Vite 6
- 桌面端：Tauri 2（Rust）

## 环境要求

- 后端与浏览器开发：Python 3.10+、Node.js 18+
- 桌面端额外需要：Rust 工具链（rustup，MSVC 目标）、Visual Studio C++ Build Tools、WebView2 Runtime
- 只跑 `npm run dev` 时不需要 Rust；只有 `npm run tauri dev` / `npm run tauri build` 才需要

## 目录结构

```
.
├── backend/
│   ├── app/
│   │   ├── main.py          # 服务入口：python -m app.main
│   │   ├── api.py           # REST + WebSocket 接口
│   │   ├── runner.py        # 对局编排器：推进引擎、调用 AI、广播与持久化
│   │   ├── engine.py        # 游戏引擎抽象：Seat / GameEvent / ActionRequest / Visibility
│   │   ├── ai.py            # Provider 适配层与 JSON 解析
│   │   ├── store.py         # SQLite 存储
│   │   ├── training.py      # 训练场：后台批量自对弈与统计
│   │   ├── voice.py         # 语音配置、系统 TTS 与 VoiceStudio 调用
│   │   ├── rag.py           # 零依赖向量记忆与上下文压缩
│   │   ├── paths.py         # 数据目录与数据库路径
│   │   └── plugins/         # 游戏插件目录（自动发现）
│   │       ├── __init__.py  # 插件加载器与注册表
│   │       ├── werewolf.py  # 狼人杀
│   │       ├── doudizhu.py  # 斗地主
│   │       └── sanguosha.py # 三国杀
│   ├── tests/               # pytest 引擎测试
│   ├── requirements.txt
│   └── pytest.ini
└── frontend/
    ├── src/
    │   ├── App.tsx          # 侧边栏与视图切换
    │   ├── api.ts           # 后端客户端（API_BASE 默认 http://127.0.0.1:8765）
    │   ├── views/           # 大厅 / Provider / 群组 / 牌桌
    │   └── types.ts
    ├── src-tauri/           # Tauri 2 桌面壳
    ├── package.json
    └── vite.config.ts
```

## 快速开始

### 1. 启动后端

需要 Python 3.10 及以上。

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

如果本机没有可用的 `python` 命令，可以用 uv 创建同样的虚拟环境：

```powershell
cd backend
uv python install 3.14
uv venv --python 3.14 .venv
uv pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.main
```

默认监听 `http://127.0.0.1:8765`，健康检查：`GET /api/health`。

可用环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MULTI_AI_HOST` | `127.0.0.1` | 监听地址 |
| `MULTI_AI_PORT` | `8765` | 监听端口 |
| `MULTI_AI_DATA_DIR` | 系统应用数据目录 | 数据目录，覆盖 SQLite 存放位置 |

### 2. 启动前端（浏览器开发）

```powershell
cd frontend
npm install
npm run dev
```

默认地址 `http://localhost:5173`。若后端不在本机 8765 端口，设置 `VITE_API_BASE`，例如：

```powershell
$env:VITE_API_BASE = "http://192.168.1.10:8765"
npm run dev
```

### 3. 启动桌面端

先确认 Rust 环境可用：

```powershell
npx tauri info
```

`rustc`、`Cargo` 都显示为已安装后再执行：

```powershell
cd frontend
npm run tauri dev
```

打包安装包（Windows NSIS）：

```powershell
npm run tauri build
```

首次编译会在 `frontend/src-tauri/target/` 下生成 Cargo 构建产物。该目录是编译缓存，已被 `.gitignore` 忽略，**不属于 npm 依赖**：删除后 `npm install` 不会也无法恢复它，重新执行 `npm run tauri dev` 或 `npm run tauri build` 即可自动重建。

## 配置 AI Provider

首次启动会自动写入一个「本地模拟 AI」（`kind=mock`），无需 API Key 即可完整跑通一局，适合演示与联调。

在界面「Provider」页新增配置，字段含义：

- `kind`：`openai`（OpenAI 兼容）、`anthropic`、`gemini`、`mock`
- `base_url`：接口根地址。OpenAI 兼容类型可填到 `/v1`，也可直接填完整的 `/chat/completions`
- `model`：模型名
- `api_key`：本地 Ollama / vLLM 等无需 Key 的服务可留空
- `temperature` / `max_tokens`：采样参数
- `voice_id`：可选，该 Provider 所有座位的默认语音音色；座位 / 群组成员可覆盖
- `extra`：可选 JSON，`{"headers": {...}}` 追加请求头，`{"body": {...}}` 追加请求体字段；Mock 可用 `{"mock_delay": 0.5}` 控制延迟

新增后可用「测试连接」验证连通性。

内置预设包括 DeepSeek、OpenAI、Kimi / Moonshot、通义千问、智谱 GLM、OpenRouter、Ollama、Anthropic Claude、Google Gemini。

## 使用流程

1. 在「Provider」页添加至少一个 AI（或直接用内置 Mock）。
2. 在「群组」页把 Provider 与座位人设组合成可复用群组（可选）。
3. 在「对局大厅」选择游戏、人数和座位，创建对局。
4. 启动对局后进入牌桌，实时查看发言、事件流、各座位私有信息与 AI 决策日志。

## 语音朗读（可选）

在「语音朗读」页开启后，编排器会把可公开的事件转成语音事件，读完一段再继续推进，形成「上帝播报 → 玩家发言 → 下一人行动」的节奏；斗地主与三国杀会先读一句聊天，再读出打出的牌。

- **默认关闭**：未开启或未配置时不会产生任何语音事件，对局逻辑与之前完全一致；保存配置后立即生效，进行中的对局也会热加载。
- **音色优先级**：座位 `voice_id` → Provider `voice_id` → 全局默认 `voice_id`；旁白 / 上帝播报使用 `narrator_voice_id`。
- **语音通道**：
  - `browser`：后端只下发文本与 `voice_id`，前端用 Web Speech API 本地朗读，适合零成本测试；
  - `system`：后端直接调用 Windows SAPI 在本机朗读，适合 WebView2 拿不到浏览器音色的桌面端；失败时自动退回浏览器朗读；
  - `voicestudio`：后端按配置向自定义 HTTP TTS 发起 POST，支持返回音频 URL、base64 或二进制音频；失败时自动退回浏览器朗读。
- **诊断**：「语音朗读」页展示浏览器是否支持语音、音色数量、最近错误与后端系统语音是否可用；牌桌语音按钮也会提示当前环境是否缺少语音引擎。
- **桌面端自动兜底**：Tauri 桌面壳使用 WebView2，语音引擎可能报告有音色却无声。牌桌连接后会检测环境，必要时自动通知后端把本局切换为系统语音，无需手动改配置。
- **回执节奏**：前端播完发送 `{"type": "speech_done", "speech_id": "..."}`，编排器等待回执（默认 15 秒超时）后再让下一个人行动；没有客户端连接时直接跳过。
- **静音**：牌桌右上角可本机静音，静音后仍会回执，不会拖慢对局。
- **音色选择**：座位、群组与 Provider 的 `voice_id` 都是可选下拉框，自动列出当前浏览器的系统音色；使用 VoiceStudio 时也可以直接填写服务端音色 ID。

## AI 玩法策略

为了让 AI 不只是“会按规则走”，每个游戏引擎都可以提供两张提示卡，编排器会随每次行动注入：

- `GameEngine.skill_for(seat_id)`：角色玩法技能卡，相当于开局先“调用”该角色的 SKILL。狼人、预言家、女巫、猎人、村民，地主/农民，主公/忠臣/反贼/内奸都有各自的玩法要点。
- `GameEngine.action_hint(req, seat_id)`：当前动作的即时策略检查，例如“女巫毒药绝不能毒自己”“狼人密谈必须发言”“农民不要压队友”。

输出协议也升级为 `stance → plan → action` 的结构：先选姿态（支持/进攻/观察），再列计划与候选动作，做安全自检后给出最终动作。上一轮的 `reads`（身份概率）会回流到下一次提示词，形成持续的信念追踪。

每局开始时，引擎还会给每个座位随机分配一种**性格**（激进 / 稳健 / 保守 / 诡诈 / 理性 / 直觉），连同角色技能卡注入系统提示词。性格只影响取舍与表达，不会让 AI 获得额外信息；同一套模型在不同对局里会表现出不同的进攻性、留牌习惯与欺骗倾向。兜底动作也按性格随机：

- 女巫兜底时在「救 / 不救」之间随机，激进或诡诈性格有少量概率用毒；
- 斗地主叫分与出牌按性格在「抢分 / 不叫」「压制 / 过牌」之间选择；
- 三国杀按性格决定进攻频率与闪、杀的响应意愿。

针对已发现的“傻操作”做了硬性保护：

- 女巫毒药目标不能是自己或非存活玩家（引擎校验直接拒绝）；
- 狼人密谈、白天发言必须有内容，AI 连续失败时使用兜底发言，避免集体沉默；
- 所有动作仍经过 `validate` 校验，非法输出会带着具体错误重试。

新增游戏只需实现 `skill_for` / `action_hint`，即可获得同样的策略注入。

## RAG 记忆库与上下文压缩

「AI 记忆库」页把三类记忆统一存进 SQLite（表 `memories`），并用内置哈希向量做余弦检索：

- `skill`：每个游戏每个角色的玩法技能卡，服务启动或点“重新导入”时幂等入库；
- `lesson`：每局结束后，把该座位的可见上下文压缩成 2-4 条可执行技巧；
- `manual`：手动录入的经验，例如“狼人首夜优先刀信息位”。

运行机制：

- **每步检索**：`GameRunner.memory_block()` 用当前角色、阵营、动作类型与最近事件拼成查询，先按 `game_id / role / faction` 过滤，再取 `top_k` 条相似记忆注入提示词；
- **上下文压缩**：可见事件超过 100 条时，保留开头与最近 60 条，中间压成“事件类型统计 + 关键节点”，避免长对局提示词膨胀；
- **对局复盘**：结束后对每个座位做一次复盘（默认调用该座位模型，`llm_reflect` 可关），失败时用角色规则兜底；结果写入 `memories`，并在牌桌上帝视角展示；
- **零依赖**：默认不需要 Chroma / FAISS / sentence-transformers，离线可跑。若想换真实 embedding，只需替换 `backend/app/rag.py` 的 `embed()`。

## AI 进化路线（可选）

当前已落地的“变聪明”手段：角色技能卡、`stance → plan → 自检 → action` 结构化决策、身份概率回流、非法动作重试、RAG 经验检索、赛后复盘沉淀。

进一步可做的方向（按投入产出排序）：

1. **多候选 + 裁判**：同一局面采样 2-3 个候选动作，让另一个模型按“合法性、收益、暴露风险”投票，降低单次采样失误。
2. **自我对弈与课程学习**（已落地基础版）：训练场可连续跑 N 局并统计胜率；下一步可按胜率调整座位与角色难度，先固定阵容练单角色，再开放全角色。
3. **真实向量模型**：把 `embed()` 换成 BGE / text-embedding-3，记忆量大时再引入 FAISS 或 Chroma；embedding 服务建议走本地或国内镜像。
4. **本地小模型辅助**：用 Ollama / llama.cpp 跑 Qwen2.5-7B 级别的模型，做“动作合法性检查、复盘教练、发言润色”等辅助角色；主决策仍可交给大模型。
5. **本地小模型主导**：用 QLoRA 在消费级显卡上微调 7B 模型（Unsloth / LLaMA-Factory），数据来自 `agent_logs` 与赛后复盘；国内可用 ModelScope 或 `HF_ENDPOINT=https://hf-mirror.com` 下载基座与数据集。
6. **更长程的记忆**：按“对手习惯 / 地图 / 角色”建立可检索的玩家画像，跨对局复用；注意区分事实记忆与推测，避免把错误结论固化。

> 不建议一上来就训练：先用 RAG + 结构化提示词把数据跑出来，等 `agent_logs` 有几千条高质量对局后，再决定是微调、蒸馏还是继续 RAG。

## 训练场（自对弈）

侧边栏「训练场」用于让 AI 连续自对弈，不进入牌桌、不展示逐条发言，只保留统计：

- **快速对局**：关闭事件持久化、AI 调用日志与语音，直接跑完整状态机；Mock Provider 会使用极低延迟。
- **并发**：1-8 路并发，统计总局数、完成数、失败数、胜方分布、平均回合、平均耗时与新增记忆数。
- **记忆沉淀**：默认训练时读取 RAG 技能卡，并在每局结束后把复盘技巧写回记忆库，长期跑会不断积累可复用经验。
- **Ollama**：选择指向 `http://127.0.0.1:11434/v1` 的 Provider 后，点「检测 Ollama 模型」可列出本机模型，点模型名即可切换该 Provider 的 `model` 字段。

### 本地 Ollama 与国内镜像

```powershell
# 安装 Ollama 后拉取模型（Ollama 官方源通常可直连）
ollama pull qwen2.5:7b
ollama serve
```

- Ollama 暴露 OpenAI 兼容接口：`base_url` 填 `http://127.0.0.1:11434/v1`，`api_key` 留空，`kind` 选 `openai`。
- 训练并发建议 1-2，避免本地显存不足；7B 模型在 8GB 显存上建议使用 `qwen2.5:7b-instruct-q4_K_M` 等量化版本。
- 需要下载 HuggingFace 基座 / 数据集时，先设置国内镜像：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
```

- ModelScope（魔搭）也可作为国内模型与数据集来源：<https://www.modelscope.cn>。
- 本项目自身的 Python / npm 依赖不需要额外镜像；若网络较慢，可自行配置 `pip` 与 `npm` 国内源。

## 数据库

SQLite 数据库文件为 `multi_ai_group.db`，位于系统应用数据目录（Windows 为 `%APPDATA%\MultiAIGroup`），可用 `MULTI_AI_DATA_DIR` 覆盖。主要数据表：

- `providers`：AI 服务配置
- `groups`：AI 群组与座位模板
- `matches`：对局、座位、公开状态、私有状态与结果
- `events`：对局事件流（含可见性）
- `agent_logs`：每次 AI 调用的提示词、原始返回、解析结果与错误
- `memories`：RAG 记忆（技能卡、复盘技巧、手动经验），含向量与角色/阵营标签
- `settings`：全局配置（目前保存语音朗读配置 `voice` 与 RAG 配置 `rag`）

服务启动时会把上次残留的 `running` / `paused` 对局标记为 `interrupted`。

## API 速览

基础：

- `GET /api/health`、`GET /api/provider-presets`、`GET /api/games`

Provider：

- `GET/POST /api/providers`、`PUT/DELETE /api/providers/{id}`
- `POST /api/providers/{id}/test`

群组：

- `GET/POST /api/groups`、`PUT/DELETE /api/groups/{id}`

语音：

- `GET /api/voice`、`PUT /api/voice`（全局开关、音色与 VoiceStudio 字段映射）
- `GET /api/voice/diagnostics`（浏览器不可见，返回后端平台、系统语音可用性与当前通道）

训练场：

- `POST /api/train/start`（`game_id`、`provider_id`、`games`、`concurrency`、`seat_count`、`rag_enabled`、`reflect`）
- `GET /api/train/status`、`POST /api/train/stop`
- `GET /api/ollama/models?base_url=http://127.0.0.1:11434`（探测本机 Ollama 模型）

RAG 记忆库：

- `GET /api/rag`、`PUT /api/rag`（开关、`top_k`、最低相似度、是否复盘）
- `GET /api/rag/memories?game_id=&role=&kind=&limit=`、`POST /api/rag/memories`、`DELETE /api/rag/memories/{id}`
- `POST /api/rag/seed`（重新导入内置技能卡）、`GET /api/rag/search?q=&game_id=&role=&top_k=`（语义检索）

对局：

- `GET/POST /api/matches`
- `GET/DELETE /api/matches/{id}`
- `POST /api/matches/{id}/start`、`POST /api/matches/{id}/stop`
- `GET /api/matches/{id}/events`、`GET /api/matches/{id}/logs?seat_id=&limit=`

实时：

- `WS /ws/matches/{id}`，首帧为 `snapshot`，之后推送 `events`、`state`、`match_status`、`voice`；客户端可发送 `ping` 获得 `pong`
- 收到 `voice` 后，前端播完语音需回执 `{"type": "speech_done", "speech_id": "<原样返回>"}`；超时或客户端未连接时后端自动继续

## 新增游戏插件

游戏逻辑全部放在 `backend/app/plugins/`，服务启动时自动扫描并注册，**不需要修改注册表或前端代码**。

新增步骤：

1. 在 `backend/app/plugins/` 下新建模块（如 `mygame.py`）或子包。
2. 继承 `GameEngine`，声明 `game_id`、`name`、`description`、`min_players`、`max_players`、`allowed_counts`、`rules`、`presets`。
3. 实现 `start()`、`advance()`、`apply()`、`public_state()`、`private_state()`。
4. 在模块末尾导出 `ENGINE = MyGameEngine`。
5. 重启后端，前端会自动从 `GET /api/games` 拿到新游戏。

最小插件示例：

```python
from ..engine import GameEngine, Seat


class MyGameEngine(GameEngine):
    game_id = "mygame"
    name = "我的游戏"
    description = "一句话介绍"
    min_players = 2
    max_players = 4
    allowed_counts = (2, 3, 4)
    rules = "在这里写规则，会进入 AI 的系统提示词。"
    presets = []

    def start(self) -> None: ...
    def advance(self) -> None: ...
    def apply(self, req, action) -> None: ...
    def public_state(self) -> dict: ...
    def private_state(self, seat_id: str) -> dict: ...


ENGINE = MyGameEngine
```

插件约定：

- `ENGINE` 必须是 `GameEngine` 的子类，`game_id` 全局唯一。
- 插件可以是单文件模块，也可以是子包；子包在 `__init__.py` 中导出 `ENGINE` 即可。
- 加载失败的插件会被跳过，不影响其它游戏，失败原因记录在 `app.plugins.PLUGIN_ERRORS` 并输出启动警告。
- 需要 AI 决策时调用 `self.request(...)`，需要对外播报时调用 `self.emit(...)` / `self.say(...)`；涉及私有信息时传入 `Visibility.private(...)` 或 `Visibility.group(...)`。

引擎不感知 AI、网络与数据库，这些都由 [runner.py](backend/app/runner.py) 负责串联。

## 测试

```powershell
cd backend
python -m pytest
```

测试配置见 `backend/pytest.ini`，当前覆盖各游戏引擎的状态机与规则。

## 常见问题

- **前端报 `failed to fetch` / 显示离线**：说明浏览器或 Tauri 连不上后端。先在终端执行 `Invoke-WebRequest http://127.0.0.1:8765/api/health` 确认后端已启动；再确认 `VITE_API_BASE` 指向正确地址。前端每 5 秒轮询一次 `/api/health`，后端恢复后会自动转回在线。
- **Tauri 启动后前端一直 `failed to fetch`**：桌面端会自动启动 `backend/.venv/Scripts/python.exe`。如果 `.venv` 已损坏（例如从其它机器拷贝过来），后端无法启动。删除 `backend/.venv`，在本机重新创建并安装依赖（见「快速开始」），或直接手动启动后端后重启桌面端。
- **Provider 测试失败**：检查 `base_url`、`model`、`api_key`；OpenAI 兼容服务若不支持 `response_format`，后端会自动去掉该字段重试一次。
- **AI 输出无法解析**：编排器最多尝试 2 次，仍失败时使用引擎的兜底动作，并在 `agent_logs` 中记录原因。
- **对局卡住或重启后状态异常**：对局状态保存在 SQLite，重启后端后残留运行态对局会被标记为 `interrupted`，重新启动即可。
- **删除了 `frontend/src-tauri/target`，`npm install` 无法恢复**：`target/` 是 Cargo 的编译产物目录，不是 npm 包，`npm install` 只会恢复 `frontend/node_modules`。解决办法：
  1. 安装 Rust 工具链（`winget install Rustlang.Rustup`，或参考 <https://rustup.rs>），并安装 Visual Studio C++ Build Tools 与 WebView2 Runtime。
  2. 在 `frontend` 下执行 `npx tauri info`，确认 `rustc`、`Cargo` 已安装。
  3. 执行 `npm run tauri dev` 或 `npm run tauri build`，`src-tauri/target` 会自动重新生成。
  4. 如果只做浏览器开发，完全不需要该目录，执行 `npm run dev` 即可。
- **后端启动报 `uv trampoline failed to spawn Python child process`**：`.venv` 指向了当前机器上不存在的 Python。删除 `backend/.venv` 后按「快速开始」重新创建即可。
