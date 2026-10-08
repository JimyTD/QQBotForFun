# 帝国3攻击动作列表与蓄力

- **Status**: WIP
- **Last Updated**: 2026-10-08
- **Owner**: @JimyTD
- **正式文档**: [../games/aoe3-battle.md](../games/aoe3-battle.md)

> 列表、出手、展示、国战角色，以及按动作名打到列表上的科技和时代改良，已经写进正式文档。本文只留还没做的，和还没对完的复查表。

## 两槽已退役

2026-10-08 收口：解析器不再写出远程、近战、攻城三槽，`Unit` 不再有这些字段，出手、战力、国战预估、战报 header、开发脚本全部只读 `attack_actions`。时代改良也不再生成按代表动作归桶的旧桶，只写按动作名的 `action_*`。此节原先记录的就是「停写两槽」，现已完成，无可继续项。

## 复查表（临时）

这张表对的是已经落地的那一版。船、不按名字排除、预备军换阵型，都还没进表。表先留着，按这些 id 对实际结果，对完再删。没出现的兵，从远处接敌的第一下和改之前相同。谁出生开、谁出生关以该原型的伤害包 `active` 为准，没写再看战术文件。下面和数据不符的格子已改过。

- 「从远处接敌」是还没贴上时会打出的那一包。
- 「钻进主武器最小射程后」是敌人已经冲进主武器打不着的距离，这时不后退，改用盖得住的下一条。
- 「满条」是蓄力条满的那一下。冷却结束前回到普通攻击。
- 「研究对应科技后」只在这场已经套了该科技时发生。

### 蓄力和普通攻击都会变

| 单位 | id | 现在 | 改后、还没研究科技 | 研究对应科技后 | 复查 |
|---|---|---|---|---|---|
| 强盗 | `desaloonbandido` | RangedAttack 20远程 12–18；HandAttack 12近战 0–1.75 | 钻进主武器最小射程后：打不着，会继续靠近 → 20远程 2–12；满条 DynamiteAttackCharge 17攻城 0–12 溅射3，冷却 30 秒 | — | — |
| 间谍 | `xpspy` | RangedAttack 15远程 2–12；MeleeHandAttack 5近战 0–1.75 | 卡宾、手枪的伤害包是 active=0，普通射击在战术里关着。从远处靠近打近战 5 | 打到 xpSpy 的 ActionEnable 才打开对应那一击。诺尔顿大陆军游骑兵或 DEIndependenceUnitedStates 打开普通射击 | — |
| 随军神父 | `depadre` | VolleyRangedAttack 10远程 2–16；HandAttack 5近战 0–1.75 | 枪在战术里关着，重击的伤害包是 active=0。从远处靠近打刺刀 5 | DEColonializeMexicans：枪打开，从 16 码射击 | — |

### 多出出生即开的蓄力

冷却写着「空」的蓄力留在列表里，这一期不自动打出。

