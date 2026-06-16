"""iGuardStove web client - handles login and scraping of stove data."""

import logging
import re
import urllib.parse
from typing import Any

import aiohttp
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

_LOGGER = logging.getLogger(__name__)


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
    WARNING is logged — this is intentional so new statuses are easy to spot
    in the HA log and can be added to STATUS_MAP in const.py.
    """
    if not raw:
        return raw
    lower = raw.lower()
    for pattern, label in STATUS_MAP.items():
        if pattern in lower:
            return label
    # Unknown — log it so the user can report / extend STATUS_MAP
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

    async def async_login(self) -> bool:
        """Log in to the iGuardFire management portal.

        Django's CSRF protection requires:
        1. GET the login page to receive the session cookie and csrfmiddlewaretoken.
        2. POST credentials with the token included, and the Referer header set.
        """
        _LOGGER.debug("Fetching iGuardFire login page for CSRF token")
        try:
            async with self._session.get(LOGIN_URL, headers=self._headers) as resp:
                if resp.status != 200:
                    raise CannotConnect(f"Login page returned HTTP {resp.status}")
                html = await resp.text()
        except aiohttp.ClientError as ex:
            raise CannotConnect("Network error fetching login page") from ex

        soup = BeautifulSoup(html, "html.parser")
        csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
        if not csrf_input:
            raise CannotConnect("csrfmiddlewaretoken not found on login page")

        csrf_token = csrf_input.get("value")
        _LOGGER.debug("CSRF token obtained")

        payload = {
            "csrfmiddlewaretoken": csrf_token,
            "login": self.username,
            "password": self.password,
        }
        post_headers = {**self._headers, "Referer": LOGIN_URL}

        _LOGGER.debug("Submitting login credentials")
        try:
            async with self._session.post(
                LOGIN_URL,
                data=payload,
                headers=post_headers,
                allow_redirects=True,
            ) as resp_login:
                if resp_login.status != 200:
                    raise CannotConnect(f"Login POST returned HTTP {resp_login.status}")
                login_html = await resp_login.text()
                final_url = str(resp_login.url)

            # If we're still on the login page, credentials were wrong
            if "login" in final_url and "next" in final_url:
                raise InvalidAuth("Credentials were rejected")

            # Check for known error messages in the page body
            err_soup = BeautifulSoup(login_html, "html.parser")
            err_el = err_soup.find(class_="errorlist") or err_soup.find(
                class_="alert-danger"
            )
            if err_el:
                raise InvalidAuth(err_el.get_text(strip=True))

            _LOGGER.info("iGuardStove login successful (redirected to %s)", final_url)
            return True

        except aiohttp.ClientError as ex:
            raise CannotConnect("Network error during login") from ex

    async def async_get_devices(self, retry_login: bool = True) -> list[dict[str, Any]]:
        """Fetch all registered iGuardStove devices from the dashboard.

        Returns a list of dicts with keys: device_id, device_name.
        """
        _LOGGER.debug("Fetching dashboard to discover devices")
        try:
            async with self._session.get(f"{BASE_URL}/", headers=self._headers) as resp:
                if resp.status == 302 or "login" in str(resp.url):
                    if retry_login:
                        _LOGGER.info("Session expired, re-logging in")
                        await self.async_login()
                        return await self.async_get_devices(retry_login=False)
                    raise InvalidAuth("Session expired after re-login attempt")
                html = await resp.text()
        except aiohttp.ClientError as ex:
            raise CannotConnect("Network error fetching dashboard") from ex

        soup = BeautifulSoup(html, "html.parser")
        devices = []

        # Each device card links to /devices/<device_id>/
        for link in soup.find_all("a", href=True):
            href: str = link["href"]
            m = re.match(r"^/devices/([A-F0-9]+)/$", href)
            if m:
                device_id = m.group(1)
                # Look for a stove title in the nearest ancestor stove_line block
                parent = link.find_parent(class_="stove_line")
                name = "iGuardStove"
                if parent:
                    title_el = parent.find(class_=SEL_STOVE_TITLE)
                    if title_el:
                        name = title_el.get_text(strip=True)
                # Avoid duplicates (the same device_id can appear multiple times)
                if not any(d["device_id"] == device_id for d in devices):
                    devices.append({"device_id": device_id, "device_name": name})

        _LOGGER.debug("Discovered %d device(s): %s", len(devices), devices)
        return devices

    async def async_get_device_data(
        self, device_id: str, retry_login: bool = True
    ) -> dict[str, Any]:
        """Fetch and parse all sensor data for a single device.

        Returns a dict with the following keys (all optional, None if not found):
          - device_id (str)
          - device_name (str)
          - status (str)           - human-readable status text
          - is_locked (bool)       - True when night/manual lock is active
          - last_check_in (str)    - relative time string, e.g. "20 minutes ago"
          - temperature (float|None) - ambient temperature in °F
            (or °C per device setting)
          - temperature_unit (str) - "°F" or "°C"
          - fires_prevented (int|None) - cumulative automatic shut-off count
        """
        url = f"{BASE_URL}/devices/{device_id}/"
        _LOGGER.debug("Fetching device page: %s", url)

        try:
            async with self._session.get(url, headers=self._headers) as resp:
                if resp.status in (302, 301) or "login" in str(resp.url):
                    if retry_login:
                        _LOGGER.info("Session expired, re-logging in")
                        await self.async_login()
                        return await self.async_get_device_data(
                            device_id, retry_login=False
                        )
                    raise InvalidAuth("Session expired after re-login attempt")

                if resp.status != 200:
                    raise CannotConnect(f"Device page returned HTTP {resp.status}")
                html = await resp.text()
        except aiohttp.ClientError as ex:
            raise CannotConnect(f"Network error fetching device {device_id}") from ex

        return self._parse_device_page(device_id, html)

    def _parse_device_page(self, device_id: str, html: str) -> dict[str, Any]:  # noqa: C901
        """Parse the device detail page HTML into a data dict."""
        soup = BeautifulSoup(html, "html.parser")
        data: dict[str, Any] = {"device_id": device_id}

        # Device name
        title_el = soup.find(class_=SEL_STOVE_TITLE)
        data["device_name"] = (
            title_el.get_text(strip=True) if title_el else "iGuardStove"
        )

        # Status text (e.g. "iGuardStove is LOCKED OUT for the night")
        # normalize_status() maps known patterns → clean labels and logs a
        # WARNING for any unrecognised string so it can be added to STATUS_MAP.
        status_el = soup.find(class_=SEL_STOVE_STATUS_TEXT)
        raw_status: str | None = status_el.get_text(strip=True) if status_el else None
        data["status_raw"] = raw_status  # always the exact portal text
        data["status"] = normalize_status(raw_status)  # clean label for the sensor

        # Determine lock state:
        # Check the form button name first as it is the most authoritative
        # indicator of lock
        # control state.
        # If the button name is 'unlock', it means the next action is to unlock, so the
        # device is currently locked.
        form = soup.find("form", {"id": "unlock"})
        button = form.find("button") if form else None
        if button and button.get("name"):
            data["is_locked"] = button.get("name") == "unlock"
        else:
            # Fallback: Determine lock state from status icon:
            # an <img class="lock"> inside the icon block
            icon_block = soup.find(class_=SEL_STATUS_ICON)
            if icon_block:
                lock_img = icon_block.find("img", class_=SEL_LOCK_IMG)
                data["is_locked"] = lock_img is not None
            else:
                # Fallback: look for "LOCKED OUT" in status text
                status_text = (data.get("status") or "").lower()
                data["is_locked"] = "locked" in status_text

        # Last check-in: strip the "iGuardStove Last Checked In:" prefix
        checkin_el = soup.find(class_=SEL_STOVE_DATE)
        if checkin_el:
            raw = checkin_el.get_text(strip=True)
            # Strip the label prefix
            raw = re.sub(
                r"^iGuardStove\s+Last\s+Checked\s+In:\s*",
                "",
                raw,
                flags=re.IGNORECASE,
            )
            data["last_check_in"] = raw
        else:
            data["last_check_in"] = None

        # Info blocks: "Potential Fires Prevented" and "Temperature"
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
                # Value looks like "81°F" or "27°C"
                m = re.match(r"([\d.]+)\s*(°[FC]?)?", value_text)
                if m:
                    try:
                        data["temperature"] = float(m.group(1))
                    except ValueError:
                        _LOGGER.warning("Could not parse temperature: %r", value_text)
                    unit_str = m.group(2) or "°F"
                    data["temperature_unit"] = unit_str

        _LOGGER.debug("Parsed device data for %s: %s", device_id, data)
        return data

    async def async_toggle_lock(self, device_id: str, retry_login: bool = True) -> bool:  # noqa: C901
        """Toggle the stove lock state via the device page form.

        The form (id='unlock') POSTs to the current device URL with only the
        csrfmiddlewaretoken. The server flips the lock state on each POST.
        Returns True on success.
        """
        url = f"{BASE_URL}/devices/{device_id}/"
        _LOGGER.debug("Fetching device page for CSRF token (lock toggle)")

        try:
            async with self._session.get(url, headers=self._headers) as resp:
                if "login" in str(resp.url):
                    if retry_login:
                        await self.async_login()
                        return await self.async_toggle_lock(
                            device_id, retry_login=False
                        )
                    raise InvalidAuth("Session expired")
                html = await resp.text()
        except aiohttp.ClientError as ex:
            raise CannotConnect("Network error fetching device page for lock") from ex

        soup = BeautifulSoup(html, "html.parser")
        form = soup.find("form", {"id": "unlock"}) or soup.find("form", {"id": "lock"})
        if not form:
            # Fallback: check any form that has a button with lock/unlock names
            for f in soup.find_all("form"):
                if f.find("button", {"name": ["lock", "unlock"]}):
                    form = f
                    break
        if not form:
            raise CannotConnect("Lock toggle form not found on device page")

        csrf_input = form.find("input", {"name": "csrfmiddlewaretoken"})
        if not csrf_input:
            raise CannotConnect("csrfmiddlewaretoken not found in lock form")

        csrf_token = csrf_input.get("value")

        # Extract button name and value (e.g. name="lock", value="device_id"
        # or name="unlock")
        button = form.find("button")
        if not button:
            raise CannotConnect("Lock button not found inside form")

        button_name = button.get("name", "lock")
        button_value = button.get("value", device_id)

        payload = {
            "csrfmiddlewaretoken": csrf_token,
            button_name: button_value,
        }

        # Resolve target POST URL from the form's action attribute
        action = form.get("action")
        if action:
            post_url = urllib.parse.urljoin(url, action)
        else:
            post_url = url

        post_headers = {**self._headers, "Referer": url}

        _LOGGER.debug("POSTing lock toggle for device %s to %s", device_id, post_url)
        try:
            async with self._session.post(
                post_url, data=payload, headers=post_headers, allow_redirects=True
            ) as resp_lock:
                if resp_lock.status != 200:
                    raise CannotConnect(
                        f"Lock toggle POST returned HTTP {resp_lock.status}"
                    )
        except aiohttp.ClientError as ex:
            raise CannotConnect("Network error during lock toggle") from ex

        _LOGGER.info("Lock toggled for device %s", device_id)
        return True
