# 海龟汤 Judge 评估集

`golden_judge.jsonl` 用于评估汤主（judge）模型对玩家提问的判定质量。

## 格式

JSONL 文件，每行一个 JSON 对象，字段如下：

| 字段 | 说明 |
|------|------|
| `id` | 用例唯一标识 |
| `tags` | 分类标签，如 `F1`（surface/truth 误读）、`baseline`、`chenmo` |
| `puzzle` | 谜题上下文：`title`、`surface`（汤面）、`truth`（汤底）、`key_clues`；可选 `canonical_facts`、`surface_gloss` |
| `question` | 玩家提问 |
| `expected` | 期望判定：`type` 为 `yes` / `no` / `key` / `irrelevant` / `claim_detected`；可选 `acceptable` 列出可接受的替代类型 |
| `rationale` | 期望判定的简要理由 |

## 判定类型

- **yes** / **no**：问题答案肯定 / 否定
- **key**：直接触及关键线索
- **irrelevant**：与故事核心无关
- **claim_detected**：玩家猜出完整真相

## F1 标签

`F1` 用例专门测试 **surface vs truth 误读**：玩家询问汤底事实但汤面未提及，或汤面叙述与汤底矛盾。合格判官应依据汤底（及 key_clues）作答，不可仅因汤面无据而判 `irrelevant`，也不可被汤面字面误导。

## 用法示例

```python
import json

with open("tests/eval/turtle_soup/golden_judge.jsonl", encoding="utf-8") as f:
    cases = [json.loads(line) for line in f if line.strip()]
```

将 `puzzle` 与 `question` 送入 judge prompt，比较输出 `type` 与 `expected.type`（或 `expected.acceptable`）。

## 脚本

| 脚本 | 用途 |
|------|------|
| `scripts/eval_soup_judge.py` | 同一模型下 prompt 版本对比（baseline vs v1.3） |
| `scripts/eval_judge_compare.py` | 多模型 golden 对比；**仅含生产相关候选**，ping 不通静默跳过 |
| `scripts/benchmark_llm.py` | 生产模型 ping；不可用模型不出现在汇总 |

有意义候选：`LongCat-Flash-Chat`（生产 judge）、`LongCat-Flash-Lite`、`glm-4-flash-250414`。已知更差或 JSON 不可用的老模型不在对比矩阵中。
