# 帝国3攻击动作列表与蓄力

- **Status**: WIP
- **Last Updated**: 2026-10-08
- **Owner**: @JimyTD
- **正式文档**: [../games/aoe3-battle.md](../games/aoe3-battle.md)

> 2026-10-08 收口：正式文档 [../games/aoe3-battle.md](../games/aoe3-battle.md) 已按攻击模式列表口径更新，并记录了查看器的蓄力/攻击动作导出字段。本文保留为这一期的完整方案与复查表。
>
> 列表、出手认目标、换初始阵型已经进代码。模拟器在单位带了攻击模式列表时按列表出手；列表为空的兵仍走两槽。两槽字段还在写出，见「还没写进代码」。



2026-09-30 对 `seeds/aoe3/units.json` 的 815 个战斗单位，对照 `data/aoe3/raw/protoy.xml`、`tactics/`、`techtreey.xml` 核对。伤害以 protoy 为准。

## 方案

每个兵保存**默认阵型**里的攻击模式列表。一条模式是一整包：伤害、伤害类型、射程、攻速、溅射、弹丸、抬手、倍率。射程不同就是另一条模式，和主武器一起留下。打建筑、打船、打守护者、砸箱子的也留在列表里，不在写入时删掉。出手见下面「出手」。

蓄力也是这种模式，数据同样是一整包。它多出来的只有两件事：战术里它的优先级通常更高，以及要等蓄力条满了才进候选。打出一次后进入冷却，冷却期间它不在候选里，其余模式照常按优先级和距离选。标记是战术动作上的 `<chargeaction>1</chargeaction>`，少数是 `<auxchargeaction>`。

`<active>0</active>` 的模式留在列表里，但先不参加挑选，不管它是不是蓄力。已套用科技用 `ActionEnable` 按动作名把它打开或关掉。间谍的普通射击、鹰炮的霰弹、掷弹兵的迫击、柏柏尔的蓄力火枪，都是这一扇门。叛乱者的齐射还要先把阵型换成齐射，枪不在出生的近战阵型里。

科技里按动作名写的伤害、射程、攻速、倍率，落到同名的那一条模式上。

## 列表里收什么

出生只取一份阵型。单位写了 `<initialtactic>` 就用它。没写的，同时有架炮前和架炮后就用架炮后；否则有齐射用齐射，没有就交错，再没有就近战；这些都没有，就用第一份不是架炮前、潜行、掩护、防御的阵型。船因此落到 `Normal`。

写了初始阵型、并且会进斗蛐蛐的，是酒馆海盗和叛乱者（近战）、酒馆亡命徒（近战，和上面的取法相同）。木制假炮写的是加特林伪装，但单位带 `InflictsNoDamage`，不写列表。17 份带架炮前的战术都没有把初始阵型写成别的，炮兵列表仍是架好之后的 Bombard。架炮前不能开火、架好才打，照旧。

这一份阵型里的攻击都留下，打建筑、打船、打守护者、砸箱子的也留。不按动作名删除。没标 `chargeaction` / `auxchargeaction` 的 Charge 是普通攻击，作弊单位很强也按数据收。骑兵的碾压在另一份 `Trample` 阵型里，出生阵型没有，不收。四辆彩蛋卡车那一击的类型是 `TruckAttack`，写了 `attackaction=1`，在它们的近战阵型里，要收。

不收的只有这三类：

- `type` 不是攻击，并且没有 `attackaction=1`。治疗、自动采集、`CastPower`。
- protoy 没有同名伤害包，或伤害小于等于 0。不拿战术文件的伤害来补。科技里的百分比和 `DamageMultiplier` 只放大已有的包，没有包就没有底数。这些是数据没做完：条顿骑士的 `ChargePistolAttack`、皇家火绳枪兵的 `EagleEyeChargeAttack`、枪手和持枪杀手的 `ChargeShootoutAttack`、归化短枪商人骑兵的 `BullseyeChargeAttack`、法外之徒的 `ChargeQuickDrawAttack`。
- 单位带 `InflictsNoDamage`。木制假炮不写列表。它的伪装炮写了 `hidefromstats`，目标却是 `All`，不能只看打谁。

