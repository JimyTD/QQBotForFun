"""今日运势 · 名人寄语 + 黄历宜忌。

签到成功后额外发送的趣味消息，非持久化，不影响经济系统。
两种风格各 50% 概率随机命中：
- 名人寄语：名人说沙雕话 + 配梗图
- 黄历宜忌：搞笑宜忌条目，纯文字
"""

from __future__ import annotations

import base64
import random
from dataclasses import dataclass, field
from pathlib import Path

from nonebot import logger

# ---------- 路径 ----------
_ROOT = Path(__file__).resolve().parents[4]  # src/plugins/tools/checkin/ -> 项目根
_CELEB_DIR = _ROOT / "resources" / "checkin" / "celebrities"

# ---------- 名人寄语数据 ----------
# 每条: (名人名, 语录, 图片文件名)
_CELEBRITY_QUOTES: list[tuple[str, str, str]] = [
    ("特朗普", "Make your 签到 great again!", "trump.jpg"),
    ("马斯克", "我很欣赏你这种每天准时打卡的人，考虑来 SpaceX 当倒计时员吗？", "musk.jpg"),
    ("鲁迅", "我没说过这句话，但签到确实能变强。", "luxun.jpg"),
    ("孔子", "学而时习之，不如日日签到之。", "kongzi.jpg"),
    ("诸葛亮", "我观你今日面相，宜苟，忌浪。", "zhugeliang.jpg"),
    ("爱因斯坦", "E=mc²，其中 m 是你的摸鱼质量，c 是签到速度。", "einstein.jpg"),
    ("乔布斯", "Stay hungry, stay 签到。", "jobs.jpg"),
    ("牛顿", "如果我比别人签到得更早，那是因为我站在闹钟的肩膀上。", "newton.jpg"),
    ("拿破仑", "不想签到的群友不是好群友。", "napoleon.jpg"),
    ("曹操", "宁教我负天下人，不教天下人负我的签到。", "caocao.jpg"),
    ("秦始皇", "朕统一六国就是为了让你们都来签到的。", "qinshihuang.jpg"),
    ("达芬奇", "签到是一门艺术，而你是今天的艺术家。", "davinci.jpg"),
    ("马云", "我对钱没有兴趣，但我对你的签到很有兴趣。", "mayun.jpg"),
    ("特朗普", "你的签到是我见过最棒的签到，没有之一，believe me。", "trump.jpg"),
    ("马斯克", "你今天的签到速度比猎鹰9号回收还精准。", "musk.jpg"),
    ("鲁迅", "世上本没有签到，签的人多了，也便成了传统。", "luxun.jpg"),
    ("孙子", "知己知彼，百签不殆。", "sunzi.jpg"),
    ("苏格拉底", "我唯一知道的，就是你今天签到了。", "socrates.jpg"),
    ("李白", "天生我材必有用，千金散尽还能签。", "libai.jpg"),
    ("杜甫", "安得广厦千万间，不如每日签到一次闲。", "dufu.jpg"),
    ("雷军", "你今天的签到，超过了99%的用户，Are you OK？", "leijun.jpg"),
    ("贝多芬", "我要扼住命运的咽喉，然后提醒它去签到。", "beethoven.jpg"),
    ("刘备", "勿以签小而不为，勿以摸鱼大而为之。", "liubei.jpg"),
    ("马斯克", "火星上也会有签到系统的，你先在地球练练手。", "musk.jpg"),
    ("特朗普", "这是有史以来最伟大的一次签到，fake news说不是。", "trump.jpg"),
    ("鲁迅", "时间就像海绵里的水，挤一挤总能签个到。", "luxun.jpg"),
    ("爱迪生", "签到是1%的灵感加99%的准时起床。", "edison.jpg"),
    ("诸葛亮", "臣本布衣，躬耕于南阳，每日签到从未间断。", "zhugeliang.jpg"),
    ("康熙", "朕批了一辈子奏折，不如你签到来得痛快。", "kangxi.jpg"),
    ("马云", "996是福报，但每天签到才是真正的福报。", "mayun.jpg"),
]

# ---------- 黄历宜忌数据 ----------
_FORTUNE_LEVELS = ["大吉", "中吉", "小吉", "吉", "末吉", "凶", "大凶"]

