"""红警2斗蛐蛐 —— 播报话术池。"""

from __future__ import annotations

# 按武器/攻击类型 × 死亡数档位的动词（详细模式时间窗口用）
ACTION_WORDS: dict[str, dict[str, list[str]]] = {
    "ranged_infantry": {
        "1": ["开火命中", "一枪击倒", "精准点射", "步枪命中"],
        "2-3": ["扫射", "一轮点射", "火力压制", "连发射击"],
        "4+": ["集火扫射", "弹幕倾泻", "火力覆盖", "扫平"],
    },
    "ranged_artillery": {
        "1": ["炮击命中", "一发入魂", "开炮", "炮弹命中"],
        "2-3": ["炮击覆盖", "连续轰击", "炮火洗地", "炮弹连珠"],
        "4+": ["炮火犁地", "毁灭性轰击", "炮弹倾泻", "夷为平地"],
    },
    "ranged_missile": {
        "1": ["导弹命中", "一发制导", "精确打击", "导弹击落"],
        "2-3": ["导弹齐射", "连续打击", "饱和攻击", "多枚命中"],
        "4+": ["导弹覆盖", "饱和打击", "弹雨倾泻", "火力风暴"],
    },
    "ranged_energy": {
        "1": ["能量束命中", "电弧击中", "光束贯穿", "辐射灼烧"],
        "2-3": ["能量扫射", "电弧连击", "光束覆盖", "辐射扩散"],
        "4+": ["能量风暴", "电弧横扫", "光束犁地", "辐射洗地"],
    },
    "crush": {
        "1": ["碾过", "碾压", "轧扁", "履带压过"],
        "2-3": ["连续碾压", "履带横扫", "一路轧过", "碾压推进"],
        "4+": ["碾压夷平", "履带犁地", "碾压屠戮", "铁流碾压"],
    },
    "melee": {
        "1": ["撕咬", "近身击杀", "扑倒", "一口咬死"],
        "2-3": ["连续撕咬", "扑杀数人", "近身横扫", "连咬带扑"],
        "4+": ["撕咬屠戮", "扑杀一片", "近身清场", "咬倒一片"],
    },
}

FIRST_ATTACK_MODE_TEMPLATES: dict[str, list[str]] = {
    "ranged": [
        "🔔 {time:.1f}s，{attacker_emoji} {attacker_name}率先开火！",
        "🔔 {time:.1f}s，进入射程！{attacker_emoji} {attacker_name}打响第一枪！",
        "🔔 {time:.1f}s，枪炮声起！{attacker_emoji} {attacker_name}率先射击！",
    ],
    "melee": [
        "⚔️ {time:.1f}s，{attacker_emoji} {attacker_name}贴脸了！近战开始！",
        "⚔️ {time:.1f}s，{attacker_emoji} {attacker_name}冲入敌阵！",
        "⚔️ {time:.1f}s，短兵相接！{attacker_emoji} {attacker_name}率先接敌！",
    ],
    "crush": [
        "🛞 {time:.1f}s，{attacker_emoji} {attacker_name}开始碾压推进！",
        "🛞 {time:.1f}s，{attacker_emoji} {attacker_name}履带压上敌阵！",
    ],
}

UNIT_WIPED_TEMPLATES: list[str] = [
    "💀 {emoji} {unit_name} 全灭！（共{count}人）",
    "💀 {emoji} {unit_name} ×{count} 全军覆没！",
    "💀 {emoji} {unit_name} 已被全歼（{count}人）",
]