`active=0` 的留下，关掉，等已经套上的科技打开。单位伤害包上如果写了 `active`、`chargeaction`、`auxchargeaction`，以伤害包为准，共享战术文件让路。

已套用科技如果写了 `InitialTactic`，这名兵改用那一份阵型的攻击列表。预备军 `DEHCReservistas` 把叛乱者从近战换成齐射，`VolleyRangedAttack` 只在齐射阵型里，同一条科技再把它打开。私掠许可证 `DEHCREVLetterOfMarque` 把酒馆海盗同样换成齐射，并打开 `RangedAttack`。换列表之后再套用同一条科技里的 `ActionEnable`。预备军的 XML 是先写打开枪、后写换阵型；先打开再整份换成齐射，枪会按 `active=0` 重新关掉。

间谍的取法已经是齐射，诺尔顿大陆军游骑兵再把初始阵型设成齐射，列表不变，只是把枪打开。管风琴的葡萄弹把初始阵型设成 Bombard，列表本来就是这份。木制假炮没有列表。修道院、大学、议会、社区广场不进斗蛐蛐。

玩家在齐射、交错、防御、掩护之间来回切，这次不做。葡萄弹还会把管风琴的 Limber 关掉，架炮进场这次不改。

## 出手

1. 已打开、伤害大于 0、射程盖住当前距离，才进候选。蓄力还要条是满的，而且冷却大于 0。
2. `<rate type>` 对不上当前目标的不进候选。长矛兵贴脸因此不会打出攻城攻击。木制牛的攻城目标写成了 `All`，按数据打得到人，这一下照收。它是彩蛋，进对战黑名单，只在乱斗里出场。这是斗蛐蛐的出场规则，不改攻击数据。
3. 候选里取优先级最高的一条。优先级是战术文件里这份阵型给该动作写的 `priority`，例如 `<action priority="100">`。没写就是 0。两槽代表动作用的那套名字排序不进这里。
4. 已经有一条盖住当前距离，就站住，不为了优先级更高、但更近的那条继续靠近。加农炮船的近炮优先级 100、20 码、140 伤，远炮优先级 90、40 码、80 伤。从远处走进 40 码就停，用远炮。已经站在 20 码以内才用近炮，不后退。
5. 落在两段射程中间，向更近的那条走进去。已经贴进最小射程里面，不后退。拿破仑炮 11.5 以内用霰弹。

直线移动每个 tick 用第 4 步把速度设成 0。绕路只在堵住时搜索，搜索算法不改。搜敌半径只用打得中人的最远射程，不用一条更远的攻城把圈子撑大。

20 个火枪兵对 20 个，现在一次 tick 是 4.51 毫秒。目标类型判断按更重的一档（40 人、每人 10 个敌人、4 条攻击）估算，多 0.16 毫秒，大约 3.5%。这是上限。为了按数据出手，一次 tick 变慢 20% 以内可以接受。

## 蓄力在数据里长什么样

- 标记在战术文件的动作上，不在动作名上。`chargeaction` 或 `auxchargeaction` 为 1，这条才是蓄力击。
- 单位上的 `<rechargetime>` 是冷却，常见 15–75 秒。`<chargeusagetime>` 是这一击占用的时间，常见 0.25–0.8 秒；持枪杀手的拔枪约 2.5 秒；喷火器写了 6.1 秒，但那条默认关着。
- 第一期按「蓄满打一次，伤害用这一条整包」实现。不模拟持续喷射。
- XML 里没有「开局蓄力条是空的」这种字段。实战里条是满的。模拟默认开局满，不是从 XML 读出来的值。
- 冷却缺省或小于等于 0 的蓄力会留在列表里，但这一期不自动打出。不要当成永远蓄满。

带蓄力标记的整包写在 `attack_actions` 里。回放里的远程 / 近战只表示这一下用了哪边的抬手，伤害类型仍看这一包自己的 `damagetype`。两槽还没退役时，卡片上的投影可以继续按动作名跳过 `Charge`；退役时这条投影一起去掉。

