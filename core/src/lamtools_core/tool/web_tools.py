from __future__ import annotations

import asyncio
import ipaddress
import re
from typing import Awaitable, Callable
from urllib.parse import urljoin, urlsplit

import httpx

from lamtools_core.tool import ToolArtifact, ToolCall, ToolResult, ToolResultStatus
from lamtools_core.tool.document_normalize import DocumentNormalizationError, normalize_pdf_bytes
from lamtools_core.tool.search.image_candidates import extract_image_candidates

_WEB_SEARCH_URL = "https://html.duckduckgo.com/html/"
_DEFAULT_FETCH_TIMEOUT = 30
_FETCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_HTTP_CLIENT: httpx.AsyncClient | None = None

#: Redirect hops followed while fetching one URL (matches httpx's default budget).
_MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class BlockedTargetError(Exception):
    """A fetch target (or one of its redirect hops) is not a public http(s) address."""


def _http_session() -> httpx.AsyncClient:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        _HTTP_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(_DEFAULT_FETCH_TIMEOUT),
            follow_redirects=False,
            headers={"User-Agent": _FETCH_USER_AGENT},
        )
    return _HTTP_CLIENT


def _is_loopback_url(url: str) -> bool:
    hostname = (urlsplit(url).hostname or "").strip().lower()
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _address_of(host: str) -> ipaddress._BaseAddress | None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped if mapped is not None else address


def _unsafe_redirect_reason(url: str) -> str:
    """Explain why a redirect hop must not be followed, or return '' when it is fine.

    ``web_fetch`` starts from a URL the model wrote, so following redirects blindly
    let any public page bounce the fetcher into the local machine — the Core server
    on 127.0.0.1, a LAN host, or a cloud metadata address (2026-09-25 audit P2).
    Hops are held to plain public http(s) targets; a deliberately local start
    (loopback or a private literal) keeps its own redirect chain, which is the
    documented "serve the file locally and fetch it" workflow.
    """
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        return f"scheme '{scheme or '?'}' is not fetchable"
    host = (parts.hostname or "").strip().lower()
    if not host:
        return "no host"
    if host == "localhost" or host.endswith(".localhost"):
        return "loopback host"
    address = _address_of(host)
    if address is None:
        return ""
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        return f"non-public address {address}"
    return ""


def _is_local_target(url: str) -> bool:
    """True when the caller pointed the fetch at a local address on purpose."""
    host = (urlsplit(url).hostname or "").strip().lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    address = _address_of(host)
    return bool(address) and bool(_unsafe_redirect_reason(url))


async def _get_following_safe_redirects(
    client: httpx.AsyncClient,
    url: str,
    *,
    allow_local_hops: bool,
    max_redirects: int = _MAX_REDIRECTS,
) -> httpx.Response:
    """GET ``url``, following only redirect hops that pass :func:`_unsafe_redirect_reason`."""
    current = url
    for hop in range(max_redirects + 1):
        if not allow_local_hops:
            reason = _unsafe_redirect_reason(current)
            if reason:
                raise BlockedTargetError(f"refusing {current}: {reason}")
        response = await client.get(current, follow_redirects=False)
        location = None
        if response.status_code in _REDIRECT_STATUSES:
            location = (response.headers.get("location") or "").strip()
        if not location:
            return response
        if hop == max_redirects:
            break
        current = urljoin(str(response.url), location)
    raise BlockedTargetError(f"too many redirects (>{max_redirects}) starting at {url}")


async def _fetch_with_loopback_bypass(url: str) -> httpx.Response:
    if not _is_loopback_url(url):
        return await _get_following_safe_redirects(
            _http_session(), url, allow_local_hops=_is_local_target(url)
        )
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(_DEFAULT_FETCH_TIMEOUT),
        follow_redirects=False,
        headers={"User-Agent": _FETCH_USER_AGENT},
        trust_env=False,
    ) as client:
        return await _get_following_safe_redirects(client, url, allow_local_hops=True)


def make_web_search_handler(work_root: str) -> Callable[[ToolCall], Awaitable[ToolResult]]:
    """兼容转发：web_search 已重构到 tool/search 包（可替换内核架构）。

    保留此函数以维持既有 import/API 兼容，实际逻辑走
    ``lamtools_core.tool.search.build_web_search_handler``。
    """
    from lamtools_core.tool.search import build_web_search_handler as _build

    return _build(work_root)


