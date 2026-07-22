"""iGuardStove web client - handles login and scraping of stove data."""

import asyncio
import logging
import re
import urllib.parse
from typing import Any

import aiohttp
import yarl
from bs4 import BeautifulSoup

from .const import (
    BASE_URL,
    LOGIN_URL,
    SEL_INFO_BLOCK,
    SEL_INFO_TITLE,
    SEL_INFO_VALUE,
    SEL_LOCK_IMG,
    SEL_STATUS_ICON,
    SEL_STOVE_DATE,
    SEL_STOVE_STATUS_TEXT,
    SEL_STOVE_TITLE,
    STATUS_MAP,
    USER_AGENT,
)

# Pre-compiled regular expressions for performance
DEVICE_URL_RE = re.compile(r"^/devices/([A-F0-9]+)/$")
CHECKIN_PREFIX_RE = re.compile(
    r"^iGuardStove\s+Last\s+Checked\s+In:\s*", flags=re.IGNORECASE
)
TEMP_RE = re.compile(r"([\d.]+)\s*(°[FC]?)?")

REQUEST_TIMEOUT = 15

_LOGGER = logging.getLogger(__name__)
_SEEN_UNKNOWN_STATUSES: set[str] = set()


class IGuardStoveException(Exception):
    """Base exception for iGuardStove integration."""


class CannotConnect(IGuardStoveException):
    """Exception to indicate connection error."""


class InvalidAuth(IGuardStoveException):
    """Exception to indicate authentication error."""


