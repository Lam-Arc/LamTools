"""文本规范化：搜索摘要与正文都从这里过一道，保证进入模型上下文的是干净的一段字。

user:“保留标题原文和关键摘要，不通过模型生成内容来替代原始摘要”+
(这里只做确定性清理：合并空白、去不可见字符、裁装饰性分隔符、按上限截断；
不改写日期、数字、单位，也不做任何“补全/润色”)。
"""

from __future__ import annotations

import re
import unicodedata

# 不可见字符：零宽空格、零宽连接符、BOM、软连字符。
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)
# 各种不间断空白统一成普通空格。
_SPACES = dict.fromkeys(map(ord, "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000"), " ")

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_SPACE_RE = re.compile(r"[ \t\f\v]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

# 摘要两端常见的装饰符号（列表项目符号、面包屑分隔符、引号），只在两端出现时去掉。
_LEADING_DECORATION = "·•►▶‣▪●○◆◇›»|｜/-—–~ "
_TRAILING_DECORATION = "·•►▶‣▪●○◆◇‹«|｜/-—–~ "

_DATE_PATTERNS = (
    re.compile(r"\b(19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b"),
    re.compile(r"\b(19|20)\d{2}年\d{1,2}月(\d{1,2}日)?\b"),
    re.compile(r"\b\d{1,2}月\d{1,2}日\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/(19|20)\d{2}\b"),
    re.compile(r"\b\d+\s*(秒|分钟|分钟前|小时|天|周|个月|年|min|mins|minute|minutes|hour|hours|day|days|week|weeks|month|months|year|years)\s*(前|ago)\b", re.I),
    re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+(19|20)\d{2}\b", re.I),
)

# 纯装饰性的「更多 / 展开 / 反馈」类标签，不构成摘要。
_DECORATIVE_LABELS = {
    "更多", "展开", "收起", "查看全部", "查看详情", "详情", "反馈", "举报", "分享", "翻译此页",
    "网页快照", "快照", "缓存", "转存", "复制链接", "站内搜索", "more", "view more", "show more",
    "feedback", "share", "translate this page", "cached", "similar",
}


def normalize(text: str | None) -> str:
    """合并空白、去掉不可见字符；保留原文的用词与标点。"""
    if not text:
        return ""
    raw = str(text).translate(_INVISIBLE).translate(_SPACES)
    raw = _CONTROL_RE.sub(" ", raw)
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_MULTI_SPACE_RE.sub(" ", line).strip() for line in raw.split("\n")]
    joined = "\n".join(lines)
    joined = _MULTI_NEWLINE_RE.sub("\n\n", joined)
    return joined.strip()


def one_line(text: str | None) -> str:
    """把多行压成一行（标题、摘要、来源名用）。"""
    return _MULTI_SPACE_RE.sub(" ", normalize(text).replace("\n", " ")).strip()


def clip(text: str | None, limit: int, *, ellipsis: str = "…") -> str:
    """按字符数截断，不切断词就不加省略号。"""
    value = text or ""
    if limit <= 0 or len(value) <= limit:
        return value
    return value[: max(0, limit - len(ellipsis))].rstrip() + ellipsis


def strip_decoration(text: str | None) -> str:
    """去掉摘要两端的项目符号 / 面包屑分隔符，不改中间内容。"""
    value = one_line(text)
    index = 0
    while index < len(value) and value[index] in _LEADING_DECORATION:
        index += 1
    value = value[index:]
    end = len(value)
    while end > 0 and value[end - 1] in _TRAILING_DECORATION:
        end -= 1
    return value[:end].strip()


def is_decorative(text: str) -> bool:
    value = strip_decoration(text).lower()
    return value in _DECORATIVE_LABELS


def looks_like_date(text: str | None) -> bool:
    """只判断「像日期」，不改写原值（原值原样保留给 publishedAt）。"""
    value = one_line(text)
    if not value or len(value) > 40:
        return False
    return any(pattern.search(value) for pattern in _DATE_PATTERNS)


def extract_date(text: str | None) -> str:
    """从一段文本里取出日期片段原文；取不到就给空字符串（不猜）。

    只截出日期那一小段（例如「发布于 2024年5月1日」→「2024年5月1日」），
    不改写格式、不补时区、不把相对时间换算成绝对时间。
    """
    value = one_line(text)
    if not value:
        return ""
    for pattern in _DATE_PATTERNS:
        found = pattern.search(value)
        if found:
            return found.group(0)
    return ""


def visible_chars(text: str | None) -> int:
    """统计可见字符数（用于噪声压缩率这类指标）。"""
    return len(normalize(text))


def width(text: str | None) -> int:
    """东亚字符按 2 计宽，用于判断「短标签」与「长摘要」。"""
    total = 0
    for char in text or "":
        total += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return total
