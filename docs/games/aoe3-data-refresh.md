# 帝国3 数据刷新 SOP

> 游戏大版本更新后，按本流程从游戏文件重建兵种数据。
>
> 本文件只写**流程、判定原则、坑**：不写死路径（自行探测本机游戏安装位置），
> 不记录个案结论（某个单位为什么进黑名单之类的历史，见 `aoe3-battle.md` 的追加决议）。
>
> **权威性**：游戏数据是唯一权威，官方加强/削弱一律照搬；只处理「我们模型不适配」的问题。

---

## 1. 管线

```
Data.bar ──aoe3_bar_extractor──> raw/{protoy,techtreey,civs,stringtabley_*}.xml + raw/tactics/
ArtUnits.bar ──aoe3_anim_extractor──> raw/anims/                  (windup 数据源)
                                        │
      ┌─────────────────────────────────┼──────────────────────────────┐
      ▼                                 ▼                              ▼
aoe3_gamedata_parser          aoe3_upgrades_parser          aoe3_generic_techs_parser
  seeds/units.json              seeds/unit_upgrades.json      seeds/generic_techs.json
  seeds/i18n_zh.json
  data/aoe3/manifest.json

图形 BAR ──aoe3_icon_extractor──> resources/aoe3/icons/*.png + data/aoe3/icon_manifest.json
          ──compress_aoe3_icons──> 仅处理超 50KB 或非 128×128 的图
```

`raw/` 与派生 seeds 都入库 git；`resources/aoe3/icons/`（≈70MB）也入库。

---

## 2. 步骤

### 2.1 基线固化 + 生成物纯净度验证

1. 把 `seeds/aoe3/`、`data/aoe3/{manifest,icon_manifest}.json` 复制成临时基线（如 `data/aoe3/_prev/`，不入 git，跑完可删）。
2. **不动 `raw/`，重跑三个派生脚本**，然后 `git diff`：
   - 空（只差 `generated_at` 时间戳）→ 生成物是纯派生产物，后面可整体替换
   - 非空 → 有人手改过生成物，先查清原因并登记，否则会被这次刷新静默覆盖

这一步决定了「人工干预到底在哪一层」，是后面所有判断的前提，不要跳过。

### 2.2 灌库

```bash
# 主数据（覆盖写）
uv run python scripts/crawler/aoe3_bar_extractor.py --bar-path <Data.bar> --output-dir data/aoe3/raw

# anims：先移走旧的，再解（见下方「坑」）
uv run python scripts/crawler/aoe3_anim_extractor.py --art-bar <ArtUnits.bar>
```

- BAR 路径用参数/环境变量指定，**不要改源码里的默认值**（那只是某台机器的路径）。
- 对照 `manifest.json` 上一版：`tactics`/`anims` 文件数、protoy 字节数。
- 游戏侧删除的文件不会自动消失 → 清空 tactics/anims 目录再跑，避免残留。

### 2.3 重跑派生

```bash
uv run python scripts/crawler/aoe3_gamedata_parser.py
uv run python scripts/crawler/aoe3_upgrades_parser.py
uv run python scripts/crawler/aoe3_generic_techs_parser.py
```

### 2.4 出对比名单

```bash
uv run python scripts/aoe3_seed_diff.py --prev data/aoe3/_prev
```

产出报告（默认 `docs/aoe3-data-refresh-<日期>.md`）：新增/消失单位、**结构性变更**（代表动作变化）、
数值变更、**人工干预清单核查**、兵种池进出、单位改良/通用科技/图标变化、待决问题。

### 2.5 兼容核查（唯一需要判断的环节）

| 现象 | 处理原则 |
|---|---|
| 数值加强/削弱 | 照搬游戏，不干预 |
| 代表动作变化、攻击槽增删 | 先用 `aoe3_unit_probe.py` 看清是「游戏改了动作名」还是「parser 规则剔除」，再看既有同类单位怎么处理 → **不为了单个单位去改 parser 规则** |
| 新增单位数值极端 | 先用 `aoe3_unit_anomaly_scan.py` 找**同型在池先例**：有先例就与先例一致；无先例才考虑干预 |
| 需要排除/禁用 | 按既有三段语义选位置（见 §3），显式 id 枚举 + 中文标签 + 理由 |
| 人工清单里的 id 消失 | 清理并记录原因 |

底线：

- **不引入阈值型规则**（"hp > X 自动屏蔽"这类）；人工干预一律显式枚举，可审计。
- **先看先例**：与既有在池/在榜单位同型的，就同处理，避免规则膨胀。
- 改 parser 规则前评估连带影响（会波及多少既有单位）；宁可精确点名，不要放宽全局。
- **生成物（units.json 等）永不手改** —— 手改的内容会在下次刷新时丢失。

### 2.6 图标

```bash
uv run python scripts/crawler/aoe3_icon_extractor.py     # BAR 路径用环境变量指定
uv run python scripts/compress_aoe3_icons.py
```

