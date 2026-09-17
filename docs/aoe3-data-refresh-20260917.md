# AoE3 数据刷新对比报告

- 生成时间：2026-09-17 22:38
- 旧快照：`generated_at 2026-05-29T05:09:37.076054+00:00` / `git_head 2ef17ca`
- 新快照：`generated_at 2026-09-17T14:32:27.881888+00:00` / `git_head 3377814`
- 旧 raw：protoy 7.88 MB / tactics 432
- 新 raw：protoy 8.47 MB / tactics 472

## 1. 总览

| 指标 | 旧 | 新 | 变化 |
|---|---|---|---|
| 战斗单位 | 756 | 815 | +59 |
| protoy 字节 | 8260469 | 8880886 | +620417 |
| tactics 文件 | 432 | 472 | +40 |
| anim 文件 | 485 | 535 | +50 |
| 有远程攻击 | 507 | 545 | +38 |
| 有近战攻击 | 571 | 626 | +55 |
| 有 AOE | 147 | 162 | +15 |
| 有 damage_cap | 160 | 176 | +16 |
| 有 windup | 661 | 713 | +52 |
| 有三槽代表动作 | 327 | 358 | +31 |
| 单位总量 | 756 | 815 | +59 |
| 有改良数据的单位 | 319 | 342 | +23 |
| 通用科技条数 | 66 | 73 | +7 |

## 2. 新增单位（65）

| id | 中文名 | 英文名 | type 摘要 | hp | 远/近/攻 | 代表动作 | 备注 |
|---|---|---|---|---|---|---|---|
| `deconsulateindependencedragoon` | 军团枪骑兵 | Legion Dragoon | AbstractCavalry/AbstractCavalryInfantry/AbstractConsulateUnit | 200 | 22/11/9 | StaggerRangedAttack / MeleeHandAttack |  |
| `deconsulatejanissary` | 皇家奥斯曼火枪兵 | Crown Janissary | AbstractCavalryInfantry/AbstractConsulateUnit/AbstractConsulateUnitColonial | 215 | 20/15/25 | VolleyRangedAttack / MeleeHandAttack |  |
| `deeggarctictruck` | 极地掠夺者 | Arctic PredatoR | AbstractCavalry/AbstractCavalryInfantry/AbstractHandCavalry | 60000 | —/1000/— | — / TrampleHandAttack | 无 windup |
| `deespingol` | 雷筒 | Espingol | AbstractArtillery/LogicalTypeLandMilitary/Military | 150 | 66/—/— | CannonAttack / — |  |
| `defriskytterider` | 骑马自由枪手 | Mounted Friskytte | AbstractCavalry/AbstractCavalryInfantry/AbstractGunpowderCavalry | 170 | 12/12/14 | StaggerRangedAttack / MeleeHandAttack |  |
| `degunboat` | 炮舰 | Gunboat | AbstractSiegeTrooper/AbstractWarShip/Military | 250 | 80/—/— | LongRangeAttack / — |  |
| `dehetman` | 大元帅 | Hetman | AbstractCanSeeStealth/AbstractCavalry/AbstractCavalryInfantry | 500 | —/6/15 | — / HandAttack |  |
| `deindependencebisonbatch` | 拉科塔狩猎场 | Lakota Hunting Grounds | AbstractBannerArmy/Military/Unit | 200 | 20/—/— | VolleyRangedAttack / — |  |
| `deindependencepolishlancer` | 维斯瓦马刀骑兵 | Vistula Uhlan | AbstractCavalry/AbstractCavalryInfantry/AbstractConsulateUnit | 190 | —/28/10 | — / MeleeHandAttack |  |
| `deindependenceserdyuk` | 谢尔久克 | Serdyuk | AbstractCavalryInfantry/AbstractConsulateUnit/AbstractGunpowderTrooper | 300 | 26/26/18 | VolleyRangedAttack / VolleyHandAttack |  |
| `delithuanianrider` | 扈从骑兵 | Retainer | AbstractCavalry/AbstractCavalryInfantry/AbstractHandCavalry | 210 | —/22/16 | — / MeleeHandAttack |  |
| `demaltesegun` | 固定炮 | Fixed Gun | AbstractArtillery/AbstractFindFort/AbstractOutpost | 2250 | 300/—/— | LongRangeAttack / — | 无 windup |
| `demerccranequinier` | 绞弦弩骑兵 | Cranequinier | AbstractArcher/AbstractCavalry/AbstractCavalryInfantry | 360 | 25/—/18 | BowAttack / — |  |
| `demercgallowglass` | 加洛格拉什 | Gallowglass | AbstractCavalryInfantry/AbstractHandInfantry/AbstractHeavyInfantry | 222 | —/30/30 | — / MeleeHandAttack |  |
| `demercwagon` | 强化马车 | Fortified Wagon | AbstractArtillery/LogicalTypeLandMilitary/Mercenary | 250 | 60/—/— | CannonAttack / — |  |
| `denatbagpiper` | 风笛手 | Bagpiper | AbstractCavalryInfantry/AbstractGunpowderTrooper/AbstractInfantry | 250 | 20/10/10 | VolleyRangedAttack / HandAttack |  |
| `denatclansman` | 氏族战士 | Clansman | AbstractCavalryInfantry/AbstractCoyoteMan/AbstractHandInfantry | 140 | —/18/11 | — / MeleeHandAttack |  |
| `denatcompanion` | 伙伴骑兵 | Companion | AbstractCavalry/AbstractCavalryInfantry/AbstractHandCavalry | 335 | —/17/18 | — / MeleeHandAttack |  |
| `denathusky` | 哈士奇 | Husky | AbstractCanSeeStealth/AbstractHandInfantry/AbstractNativeWarrior | 215 | —/9/— | — / MeleeHandAttack |  |
| `denatinuithunter` | 因纽特猎人 | Inuit Hunter | AbstractArchaicInfantry/AbstractArcher/AbstractCavalryInfantry | 130 | 13/10/10 | RangedAttack / HandAttack |  |
| `denatinuitqamutik` | 因纽特人雪橇 | Inuit Qamutik | AbstractArcher/AbstractCavalry/AbstractCavalryInfantry | 420 | 15/—/15 | BowAttack / — | 无 windup |
| `denatlowlanderinfantry` | 低地人 | Lowlander | AbstractCavalryInfantry/AbstractGunpowderTrooper/AbstractHeavyInfantry | 135 | 19/15/19 | VolleyRangedAttack / VolleyHandAttack |  |
| `denatlowlanderrider` | 低地枪骑兵 | Lowland Dragoon | AbstractCavalry/AbstractCavalryInfantry/AbstractGunpowderCavalry | 140 | 12/12/14 | StaggerRangedAttack / MeleeHandAttack |  |
| `denatmercbagpiper` | 风笛手 | Bagpiper | AbstractCavalryInfantry/AbstractGunpowderTrooper/AbstractInfantry | 250 | 20/10/10 | VolleyRangedAttack / HandAttack |  |
| `denatmercclansman` | 氏族战士 | Clansman | AbstractCavalryInfantry/AbstractCoyoteMan/AbstractHandInfantry | 140 | —/18/11 | — / MeleeHandAttack |  |
| `denatmerccompanion` | 伙伴骑兵 | Companion | AbstractCavalry/AbstractCavalryInfantry/AbstractHandCavalry | 335 | —/17/18 | — / MeleeHandAttack |  |
| `denatmerchusky` | 哈士奇 | Husky | AbstractCanSeeStealth/AbstractHandInfantry/AbstractNativeWarrior | 215 | —/9/— | — / MeleeHandAttack |  |
| `denatmercinuithunter` | 因纽特猎人 | Inuit Hunter | AbstractArchaicInfantry/AbstractArcher/AbstractCavalryInfantry | 130 | 13/10/10 | RangedAttack / HandAttack |  |
| `denatmercinuitqamutik` | 因纽特人雪橇 | Inuit Qamutik | AbstractArcher/AbstractCavalry/AbstractCavalryInfantry | 420 | 15/—/15 | BowAttack / — | 无 windup |
| `denatmerclowlanderinfantry` | 低地人 | Lowlander | AbstractCavalryInfantry/AbstractGunpowderTrooper/AbstractHeavyInfantry | 135 | 19/15/19 | VolleyRangedAttack / VolleyHandAttack |  |
| `denatmerclowlanderrider` | 低地枪骑兵 | Lowland Dragoon | AbstractCavalry/AbstractCavalryInfantry/AbstractGunpowderCavalry | 140 | 12/12/14 | StaggerRangedAttack / MeleeHandAttack |  |
| `denatmercnoaidi` | 萨米巫师 | Sámi Noaidi | AbstractDoubleVillager/AbstractNativeWarrior/AbstractVillager | 240 | 3/10/10 | BlunderbussAttack / HandAttack |  |
| `denatmercroyalhuntsman` | 皇家猎人 | Royal Huntsman | AbstractCavalryInfantry/AbstractCounterSkirmisher/AbstractGunpowderTrooper | 150 | 10/10/5 | VolleyRangedAttack / VolleyHandAttack |  |
| `denatnoaidi` | 萨米巫师 | Sámi Noaidi | AbstractDoubleVillager/AbstractNativeWarrior/AbstractVillager | 240 | 5/10/10 | BlunderbussAttack / HandAttack |  |
| `deoutlawwhalingship` | 捕鲸船 | Whaling Ship | AbstractCountAsGatherer/AbstractFishingBoat/AbstractSiegeTrooper | 1500 | 50/—/— | RangedAttack / — |  |
| `depiechur` | 波兰步兵 | Piechur | AbstractCavalryInfantry/AbstractGunpowderTrooper/AbstractInfantry | 120 | 16/10/14 | VolleyRangedAttack / VolleyHandAttack |  |
| `deregent` | 摄政王 | Regent | AbstractRegent/LogicalTypeLandMilitary/Unit | 2500 | —/10/5 | — / MeleeHandAttack |  |
| `deregenthorse` | 摄政王 | Regent | AbstractCavalry/AbstractCavalryInfantry/AbstractDaimyo | 2000 | —/10/5 | — / MeleeHandAttack |  |
| `derevchern` | 哥萨克农夫 | Khutorian | AbstractArchaicInfantry/AbstractCavalryInfantry/AbstractHandInfantry | 135 | —/8/36 | — / HandAttack |  |
| `derevcossacktabor` | 哥萨克战车 | Tabor | AbstractCavalry/AbstractGunpowderCavalry/AbstractLightCavalry | 535 | 20/20/8 | StaggerRangedAttack / MeleeHandAttack | 无 windup |
| `derevhaidamaka` | 海达马卡步枪兵 | Haidamaka Rifleman | AbstractCavalryInfantry/AbstractGunpowderTrooper/AbstractInfantry | 130 | 14/7/20 | VolleyRangedAttack / MeleeHandAttack |  |
| `derevhaidamakarider` | 海达马卡人 | Haidamaka | AbstractCavalry/AbstractCavalryInfantry/AbstractGunpowderCavalry | 140 | 14/9/14 | StaggerRangedAttack / MeleeHandAttack |  |
| `derevhighmaster` | 大团长 | High Master | AbstractCavalry/AbstractCavalryInfantry/AbstractHandCavalry | 900 | —/45/14 | — / HandAttack |  |
| `derevknightbrother` | 骑士兄弟团 | Knight Brother | AbstractBasilicaUnit/AbstractCavalry/AbstractCavalryInfantry | 480 | —/24/24 | — / MeleeHandAttack |  |
| `derevordermusketeer` | 火枪骑士团骑士 | Order Musketeer | AbstractCavalryInfantry/AbstractGunpowderTrooper/AbstractHeavyInfantry | 160 | 25/18/18 | VolleyRangedAttack / MeleeHandAttack |  |
| `derevorderpavisier` | 弩手骑士团骑士 | Order Crossbowman | AbstractArchaicInfantry/AbstractArcher/AbstractCavalryInfantry | 110 | 21/10/10 | VolleyRangedAttack / MeleeHandAttack |  |
| `derevpolishlancer` | 维斯瓦马刀骑兵 | Vistula Uhlan | AbstractCavalry/AbstractCavalryInfantry/AbstractHandCavalry | 190 | —/28/10 | — / MeleeHandAttack |  |
| `derevscytheman` | 镰刀手 | Scytheman | AbstractArchaicInfantry/AbstractCavalryInfantry/AbstractHandInfantry | 190 | —/15/24 | — / MeleeHandAttack |  |
| `derevserdyuk` | 谢尔久克 | Serdyuk | AbstractCavalryInfantry/AbstractGunpowderTrooper/AbstractHeavyInfantry | 300 | 26/26/18 | VolleyRangedAttack / VolleyHandAttack |  |
| `derevstarshyna` | 哥萨克军官 | Starshyna | AbstractCavalry/AbstractCavalryInfantry/AbstractHandCavalry | 450 | —/32/30 | — / MeleeHandAttack |  |
| `derevteutonicknight` | 条顿骑士 | Teutonic Knight | AbstractCavalryInfantry/AbstractHandInfantry/AbstractHeavyInfantry | 320 | —/35/50 | — / MeleeHandAttack |  |
| `desaloonharpooner` | 鱼叉手 | Harpooner | AbstractCavalryInfantry/AbstractGunpowderTrooper/AbstractHeavyInfantry | 210 | 20/14/14 | RangedAttack / HandAttack |  |
| `desaloonqivittoq` | 基维图克 | Qivittoq | AbstractArcher/AbstractCavalryInfantry/AbstractLightInfantry | 111 | 15/15/15 | RangedAttack / HandAttack |  |
| `desaloonsailor` | 水手 | Sailor | AbstractCavalryInfantry/AbstractGunpowderTrooper/AbstractInfantry | 190 | 15/10/22 | RangedAttack / HandAttack |  |
| `despchmbonaght` | 博纳赫特佣兵 | Bonaght Soldier | AbstractCavalryInfantry/AbstractConsulateUnit/AbstractConsulateUnitColonial | 155 | 19/14/22 | VolleyRangedAttack / VolleyHandAttack |  |
| `despchmcavalier` | 重装骑士 | Cavalier | AbstractCavalry/AbstractCavalryInfantry/AbstractConsulateUnit | 200 | 22/18/15 | StaggerRangedAttack / MeleeHandAttack |  |
| `despchmcovenanter` | 誓约党 | Covenanter | AbstractCavalry/AbstractCavalryInfantry/AbstractConsulateUnit | 170 | 12/12/14 | StaggerRangedAttack / MeleeHandAttack |  |
| `despchmcovenanterinfantry` | 誓约党步兵 | Covenanter Infantry | AbstractCavalryInfantry/AbstractConsulateUnit/AbstractConsulateUnitColonial | 150 | 16/15/16 | VolleyRangedAttack / VolleyHandAttack |  |
| `despchmirishhorseman` | 爱尔兰骑兵 | Irish Horseman | AbstractArcher/AbstractCavalry/AbstractCavalryInfantry | 275 | 11/—/12 | BowAttack / — |  |
| `despchmironside` | 重装骑兵 | Ironside | AbstractCavalry/AbstractCavalryInfantry/AbstractConsulateUnit | 260 | 18/27/10 | StaggerRangedAttack / MeleeHandAttack |  |
| `despchmlord` | 领主 | Lord | AbstractCavalry/AbstractCavalryInfantry/AbstractHandCavalry | 2026 | —/10/5 | — / MeleeHandAttack |  |
| `despchmredcoat` | 红衫军 | Redcoat | AbstractCavalryInfantry/AbstractConsulateUnit/AbstractConsulateUnitColonial | 160 | 25/13/19 | VolleyRangedAttack / VolleyHandAttack |  |
| `despchmwhitecoat` | 白衫军 | Whitecoat | AbstractCavalryInfantry/AbstractConsulateUnit/AbstractConsulateUnitColonial | 145 | 21/9/20 | VolleyRangedAttack / VolleyHandAttack |  |
| `despcwingedhussar` | 翼骑兵 | Winged Hussar | AbstractCavalry/AbstractCavalryInfantry/AbstractHandCavalry | 395 | —/27.5/25 | — / MeleeHandAttack |  |
| `dewingedhussar` | 翼骑兵 | Winged Hussar | AbstractCavalry/AbstractCavalryInfantry/AbstractHandCavalry | 360 | —/30/20 | — / MeleeHandAttack |  |

