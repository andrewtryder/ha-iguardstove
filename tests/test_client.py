"""Tests for the iGuardStove API client."""

from __future__ import annotations

import aiohttp
import pytest

from custom_components.iguardstove.client import (
    CannotConnect,
    IGuardStoveClient,
    InvalidAuth,
    normalize_status,
)

pytestmark = pytest.mark.enable_socket

PORTAL_HOST = "manage.iguardfire.com"

# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

LOGIN_PAGE_HTML = """
<!doctype html>
<html>
<body>
  <form method="post">
    <input type="hidden" name="csrfmiddlewaretoken" value="test_csrf_token" />
    <input type="text" name="login" />
    <input type="password" name="password" />
    <button type="submit">Login</button>
  </form>
</body>
</html>
"""

LOGIN_ERROR_HTML = """
<!doctype html>
<html>
<body>
  <form method="post">
    <ul class="errorlist"><li>Invalid credentials.</li></ul>
    <input type="hidden" name="csrfmiddlewaretoken" value="test_csrf_token" />
  </form>
</body>
</html>
"""

DASHBOARD_HTML = """
<!doctype html>
<html>
<body>
  <div class="stove_line">
    <span class="stove_title">Guest House Stove</span>
    <a href="/devices/AABBCCDD1234/">View</a>
  </div>
</body>
</html>
"""

DEVICE_PAGE_UNLOCKED_HTML = """
<!doctype html>
<html>
<body>
  <span class="stove_title">Guest House Stove</span>
  <span class="stove_status_text">iGuardStove is off</span>
  <span class="stove_date">iGuardStove Last Checked In: 20 minutes ago</span>
  <div class="info_block">
    <span class="info_title">Potential Fires Prevented</span>
    <span class="info_value">3</span>
  </div>
  <div class="info_block">
    <span class="info_title">Temperature</span>
    <span class="info_value">72°F</span>
  </div>
  <form id="unlock">
    <input type="hidden" name="csrfmiddlewaretoken" value="form_csrf_token" />
    <button type="submit" name="lock" value="AABBCCDD1234">Lock</button>
  </form>
</body>
</html>
"""

DEVICE_PAGE_LOCKED_HTML = """
<!doctype html>
<html>
<body>
  <span class="stove_title">Guest House Stove</span>
  <span class="stove_status_text">iGuardStove is LOCKED OUT for the night</span>
  <span class="stove_date">iGuardStove Last Checked In: 5 minutes ago</span>
  <div class="info_block">
    <span class="info_title">Potential Fires Prevented</span>
    <span class="info_value">3</span>
  </div>
  <div class="info_block">
    <span class="info_title">Temperature</span>
    <span class="info_value">70°F</span>
  </div>
  <form id="unlock">
    <input type="hidden" name="csrfmiddlewaretoken" value="form_csrf_token" />
    <button type="submit" name="unlock" value="AABBCCDD1234">Unlock</button>
  </form>
</body>
</html>
"""


DEVICE_PAGE_INVALID_TEMP_HTML = """
<!doctype html>
<html>
<body>
  <span class="stove_title">Invalid Temp Stove</span>
  <span class="stove_status_text">iGuardStove is off</span>
  <span class="stove_date">iGuardStove Last Checked In: 1 hour ago</span>
  <div class="info_block">
    <span class="info_title">Temperature</span>
    <span class="info_value">1.2.3°F</span>
  </div>
  <form id="unlock">
    <input type="hidden" name="csrfmiddlewaretoken" value="form_csrf_token" />
    <button type="submit" name="lock" value="CCDD1234">Lock</button>
  </form>
</body>
</html>
"""