- 核对 manifest 的 source 分布：`bar`（真实提取）/ `local_reuse`（本次 BAR 未解出、磁盘已有历史图，来源不可回溯）/ `variant_copy` / `missing`。
- 复核 `data/aoe3/icon_overrides.json`：用 `aoe3_icon_audit.py compare <unit> <target>` 做像素比对，
  确认覆盖是否仍必要（覆盖初衷通常是「BAR 解出的图不对」，图已修好就该解除）；解除的移入 `_resolved` 并记理由。
- 别被「上百个图标都更新了」误导：`aoe3_icon_audit.py diff --ref <旧 git rev>` 区分真换图与重新编码噪声。

### 2.7 验证

```bash
uv run pytest tests/ -q                     # 默认跳过 ra2 标记；改 ra2 时手动 -m ra2
uv run python scripts/aoe3_named_attack_audit.py
uv run python scripts/aoe3_damagecap_audit.py
uv run python scripts/aoe3_attack_slot_audit.py
uv run python scripts/aoe3_windup_research.py     # 需游戏 BAR
uv run python scripts/aoe3_battle_sim.py --random --seed 42      # 其余模式：--duel / --blacklist / --red X:N --blue Y:M
```

- 数据相关测试挂掉，多数是硬编码期望值过期 → 优先改成数据驱动断言。
- 抽样人工对照游戏内面板或社区数据站。

### 2.8 收尾

- `aoe3.md`：更新快照统计；`aoe3-battle.md`：追加决议（只记**结论 + 理由 + 影响**，不写流水账）。
- 提交拆分：raw / seeds / icons / 代码兼容 / 文档，便于单独回滚。

---

## 3. 人工干预点（位置清单）

| 位置 | 作用 | 刷新时注意 |
|---|---|---|
| `data/aoe3/icon_overrides.json` | 图标人工覆盖（`force_copy_from` / `block_wiki`） | 逐条复核是否仍必要 |
| `repository.py :: _EXCLUDED_IDS` + `is_excluded_unit()` | 全局排除（搜索 + 池都不出现）：召唤占位符 / 代币 / PVE 守护者 / 战役专属 | 规则型为主，新增命中项自动生效 |
| `lineup.py :: BLACKLIST` | 永久禁用（数据 broken、无法模拟） | 若数值被官方修正，应放回池子 |
| `lineup.py :: BATTLE_BLACKLIST` | 仅普通对战禁用（彩蛋 / 作弊 / 怪物级战役兵），黑名单乱斗可用 | 新增极端单位按同一分级标准纳入 |
| `aoe3_gamedata_parser.py` 攻击优先级表 | 代表动作选取（含「炮兵打兵优先」等） | 新动作名可能未覆盖 → 落兜底，需人工确认 |
| `aoe3_gamedata_parser.py :: TRAMPLE_ONLY_ATTACK_UNITS` | 只有「碾压」类动作的彩蛋单位放行 | 新增同类时追加 |
| `aoe3_upgrades_parser.py :: DIRTY_EFFECTS` | 点名丢弃离谱升级值（不用数值上限一刀切） | 科技改名/删除后规则失效 |
| `aoe3_gamedata_parser.py :: generate_i18n()` | 中文显示名来源（生成的 `i18n_zh.json` 不要手改） | 缺翻译补这里，不是补 json |

以上都由 `aoe3_seed_diff.py` 自动逐条核查并在报告里给出状态。

---

## 4. 坑

- **anims 增量跳过**：`aoe3_anim_extractor.py` 遇到已存在文件会跳过 → 不清空就永远拿不到改动后的 windup。
- **路径**：脚本默认路径可能写死了某台机器的盘符，用参数/环境变量覆盖，不要改源码。
- **生成物/manifest 曾被手工编辑**：历史上出现过手写的 `source` 值（代码里并不存在该取值）→ 一切以代码为准，手改物会被下次刷新覆盖。
- **文档与代码漂移**：文档描述的机制可能已被重构掉（曾出现文档记录的上限机制在代码中已不存在）→ 以代码为准，发现漂移顺手修文档。
- **pytest 默认跳过 ra2 标记**（约占全套测试 70% 时间）。

---

## 5. 工具

| 脚本 | 用途 |
|---|---|
| `scripts/aoe3_seed_diff.py` | 新旧快照对比 → 核实名单（核心） |
| `scripts/aoe3_unit_probe.py` | 某单位全部攻击动作 + parser 评分与最终选择 |
| `scripts/aoe3_unit_anomaly_scan.py` | 极端数值单位体检 + 同型在池先例 |
| `scripts/aoe3_icon_audit.py` | 图标像素比对 / 真换图 vs 重编码判定 |
| `scripts/aoe3_attack_slot_audit.py` | 因动作名跳过规则丢失攻击槽的审计 |
| `scripts/aoe3_named_attack_audit.py` | 具名攻击表 / 非 DPS 技能审计 |
| `scripts/aoe3_damagecap_audit.py` | 溅射池（damagecap）口径审计 |
| `scripts/aoe3_windup_research.py` | windup 取值核对（需游戏 BAR） |
