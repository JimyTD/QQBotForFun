# AoE3 斗蛐蛐 —— 士兵状态机 & Tick Pipeline

## Tick Pipeline（每 tick 执行顺序）

```
┌─────────────────────────────────────────────────┐
│                  每个 Tick                        │
├─────────────────────────────────────────────────┤
│  ① _process_movement()    所有存活单位移动判定    │
│  ② _rebuild_sorted_cache() 重建位置索引          │
│  ③ _acquire_target()      stopped 的兵锁定目标   │
│  ④ _process_attacks()     stopped+CD就绪→攻击    │
│  ⑤ _process_deaths()      防御性死亡清算         │
│  ⑥ _check_winner()        胜负判定              │
└─────────────────────────────────────────────────┘
```

## 士兵状态机（3 个状态）

```
                         ┌──────────────────────────────────────┐
                         │           MOVING（正常移动）           │
                         │  行为：向最近敌方全速前进              │
                         │  速度：unit.speed × 1.0              │
                         └───────────┬──────────────────────────┘
                                     │
                          _can_attack_any_enemy()?
                          远程: range_min ≤ dist ≤ range
                          近战: dist ≤ melee_range
                                     │ Yes
                                     ▼
                         ┌──────────────────────────────────────┐
                         │          STOPPED（站定攻击）           │
                         │  行为：锁定目标 → 判定模式 → 攻击      │
                         └───┬──────────────────────────────┬───┘
                             │                              │
                  射程内无存活敌方                    [仅纯近战兵]
                  (WARNING → 回 MOVING)             所有近战目标 CAP 满
                             │                              │
                             ▼                              ▼
                    stopped=False              ┌────────────────────────┐
                    回到 MOVING                │   INFILTRATING（渗透）   │
                                              │  行为：缓慢穿越找后排    │
                                              │  速度：speed × 0.1      │
                                              └──────────┬─────────────┘
                                                         │
                                              找到 CAP 未满目标?
                                                         │ Yes
                                                         ▼
                                                回到 STOPPED
```

## 攻击模式决策树（STOPPED 状态下每次攻击）

核心原则：**不允许"等"，每个兵必须做出有效行动。**

```
已锁定目标，计算 dist
        │
        ├── dist ≤ melee_range
        │       ├── has_melee → MELEE
        │       └── 纯远程   → RANGED_PENALIZED (×0.5，保底输出)
        │
        ├── range_min ≤ dist ≤ range (远程有效区间)
        │       └── RANGED
        │
        ├── dist < range_min 且 dist > melee_range (死区)
        │       └── ERROR log + 取消 stop (不应走到这里)
        │           ├── has_melee → 回 MOVING (前进到近战距离)
        │           └── 纯远程   → RANGED_PENALIZED (防御性保底)
        │
        └── dist > range (超出所有射程)
                └── ERROR log + 取消 stop (不应走到这里)
```

## "能攻击"的统一判定标准

所有地方（`_can_attack_any_enemy`、`_acquire_target`）使用相同标准：

| 攻击类型 | 有效区间 | range_min 未配置时 |
|----------|----------|-------------------|
| 远程 | `[range_min, range]` | `[0, range]` |
| 近战 | `[0, melee_range]` | `[0, melee_range]` |

**不在有效区间内 = 不算能攻击 = 不会 stop = 继续前进。**

## 伤害公式

```
damage = base_atk × multiplier × (1 - armor)

if RANGED_PENALIZED:
    damage × 0.5 (贴脸惩罚，仅纯远程兵无近战时)

damage = max(damage, 1.0)   ← 保底 1 点
```

## 异常检测 (ERROR log)

| 场景 | 日志 |
|------|------|
| 兵处于"死区"(range_min > dist > melee_range) | `处于死区！dist=X range_min=Y melee_range=Z` |
| 兵 stopped 但无法攻击目标（超出射程） | `无法攻击目标！dist=X` |

这些 ERROR 说明 `_can_attack_any_enemy` 的判定与实际攻击判定不一致，需要排查。