| 单位 | id | 现在 | 改后、还没研究科技 | 研究对应科技后 | 复查 |
|---|---|---|---|---|---|
| 加洛格拉什 | `demercgallowglass` | MeleeHandAttack 30近战 0–1.75 溅射2 | 满条 ChargeSwashbucklerAttack 50近战 0–1.75 溅射2，冷却 36 秒 | — | — |
| 哥萨克蛮兵 | `desaloonoutlawcossack` | VolleyRangedAttack 22远程 2–12；HandAttack 14近战 0–1.75 | 满条 KnifeChargeAttack 22远程 2–16，冷却空 | — | 冷却字段是空的 |
| 哥萨克蛮兵 | `desaloonoutlawcossackrider` | MeleeHandAttack 17近战 0–1.75 | 满条 LanceChargeAttack 34近战 0–2 溅射2，冷却空 | — | 冷却字段是空的 |
| 国土佣仆 | `merclandsknecht` | MeleeHandAttack 43近战 0–1.75 | 满条 ChargeSwashbucklerAttack 43近战 0–1.75 溅射2，冷却 15 秒 | — | — |
| 大师 | `degrandmaster` | VolleyRangedAttack 12远程 2–16；HandAttack 6近战 0–1.75 | 卡宾和重击的伤害包是 active=0，关着。从远处仍是齐射 12，2–16 | — | — |
| 将军 | `degeneral` | VolleyRangedAttack 12远程 2–16；HandAttack 6近战 0–1.75 | 卡宾和重击的伤害包是 active=0，关着。从远处仍是齐射 12，2–16 | — | — |
| 将军 | `degeneral2` | VolleyRangedAttack 12远程 2–16；HandAttack 6近战 0–1.75 | 卡宾和重击的伤害包是 active=0，关着。从远处仍是齐射 12，2–16 | — | — |
| 拦路强盗 | `desaloonhighwayman` | RangedAttack 12远程 2–12；HandAttack 15近战 0–1.5 | 满条 ChargeShootoutAttack 12远程 2–12 ×3发，冷却 60 秒 | — | — |
| 拦路强盗 | `desaloonhighwaymanrider` | RangedAttack 16远程 0–12；HandAttack 6近战 0–1.75 | 满条 BullseyeChargeAttack 36远程 0–16，冷却 60 秒 | — | 贴脸 HandAttack 6近战 0–1.75 → 16远程 0–12 |
| 教宗护卫 | `depapalguard` | MeleeHandAttack 13近战 0–2 | 满条 ChargeHalberdAttack 13近战 3–5 溅射1，冷却 60 秒 | 教宗兵工厂：蓄力 ChargePistolAttack 26远程 7–12 | — |
| 民兵军官 | `despcmilitiaofficer` | VolleyRangedAttack 15远程 2–16；HandAttack 6近战 0–1.75 | 满条 ChargeCarbineAttack 60远程 2–20，冷却 45 秒。重击的伤害包是 active=0，关着 | — | — |
| 波斯尼亚兵 | `demercbosniak` | MeleeHandAttack 45近战 0–3 | 满条 LanceChargeAttack 67.5近战 0–3 溅射2，冷却 60 秒 | — | — |
| 流浪的国土佣仆 | `despcoutlawlandsknecht` | MeleeHandAttack 54近战 0–1.75 | 满条 ChargeSwashbucklerAttack 54近战 0–1.75 溅射2，冷却 15 秒 | — | — |
| 牛仔 | `desalooncowboy` | RangedAttack 20远程 0–12；HandAttack 9近战 0–1.75 | 满条 BullseyeChargeAttack 30远程 0–16，冷却 40 秒 | — | 贴脸 HandAttack 9近战 0–1.75 → 20远程 0–12 |
| 牲畜盗贼 | `desaloonvaquero` | RangedAttack 20远程 0–12；HandAttack 11近战 0–1.75 | 满条 LassoAttackCharge 18远程 2–12 溅射1，冷却 30 秒 | — | 贴脸 HandAttack 11近战 0–1.75 → 20远程 0–12 |
| 皇家火枪兵 | `denatmercroyalmusketeer` | VolleyRangedAttack 22远程 2–12；VolleyHandAttack 20近战 0–1.75 | 满条 ChargePistolAttack 44远程 0–12，冷却 60 秒 | 拿破仑时代：蓄力 MortarAttack 20攻城 2–14 溅射2 | — |
| 皇家火枪兵 | `denatroyalmusketeer` | VolleyRangedAttack 22远程 2–12；VolleyHandAttack 20近战 0–1.75 | 满条 ChargePistolAttack 44远程 0–12，冷却 60 秒 | 拿破仑时代：蓄力 MortarAttack 20攻城 2–14 溅射2 | — |
| 神射手 | `debersagliere` | VolleyRangedAttack 16远程 2–20；VolleyHandAttack 5.5近战 0–1.75 | 满条 ChargeStun 16远程 0–25，冷却空 | — | 冷却字段是空的 |
| 穆赫比尔 | `despyottoman` | MeleeHandAttack 5近战 0–1.75 | 卡宾和手枪的伤害包是 active=0，关着。从远处靠近打近战 5 | — | — |
| 突击骑士 | `denatmercshockrider` | MeleeHandAttack 25近战 0–1.75 | 满条 LanceChargeAttack 37.5近战 0–2 溅射3，冷却 60 秒 | — | — |
| 突击骑士 | `denatshockrider` | MeleeHandAttack 25近战 0–1.75 | 满条 LanceChargeAttack 37.5近战 0–2 溅射3，冷却 60 秒 | — | — |
| 维斯瓦马刀骑兵 | `deindependencepolishlancer` | MeleeHandAttack 28近战 0–1.75 | 长矛的伤害包是 active=0，关着，冷却也是空的。从远处仍是近战 28 | — | — |
| 维斯瓦马刀骑兵 | `derevpolishlancer` | MeleeHandAttack 28近战 0–1.75 | 长矛的伤害包是 active=0，关着，冷却也是空的。从远处仍是近战 28 | — | — |
| 翼骑兵 | `despcwingedhussar` | MeleeHandAttack 27.5近战 0–3.75 溅射1 | 满条 LanceChargeAttack 41.25攻城 0–2 溅射3，冷却 60 秒 | — | — |
| 翼骑兵 | `dewingedhussar` | MeleeHandAttack 30近战 0–3.75 | 满条 LanceChargeAttack 30攻城 0–2 溅射3，冷却 60 秒 | — | — |
| 莱纳佩战士 | `denatmerclenaperifleman` | VolleyRangedAttack 20远程 2–14；VolleyHandAttack 15近战 0–1.75 | 满条 ChargeStun 30远程 2–14，冷却 40 秒 | — | — |
| 莱纳佩战士 | `denatspclenaperifleman` | VolleyRangedAttack 20远程 2–14；VolleyHandAttack 15近战 0–1.75 | 满条 ChargeStun 30远程 2–14，冷却 40 秒 | — | — |
| 骷髅武士 | `xpskullknight` | MeleeHandAttack 20近战 0–1.75 溅射2 | 满条 ObsidianChargeAttack 30近战 0–2 溅射4，冷却 15 秒 | — | — |
| 骷髅轻骑兵 | `denatmerctotenkopf` | MeleeHandAttack 27近战 0–1.75 | 满条 DeathStrikeChargeAttack 54近战 0–1.75，冷却空 | — | 冷却字段是空的 |
| 骷髅轻骑兵 | `denattotenkopf` | MeleeHandAttack 27近战 0–1.75 | 满条 DeathStrikeChargeAttack 54近战 0–1.75，冷却空 | — | 冷却字段是空的 |
| 骷髅轻骑兵护卫 | `detotenkopf` | MeleeHandAttack 27近战 0–1.75 | 满条 DeathStrikeChargeAttack 54近战 0–1.75，冷却空 | — | 冷却字段是空的 |

