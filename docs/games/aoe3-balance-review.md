# 帝国3 单位平衡变更审查

> 游戏数据刷新后，用 git 快照比较新旧单位字段，辅助判断哪些改动值得复核。
>
> 这是分析工具，不是游戏平衡结论，也不是 QQBot 运行时依赖。

## 用途

脚本比较两个提交中的 `seeds/aoe3/units.json`，输出：

- 单位新增 / 消失
- 战斗、成本、文本字段变化
- 辅助公式分变化和归因
- 新版与旧版单位的镜像模拟结果
- 对火枪兵 / 轻骑兵 / 弩手 / 鹰炮四类固定陪练的胜率迁移

## 口径边界

- 辅助公式分复用斗蛐蛐的 `power_score`，只覆盖 HP、护甲、攻击、AOE、攻击间隔和弹丸数。
- 公式不覆盖倍率、射程、抬手、攻击槽、时代和实际克制关系，不能单独作为增强 / 削弱结论。
- `rof_*` 表示两次攻击之间的秒数：数值降低代表攻击更快。
- 模拟结果只用于交叉验证；镜像胜率和固定陪练都可能受站位、克制链和极端数值影响。

## 运行

```bash
# 默认比较数据刷新前的 seeds 快照与当前工作区
uv run python scripts/aoe3_balance_review.py --no-sim

# 跑镜像战与固定陪练
uv run python scripts/aoe3_balance_review.py

# 指定旧版提交和输出位置
uv run python scripts/aoe3_balance_review.py \
  --old-rev <git-rev> \
  --out data/aoe3/balance_review.json
```

`data/aoe3/balance_review.json` 是分析中间产物，默认不提交。需要分享报告时，优先提交精简摘要或可复现命令，不要提交整份页面和重复图标。