def make_web_fetch_handler(work_root: str) -> Callable[[ToolCall], Awaitable[ToolResult]]:
    _ = work_root

    async def web_fetch(call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        url = args.get("url", "")
        expect = args.get("expect")
        if not url or not isinstance(url, str):
            return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'url' argument")
        if url.startswith("file://"):
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error="Access to file:// protocol is blocked; serve the file over http://127.0.0.1:<port>/",
            )
        if expect is not None and not isinstance(expect, str):
            return ToolResult(call_id=call.id, name=call.name, status="failed", error="'expect' must be a string or null")

        try:
            resp = await _fetch_with_loopback_bypass(url)
        except BlockedTargetError as exc:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error=f"web_fetch refused target: {exc}",
            )
        except httpx.HTTPError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"web_fetch network error: {exc}")
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"web_fetch error: {exc}")

        content_type = resp.headers.get("content-type", "")
        normalized_type = content_type.split(";", 1)[0].strip().lower()

        if normalized_type.startswith("image/"):
            metadata = {
                "url": str(resp.url),
                "status_code": resp.status_code,
                "content_type": content_type,
                "content_length": len(resp.content),
                "verified_image": resp.status_code < 400,
                "image_candidates": [
                    {
                        "url": str(resp.url),
                        "alt": "",
                        "kind": "direct_image",
                        "source_url": url,
                    }
                ] if resp.status_code < 400 and str(resp.url).startswith("https://") else [],
            }
            status: ToolResultStatus = "ok" if resp.status_code < 400 else "failed"
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status=status,
                content=(
                    f"[web_fetch {url}] HTTP {resp.status_code}\n\n"
                    f"Verified image response: {content_type}; {len(resp.content)} bytes"
                ),
                error="" if status == "ok" else f"HTTP {resp.status_code}",
                metadata=metadata,
                artifacts=[ToolArtifact(kind="web_fetch_content", uri=url, content="", metadata=metadata)],
            )

        is_pdf = normalized_type == "application/pdf" or resp.content.startswith(b"%PDF-")
        if is_pdf:
            metadata = {
                "url": str(resp.url),
                "status_code": resp.status_code,
                "content_type": content_type,
                "content_length": len(resp.content),
                "document_format": "pdf",
                "content_trust": "untrusted",
                "expect": expect,
                "expect_found": None,
                "warnings": [],
                "image_candidates": [],
            }
            if resp.status_code >= 400:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="failed",
                    content=f"[web_fetch {url}] HTTP {resp.status_code}\n\nPDF response was not parsed.",
                    error=f"HTTP {resp.status_code}",
                    metadata=metadata,
                    artifacts=[ToolArtifact(kind="web_fetch_content", uri=url, content="", metadata=metadata)],
                )
            try:
                normalized = await asyncio.to_thread(
                    normalize_pdf_bytes,
                    resp.content,
                    max_text_length=30_000,
                )
            except DocumentNormalizationError as exc:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="failed",
                    content=f"[web_fetch {url}] HTTP {resp.status_code}\n\nPDF parsing failed: {exc}",
                    error=f"PDF parsing failed: {exc}",
                    metadata=metadata,
                    artifacts=[ToolArtifact(kind="web_fetch_content", uri=url, content="", metadata=metadata)],
                )

            clean = normalized.markdown
            expect_found = expect in clean if expect else None
            metadata.update(
                {
                    "text_length": len(clean),
                    "truncated": any("text limit" in warning for warning in normalized.warnings),
                    "expect_found": expect_found,
                    "warnings": list(normalized.warnings),
                }
            )
            info = f"[web_fetch {url}] HTTP {resp.status_code}\n\n{clean}"
            if expect:
                info += f"\n\nexpect: {expect}\nexpect_found: {str(expect_found).lower()}"
            status: ToolResultStatus = "ok" if not expect or expect_found else "failed"
            error = "" if status == "ok" else f"Expected text not found: {expect}"
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status=status,
                content=info,
                error=error,
                metadata=metadata,
                artifacts=[ToolArtifact(kind="web_fetch_content", uri=url, content=clean, metadata=metadata)],
            )

        text = resp.text
        image_candidates: list[dict[str, str]] = []

        if "text/html" in content_type or url.endswith((".html", ".htm")) or "<html" in text[:200].lower():
            image_candidates = extract_image_candidates(text, str(resp.url))
            clean = _extract_readable_text(text, url)
        else:
            clean = text

        if len(clean) > 30000:
            clean = clean[:30000] + f"\n\n[... truncated at 30000 / {len(clean)} chars]"

        expect_found = None
        if expect:
            expect_found = expect in text

        info = f"[web_fetch {url}] HTTP {resp.status_code}\n\n{clean}"
        if image_candidates:
            info += "\n\n[image candidates from this source page]\n" + "\n".join(
                f"- {item['url']}"
                + (f" — {item['alt']}" if item.get("alt") else "")
                for item in image_candidates
            )
        if expect:
            info += f"\n\nexpect: {expect}\nexpect_found: {str(expect_found).lower()}"
        metadata = {
            # The final URL, so a redirected fetch reports where the content
            # actually came from (the requested one is kept when they differ).
            "url": str(resp.url),
            "status_code": resp.status_code,
            "content_type": content_type,
            "text_length": len(clean),
            "truncated": "[... truncated" in clean,
            "expect": expect,
            "expect_found": expect_found,
            "image_candidates": image_candidates,
        }
        if str(resp.url) != url:
            metadata["requested_url"] = url

        status: ToolResultStatus = "ok"
        error = ""
        if resp.status_code >= 400:
            status = "failed"
            error = f"HTTP {resp.status_code}"
        elif expect and not expect_found:
            status = "failed"
            error = f"Expected text not found: {expect}"

        return ToolResult(
            call_id=call.id,
            name=call.name,
            status=status,
            content=info,
            error=error,
            metadata=metadata,
            artifacts=[
                ToolArtifact(
                    kind="web_fetch_content",
                    uri=url,
                    content=clean,
                    metadata=metadata,
                )
            ],
        )

    return web_fetch


