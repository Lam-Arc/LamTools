from __future__ import annotations

import ipaddress
import re
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from lamtools_core.tool import ToolArtifact, ToolCall, ToolResult, ToolResultStatus

_WEB_SEARCH_URL = "https://html.duckduckgo.com/html/"
_DEFAULT_FETCH_TIMEOUT = 30
_FETCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_HTTP_CLIENT: httpx.AsyncClient | None = None


def _http_session() -> httpx.AsyncClient:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        _HTTP_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(_DEFAULT_FETCH_TIMEOUT),
            follow_redirects=True,
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


async def _browser_check_get(url: str) -> httpx.Response:
    if not _is_loopback_url(url):
        return await _http_session().get(url)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(_DEFAULT_FETCH_TIMEOUT),
        follow_redirects=True,
        headers={"User-Agent": _FETCH_USER_AGENT},
        trust_env=False,
    ) as client:
        return await client.get(url)


def make_web_search_handler(work_root: str) -> Callable[[ToolCall], Awaitable[ToolResult]]:
    _ = work_root

    async def web_search(call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        query = args.get("query", "")
        limit = int(args.get("limit", 5) or 5)
        raw_domains = args.get("domains")
        domains = [str(item).strip() for item in raw_domains if str(item).strip()] if isinstance(raw_domains, list) else []
        if not query or not isinstance(query, str):
            return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'query' argument")
        search_query = query
        if domains:
            search_query = f"{query} " + " ".join(f"site:{domain}" for domain in domains)

        try:
            client = _http_session()
            resp = await client.post(_WEB_SEARCH_URL, data={"q": search_query})
            if resp.status_code != 200:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=(
                        f"[web_search] HTTP {resp.status_code} from DuckDuckGo - "
                        "try a different query or use web_fetch to a known URL"
                    ),
                    metadata={
                        "query": query,
                        "domains": domains,
                        "provider": "duckduckgo_html",
                        "status_code": resp.status_code,
                        "result_count": 0,
                    },
                )
            text = resp.text
            results: list[str] = []
            structured_results: list[dict[str, str]] = []
            link_pattern = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
            snippet_pattern = re.compile(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)

            links = link_pattern.findall(text)
            snippets = snippet_pattern.findall(text)

            for i, (url, title) in enumerate(links[:limit]):
                title_clean = re.sub(r"<[^>]+>", "", title).strip()
                title_clean = (
                    title_clean
                    .replace("&amp;", "&")
                    .replace("&lt;", "<")
                    .replace("&gt;", ">")
                    .replace("&quot;", "\"")
                    .replace("&#39;", "'")
                )
                snippet = ""
                if i < len(snippets):
                    snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
                results.append(f"{i+1}. {title_clean}\n   URL: {url}\n   {snippet}")
                structured_results.append({
                    "title": title_clean,
                    "url": url,
                    "snippet": snippet,
                    "source": "duckduckgo_html",
                })

            if not results:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content="[web_search] No results found for query: " + query,
                    metadata={
                        "query": query,
                        "domains": domains,
                        "provider": "duckduckgo_html",
                        "status_code": resp.status_code,
                        "result_count": 0,
                        "results": [],
                    },
                )

            content = f"[web_search results for '{query}']\n\n" + "\n\n".join(results)
            if len(content) > 8000:
                content = content[:8000] + "\n[... truncated]"
            metadata = {
                "query": query,
                "domains": domains,
                "provider": "duckduckgo_html",
                "status_code": resp.status_code,
                "result_count": len(structured_results),
                "results": structured_results,
            }
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content=content,
                metadata=metadata,
                artifacts=[
                    ToolArtifact(
                        kind="web_search_result",
                        uri="duckduckgo_html",
                        content=structured_results,
                        metadata={
                            "query": query,
                            "domains": domains,
                            "result_count": len(structured_results),
                        },
                    )
                ],
            )
        except httpx.HTTPError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"web_search network error: {exc}")
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"web_search error: {exc}")

    return web_search


def make_web_fetch_handler(work_root: str) -> Callable[[ToolCall], Awaitable[ToolResult]]:
    _ = work_root

    async def web_fetch(call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        url = args.get("url", "")
        if not url or not isinstance(url, str):
            return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'url' argument")
        if url.startswith("file://"):
            return ToolResult(call_id=call.id, name=call.name, status="failed", error="Access to file:// protocol is blocked")

        try:
            client = _http_session()
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"web_fetch network error: {exc}")
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"web_fetch error: {exc}")

        text = resp.text
        content_type = resp.headers.get("content-type", "")

        if "text/html" in content_type or url.endswith((".html", ".htm")) or "<html" in text[:200].lower():
            clean = _extract_readable_text(text, url)
        else:
            clean = text

        if len(clean) > 30000:
            clean = clean[:30000] + f"\n\n[... truncated at 30000 / {len(clean)} chars]"

        info = f"[web_fetch {url}] HTTP {resp.status_code}\n\n{clean}"
        metadata = {
            "url": url,
            "status_code": resp.status_code,
            "content_type": content_type,
            "text_length": len(clean),
            "truncated": "[... truncated" in clean,
        }
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="ok",
            content=info,
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


def make_browser_check_handler(work_root: str) -> Callable[[ToolCall], Awaitable[ToolResult]]:
    _ = work_root

    async def browser_check(call: ToolCall) -> ToolResult:
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
            resp = await _browser_check_get(url)
        except httpx.HTTPError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"browser_check network error: {exc}")
        except Exception as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"browser_check error: {exc}")

        body = resp.text or ""
        content_type = resp.headers.get("content-type", "")
        title = ""
        if "text/html" in content_type or "<html" in body[:500].lower():
            title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
            if title_match:
                title = re.sub(r"\s+", " ", title_match.group(1)).strip()

        expect_found = None
        if expect:
            expect_found = expect in body

        lines = [
            f"[browser_check {url}] HTTP {resp.status_code}",
            f"content_type: {content_type or 'unknown'}",
            f"bytes: {len(resp.content)}",
        ]
        if title:
            lines.append(f"title: {title}")
        if expect:
            lines.append(f"expect: {expect}")
            lines.append(f"expect_found: {str(expect_found).lower()}")

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
            content="\n".join(lines),
            error=error,
            metadata={
                "url": url,
                "status_code": resp.status_code,
                "content_type": content_type,
                "title": title,
                "expect": expect,
                "expect_found": expect_found,
            },
        )

    return browser_check


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