### 普通攻击会变

木制假炮带 `InflictsNoDamage`，不写列表。40 伤和现在入库的 500 伤都不是实战输出。固定炮仍是 300 伤，打人用 14–34、溅射 5 的主炮；60 码那发只打船和建筑。间谍、随军神父的枪和蓄力按数据关着，没套上对应科技时只剩近战。叛乱者、海盗出生在近战阵型，枪不在这份列表里。

| 单位 | id | 现在 | 改后、还没研究科技 | 研究对应科技后 | 复查 |
|---|---|---|---|---|---|
| 叛乱者 | `deinsurgente` | VolleyRangedAttack 15远程 5–12；MeleeHandAttack 10近战 0–2 | 从远处接敌：VolleyRangedAttack 15远程 5–12 → 10近战 0–2（VolleyRangedAttack → MeleeHandAttack） | 尤卡坦州：蓄力 LassoChargeAttack 15远程 2–12 溅射2；预备军：现在的主武器 VolleyRangedAttack 15远程 5–12 | — |
| 叛兵 | `saloonoutlawrifleman` | RangedAttack 20远程 2–12；HandAttack 12近战 0–1.75 | 从远处接敌：RangedAttack 20远程 2–12 → 20远程 12–18（RangedAttack → LongRangedAttack） | 雇佣逃犯 或 美国起始点亮的酒馆蓄力 或 强盗：蓄力 BuckshotChargeAttack 3远程 2–18 溅射2 ×6发 | — |
| 固定炮 | `demaltesegun` | LongRangeAttack 300攻城 14–60 溅射1 | 从远处接敌：LongRangeAttack 300攻城 14–60 溅射1 → 300攻城 14–34 溅射5（LongRangeAttack → CannonAttack） | — | — |
| 拿破仑炮 | `demercnapoleongun` | CannonAttack 75攻城 11.5–23 溅射2 | 钻进主武器最小射程后：打不着，会继续靠近 → 7.5攻城 0–11.5 溅射3 ×7发 | — | — |
| 木制假炮 | `dequakergun` | MortarAttack 500攻城 4–40 溅射1 | 不写攻击列表。40 和 500 都不是实战输出 | — | — |
| 沙漠步弓手 | `deoutlawdesertarcher` | VolleyRangedAttack 20远程 16–22；MeleeHandAttack 12近战 0–1.75 | 钻进主武器最小射程后：打不着，会继续靠近 → 12远程 2–16 | — | — |
| 海盗 | `saloonpirate` | RangedAttack 15远程 6–20；HandAttack 16近战 0–1.75 | 从远处接敌：RangedAttack 15远程 6–20 → 16近战 0–1.75（RangedAttack → HandAttack） | 私掠许可证：现在的主武器 RangedAttack 15远程 6–20 | — |
| 逃犯 | `desaloonowlhoot` | RangedAttack 20远程 2–12；HandAttack 12近战 0–1.75 | 从远处接敌：RangedAttack 20远程 2–12 → 20远程 12–18（RangedAttack → LongRangedAttack） | — | 霰弹的伤害包是 active=1，出生开着 |
| 鱼叉手 | `desaloonharpooner` | RangedAttack 20远程 2–14 溅射0.25；HandAttack 14近战 0–1.75 | 钻进主武器最小射程后：打不着，会继续靠近 → 15攻城 0–14 溅射1 | — | — |

