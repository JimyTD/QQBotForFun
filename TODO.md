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

## 🖼️ 红警2斗蛐蛐：导出兵种 icon（`ra2_battle`）

**现象**：红警斗蛐蛐开局只有中文文字面板，**没有**帝国斗蛐蛐那种兵种头像图。
代码已接通（`game.py` 用 `broadcast_rich` 发图 + 文字），但 `resources/ra2/icons/`
目前**只有 README，没有 PNG**。

**背景**（2026-05-22 确认）：

- GitHub [OpenRA/ra2](https://github.com/OpenRA/ra2) **能独立运行**（装 OpenRA + 导入原版资源后），
  但仓库里**不能**分发原版美术（版权）；头像在 `language.mix` → `cameo.mix` 里的
  `giicon.shp` 等，不在 git 里。
- `data/ra2/icon_map.json`（45 条 actor → shp 文件名）已由 `openra_ra2_export.py`
  从 sequences 自动生成，**无需**游戏文件。
- 中文名在 `data/ra2/locale_zh.json`；结算战报重复发送已修（2026-05-22）。

**待办**（需要本机已有原版 RA2 或 OpenRA 已导入内容）：

1. **安装导出依赖**
   ```bash
   uv pip install ra2mix Pillow
   ```

2. **从 cameo.mix 导出 PNG**（任选其一目录，需含 `cameo.mix` + `cameo.pal`）
   ```bash
   # Steam 原版
   uv run python scripts/crawler/ra2_icon_export.py --ra2-dir "你的红警2安装目录"

   # 或 OpenRA 已导入的内容目录（常见）
   uv run python scripts/crawler/ra2_icon_export.py --ra2-dir "%LocalAppData%\OpenRA\Content\ra2"
   ```
   也可：`--cameo-mix` / `--palette` 直接指定文件；或环境变量 `RA2_DIR`。

   产出：`resources/ra2/icons/{actor_id}.png`（脚本默认缩到 128×128）。

3. **验收**
   - 约 45 个 PNG，`file` 头为 `\x89PNG\r\n\x1a\n`
   - 单文件尽量 ≤ 50KB（过大可参考 `scripts/compress_aoe3_icons.py` 改目录跑一遍）
   - **部署到 bot 服务器**（与代码一起），群里开 `@我 红警斗蛐蛐` 应看到红/蓝方各槽位头像

**已落地**：

- 导出：`scripts/crawler/ra2_icon_export.py`（SHP 解码对齐 OpenRA `ShpTSLoader`）
- 读取：`src/plugins/games/ra2_battle/icons.py`（坏 PNG magic 校验，缺图只发文字）
- 说明：`resources/ra2/icons/README.md`、`docs/games/ra2-battle.md` §8.3

**相关文件**：

- `data/ra2/icon_map.json`
- `src/plugins/games/ra2_battle/icon_map.py`（`dog`→`adog` 等序列名别名）

**优先级**：高 / 体验向 —— 与帝国斗蛐蛐展示对齐，缺图不影响开战。

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

## 🔫 多弹丸 / 连射兵种 DPS 严重低估（aoe3 数据 + simulator）

**现象**：加特林机枪、连弩兵这种**一次攻击循环打多发**的热门单位，斗蛐蛐里
DPS 被算成实际值的 1/3 ~ 1/10，对线表现完全脱离游戏直觉。

**问题对照**：

| 单位 | id | 当前数据 | 游戏实际 | 偏差 |
|------|----|--------|--------|------|
| 加特林机枪 | `xpgatlinggun` / `defortgatlinggunbatch` | `attack_ranged=20`, `rof_ranged=3.0`，单发 | 一次攻击循环连射 5~10 发，每发 ~10-20 | DPS ≈ 1/5 ~ 1/10 |
| 中国连弩兵 | `ypchukonu` | `attack_ranged=5`, `rof_ranged=3.0`，单发 | 一次攻击 3 连发 × 5 伤害 = 15 总伤害 | DPS ≈ 1/3 |
| 飞行乌鸦 | `Flying Crow`（火箭车） | 同上单发 | 一次齐射多发火箭 | 偏弱 |

（这两个都是热门单位，**不是冷门兵**——加特林机枪是中国进入工业的核心远程，
连弩兵是中国全程主力 skirm）

**根因**：

1. **数据侧**：`seeds/aoe3/units.json` 没有"弹丸数 / 连射数"字段。
   游戏 protoy.xml 里这些信息在 protoaction 节点的 `<NumberProjectiles>` /
   `<NumRangedAttacks>` 之类的字段，**爬虫 (`aoe3_gamedata_parser.py`)
   完全没读**。
2. **模拟器侧**：`simulator.py` 也没有 burst / multi-projectile 处理逻辑
   （grep `projectile|burst|shots` 0 命中），完全按"一次开火 = 一发命中"
   计算。即使数据有了字段，simulator 也得改才能用上。

**修复方案**（需要装了 AoE3 DE 的机器拆包验证）：

1. **拆包确认弹丸字段名**
   - `scripts/crawler/_extracted/protoy.xml` 搜
     `<unit name="xpGatlingGun">` / `<unit name="ypChuKoNu">` 的
     `<protoaction>` 节点
   - 看连射相关字段叫什么（`NumberProjectiles` / `NumRangedAttacks` /
     `RangedAttackBurst` / 类似），记下精确字段名
   - 看 RoF 是"整个 burst 的间隔"还是"单发间隔"——这决定了乘法该怎么算

2. **爬虫补字段**
   修改 `scripts/crawler/aoe3_gamedata_parser.py :: _parse_attacks`，把弹丸数
   读出来塞进每个攻击模式的 dict，最终落到 `units.json`：
   ```json
   "attack_ranged": 20,
   "rof_ranged": 3.0,
   "num_projectiles_ranged": 8,   // ← 新增
   ```
   注意：和迫击炮 multipliers 问题一样要遵守 MEMORY.md ID 54955007 的铁律
   ——弹丸数必须和当前选定的代表攻击属于**同一个攻击模式**，不能跨模式拼。

3. **simulator 支持连发**
   `simulator.py :: _resolve_ranged` 一带，开火时按 `num_projectiles` 处理。
   两种实现方案：
   - **简化版**：伤害 × 弹丸数（一次结算）。最简单，但 AOE / 暴毙判定
     不准（实际是多发独立命中，会重复触发 AOE）。
   - **精确版**：拆成 N 次独立命中，每次走完整的伤害结算流程。
     更准但要小心 CD：N 发都已"打出"后才进入 RoF 间隔。
   - 推荐先做简化版，跑通后再决定要不要升级。

4. **验收**
   - `seeds/aoe3/units.json` 里加特林机枪、连弩兵、飞行乌鸦都有
     `num_projectiles_ranged` 字段
   - `/帝国3 加特林机枪` 详情页显示弹丸数（renderer 也得加）
   - 斗蛐蛐里 10 加特林机枪 vs 10 步兵线，加特林应该明显占优；
     现在大概率打输（DPS 被低估 5x）

**相关文件**：
- 爬虫：`scripts/crawler/aoe3_gamedata_parser.py`（`_parse_attacks`）
- 数据：`seeds/aoe3/units.json`
- 模拟：`src/plugins/games/aoe3_battle/simulator.py`
- 详情渲染：`src/plugins/aoe3/render.py`（如果加了字段也要在详情里展示）

**优先级**：中-高 / 平衡向 —— 影响两个热门兵种在斗蛐蛐里的判定，群里玩家
对加特林机枪 / 连弩兵的体感会很违和。但工作量较大（拆包 + 爬虫 + simulator
三处都要动），不是小修。

---


