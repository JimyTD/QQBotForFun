# TODO

> 待办事项列表 —— 需要在本机 / 装了游戏的机器上验证或处理的事项。

---

## 🖼️ aoe3 单位 icon 损坏导致 3v3 阵容广播发图失败

**现象**：3v3 斗蛐蛐阵容公布时，QQ 上 6 张兵种 icon 经常有 3~4 张发不出去
（NapCat 报 `rich media transfer failed`，retcode=1200）。1v1 单挑也偶发。

**根因**（已在 win 机本地复现确认，2026-05-21）：

`resources/aoe3/icons/` 共 2005 张 PNG，其中 **230 张文件根本不是 PNG**。
随便挑一张 `abusgun.png`（158KB）看 magic bytes：

```
hex:   02 01 00 fc fd ff 00 fb ...   ← 异常
正确:  89 50 4E 47 0D 0A 1A 0A       ← PNG header "\x89PNG\r\n\x1a\n"
```

这些是游戏原始 DDT/裸像素纹理被错误命名成 `.png` 写出来的。NapCat 按扩展名当
PNG 处理，解码失败 → QQ 服务端拒收 → 整条消息发送失败。
3v3 抽 6 个兵种期望命中 230/2005 ≈ 11.5% × 6 ≈ 0.7 张坏图，加上"常见正规兵
反而更容易踩坑"（如奥斯曼枪手 abusgun）的偏置，实测 3-4/6 失败完全合理。

辅助指标：本地另跑了体积统计，正常 PNG 也有 180+ 张超过 50KB（部分到 200KB+），
对单条消息总大小也是隐患（QQ 单消息上限约 1MB），但这不是当前主因，**主因就是
DDT 假冒 PNG**。

**修复方案**（需要装了 AoE3 DE 的本机执行）：

1. **解包 BAR 文件 → 重新生成正版 PNG**
   ```bash
   # 路径在 scripts/crawler/aoe3_icon_extractor.py 顶部 GAME_ART_DIR / GAME_UI_DIR
   # 默认 E:\SteamLibrary\steamapps\common\AoE3DE\Game\Art (UI)
   # 按本机调整后：
   uv run python scripts/crawler/aoe3_icon_extractor.py
   ```
   这个脚本会：
   - 读 `_extracted/protoy.xml` 拿到每个 unit 的 icon 路径
   - 扫 `ArtUnitsTextures{1..5}.bar` / `ArtUI.bar` / `UIResources1.bar` 等
   - DDT 格式经 RTS3 解码（DXT1/DXT5/BGRA）转成真 PNG
   - 原生 PNG（DE DLC 内容）直接 dump
   - 输出到 `resources/aoe3/icons/{unit_id}.png` **会覆盖**当前的坏文件

   预期：matched 数应≈2000，failed 应趋近 0。如果 unmatched 列表里仍有 230 张
   （和当前坏文件数量重合），说明 icon_extractor 没匹配到对应 BAR 项，需要排查
   `_extracted/protoy.xml` 里它们的 icon 字段写的什么路径。

2. **运行体积压缩 + 损坏检测**
   ```bash
   uv run python scripts/compress_aoe3_icons.py --dry-run   # 先看清单
   uv run python scripts/compress_aoe3_icons.py             # 实际压缩
   ```
   `compress_aoe3_icons.py` 已经写好（i:\QQBotForFun\scripts\），逻辑：
   - 检测 PNG magic bytes，非 PNG 一律报告并**跳过**（不删，留人工判断）
   - 正常 PNG 如果 > 50KB 或边长 > 256px → 缩到 128×128 + PNG optimize
   - 输出统计报告（处理数 / 压缩前后总大小 / 损坏文件清单）

   重爬完成后再跑一次 dry-run，**预期"损坏" 应该=0**，如果还有非零，说明 icon_extractor
   没修好那些条目，需要回到步骤 1 排查。

3. **验收**
   - `resources/aoe3/icons/` 下 2000+ 张 PNG，全部 magic bytes 是 `89 50 4E 47`
   - 单文件体积 ≤ 50KB
   - 提交后部署到服务器，群里跑几次 3v3 斗蛐蛐，连续 5 把不再出现
     `rich media transfer failed`

**已落地的防御性兜底**（2026-05-21，commit 待提交）：

`UnitRepo.get_icon_path()` 已加 PNG magic bytes 校验，文件前 8 字节不是
`\x89PNG\r\n\x1a\n` 就返 `None`。渲染层（`aoe3_battle/game.py:339-359`）的
`if icon_path:` 已有 None 跳过逻辑，所以**坏一张只丢那一张图，其他图和文字详情
照常发**，不会再让整条消息被 QQ 服务端拒收。

这个兜底是长期保障，**不替代**重爬 icon 文件（坏图用户还是看不到那张兵的图标）。
重爬+压缩做完后，兜底依然保留，作为未来任何坏图的保险。

**相关文件**：
- 解包：`scripts/crawler/aoe3_icon_extractor.py`（已有，靠 BAR + protoy.xml）
- 压缩 / 检测：`scripts/compress_aoe3_icons.py`（本次新增）
- 临时脚本：`_tmp_inspect.py` / `_tmp_check_icons.ps1`（验证用，可删）
- 资源说明：`docs/games/aoe3.md` §6（268×270 / 15KB / 6.5MB 总体积已过时，重爬后会变）

**优先级**：高 / 体验向 —— 直接影响斗蛐蛐核心展示。

---

## 🐎 沙漠突袭者反兵攻击缺失（aoe3 数据）