名字里有 Charge、但战术动作**没有**上述标记的，不是蓄力，按普通攻击收进列表。骑射手、基齐勒巴什这一类的 `ChargeAttack` 就是改了名的普通近战，伤害按数据来，很强也留下；它们是作弊单位。2026-09-17 按名字跳过的决议作废。蓄力只认标记，没标记的不走冷却。

谁出生开、谁出生关，不在这里点名验收。伤害包写了 `active` 就以它为准，没写再看战术文件。教宗护卫的戟击按数据出生就开，手枪要等科技。

按数据出生就开、能看出和普通攻击不是同一包的例子：

| 兵 | 蓄力（protoy） | 同一兵的普通攻击 | 冷却 |
|---|---|---|---|
| 牛仔 | 瞄准 30 远程，射程 16 | 射击 20 远程，射程 12 | 40 秒 |
| 骑乘拦路强盗 | 瞄准 36 远程，射程 16 | 射击 16 远程，射程 12 | 60 秒 |
| 翼骑兵 | 长矛 30 攻城，溅射 3，池 60 | 近战 30 近战，射程 3.75 | 60 秒 |
| 皇家火枪兵 | 手枪 44 远程，射程 12 | 齐射 22 远程，射程 12 | 60 秒 |
| 骷髅武士 | 黑曜石 30 近战，溅射 4 | 近战 20 | 15 秒 |

翼骑兵另有剧情变体，长矛 41.25 攻城，普通近战 27.5。波斯尼亚兵、加洛格拉什、国土佣仆的蓄力同样是更高伤害或带溅射的一击，冷却写在单位上。

## 默认关着的模式，靠科技打开

闸门打在攻击模式上，不打在「是不是蓄力」上。这一条开没开，先看该原型伤害包有没有写 `active`，没写再看战术文件。写成 0 就不参与，写成 1 就参与。打开或关掉它的效果是：

`techtreey.xml` 里 `<effect type="Data" subtype="ActionEnable" amount="1.00" action="动作名">`，目标是 `<target type="ProtoUnit">原型单位名</target>`。

`amount` 为 1 把这条加入该原型的列表，为 0 拿掉。解锁认**原型单位名**，不认「共用了哪个战术文件」。

`scripts/crawler/aoe3_civ_war_tech_pool.py` 已把 `ActionEnable` 记成战斗相关 subtype，所以这种科技能进国战池。套用时按动作名打开或关掉这一条。伤害、射程、攻速、溅射、倍率也会落到同名模式上。

下面先列蓄力模式里已经对上开关的。霰弹、迫击、火箭，以及间谍、随军神父、海盗现在用着、但战术里其实关着的普通射击，都是这一扇门。叛乱者要先换成齐射阵型。具体单位在复查表的「普通攻击会变」和「套科技才变」。

已核对、默认关着、并且有对应 `ActionEnable` 的蓄力模式：

| 科技 | 打开谁的哪一击 |
|---|---|
| 教宗兵工厂 `DEHCPapalArsenal` | 教宗长矛骑兵的长矛冲锋；祖阿夫的卡宾；教宗护卫的手枪（含掩护副本）；教宗重炮的蓄力炮击 |
| 柏柏尔幻想曲 `DENatBerberMusketCharge` | 柏柏尔骆驼骑兵、雇佣骆驼骑兵、扎纳塔骑兵、柏柏尔苏丹的蓄力火枪 |
| 密歇根志愿狙击手 1 团 `DEHCMichiganSharpshooters` | 克里追踪者（含雇佣）的鹰眼 |
| 猎熊长矛 `DENatVasaRohatyna` | 伙伴骑兵（含雇佣）的长矛冲锋 |
| 拿破仑时代 `DERevolutionFranceNE` | 皇家火枪兵（含雇佣）的迫击。这条迫击本身带 `chargeaction`，手枪蓄力则出生就开 |
| 达官贵人 `DEHCDignitaries` | 医院骑士团骑士的手枪蓄力 |
| 喷火器 `DEHCFlameThrowers` | 火焰兵的喷火 |
| 驻防长矛骑兵 `DEHCPresidialLancers`、德克萨斯长矛骑兵 `DEHCREVMXTexasLancers` | 游击叛兵的长矛冲锋 |
| 尤卡坦州 `DERevolutionMXYucatan` | 叛乱者的套索 |
| 雇佣逃犯 `HCXPRenegadoAllies`、强盗 `DEBandido`，以及阴影科技 `DEOutlawChargedActions` | 原型 `SaloonOutlawRifleman`（界面上的叛兵）的霰弹蓄力 |
| 雇佣持枪杀手 `HCXPPistoleroAllies`、法外之徒 `DEDesperado`，以及同一阴影科技 | 原型 `SaloonOutlawPistol`（界面上的枪手）的拔枪 |
| 雇佣牛仔 `HCXPComancheroAllies`、牲畜盗贼 `DEVaquero`，以及同一阴影科技 | 原型 `SaloonOutlawRider`（界面上的短枪商人骑兵）的瞄准 |