DEVICE_PAGE_CELSIUS_HTML = """
<!doctype html>
<html>
<body>
  <span class="stove_title">Celsius Stove</span>
  <span class="stove_status_text">iGuardStove is off</span>
  <span class="stove_date">iGuardStove Last Checked In: 1 hour ago</span>
  <div class="info_block">
    <span class="info_title">Temperature</span>
    <span class="info_value">22°C</span>
  </div>
  <form id="unlock">
    <input type="hidden" name="csrfmiddlewaretoken" value="form_csrf_token" />
    <button type="submit" name="lock" value="CCDD1234">Lock</button>
  </form>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# normalize_status tests (pure function — no HTTP needed)
# ---------------------------------------------------------------------------


def test_normalize_status_known_patterns() -> None:
    """Test all known STATUS_MAP patterns are matched correctly."""
    assert normalize_status("iGuardStove is off") == "Stove Off"
    assert normalize_status("iGuardStove is on") == "Stove On"
    assert (
        normalize_status("iGuardStove has been shut off automatically")
        == "Stove Shut Off"
    )
    assert normalize_status("iGuardStove was automatically shut off") == "Auto Shut Off"
    assert normalize_status("iGuardStove is LOCKED OUT for the night") == "Night Lock"
    assert normalize_status("iGuardStove is locked out") == "Locked Out"
    assert normalize_status("iGuardStove is manually locked") == "Manually Locked"
    assert normalize_status("Caregiver locked") == "Caregiver Locked"
    assert normalize_status("No motion detected") == "No Motion Detected"


def test_normalize_status_none_and_empty() -> None:
    """Test that None and empty strings are returned unchanged."""
    assert normalize_status(None) is None
    assert normalize_status("") == ""


def test_normalize_status_unknown_returns_raw() -> None:
    """Test that an unknown status falls back to the raw text."""
    result = normalize_status("Some brand new portal status")
    assert result == "Some brand new portal status"


# ---------------------------------------------------------------------------
# async_login tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_login_success(aresponses) -> None:
    """Test successful login: GET csrf then POST and redirect to dashboard."""
    aresponses.add(
        PORTAL_HOST,
        "/account/login/",
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    # POST redirects to dashboard
    aresponses.add(
        PORTAL_HOST,
        "/account/login/",
        "POST",
        aresponses.Response(
            status=302,
            headers={"Location": "https://manage.iguardfire.com/"},
        ),
    )
    # GET dashboard
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(text="<html><body>Dashboard</body></html>", status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        result = await client.async_login()
        assert result is True


@pytest.mark.asyncio
async def test_async_login_invalid_credentials(aresponses) -> None:
    """Test login raises InvalidAuth when the portal returns an errorlist."""
    aresponses.add(
        PORTAL_HOST,
        "/account/login/",
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    aresponses.add(
        PORTAL_HOST,
        "/account/login/",
        "POST",
        aresponses.Response(text=LOGIN_ERROR_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "wrong")
        with pytest.raises(InvalidAuth):
            await client.async_login()


@pytest.mark.asyncio
async def test_async_login_server_error(aresponses) -> None:
    """Test login raises CannotConnect when the login page returns a 5xx."""
    aresponses.add(
        PORTAL_HOST,
        "/account/login/",
        "GET",
        aresponses.Response(status=500),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(CannotConnect):
            await client.async_login()


@pytest.mark.asyncio
async def test_async_login_no_csrf_token(aresponses) -> None:
    """Test login raises CannotConnect when the CSRF token is missing."""
    aresponses.add(
        PORTAL_HOST,
        "/account/login/",
        "GET",
        aresponses.Response(text="<html><body>No form here</body></html>", status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(CannotConnect, match="csrfmiddlewaretoken not found"):
            await client.async_login()


# ---------------------------------------------------------------------------
# async_get_devices tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_get_devices_success(aresponses) -> None:
    """Test device discovery parses links correctly."""
    aresponses.add(
        PORTAL_HOST, "/", "GET", aresponses.Response(text=DASHBOARD_HTML, status=200)
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        devices = await client.async_get_devices()
        assert len(devices) == 1
        assert devices[0]["device_id"] == "AABBCCDD1234"
        assert devices[0]["device_name"] == "Guest House Stove"


@pytest.mark.asyncio
async def test_async_get_devices_empty_dashboard(
    aresponses,
) -> None:
    """Test that empty dashboard returns empty list."""
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(text="<html><body>No stoves</body></html>", status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        devices = await client.async_get_devices()
        assert devices == []


# ---------------------------------------------------------------------------
# _parse_device_page tests (pure — no HTTP)
# ---------------------------------------------------------------------------


def test_parse_device_page_unlocked() -> None:
    """Test parsing a device page where the stove is unlocked."""
    # _parse_device_page is a pure sync method; we pass a dummy object for session.
    client = IGuardStoveClient.__new__(IGuardStoveClient)
    data = client._parse_device_page("AABBCCDD1234", DEVICE_PAGE_UNLOCKED_HTML)
    assert data["device_id"] == "AABBCCDD1234"
    assert data["device_name"] == "Guest House Stove"
    assert data["is_locked"] is False
    assert data["status"] == "Stove Off"
    assert data["last_check_in"] == "20 minutes ago"
    assert data["fires_prevented"] == 3
    assert data["temperature"] == 72.0
    assert data["temperature_unit"] == "°F"


def test_parse_device_page_locked() -> None:
    """Test parsing a device page where the stove is locked."""
    client = IGuardStoveClient.__new__(IGuardStoveClient)
    data = client._parse_device_page("AABBCCDD1234", DEVICE_PAGE_LOCKED_HTML)
    assert data["is_locked"] is True
    assert data["status"] == "Night Lock"
    assert data["last_check_in"] == "5 minutes ago"


def test_parse_device_page_celsius() -> None:
    """Test that Celsius temperature units are parsed correctly."""
    client = IGuardStoveClient.__new__(IGuardStoveClient)
    data = client._parse_device_page("CCDD1234", DEVICE_PAGE_CELSIUS_HTML)
    assert data["temperature"] == 22.0
    assert data["temperature_unit"] == "°C"


def test_parse_device_page_invalid_temperature(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test invalid temperature logs a warning."""
    client = IGuardStoveClient.__new__(IGuardStoveClient)
    data = client._parse_device_page("CCDD1234", DEVICE_PAGE_INVALID_TEMP_HTML)

    assert data["temperature"] is None
    assert data["temperature_unit"] == "°F"
    assert "Could not parse temperature" in caplog.text


