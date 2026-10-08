# AoE3 damagecap 审计报告

## 1. 本次修改后溅射池变化的单位

- seeds 中带 AOE 的条目（ranged/melee 槽）约 **200** 条
- **溅射池与旧模拟器（一律 2×合并基础攻）不同**的槽位：**126** 条
- 有 AOE 但 JSON 无 `damage_cap_*`、仍走 2× fallback 的槽位：**17** 条

旧模拟器：`damage_cap = 合并基础攻 × 2`。
新模拟器：有 `damage_cap_*` 用 protoy；否则仍 2× fallback。

下表「满溅射每人伤害」按 `min(cap / round(aoe_radius), 合并基础攻)` 在满人数溅射时的上限估算。

| id | 中文名 | 槽 | 伤害×弹丸 | aoe | 旧cap | 新cap | Δcap | 旧溅射/人 | 新溅射/人 | Δ |
|----|--------|-----|-----------|-----|-------|-------|------|-----------|-----------|---|
| deeggwoodcattle | 木制牛 | BuildingAttack | 20000.0×1 | 23.0 | 40000 | 400000 | +360000 | 1739.13 | 17391.3 | +15652.2 |
| mediocrebombard | 中型火炮 | CannonAttack | 5000.0×1 | 10.0 | 10000 | 100000 | +90000 | 1000.0 | 5000.0 | +4000.0 |
| legacygatlingcamel | 加特林骆驼 | StaggerRangedAttack | 150.0×6 | 2.0 | 1800 | 3000 | +1200 | 900.0 | 900.0 | +0.0 |
| denmpapalbombard | 教宗重型火炮 | ChargedCannonAttack | 430.0×1 | 7.0 | 860 | 1720 | +860 | 122.86 | 245.71 | +122.9 |
| monstertruckt | 汤米卡车 | TrampleHandAttack | 1200.0×1 | 6.0 | 2400 | 3000 | +600 | 400.0 | 500.0 | +100.0 |
| ypspcriderlesselephant | 没人骑的大象 | TrampleHandAttack | 1200.0×1 | 6.0 | 2400 | 3000 | +600 | 400.0 | 500.0 | +100.0 |
| demaltesefireship | 火战船 | HandAttack | 500.0×1 | 2.0 | 1000 | 1500 | +500 | 500.0 | 500.0 | +0.0 |
| ypfireship | 火帆船 | HandAttack | 500.0×1 | 2.0 | 1000 | 1500 | +500 | 500.0 | 500.0 | +0.0 |
| detank | 莱昂纳多的战车 | RoundelCascadeAttack | 300.0×1 | 4.0 | 600 | 150 | -450 | 150.0 | 37.5 | -112.5 |
| detank | 莱昂纳多的战车 | RoundelExplodeAttack | 300.0×1 | 4.0 | 600 | 150 | -450 | 150.0 | 37.5 | -112.5 |
| detank | 莱昂纳多的战车 | RoundelMultiAttack | 300.0×1 | 4.0 | 600 | 150 | -450 | 150.0 | 37.5 | -112.5 |
| deespingol | 雷筒 | CannonAttack | 66.0×3 | 2.0 | 396 | 60 | -336 | 198.0 | 30.0 | -168.0 |
| organgun | 风琴炮 | CannonAttack | 33.0×6 | 2.0 | 396 | 60 | -336 | 198.0 | 30.0 | -168.0 |
| ypsiegeelephantmansabdar | 曼萨卜达尔攻城大象 | CannonAttack | 40.0×1 | 1.0 | 80 | 400 | +320 | 40.0 | 40.0 | +0.0 |
| xpgatlinggun | 加特林机枪 | CannonAttack | 30.0×6 | 2.0 | 360 | 60 | -300 | 180.0 | 30.0 | -150.0 |
| cannon | 重型加农炮 | CaseShotAttack | 20.0×7 | 6.0 | 280 | 40 | -240 | 46.67 | 6.67 | -40.0 |
| degunboat | 炮舰 | RangedAttack | 25.0×1 | 1.0 | 50 | 280 | +230 | 25.0 | 25.0 | +0.0 |
| caravel | 卡拉维尔战舰 | LongRangeAttack | 100.0×1 | 4.0 | 200 | 400 | +200 | 50.0 | 100.0 | +50.0 |
| demerccapturedmortar | 被夺取的迫击炮 | CannonAttack | 416.67×1 | 1.0 | 833 | 1000 | +167 | 416.67 | 416.67 | +0.0 |
| destartingunitprivateer | 勇敢的私掠船 | BroadsideAttack | 20.0×1 | 3.0 | 40 | 200 | +160 | 13.33 | 20.0 | +6.7 |
| destartingunitprivateer | 勇敢的私掠船 | GuardianAttack | 20.0×1 | 1.0 | 40 | 200 | +160 | 20.0 | 20.0 | +0.0 |
| destartingunitprivateer | 勇敢的私掠船 | RangedAttack | 20.0×1 | 1.0 | 40 | 200 | +160 | 20.0 | 20.0 | +0.0 |
| xphorseartillery | 马炮兵 | CaseShotAttack | 12.5×7 | 5.0 | 175 | 25 | -150 | 35.0 | 5.0 | -30.0 |
| demercgatlingcamel | 加特林骆驼 | StaggerRangedAttack | 14.5×6 | 2.0 | 174 | 29 | -145 | 87.0 | 14.5 | -72.5 |
| ypmonkchinese | 少林大师 | RoundhouseAttack | 170.0×1 | 3.0 | 340 | 200 | -140 | 113.33 | 66.67 | -46.7 |
| ypmonkchinese2 | 少林大师 | RoundhouseAttack | 170.0×1 | 3.0 | 340 | 200 | -140 | 113.33 | 66.67 | -46.7 |
| falconet | 鹰炮 | CaseShotAttack | 10.0×7 | 5.0 | 140 | 20 | -120 | 28.0 | 4.0 | -24.0 |
| legacygatlingcamel | 加特林骆驼 | BuildingAttack | 15.0×6 | 2.0 | 180 | 300 | +120 | 90.0 | 90.0 | +0.0 |
| ypsiegeelephant | 攻城大象 | CannonAttack | 40.0×1 | 1.0 | 80 | 200 | +120 | 40.0 | 40.0 | +0.0 |
| dechincharaft | 钦查木筏 | BuildingAttack | 25.0×3 | 1.0 | 150 | 50 | -100 | 75.0 | 50.0 | -25.0 |
| dechincharaft | 钦查木筏 | RangedAttack | 25.0×3 | 1.0 | 150 | 50 | -100 | 75.0 | 50.0 | -25.0 |
| degalleass | 三桅帆装军舰 | ShuntAttack | 400.0×1 | 3.0 | 800 | 700 | -100 | 266.67 | 233.33 | -33.3 |
| deminer | 矿工 | BuildingAttack | 50.0×1 | 5.0 | 100 | 200 | +100 | 20.0 | 40.0 | +20.0 |
| demercnapoleongun | 拿破仑炮 | CaseShotAttack | 7.5×7 | 3.0 | 105 | 16 | -89 | 35.0 | 5.33 | -29.7 |
| merclandsknecht | 国土佣仆 | ChargeSwashbucklerAttack | 43.0×1 | 2.0 | 86 | 162 | +76 | 43.0 | 43.0 | +0.0 |
| deminer | 矿工 | GrenadeAttack | 30.0×1 | 5.0 | 60 | 120 | +60 | 12.0 | 24.0 | +12.0 |
| galley | 桨帆船 | RangedAttack | 100.0×1 | 1.0 | 200 | 140 | -60 | 100.0 | 100.0 | +0.0 |
| despcoutlawlandsknecht | 流浪的国土佣仆 | ChargeSwashbucklerAttack | 54.0×1 | 2.0 | 108 | 162 | +54 | 54.0 | 54.0 | +0.0 |
| ypmercarsonist | 火兵 | RocketAttack | 42.0×1 | 3.0 | 84 | 32 | -52 | 28.0 | 10.67 | -17.3 |
| demercnapoleongun | 拿破仑炮 | BombardAttack | 75.0×1 | 2.0 | 150 | 200 | +50 | 75.0 | 75.0 | +0.0 |
| demercnapoleongun | 拿破仑炮 | CannonAttack | 75.0×1 | 2.0 | 150 | 200 | +50 | 75.0 | 75.0 | +0.0 |
| russiancannon | 大型加农炮 | CannonAttack | 650.0×1 | 6.0 | 1300 | 1350 | +50 | 216.67 | 225.0 | +8.3 |
| spcxpredoubtcannon | 防卫据点加农炮 | CannonAttack | 650.0×1 | 6.0 | 1300 | 1350 | +50 | 216.67 | 225.0 | +8.3 |
| ypconsulategendarmes | 护卫胸甲骑兵 | BuildingAttack | 25.0×1 | 2.0 | 50 | 100 | +50 | 25.0 | 25.0 | +0.0 |
| ypwarjunk | 战争帆船 | BroadsideAttack | 35.0×1 | 1.0 | 70 | 120 | +50 | 35.0 | 35.0 | +0.0 |
| ypwarjunksittingducks | 搁浅的战争帆船 | BroadsideAttack | 35.0×1 | 1.0 | 70 | 120 | +50 | 35.0 | 35.0 | +0.0 |
| culverin | 长管炮 | CaseShotAttack | 4.0×7 | 3.0 | 56 | 8 | -48 | 18.67 | 2.67 | -16.0 |
| deleathercannon | 皮革加农炮 | CaseShotAttack | 4.0×7 | 4.0 | 56 | 8 | -48 | 14.0 | 2.0 | -12.0 |
| demercgallowglass | 加洛格拉什 | MeleeHandAttack | 30.0×1 | 2.0 | 60 | 105 | +45 | 30.0 | 30.0 | +0.0 |
| demercdhow | 達烏战船 | BroadsideAttack | 20.0×1 | 1.0 | 40 | 80 | +40 | 20.0 | 20.0 | +0.0 |
| deordergalley | 军团桨帆船 | RangedAttack | 65.0×1 | 1.0 | 130 | 170 | +40 | 65.0 | 65.0 | +0.0 |
| dehetman | 大元帅 | HandAttack | 6.0×1 | 2.0 | 12 | 50 | +38 | 6.0 | 6.0 | +0.0 |
| igcdeunclefrankhorse | 法兰克叔叔 | MeleeHandAttack | 6.0×1 | 1.0 | 12 | 50 | +38 | 6.0 | 6.0 | +0.0 |
| igcxpcrazyhorse | 疯马 | MeleeHandAttack | 6.0×1 | 1.0 | 12 | 50 | +38 | 6.0 | 6.0 | +0.0 |
| spcdeunclefrankhorse | 法兰克叔叔 | HandAttack | 6.0×1 | 1.0 | 12 | 50 | +38 | 6.0 | 6.0 | +0.0 |
| spcxpcrazyhorse | 疯马 | HandAttack | 6.0×1 | 1.0 | 12 | 50 | +38 | 6.0 | 6.0 | +0.0 |
| xplakotawarchief | 战酋 | HandAttack | 6.0×1 | 2.0 | 12 | 50 | +38 | 6.0 | 6.0 | +0.0 |
| ypmercarsonist | 火兵 | VolleyRangedAttack | 42.0×1 | 3.0 | 84 | 48 | -36 | 28.0 | 16.0 | -12.0 |
| demercgallowglass | 加洛格拉什 | ChargeSwashbucklerAttack | 50.0×1 | 2.0 | 100 | 135 | +35 | 50.0 | 50.0 | +0.0 |
| desloop | 单桅战船 | ChargeBroadsideAttack | 34.0×1 | 1.0 | 68 | 100 | +32 | 34.0 | 34.0 | +0.0 |
| ypmonkindian | 婆罗门 | GuardianAttack | 4.0×1 | 2.0 | 8 | 40 | +32 | 4.0 | 4.0 | +0.0 |
| ypmonkindian | 婆罗门 | HandAttack | 4.0×1 | 2.0 | 8 | 40 | +32 | 4.0 | 4.0 | +0.0 |
| ypmonkindian2 | 婆罗门 | GuardianAttack | 4.0×1 | 2.0 | 8 | 40 | +32 | 4.0 | 4.0 | +0.0 |
| ypmonkindian2 | 婆罗门 | HandAttack | 4.0×1 | 2.0 | 8 | 40 | +32 | 4.0 | 4.0 | +0.0 |
| ypspcbrahminhealer | 婆罗门治疗者 | GuardianAttack | 4.0×1 | 2.0 | 8 | 40 | +32 | 4.0 | 4.0 | +0.0 |
| ypspcbrahminhealer | 婆罗门治疗者 | HandAttack | 4.0×1 | 2.0 | 8 | 40 | +32 | 4.0 | 4.0 | +0.0 |
| ypmorutaru | 日本迫击炮 | BarrageAttack | 19.0×1 | 4.0 | 38 | 69 | +31 | 9.5 | 17.25 | +7.8 |
| demercxebec | 谢贝克帆船 | BroadsideAttack | 15.0×1 | 1.0 | 30 | 60 | +30 | 15.0 | 15.0 | +0.0 |
| derevteutonicknight | 条顿骑士 | GuardianAttack | 35.0×1 | 2.0 | 70 | 40 | -30 | 35.0 | 20.0 | -15.0 |
| desaloonharpooner | 鱼叉手 | GrenadeAttack | 15.0×1 | 1.0 | 30 | 60 | +30 | 15.0 | 15.0 | +0.0 |
| galley | 桨帆船 | BroadsideAttack | 40.0×1 | 1.0 | 80 | 50 | -30 | 40.0 | 40.0 | +0.0 |
| mortar | 迫击炮 | BarrageAttack | 30.0×1 | 4.0 | 60 | 90 | +30 | 15.0 | 22.5 | +7.5 |
| spclizzieflagship | 莉丝的旗舰 | BroadsideAttack | 35.0×1 | 1.0 | 70 | 100 | +30 | 35.0 | 35.0 | +0.0 |
| xpskullknight | 骷髅武士 | ObsidianChargeAttack | 30.0×1 | 4.0 | 60 | 90 | +30 | 15.0 | 22.5 | +7.5 |
| ypconsulatemortar | 迫击炮 | BarrageAttack | 30.0×1 | 4.0 | 60 | 90 | +30 | 15.0 | 22.5 | +7.5 |
| ypfune | 日本船 | BroadsideAttack | 25.0×1 | 1.0 | 50 | 80 | +30 | 25.0 | 25.0 | +0.0 |
| xpskullknight | 骷髅武士 | MeleeHandAttack | 20.0×1 | 2.0 | 40 | 68 | +28 | 20.0 | 20.0 | +0.0 |
| denatcompanion | 伙伴骑兵 | LanceChargeAttack | 28.0×1 | 1.0 | 56 | 82 | +26 | 28.0 | 28.0 | +0.0 |
| denatmerccompanion | 伙伴骑兵 | LanceChargeAttack | 28.0×1 | 1.0 | 56 | 82 | +26 | 28.0 | 28.0 | +0.0 |
| demerccapturedmortar | 被夺取的迫击炮 | BarrageAttack | 25.0×1 | 4.0 | 50 | 75 | +25 | 12.5 | 18.75 | +6.2 |
| deoutlawwhalingship | 捕鲸船 | GrenadeAttack | 37.5×1 | 4.0 | 75 | 100 | +25 | 18.75 | 25.0 | +6.2 |
| ypflamethrower | 猛火油柜 | FlameAttack | 5.0×1 | 1.0 | 10 | 35 | +25 | 5.0 | 5.0 | +0.0 |
| derevknightbrother | 骑士兄弟团 | LanceChargeAttack | 50.0×1 | 2.0 | 100 | 120 | +20 | 50.0 | 50.0 | +0.0 |
| derevteutonicknight | 条顿骑士 | MeleeHandAttack | 35.0×1 | 2.0 | 70 | 50 | -20 | 35.0 | 25.0 | -10.0 |
| desaloonharpooner | 鱼叉手 | RangedAttack | 20.0×1 | 0.25 | 40 | 60 | +20 | 0 | 0 | +0.0 |
| xptlaloccanoe | 雨神独木舟 | RangedAttack | 50.0×1 | 1.0 | 100 | 80 | -20 | 50.0 | 50.0 | +0.0 |
| xpwarcanoe | 战斗独木舟 | RangedAttack | 40.0×1 | 1.0 | 80 | 60 | -20 | 40.0 | 40.0 | +0.0 |
| ypmorutaru | 日本迫击炮 | CannonAttack | 385.0×1 | 1.0 | 770 | 750 | -20 | 385.0 | 385.0 | +0.0 |
| xpcolonialmilitia | 革命军 | GrenadeAttack | 19.0×1 | 2.0 | 38 | 57 | +19 | 19.0 | 19.0 | +0.0 |
| desaloonowlhoot | 逃犯 | BuckshotChargeAttack | 3.0×6 | 2.5 | 36 | 18 | -18 | 18.0 | 9.0 | -9.0 |
| desaloonsailor | 水手 | BuckshotChargeAttack | 3.0×6 | 3.0 | 36 | 18 | -18 | 12.0 | 6.0 | -6.0 |
| saloonoutlawrifleman | 叛兵 | BuckshotChargeAttack | 3.0×6 | 2.0 | 36 | 18 | -18 | 18.0 | 9.0 | -9.0 |
| denatmercroyalmusketeer | 皇家火枪兵 | MortarAttack | 20.0×1 | 2.0 | 40 | 57 | +17 | 20.0 | 20.0 | +0.0 |
| denatroyalmusketeer | 皇家火枪兵 | MortarAttack | 20.0×1 | 2.0 | 40 | 57 | +17 | 20.0 | 20.0 | +0.0 |
| demercbattleship | 战列舰 | BroadsideAttack | 32.0×1 | 1.0 | 64 | 80 | +16 | 32.0 | 32.0 | +0.0 |
| derevcalifornio | 加利福尼亚西裔兵 | StaggerRangedAttack | 20.0×1 | 2.0 | 40 | 24 | -16 | 20.0 | 12.0 | -8.0 |
| definnishrider | 芬兰轻装骑兵 | StaggerRangedAttack | 20.0×1 | 1.0 | 40 | 52 | +12 | 20.0 | 20.0 | +0.0 |
| dehoopthrower | 火焰兵 | RocketAttack | 22.0×1 | 2.0 | 44 | 32 | -12 | 22.0 | 16.0 | -6.0 |
| xpcouprider | 塔斯云坎游荡者 | MeleeHandAttack | 14.0×1 | 2.0 | 28 | 40 | +12 | 14.0 | 14.0 | +0.0 |
| depapalguard | 教宗护卫 | ChargeHalberdAttack | 13.0×1 | 1.0 | 26 | 15 | -11 | 13.0 | 13.0 | +0.0 |
| degalleass | 三桅帆装军舰 | RoundelAttack | 40.0×1 | 2.0 | 80 | 70 | -10 | 40.0 | 35.0 | -5.0 |
| degalleass | 三桅帆装军舰 | RoundelPierceAttack | 40.0×1 | 2.0 | 80 | 70 | -10 | 40.0 | 35.0 | -5.0 |
| desaloonoutlawarsonist | 马拉塔火兵 | VolleyRangedAttack | 25.0×1 | 3.0 | 50 | 60 | +10 | 16.67 | 20.0 | +3.3 |
| desloop | 单桅战船 | RangedAttack | 110.0×1 | 1.0 | 220 | 230 | +10 | 110.0 | 110.0 | +0.0 |
| desloop | 单桅战船 | RangedAttackContained | 110.0×1 | 1.0 | 220 | 230 | +10 | 110.0 | 110.0 | +0.0 |
| spcxpchiefbravewolf | 狼勇士酋长 | HandAttack | 30.0×1 | 1.0 | 60 | 50 | -10 | 30.0 | 30.0 | +0.0 |
| spcxpchiefbullbear | 巨熊酋长 | HandAttack | 30.0×1 | 1.0 | 60 | 50 | -10 | 30.0 | 30.0 | +0.0 |
| ypflamingarrow | 火焰之箭 | CannonAttack | 75.0×1 | 2.0 | 150 | 140 | -10 | 75.0 | 70.0 | -5.0 |
| yptekkousen | 铁甲船 | BroadsideAttack | 35.0×1 | 1.0 | 70 | 80 | +10 | 35.0 | 35.0 | +0.0 |
| ypmercflailiphant | 连枷象 | GuardianAttack | 10.0×1 | 2.0 | 20 | 28 | +8 | 10.0 | 10.0 | +0.0 |
| ypmercflailiphant | 连枷象 | MeleeHandAttack | 10.0×1 | 2.0 | 20 | 28 | +8 | 10.0 | 10.0 | +0.0 |
| ypmercflailiphantmansabdar | 曼萨卜达尔连枷象 | GuardianAttack | 10.0×1 | 2.0 | 20 | 28 | +8 | 10.0 | 10.0 | +0.0 |
| ypmercflailiphantmansabdar | 曼萨卜达尔连枷象 | MeleeHandAttack | 10.0×1 | 2.0 | 20 | 28 | +8 | 10.0 | 10.0 | +0.0 |
| deinsurgente | 叛乱者 | LassoChargeAttack | 15.0×1 | 2.0 | 30 | 36 | +6 | 15.0 | 15.0 | +0.0 |
| deregular | 正规军 | MortarAttack | 22.0×1 | 1.0 | 44 | 50 | +6 | 22.0 | 22.0 | +0.0 |
| derevstarshyna | 哥萨克军官 | MeleeHandAttack | 32.0×1 | 3.0 | 64 | 70 | +6 | 21.33 | 23.33 | +2.0 |
| desaloonbandido | 强盗 | DynamiteAttackCharge | 17.0×1 | 3.0 | 34 | 40 | +6 | 11.33 | 13.33 | +2.0 |
| natmerctracker | 克里追踪者 | EagleEyeChargeAttack | 13.0×1 | 2.0 | 26 | 20 | -6 | 13.0 | 10.0 | -3.0 |
| nattracker | 克里追踪者 | EagleEyeChargeAttack | 13.0×1 | 2.0 | 26 | 20 | -6 | 13.0 | 10.0 | -3.0 |
| deindependencepolishlancer | 维斯瓦马刀骑兵 | LanceChargeAttack | 35.0×1 | 2.5 | 70 | 75 | +5 | 35.0 | 35.0 | +0.0 |
| derevpolishlancer | 维斯瓦马刀骑兵 | LanceChargeAttack | 35.0×1 | 2.5 | 70 | 75 | +5 | 35.0 | 35.0 | +0.0 |
| ypkensei | 日本武士 | MeleeHandAttack | 28.0×1 | 1.0 | 56 | 60 | +4 | 28.0 | 28.0 | +0.0 |
| ypurumi | 软剑兵 | MeleeHandAttack | 17.0×1 | 1.0 | 34 | 38 | +4 | 17.0 | 17.0 | +0.0 |
| ypurumimansabdar | 曼萨卜达尔软剑兵 | MeleeHandAttack | 17.0×1 | 1.0 | 34 | 38 | +4 | 17.0 | 17.0 | +0.0 |
| desaloonvaquero | 牲畜盗贼 | LassoAttackCharge | 18.0×1 | 1.0 | 36 | 38 | +2 | 18.0 | 18.0 | +0.0 |
| ypnatconquistador | 西班牙征服者 | StaggerRangedAttack | 18.0×1 | 1.0 | 36 | 38 | +2 | 18.0 | 18.0 | +0.0 |

## 2. basedamagecap 调研（protoy.xml）

- 含 `damagearea` 的 protoaction：**651**
- 同时有 `damagecap`：**596**
- 有 `damagearea` 但无 `damagecap`：**55**（斗蛐蛐用 2× fallback）
- 含 `basedamagecap` 子节点：**11**
- `basedamagecap` 取值分布：`{'1': 11}`

### 含义（结合 techtreey `subtype="DamageCap"` + `relativity="BasePercent"`）

- `basedamagecap` **不是**「溅射池 = 1×攻击力」的意思。
- 多为 `1`，表示该动作的 DamageCap 会随科技/升级按**基础值百分比**缩放（与 `damage` 升级方式同类）。
- 斗蛐蛐当前**不模拟**科技升级，单局内 cap 用 protoy 静态 `damagecap` 即可。

### 是否把 fallback 从 2× 改成 1×？

**不建议。** 理由：

1. `basedamagecap=1` 是升级缩放标记，不是 fallback 倍数。
2. 无 `damagecap` 的 AOE 动作在数据里很少；有 cap 时绝大多数 `damagecap ≈ 2×damage`（与社区一致）。
3. 改成 1× 会使「无 cap 字段」的少数单位溅射减半，与 DE 常见 2× 默认不符。

