"""Meta Graph API client: pagination, retries with backoff, rate limits, clear token errors."""
from __future__ import annotations

import json
import logging
import time
from typing import Callable, Iterator

import httpx

log = logging.getLogger(__name__)

BASE = "https://graph.facebook.com/"

# Graph API error codes.
RETRY_CODES = {1, 2, 4, 17, 32, 341, 368, 613, 80001, 80002, 80005, 80006, 80008}  # transient errors and rate limits
TOKEN_CODES = {102, 190}
PERMISSION_CODES = {10, *range(200, 300)}


class GraphError(Exception):
    def __init__(self, message: str, *, code: int | None = None, subcode: int | None = None,
                 status: int | None = None, raw: dict | None = None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.status = status
        self.raw = raw or {}


class TokenError(GraphError):
    """The token is invalid, expired or revoked. Syncing makes no sense until it is renewed."""


class GraphPermissionError(GraphError):
    """A missing permission, or a resource not assigned to the system user."""


class MetricError(GraphError):
    """The API does not know the metric (Meta renamed it) or does not support it for this object."""


def explain_token_error(code: int | None, subcode: int | None, message: str) -> str:
    hints = {
        463: "The token has expired.",
        460: "The token was invalidated after the account password changed.",
        467: "The token is invalid.",
        458: "The app was disconnected from the account.",
        492: "The user no longer has a role on this page.",
    }
    head = hints.get(subcode or 0, "Meta rejected the token.")
    return (f"{head} Generate a new system user token in Business Manager "
            f"(System users → Generate token, expiry: Never) and paste it in the program: "
            f"Settings → connection → Change token. Details from Meta: {message}")


def _classify(status: int, body: dict) -> GraphError:
    err = body.get("error") or {}
    code = err.get("code")
    sub = err.get("error_subcode")
    msg = err.get("message") or f"HTTP {status}"
    kw = dict(code=code, subcode=sub, status=status, raw=err)
    if code in TOKEN_CODES:
        return TokenError(explain_token_error(code, sub, msg), **kw)
    if code in PERMISSION_CODES:
        return GraphPermissionError(
            f"Missing permission or no access to the resource ({msg}). Check the token's permissions and "
            f"whether the page or IG account is assigned to the system user.", **kw)
    if code == 100 and "metric" in msg.lower():
        return MetricError(msg, **kw)
    return GraphError(msg, **kw)


def _max_usage(headers: httpx.Headers) -> tuple[float, int]:
    """Highest rate limit usage in % and the suggested wait in seconds, from Meta's headers."""
    top, wait = 0.0, 0
    for name in ("x-app-usage", "x-page-usage", "x-business-use-case-usage", "x-ad-account-usage"):
        raw = headers.get(name)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        items = [data] if name in ("x-app-usage", "x-page-usage", "x-ad-account-usage") else \
            [i for lst in data.values() for i in lst]
        for i in items:
            for k in ("call_count", "total_cputime", "total_time"):
                top = max(top, float(i.get(k) or 0))
            wait = max(wait, int(i.get("estimated_time_to_regain_access") or 0) * 60)
    return top, wait


class Graph:
    def __init__(self, token: str, version: str, *, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep, max_tries: int = 5, base: str | None = None):
        if not token:
            raise TokenError("No token. Add a system user token in the program: Settings → Add Meta connection.")
        self.token = token
        self.version = version
        self.fake = base == "fake"
        if self.fake:  # Meta API simulator for tests (metastat.fakeapi), no internet connection
            from metastat.fakeapi.transport import FAKE_BASE, transport
            self.base = FAKE_BASE
            client = client or httpx.Client(transport=transport(), timeout=60)
        else:
            self.base = (base or BASE).rstrip("/") + "/"
        if client is None:
            from metastat import net
            client = net.client()
        self.client = client
        self.sleep = sleep
        self.max_tries = max_tries
        self.calls = 0
        self._page_tokens: dict[str, str] = {}

    # ---------- low level ----------

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            # a full URL (paging.next) comes from an API response: the token goes only to the same Meta server
            u, b = httpx.URL(path), httpx.URL(self.base)
            if (u.scheme, u.host, u.port) != (b.scheme, b.host, b.port):
                raise GraphError(f"Rejected a URL outside the Graph API: {u.scheme}://{u.host}")
            return path
        return self.base + self.version + "/" + path.lstrip("/")

    def request(self, path: str, params: dict | None = None, *, token: str | None = None) -> dict:
        url = self._url(path)
        safe = url.split("?")[0]
        # The token goes in the Authorization header, never in the URL (URLs end up in logs, proxies and history).
        # Meta's paging.next links contain access_token, so it is stripped from them.
        # Merge with the parameters already in the URL (paging.next): httpx with params= replaces the whole query.
        full = httpx.URL(url).copy_remove_param("access_token").copy_merge_params(dict(params or {}))
        headers = {"Authorization": f"Bearer {token or self.token}"}
        for attempt in range(1, self.max_tries + 1):
            try:
                resp = self.client.get(full, headers=headers)
            except httpx.TransportError as e:
                if attempt == self.max_tries:
                    raise GraphError(f"Cannot connect to Meta ({e}).") from e
                self._backoff(attempt, f"network error at {safe}")
                continue
            self.calls += 1
            try:
                body = resp.json()
            except ValueError:
                body = {"error": {"message": f"Invalid response, HTTP {resp.status_code}"}}

            usage, wait = _max_usage(resp.headers)
            if usage >= 95:
                pause = min(max(wait, 60), 900)
                log.warning("Meta rate limit at %.0f%%, waiting %ss", usage, pause)
                self.sleep(pause)

            if resp.status_code < 400 and "error" not in body:
                return body
            err = _classify(resp.status_code, body)
            retriable = err.code in RETRY_CODES or resp.status_code >= 500
            if retriable and attempt < self.max_tries:
                self._backoff(attempt, f"{err} ({safe})", minimum=wait)
                continue
            raise err
        raise GraphError("The request could not be completed")  # unreachable

    def _backoff(self, attempt: int, why: str, minimum: int = 0) -> None:
        delay = max(minimum, min(2 ** attempt * 2, 120))
        log.warning("Retrying in %ss (attempt %s/%s): %s", delay, attempt + 1, self.max_tries, why)
        self.sleep(delay)

    # ---------- convenience ----------

    def get(self, path: str, params: dict | None = None, *, token: str | None = None) -> dict:
        return self.request(path, params, token=token)

    def paginate(self, path: str, params: dict | None = None, *, token: str | None = None,
                 max_pages: int = 200) -> Iterator[dict]:
        body = self.request(path, params, token=token)
        for _ in range(max_pages):
            yield from body.get("data") or []
            nxt = (body.get("paging") or {}).get("next")
            if not nxt:
                return
            body = self.request(nxt, token=token)
        log.warning("Stopped paginating %s after %s pages", path, max_pages)

    def page_token(self, page_id: str) -> str:
        """Page token from the system user token (page insights and posts require it)."""
        if page_id not in self._page_tokens:
            data = self.request(page_id, {"fields": "access_token"})
            tok = data.get("access_token")
            if not tok:
                raise GraphPermissionError(
                    f"The token gives no access to page {page_id}. Assign the page to the system user "
                    f"(Business Manager → System users → Assign assets).")
            self._page_tokens[page_id] = tok
        return self._page_tokens[page_id]
