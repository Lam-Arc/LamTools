"""Bounded response buffering for research tools, using their existing routes."""

from __future__ import annotations

import asyncio
import math

import httpx

MAX_SEARCH_RESPONSE_BYTES = 4 * 1024 * 1024
SEARCH_TOTAL_TIMEOUT_SECONDS = 120.0


class ResponseTooLarge(httpx.HTTPError):
    """The decoded response exceeded the research tool's input budget."""


async def bounded_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    total_timeout: float,
    max_response_bytes: int = MAX_SEARCH_RESPONSE_BYTES,
    **kwargs,
) -> httpx.Response:
    """Buffer a response with a wall clock deadline and a decoded byte limit.

    HTTPX's read timeout only bounds idle gaps. Its automatic redirect handling
    also buffers redirect bodies before returning a streaming final response.
    Follow its generated next_request instead, closing intermediate responses
    without reading their bodies; cookies and POST redirect rules stay HTTPX's.
    """
    if not math.isfinite(total_timeout) or total_timeout <= 0:
        raise ValueError("Network total timeout must be a finite positive number")
    follow_redirects = kwargs.pop("follow_redirects", client.follow_redirects)
    kwargs.setdefault("timeout", total_timeout)
    history: list[httpx.Response] = []
    try:
        async with asyncio.timeout(total_timeout):
            request = client.build_request(method, url, **kwargs)
            for hop in range(client.max_redirects + 1):
                response = await client.send(request, stream=True, follow_redirects=False)
                try:
                    next_request = response.next_request
                    if next_request is not None and follow_redirects:
                        if hop == client.max_redirects:
                            raise httpx.TooManyRedirects("Too many redirects", request=request)
                        history.append(response)
                        request = next_request
                        continue
                    content = bytearray()
                    # Callers that inspect redirects only need their headers.
                    if next_request is None:
                        async for chunk in response.aiter_bytes():
                            if len(content) + len(chunk) > max_response_bytes:
                                raise ResponseTooLarge(
                                    f"Response exceeds the {max_response_bytes} byte decoded size limit; "
                                    "fetch a smaller document or a narrower source."
                                )
                            content.extend(chunk)
                    # The stream already decoded content-encoding. Construct a
                    # buffered response without decompressing it a second time.
                    headers = response.headers.copy()
                    headers.pop("content-encoding", None)
                    headers["content-length"] = str(len(content))
                    buffered = httpx.Response(
                        response.status_code,
                        headers=headers,
                        content=bytes(content),
                        request=response.request,
                        extensions=response.extensions,
                    )
                    buffered.history = history
                    return buffered
                finally:
                    await response.aclose()
    except TimeoutError as exc:
        raise httpx.TimeoutException(
            f"Network request exceeded its {total_timeout:g}s total time limit."
        ) from exc
    except httpx.TimeoutException as exc:
        raise httpx.TimeoutException(
            f"Network request timed out while connecting or waiting for data "
            f"(limit {total_timeout:g}s)."
        ) from exc
    raise AssertionError("Redirect loop did not return a response")
