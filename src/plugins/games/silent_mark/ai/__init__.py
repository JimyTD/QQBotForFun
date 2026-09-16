"""静夜标记 · AI 玩家子系统。

移植自源项目 `server/game/ai/`（2242 行 TypeScript）。分工：

| 源 | 本侧 |
|---|---|
| `AIContextBuilder` | `context.py`：信息过滤唯一出口，直接复用 `engine.private_info` |
| `AIPromptTemplates` | `prompts.py`：中文策略文案**逐字移植**（这是最有价值的资产） |
| `AIDecisionGuard` | `guard.py`：硬约束，最容易写错、最该独立单测 |
| `AIPersona` | `persona.py`：6 人格，整局固定 |
| `AIPlayerController` | `controller.py`：延迟 / 容错解析 / 三级兜底 |
| `AILogger` | `logger.py`：JSON 落盘，便于事后复盘"AI 为什么这么打" |
| `aiNames` + `generateAIName` | `names.py`：LLM 取名 + 名字池兜底 |

**统一经由 `core.llm`**（源项目自带的 `AIApiClient` 不移植）。
"""
