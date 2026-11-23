"""URL 处理：中转链接解包、跟踪参数剔除、去重键。

user:“识别真实目标链接与搜索引擎中转链接；清除明确无意义的追踪参数；保留业务必需的查询参数、
签名与锚点；保留原始 URL 以便追溯；不对无法确认语义的参数进行破坏性清理”+
(所以清洗是**白名单式**的：只有列在 TRACKING_PARAMS 里的参数会被删，
其余参数一律原样保留；解包失败就保留原链接并标 pending，绝不猜目标地址)。
"""

from __future__ import annotations

import base64
import binascii
from urllib.parse import parse_qsl, quote, urljoin, urlsplit, urlunsplit

# 明确无意义、且删掉不影响取到内容的跟踪参数（宁可少删，不可错删）。
TRACKING_PARAMS = frozenset(
    {
        # 通用广告/投放归因
        "gclid", "gclsrc", "dclid", "msclkid", "fbclid", "twclid", "igshid", "ttclid",
        "yclid", "epik", "ad_id", "adset_id", "campaign_id", "cmpid", "ocid",
        # 通用分析
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
        "utm_campaignid", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
        "mc_cid", "mc_eid", "ref_src", "ref_url", "referrer",
        # 搜索引擎自己的点击统计（解包后才会出现，残留也一并清掉）
        "sa", "ved", "usg", "ei", "sxsrf", "uact", "opi", "vet", "gs_lcp", "gs_lcrp",
        "sugid", "spm", "spm_id_from", "vd_source", "from_spmid", "eqid", "rsv_spt", "rsv_iqid",
    }
)

# 这些站点是中转壳，解不出目标时保留原链接（PRD §5.4：不得猜真实 URL）。
_REDIRECT_HOSTS = {
    "www.google.com": "google",
    "google.com": "google",
    "www.google.com.hk": "google",
    "www.bing.com": "bing",
    "cn.bing.com": "bing",
    "www.baidu.com": "baidu",
    "baidu.com": "baidu",
    "duckduckgo.com": "duckduckgo",
}


def normalize_host(host: str | None) -> str:
    value = (host or "").strip().lower().rstrip(".")
    if value.startswith("www."):
        value = value[4:]
    return value


def host_of(url: str) -> str:
    try:
        return normalize_host(urlsplit(url).hostname or "")
    except ValueError:
        return ""


def absolutize(base: str, href: str) -> str:
    """把相对链接按页面地址补全；不支持 mailto/javascript 之类（原样返回，后面会被判无效）。"""
    target = (href or "").strip()
    if not target:
        return ""
    if target.startswith("//"):
        scheme = urlsplit(base).scheme or "https"
        return f"{scheme}:{target}"
    if target.startswith(("http://", "https://")):
        return target
    if target.startswith(("javascript:", "mailto:", "tel:", "data:", "about:")):
        return ""
    if "#" == target[0]:
        return ""
    try:
        return urljoin(base, target)
    except ValueError:
        return ""


def _bing_decode(value: str) -> str:
    """Bing 的 `/ck/a?...&u=a1<base64url>`：`a1` 前缀后是目标地址的 base64url。"""
    token = value[2:] if value.startswith("a1") else value
    padding = "=" * (-len(token) % 4)
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            decoded = decoder(token + padding).decode("utf-8", "strict")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            continue
        if decoded.startswith(("http://", "https://")):
            return decoded
    return ""


def unwrap(url: str) -> tuple[str, bool]:
    """把中转链接还原成目标链接。

    返回 ``(url, resolved)``：``resolved=False`` 表示「知道这是中转，但解不出目标」，
    调用方必须原样保留并标注待解析。
    """
    target = (url or "").strip()
    if not target:
        return "", False
    try:
        parts = urlsplit(target)
    except ValueError:
        return target, False
    kind = _REDIRECT_HOSTS.get(normalize_host(parts.hostname or ""))
    if kind is None:
        return target, True
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    path = parts.path or ""
    if kind == "google":
        if path in {"/url", "/imgres", "/interstitial"} or "url" in params or "q" in params:
            candidate = params.get("url") or params.get("q") or params.get("imgurl") or ""
            if candidate.startswith(("http://", "https://")):
                return candidate, True
        # 解不出目标就保留原链接（PRD：不得猜测真实 URL）。
        return target, True
    if kind == "bing":
        candidate = params.get("u") or params.get("url") or ""
        decoded = _bing_decode(candidate) if candidate else ""
        if decoded:
            return decoded, True
        if candidate.startswith(("http://", "https://")):
            return candidate, True
        # /ck/a 但没有可解的目标：这是中转，不是答案。
        return target, not path.startswith("/ck/")
    if kind == "baidu":
        # 百度 /link?url=… 是加密 token，解出来只能靠再发一次请求；不猜（PRD §5.4）。
        if path.startswith("/link"):
            return target, False
        return target, True
    if kind == "duckduckgo":
        candidate = params.get("uddg") or ""
        if candidate.startswith(("http://", "https://")):
            return candidate, True
    return target, True


def strip_tracking(url: str) -> str:
    """只删 TRACKING_PARAMS 里的参数；其它参数、路径、锚点原样保留。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(key, value) for key, value in pairs if key.lower() not in TRACKING_PARAMS]
    if len(kept) == len(pairs):
        return url
    query = "&".join(f"{quote(key, safe='')}={quote(value, safe='')}" for key, value in kept)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def is_web_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and bool(parts.hostname)


def clean(url: str) -> str:
    """对外入口：解包 + 去跟踪参数。解不出目标的中转链接原样返回。"""
    target, _resolved = unwrap(absolutize("", url))
    if not is_web_url(target):
        return ""
    return strip_tracking(target)


def query_text(url: str) -> str:
    """取地址里的查询参数原文（q / wd / word / query），用于判断页面是不是已经换成新查询。"""
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return ""
    fields = {key.lower(): value for key, value in pairs}
    for key in ("q", "wd", "word", "query"):
        if key in fields:
            return " ".join(fields[key].split())
    return ""


def same_query(a: str, b: str) -> bool:
    """两条地址是不是同一个查询（忽略 rdr/rdrig/count 之类旁路参数）。"""
    left, right = query_text(a), query_text(b)
    if left and right:
        return left == right
    return (a or "").split("#")[0] == (b or "").split("#")[0]


def dedupe_key(url: str) -> str:
    """去重键：主机（去 www、小写）+ 路径（去尾斜杠）+ 保留参数（去掉跟踪项后排序）。

    同一域名下的不同页面路径不同，不会互相合并（PRD S5）。
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    host = normalize_host(parts.hostname or "")
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    query_pairs = [
        (key.lower(), value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    query_pairs.sort()
    query = "&".join(f"{key}={value}" for key, value in query_pairs)
    return f"{host}{path}" + (f"?{query}" if query else "")
