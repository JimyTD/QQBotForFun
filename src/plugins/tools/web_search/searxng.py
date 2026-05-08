"""搜索客户端封装（百度百科优先 → 搜狗 fallback）。

策略：
1. 先查百度百科（结构化知识，内容准确完整）
2. 百科没有对应词条时，fallback 到搜狗网页搜索

为什么这样设计：
- 百度百科能直接返回完整、准确的知识正文
- 搜狗网页搜索只能拿到标题和零碎摘要，质量不够
- 维基百科国内不可达
- 知乎等站点反爬 403
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import quote

import httpx
from nonebot import logger


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


@dataclass
class SearchResult:
    """单条搜索结果。"""

    title: str
    url: str
    snippet: str


# ==================== 百度百科 ====================

# 常见疑问词/停用词，用于从查询中提取核心实体
_STOP_WORDS = re.compile(
    r"(是什么|有什么|怎么样|怎么|如何|什么是|什么|为什么|哪些|哪个|多少|"
    r"几个|吗|呢|吧|啊|的|了|在|有|和|与|或|能|会|要|可以|应该|"
    r"效果|作用|区别|特点|优势|用途|含义|意思|介绍|简介|"
    r"请问|请|告诉我|帮我|查一下|搜一下)",
    re.IGNORECASE,
)


def _extract_baike_keywords(query: str) -> list[str]:
    """从用户查询中提取可能的百科词条名。

    返回多个候选（从最具体到最宽泛），依次尝试查百科。
    """
    candidates: list[str] = []

    # 原始查询（去首尾空格）
    q = query.strip()

    # 去掉疑问词后的核心部分
    core = _STOP_WORDS.sub("", q).strip()
    if core and core != q:
        candidates.append(core)

    # 原始查询本身也试试
    candidates.append(q)

    # 如果查询有空格，取最长的非停用词片段
    parts = [p.strip() for p in q.split() if len(p.strip()) >= 2]
    for p in parts:
        cleaned = _STOP_WORDS.sub("", p).strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

    # 去重保序
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        if c not in seen and len(c) >= 2:
            seen.add(c)
            result.append(c)

    return result[:4]  # 最多尝试 4 个

def _clean_html(html: str) -> str:
    """移除 HTML 标签、script、style，返回纯文本。"""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    # 合并多余空白
    text = re.sub(r"\n\s*\n", "\n", text)
    return text.strip()


async def _search_baike(query: str) -> list[SearchResult]:
    """尝试从百度百科获取词条内容。

    从查询中提取核心关键词，依次尝试查百度百科。
    如果命中词条，提取摘要正文。
    """
    candidates = _extract_baike_keywords(query)
    if not candidates:
        return []

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for keyword in candidates:
            url = f"https://baike.baidu.com/item/{quote(keyword)}"
            try:
                resp = await client.get(url, headers=_HEADERS)
                if resp.status_code != 200:
                    continue
                html = resp.text
            except Exception:  # noqa: BLE001
                continue

            # 检查是否命中词条
            if len(html) < 5000 or "百度百科错误页" in html or "error.html" in str(resp.url):
                continue

            # 提取正文
            text = _clean_html(html)

            # 找关键词附近的内容
            content = ""
            for kw in [keyword] + [query]:
                idx = text.find(kw)
                if idx > 0:
                    content = text[idx:idx + 600]
                    break

            if not content:
                if len(text) > 2000:
                    content = text[500:1100]
                else:
                    content = text[:600]

            # 清理
            lines = [l.strip() for l in content.splitlines() if l.strip() and len(l.strip()) > 5]
            content = "\n".join(lines[:15])

            if len(content) < 30:
                continue

            logger.info(f"[web_search] 百度百科命中词条: {keyword}")
            return [SearchResult(
                title=f"{keyword} - 百度百科",
                url=str(resp.url),
                snippet=content,
            )]

    return []


# ==================== 搜狗搜索 ====================

_H3_PATTERN = re.compile(
    r"<h3[^>]*>\s*<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>\s*</h3>",
    re.DOTALL,
)


def _extract_snippet(block: str) -> str:
    """从搜狗结果块 HTML 中提取摘要。"""
    # 收集所有有效中文文本片段并拼接
    fragments: list[str] = []

    # 从 >文本< 模式提取
    for chunk in re.findall(r">([^<]+)<", block):
        text = unescape(chunk.strip())
        if (
            len(text) >= 6
            and re.search(r"[\u4e00-\u9fff]", text)
            and not text.startswith(("var ", "function", "//", "?@", "window", "{", "https://"))
            and "搜狗" not in text
            and "相关结果" not in text
        ):
            fragments.append(text)

    if fragments:
        return "".join(fragments)[:300]
    return ""


async def _search_sogou(query: str, max_results: int = 5) -> list[SearchResult]:
    """通过搜狗网页搜索获取结果。"""
    url = f"https://www.sogou.com/web?query={quote(query)}"

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=_HEADERS)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[web_search] 搜狗请求失败: {e}")
        return []

    matches = list(_H3_PATTERN.finditer(html))
    if not matches:
        return []

    results: list[SearchResult] = []
    for i, m in enumerate(matches[:max_results]):
        raw_title = m.group(2)
        title = unescape(re.sub(r"<[^>]+>", "", raw_title).strip())
        if len(title) < 3:
            continue

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else start + 2000
        block = html[start:end]
        snippet = _extract_snippet(block)

        results.append(SearchResult(title=title, url=m.group(1), snippet=snippet))

    return results


# ==================== 统一入口 ====================

async def search(query: str, *, max_results: int = 5) -> list[SearchResult]:
    """统一搜索入口：百度百科优先，搜狗 fallback。

    Args:
        query: 搜索关键词
        max_results: 搜狗最多返回结果数

    Returns:
        搜索结果列表
    """
    # 1. 先试百度百科
    results = await _search_baike(query)
    if results:
        logger.info(f"[web_search] 百度百科命中: {query}")
        return results

    # 2. Fallback 搜狗
    results = await _search_sogou(query, max_results)
    if results:
        logger.info(f"[web_search] 搜狗返回 {len(results)} 条结果: {query}")
    else:
        logger.warning(f"[web_search] 所有搜索源均无结果: {query}")

    return results


def format_results_for_llm(results: list[SearchResult]) -> str:
    """将搜索结果格式化为 LLM 可消化的文本。"""
    if not results:
        return "（无搜索结果）"

    parts: list[str] = []
    for i, r in enumerate(results, 1):
        if r.snippet:
            parts.append(f"[{i}] {r.title}\n内容：{r.snippet}")
        else:
            parts.append(f"[{i}] {r.title}")

    return "\n\n".join(parts)


def format_sources_for_user(results: list[SearchResult], *, max_show: int = 3) -> list[str]:
    """格式化来源列表供用户查看。"""
    lines: list[str] = []
    for i, r in enumerate(results[:max_show], 1):
        title = r.title[:30] + "…" if len(r.title) > 30 else r.title
        lines.append(f"{i}. {title}")
    return lines