def test_parse_device_page_missing_elements() -> None:
    """Test parsing a minimal page with missing optional elements."""
    minimal_html = """
    <html><body>
      <form id="unlock">
        <input type="hidden" name="csrfmiddlewaretoken" value="tok" />
        <button name="lock" value="DEV001">Lock</button>
      </form>
    </body></html>
    """
    client = IGuardStoveClient.__new__(IGuardStoveClient)
    data = client._parse_device_page("DEV001", minimal_html)
    assert data["device_name"] == "iGuardStove"
    assert data["status"] is None
    assert data["last_check_in"] is None
    assert data["fires_prevented"] is None
    assert data["temperature"] is None
    assert data["is_locked"] is False


# ---------------------------------------------------------------------------
# async_get_device_data tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_get_device_data_success(aresponses) -> None:
    """Test fetching and parsing device data end-to-end."""
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_UNLOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        data = await client.async_get_device_data("AABBCCDD1234")
        assert data["device_id"] == "AABBCCDD1234"
        assert data["is_locked"] is False
        assert data["temperature"] == 72.0


@pytest.mark.asyncio
async def test_async_get_device_data_server_error(
    aresponses,
) -> None:
    """Test that a 500 response raises CannotConnect."""
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(status=500),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(CannotConnect):
            await client.async_get_device_data("AABBCCDD1234")


# ---------------------------------------------------------------------------
# async_toggle_lock tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_toggle_lock_success(aresponses) -> None:
    """Test that the lock toggle GETs the page for CSRF then POSTs successfully."""
    # First GET to retrieve CSRF token
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_UNLOCKED_HTML, status=200),
    )
    # POST to toggle lock
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "POST",
        aresponses.Response(text=DEVICE_PAGE_LOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        result = await client.async_toggle_lock("AABBCCDD1234")
        assert result is True


@pytest.mark.asyncio
async def test_async_toggle_lock_post_failure(aresponses) -> None:
    """Test that a non-200 POST raises CannotConnect."""
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_UNLOCKED_HTML, status=200),
    )
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "POST",
        aresponses.Response(status=403),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(CannotConnect):
            await client.async_toggle_lock("AABBCCDD1234")


@pytest.mark.asyncio
async def test_async_toggle_lock_no_form(aresponses) -> None:
    """Test that CannotConnect is raised when the lock form is absent."""
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text="<html><body>No form here</body></html>", status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(CannotConnect, match="Lock toggle form not found"):
            await client.async_toggle_lock("AABBCCDD1234")