美国文明起始阴影科技 `DEAge0Americans`（无显示名）把 `DEOutlawChargedActions` 设为 active。因此美国这边，上面三个**基础酒馆原型**的蓄力在文明起始就开。其它文明靠对应的主城卡。卡的做法是给基础原型改名、换说明，再 `ActionEnable` 那个基础原型。`ActionEnable` 只打到写明的原型，不因为共用战术文件就打开别的原型。`deSaloonOwlhoot`、`deSaloonGunslinger`、`deSaloonDesperado` 自己的伤害包把对应蓄力写成了 `active` 为 1，所以这三下出生就是开的。

雇佣持枪杀手只打开基础原型 `SaloonOutlawPistol` 的 `ChargeQuickDrawAttack`。同文件里的 `ChargeShootoutAttack` 在这个基础原型上没有同名伤害包，不收录。

间谍、将军、随军神父、大师、穆赫比尔的蓄力，伤害包写成 `active` 为 0，出生关着。打到该原型的 `ActionEnable` 才打开。维斯瓦马刀骑兵的长矛同样是伤害包 `active` 为 0，而且冷却是空的。

没有同名伤害包的不收录：归化短枪商人骑兵的瞄准、皇家火绳枪兵的鹰眼、条顿骑士的手枪、枪手和持枪杀手的 `ChargeShootoutAttack`、法外之徒的 `ChargeQuickDrawAttack`。扈从骑兵的蓄力火枪是战术文件关着、伤害包没把它写成开，所以关着。亲随的手枪、奥罗莫战士的蓄力火枪、水手的霰弹、骑士兄弟团的长矛，伤害包写成了开，出生就开。

改冷却长短的 `RechargeTime` 会落到这名兵已经有的蓄力上。0.6 就是变成原来的六成。原来没有冷却时间的，乘完还是 0，仍然不会打出。

这场对局只应用已经套上的科技。柏柏尔幻想曲没进本场已套用列表，骆驼骑兵的蓄力火枪就保持关闭。美国酒馆兵要开蓄力，得让 `DEAge0Americans` 或它点亮的 `DEOutlawChargedActions` 进入已套用科技。不按文明名写死。

## 不同射程，以及默认关着的普通模式

不同射程的模式在这次计划里。只要它在当前这份阵型里，就和主武器一起留下，用自己的那一整包。默认关着的留在列表里，但不参加挑选。

- 拿破仑炮的霰弹出生就是开的，和主炮是两条模式。11.5 以内用霰弹，不为了打主炮而后退。
- 叛兵、逃犯的 12–18 远射，强盗的 2–12 中射，沙漠步弓手的中距离射击，都是已经开着的另一条模式。现在的两槽只留了其中一条。
- 鹰炮、重型加农炮、长管炮、皮革加农炮、马炮的霰弹默认关着。主城卡榴霰弹 `DEHCCaseShot` 对其中多门炮 `ActionEnable` 了 `CaseShotAttack`。卡没套上就保持关闭。
- 掷弹兵、墨西哥士兵、正规军、卫士等的迫击或火箭同样默认关着，有对应卡才开。没有卡的那几门（例如佛郎加农炮的霰弹）保持关闭。

掩护阵型上的半伤副本跟着阵型走。这一期不切掩护，就不把 `Cover` 动作放进默认列表。教宗兵工厂虽然同时打开手枪和手枪掩护，默认阵型只用手枪那条。

## 动作列表同时补上的距离差

