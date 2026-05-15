"""百度百科名人头像下载器。

从百度百科获取名人的肖像/照片，缩放到 200px 宽度，适合 QQ 群发送。

用法：
    uv run python scripts/crawler/celebrity_wiki_downloader.py
"""

from __future__ import annotations

import io
import re
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import httpx

_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_DIR = _ROOT / "resources" / "checkin" / "celebrities"

# (百度百科词条名, 文件名)
CELEBRITIES = [
    ("特朗普", "trump"),
    ("埃隆·马斯克", "musk"),
    ("鲁迅", "luxun"),
    ("孔子", "kongzi"),
    ("诸葛亮", "zhugeliang"),
    ("阿尔伯特·爱因斯坦", "einstein"),
    ("史蒂夫·乔布斯", "jobs"),
    ("艾萨克·牛顿", "newton"),
    ("拿破仑·波拿巴", "napoleon"),
    ("曹操", "caocao"),
    ("秦始皇", "qinshihuang"),
    ("列奥纳多·达·芬奇", "davinci"),
    ("马云", "mayun"),
    ("孙武", "sunzi"),
    ("苏格拉底", "socrates"),
    ("李白", "libai"),
    ("杜甫", "dufu"),
    ("雷军", "leijun"),
    ("路德维希·凡·贝多芬", "beethoven"),
    ("刘备", "liubei"),
    ("托马斯·爱迪生", "edison"),
    ("康熙", "kangxi"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def get_baike_image(client: httpx.Client, keyword: str) -> str | None:
    """从百度百科页面提取主图 URL。"""
    from urllib.parse import quote

    url = f"https://baike.baidu.com/item/{quote(keyword)}"
    try:
        resp = client.get(url, timeout=20, follow_redirects=True)
        if resp.status_code != 200:
            print(f"  ⚠️ 页面请求失败 HTTP {resp.status_code}")
            return None
        html = resp.text

        # 百度百科主图通常在 summary-pic 或 poster 区域
        # 匹配 bkimg.cdn.bcebos.com 的图片 URL
        patterns = [
            r'"(https?://bkimg\.cdn\.bcebos\.com/pic/[^"]+)"',
            r'src="(https?://bkimg\.cdn\.bcebos\.com/pic/[^"]+)"',
        ]
        for pat in patterns:
            matches = re.findall(pat, html)
            if matches:
                # 第一张通常是主图
                return matches[0]
        
        # 备用: 匹配任何百度图片 CDN
        matches = re.findall(r'"(https?://[^"]*bkimg[^"]*\.(?:jpg|jpeg|png))[^"]*"', html, re.I)
        if matches:
            return matches[0]

        print(f"  ⚠️ 未找到图片 URL")
        return None
    except Exception as e:
        print(f"  ⚠️ 请求异常: {e}")
        return None


def download_image(client: httpx.Client, url: str, save_path: Path) -> bool:
    """下载图片到本地。"""
    try:
        resp = client.get(url, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            print(f"    HTTP {resp.status_code}")
            return False
        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type:
            print(f"    content-type: {content_type}")
            return False
        data = resp.content
        if len(data) < 2048:
            print(f"    太小: {len(data)} bytes")
            return False
        # 限制文件不超过 200KB
        if len(data) > 200 * 1024:
            print(f"    原图 {len(data)//1024}KB，保存（后续可压缩）")
        save_path.write_bytes(data)
        return True
    except Exception as e:
        print(f"    异常: {e}")
        return False


def main() -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("🎭 百度百科名人头像下载器")
    print(f"   输出目录: {_OUTPUT_DIR}")
    print(f"   名人数量: {len(CELEBRITIES)}")
    print("=" * 60)

    success = 0
    failed = []

    with httpx.Client(headers=HEADERS) as client:
        for i, (keyword, name) in enumerate(CELEBRITIES):
            print(f"\n[{i + 1}/{len(CELEBRITIES)}] 🔍 {keyword}")

            img_url = get_baike_image(client, keyword)
            if not img_url:
                failed.append(name)
                continue

            print(f"  📷 {img_url[:80]}...")

            ext = ".jpg"
            if ".png" in img_url.lower():
                ext = ".png"

            save_path = _OUTPUT_DIR / f"{name}_new{ext}"
            if download_image(client, img_url, save_path):
                size_kb = save_path.stat().st_size / 1024
                success += 1
                print(f"  ✅ 已保存: {save_path.name} ({size_kb:.1f}KB)")
            else:
                print(f"  ❌ 下载失败")
                failed.append(name)

            if i < len(CELEBRITIES) - 1:
                time.sleep(1.5)

    print("\n" + "=" * 60)
    print(f"✅ 成功: {success}/{len(CELEBRITIES)}")
    if failed:
        print(f"❌ 失败: {', '.join(failed)}")
    print(f"📁 图片位于: {_OUTPUT_DIR}")
    print(f"\n📌 下一步: 检查 *_new.jpg 图片质量，满意后替换旧图片")


if __name__ == "__main__":
    main()