def normalize_status(raw: str | None) -> str | None:
    """Map a raw portal status string to a clean, normalised label.

    Checks each key in STATUS_MAP (in definition order) as a substring of the
    lowercased raw string. Returns the first match found.

    If no known pattern matches, the raw text is returned unchanged AND a
    WARNING is logged once per distinct unknown raw status value.
    """
    if not raw:
        return raw
    lower = raw.lower()
    for pattern, label in STATUS_MAP.items():
        if pattern in lower:
            return label
    if raw not in _SEEN_UNKNOWN_STATUSES:
        _SEEN_UNKNOWN_STATUSES.add(raw)
        _LOGGER.warning(
            "Unknown iGuardStove status encountered: %r — "
            "please open an issue or add it to STATUS_MAP in const.py",
            raw,
        )
    return raw  # fall back to raw text so the sensor still has a value


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

        soup = BeautifulSoup(html, "html.parser")
        csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
        if not csrf_input or not csrf_input.get("value"):
            raise CannotConnect("csrfmiddlewaretoken not found on login page")

        csrf_token = csrf_input.get("value")
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

        # Check for specific error elements on the returned login page first
        err_soup = BeautifulSoup(login_html, "html.parser")
        err_el = err_soup.find(class_="errorlist") or err_soup.find(
            class_="alert-danger"
        )
        if err_el:
            raise InvalidAuth(err_el.get_text(strip=True))

        final_str = str(final_url).lower()
        if "login" in final_url.path.lower() or ("login" in final_str and "next" in final_str):
            raise InvalidAuth("Credentials were rejected")

        # Positive authenticated-page invariant: reject if password input remains on page
        if err_soup.find("input", {"type": "password"}):
            raise InvalidAuth("Login page still present after credentials submission")

        _LOGGER.info("iGuardStove login successful (redirected to %s)", final_url)
        return True

    async def async_get_devices(self, retry_login: bool = True) -> list[dict[str, Any]]:
        """Fetch all registered iGuardStove devices from the dashboard.

        Returns a list of dicts with keys: device_id, device_name.
        """
        _LOGGER.debug("Fetching dashboard to discover devices")
        try:
            _, html, _ = await self._request("GET", f"{BASE_URL}/")
        except InvalidAuth:
            if retry_login:
                _LOGGER.info("Session expired, re-logging in")
                await self.async_login()
                return await self.async_get_devices(retry_login=False)
            raise

        soup = BeautifulSoup(html, "html.parser")
        devices = []
        seen_device_ids = set()

        for link in soup.find_all("a", href=True):
            href: str = link["href"]
            m = DEVICE_URL_RE.match(href)
            if m:
                device_id = m.group(1)
                parent = link.find_parent(class_="stove_line")
                name = "iGuardStove"
                if parent:
                    title_el = parent.find(class_=SEL_STOVE_TITLE)
                    if title_el:
                        name = title_el.get_text(strip=True)
                if device_id not in seen_device_ids:
                    seen_device_ids.add(device_id)
                    devices.append({"device_id": device_id, "device_name": name})

        _LOGGER.debug("Discovered %d device(s): %s", len(devices), devices)
        return devices

    async def async_get_device_data(
        self, device_id: str, retry_login: bool = True
    ) -> dict[str, Any]:
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
                    device_id, retry_login=False
                )
            raise

        return self._parse_device_page(device_id, html)

    def _parse_device_page(self, device_id: str, html: str) -> dict[str, Any]:
        """Parse the device detail page HTML into a data dict."""
        soup = BeautifulSoup(html, "html.parser")
        data: dict[str, Any] = {"device_id": device_id}

        # Device name
        title_el = soup.find(class_=SEL_STOVE_TITLE)
        data["device_name"] = (
            title_el.get_text(strip=True) if title_el else "iGuardStove"
        )

        status_el = soup.find(class_=SEL_STOVE_STATUS_TEXT)
        raw_status: str | None = status_el.get_text(strip=True) if status_el else None
        data["status_raw"] = raw_status
        data["status"] = normalize_status(raw_status)

        # Determine lock state from button first (authoritative action indicator)
        form = soup.find("form", {"id": "unlock"}) or soup.find("form", {"id": "lock"})
        if not form:
            for f in soup.find_all("form"):
                if f.find("button", {"name": ["lock", "unlock"]}):
                    form = f
                    break

        button = form.find("button") if form else None
        if button and button.get("name") in ("lock", "unlock"):
            data["is_locked"] = button.get("name") == "unlock"
        else:
            icon_block = soup.find(class_=SEL_STATUS_ICON)
            if icon_block:
                lock_img = icon_block.find("img", class_=SEL_LOCK_IMG)
                data["is_locked"] = lock_img is not None
            else:
                status_text = (data.get("status") or "").lower()
                data["is_locked"] = "locked" in status_text

        checkin_el = soup.find(class_=SEL_STOVE_DATE)
        if checkin_el:
            raw = checkin_el.get_text(strip=True)
            raw = CHECKIN_PREFIX_RE.sub("", raw)
            data["last_check_in"] = raw
        else:
            data["last_check_in"] = None

        data["fires_prevented"] = None
        data["temperature"] = None
        data["temperature_unit"] = "°F"

        for block in soup.find_all(class_=SEL_INFO_BLOCK):
            title_el = block.find(class_=SEL_INFO_TITLE)
            value_el = block.find(class_=SEL_INFO_VALUE)
            if not title_el or not value_el:
                continue
            title_text = title_el.get_text(strip=True).lower()
            value_text = value_el.get_text(strip=True)

            if "fires" in title_text or "shut off" in title_text:
                try:
                    data["fires_prevented"] = int(value_text)
                except ValueError:
                    _LOGGER.warning("Could not parse fires_prevented: %r", value_text)

            elif "temperature" in title_text:
                m = TEMP_RE.match(value_text)
                if m:
                    try:
                        data["temperature"] = float(m.group(1))
                    except ValueError:
                        _LOGGER.warning("Could not parse temperature: %r", value_text)
                    unit_str = m.group(2) or "°F"
                    data["temperature_unit"] = unit_str

        _LOGGER.debug("Parsed device data for %s: %s", device_id, data)
        return data

    async def async_set_lock_state(
        self, device_id: str, target_locked: bool, retry_login: bool = True
    ) -> None:
        """Safely and idempotently set device lock state."""
        lock = self._get_device_lock(device_id)
        async with lock:
            url = f"{BASE_URL}/devices/{device_id}/"
            try:
                _, html, _ = await self._request("GET", url)
            except InvalidAuth:
                if retry_login:
                    _LOGGER.info("Session expired before lock state change, re-logging in")
                    await self.async_login()
                    return await self.async_set_lock_state(
                        device_id, target_locked, retry_login=False
                    )
                raise

            soup = BeautifulSoup(html, "html.parser")
            form = soup.find("form", {"id": "unlock"}) or soup.find("form", {"id": "lock"})
            if not form:
                for f in soup.find_all("form"):
                    if f.find("button", {"name": ["lock", "unlock"]}):
                        form = f
                        break

            if not form:
                raise CannotConnect(
                    f"Lock toggle form not found on device page for {device_id}"
                )

            csrf_input = form.find("input", {"name": "csrfmiddlewaretoken"})
            if not csrf_input or not csrf_input.get("value"):
                raise CannotConnect(
                    "csrfmiddlewaretoken missing or invalid in lock form"
                )

            csrf_token = csrf_input.get("value")

            button = form.find("button")
            if not button or not button.get("name"):
                raise CannotConnect("Lock button missing or unnamed in form")

            button_name = button.get("name")
            if button_name not in ("lock", "unlock"):
                raise CannotConnect(f"Unexpected button name {button_name!r} in lock form")

            is_currently_locked = (button_name == "unlock")

            if is_currently_locked == target_locked:
                _LOGGER.debug(
                    "Device %s is already in target lock state (%s), skipping POST",
                    device_id,
                    target_locked,
                )
                return

            expected_button_name = "lock" if target_locked else "unlock"
            if button_name != expected_button_name:
                raise CannotConnect(
                    f"Form action {button_name!r} does not match required action for target_locked={target_locked}"
                )

            button_value = button.get("value", device_id)
            payload = {
                "csrfmiddlewaretoken": csrf_token,
                button_name: button_value,
            }

            action = form.get("action")
            post_url = urllib.parse.urljoin(url, action) if action else url
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
                    return await self.async_set_lock_state(
                        device_id, target_locked, retry_login=False
                    )
                raise

            parsed = self._parse_device_page(device_id, post_html)
            final_locked = parsed.get("is_locked")

            if final_locked != target_locked:
                _, refetch_html, _ = await self._request("GET", url)
                refetch_parsed = self._parse_device_page(device_id, refetch_html)
                final_locked = refetch_parsed.get("is_locked")

            if final_locked != target_locked:
                raise CannotConnect(
                    f"Failed to confirm lock state transition for device {device_id}: expected {target_locked}, got {final_locked}"
                )

            _LOGGER.info(
                "Lock state for device %s successfully changed to %s",
                device_id,
                target_locked,
            )