### 套科技才变

没研究之前，这些兵和现在相同。原住民村民、骑射手虽然写着科技打开「现在的主武器」，但没研究时接敌数字不变，阵型里已经有另一条开着的同等攻击。加特林机枪出生开着的是 6 发炮击，连射关着。不要把他们和间谍算成同一类。

| 单位 | id | 现在 | 改后、还没研究科技 | 研究对应科技后 | 复查 |
|---|---|---|---|---|---|
| 伙伴骑兵 | `denatcompanion` | MeleeHandAttack 17攻城 0–1.75 | 稳态与现在相同 | 猎熊长矛：蓄力 LanceChargeAttack 28攻城 0–2 溅射1 | — |
| 伙伴骑兵 | `denatmerccompanion` | MeleeHandAttack 17攻城 0–1.75 | 稳态与现在相同 | 猎熊长矛：蓄力 LanceChargeAttack 28攻城 0–2 溅射1 | — |
| 克里追踪者 | `natmerctracker` | VolleyRangedAttack 13远程 2–16；VolleyHandAttack 9近战 0–1.75 | 稳态与现在相同 | 密歇根志愿狙击手 1 团：蓄力 EagleEyeChargeAttack 13远程 2–25 溅射2 | — |
| 克里追踪者 | `nattracker` | VolleyRangedAttack 13远程 2–16；VolleyHandAttack 9近战 0–1.75 | 稳态与现在相同 | 密歇根志愿狙击手 1 团：蓄力 EagleEyeChargeAttack 13远程 2–25 溅射2 | — |
| 加特林机枪 | `xpgatlinggun` | RepeatingAttack 30攻城 0–24 溅射2 | 出生是 CannonAttack 30攻城 0–24 溅射2 ×6 发。RepeatingAttack 关着 | 咖啡磨机枪：关掉炮击，打开 RepeatingAttack 30攻城 0–24 溅射2 | — |
| 匈牙利掷弹兵 | `denathungariangrenadier` | VolleyRangedAttack 16攻城 2–18 溅射3；MeleeHandAttack 24近战 0–2 溅射1 | 稳态与现在相同 | DEHandMortarHungarianGrenadierShadow 或 榴弹发射器：模式 MortarAttack 16攻城 4–20 溅射3 | — |
| 医院骑士团骑士 | `dehospitaller` | MeleeHandAttack 20近战 0–1.75 溅射1 | 稳态与现在相同 | 达官贵人：蓄力 ChargePistolAttack 40远程 2–14 | — |
| 卫士 | `demaltesemusketeer` | VolleyRangedAttack 23远程 2–13；MeleeHandAttack 18近战 0–1.75 | 稳态与现在相同 | 燧发火箭炮：模式 RocketAttack 18.4攻城 0–14 溅射1 | — |
| 墨西哥士兵 | `desoldado` | VolleyRangedAttack 36远程 2–12；VolleyHandAttack 25近战 0–1.75 | 稳态与现在相同 | 旧枪新用：模式 MortarAttack 28.8攻城 0–14 溅射1 | — |
| 年轻守卫 | `ypconsulateyounggarde` | VolleyRangedAttack 16攻城 2–12 溅射3；MeleeHandAttack 24近战 0–2 溅射1 | 稳态与现在相同 | 老年守卫：模式 MortarAttack 16攻城 4–14 溅射3 | — |
| 扎纳塔骑兵 | `demerczenata` | BowAttack 27远程 2–14 | 稳态与现在相同 | 柏柏尔幻想曲：蓄力 ChargeMusketAttack 35远程 0–15 | — |
| 掷弹兵 | `delegiongrenadier` | VolleyRangedAttack 16攻城 2–12 溅射3；MeleeHandAttack 24近战 0–2 溅射1 | 稳态与现在相同 | 明治维新 或 华盛顿军团 或 华盛顿大陆军掷弹兵 或 DEIndependenceUnitedStates：模式 MortarAttack 16攻城 3–14 溅射3 | — |
| 掷弹兵 | `grenadier` | VolleyRangedAttack 16攻城 2–12 溅射3；MeleeHandAttack 24近战 0–2 溅射1 | 稳态与现在相同 | 老年守卫 或 名英国掷弹兵 或 榴弹发射器：模式 MortarAttack 16攻城 4–14 溅射3 | — |
| 教宗祖阿夫兵 | `denmpapalzouave` | VolleyRangedAttack 32远程 2–20；VolleyHandAttack 20近战 0–1.75 | 稳态与现在相同 | 教宗兵工厂：蓄力 ChargeCarbineAttack 64远程 2–25 | — |
| 教宗重型火炮 | `denmpapalbombard` | CannonAttack 430攻城 0–28 溅射4 | 稳态与现在相同 | 教宗兵工厂：蓄力 ChargedCannonAttack 430攻城 0–28 溅射7 | — |
| 教宗长矛骑兵 | `denmpapalelmetto` | MeleeHandAttack 30近战 0–1.75 | 稳态与现在相同 | 教宗兵工厂：蓄力 LanceChargeAttack 60近战 0–4 溅射2 | — |
| 村民 | `settlernative` | BlunderbussAttack 3远程 2–12；HandAttack 10近战 0–2 | 稳态与现在相同 | WesterniseNatives 或 山背拓荒者：现在的主武器 BlunderbussAttack 3远程 2–12 | — |
| 枪手 | `saloonoutlawpistol` | RangedAttack 15远程 2–12；HandAttack 12近战 0–1.5 | 稳态与现在相同 | 雇佣持枪杀手 或 美国起始点亮的酒馆蓄力 或 法外之徒：蓄力 ChargeQuickDrawAttack 15远程 2–12 ×3发 | 有蓄力标记但 protoy 没伤害包：ChargeShootoutAttack |
| 柏柏尔苏丹 | `denatberbersultan` | MeleeHandAttack 30近战 0–1.75 | 稳态与现在相同 | 柏柏尔幻想曲：蓄力 ChargeMusketAttack 60远程 0–15 | — |
| 柏柏尔骆驼骑兵 | `denatcamelrider` | MeleeHandAttack 22近战 0–1.75 | 稳态与现在相同 | 柏柏尔幻想曲：蓄力 ChargeMusketAttack 24远程 0–15 | — |
| 柏柏尔骆驼骑兵 | `denatmerccamelrider` | MeleeHandAttack 22近战 0–1.75 | 稳态与现在相同 | 柏柏尔幻想曲：蓄力 ChargeMusketAttack 24远程 0–15 | — |
| 正规军 | `deregular` | VolleyRangedAttack 25远程 2–14；VolleyHandAttack 14近战 0–1.75 | 稳态与现在相同 | DERefurbishedFirearmsTexasShadow：模式 MortarAttack 22远程 0–16 溅射1 | — |
| 游击叛兵 | `dechinaco` | MeleeHandAttack 25近战 0–2.75 | 稳态与现在相同 | 德克萨斯长矛骑兵 或 驻防长矛骑兵：蓄力 LanceChargeAttack 25近战 0–3.75 溅射2 | — |
| 火兵 | `ypmercarsonist` | VolleyRangedAttack 42攻城 2–12 溅射3；VolleyHandAttack 22攻城 0–2 | 稳态与现在相同 | 火箭炮手：模式 RocketAttack 42攻城 12–20 溅射3 | — |
| 火焰兵 | `dehoopthrower` | GrenadeAttack 16攻城 4–16 溅射2；HandAttack 12近战 0–2 | 稳态与现在相同 | 火箭炮：模式 RocketAttack 22攻城 16–22 溅射2；喷火器：蓄力 FlameThrowerAttack 5攻城 2–10 溅射4 | — |
| 皮革加农炮 | `deleathercannon` | CannonAttack 40攻城 0–21 溅射2 | 稳态与现在相同 | 榴霰弹会把 CaseShotAttack 打开，但主炮最小射程是 0、优先级更高，仍打主炮 | 打开后选不到 |
| 短枪商人骑兵 | `saloonoutlawrider` | RangedAttack 20远程 0–12；HandAttack 11近战 0–1.75 | 稳态与现在相同 | 雇佣牛仔 或 美国起始点亮的酒馆蓄力 或 牲畜盗贼：蓄力 BullseyeChargeAttack 30远程 0–16 | 贴脸 HandAttack 11近战 0–1.75 → 20远程 0–12 |
| 重型加农炮 | `cannon` | CannonAttack 200攻城 0–28 溅射4 | 稳态与现在相同 | 榴霰弹会把 CaseShotAttack 打开，但主炮最小射程是 0、优先级更高，仍打主炮 | 打开后选不到 |
| 铁帽炮兵 | `dehumbaraci` | VolleyRangedAttack 18攻城 4–14 溅射2；MeleeHandAttack 28近战 0–2 | 稳态与现在相同 | 榴弹发射器：模式 MortarAttack 18攻城 4–16 溅射2 | — |
| 长管炮 | `culverin` | CannonAttack 40攻城 0–34 溅射1 | 稳态与现在相同 | 榴霰弹会把 CaseShotAttack 打开，但主炮最小射程是 0、优先级更高，仍打主炮 | 打开后选不到 |
| 马炮兵 | `xphorseartillery` | CannonAttack 125攻城 0–26 溅射3 | 稳态与现在相同 | 榴霰弹会把 CaseShotAttack 打开，但主炮最小射程是 0、优先级更高，仍打主炮 | 打开后选不到 |
| 骑射手 | `cavalryarcher` | VolleyRangedAttack 13远程 0–12；GuardianAttack 6.5近战 0–1.75 | 稳态与现在相同 | 飞天箭矢 或 比洛茨克瓦兵团：现在的主武器 VolleyRangedAttack 13远程 0–12 | 贴脸 GuardianAttack 6.5近战 0–1.75 → 13远程 0–12 |
| 鹰炮 | `falconet` | CannonAttack 100攻城 0–26 溅射3 | 稳态与现在相同 | 榴霰弹会把 CaseShotAttack 打开，但主炮最小射程是 0、优先级更高，仍打主炮 | 打开后选不到 |

