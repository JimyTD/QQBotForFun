"""静夜标记 · 规则内核（纯逻辑）。

设计约束（M0 起就成立，后续不得破坏）：

1. **零依赖**：本包不 import NoneBot，也不 import ``core.*``。
   它只依赖传入的 state dict。
2. **无 IO**：不广播、不私聊、不读数据库、不读时钟。
3. **状态是普通 dict**：与 ``GameContext.state`` 同构且 JSON 可序列化，
   因此游戏本体、CLI 适配器、AI 上下文构建器可以共用同一份规则。
4. **玩家标识是 ``pid: str``**：语义等价于源项目的 ``userId: string``。
   ``pid`` 与 QQ 号的映射由游戏本体持有（``state["seat_owners"]``），
   规则内核**永远不接触 QQ 号**。

命名约定：相对源项目（TypeScript）统一把 camelCase 改为 snake_case，
例如 ``nightActions`` → ``night_actions``、``roleState.antidoteUsed`` →
``role_state.antidote_used``。字段语义不变。

模块划分（对应源项目文件）：

===============  ============================================  ==========================
本模块            职责                                           源项目对应
===============  ============================================  ==========================
``constants``     角色/阵营/阶段/死因/物品/理由/预设板子          ``shared/constants.ts``
``types``         状态字典的形状定义与构造函数                    ``shared/types/game.ts``
``roles``         10 个角色处理器                                ``server/game/roles/*``
``fallback``      玩家未行动时的服务端兜底（非 AI 专用）          ``GameManager.submitDisconnectedFallback``
``resolve``       结算与校验（夜晚/投票/胜负/标记/配置）          ``rules.ts`` + ``validators.ts``
``private_info``  按角色裁剪的私有信息（信息防火墙）              ``shared/privateInfo.ts``
===============  ============================================  ==========================
"""
