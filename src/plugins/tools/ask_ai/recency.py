"""时效题：带今天去搜，丢掉明显过期的材料。"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from src.plugins.tools.web_search.searxng import SearchResult

_CN_TZ = timezone(timedelta(hours=8))

_RECENCY = re.compile(
    r"(最近|近日|近期|现在|目前|正在|最新|今天|今日|刚出|新开)"
)

#: 话题本身「时效敏感」的信号词：字面没有「最近/今天」，但答案随时间变。
#: 例：「原神7.1版本卡池信息」——不加时间锚点会搜到几年前的攻略，
#: 而 prompt 里「旧年版本直接忽略」的规则在材料不带年份时无从生效。
_TIMELY_TOPIC = re.compile(
    r"(卡池|池子|抽卡|活动|版本|更新|上线|开服|内测|公测|测试服|"
    r"发售|上市|开卖|开售|预售|"
    r"赛季|赛事|赛程|比赛|排行|榜单|排行榜|"
    r"优惠|折扣|特惠|历史最低|价格|售价|票价|"
    r"票房|销量|流水|阵容|爆料|前瞻|公告|预告|返场|复刻)"
)

_NEWS_DAY = re.compile(r"(今天|今日|最新).{0,6}(新闻|头条|资讯)")

_FILLER = re.compile(
    r"(最近|近日|近期|现如今|现在|目前|正在|最新|今天|今日|刚出|新开)"
    r"|(开了什么|有哪些|有什么)"
)

_OLD_TITLE = re.compile(r"历史上的今天|往期活动汇总")

_GAME_VER = re.compile(
    r"(?:鸣潮|原神|星铁|绝区零)\s*([1-5]\.\d)|([1-5]\.\d)\s*版本"
)

_YEAR = re.compile(r"(20[12]\d)\s*年")


def today_cn(today: date | None = None) -> date:
    if today is not None:
        return today
    return datetime.now(_CN_TZ).date()


def is_recency_question(question: str) -> bool:
    """问句是否「时效相关」。

    两类都算：① 带「最近 / 今天 / 最新」等时效词；
    ② 话题本身时效敏感（卡池 / 版本 / 优惠 / 赛程…）。

    第②类以前被漏掉，导致「原神7.1版本卡池信息」原样去搜、
    也跳过了过期材料过滤 —— 这是搜到旧攻略的直接原因。
    """
    q = question.strip()
    return bool(_RECENCY.search(q)) or bool(_TIMELY_TOPIC.search(q))


def rewrite_search_query(question: str, today: date | None = None) -> str:
    """给时效相关问句补上时间锚点，非时效题原样返回。

    - 带「今天/最新」+ 新闻类 → 锚到「YYYY年M月D日」
    - 其余（含时效敏感话题）→ 锚到「YYYY年M月」
    """
    q = question.strip()
    if not is_recency_question(q):
        return q
    day = today_cn(today)
    core = _FILLER.sub(" ", q)
    core = re.sub(r"\s+", " ", core).strip(" ，。？?、")
    if not core:
        core = q
    if _NEWS_DAY.search(q):
        stamp = f"{day.year}年{day.month}月{day.day}日"
    else:
        stamp = f"{day.year}年{day.month}月"
    if stamp in core:
        return core
    return f"{core} {stamp}"


def _blob(r: SearchResult) -> str:
    return f"{r.title}\n{r.snippet}\n{r.body}"


def _years(text: str) -> list[int]:
    return [int(y) for y in _YEAR.findall(text)]


def _versions(text: str) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    for m in _GAME_VER.finditer(text):
        raw = m.group(1) or m.group(2)
        a, b = raw.split(".", 1)
        found.append((int(a), int(b)))
    return found


def _is_stale(
    r: SearchResult, today: date, corpus_max_ver: tuple[int, int] | None
) -> bool:
    text = _blob(r)
    if _OLD_TITLE.search(r.title):
        return True
    years = _years(text)
    if years and max(years) < today.year and today.year not in years:
        return True
    vers = _versions(text)
    if corpus_max_ver and vers:
        mine = max(vers)
        if mine[0] < corpus_max_ver[0]:
            return True
    return False


def drop_stale_results(
    results: list[SearchResult],
    *,
    today: date | None = None,
) -> list[SearchResult]:
    """丢掉旧年、旧大版本、历史上的今天。若全被丢掉则原样返回，避免空搜去瞎编。"""
    if not results:
        return results
    day = today_cn(today)
    all_vers: list[tuple[int, int]] = []
    for r in results:
        all_vers.extend(_versions(_blob(r)))
    corpus_max = max(all_vers) if all_vers else None
    kept = [r for r in results if not _is_stale(r, day, corpus_max)]
    return kept if kept else results
