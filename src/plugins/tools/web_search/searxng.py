"""搜索客户端：百科 + 网页并行，必要时抓正文。

策略：
1. 时效 / 教程 / 对比类问题跳过百科，避免错词条锁死答案
2. 其余问题百科与搜狗并行，百科只是材料之一，不再一票否决
3. 搜狗拿标题+摘要后，抓前 2 条结果页正文（豆包式回答需要原文，不是残句）
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import quote, urljoin, urlparse

import httpx
from nonebot import logger


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

_SOGOU_ORIGIN = "https://www.sogou.com"


@dataclass
class SearchResult:
    """单条搜索结果。"""

    title: str
    url: str
    snippet: str
    body: str = ""
    source: str = ""  # baike / sogou / page


# 常见疑问词，仅用于百科词条名猜测，搜狗始终用原句
_STOP_WORDS = re.compile(
    r"(是什么|有什么|怎么样|怎么|如何|什么是|什么|为什么|哪些|哪个|多少|"
    r"几个|吗|呢|吧|啊|"
    r"效果|作用|特点|优势|用途|含义|意思|介绍|简介|"
    r"请问|请|告诉我|帮我|查一下|搜一下)",
    re.IGNORECASE,
)

_SKIP_BAIKE = re.compile(
    r"(今天|今日|最新|新闻|头条|比分|股价|行情|天气|赛况|实时|"
    r"最近|近日|近期|正在|"
    r"怎么|如何|怎样|教程|步骤|方法|配置|安装|"
    r"区别|对比|还是|哪个好|\bvs\b|\bVS\b|"
    r"20[12]\d年)"
)

_META_DESC_A = re.compile(
    r'<meta\b[^>]*\bname=["\']description["\'][^>]*\bcontent=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_META_DESC_B = re.compile(
    r'<meta\b[^>]*\bcontent=["\']([^"\']+)["\'][^>]*\bname=["\']description["\']',
    re.IGNORECASE,
)
_LEMMA_SUMMARY = re.compile(
    r'<div[^>]*class="[^"]*lemma-summary[^"]*"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_H3_PATTERN = re.compile(
    r"<h3[^>]*>\s*<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>\s*</h3>",
    re.DOTALL,
)
_DATA_URL = re.compile(r'data-url="(https?://[^"]+)"', re.IGNORECASE)
_SKIP_FETCH_HOSTS = (
    "sogou.com",
    "baike.baidu.com",  # 已单独走百科；直抓 403
)


def should_try_baike(query: str) -> bool:
    """时效/教程/对比用网页搜，百科帮不上忙还容易锁错词条。"""
    return not bool(_SKIP_BAIKE.search(query.strip()))


def _extract_baike_keywords(query: str) -> list[str]:
    """从用户查询中提取可能的百科词条名。"""
    candidates: list[str] = []
    q = query.strip()
    core = _STOP_WORDS.sub("", q).strip()
    if core and core != q:
        candidates.append(core)
    candidates.append(q)
    parts = [p.strip() for p in q.split() if len(p.strip()) >= 2]
    for p in parts:
        cleaned = _STOP_WORDS.sub("", p).strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        if c not in seen and len(c) >= 2:
            seen.add(c)
            result.append(c)
    return result[:4]


def _clean_html(html: str) -> str:
    """移除 HTML 标签、script、style，返回纯文本。"""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<noscript[^>]*>.*?</noscript>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\n\s*\n", "\n", text)
    return text.strip()


def _meta_description(html: str) -> str:
    m = _META_DESC_A.search(html) or _META_DESC_B.search(html)
    return unescape(m.group(1)).strip() if m else ""


def _compact_lines(text: str, *, min_len: int = 8, max_lines: int = 40) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and len(ln.strip()) >= min_len]
    return "\n".join(lines[:max_lines])


async def _search_baike(query: str) -> list[SearchResult]:
    """尝试从百度百科获取词条摘要 + 正文片段。"""
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

            if (
                len(html) < 5000
                or "百度百科错误页" in html
                or "error.html" in str(resp.url)
                or "您所访问的页面不存在" in html
            ):
                continue

            meta = _meta_description(html)
            lemma = ""
            m = _LEMMA_SUMMARY.search(html)
            if m:
                lemma = _clean_html(m.group(1))

            text = _clean_html(html)
            nearby = ""
            for kw in [keyword, query]:
                idx = text.find(kw)
                if idx >= 0:
                    nearby = text[idx : idx + 1600]
                    break
            if not nearby:
                nearby = text[400:2000] if len(text) > 2000 else text[:1600]

            parts = [p for p in (meta, lemma, _compact_lines(nearby)) if p]
            content = "\n".join(parts)
            # 去简单重复
            if meta and lemma and meta in lemma:
                content = "\n".join(p for p in (lemma, _compact_lines(nearby)) if p)
            if len(content) < 40:
                continue

            logger.info(f"[web_search] 百度百科命中词条: {keyword}")
            return [
                SearchResult(
                    title=f"{keyword} - 百度百科",
                    url=str(resp.url),
                    snippet=meta or content[:200],
                    body=content[:2400],
                    source="baike",
                )
            ]

    return []


def _extract_real_url(href: str, block: str) -> str:
    """搜狗 h3 的 href 多半是 /link?url= 跳转壳，结果块里的 data-url 才是真地址。"""
    href = unescape(href.strip())
    m = _DATA_URL.search(block)
    if m:
        return unescape(m.group(1)).strip()
    return urljoin(_SOGOU_ORIGIN, href)


def _host_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _is_fetchable(url: str) -> bool:
    if not url.startswith("http"):
        return False
    host = _host_of(url)
    if not host:
        return False
    return not any(host == s or host.endswith("." + s) for s in _SKIP_FETCH_HOSTS)


def _extract_snippet(block: str) -> str:
    """从搜狗结果块 HTML 中提取摘要。"""
    fragments: list[str] = []
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
        return "".join(fragments)[:400]
    return ""


async def _search_sogou(query: str, max_results: int = 5) -> list[SearchResult]:
    """通过搜狗网页搜索获取结果。"""
    url = f"{_SOGOU_ORIGIN}/web?query={quote(query)}"

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
        href = m.group(1).strip()
        if not href or href.startswith("javascript"):
            continue
        raw_title = m.group(2)
        title = unescape(re.sub(r"<[^>]+>", "", raw_title).strip())
        if len(title) < 3:
            continue
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(html), start + 4500)
        block = html[start:end]
        snippet = _extract_snippet(block)
        results.append(
            SearchResult(
                title=title,
                url=_extract_real_url(href, block),
                snippet=snippet,
                source="sogou",
            )
        )
    return results


async def _fetch_page_text(url: str) -> str:
    """抓结果页正文，失败返回空串。"""
    if not _is_fetchable(url):
        return ""
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=_HEADERS)
            if resp.status_code != 200:
                return ""
            final = str(resp.url)
            if not _is_fetchable(final):
                return ""
            ctype = (resp.headers.get("content-type") or "").lower()
            if ctype and "html" not in ctype and "text" not in ctype:
                return ""
            html = resp.text[:180_000]
    except Exception as e:  # noqa: BLE001
        logger.info(f"[web_search] 抓正文失败: {url[:80]} {e}")
        return ""

    text = _compact_lines(_clean_html(html), min_len=10, max_lines=50)
    if len(text) < 80:
        return ""
    return text[:2200]


async def _enrich_pages(results: list[SearchResult], *, limit: int = 2) -> None:
    """并行抓可打开的结果页；多试几条，凑满 limit 篇正文。"""
    candidates = [r for r in results if r.source != "baike" and _is_fetchable(r.url)][:4]
    if not candidates:
        return
    texts = await asyncio.gather(*(_fetch_page_text(r.url) for r in candidates))
    filled = 0
    for r, text in zip(candidates, texts, strict=True):
        if not text:
            continue
        r.body = text
        r.source = "page"
        filled += 1
        if filled >= limit:
            break


def _dedupe(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    out: list[SearchResult] = []
    for r in results:
        key = re.sub(r"\s+", "", r.title)[:24]
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


async def search(query: str, *, max_results: int = 5) -> list[SearchResult]:
    """统一搜索入口：百科与网页可并存，再抓正文。"""
    if should_try_baike(query):
        baike, sogou = await asyncio.gather(
            _search_baike(query),
            _search_sogou(query, max_results),
        )
    else:
        baike = []
        sogou = await _search_sogou(query, max_results)

    await _enrich_pages(sogou, limit=2)

    merged = _dedupe([*baike, *sogou])
    if baike:
        logger.info(f"[web_search] 百科+网页 共 {len(merged)} 条: {query}")
    elif sogou:
        logger.info(f"[web_search] 搜狗返回 {len(sogou)} 条: {query}")
    else:
        logger.warning(f"[web_search] 所有搜索源均无结果: {query}")
    return merged[:max_results]


def format_results_for_llm(results: list[SearchResult]) -> str:
    """将搜索结果格式化为 LLM 可消化的文本。优先给正文。"""
    if not results:
        return "（无搜索结果）"

    parts: list[str] = []
    for i, r in enumerate(results, 1):
        content = r.body or r.snippet
        host = _source_host(r.url)
        head = f"[{i}] {r.title}"
        if host:
            head += f"（{host}）"
        if content:
            parts.append(f"{head}\n内容：{content}")
        else:
            parts.append(head)
    return "\n\n".join(parts)


def format_sources_for_user(results: list[SearchResult], *, max_show: int = 3) -> list[str]:
    """格式化来源列表供用户查看。"""
    lines: list[str] = []
    for i, r in enumerate(results[:max_show], 1):
        title = r.title[:30] + "…" if len(r.title) > 30 else r.title
        host = _source_host(r.url)
        if host and host not in title:
            lines.append(f"{i}. {title}  ({host})")
        else:
            lines.append(f"{i}. {title}")
    return lines


def _source_host(url: str) -> str:
    host = _host_of(url)
    if not host or "sogou.com" in host:
        return ""
    return host
