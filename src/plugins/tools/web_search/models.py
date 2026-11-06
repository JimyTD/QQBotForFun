"""AI 助手搜索层的稳定数据契约。"""

from __future__ import annotations

from dataclasses import dataclass, field


class SearchError(RuntimeError):
    """搜索服务不可用。消息可直接展示给用户。"""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    body: str = ""
    source: str = "web"


@dataclass
class ImageResult:
    title: str
    content_url: str
    page_url: str = ""
    width: int = 0
    height: int = 0
    source: str = "image"

    @property
    def aspect_ratio(self) -> float:
        if not self.width or not self.height:
            return 0.0
        return self.width / self.height


@dataclass
class SearchBundle:
    query: str
    web_results: list[SearchResult] = field(default_factory=list)
    images: list[ImageResult] = field(default_factory=list)


def format_results_for_llm(results: list[SearchResult]) -> str:
    if not results:
        return "（无搜索结果）"
    parts: list[str] = []
    for i, r in enumerate(results, 1):
        content = (r.body or r.snippet).strip()
        head = f"[{i}] {r.title}"
        host = source_host(r.url)
        if host:
            head += f"（{host}）"
        parts.append(f"{head}\n内容：{content}" if content else head)
    return "\n\n".join(parts)


def format_sources_for_user(
    results: list[SearchResult], *, max_show: int = 3
) -> list[str]:
    lines: list[str] = []
    for i, r in enumerate(results[:max_show], 1):
        title = r.title[:30] + "…" if len(r.title) > 30 else r.title
        host = source_host(r.url)
        lines.append(f"{i}. {title}  ({host})" if host else f"{i}. {title}")
    return lines


def source_host(url: str) -> str:
    from urllib.parse import urlparse

    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""
