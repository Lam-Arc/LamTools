from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


def _https_image_url(value: str, source_url: str) -> str:
    candidate = urljoin(source_url, unescape(value).strip())
    parsed = urlsplit(candidate)
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    return candidate


class _ImageCandidateParser(HTMLParser):
    """Collect source-backed image candidates without judging relevance."""

    def __init__(self, source_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source_url = source_url
        self.candidates: list[dict[str, str]] = []

    def _add(self, raw_url: str, *, alt: str = "", kind: str) -> None:
        url = _https_image_url(raw_url, self.source_url)
        if not url or any(item["url"] == url for item in self.candidates):
            return
        self.candidates.append(
            {"url": url, "alt": alt.strip(), "kind": kind, "source_url": self.source_url}
        )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag.lower() == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key in {"og:image", "og:image:url", "twitter:image", "twitter:image:src"}:
                self._add(values.get("content", ""), kind=key)
        elif tag.lower() == "link" and "image_src" in values.get("rel", "").lower().split():
            self._add(values.get("href", ""), kind="image_src")
        elif tag.lower() == "img" and len(self.candidates) < 8:
            self._add(values.get("src", ""), alt=values.get("alt", ""), kind="img")


def extract_image_candidates(
    html: str,
    source_url: str,
    limit: int = 8,
) -> list[dict[str, str]]:
    parser = _ImageCandidateParser(source_url)
    try:
        parser.feed(html)
    except Exception:
        return []
    return parser.candidates[:limit]


__all__ = ["extract_image_candidates"]