陆地兵里，开着的另一条射程会改变交战的，集中在拿破仑炮霰弹、叛兵和逃犯的 12–18 远射、强盗的 2–12 中射、沙漠步弓手的中距离弱射击。加农炮船从远处停在 40 码的远炮，不会为了 20 码的近炮继续靠近。鱼叉手、捕鲸船、战酋的额外动作优先级很低，主武器能打时轮不到；战酋狂暴不自动放。

木制假炮当前入库的是迫击 500 伤。单位带 `InflictsNoDamage`，不写攻击列表。40 和 500 都不要当成实战输出。固定炮的第一优先是 `CannonAttack`，入库的是另一条 `LongRangeAttack`。以战术列表为准之后，这种选错套会一起消失。

tactics 里的伤害和攻速经常是过期副本。火枪兵游戏内远程是 23 伤、攻速 3 秒，和 protoy 一致；战术文件写成 13 伤、2 秒。全库 167 个兵有这种不一致。战术文件只提供：阵型里有哪些动作、优先级、开没开、打哪类目标，以及 protoy 没写的射程。

## 这一期留在外面

- 齐射、交错、防御、掩护的来回切换。齐射和交错数字真正不同的只有大约 7 个兵。科技改写初始阵型要做，见上面。
- 建筑上的蓄力射击（交易站一类）不进陆地斗蛐蛐。
- `hitpercent`、`stunduration`、`accuracy`、`CanDodgeAttacks`。没有对应的手写补丁，常态出手不模拟。
- 葡萄弹关掉管风琴 Limber 之后不再架炮。这次不改架炮进场。

## 已经落地的代码

正式文档还没改。

- 列表按「列表里收什么」重写。船写上，没写初始阵型的落到 `Normal`。读了 `<initialtactic>`。不按名字删。没有 protoy 伤害包、伤害不大于 0 的不收。`InflictsNoDamage` 不写列表，木制假炮因此进不了池。每个阵型的列表记在 `attack_actions_by_tactic`。
- 出手认 `<rate type>`。对不上当前目标的不进候选。搜敌半径只用打得中人、并且现在打得出来的最远射程。已经盖住当前距离就停住。
- `InitialTactic` 先换成那一份阵型的列表，然后才套同一条科技里的 `ActionEnable`。预备军因此能把叛乱者的枪打开。科技池里已有的这类效果写进了 `combat_ops`。
- 进池、战力、国战预估改读列表。单位卡、配兵面板、兵种对比各显示当前阵型里优先级最高的最多两条，标题是动作名。同优先级保持阵型里的先后。详略按场合：卡片和对比写出这一条的伤害、伤害类型、射程、射速、前摇、溅射、弹丸、蓄力和倍率；配兵面板只留动作名、伤害、伤害类型、射程、射速，有溅射或关掉才补上。克制和国战角色看现在开着、打得中人的模式自己的倍率。一行摘要在没有这种模式时不写攻击。
- 蓄力、`ActionEnable`、`RechargeTime` 仍按上一期。蓄力条开局是满的。冷却缺省或小于等于 0 的不自动打出。

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

## 还没写进代码

模拟器仍读两槽，这次不动。解析器继续写出槽字段。时代改良的旧桶继续按原来的算法生成，模拟器读到的攻击数字不变。停写两槽留给模拟器。

列表这边已经按模式走：单位卡、配兵面板、兵种对比显示当前阵型里优先级最高的最多两条。克制和国战角色看开着且打得中人的模式自己的倍率。科技按动作名改列表。时代改良种子另有一份按动作名的加减，打到同名模式上。

够得着就停，是现在的移动判断，绕路搜索没改。

已经定了、代码也按这个在跑的：

- 开局蓄力条是满的。这是模拟默认，不是 XML 字段。
- 冷却缺省或小于等于 0 的蓄力不自动打出。哥萨克蛮兵、波兰枪骑兵、骷髅轻骑兵、bersagliere 的晕击都在这列。
- 鹰炮、重炮、长管炮、马炮、皮革炮的主炮最小射程是 0，优先级高于榴霰。科技把榴霰打开之后，这一下仍是主炮。拿破仑炮的主炮从 11.5 起，贴进去才会换榴霰。
