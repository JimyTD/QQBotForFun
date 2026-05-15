"""Bing 图片爬虫 · 下载名人梗图候选。

用法：
    uv run python scripts/crawler/celebrity_meme_downloader.py

功能：
    - 按名人名搜索 Bing 图片
    - 每个名人下载 3~5 张候选图到 resources/checkin/celebrities/<name>/
    - 人工挑选后，将最终图片重命名为 <name>.jpg 放到 resources/checkin/celebrities/ 根目录

注意：
    - 需要网络访问
    - Bing 图片搜索可能有反爬限制，失败时会自动重试
    - 下载的是候选图，需要人工挑选最终使用的图片
"""

from __future__ import annotations

import io
import re
import sys

# Windows UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import time
from pathlib import Path
from urllib.parse import quote_plus

import httpx

# 项目根目录
_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_DIR = _ROOT / "resources" / "checkin" / "celebrities"

# 名人列表：(搜索关键词, 文件名前缀)
CELEBRITIES = [
    ("特朗普 搞笑 梗图 meme", "trump"),
    ("马斯克 搞笑 梗图 meme", "musk"),
    ("鲁迅 搞笑 梗图 表情包", "luxun"),
    ("孔子 搞笑 梗图 表情包", "kongzi"),
    ("诸葛亮 搞笑 梗图 表情包", "zhugeliang"),
    ("爱因斯坦 搞笑 梗图 meme", "einstein"),
    ("乔布斯 搞笑 梗图 meme", "jobs"),
    ("牛顿 搞笑 梗图 meme", "newton"),
    ("拿破仑 搞笑 梗图 meme", "napoleon"),
    ("曹操 搞笑 梗图 表情包", "caocao"),
    ("秦始皇 搞笑 梗图 表情包", "qinshihuang"),
    ("达芬奇 搞笑 梗图 meme", "davinci"),
    ("马云 搞笑 梗图 表情包", "mayun"),
    ("孙子兵法 搞笑 梗图 表情包", "sunzi"),
    ("苏格拉底 搞笑 梗图 meme", "socrates"),
    ("李白 搞笑 梗图 表情包", "libai"),
    ("杜甫 搞笑 梗图 表情包", "dufu"),
    ("雷军 搞笑 梗图 表情包 are you ok", "leijun"),
    ("贝多芬 搞笑 梗图 meme", "beethoven"),
    ("刘备 搞笑 梗图 表情包", "liubei"),
    ("爱迪生 搞笑 梗图 meme", "edison"),
    ("康熙 搞笑 梗图 表情包", "kangxi"),
]

# 每个名人下载的候选图数量
MAX_CANDIDATES = 5

# HTTP 请求头
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _extract_image_urls(html: str) -> list[str]:
    """从 Bing 图片搜索结果页面提取图片 URL。"""
    # Bing 图片搜索结果中 murl 参数使用 HTML 转义引号 &quot;
    # 格式: &quot;murl&quot;:&quot;https://...&quot;
    pattern = r'&quot;murl&quot;:&quot;(https?://[^&]+)&quot;'
    urls = re.findall(pattern, html)
    # 去重并过滤
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        if url not in seen and not url.endswith(".svg"):
            seen.add(url)
            result.append(url)
    return result


def _download_image(client: httpx.Client, url: str, save_path: Path) -> bool:
    """下载单张图片，成功返回 True。"""
    try:
        resp = client.get(url, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return False
        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type:
            return False
        # 检查文件大小：跳过太小（< 5KB，可能是占位图）或太大（> 500KB）的
        data = resp.content
        if len(data) < 5 * 1024 or len(data) > 500 * 1024:
            return False
        save_path.write_bytes(data)
        return True
    except Exception:  # noqa: BLE001
        return False


def search_and_download(
    client: httpx.Client,
    query: str,
    name: str,
    max_count: int = MAX_CANDIDATES,
) -> int:
    """搜索并下载某个名人的梗图候选。返回成功下载的数量。"""
    # 创建候选目录
    candidate_dir = _OUTPUT_DIR / name
    candidate_dir.mkdir(parents=True, exist_ok=True)

    # Bing 图片搜索
    search_url = f"https://www.bing.com/images/search?q={quote_plus(query)}&form=HDRSC2&first=1"
    try:
        resp = client.get(search_url, timeout=20, follow_redirects=True)
        if resp.status_code != 200:
            print(f"  ⚠️ 搜索失败 (HTTP {resp.status_code})")
            return 0
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ 搜索请求异常: {e}")
        return 0

    image_urls = _extract_image_urls(resp.text)
    if not image_urls:
        print(f"  ⚠️ 未找到图片 URL")
        return 0

    print(f"  找到 {len(image_urls)} 个候选 URL，开始下载前 {max_count} 张...")

    downloaded = 0
    for i, url in enumerate(image_urls):
        if downloaded >= max_count:
            break
        # 根据 URL 猜测扩展名
        ext = ".jpg"
        if ".png" in url.lower():
            ext = ".png"
        elif ".gif" in url.lower():
            ext = ".gif"

        save_path = candidate_dir / f"{name}_{i + 1}{ext}"
        if _download_image(client, url, save_path):
            downloaded += 1
            size_kb = save_path.stat().st_size / 1024
            print(f"    ✅ [{downloaded}/{max_count}] {save_path.name} ({size_kb:.0f}KB)")
        else:
            print(f"    ❌ 跳过: {url[:80]}...")

    return downloaded


def main() -> None:
    """主入口：遍历所有名人，搜索并下载梗图候选。"""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("🎭 名人梗图下载器")
    print(f"   输出目录: {_OUTPUT_DIR}")
    print(f"   名人数量: {len(CELEBRITIES)}")
    print(f"   每人候选: {MAX_CANDIDATES} 张")
    print("=" * 60)

    total_downloaded = 0

    with httpx.Client(headers=HEADERS) as client:
        for i, (query, name) in enumerate(CELEBRITIES):
            print(f"\n[{i + 1}/{len(CELEBRITIES)}] 🔍 搜索: {query}")
            count = search_and_download(client, query, name)
            total_downloaded += count

            # 礼貌延迟，避免被 Bing 限流
            if i < len(CELEBRITIES) - 1:
                time.sleep(2)

    print("\n" + "=" * 60)
    print(f"✅ 完成！共下载 {total_downloaded} 张候选图")
    print(f"📁 候选图位于: {_OUTPUT_DIR}/<name>/")
    print()
    print("📌 下一步：")
    print("   1. 浏览每个名人的候选目录，挑选最合适的一张")
    print("   2. 将选中的图片复制到根目录并重命名：")
    print(f"      {_OUTPUT_DIR}/<name>.jpg")
    print("   3. 可以删除候选目录")


if __name__ == "__main__":
    main()