**单位**：`deoutlawdesertraider` Desert Raider 沙漠突袭者
**现象**：游戏里它是骑兵无法者，**确实能打兵**，但当前 `seeds/aoe3/units.json` 里：

```
attack_ranged: None
attack_melee:  None         ← 异常
attack_siege:  26.0
```

**对照组**（同系列沙漠三兄弟）：

| 单位 | atk_r | atk_m | atk_s |
|------|-------|-------|-------|
| `deoutlawdesertarcher` 沙漠射手 | 12 | 12 | 12 |
| `deoutlawdesertraider` 沙漠突袭者 | **None** | **None** | **26** ← 异常 |
| `deoutlawdesertwarrior` 沙漠勇士 | 11.2 | 9.6 | 24 |

只有突袭者完全没有 melee。

**主流假设**：
parser (`scripts/crawler/aoe3_gamedata_parser.py :: _parse_attacks`) 用
**动作名子串匹配** `"BuildingAttack" in name` 把所有名字含 `BuildingAttack` 的
protoaction 统统丢进 siege 桶。怀疑突袭者的真攻击叫
`"MeleeBuildingAttack"` 或 `"CavalryBuildingAttack"`：
- `damagetype = "Hand"`（吃 melee 护甲）
- `maxrange ≤ 2`（近战）
- 但名字含 `BuildingAttack` → 被错分到 siege 桶
- 于是 `attack_melee` 槽位空了，单位被 `has_attack` 过滤掉，退出战斗池

**修法（待验证后实施）**：

修改 `_parse_attacks` 的归类逻辑，**只看 damagetype + maxrange，不再看动作名**：

```python
# 旧逻辑：
if "BuildingAttack" in name:
    siege_candidates.append(info)        # ❌ 子串匹配
elif damagetype == "Siege" and maxrange > 6: ...
elif damagetype == "Hand" or maxrange <= 2: ...

# 新逻辑（待验证）：
if damagetype == "Hand" or maxrange <= 2:
    melee_candidates.append(info)        # 不管动作名
elif damagetype == "Ranged":
    ranged_candidates.append(info)
elif damagetype == "Siege" and maxrange > 6:
    ranged_candidates.append(info)       # 远程炮击
elif damagetype == "Siege":
    siege_candidates.append(info)        # 真正的拆建筑专用
```

**验证步骤（需要装了 AoE3 DE 的机器）**：

1. 跑解包：`python scripts/crawler/aoe3_bar_extractor.py`（默认路径
   `E:\SteamLibrary\steamapps\common\AoE3DE\Game\Data\Data.bar`，按你机器调整）
2. 在 `scripts/crawler/_extracted/protoy.xml` 中搜
   `<unit name="deOutlawDesertRaider">` 的完整节点，确认：
   - 它是否真有 `damagetype="Hand"` + 名字含 `BuildingAttack` 的 protoaction
   - damage 值是否 ≈ 26
3. 如果假设成立 → 修 parser，重跑 `aoe3_gamedata_parser.py` + `merge_to_seeds.py`
4. 验收：`seeds/aoe3/units.json` 里突袭者应该有 `attack_melee ≈ 26`，
   重启 bot 后能进战斗池

**降级方案**（如果假设不成立）：
- 如果 xml 里突袭者根本没有 Hand 类 protoaction，那就是游戏数据本身缺失
  （可能通过 tactic / entityaction 继承），需要单独想办法
- 如果是这种情况，**不要**把它加 `has_attack` 白名单——保持当前排除即可

**相关讨论**：见 2026-05-21 群聊"攻击方式 vs 伤害属性"对话，以及
`docs/games/aoe3-battle.md` §3.9。

**优先级**：低 / 体验向 —— 不修也不影响斗蛐蛐核心玩法，只是少一个候选兵种。

---

## 🎯 迫击炮系列 multipliers 整体缺失（aoe3 数据）

**现象**：`/帝国3 迫击炮` 系列（`mortar` / `demortar` / `xpheavymortar` 等）
查出来的兵种倍率（multipliers）字段是空的，但游戏里它们对建筑 / 海军有非常高
的倍率（实测对城镇中心 ×3、对船 ×2 等）。

**根因怀疑**：`scripts/crawler/aoe3_merge_supplement.py` 里的
"每个兵种只选一个 ranged + 一个 melee 攻击作为代表"逻辑，对迫击炮这种
**主攻 = Cannon Attack（攻城），还有 Barrage Attack 等多个攻击模式**的兵种
选错了代表攻击，导致主攻的 bonuses 没被写进 `units.json`。

**铁律提醒**（来自 MEMORY.md ID 54955007）：
supplement 中每个攻击模式的 damage/range/rof/aoe/bonuses 是**一套完整数据**，
必须整体选用。绝对禁止把攻击 A 的伤害和攻击 B 的倍率拼在一起。
要修的情况是"选错了代表攻击"，**不是**"从多个攻击里拼数据"。

**验证步骤**：
1. 跑 `python scripts/crawler/inspect_supplement.py mortar`（如果脚本不存在
   就直接读 `seeds/aoe3/units_supplement_da.json` / `_es.json`），确认迫击炮在
   supplement 里有几个攻击模式、各自的 damage/bonuses。
2. 看当前 `units.json` 里 `mortar` 的 attack_siege / multipliers_siege 字段
   到底取的是哪个攻击模式。
3. 如果取错了 → 改 `aoe3_merge_supplement.py` 的代表攻击挑选规则
   （比如：siege 桶里优先选 ``CannonAttack``，再考虑 damage 最大的）。

**优先级**：中 / 体验向 —— 影响斗蛐蛐里迫击炮 vs 建筑/船的判定（目前会偏弱）。

---

