"""确定性优先的助手意图判断。"""

from __future__ import annotations

import re

from .models import TaskKind

_IMAGE_ACTION = re.compile(
    r"(搜|找|来|发|要|给我|搞|整|换)(一|几)?(张|幅|个|些|点)?"
    r".{0,16}(图|照片|图片|壁纸|表情包|头像|海报|截图|插画|配图)"
    r"|(图片|照片|壁纸|表情包|头像|插画|配图)(搜索|搜一下|来一张|来几张)"
    r"|搜图|找图|配张图|配个图",
    re.IGNORECASE,
)

_WEB_ACTION = re.compile(
    r"(查一下|查查|搜一下|搜索|联网|上网查|最新|今天|今日|现在|目前|实时|"
    r"新闻|头条|比分|赛程|价格|售价|票价|股价|行情|天气|版本|卡池|活动|"
    r"公告|发售|上线|开服|销量|排行|排行榜|优惠|折扣|来源|出处)",
    re.IGNORECASE,
)

_IMAGE_QUESTION = re.compile(
    r"(这是什么|是什么|图里|图中|图上|截图|识别|认一下|看看|看一下|"
    r"写的什么|文字|报错|怎么解决|什么意思|翻译)",
    re.IGNORECASE,
)

_FOLLOW_IMAGE = re.compile(r"(换一张|再找一张|再来一张|还有吗|其他图|别的图)")

_GREETING = re.compile(
    r"^(你好|您好|hi|hello|嗨|在吗|谢谢|多谢|晚安|早安|早上好|下午好)$",
    re.IGNORECASE,
)


def classify(text: str, *, has_image: bool = False) -> TaskKind:
    q = text.strip()
    if _FOLLOW_IMAGE.search(q):
        return TaskKind.IMAGE_SEARCH
    if has_image and (_IMAGE_QUESTION.search(q) or not q):
        return TaskKind.IMAGE_UNDERSTAND
    if _IMAGE_ACTION.search(q):
        return TaskKind.IMAGE_SEARCH
    if _WEB_ACTION.search(q):
        return TaskKind.WEB_SEARCH
    if not q and has_image:
        return TaskKind.IMAGE_UNDERSTAND
    if _GREETING.match(q):
        return TaskKind.CHAT
    return TaskKind.CHAT


def wants_direct_answer(text: str) -> bool:
    return bool(re.search(r"(直接回答|不用搜|别搜|凭知识回答)", text))


def image_query(text: str) -> str:
    q = text.strip()
    q = re.sub(r"^(请|麻烦|帮我|帮忙|给我|来|找|搜|发|要)(一下|一找|一搜)?", "", q)
    q = re.sub(r"(搜一张|找一张|来一张|发一张|配张图|配个图)", "", q)
    q = re.sub(r"[，。！？!?]+$", "", q).strip()
    return q or text.strip()