### 战术文件里关着的几条

没伤害包的不收录。开没开只看这个原型自己的 `active`：伤害包写成 1 就出生开着，战术文件是 0 也不关掉。同类兵有卡，不会打开没被点名的原型。

| 单位 | id | 现在 | 改后、还没研究科技 | 研究对应科技后 | 复查 |
|---|---|---|---|---|---|
| 亲随 | `denatmerctrabant` | MeleeHandAttack 22近战 0–2 | 满条 ChargePistolAttack 30远程 0–12，冷却 60 秒 | — | 伤害包 active=1 |
| 亲随 | `denattrabant` | MeleeHandAttack 22近战 0–2 | 满条 ChargePistolAttack 30远程 0–12，冷却 60 秒 | — | 伤害包 active=1 |
| 俄国骑射手 | `deconsulatedvoryanin` | VolleyRangedAttack 13远程 0–12 | 稳态与现在相同 | — | 默认关、没有打到这个原型的开关：VolleyRangedAttack |
| 墨西哥士兵 | `deconsulatesoldado` | VolleyRangedAttack 36远程 2–12；VolleyHandAttack 25近战 0–1.75 | 稳态与现在相同 | — | 默认关、没有打到这个原型的开关：MortarAttack |
| 奥罗莫战士 | `deoromowarrior` | MeleeHandAttack 30近战 0–1.75 | 满条 ChargeMusketAttack 34远程 4–12，冷却 60 秒 | — | 伤害包 active=1 |
| 归化的短枪商人骑兵 | `yprepentantoutlawrider` | RangedAttack 16远程 0–12；HandAttack 7近战 0–1.75 | 稳态与现在相同 | — | 有蓄力标记但 protoy 没伤害包：BullseyeChargeAttack；贴脸 HandAttack 7近战 0–1.75 → 16远程 0–12 |
| 扈从骑兵 | `delithuanianrider` | MeleeHandAttack 22近战 0–1.75 | 稳态与现在相同 | — | 默认关、没有打到这个原型的开关：ChargeMusketAttack |
| 持枪杀手 | `desaloongunslinger` | RangedAttack 15远程 2–12；HandAttack 12近战 0–1.5 | 满条 ChargeQuickDrawAttack 15远程 2–12 ×3发，冷却 30 秒 | — | ChargeShootoutAttack 没有伤害包，不收录。拔枪是伤害包 active=1 |
| 村民 | `denatspclenapevillager` | BlunderbussAttack 3远程 2–12；HandAttack 10近战 0–2 | 稳态与现在相同 | — | 默认关、没有打到这个原型的开关：BlunderbussAttack |
| 条顿骑士 | `derevteutonicknight` | MeleeHandAttack 35近战 0–1.75 溅射2 | 稳态与现在相同 | — | 有蓄力标记但 protoy 没伤害包：ChargePistolAttack |
| 水手 | `desaloonsailor` | RangedAttack 15远程 2–12 溅射1；HandAttack 10近战 0–1.75 | 满条 BuckshotChargeAttack 3远程 2–14 溅射3 ×6发，冷却 30 秒 | — | 伤害包 active=1 |
| 法外之徒 | `desaloondesperado` | RangedAttack 15远程 2–12；HandAttack 12近战 0–1.5 | 满条 ChargeShootoutAttack 15远程 2–14 ×3发，冷却 30 秒 | — | ChargeQuickDrawAttack 没有伤害包，不收录。对射是伤害包 active=1 |
| 皇家火绳枪兵 | `denatmercroyalarquebusier` | VolleyRangedAttack 12远程 2–15；VolleyHandAttack 8近战 0–1.75 | 稳态与现在相同 | — | 有蓄力标记但 protoy 没伤害包：EagleEyeChargeAttack |
| 皇家火绳枪兵 | `denatroyalarquebusier` | VolleyRangedAttack 12远程 2–15；VolleyHandAttack 8近战 0–1.75 | 稳态与现在相同 | — | 有蓄力标记但 protoy 没伤害包：EagleEyeChargeAttack |
| 骑士兄弟团 | `derevknightbrother` | MeleeHandAttack 24近战 0–1.75 | 满条 LanceChargeAttack 50近战 0–4 溅射2，冷却 60 秒 | — | 伤害包 active=1 |

