"""趣味问答答案宽松匹配。

判定不走 LLM，完全在代码层做归一化 + 子串匹配。
"""

from __future__ import annotations

import re
import unicodedata


# 常见的 "废话词"：出现在作答里会被剔除，便于子串匹配
_FILLER_WORDS = (
    "是不是", "吗", "啊", "吧", "哦", "呢", "呀", "嘛",
    "是", "应该", "可能", "肯定", "大概", "好像",
    "我猜", "猜", "答", "答案",
    "那个", "这个", "那是", "这是",
)

# 繁→简最小映射（覆盖本游戏最常见的字即可；复杂场景用 opencc，
# 但加依赖得不偿失 —— LLM 输出本就偏简体，玩家误打繁体概率极低）
_TRAD_SIMP: dict[str, str] = {
    "國": "国", "語": "语", "麵": "面", "貓": "猫",
    "魚": "鱼", "馬": "马", "龍": "龙", "雞": "鸡",
    "鳥": "鸟", "車": "车", "風": "风", "氣": "气",
    "時": "时", "東": "东", "區": "区", "書": "书",
    "樂": "乐", "當": "当", "會": "会", "愛": "爱",
    "號": "号", "專": "专", "體": "体", "學": "学",
    "幾": "几", "熱": "热", "發": "发", "對": "对",
    "實": "实", "頭": "头", "聲": "声", "種": "种",
    "樣": "样", "兒": "儿", "處": "处", "場": "场",
    "團": "团", "門": "门", "問": "问", "間": "间",
    "內": "内", "個": "个", "們": "们", "臉": "脸",
    "麽": "么", "麼": "么", "變": "变", "來": "来",
    "點": "点", "員": "员", "應": "应", "國": "国",
}

# 归一化后会被剥离的标点
_PUNCT_RE = re.compile(
    r"[\s\.,!?;:'\"()\[\]{}\-_/\\"
    r"。，、！？；：「」『』（）【】《》·~—…·"
    r"]+"
)


def _trad_to_simp(text: str) -> str:
    return "".join(_TRAD_SIMP.get(ch, ch) for ch in text)


def normalize(text: str) -> str:
    """统一归一化规则：

    1. NFKC（全角→半角、兼容字符统一）
    2. 转小写
    3. 繁→简（最小映射）
    4. 剔除所有空白和标点
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = s.lower()
    s = _trad_to_simp(s)
    s = _PUNCT_RE.sub("", s)
    return s


def strip_filler(text: str) -> str:
    """从已归一化的文本里剔除常见废话词，便于更宽松的匹配。

    只在"子串匹配未命中"的兜底阶段使用，避免一上来就剥掉有意义的字。
    """
    out = text
    for w in _FILLER_WORDS:
        out = out.replace(normalize(w), "")
    return out


def match(user_text: str, answer: str, aliases: list[str] | None = None) -> bool:
    """宽松判定：归一化后，answer 或任一 alias 是 user_text 的子串即为命中。

    示例（answer="加拿大", aliases=["Canada","枫叶国"]）：
        "加拿大"        → ✅
        "加拿大！"      → ✅
        "那是加拿大吧"  → ✅
        "canada"        → ✅
        "USA"           → ❌
        "我猜 加拿大"   → ✅
    """
    if not user_text or not answer:
        return False

    user_norm = normalize(user_text)
    if not user_norm:
        return False

    candidates = [answer]
    if aliases:
        candidates.extend(a for a in aliases if a)

    # 第一轮：直接子串
    for c in candidates:
        c_norm = normalize(c)
        if c_norm and c_norm in user_norm:
            return True

    # 第二轮：剥掉废话词后再试
    stripped = strip_filler(user_norm)
    if stripped and stripped != user_norm:
        for c in candidates:
            c_norm = normalize(c)
            if c_norm and c_norm in stripped:
                return True

    return False


def looks_like_answer(text: str, max_len: int = 40) -> bool:
    """粗略判断这条消息是不是"在作答"，用于过滤闲聊。

    规则：去空白后非空 且 原文长度 <= max_len。
    """
    if not text:
        return False
    s = text.strip()
    if not s:
        return False
    return len(s) <= max_len
