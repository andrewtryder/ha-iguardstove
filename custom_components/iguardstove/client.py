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

_LOGGER = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = [
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

    async def async_close(self) -> None:
        """Close underlying HTTP session resources if open."""
        if not self._session.closed:
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
        """Shared request helper validating status, origin, content-type, login redirects, and timeout."""
        self._validate_origin(url)
        req_headers = {**self._headers, **(headers or {})}

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method,
                    url,
                    headers=req_headers,
                    data=data,
                    allow_redirects=allow_redirects,
                ) as resp:
                    final_url = resp.url
                    self._validate_origin(final_url)

                    # Detect redirect to login page for non-login requests
                    final_str = str(final_url).lower()
                    if not is_login_page and (
                        "login" in final_url.path.lower() or "login" in final_str
                    ):
                        raise InvalidAuth("Session expired or redirected to login page")

                    if resp.status != 200:
                        raise CannotConnect(
                            f"HTTP request to {url} returned status {resp.status}"
                        )

                    content_type = resp.headers.get("Content-Type", "").lower()
                    if (
                        content_type
                        and "text/html" not in content_type
                        and "application/xhtml+xml" not in content_type
                        and "text/plain" not in content_type
                    ):
                        raise CannotConnect(
                            f"Unexpected content type {content_type!r} from {url}"
                        )

                    html = await resp.text()
                    return resp.status, html, final_url
        except asyncio.TimeoutError as ex:
            raise CannotConnect(f"Timeout connecting to {url}") from ex
        except aiohttp.ClientError as ex:
            raise CannotConnect(f"Network error during {method} to {url}") from ex

    async def async_login(self) -> bool:
        """Log in to the iGuardFire management portal.

        Django's CSRF protection requires:
        1. GET the login page to receive the session cookie and csrfmiddlewaretoken.
        2. POST credentials with the token included, and the Referer header set.
        """
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
            allow_redirects=True,
            is_login_page=True,
        )

        self._validate_login_response(login_html, final_url)
        _LOGGER.info("iGuardStove login successful (redirected to %s)", final_url)
        return True

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
        try:
            _, html, _ = await self._request("GET", DASHBOARD_URL)
        except InvalidAuth:
            if retry_login:
                _LOGGER.info("Session expired, re-logging in")
                await self.async_login()
                return await self.async_get_devices(retry_login=False)
            raise

        devices = parse_dashboard_devices(html)
        _LOGGER.debug("Discovered %d device(s): %s", len(devices), devices)
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

        try:
            _, html, _ = await self._request("GET", url)
        except InvalidAuth:
            if retry_login:
                _LOGGER.info("Session expired, re-logging in")
                await self.async_login()
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
        _LOGGER.debug("Parsed device data for %s: %s", device_id, data)
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
        try:
            _, html, _ = await self._request("GET", url)
        except InvalidAuth:
            if retry_login:
                _LOGGER.info("Session expired before lock state change, re-logging in")
                await self.async_login()
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
            url, device_id, target_locked, form_data, retry_login
        )

    async def _execute_lock_state_change(
        self,
        url: str,
        device_id: str,
        target_locked: bool,
        form_data: LockFormData,
        retry_login: bool,
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

        _LOGGER.debug(
            "Posting lock state change for device %s (target_locked=%s) to %s",
            device_id,
            target_locked,
            post_url,
        )

        try:
            _, post_html, _ = await self._request(
                "POST", post_url, headers=post_headers, data=payload
            )
        except InvalidAuth:
            if retry_login:
                _LOGGER.info("Session expired during lock POST, re-logging in")
                await self.async_login()
                return await self._async_set_lock_state_internal(
                    device_id, target_locked, retry_login=False
                )
            raise

        final_locked: bool | None = None
        try:
            post_soup = BeautifulSoup(post_html, "html.parser")
            validate_device_page_invariants(post_soup, device_id)
            final_locked = parse_lock_state(post_soup)
        except DevicePageParseError, InvalidAuth:
            final_locked = None

        if final_locked != target_locked:
            _, refetch_html, _ = await self._request("GET", url)
            refetch_soup = BeautifulSoup(refetch_html, "html.parser")
            validate_device_page_invariants(refetch_soup, device_id)
            final_locked = parse_lock_state(refetch_soup)

        if final_locked != target_locked:
            raise CannotConnect(
                f"Failed to confirm lock state transition for device {device_id}: "
                f"expected {target_locked}, got {final_locked}"
            )

        _LOGGER.info(
            "Lock state for device %s successfully changed to %s",
            device_id,
            target_locked,
        )