### 船（旧对照，不是方案）

船按 `Normal` 写列表，规则在「列表里收什么」。远炮优先级更低但已经够得着时，停在远炮。下面是误用陆地齐射 / 架炮规则时的旧对照，不按这张表改。

| 单位 | id | 现在 | 改后、还没研究科技 | 研究对应科技后 | 复查 |
|---|---|---|---|---|---|
| ypFishingBoatIndians | `ypfishingboatindians` | RangedAttack 8远程 0–20 | 从远处接敌：RangedAttack 8远程 0–20 → 打不着（这条在战术里 active=0） | — | 默认关、没有打到这个原型的开关：RangedAttack |
| 加农炮船 | `decannonboat` | LongRangeAttack 80攻城 0–40 溅射3 | 从远处接敌：LongRangeAttack 80攻城 0–40 溅射3 → 140攻城 0–20 溅射1（LongRangeAttack → RangedAttack） | — | — |
| 单桅战船 | `desloop` | RangedAttack 110攻城 0–22 溅射1 | 满条 ChargeBroadsideAttack 34攻城 0–20 溅射1，冷却 60 秒 | — | — |
| 卡拉维尔战舰 | `caravel` | LongRangeAttack 100攻城 0–40 溅射4 | 从远处接敌：LongRangeAttack 100攻城 0–40 溅射4 → 75攻城 0–20 溅射1（LongRangeAttack → RangedAttack） | — | — |
| 战列舰 | `demercbattleship` | LongRangeAttack 200攻城 0–64 溅射8 | 从远处接敌：LongRangeAttack 200攻城 0–64 溅射8 → 35攻城 0–32 溅射1（LongRangeAttack → RangedAttack） | — | 默认关、没有打到这个原型的开关：LongRangeAttack |
| 捕鱼独木舟 | `defishingboatafrican` | RangedAttack 8远程 0–20 | 从远处接敌：RangedAttack 8远程 0–20 → 打不着（这条在战术里 active=0） | 河流小规模战斗：现在的主武器 RangedAttack 8远程 0–20 | — |
| 渔船 | `fishingboat` | RangedAttack 8远程 0–20 | 从远处接敌：RangedAttack 8远程 0–20 → 打不着（这条在战术里 active=0） | 武装渔夫：现在的主武器 RangedAttack 8远程 0–20 | — |
| 渔船 | `ypfishingboatasian` | RangedAttack 8远程 0–20 | 从远处接敌：RangedAttack 8远程 0–20 → 打不着（这条在战术里 active=0） | 武装渔夫：现在的主武器 RangedAttack 8远程 0–20 | — |
| 炮舰 | `degunboat` | LongRangeAttack 80攻城 0–40 溅射3 | 从远处接敌：LongRangeAttack 80攻城 0–40 溅射3 → 25攻城 0–16 溅射1（LongRangeAttack → RangedAttack） | 炮舰 或 炮舰战术 或 群岛舰队：现在的主武器 LongRangeAttack 80攻城 0–40 溅射3 | — |
| 装甲军舰 | `xpironclad` | LongRangeAttack 200攻城 0–80 溅射6 | 从远处接敌：LongRangeAttack 200攻城 0–80 溅射6 → 115攻城 0–30 溅射1（LongRangeAttack → RangedAttack） | — | — |
| 谢贝克帆船 | `demercxebec` | RangedAttack 180攻城 16–32 溅射1 | 钻进主武器最小射程后：打不着，会继续靠近 → 60攻城 0–16 溅射1 | — | — |
| 迫击炮战船 | `monitor` | LongRangeAttack 200攻城 0–70 溅射10 | 从远处接敌：LongRangeAttack 200攻城 0–70 溅射10 → 80攻城 0–36 溅射3（LongRangeAttack → MortarAttack） | — | — |

### 贴脸才不同

从远处接敌的第一下不变。远程最小射程是 0，贴脸时现在会改砍，按优先级会继续打远程。伤害类型会变的只有这几个：

| 单位 | id | 贴脸现在 | 贴脸改后 |
|---|---|---|---|
| 加特林骆驼 | `demercgatlingcamel` | 22 近战 | 14.5 攻城，6 发 |
| 加特林骆驼 | `legacygatlingcamel` | 1 近战 | 150 攻城，6 发 |
| 槌兵 | `demaceman` | 36 近战 | 72 攻城 |
| 三桅帆装军舰 | `degalleass` | 400 近战，溅射 3 | 40 攻城。上一版没给船写列表 |

其余约 26 个是枪骑兵、火枪骑兵、保镖、黑骑士、骆驼骑兵、象轿兵、阿帕切骑兵、鞑靼弓手、西班牙征服者这一类：贴脸从刀换成同一套远程，接敌仍是那套远程。`dragoon`、`ruyter`、`ypmercyojimbo` 可以当代表。远程最小射程不是 0 的火枪兵不在这里，贴脸仍用刺刀。
