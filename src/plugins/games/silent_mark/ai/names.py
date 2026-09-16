"""AI 昵称：LLM 取名 + 名字池兜底（移植自源项目 `ai/aiNames.ts` + `generateAIName`）。

原则：**取名失败绝不能让开局卡住**。LLM 任何异常都安静回落到名字池。
"""

from __future__ import annotations

import random
from collections.abc import Iterable

from nonebot import logger

from core import llm
from core.errors import LLMConfigError, LLMError

#: ⚠️ `LLMConfigError` **不是** `LLMError` 的子类（它继承 GameError）：
#: 漏了它，一旦没配 api_key，取名就会把整局带崩 —— 而"取名失败"本该是最无害的一种失败。
_LLM_FAILURES = (LLMError, LLMConfigError)

#: 源项目 `DEFAULT_NAMES` 逐字照抄（30 个，像真人的中文昵称）
DEFAULT_NAMES: tuple[str, ...] = (
    "林夕", "陈北", "苏然", "韩明", "沈默", "叶知秋",
    "顾南", "白川", "许晴", "周也", "方远", "江澄",
    "温宁", "魏然", "谢遥", "蓝湛", "赵简", "钱进",
    "孙朗", "李默", "吴声", "郑风", "王逸", "冯唐",
    "褚遂", "卫庄", "秦朗", "杨柳", "朱雀", "何安",
)

_NAME_SYSTEM_PROMPT = (
    "你给狼人杀游戏里的机器人玩家取一个中文昵称。"
    "要求：2~4 个字，像真人在用的网名，不要带符号、数字、引号或任何解释。"
    "只输出昵称本身。"
)


def pick_default_name(existing: Iterable[str], *, rng: random.Random | None = None) -> str:
    """从名字池里挑一个没被占用的。

    源项目用一个模块级游标轮着取 —— 那是**跨局共享的可变状态**（重启/并发下会串），
    这里改成"从没用过的里面随机取"：同样能保证不重名，而且无状态、可复现。
    池子用完了就给 ``旅人N``。
    """
    taken = set(existing)
    free = [name for name in DEFAULT_NAMES if name not in taken]
    if free:
        return (rng or random).choice(free)
    counter = 1
    while f"旅人{counter}" in taken:
        counter += 1
    return f"旅人{counter}"


def _clean(text: str) -> str:
    """把模型可能多嘴带出来的引号/标点/换行清掉。"""
    cleaned = text.strip().strip("「」『』\"'“”‘’　 \n\r\t")
    cleaned = cleaned.splitlines()[0].strip() if cleaned else ""
    return cleaned


async def generate_ai_name(
    existing: Iterable[str], *, rng: random.Random | None = None
) -> str:
    """让 LLM 取个昵称；失败/不合适/重名都回落到名字池。"""
    taken = set(existing)
    try:
        response = await llm.chat(
            [
                llm.LLMMessage(role="system", content=_NAME_SYSTEM_PROMPT),
                llm.LLMMessage(
                    role="user",
                    content=f"已被占用的昵称：{'、'.join(sorted(taken)) or '（无）'}",
                ),
            ],
            scene="silent_mark_ai_name",
        )
    except _LLM_FAILURES as exc:
        logger.warning(f"[ai] 取名调用失败，回落名字池：{exc!r}")
        return pick_default_name(taken, rng=rng)

    name = _clean(response.content)
    if not name or name in taken or not 2 <= len(name) <= 6:
        logger.info(f"[ai] 取名结果不可用（{name!r}），回落名字池")
        return pick_default_name(taken, rng=rng)
    return name