def _extract_readable_text(html: str, source_url: str = "") -> str:
    import html as _html_module

    parts: list[str] = []
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = re.sub(r"\s+", " ", _html_module.unescape(title_match.group(1).strip()))
        parts.append(f"Title: {title}")

    quote = r'["' + "'" + r'"]'
    desc_re = re.compile(
        r"<meta\s+name\s*=\s*" + quote + r"description" + quote
        + r"\s+content\s*=\s*" + quote + r"([^\"'<>]+)" + quote,
        re.IGNORECASE,
    )
    desc_match = desc_re.search(html)
    if desc_match:
        parts.append(f"Description: {_html_module.unescape(desc_match.group(1))}")

    for tag in ("script", "style", "svg", "nav", "header", "footer", "aside", "noscript", "iframe"):
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

    html = re.sub(r"\s+", " ", html)
    html = re.sub(
        r"</?(?:div|p|h[1-6]|li|tr|br|hr|article|section|main|blockquote|pre|table|ul|ol|dl)[^>]*>",
        "\n",
        html,
        flags=re.IGNORECASE,
    )
    html = re.sub(r"<[^>]+>", "", html)
    text = _html_module.unescape(html)

    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    seen: set[str] = set()
    filtered: list[str] = []
    for line in lines:
        if len(line) < 3:
            continue
        if line.lower() in seen:
            continue
        seen.add(line.lower())
        normalized = line.lower()
        if normalized in (
            "skip to content",
            "skip to main content",
            "menu",
            "search",
            "subscribe",
            "sign in",
            "log in",
            "cookie",
            "privacy policy",
            "terms of service",
            "all rights reserved",
            "back to top",
            "scroll to top",
            "loading",
            "please enable javascript",
        ):
            continue
        if normalized.startswith(("share ", "tweet ", "posted on ", "last updated", "published:", "(c)")):
            continue
        filtered.append(line)

    if parts:
        parts.append("")
    parts.extend(filtered)

    result = "\n".join(parts)
    if len(result) < 100:
        result = re.sub(r"<[^>]+>", " ", html)
        result = re.sub(r"\s+", " ", result).strip()[:12000]
        result = f"[web_fetch {source_url}] Content extraction produced little output.\n\n{result}"

    return result
