"""iGuardStove web client - handles login and scraping of stove data."""

import asyncio
import logging
import urllib.parse
from datetime import date, tzinfo
from typing import Any

import aiohttp
import yarl
from bs4 import BeautifulSoup

from .const import (
    BASE_URL,
    DASHBOARD_URL,
    LOGIN_URL,
    USER_AGENT,
)
from .exceptions import (
    AmbiguousRequestError,
    CannotConnect,
    DevicePageParseError,
    EventParseError,
    IGuardStoveException,
    InvalidAuth,
)
from .parser import (
    LockFormData,
    has_password_input,
    normalize_status,
    parse_dashboard_devices,
    parse_device_page,
    parse_lock_form,
    parse_lock_state,
    parse_login_csrf,
    parse_login_errors,
    validate_device_page_invariants,
)
from .types import DeviceData, DeviceSummary

REQUEST_TIMEOUT = 15
MAX_REDIRECTS = 5
MAX_SAFE_ATTEMPTS = 3
SAFE_METHODS = frozenset({"GET", "HEAD"})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
GET_AFTER_REDIRECT = frozenset({301, 302, 303})

_LOGGER = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = [
    "AmbiguousRequestError",
    "CannotConnect",
    "DevicePageParseError",
    "EventParseError",
    "IGuardStoveClient",
    "IGuardStoveException",
    "InvalidAuth",
    "normalize_status",
]