_LUCKY_POOL = [
    "摸鱼", "带薪拉屎", "发呆", "躺平", "早退",
    "划水", "午睡", "点外卖", "刷短视频", "逛淘宝",
    "喝奶茶", "说骚话", "装死", "已读不回", "阴阳怪气",
    "假装很忙", "提前下班", "吃零食", "发表情包", "水群",
    "做白日梦", "偷偷摸鱼", "假装加班", "拒绝社交", "原地躺平",
    "看番", "打游戏", "吃火锅", "网购", "睡懒觉",
]

_UNLUCKY_POOL = [
    "主动加班", "碰 CSS", "说\"这个需求很简单\"", "重构代码", "跟产品经理讲道理",
    "说\"这把稳了\"", "立 flag", "回复\"收到\"", "看体重秤", "打开花呗账单",
    "查银行余额", "答应别人的请求", "相亲", "剪头发", "发朋友圈",
    "跟老板对视", "说真话", "认真工作", "早起", "运动",
    "学习", "思考人生", "打开工作群", "接电话", "看未读消息",
    "说\"我来吧\"", "承诺 deadline", "改 bug", "碰生产环境", "说\"马上就好\"",
]

# ---------- 图片缓存 ----------
# 启动时预加载，key=文件名, value=base64 字符串
_image_cache: dict[str, str] = {}


def load_image_cache() -> None:
    """启动时扫描名人梗图目录，预缓存到内存。

    应在插件加载时调用一次。图片缺失不报错，只记 debug 日志。
    """
    _image_cache.clear()
    if not _CELEB_DIR.exists():
        logger.debug(f"[fortune] 名人梗图目录不存在: {_CELEB_DIR}")
        return

    for img_path in _CELEB_DIR.iterdir():
        if img_path.is_file() and img_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif"):
            try:
                b64 = base64.b64encode(img_path.read_bytes()).decode()
                _image_cache[img_path.name] = b64
                logger.debug(f"[fortune] 缓存梗图: {img_path.name}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[fortune] 读取梗图失败: {img_path} err={e}")

    logger.info(f"[fortune] 已缓存 {len(_image_cache)} 张名人梗图")


# ---------- 数据结构 ----------
@dataclass(frozen=True)
class FortuneResult:
    """今日运势结果。"""

    style: str  # "celebrity" 或 "almanac"

    # 名人寄语字段
    celebrity_name: str = ""
    quote: str = ""
    image_b64: str = ""  # base64 编码的图片，空串表示无图

    # 黄历宜忌字段
    fortune_level: str = ""
    lucky_items: list[str] = field(default_factory=list)
    unlucky_items: list[str] = field(default_factory=list)


# ---------- 核心函数 ----------
def roll_fortune() -> FortuneResult:
    """随机生成今日运势。

    50% 概率名人寄语，50% 概率黄历宜忌。纯函数，不依赖 DB。
    """
    if random.random() < 0.5:
        return _roll_celebrity()
    return _roll_almanac()


def _roll_celebrity() -> FortuneResult:
    """随机抽一条名人寄语。"""
    name, quote, img_file = random.choice(_CELEBRITY_QUOTES)
    image_b64 = _image_cache.get(img_file, "")
    return FortuneResult(
        style="celebrity",
        celebrity_name=name,
        quote=quote,
        image_b64=image_b64,
    )


def _roll_almanac() -> FortuneResult:
    """随机生成黄历宜忌。"""
    level = random.choice(_FORTUNE_LEVELS)
    lucky = random.sample(_LUCKY_POOL, 3)
    unlucky = random.sample(_UNLUCKY_POOL, 3)
    return FortuneResult(
        style="almanac",
        fortune_level=level,
        lucky_items=lucky,
        unlucky_items=unlucky,
    )


def format_fortune_text(fortune: FortuneResult) -> str:
    """将运势结果格式化为纯文字消息。

    名人寄语风格：
        🗣️ <名人>寄语：
        "<语录>"

    黄历宜忌风格：
        📜 今日黄历 ─── <等级>
        宜：xxx、xxx、xxx
        忌：xxx、xxx、xxx
    """
    if fortune.style == "celebrity":
        return (
            f"🗣️ {fortune.celebrity_name}寄语：\n"
            f"\"{fortune.quote}\""
        )

    # almanac
    lucky_str = "、".join(fortune.lucky_items)
    unlucky_str = "、".join(fortune.unlucky_items)
    return (
        f"📜 今日黄历 ─── {fortune.fortune_level}\n"
        f"宜：{lucky_str}\n"
        f"忌：{unlucky_str}"
    )