## 3. 消失单位（6）

| id | 中文名 | 英文名 | hp | 备注 |
|---|---|---|---|---|
| `denatmercwingedhussar` | 翼骑兵 | Winged Hussar | 395 | 旧数据独有 |
| `denatwingedhussar` | 翼骑兵 | Winged Hussar | 395 | 旧数据独有 |
| `derevmxminutemanbatch` | 民兵 | Militiaman | 200 | 旧数据独有 |
| `derevnatvillagerbatch` | 原住民村民 | Native Villager | 200 | 旧数据独有 |
| `despawnbajacaliforniaterritorybatch` | 拓荒者 | Settler | 200 | 旧数据独有 |
| `ypoldhanarmy` | 旧汉军 | Old Han Army | 200 | 旧数据独有 |

## 4. 结构性变更（代表动作 / 攻击槽增删）（31）

> 代表动作变更意味着整包攻击数据（damage/rof/aoe/倍率/windup）换了一套，比单纯数值变动严重，需重点核对。

| id | 中文名 | 变更 | 旧 → 新 |
|---|---|---|---|
| `abusgun` | 奥斯曼枪手 | 2 项 | attack_ranged: 36 → 34<br>description: 造成围攻破坏的奥斯曼步兵部队。擅长对抗步兵。 → 造成攻城伤害的奥斯曼步兵单位。擅长对抗步兵。 |
| `cavalryarcher` | 骑射手 | 8 项 | attack_melee: — → 6.5<br>damage_type_melee: — → Hand<br>melee: +AbstractArtillery x2, +AbstractCoyoteMan x3.5, +AbstractHeavyCavalry x4.5<br>**protoaction_melee**: — → GuardianAttack<br>range_melee: — → 1.75<br>rof_melee: — → 1.5<br>windup_melee: — → 0.54<br>+GuardianAttack 0.54s, +TrampleHandAttack 0.56s |
| `debolaswarrior` | 掷石绳战士 | 1 项 | attack_melee: 8 → 15 |
| `definnishrider` | 芬兰轻装骑兵 | 5 项 | armor_ranged: 0.2 → 0.15<br>attack_melee: 22 → 20<br>hp: 210 → 215<br>los: 15 → 14<br>type: ["AbstractCavalry", "AbstractCavalryInfantry", "AbstractGunpowderCavalry", "AbstractHandCavalry", "AbstractLightCavalry… → ["AbstractCavalry", "AbstractCavalryInfantry", "AbstractGunpowderCavalry", "AbstractLightCavalry", "AbstractRangedCaval… |
| `degascenya` | 加塞尼亚步兵 | 3 项 | attack_melee: 15 → 12<br>hp: 135 → 140<br>melee: AbstractCavalry x3→x4, AbstractLightInfantry x2.25→x2.5 |
| `demercharquebusier` | 火绳枪骑兵 | 1 项 | attack_melee: 121 → 110 |
| `denatholcanjavelineer` | 霍尔坎标枪手 | 3 项 | **protoaction_melee**: VolleyHandAttack → MeleeHandAttack<br>windup_melee: 0.47 → 0.37<br>BuildingAttack 0.49→0.75s, -DefendHandAttack, MeleeHandAttack 0.47→0.37s, -StaggerHandAttack, -VolleyHandAttack |
| `denatlipkatatar` | 利普卡鞑靼人 | 2 项 | attack_ranged: 12.5 → 10<br>cost: {"food": 70, "wood": 60} → {"food": 80, "wood": 70} |
| `denatmercholcanjavelineer` | 霍尔坎标枪手 | 3 项 | **protoaction_melee**: VolleyHandAttack → MeleeHandAttack<br>windup_melee: 0.47 → 0.37<br>BuildingAttack 0.49→0.75s, -DefendHandAttack, MeleeHandAttack 0.47→0.37s, -StaggerHandAttack, -VolleyHandAttack |
| `denatmerclipkatatar` | 利普卡鞑靼人 | 2 项 | attack_ranged: 12.5 → 10<br>cost: {"food": 70, "wood": 60} → {"food": 80, "wood": 70} |
| `denatmercqizilbash` | 基齐勒巴什兵 | 6 项 | attack_melee: 18 → —<br>damage_type_melee: Hand → —<br>melee: -AbstractInfantry<br>**protoaction_melee**: MeleeHandAttack → —<br>range_melee: 0 → —<br>rof_melee: 1.5 → — |
| `denatmercsharktoothbowman` | 塞米诺尔鲨齿弓箭手 | 3 项 | **protoaction_melee**: VolleyHandAttack → HandAttack<br>**protoaction_ranged**: VolleyRangedAttack → RangedAttack<br>-DefendHandAttack, -DefendRangedAttack, +HandAttack 0.27s, -MeleeHandAttack, +RangedAttack 0.98s, -StaggerHandAttack, -StaggerRangedAttack, -VolleyHandAttack, -VolleyRangedAttack |
| `denatqizilbash` | 基齐勒巴什兵 | 6 项 | attack_melee: 18 → —<br>damage_type_melee: Hand → —<br>melee: -AbstractInfantry<br>**protoaction_melee**: MeleeHandAttack → —<br>range_melee: 0 → —<br>rof_melee: 1.5 → — |
| `desalooninquisitor` | 审判官 | 4 项 | attack_melee: 15 → 18<br>cost: {"gold": 100} → {"gold": 110}<br>speed: 4.25 → 4.75<br>train_time: 35 → 45 |
| `detank` | 莱昂纳多的战车 | 3 项 | aoe_radius: 3 → 4<br>aoe_radius_ranged: 3 → 4<br>attack_ranged: 100 → 300 |
| `deunknownnateaglewarrior` | 阿兹特克鹰勇士 | 5 项 | description: 阿兹特克步兵，会用掷矛器掷射标枪，擅长对付骑兵及近战突击步兵。 → 阿兹特克步兵，会用掷矛器掷射标枪，擅长对付骑兵及近战冲击部队。<br>description_en: Aztec infantry that flings javelins from an atlatl. Good against Cavalry and Hand Shock Infantry. → Aztec infantry that flings javelins from an atlatl. Good against Cavalry and Hand Shock Troops.<br>**protoaction_melee**: VolleyHandAttack → MeleeHandAttack<br>windup_melee: 0.47 → 0.37<br>BuildingAttack 0.49→0.75s, -DefendHandAttack, MeleeHandAttack 0.47→0.37s, -StaggerHandAttack, -VolleyHandAttack |
| `monstertrucka` | 大安迪 | 8 项 | aoe_radius: — → 8<br>aoe_radius_melee: — → 8<br>attack_melee: — → 1000<br>damage_cap_melee: — → 2000<br>damage_type_melee: — → Hand<br>**protoaction_melee**: — → TrampleHandAttack<br>range_melee: — → 8<br>rof_melee: — → 2 |
| `monstertruckt` | 汤米卡车 | 8 项 | aoe_radius: — → 6<br>aoe_radius_melee: — → 6<br>attack_melee: — → 1200<br>damage_cap_melee: — → 3000<br>damage_type_melee: — → Hand<br>**protoaction_melee**: — → TrampleHandAttack<br>range_melee: — → 8<br>rof_melee: — → 2 |
| `nateaglewarrior` | 阿兹特克鹰勇士 | 5 项 | description: 阿兹特克步兵，会用掷矛器掷射标枪，擅长对付骑兵及近战突击步兵。 → 阿兹特克步兵，会用掷矛器掷射标枪，擅长对付骑兵及近战冲击部队。<br>description_en: Aztec infantry that flings javelins from an atlatl. Good against Cavalry and Hand Shock Infantry. → Aztec infantry that flings javelins from an atlatl. Good against Cavalry and Hand Shock Troops.<br>**protoaction_melee**: VolleyHandAttack → MeleeHandAttack<br>windup_melee: 0.47 → 0.37<br>BuildingAttack 0.49→0.75s, -DefendHandAttack, MeleeHandAttack 0.47→0.37s, -StaggerHandAttack, -VolleyHandAttack |
| `nathorsearcher` | 卡曼契骑马弓兵 | 1 项 | attack_ranged: 13 → 15 |
| `natmerchorsearcher` | 卡曼契骑马弓兵 | 1 项 | attack_ranged: 13 → 15 |
| `natsharktoothbowman` | 塞米诺尔鲨齿弓箭手 | 3 项 | **protoaction_melee**: VolleyHandAttack → HandAttack<br>**protoaction_ranged**: VolleyRangedAttack → RangedAttack<br>-DefendHandAttack, -DefendRangedAttack, +HandAttack 0.27s, -MeleeHandAttack, +RangedAttack 0.98s, -StaggerHandAttack, -StaggerRangedAttack, -VolleyHandAttack, -VolleyRangedAttack |
| `spcxpchiefbravewolf` | 狼勇士酋长 | 5 项 | attack_melee: 6 → 30<br>attack_siege: 15 → 30<br>hp: 500 → 750<br>melee: +AbstractInfantry x1.5, -AbstractVillager<br>+BerserkAttack 0.57s |
| `spcxpchiefbullbear` | 巨熊酋长 | 7 项 | aoe_radius: — → 1<br>aoe_radius_melee: — → 1<br>attack_melee: 28 → 30<br>damage_cap_melee: — → 50<br>hp: 475 → 750<br>melee: +Guardian x3<br>+BerserkAttack 0.57s, +SwashbucklerAttack 0.57s |
| `uhlan` | 德国骑兵 | 2 项 | attack_melee: 37 → 35<br>attack_siege: 20 → 19 |
| `xpbowrider` | 弓骑士 | 3 项 | attack_ranged: 20 → 18<br>hp: 225 → 230<br>ranged: AbstractHeavyCavalry x2.25→x2.5 |
| `xpcouprider` | 塔斯云坎游荡者 | 4 项 | age: Industrial Age → Fortress Age<br>attack_melee: 15 → 14<br>attack_siege: 15 → 14<br>hp: 220 → 215 |
| `xpeagleknight` | 鹰游击武士 | 5 项 | description: 贵族单位，会从掷矛器掷射标枪，擅长对付骑兵及近战突击步兵。 → 贵族单位，会从掷矛器掷射标枪，擅长对付骑兵及近战冲击部队。<br>description_en: Nobleman that flings javelins from an atlatl. Good against Cavalry and Hand Shock Infantry. → Nobleman that flings javelins from an atlatl. Good against Cavalry and Hand Shock Troops.<br>**protoaction_melee**: VolleyHandAttack → MeleeHandAttack<br>windup_melee: 0.47 → 0.37<br>BuildingAttack 0.49→0.75s, -DefendHandAttack, MeleeHandAttack 0.47→0.37s, -StaggerHandAttack, -VolleyHandAttack |
| `ypeggicecreamtruck` | 冰淇淋大脚车 | 8 项 | aoe_radius: — → 8<br>aoe_radius_melee: — → 8<br>attack_melee: — → 1000<br>damage_cap_melee: — → 2000<br>damage_type_melee: — → Hand<br>**protoaction_melee**: — → TrampleHandAttack<br>range_melee: — → 8<br>rof_melee: — → 2 |
| `ypspcishida` | 石田大名 | 4 项 | armor_ranged: 0.6 → 0.7<br>attack_melee: 10 → 70<br>attack_siege: 5 → 25<br>hp: 1250 → 2500 |
| `ypwokoupirate` | 倭寇海盗 | 4 项 | **protoaction_melee**: HandAttack → MeleeHandAttack<br>range_melee: 0 → 1.75<br>windup_melee: — → 0.5<br>+MeleeHandAttack 0.5s |

## 5. 数值 / 文本变更（194）

| id | 中文名 | 变更 | 旧 → 新 |
|---|---|---|---|
| `coureur` | 森林酷民 | 1 项 | armor_ranged: 0.4 → 0.3 |
| `crossbowman` | 弩手 | 1 项 | +LockRangedAttack 0.48s |
| `deabun` | 阿布恩 | 1 项 | train_time: 30 → 24 |
| `deafricancatamaran` | 强盗双体艇 | 1 项 | ranged: -Guardian, +WaterGuardian x10; siege: -Guardian, +WaterGuardian x5 |
| `debattlecanoe` | 作战划艇 | 2 项 | description: 战斗独木舟。一艘强大、敏捷的军舰，可以训练单位。 → 作战划艇。一艘强大、敏捷的军舰，可以训练单位。<br>name: 战斗独木舟 → 作战划艇 |
| `decarolean` | 卡尔远征军 | 1 项 | cost: {"food": 65, "gold": 40} → {"food": 60, "gold": 40} |
| `decaroleanbatch` | 卡尔远征军 | 1 项 | type: ["AbstractBannerArmy", "AbstractMusketeer", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractMusketeer", "Military", "Unit", "UnitClass"] |
| `dechevauleger` | 普林茨近卫轻骑兵 | 1 项 | melee: AbstractSkirmisher x0.6→x0.75 |
| `deconsulatecounterjaeger` | 反制步枪兵 | 1 项 | description_en: Specialized Light Infantry that only counters other Light Infantry, but does so very effectively. → Specialized Light Infantry that primarily counters other Light Infantry, but does so very effectively. |
| `deconsulaterocket` | 火箭炮 | 2 项 | name: 迈索尔火箭炮 → 火箭炮<br>name_en: Mysorean Rocket → Rocket |
| `deemboscador` | 劫匪 | 1 项 | speed: 4 → 4.25 |
| `defedbisonbatch` | 野牛 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `defedimmigrantbatch` | 清教徒 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `defedstatemilitiabatch` | 州民兵 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `defedstatemilitiabatch2` | 州民兵 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `defedvillagerbatch` | 拓荒者 | 1 项 | type: ["AbstractBannerArmy", "AbstractVillager", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractVillager", "Military", "Unit", "UnitClass"] |
| `defortgatlinggunbatch` | 加特林机枪 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `deforthussarbatch` | 轻骑兵 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `defortlegionczapakabatch` | 护卫德国骑兵 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Unit", "UnitClass"] |
| `defortlegiondragoonbatch` | 枪骑兵 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Unit", "UnitClass"] |
| `defortlegiongrenadierbatch` | 掷弹兵 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Unit", "UnitClass"] |
| `defortlegionmagyarhussarbatch` | 马扎尔轻骑兵 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Unit", "UnitClass"] |
| `defortregularbatch` | 正规军 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `defortriflemanbatch` | 狙击手 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `defortstatemilitiabatch` | 州民兵 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `defortuscavalrybatch` | 卡宾枪骑兵 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `defulawarrior` | 富拉尼步弓手 | 2 项 | +DefendRifleAttack 0.48s, +StaggerRifleAttack 0.46s, +VolleyRifleAttack 0.46s<br>range: 18 → 17 |
| `degalleass` | 三桅帆装军舰 | 3 项 | attack_melee: 350 → 400<br>aoe_radius_ranged: 1 → 2<br>attack_ranged: 35 → 40 |
| `dehumbaraci` | 铁帽炮兵 | 4 项 | ranged: AbstractCavalry x0.4→x0.25<br>armor_ranged: 0.3 → 0.25<br>speed: 4.5 → 4.25<br>train_time: 38 → 40 |
| `deincarunner` | 奇穆游击兵 | 1 项 | train_time: 30 → 27 |
| `deincaspearman` | 羽饰长矛兵 | 1 项 | cost: {"food": 100, "wood": 25} → {"food": 100, "wood": 20} |
| `dejavelinrider` | 标枪骑兵 | 1 项 | speed: 6.75 → 7 |
| `dejunglebowman` | 丛林弓箭手 | 1 项 | hp: 90 → 95 |
| `delifidi` | 利菲迪骑士 | 1 项 | hp: 375 → 390 |
| `demaceman` | 槌兵 | 1 项 | rof_melee: 2.25 → 2 |
| `demercaskari` | 阿斯卡里 | 1 项 | name: 非洲民兵 → 阿斯卡里 |
| `demercbrigadier` | 爱尔兰旅士兵 | 1 项 | name: 爱尔兰准将 → 爱尔兰旅士兵 |
| `demercdhow` | 達烏战船 | 2 项 | name: 战争单桅帆船 → 達烏战船<br>cost: {"gold": 700} → {"gold": 700, "wood": 700} |
| `demercgatlingcamel` | 加特林骆驼 | 1 项 | ranged: -AbstractCavalry, -AbstractHeavyInfantry, -AbstractLightInfantry; melee: +AbstractArtillery x0.34, -AbstractCavalry, -AbstractHeavyInfantry, -AbstractLightInfantry |
| `demercgrenadier` | 巨型掷弹兵 | 1 项 | hp: 250 → 260 |
| `demercirishbrigadier` | 爱尔兰旅士兵 | 1 项 | name: 爱尔兰准将 → 爱尔兰旅士兵 |
| `demercmountedrifleman` | 骑马步枪兵 | 2 项 | type: ["AbstractCavalry", "AbstractCavalryInfantry", "AbstractCounterSkirmisher", "AbstractGunpowderCavalry", "AbstractHandCa… → ["AbstractCavalry", "AbstractCavalryInfantry", "AbstractGunpowderCavalry", "AbstractHandCavalry", "AbstractHeavyCavalry…<br>range: 15 → 18 |
| `demercnapoleongun` | 拿破仑炮 | 1 项 | cost: {"gold": 450} → {"gold": 475} |
| `demercpandour` | 掠夺兵 | 2 项 | description: 来自巴尔干半岛的恶名昭彰的长枪兵，反制长枪兵。可以使用隐匿。 → 来自巴尔干半岛的恶名昭彰的反制长枪兵类型，反制长枪兵。可以使用隐匿。<br>description_en: Notorious Skirmisher from the Balkans that counters Skirmishers. Can use stealth. → Notorious Counter Skirmisher from the Balkans that counters Skirmishers. Can use stealth. |
| `demercroyalhorseman` | 皇家骑兵 | 1 项 | hp: 900 → 1200 |
| `demercxebec` | 谢贝克帆船 | 2 项 | name: 三桅帆船 → 谢贝克帆船<br>cost: {"gold": 700} → {"gold": 700, "wood": 700} |
| `demerczouave` | 祖阿夫兵 | 2 项 | description: 义勇军。拥有高生命值的多用途雇佣远距步兵。非常擅长对付所有单位。 → 祖阿夫兵。拥有高生命值的多用途雇佣远距步兵。非常擅长对付所有单位。<br>name: 义勇军 → 祖阿夫兵 |
| `denatberbersultan` | 柏柏尔苏丹 | 1 项 | name: 柏柏尔苏丹人 → 柏柏尔苏丹 |
| `denatbolasrider` | 马普切掷石绳骑兵 | 2 项 | range_melee: 1.75 → 3<br>rof_ranged: 3.5 → 3 |
| `denatchevauleger` | 近卫轻骑兵 | 1 项 | melee: AbstractSkirmisher x0.6→x0.75 |
| `denatmercchevauleger` | 近卫轻骑兵 | 1 项 | melee: AbstractSkirmisher x0.6→x0.75 |
| `denatmerclenaperifleman` | 莱纳佩战士 | 1 项 | +ChargeStun 0.44s |
| `denatmercnomad` | 柏柏尔游牧民 | 1 项 | name: 柏柏尔游牧民族 → 柏柏尔游牧民 |
| `denatmercroyaldragoon` | 皇家枪骑兵 | 1 项 | range: 16 → 17 |
| `denatmercroyalhunter` | 皇家猎兵 | 1 项 | name: 皇家猎人 → 皇家猎兵 |
| `denatmercroyalmusketeer` | 皇家火枪兵 | 2 项 | armor_melee: 0.4 → 0.3<br>attack_siege: 19 → 16 |
| `denatmercsudanesedervish` | 苏丹德尔维希 | 2 项 | attack_melee: 9 → 12<br>attack_ranged: 9 → 12 |
| `denatmerctatararcher` | 鞑靼弓手 | 3 项 | hp: 140 → 155<br>rof_siege: 1.25 → 1.2<br>name: 鞑靼步弓手 → 鞑靼弓手 |
| `denatnomad` | 柏柏尔游牧民 | 1 项 | name: 柏柏尔游牧民族 → 柏柏尔游牧民 |
| `denatroyaldragoon` | 皇家枪骑兵 | 1 项 | range: 16 → 17 |
| `denatroyalhorsemanbourbonproxy` | 皇家骑兵 | 1 项 | type: ["AbstractBannerArmy", "AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantr… → ["AbstractBannerArmy", "AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantr… |
| `denatroyalhunter` | 皇家猎兵 | 1 项 | name: 皇家猎人 → 皇家猎兵 |
| `denatroyalhuntsman` | 皇家猎人 | 1 项 | name: 皇家狩猎者 → 皇家猎人 |
| `denatroyalmusketeer` | 皇家火枪兵 | 2 项 | armor_melee: 0.4 → 0.3<br>attack_siege: 19 → 16 |
| `denatsomaliaskariproxy` | 阿斯卡里 | 2 项 | name: 非洲民兵 → 阿斯卡里<br>type: ["AbstractBannerArmy", "AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantr… → ["AbstractBannerArmy", "AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantr… |
| `denatspclenaperifleman` | 莱纳佩战士 | 1 项 | +ChargeStun 0.44s |
| `denatsudaneseaskariproxy` | 阿斯卡里 | 2 项 | name: 非洲民兵 → 阿斯卡里<br>type: ["AbstractBannerArmy", "AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantr… → ["AbstractBannerArmy", "AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantr… |
| `denatsudanesedervish` | 苏丹德尔维希 | 2 项 | attack_melee: 9 → 12<br>attack_ranged: 9 → 12 |
| `denatsudanesesennarproxy` | 森纳尔骑兵 | 1 项 | type: ["AbstractBannerArmy", "AbstractCavalry", "AbstractCavalryInfantry", "AbstractHandCavalry", "AbstractHeavyCavalry", "Lo… → ["AbstractBannerArmy", "AbstractCavalry", "AbstractCavalryInfantry", "AbstractHandCavalry", "AbstractHeavyCavalry", "Me… |
| `denattatararcher` | 鞑靼弓手 | 3 项 | hp: 140 → 155<br>rof_siege: 1.25 → 1.2<br>name: 鞑靼步弓手 → 鞑靼弓手 |
| `deneftenya` | 内夫特尼亚步枪兵 | 1 项 | cost: {"food": 65, "gold": 70} → {"food": 65, "gold": 65} |
| `denmpandour` | 斯基亚沃内兵 | 2 项 | description_en: Specialized Light Infantry that only counters other Light Infantry, but does so very effectively. → Specialized Light Infantry that primarily counters other Light Infantry, but does so very effectively.<br>name: 双刃剑手 → 斯基亚沃内兵 |
| `denmpapalzouave` | 教宗祖阿夫兵 | 1 项 | name: 教宗义勇军 → 教宗祖阿夫兵 |
| `deordenanca` | 法令步枪兵 | 2 项 | name: 法令斯步枪兵 → 法令步枪兵<br>cost: {"food": 35, "wood": 35} → {"food": 40, "wood": 40} |
| `deordergalley` | 军团桨帆船 | 2 项 | description: 箭船被装甲覆盖，但移速快。适用于进行探索、捕鱼或运输。在击沉敌方船只后获得攻击力加成。 → 桨帆船被装甲覆盖，但移速快。适用于进行探索、捕鱼或运输。在击沉敌方船只后获得攻击力加成。<br>name: 军团箭船 → 军团桨帆船 |
| `deoromowarrior` | 奥罗莫战士 | 1 项 | train_time: 50 → 45 |
| `deoutlawdesertraider` | 沙漠突袭者 | 1 项 | type: ["AbstractCavalry", "AbstractCavalryInfantry", "AbstractHandCavalry", "AbstractHeavyCavalry", "AbstractOutlaw", "Logica… → ["AbstractCamel", "AbstractCavalry", "AbstractCavalryInfantry", "AbstractHandCavalry", "AbstractHeavyCavalry", "Abstrac… |
| `depapalguard` | 教宗护卫 | 1 项 | hp: 200 → 220 |
| `depavisier` | 墙盾手 | 1 项 | cost: {"food": 35, "wood": 50} → {"food": 45, "wood": 40} |
| `derevbarbarywarrior` | 巴巴里战士 | 2 项 | attack_siege: 13 → 16<br>cost: {"food": 100} → {"food": 90} |
| `derevcruzobinfantry` | 克鲁佐布步兵 | 1 项 | cost: {"food": 80, "gold": 35} → {"food": 80, "gold": 30} |
| `derevfilibuster` | 军事冒险家 | 1 项 | attack_siege: 24 → 25 |
| `derevgranadero` | 骑马近卫掷弹兵 | 3 项 | ranged: +AbstractArtillery x0.25, +AbstractLightCavalry x0.5, +AbstractRangedShockInfantry x0.5, +AbstractVillager x0.25<br>armor_ranged: 0.3 → 0.2<br>cost: {"food": 150} → {"food": 120, "gold": 50} |
| `derevmancoinca` | 曼科‧印卡 | 1 项 | type: ["AbstractCanSeeStealth", "AbstractCavalryInfantry", "AbstractHandInfantry", "AbstractHeavyInfantry", "AbstractInfantry… → ["AbstractCanSeeStealth", "AbstractCavalryInfantry", "AbstractHandInfantry", "AbstractHeavyInfantry", "AbstractInfantry… |
| `derevolutionaryscout` | 埃克莱尔 | 2 项 | DefendHandAttack 0.57→0.64s, GuardianAttack 0.57→0.64s, MeleeHandAttack 0.57→0.64s, TrampleHandAttack 0.53→0.56s<br>windup_melee: 0.57 → 0.64 |
| `derevpiratebatch` | 海盗 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `derevstartrekwagon` | 长途马车 | 1 项 | type: ["AbstractCavalry", "AbstractCavalryInfantry", "AbstractGunpowderCavalry", "AbstractRangedCavalry", "AbstractWagon", "L… → ["AbstractCavalry", "AbstractCavalryInfantry", "AbstractGunpowderCavalry", "AbstractRangedCavalry", "LogicalTypeLandMil… |
| `derevvoluntariobatch` | 祖国志愿者 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `derussianhalberdier` | 尉官 | 1 项 | cost: {"food": 50, "gold": 70} → {"food": 70, "gold": 50} |
| `desaloondesperado` | 法外之徒 | 1 项 | type: ["AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer… → ["AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer… |
| `desaloongunslinger` | 持枪杀手 | 1 项 | type: ["AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer… → ["AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer… |
| `desaloonhighwayman` | 拦路强盗 | 1 项 | type: ["AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer… → ["AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer… |
| `desaloonoutlawarsonist` | 马拉塔火兵 | 3 项 | ranged: -AbstractArtillery<br>attack_melee: 8 → 12<br>attack_ranged: 20 → 25 |
| `desettlerhouse` | 拓荒者 | 1 项 | type: ["AbstractBannerArmy", "AbstractVillager", "LogicalTypeLandEconomy", "LogicalTypeLandMilitary", "Military", "Unit", "Un… → ["AbstractBannerArmy", "AbstractVillager", "LogicalTypeLandEconomy", "Military", "Unit", "UnitClass"] |
| `deshotelwarrior` | 弯刀勇士 | 2 项 | description: 快速移动的突击步兵，用两把弯刀快速攻击。擅长对抗轻型步兵。 → 快速移动的冲击兵，用两把弯刀快速攻击。擅长对抗轻型步兵。<br>description_en: Fast moving shock infantry that attacks quickly with two curved swords. Good against light infantry. → Fast moving shock trooper that attacks quickly with two curved swords. Good against light infantry. |
| `deslinger` | 投石索兵 | 3 项 | armor_ranged: 0.3 → 0.2<br>armor_siege: — → 0.2<br>attack_siege: 37 → 40 |
| `despcoutlawlandsknecht` | 流浪的国土佣仆 | 4 项 | -BuildingAttack, -ChargeSwashbucklerAttack, -ChargeSwashbucklerCoverAttack, -CoverBuildingAttack, -CoverHandAttack, -DefendHandAttack, -GuardianAttack, -GuardianCoverAttack, -MeleeHandAttack<br>name: 亡命之徒德国步兵 → 流浪的国土佣仆<br>name_en: Outlaw Landsknecht → Vagrant Landsknecht<br>windup_melee: 0.51 → — |
| `deusminutemenbatch` | 后备民兵 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `dopplesoldner` | 双酬剑士 | 1 项 | name: 都卜勒武士 → 双酬剑士 |
| `envoy` | 使者 | 1 项 | description_en: Dutch reconnaissance unit with a good line that benefits from villager upgrades. → Dutch reconnaissance unit with a good line of sight. Benefits from villager upgrades. |
| `galley` | 桨帆船 | 2 项 | description: 箭船，适用于进行探索、捕鱼或运输。 → 桨帆船，适用于进行探索、捕鱼或运输。<br>name: 箭船 → 桨帆船 |
| `greatbombard` | 重型火炮 | 1 项 | train_time: 100 → 115 |
| `janissary` | 奥斯曼火枪兵 | 1 项 | hp: 215 → 210 |
| `legacygatlingcamel` | 加特林骆驼 | 1 项 | — |
| `mercgreatcannon` | 里尔火炮雇佣兵 | 1 项 | armor_siege: — → 0.25 |
| `merclandsknecht` | 国土佣仆 | 1 项 | name: 德国步兵 → 国土佣仆 |
| `natklamathrifleman` | 克拉马斯步枪兵 | 2 项 | armor_ranged: 0.25 → 0.3<br>hp: 135 → 160 |
| `natmedicineman` | 玛雅祭司 | 3 项 | name: 治疗者 → 玛雅祭司<br>name_en: Healer → Maya Priest<br>age: Commerce Age → Exploration Age |
| `saloonoutlawpistol` | 枪手 | 1 项 | type: ["AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer… → ["AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer… |
| `spahi` | 西帕希 | 2 项 | name: 突厥骑射 → 西帕希<br>cost: {"food": 400} → {"food": 200, "gold": 200} |
| `spcxpchieftwomoon` | 双月酋长 | 5 项 | ranged: -AbstractVillager; melee: -AbstractVillager<br>hp: 500 → 750<br>+SharpshooterAttack 0.59s, +SwashbucklerAttack 0.7s<br>attack_melee: 6 → 15<br>attack_ranged: 12 → 24 |
| `warwagon` | 老练马战车 | 6 项 | -BuildingAttack, -DefendRangedAttack, -MeleeHandAttack, -StaggerRangedAttack<br>description: 由胡斯马拉动的马车，上面装备有加农炮。 → 来自南德意志的远程马车骑兵。擅长对抗骑兵。<br>description_en: Hussite horse-drawn wagon outfitted with cannon. → Ranged wagon cavalry from Southern Germany. Good against cavalry.<br>windup_melee: 0.33 → —<br>range_min: 0 → 2<br>windup_ranged: 0.33 → — |
| `xpcolonialmilitia` | 革命军 | 1 项 | speed: 5 → 4.5 |
| `xpiroquoiswarchief` | 战酋 | 1 项 | +SwashbucklerAttack 0.7s |
| `xpmacehualtin` | 奥托米掷石绳兵 | 2 项 | cost: {"food": 40, "wood": 30} → {"food": 40, "wood": 35}<br>train_time: 23 → 25 |
| `xpmedicinemanaztec` | 战斗祭司 | 1 项 | train_time: 45 → 50 |
| `xpram` | 精锐攻城槌 | 1 项 | +CoverHandAttack 0.36s |
| `xptomahawk` | 战斧兵 | 2 项 | hp: 145 → 150<br>type: ["AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer… → ["AbstractCavalryInfantry", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer", "AbstractRangedInfantry",… |
| `xpwarbow` | 鹰神弓箭手 | 1 项 | ranged: AbstractHeavyInfantry x2→x1.75; melee: AbstractHeavyInfantry x2→x1.75 |
| `ypblackflagarmy` | 黑旗军 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `ypblackflagarmyspawn` | 黑旗军 (颐和园) | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmybritish1` | 英国远征连 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Ranged", "Unit", "UnitCla… |
| `ypconsulatearmybritish2` | 英国远征团 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulatearmybritish3` | 英国远征军 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulatearmydutch1` | 荷兰远征连 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmydutch2` | 荷兰远征团 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmydutch3` | 荷兰远征军 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyfrench1` | 法国远征连 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Ranged", "Unit", "UnitCla… |
| `ypconsulatearmyfrench2` | 法国远征团 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulatearmyfrench3` | 法国远征军 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulatearmygerman1` | 德国远征连 | 2 项 | description: 由德国双手巨剑 (都卜勒武士) 组成的一支军队。\n3 名双手巨剑：能发起扫荡攻击的重装剑士，擅长对付骑兵。 → 由德国双手巨剑 (双酬剑士) 组成的一支军队。\n3 名双手巨剑：能发起扫荡攻击的重装剑士，擅长对付骑兵。<br>type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Ranged", "Unit", "UnitCla… |
| `ypconsulatearmygerman2` | 德国远征团 | 2 项 | description: 由德国双手巨剑 (都卜勒武士) 和护卫德国长枪兵组成的一支军队。\n3 名双手巨剑：能发起扫荡攻击的重装剑士，擅长对付骑兵。\n7 名护卫德国长枪兵：远程攻击射程长的步枪兵单位，但生命值低。 → 由德国双手巨剑 (双酬剑士) 和护卫德国长枪兵组成的一支军队。\n3 名双手巨剑：能发起扫荡攻击的重装剑士，擅长对付骑兵。\n7 名护卫德国长枪兵：远程攻击射程长的步枪兵单位，但生命值低。<br>type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulatearmygerman3` | 德国远征军 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulatearmyottoman1` | 奥斯曼远征连 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Ranged", "Unit", "UnitCla… |
| `ypconsulatearmyottoman2` | 奥斯曼远征团 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulatearmyottoman3` | 奥斯曼远征军 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulatearmyportuguese1` | 葡萄牙远征连 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Ranged", "Unit", "UnitCla… |
| `ypconsulatearmyportuguese2` | 葡萄牙远征军 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulatearmyportuguese3` | 葡萄牙远征军 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulatearmyrussian1` | 俄罗斯远征连 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Ranged", "Unit", "UnitCla… |
| `ypconsulatearmyrussian2` | 俄罗斯远征团 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulatearmyrussian3` | 俄罗斯远征军 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulatearmyspanish1` | 西班牙远征连 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspanish2` | 西班牙远征团 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspanish3` | 西班牙远征军 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspcchinese1` | 中国雇佣兵连 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspcchinese2` | 中国雇佣兵团 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspcchinese3` | 中国雇佣兵军队 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspcdutch1` | 荷兰远征连 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspcdutch2` | 荷兰远征团 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspcdutch3` | 荷兰远征军 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspcindian1` | 印度雇佣兵连 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspcindian2` | 印度雇佣兵团 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspcindian3` | 印度雇佣兵军队 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspcjapanese1` | 日本雇佣兵连 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspcjapanese2` | 日本雇佣兵团 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspcjapanese3` | 日本雇佣兵军队 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Unit", "UnitClass"] |
| `ypconsulatearmyspcportuguese1` | 葡萄牙远征连 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "LogicalTypeLandMilitary", "Military",… → ["AbstractBannerArmy", "AbstractConsulateUnit", "AbstractConsulateUnitColonial", "Military", "Ranged", "Unit", "UnitCla… |
| `ypconsulatearmyspcportuguese2` | 葡萄牙远征军 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulatearmyspcportuguese3` | 葡萄牙远征军 | 1 项 | type: ["AbstractBannerArmy", "AbstractConsulateUnit", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "AbstractConsulateUnit", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypconsulateczapakauhlan` | 德国骑兵 | 2 项 | name: 护卫德国骑兵 → 德国骑兵<br>name_en: Prussian Uhlan → Uhlan |
| `ypconsulatejinete` | 军团枪骑兵 | 1 项 | +LanceHandAttack 0.64s |
| `ypconsulateninja` | 隐身忍者 | 1 项 | melee: +AbstractNativeWarrior x5 |
| `ypconsulatetufancicorps` | 巴格达奥斯曼火枪兵 | 1 项 | train_time: 34 → 40 |
| `ypdacoit` | 马拉塔土匪 | 1 项 | type: ["AbstractCavalryInfantry", "AbstractDacoit", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", … → ["AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer… |
| `ypdaimyoregicide` | 摄政王 | 1 项 | description_en: Extremely powerful Japanese lord who can receive Shipments. Lose your Regent and you are defeated. → Local ruler under your army's protection who can receive Shipments. Lose your Regent and you are defeated. |
| `ypforbiddenarmy` | 禁卫军 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `ypforbiddenarmyspawn` | 禁卫军 (颐和园) | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `yphandmortar` | 轻型迫击炮 | 1 项 | ranged: AbstractSiegeTrooper x6→x2 |
| `ypimperialarmy` | 御林军 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `ypimperialarmyspawn` | 御林军 (颐和园) | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `ypkensei` | 日本武士 | 1 项 | attack_siege: 67 → 60 |
| `ypmandarinarmy` | 满清军队 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Mercenary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Mercenary", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypmercarsonist` | 火兵 | 2 项 | attack_melee: 15 → 22<br>attack_ranged: 28 → 42 |
| `ypmingarmy` | 明军 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `ypmingarmyspawn` | 明军 (颐和园) | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `ypmongolianarmy` | 蒙古军 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `ypmongolianarmyspawn` | 蒙古军 (颐和园) | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `ypmonkdisciple` | 弟子 | 1 项 | train_time: 7 → 14 |
| `ypoldhanarmyspawn` | 旧汉军 (颐和园) | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Ranged", "Unit", "UnitClass"] |
| `yppetwhitetiger` | 宠物白虎华格纳 | 2 项 | description: 一只驯服的白色斑纹老虎，擅长对付守护者和突击步兵。 → 一只驯服的白色斑纹老虎，擅长对付守护者和冲击部队。<br>description_en: A tame tiger with white coloration that is good against guardians and shock infantry. → A tame tiger with white coloration that is good against guardians and shock troops. |
| `yprepentantdacoit` | 归化的土匪 | 1 项 | type: ["AbstractCavalryInfantry", "AbstractDacoit", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", … → ["AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer… |
| `yprepentantlandsknecht` | 归化的国土佣仆 | 1 项 | name: 归化的德国步兵 → 归化的国土佣仆 |
| `yprepentantoutlawpistol` | 归化的枪手 | 1 项 | type: ["AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer… → ["AbstractCavalryInfantry", "AbstractGunpowderTrooper", "AbstractHeavyInfantry", "AbstractInfantry", "AbstractMusketeer… |
| `ypsiegeelephant` | 攻城大象 | 1 项 | armor_ranged: 0.3 → 0.35 |
| `ypsiegeelephantmansabdar` | 曼萨卜达尔攻城大象 | 1 项 | armor_ranged: 0.3 → 0.35 |
| `ypstandardarmy` | 正规军 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `ypstandardarmyspawn` | 正规军 (颐和园) | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypterritorialarmy` | 防卫军 | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `ypterritorialarmyspawn` | 防卫军 (颐和园) | 1 项 | type: ["AbstractBannerArmy", "LogicalTypeLandMilitary", "Military", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Military", "Unit", "UnitClass"] |
| `ypurumi` | 软剑兵 | 1 项 | melee: AbstractCavalry x0.75→x0.6 |
| `ypurumimansabdar` | 曼萨卜达尔软剑兵 | 1 项 | melee: AbstractCavalry x0.75→x0.6 |
| `ypwokouarmy` | 倭寇军队 | 1 项 | type: ["AbstractBannerArmy", "Guardian", "LogicalTypeLandMilitary", "Military", "Ranged", "Unit", "UnitClass"] → ["AbstractBannerArmy", "Guardian", "Military", "Ranged", "Unit", "UnitClass"] |
| `ypzamburak` | 骆驼骑兵 | 1 项 | hp: 120 → 130 |

## 6. 人工干预清单核查

> 以下是历史上人工加进代码 / 覆盖文件的名字。刷新后必须逐条确认：还在不在、入榜理由是否仍成立。

### 6.1 BLACKLIST（永久禁用）

| id | 状态 | 新数据关键值 |
|---|---|---|
| `dequakergun` | 无变化 | hp 200 / 远 500 / 近 —  `[lineup.py]` |
| `learicorn` | 无变化 | hp 600 / 远 — / 近 800  `[lineup.py]` |
| `mediocrebombard` | 无变化 | hp 550 / 远 5000 / 近 —  `[lineup.py]` |
| `ypirregularindians` | 无变化 | hp 130 / 远 21 / 近 10  `[lineup.py]` |
| `yppeasantindians` | 无变化 | hp 120 / 远 — / 近 7  `[lineup.py]` |

### 6.2 BATTLE_BLACKLIST（普通对战禁用）

| id | 状态 | 新数据关键值 |
|---|---|---|
| `deeggarctictruck` | 新增 | hp 60000 / 远 — / 近 1000  `[lineup.py]` |
| `deeggleonardostank` | 无变化 | hp 5000 / 远 800 / 近 —  `[lineup.py]` |
| `deregent` | 新增 | hp 2500 / 远 — / 近 10  `[lineup.py]` |
| `deregenthorse` | 新增 | hp 2000 / 远 — / 近 10  `[lineup.py]` |
| `despcgreatbombardnopop` | 无变化 | hp 475 / 远 500 / 近 —  `[lineup.py]` |
| `despchmlord` | 新增 | hp 2026 / 远 — / 近 10  `[lineup.py]` |
| `despckassahailu` | 无变化 | hp 650 / 远 — / 近 40  `[lineup.py]` |
| `despcmansur` | 无变化 | hp 1000 / 远 — / 近 30  `[lineup.py]` |
| `despcmilitiaofficer` | 无变化 | hp 500 / 远 15 / 近 6  `[lineup.py]` |
| `despcoutlawlandsknecht` | 变更 4 项 | hp 430 / 远 — / 近 54  `[lineup.py]` |
| `fluffy` | 无变化 | hp 600 / 远 — / 近 800  `[lineup.py]` |
| `flyingpurpletapir` | 无变化 | hp 600 / 远 — / 近 800  `[lineup.py]` |
| `georgecrushington` | 无变化 | hp 999999 / 远 — / 近 800  `[lineup.py]` |
| `lazerbear` | 无变化 | hp 106106 / 远 800 / 近 400  `[lineup.py]` |
| `legacygatlingcamel` | 变更 1 项 | hp 9001 / 远 150 / 近 1  `[lineup.py]` |
| `monstertrucka` | 变更 8 项 | hp 60000 / 远 — / 近 1000  `[lineup.py]` |
| `monstertruckt` | 变更 8 项 | hp 60000 / 远 — / 近 1200  `[lineup.py]` |
| `spcdeunclefrankhorse` | 无变化 | hp 1000 / 远 — / 近 6  `[lineup.py]` |
| `spcxpchiefbravewolf` | 变更 5 项 | hp 750 / 远 — / 近 30  `[lineup.py]` |
| `spcxpchiefbullbear` | 变更 7 项 | hp 750 / 远 — / 近 30  `[lineup.py]` |
| `spcxpchieftwomoon` | 变更 5 项 | hp 750 / 远 24 / 近 15  `[lineup.py]` |
| `spcxpcrazyhorse` | 无变化 | hp 1000 / 远 — / 近 6  `[lineup.py]` |
| `spcxpredoubtcannon` | 无变化 | hp 1000 / 远 650 / 近 —  `[lineup.py]` |
| `ypeggicecreamtruck` | 变更 8 项 | hp 60000 / 远 — / 近 1000  `[lineup.py]` |
| `ypspcdaimyokiyomasa` | 无变化 | hp 1000 / 远 — / 近 40  `[lineup.py]` |
| `ypspcdaimyomasamune` | 无变化 | hp 1000 / 远 — / 近 40  `[lineup.py]` |
| `ypspcdaimyotadaoki` | 无变化 | hp 1000 / 远 — / 近 40  `[lineup.py]` |
| `ypspcishida` | 变更 4 项 | hp 2500 / 远 — / 近 70  `[lineup.py]` |

### 6.3 _EXCLUDED_IDS（全局排除）

| id | 状态 | 新数据关键值 |
|---|---|---|
| `despccityguard` | 无变化 | hp 140 / 远 16 / 近 13  `[repository.py]` |
| `despccorsairship` | 无变化 | hp 1500 / 远 100 / 近 —  `[repository.py]` |
| `despcdelugecossack` | 无变化 | hp 225 / 远 — / 近 26  `[repository.py]` |
| `despcgenitour` | 无变化 | hp 175 / 远 15 / 近 —  `[repository.py]` |
| `despchornskirmisher` | 无变化 | hp 100 / 远 17 / 近 4  `[repository.py]` |
| `despchornspearman` | 无变化 | hp 100 / 远 — / 近 10  `[repository.py]` |
| `despcjanissarynopop` | 无变化 | hp 210 / 远 20 / 近 15  `[repository.py]` |
| `despcoutlawmusketeer` | 无变化 | hp 150 / 远 23 / 近 13  `[repository.py]` |
| `despcprivateer` | 无变化 | hp 1000 / 远 100 / 近 —  `[repository.py]` |
| `despcrowboat` | 无变化 | hp 500 / 远 60 / 近 —  `[repository.py]` |
| `despcshotel` | 无变化 | hp 90 / 远 — / 近 26  `[repository.py]` |
| `despcusregular` | 无变化 | hp 280 / 远 30 / 近 15  `[repository.py]` |
| `despcusvolunteer` | 无变化 | hp 140 / 远 30 / 近 10  `[repository.py]` |
| `spcbuccaneer` | 无变化 | hp 190 / 远 — / 近 20  `[repository.py]` |
| `spcfiercecougar` | 无变化 | hp 115 / 远 — / 近 10  `[repository.py]` |
| `spcfireship` | 无变化 | hp 240 / 远 — / 近 900  `[repository.py]` |
| `spcfrigate` | 无变化 | hp 6500 / 远 45 / 近 —  `[repository.py]` |
| `spchoopthrowers` | 无变化 | hp 200 / 远 25 / 近 16  `[repository.py]` |
| `spclizzieflagship` | 无变化 | hp 2200 / 远 82 / 近 —  `[repository.py]` |
| `spcxpvfsoldier` | 无变化 | hp 180 / 远 8 / 近 10  `[repository.py]` |
| `xpspccolonialmilitia` | 无变化 | hp 120 / 远 15 / 近 6  `[repository.py]` |
| `ypspcarrowknight` | 无变化 | hp 150 / 远 10 / 近 6  `[repository.py]` |
| `ypspcarsonist` | 无变化 | hp 120 / 远 16 / 近 16  `[repository.py]` |
| `ypspcriderlesselephant` | 无变化 | hp 2000 / 远 — / 近 —  `[repository.py]` |

### 6.4 icon_overrides（人工图标覆盖）

| id | 状态 | 新数据关键值 |
|---|---|---|
| `ypmandarinarmy` | 变更 1 项 | hp 200 / 远 20 / 近 —  `[icon_overrides.json]` |

## 7. 兵种池变化

| 池子 | 旧 | 新 | 变化 | 进池（新增） | 出池（消失） |
|---|---|---|---|---|---|
| 押注池 | 495 | 547 | +52 | `deconsulateindependencedragoon`, `deconsulatejanissary`, `deespingol`, `defriskytterider`, `dehetman`, `deindependencepolishlancer`, `deindependenceserdyuk`, `delithuanianrider`, `demerccranequinier`, `demercgallowglass`, `demercwagon`, `denatbagpiper`, `denatclansman`, `denatcompanion`, `denathusky`, `denatinuithunter`, `denatinuitqamutik`, `denatlowlanderinfantry`, `denatlowlanderrider`, `denatmercbagpiper`, `denatmercclansman`, `denatmerccompanion`, `denatmerchusky`, `denatmercinuithunter`, `denatmercinuitqamutik` | `denatmercwingedhussar`, `denatwingedhussar` |
| 单挑池 | 511 | 563 | +52 | `deconsulateindependencedragoon`, `deconsulatejanissary`, `deespingol`, `defriskytterider`, `dehetman`, `deindependencepolishlancer`, `deindependenceserdyuk`, `delithuanianrider`, `demerccranequinier`, `demercgallowglass`, `demercwagon`, `denatbagpiper`, `denatclansman`, `denatcompanion`, `denathusky`, `denatinuithunter`, `denatinuitqamutik`, `denatlowlanderinfantry`, `denatlowlanderrider`, `denatmercbagpiper`, `denatmercclansman`, `denatmerccompanion`, `denatmerchusky`, `denatmercinuithunter`, `denatmercinuitqamutik` | `denatmercwingedhussar`, `denatwingedhussar` |
| 黑名单乱斗池 | 21 | 28 | +7 | `deeggarctictruck`, `deregent`, `deregenthorse`, `despchmlord`, `monstertrucka`, `monstertruckt`, `ypeggicecreamtruck` | — |

当前黑名单乱斗池内容：

```
deeggarctictruck, deeggleonardostank, deregent, deregenthorse, despcgreatbombardnopop, despchmlord, despckassahailu, despcmansur, despcmilitiaofficer, despcoutlawlandsknecht, fluffy, flyingpurpletapir, georgecrushington, lazerbear, legacygatlingcamel, monstertrucka, monstertruckt, spcdeunclefrankhorse, spcxpchiefbravewolf, spcxpchiefbullbear, spcxpchieftwomoon, spcxpcrazyhorse, spcxpredoubtcannon, ypeggicecreamtruck, ypspcdaimyokiyomasa, ypspcdaimyomasamune, ypspcdaimyotadaoki, ypspcishida
```

## 8. icon 变化

- 旧 icon 记录：2024；新 icon 记录：2225
- 新增：203；消失：2；来源变化：9
- 新增 id（前 40）：`bpnuggetabandonedigloo`, `bpnuggetwhale`, `dearctictrader`, `dearctictraderdogs`, `dearctictraderdogsled`, `dearctictradersled`, `dechurchdanish`, `dechurchpolish`, `deconsulateindependencedragoon`, `deconsulatejanissary`, `decrateofcoin50`, `decrateofwood50`, `decustomshouse`, `decustomshousewagon`, `dedanishcrateofcoin`, `dedanishcrateoffood`, `dedanishcrateofwood`, `dedojodragoonarmy`, `dedojogrenadierarmy`, `dedojoriflemanarmy`, `dedojouhlanarmy`, `dedrydock`, `deeggarctictruck`, `deeggsleigh`, `deeggsnowboxer`, `deespingol`, `deferalsheep`, `defishinghole`, `defishtrap`, `defolwark`, `defolwarkdefensive`, `defolwarkfarm`, `defolwarkfoodcrate`, `defolwarklivestock`, `defolwarksich`, `defriskytterider`, `deguardianarcticfox`, `deguardianbritisharquebusier`, `deguardianbritishdragoon`, `deguardianbritishlancer`
- 消失 id：`denatmercwingedhussar`, `denatwingedhussar`
- 来源变化 id（前 40）：`deiconbashkirarcher`, `shrine`, `treechristmas`, `ypigctreasureship`, `ypmandarinarmy`, `ypspctreasureship`, `ypspctreasureshipstage1`, `ypspctreasureshipstage2`, `ypspctreasureshipstage3`

## 9. 单位改良 / 通用科技变化

### 9.1 单位改良（unit_upgrades.json）

- 覆盖单位：319 → 342（新增覆盖 25，失去覆盖 2，数据变化 15）
- 新增覆盖：`defriskytterider`, `dehetman`, `delithuanianrider`, `demaltesegun`, `denatbagpiper`, `denatclansman`, `denatcompanion`, `denatinuithunter`, `denatinuitqamutik`, `denatlowlanderinfantry`, `denatlowlanderrider`, `denatmercbagpiper`, `denatmercclansman`, `denatmerccompanion`, `denatmercinuithunter`, `denatmercinuitqamutik`, `denatmerclowlanderinfantry`, `denatmerclowlanderrider`, `denatmercnoaidi`, `denatmercroyalhuntsman`, `denatnoaidi`, `depiechur`, `deregenthorse`, `dewingedhussar`, `minuteman`
- 失去覆盖：`denatmercwingedhussar`, `denatwingedhussar`

| 单位 | 变化明细（按时代） |
|---|---|
| `debattlecanoe` | **5** name: 传奇战斗独木舟 → 传奇作战划艇 |
| `deinsurgente` | **4** name: — → 护卫叛乱者 |
| `denatmercroyalhunter` | **3** name: 老练皇家猎人 → 老练皇家猎兵<br>**4** name: 皇家护卫猎人 → 皇家护卫猎兵 |
| `denatmerctatararcher` | **3** name: 纪律严明的鞑靼步弓手 → 纪律严明的鞑靼弓手<br>**4** name: 光荣的鞑靼步弓手 → 光荣的鞑靼弓手 |
| `denatroyalhunter` | **3** name: 老练皇家猎人 → 老练皇家猎兵<br>**4** name: 皇家护卫猎人 → 皇家护卫猎兵 |
| `denatroyalhuntsman` | **3** name: 老练皇家狩猎者 → 老练皇家猎人<br>**4** name: 皇家护卫狩猎者 → 皇家护卫猎人 |
| `denattatararcher` | **3** name: 纪律严明的鞑靼步弓手 → 纪律严明的鞑靼弓手<br>**4** name: 光荣的鞑靼步弓手 → 光荣的鞑靼弓手 |
| `deordenanca` | **5** name: 帝国法令斯步枪兵 → 帝国法令步枪兵 |
| `deuscavalry` | **3** range_add: {"ranged": 2.0} → {"ranged": 1.0}<br>**4** range_add: {"ranged": 2.0} → {"ranged": 1.0}<br>**5** range_add: {"ranged": 2.0} → {"ranged": 1.0} |
| `dopplesoldner` | **3** name: 老练都卜勒武士 → 老练双酬剑士<br>**4** name: 护卫都卜勒武士 → 护卫双酬剑士<br>**5** name: 帝国都卜勒武士 → 帝国双酬剑士 |
| `mercswisspikeman` | **3** damage_mult: 1.1 → 1.2; hp_mult: 1.1 → 1.2; speed_add: — → 0.25 |
| `mortar` | **4** name: 加利利迫击炮 → 皇家迫击炮<br>**5** name: 帝国加利利迫击炮 → 帝国皇家迫击炮 |
| `natrifleman` | **3** name: 精锐步枪兵 → 精锐切罗基步枪兵 |
| `spahi` | **4** name: 护卫突厥骑射 → 护卫西帕希<br>**5** name: 帝国突厥骑射 → 帝国西帕希 |
| `strelet` | **3** range_add: — → {"ranged": 1.0}<br>**4** range_add: — → {"ranged": 2.0}<br>**5** range_add: {"ranged": 2.0} → {"ranged": 3.0} |

### 9.2 类别科技（土著 / 亡命徒 / 佣兵）

- `AbstractNativeWarrior`：无变化
- `AbstractOutlaw`：无变化
- `Mercenary`：无变化

### 9.3 通用科技（generic_techs.json）

- 科技条数：66 → 73
- 新增（8）：`RGDalkarl`, `RGDanishCrossbowmen`, `RGDanishGrenadiers`, `RGDanishHussars`, `RGDanishMusketeers`, `RGDanishPikemen`, `RGDanishSkirmishers`, `RGLeiciaiCrossbowmen`
- 消失（1）：`ChurchKapikuluCorps`
- 数据变化（43）：`Caracole`, `CavalryCuirass`, `ChurchCorsolet`, `ChurchTillysDiscipline`, `DEChurchPikePush`, `DEChurchSecondGuarantee`, `DEHCContinentalRangers`, `DEHCFedMXBustamante`, `DEHCFedSeminolePonies`, `DEHCHandUnitDamage`, `DEHCHandUnitHitpoints`, `DEHCInfantryDamageItalian`, `DEHCInfantryHitpointsItalian`, `DEHCLiberationMarch`, `DEHCPeninsularGuerrillas`, `DEHCPlanCasaMata`, `DEHCPlanMiramare`, `DEHCPlanTuxtepec`, `DEHCRangedCavalryCombat`, `DEHCRegularCombat`, `Flintlock`, `HCArtilleryCombatFrench`, `HCArtilleryCombatOttoman`, `HCCaballeros`, `HCCavalryDamageBritish`, `HCCavalryHitpointsBritish`, `HCHandCavalryCombatSpanish`, `HCHandCavalryDamageSpanish`, `HCHandCavalryHitpointsSpanish`, `HCHandInfantryCombatSpanish`, `HCHandInfantryHitpointsSpanish`, `HCRidingSchoolGerman2`, `HCXPImprovedGrenades`, `MilitaryDrummers`, `PaperCartridge`, `ProfessionalGunners`, `Rifling`, `Trunion`, `YPHCArtilleryCombatChinese`, `YPHCArtilleryDamageChinese`, `YPHCArtilleryHitpointsChinese`, `YPHCInfantryCombatIndians`, `YPHCOldHanArmyReforms`

## 10. 待决问题（自动汇总）

- [ ] 结构性变更需确认代表动作是否仍正确：`abusgun`
- [ ] 结构性变更需确认代表动作是否仍正确：`cavalryarcher`
- [ ] 结构性变更需确认代表动作是否仍正确：`debolaswarrior`
- [ ] 结构性变更需确认代表动作是否仍正确：`definnishrider`
- [ ] 结构性变更需确认代表动作是否仍正确：`degascenya`
- [ ] 结构性变更需确认代表动作是否仍正确：`demercharquebusier`
- [ ] 结构性变更需确认代表动作是否仍正确：`denatholcanjavelineer`
- [ ] 结构性变更需确认代表动作是否仍正确：`denatlipkatatar`
- [ ] 结构性变更需确认代表动作是否仍正确：`denatmercholcanjavelineer`
- [ ] 结构性变更需确认代表动作是否仍正确：`denatmerclipkatatar`
- [ ] 结构性变更需确认代表动作是否仍正确：`denatmercqizilbash`
- [ ] 结构性变更需确认代表动作是否仍正确：`denatmercsharktoothbowman`
- [ ] 结构性变更需确认代表动作是否仍正确：`denatqizilbash`
- [ ] 结构性变更需确认代表动作是否仍正确：`desalooninquisitor`
- [ ] 结构性变更需确认代表动作是否仍正确：`detank`
- [ ] 结构性变更需确认代表动作是否仍正确：`deunknownnateaglewarrior`
- [ ] 结构性变更需确认代表动作是否仍正确：`monstertrucka`
- [ ] 结构性变更需确认代表动作是否仍正确：`monstertruckt`
- [ ] 结构性变更需确认代表动作是否仍正确：`nateaglewarrior`
- [ ] 结构性变更需确认代表动作是否仍正确：`nathorsearcher`
- [ ] 结构性变更需确认代表动作是否仍正确：`natmerchorsearcher`
- [ ] 结构性变更需确认代表动作是否仍正确：`natsharktoothbowman`
- [ ] 结构性变更需确认代表动作是否仍正确：`spcxpchiefbravewolf`
- [ ] 结构性变更需确认代表动作是否仍正确：`spcxpchiefbullbear`
- [ ] 结构性变更需确认代表动作是否仍正确：`uhlan`
- [ ] 结构性变更需确认代表动作是否仍正确：`xpbowrider`
- [ ] 结构性变更需确认代表动作是否仍正确：`xpcouprider`
- [ ] 结构性变更需确认代表动作是否仍正确：`xpeagleknight`
- [ ] 结构性变更需确认代表动作是否仍正确：`ypeggicecreamtruck`
- [ ] 结构性变更需确认代表动作是否仍正确：`ypspcishida`
- [ ] 结构性变更需确认代表动作是否仍正确：`ypwokoupirate`

> 以上为工具自动汇总；人工核对结论与处置记录见 `docs/games/aoe3-battle.md` §「2026-09-17 追加决议（游戏大版本更新 · 数据快照刷新）」。