class IGuardStoveClient:
    """Client for the iGuardStove web management portal.

    Authenticates via the Django-based login form (CSRF token + session cookie)
    and scrapes device status data from the HTML device pages.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self.username = username
        self.password = password
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self._device_locks: dict[str, asyncio.Lock] = {}
        self._login_lock = asyncio.Lock()
        self._auth_generation = 0

    @property
    def auth_generation(self) -> int:
        """Return the current authentication generation count."""
        return self._auth_generation

    async def close(self) -> None:
        """Close the underlying client session."""
        if self._session and not bool(getattr(self._session, "closed", False)):
            await self._session.close()

    def _get_device_lock(self, device_id: str) -> asyncio.Lock:
        """Get or create per-device asyncio lock."""
        if device_id not in self._device_locks:
            self._device_locks[device_id] = asyncio.Lock()
        return self._device_locks[device_id]

    def _validate_origin(self, url: str | yarl.URL) -> None:
        """Validate URL origin matches the expected HTTPS portal origin."""
        target = yarl.URL(url)
        expected = yarl.URL(BASE_URL)
        if target.scheme != "https":
            raise CannotConnect(f"Insecure URL scheme: {target.scheme}")
        if target.host != expected.host:
            raise CannotConnect(
                f"URL origin mismatch: expected {expected.host}, got {target.host}"
            )

    def _resolve_redirect_url(
        self, current_url: str | yarl.URL, location: str
    ) -> yarl.URL:
        """Resolve a Location header against the current URL and validate origin."""
        next_url = yarl.URL(current_url).join(yarl.URL(location))
        self._validate_origin(next_url)
        return next_url

    def _check_final_response(
        self,
        resp: aiohttp.ClientResponse,
        url: str,
        is_login_page: bool,
    ) -> None:
        """Validate a non-redirect response status, origin, and content type."""
        final_url = resp.url
        self._validate_origin(final_url)

        final_str = str(final_url).lower()
        if not is_login_page and (
            "login" in final_url.path.lower() or "login" in final_str
        ):
            raise InvalidAuth("Session expired or redirected to login page")

        if resp.status in (401, 403):
            raise InvalidAuth(
                f"Authentication failure (HTTP {resp.status}) accessing {url}"
            )

        if resp.status in RETRYABLE_STATUSES:
            raise AmbiguousRequestError(
                f"HTTP request to {url} returned status {resp.status}"
            )

        if resp.status != 200:
            raise CannotConnect(f"HTTP request to {url} returned status {resp.status}")

        content_type = resp.headers.get("Content-Type", "").lower()
        if (
            content_type
            and "text/html" not in content_type
            and "application/xhtml+xml" not in content_type
            and "text/plain" not in content_type
        ):
            raise CannotConnect(f"Unexpected content type {content_type!r} from {url}")

    async def _read_response_html(
        self, resp: aiohttp.ClientResponse, max_html_size: int, url: str
    ) -> str:
        """Read response body in chunks and enforce max size limit."""
        body_bytes = bytearray()
        while len(body_bytes) <= max_html_size:
            chunk = await resp.content.read(65536)
            if not chunk:
                break
            body_bytes.extend(chunk)

        if len(body_bytes) > max_html_size:
            raise CannotConnect(
                f"Response body from {url} exceeds maximum size limit of {max_html_size} bytes"
            )

        return body_bytes.decode("utf-8", errors="replace")

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: Any = None,
        allow_redirects: bool = True,
        is_login_page: bool = False,
    ) -> tuple[int, str, yarl.URL]:
        """Shared request helper with safe-method retries and pre-validated redirects.

        ``allow_redirects`` is accepted for call-site compatibility but redirects are
        always followed manually after validating each Location header.
        """
        del allow_redirects  # Always follow manually after origin validation.
        self._validate_origin(url)
        req_headers = {**self._headers, **(headers or {})}
        method_upper = method.upper()
        can_retry = method_upper in SAFE_METHODS
        max_attempts = MAX_SAFE_ATTEMPTS if can_retry else 1
        max_html_size = 5 * 1024 * 1024  # 5MB limit

        for attempt in range(max_attempts):
            try:
                return await self._request_with_redirects(
                    method_upper,
                    url,
                    req_headers=req_headers,
                    data=data,
                    is_login_page=is_login_page,
                    max_html_size=max_html_size,
                )
            except AmbiguousRequestError:
                if can_retry and attempt < max_attempts - 1:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise
            except (InvalidAuth, CannotConnect):
                raise
            except TimeoutError as ex:
                ambiguous = AmbiguousRequestError(f"Timeout connecting to {url}")
                ambiguous.__cause__ = ex
                if can_retry and attempt < max_attempts - 1:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise ambiguous from ex
            except aiohttp.ClientError as ex:
                ambiguous = AmbiguousRequestError(
                    f"Network error during {method_upper} to {url}"
                )
                ambiguous.__cause__ = ex
                if can_retry and attempt < max_attempts - 1:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise ambiguous from ex

        raise CannotConnect(f"Request to {url} failed after retries")

    async def _request_with_redirects(
        self,
        method: str,
        url: str,
        *,
        req_headers: dict[str, str],
        data: Any,
        is_login_page: bool,
        max_html_size: int,
    ) -> tuple[int, str, yarl.URL]:
        """Perform one logical request, validating and following redirects manually."""
        current_method = method
        current_url = url
        current_data = data

        for _ in range(MAX_REDIRECTS + 1):
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    current_method,
                    current_url,
                    headers=req_headers,
                    data=current_data,
                    allow_redirects=False,
                ) as resp:
                    if resp.status in REDIRECT_STATUSES:
                        location = resp.headers.get("Location")
                        if not location:
                            raise CannotConnect(
                                f"Redirect from {current_url} missing Location header"
                            )
                        next_url = self._resolve_redirect_url(current_url, location)
                        if resp.status in GET_AFTER_REDIRECT:
                            current_method = "GET"
                            current_data = None
                        current_url = str(next_url)
                        continue

                    self._check_final_response(resp, current_url, is_login_page)
                    html = await self._read_response_html(
                        resp, max_html_size, current_url
                    )
                    return resp.status, html, resp.url

        raise CannotConnect(
            f"Too many redirects (>{MAX_REDIRECTS}) while requesting {url}"
        )

    async def async_login(self, current_generation: int | None = None) -> bool:
        """Log in to the iGuardFire management portal with account-level lock serialization."""
        async with self._login_lock:
            if (
                current_generation is not None
                and current_generation < self._auth_generation
            ):
                _LOGGER.debug(
                    "Session was already re-authenticated by another operation "
                    "(generation %d -> %d), skipping duplicate login",
                    current_generation,
                    self._auth_generation,
                )
                return True

            last_error: Exception | None = None
            for attempt in range(2):
                try:
                    await self._async_login_once()
                    self._auth_generation += 1
                    _LOGGER.info(
                        "iGuardStove login successful (generation %d)",
                        self._auth_generation,
                    )
                    return True
                except AmbiguousRequestError as err:
                    last_error = err
                    _LOGGER.warning(
                        "Ambiguous login failure (attempt %d); restarting CSRF login flow: %s",
                        attempt + 1,
                        err,
                    )

            raise CannotConnect(
                "Login failed after restarting CSRF flow"
            ) from last_error

    async def _async_login_once(self) -> None:
        """Perform a single CSRF login cycle (GET token + POST credentials)."""
        _LOGGER.debug("Fetching iGuardFire login page for CSRF token")
        _, html, _ = await self._request("GET", LOGIN_URL, is_login_page=True)

        csrf_token = parse_login_csrf(html)
        if not csrf_token:
            raise CannotConnect("csrfmiddlewaretoken not found on login page")

        _LOGGER.debug("CSRF token obtained")
        payload = {
            "csrfmiddlewaretoken": csrf_token,
            "login": self.username,
            "password": self.password,
        }
        post_headers = {"Referer": LOGIN_URL}

        _LOGGER.debug("Submitting login credentials")
        _, login_html, final_url = await self._request(
            "POST",
            LOGIN_URL,
            data=payload,
            headers=post_headers,
            is_login_page=True,
        )

        self._validate_login_response(login_html, final_url)

    def _validate_login_response(self, login_html: str, final_url: yarl.URL) -> None:
        """Validate login post response HTML and final redirect URL."""
        err_text = parse_login_errors(login_html)
        if err_text:
            raise InvalidAuth(err_text)

        final_str = str(final_url).lower()
        if "login" in final_url.path.lower() or (
            "login" in final_str and "next" in final_str
        ):
            raise InvalidAuth("Credentials were rejected")

        if has_password_input(login_html):
            raise InvalidAuth("Login page still present after credentials submission")

    async def async_get_devices(self, retry_login: bool = True) -> list[DeviceSummary]:
        """Fetch all registered iGuardStove devices from the dashboard."""
        _LOGGER.debug("Fetching dashboard to discover devices")
        gen = self._auth_generation
        try:
            _, html, _ = await self._request("GET", DASHBOARD_URL)
        except InvalidAuth:
            if retry_login:
                _LOGGER.info("Session expired during device discovery, re-logging in")
                await self.async_login(current_generation=gen)
                return await self.async_get_devices(retry_login=False)
            raise

        devices = parse_dashboard_devices(html)
        _LOGGER.debug("Discovered %d device(s)", len(devices))
        return devices

    async def async_get_device_data(
        self,
        device_id: str,
        retry_login: bool = True,
        event_date: date | None = None,
        tzinfo: tzinfo | None = None,
    ) -> DeviceData:
        """Fetch and parse all sensor data for a single device."""
        url = f"{BASE_URL}/devices/{device_id}/"
        _LOGGER.debug("Fetching device page: %s", url)
        gen = self._auth_generation

        try:
            _, html, _ = await self._request("GET", url)
        except InvalidAuth:
            if retry_login:
                _LOGGER.info("Session expired for device %s, re-logging in", device_id)
                await self.async_login(current_generation=gen)
                return await self.async_get_device_data(
                    device_id,
                    retry_login=False,
                    event_date=event_date,
                    tzinfo=tzinfo,
                )
            raise

        data = self._parse_device_page(
            device_id, html, event_date=event_date, tzinfo=tzinfo
        )
        _LOGGER.debug(
            "Parsed device %s: status=%s lock=%s temp=%s events=%d",
            device_id,
            data.get("status"),
            data.get("is_locked"),
            data.get("temperature"),
            len(data.get("today_events") or ()),
        )
        return data

    def _parse_device_page(
        self,
        device_id: str,
        html: str,
        event_date: date | None = None,
        tzinfo: tzinfo | None = None,
    ) -> DeviceData:
        """Parse the device detail page HTML into a DeviceData dict."""
        return parse_device_page(device_id, html, event_date=event_date, tzinfo=tzinfo)

    async def async_set_lock_state(
        self, device_id: str, target_locked: bool, retry_login: bool = True
    ) -> None:
        """Safely and idempotently set device lock state."""
        lock = self._get_device_lock(device_id)
        async with lock:
            await self._async_set_lock_state_internal(
                device_id, target_locked, retry_login=retry_login
            )

    async def _async_set_lock_state_internal(
        self, device_id: str, target_locked: bool, retry_login: bool = True
    ) -> None:
        """Internal helper for setting lock state while holding per-device lock."""
        url = f"{BASE_URL}/devices/{device_id}/"
        gen = self._auth_generation
        try:
            _, html, _ = await self._request("GET", url)
        except InvalidAuth:
            if retry_login:
                _LOGGER.info("Session expired before lock state change, re-logging in")
                await self.async_login(current_generation=gen)
                return await self._async_set_lock_state_internal(
                    device_id, target_locked, retry_login=False
                )
            raise

        try:
            form_data = parse_lock_form(html, device_id)
        except ValueError as ex:
            raise CannotConnect(str(ex)) from ex

        if form_data.is_currently_locked == target_locked:
            _LOGGER.debug(
                "Device %s is already in target lock state (%s), skipping POST",
                device_id,
                target_locked,
            )
            return

        await self._execute_lock_state_change(
            url,
            device_id,
            target_locked,
            form_data,
            retry_login,
            allow_controlled_retry=True,
        )

    async def _async_fetch_verification_page(
        self, url: str, device_id: str, retry_login: bool = True
    ) -> str:
        """Fetch device page for verification, handling session expiration reauthentication."""
        gen = self._auth_generation
        try:
            _, html, _ = await self._request("GET", url)
            return html
        except InvalidAuth:
            if retry_login:
                _LOGGER.info(
                    "Session expired during lock verification GET for %s, re-logging in",
                    device_id,
                )
                await self.async_login(current_generation=gen)
                return await self._async_fetch_verification_page(
                    url, device_id, retry_login=False
                )
            raise

    async def _confirm_lock_state(
        self,
        url: str,
        device_id: str,
        target_locked: bool,
        post_html: str | None,
        retry_login: bool,
    ) -> bool:
        """Return True if device page confirms the target lock state."""
        if post_html is not None:
            try:
                post_soup = BeautifulSoup(post_html, "html.parser")
                validate_device_page_invariants(post_soup, device_id)
                final_locked = parse_lock_state(post_soup)
                if final_locked == target_locked:
                    return True
            except (DevicePageParseError, InvalidAuth):
                pass

        refetch_html = await self._async_fetch_verification_page(
            url, device_id, retry_login=retry_login
        )
        refetch_soup = BeautifulSoup(refetch_html, "html.parser")
        validate_device_page_invariants(refetch_soup, device_id)
        return parse_lock_state(refetch_soup) == target_locked

    async def _execute_lock_state_change(
        self,
        url: str,
        device_id: str,
        target_locked: bool,
        form_data: LockFormData,
        retry_login: bool,
        *,
        allow_controlled_retry: bool,
    ) -> None:
        """Perform lock state change HTTP POST and verify state update."""
        expected_button_name = "lock" if target_locked else "unlock"
        if form_data.button_name != expected_button_name:
            raise CannotConnect(
                f"Form action {form_data.button_name!r} does not match required action for "
                f"target_locked={target_locked}"
            )

        payload = {
            "csrfmiddlewaretoken": form_data.csrf_token,
            form_data.button_name: form_data.button_value,
        }
        post_url = (
            urllib.parse.urljoin(url, form_data.action) if form_data.action else url
        )
        post_headers = {"Referer": url}
        gen = self._auth_generation

        _LOGGER.debug(
            "Posting lock state change for device %s (target_locked=%s) to %s",
            device_id,
            target_locked,
            post_url,
        )

        post_html: str | None
        try:
            _, post_html, _ = await self._request(
                "POST", post_url, headers=post_headers, data=payload
            )
        except InvalidAuth:
            if retry_login:
                _LOGGER.info("Session expired during lock POST, re-logging in")
                await self.async_login(current_generation=gen)
                return await self._async_set_lock_state_internal(
                    device_id, target_locked, retry_login=False
                )
            raise
        except AmbiguousRequestError as err:
            _LOGGER.warning(
                "Ambiguous lock POST for device %s; verifying state before any retry: %s",
                device_id,
                err,
            )
            if await self._confirm_lock_state(
                url, device_id, target_locked, None, retry_login
            ):
                _LOGGER.info(
                    "Lock state for device %s already at target %s after ambiguous POST",
                    device_id,
                    target_locked,
                )
                return

            if not allow_controlled_retry:
                raise CannotConnect(
                    f"Failed to confirm lock state transition for device {device_id}: "
                    f"expected {target_locked} after ambiguous POST"
                ) from err

            _, refresh_html, _ = await self._request("GET", url)
            try:
                refreshed_form = parse_lock_form(refresh_html, device_id)
            except ValueError as ex:
                raise CannotConnect(str(ex)) from ex

            if refreshed_form.is_currently_locked == target_locked:
                _LOGGER.info(
                    "Lock state for device %s already at target %s after form refresh",
                    device_id,
                    target_locked,
                )
                return

            await self._execute_lock_state_change(
                url,
                device_id,
                target_locked,
                refreshed_form,
                retry_login,
                allow_controlled_retry=False,
            )
            return

        if await self._confirm_lock_state(
            url, device_id, target_locked, post_html, retry_login
        ):
            _LOGGER.info(
                "Lock state for device %s successfully changed to %s",
                device_id,
                target_locked,
            )
            return

        raise CannotConnect(
            f"Failed to confirm lock state transition for device {device_id}: "
            f"expected {target_locked}"
        )
