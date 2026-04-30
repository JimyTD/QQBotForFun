# 海龟汤 · 插件说明

- Game ID: `turtle_soup`
- 指令：
  - `/开始 turtle_soup` — 开始一局（别名：`/play`、`/开局`、`/玩`）
  - 提问：以 `?` 或 `？` 结尾
  - 宣告：以 `汤底:` / `答案:` / `宣告:` 开头
  - `/汤 状态` — 查看进度（别名：`/soup status`）
  - `/汤 投降` — 投降公布汤底（别名：`/soup giveup`）
  - `/汤 回顾` — 回顾关键线索（别名：`/soup recap`）
  - `/汤 烂题` — **本局结束后 5 分钟内**可用，硬删上一题（仅 `llm_generated` 题；别名：`/soup bad`、`/汤 差评`、`/汤 删除`）
  - `/结束` — 终止本局（别名：`/quit`）

## 题库治理（v2.2+）

- **来源**：`builtin`（人工种子）+ `llm_generated`（游戏中自动生成回写）
- **上限**：`llm_generated` 总数受 `GAME_TURTLE_SOUP_LLM_GENERATED_CAP`（默认 200）限制，超限时 FIFO 淘汰最老的一条；`builtin` 永不被淘汰
- **烂题反馈**：玩家通过 `/汤 烂题` 硬删刚玩过的题，窗口 5 分钟（由 `GAME_TURTLE_SOUP_MARK_BAD_WINDOW_SECONDS` 控制）
- **CLI 特殊处理**：play_cli 在每局结束后会追问 `这题要标记为烂题吗？(y/N)`，与 Bot 的 `/汤 烂题` 等价

## 经济接入（v2.3+）

遵循项目核心设计哲学：**及时正反馈 > 公平性**（详见 `docs/09-conventions.md` §0.5）。

| 事件 | 奖励 | 默认值 | 环境变量 |
|---|---|---|---|
| 提问命中 key 线索 | +score | `2` | `GAME_TURTLE_SOUP_REWARD_SCORE_ON_KEY_HIT` |
| 宣告部分正确（partial） | +score | `1` | `GAME_TURTLE_SOUP_REWARD_SCORE_ON_PARTIAL_HIT` |
| 宣告完全正确（赢家） | +score + +coin | `20` / `100` | `GAME_TURTLE_SOUP_REWARD_SCORE_ON_WIN` / `GAME_TURTLE_SOUP_REWARD_COIN_ON_WIN` |
| 投降 / 超时 / 烂题 | 不扣不加 | — | — |

- `score` 进 `/榜` 默认排行榜
- `coin` 进钱包（`/金币` 可查）
- **永不负反馈**：即使玩家投降或超时也不扣任何东西
- **CLI 策略**：CLI adapter 本地累加显示 `+X score / +Y coin`，但**不**真实调 `economy.add`（避免 `qq_id=0` 幽灵账户污染 DB）

详细设计见 [`docs/games/turtle-soup.md`](../../../../docs/games/turtle-soup.md)。

