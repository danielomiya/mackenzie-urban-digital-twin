from __future__ import annotations

from typing import Any

import httpx

from mudt.exceptions import (
    NonDataResponseError,
    RetrievalAddressDeadError,
    RetrievalError,
    UpstreamUnavailableError,
)

#: GeoSampa sits behind a WAF that resets connections carrying no conventional browser
#: `User-Agent`, so one must be sent for any request to complete at all.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_ZIP_MAGIC = b"PK"


def http_get(url: str, params: dict[str, Any], *, timeout: float = 30.0) -> httpx.Response:
    """
    Send a GET request, turning every failure into a typed `RetrievalError`.

    A redirect is treated like a 404: the address the configuration points to is no longer the
    one that serves the data, and the configuration should be updated.
    """
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": _USER_AGENT}) as client:
            response = client.get(url, params=params)
    except httpx.TransportError as exc:
        raise UpstreamUnavailableError(f"Could not reach {url}: {exc}", retrieval_url=url) from exc

    if response.status_code == httpx.codes.NOT_FOUND or response.is_redirect:
        raise RetrievalAddressDeadError(f"{url} returned {response.status_code}", retrieval_url=url)
    if response.is_server_error:
        raise UpstreamUnavailableError(f"{url} returned {response.status_code}", retrieval_url=url)
    if response.is_error:
        raise RetrievalError(f"{url} returned {response.status_code}", retrieval_url=url)
    return response


def ensure_json(response: httpx.Response) -> None:
    """
    Reject a response whose body is not JSON, even at HTTP 200.

    GeoServer answers some bad requests with HTTP 200 and an XML exception report, so the
    body is checked rather than the status code.
    """
    if response.content[:1] != b"{":
        raise NonDataResponseError(
            f"{response.url} did not return JSON", retrieval_url=str(response.url)
        )


def ensure_zip_attachment(response: httpx.Response) -> None:
    """
    Reject a response that is not a downloaded zip archive, even at HTTP 200.

    The GeoSampa download endpoint answers a missing file with HTTP 200 and an HTML error page,
    and labels genuine downloads `Content-Type: text/html` too. So neither the status nor the
    content type can be trusted: a real download is recognised by its `Content-Disposition:
    attachment` header *and* the zip magic bytes at the start of the body.
    """
    is_attachment = "attachment" in response.headers.get("content-disposition", "").lower()
    if not (is_attachment and response.content[:2] == _ZIP_MAGIC):
        raise NonDataResponseError(
            f"{response.url} did not return a zip archive", retrieval_url=str(response.url)
        )
