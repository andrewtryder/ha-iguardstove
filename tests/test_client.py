"""Tests for the iGuardStove API client."""

import asyncio
import re
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from custom_components.iguardstove.client import (
    CannotConnect,
    IGuardStoveClient,
    InvalidAuth,
    normalize_status,
)
from custom_components.iguardstove.const import USER_AGENT

pytestmark = pytest.mark.enable_socket

PORTAL_HOST = "manage.iguardfire.com"
LOGIN_PATH_RE = re.compile(r"/account/login/.*")

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

LOGIN_SUCCESS_HTML = """
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

LOGIN_ALERT_DANGER_HTML = """
<!doctype html>
<html>
<body>
  <div class="alert-danger">Bad credentials specified</div>
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

DASHBOARD_MISSING_TITLE_HTML = """
<!doctype html>
<html>
<body>
  <div class="stove_line">
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


def test_user_agent_has_no_release_version() -> None:
    """User-Agent must stay versionless to avoid Release Please drift."""
    assert USER_AGENT == "HomeAssistant-iGuardStove"
    assert "/" not in USER_AGENT


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


def test_normalize_status_unknown_deduplication(caplog) -> None:
    """Test that unknown status warnings are deduplicated."""
    caplog.clear()
    res1 = normalize_status("Unique Status 999")
    res2 = normalize_status("Unique Status 999")
    assert res1 == "Unique Status 999"
    assert res2 == "Unique Status 999"
    warnings = [
        rec for rec in caplog.records if "Unknown iGuardStove status" in rec.message
    ]
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# async_login tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_login_success(aresponses) -> None:
    """Test successful login: GET csrf then POST and redirect to dashboard."""
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "POST",
        aresponses.Response(
            status=302,
            headers={"Location": "https://manage.iguardfire.com/"},
        ),
    )
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(text=LOGIN_SUCCESS_HTML, status=200),
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
        LOGIN_PATH_RE,
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "POST",
        aresponses.Response(text=LOGIN_ERROR_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "wrong")
        with pytest.raises(InvalidAuth):
            await client.async_login()


@pytest.mark.asyncio
async def test_async_login_alert_danger(aresponses) -> None:
    """Test login raises InvalidAuth when the portal returns an alert-danger div."""
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "POST",
        aresponses.Response(text=LOGIN_ALERT_DANGER_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "wrong")
        with pytest.raises(InvalidAuth, match="Bad credentials specified"):
            await client.async_login()


@pytest.mark.asyncio
async def test_async_login_server_error(aresponses) -> None:
    """Test login raises CannotConnect when the login page returns a 5xx."""
    for _ in range(3):
        aresponses.add(
            PORTAL_HOST,
            LOGIN_PATH_RE,
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
        LOGIN_PATH_RE,
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
async def test_async_get_devices_empty_dashboard(aresponses) -> None:
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


@pytest.mark.asyncio
async def test_async_get_devices_session_expired(aresponses) -> None:
    """Test async_get_devices re-logins when session has expired."""
    # First GET redirects to login
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(
            status=302,
            headers={"Location": "https://manage.iguardfire.com/account/login/?next=/"},
        ),
    )
    # Redirect follow GET /account/login/?next=/
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    # Login GET CSRF
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    # Login POST
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "POST",
        aresponses.Response(
            status=302,
            headers={"Location": "https://manage.iguardfire.com/"},
        ),
    )
    # Login GET redirect target /
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(text=LOGIN_SUCCESS_HTML, status=200),
    )
    # Retry async_get_devices GET /
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(text=DASHBOARD_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        devices = await client.async_get_devices()
        assert len(devices) == 1


# ---------------------------------------------------------------------------
# _parse_device_page tests (pure — no HTTP)
# ---------------------------------------------------------------------------


def test_parse_device_page_unlocked() -> None:
    """Test parsing a device page where the stove is unlocked."""
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


def test_parse_device_page_invalid_numbers() -> None:
    """Test parsing handles invalid integer/float strings gracefully."""
    invalid_html = """
    <html><body>
      <span class="stove_title">Guest House Stove</span>
      <div class="info_block">
        <span class="info_title">Potential Fires Prevented</span>
        <span class="info_value">invalid_int</span>
      </div>
      <div class="info_block">
        <span class="info_title">Temperature</span>
        <span class="info_value">invalid_float°F</span>
      </div>
    </body></html>
    """
    client = IGuardStoveClient.__new__(IGuardStoveClient)
    data = client._parse_device_page("DEV001", invalid_html)
    assert data["fires_prevented"] is None
    assert data["temperature"] is None


def test_parse_device_page_icon_and_status_fallbacks() -> None:
    """Test lock state fallback parsing via status icon and status text."""
    icon_html = """
    <html><body>
      <span class="stove_title">Guest House Stove</span>
      <div class="stove_status_icon"><img class="lock" /></div>
    </body></html>
    """
    client = IGuardStoveClient.__new__(IGuardStoveClient)
    data_icon = client._parse_device_page("DEV001", icon_html)
    assert data_icon["is_locked"] is True

    status_html = """
    <html><body>
      <span class="stove_title">Guest House Stove</span>
      <span class="stove_status_text">Stove is locked out</span>
    </body></html>
    """
    data_status = client._parse_device_page("DEV001", status_html)
    assert data_status["is_locked"] is True


# ---------------------------------------------------------------------------
# async_set_lock_state tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_set_lock_state_success(aresponses) -> None:
    """Test that async_set_lock_state GETs the device page, submits POST, and verifies transition."""
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
        aresponses.Response(text=DEVICE_PAGE_LOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        await client.async_set_lock_state("AABBCCDD1234", target_locked=True)


@pytest.mark.asyncio
async def test_async_set_lock_state_idempotent_short_circuit(aresponses) -> None:
    """Test that async_set_lock_state skips POST if stove is already in target state."""
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_UNLOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        await client.async_set_lock_state("AABBCCDD1234", target_locked=False)


@pytest.mark.asyncio
async def test_async_set_lock_state_duplicate_and_concurrent_calls(aresponses) -> None:
    """Test that duplicate/concurrent calls are safely serialized and idempotent."""
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
        aresponses.Response(text=DEVICE_PAGE_LOCKED_HTML, status=200),
    )
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_LOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        await asyncio.gather(
            client.async_set_lock_state("AABBCCDD1234", target_locked=True),
            client.async_set_lock_state("AABBCCDD1234", target_locked=True),
        )


@pytest.mark.asyncio
async def test_async_set_lock_state_200_no_state_change(aresponses) -> None:
    """Test that a 200 POST response that fails to change state raises CannotConnect."""
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
        aresponses.Response(text=DEVICE_PAGE_UNLOCKED_HTML, status=200),
    )
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_UNLOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(
            CannotConnect, match="Failed to confirm lock state transition"
        ):
            await client.async_set_lock_state("AABBCCDD1234", target_locked=True)


@pytest.mark.asyncio
async def test_async_set_lock_state_no_form(aresponses) -> None:
    """Test async_set_lock_state raises CannotConnect when form is absent."""
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text="<html><body>No lock form</body></html>", status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(CannotConnect, match="Lock toggle form not found"):
            await client.async_set_lock_state("AABBCCDD1234", target_locked=True)


# ---------------------------------------------------------------------------
# Request Hardening & Origin Validation tests
# ---------------------------------------------------------------------------


def test_validate_origin_insecure_scheme() -> None:
    """Test origin validator rejects HTTP scheme."""
    client = IGuardStoveClient.__new__(IGuardStoveClient)
    with pytest.raises(CannotConnect, match="Insecure URL scheme"):
        client._validate_origin("http://manage.iguardfire.com/")


def test_validate_origin_host_mismatch() -> None:
    """Test origin validator rejects unexpected hosts."""
    client = IGuardStoveClient.__new__(IGuardStoveClient)
    with pytest.raises(CannotConnect, match="URL origin mismatch"):
        client._validate_origin("https://evil.com/")


@pytest.mark.asyncio
async def test_request_unexpected_content_type(aresponses) -> None:
    """Test _request rejects non-HTML Content-Type."""
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(
            text='{"error": "bad"}',
            status=200,
            headers={"Content-Type": "application/json"},
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(CannotConnect, match="Unexpected content type"):
            await client._request("GET", f"https://{PORTAL_HOST}/devices/AABBCCDD1234/")


@pytest.mark.asyncio
async def test_async_get_device_data_relogin_retry(aresponses) -> None:
    """Test async_get_device_data retries login when session expires."""
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(status=302, headers={"Location": "/account/login/?next=/"}),
    )
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_UNLOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with patch.object(client, "async_login", new_callable=AsyncMock) as mock_login:
            data = await client.async_get_device_data("AABBCCDD1234")
            assert data["device_id"] == "AABBCCDD1234"
            mock_login.assert_called_once()


@pytest.mark.asyncio
async def test_async_set_lock_state_relogin_retry(aresponses) -> None:
    """Test async_set_lock_state retries login when session expires on GET."""
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(status=302, headers={"Location": "/account/login/?next=/"}),
    )
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
        aresponses.Response(text=DEVICE_PAGE_LOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with patch.object(client, "async_login", new_callable=AsyncMock) as mock_login:
            await client.async_set_lock_state("AABBCCDD1234", target_locked=True)
            mock_login.assert_called_once()


@pytest.mark.asyncio
async def test_async_set_lock_state_unlock_post_returns_non_device_page(
    aresponses,
) -> None:
    """Test that unlock POST returning non-device page triggers GET refetch and fails if refetch stays locked."""
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_LOCKED_HTML, status=200),
    )
    non_device_html = "<html><body><h1>Welcome to iGuardFire Portal</h1></body></html>"
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "POST",
        aresponses.Response(text=non_device_html, status=200),
    )
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_LOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(
            CannotConnect, match="Failed to confirm lock state transition"
        ):
            await client.async_set_lock_state("AABBCCDD1234", target_locked=False)


@pytest.mark.asyncio
async def test_login_account_serialization_and_generation_tracking(aresponses) -> None:
    """Test that concurrent login calls serialize and skip redundant HTTP logins."""
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "POST",
        aresponses.Response(
            status=302,
            headers={"Location": "https://manage.iguardfire.com/"},
        ),
    )
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(text=LOGIN_SUCCESS_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        assert client.auth_generation == 0

        # First login succeeds and bumps generation to 1
        res1 = await client.async_login()
        assert res1 is True
        assert client.auth_generation == 1

        # Second login called with old generation (0 < 1) skips network request
        res2 = await client.async_login(current_generation=0)
        assert res2 is True
        assert client.auth_generation == 1


@pytest.mark.asyncio
async def test_verification_get_reauthentication_recovery(aresponses) -> None:
    """Test verification GET recovers from session expiration by re-logging in and retrying GET without re-POSTing."""
    # 1. Initial GET before POST
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_LOCKED_HTML, status=200),
    )
    # 2. Lock POST returns 200 OK with non-device HTML (triggering verification GET)
    non_device_html = "<html><body><h1>Welcome to Portal</h1></body></html>"
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "POST",
        aresponses.Response(text=non_device_html, status=200),
    )
    # 3. Verification GET returns 302 redirect to login page (session expired!)
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(
            status=302,
            headers={"Location": "https://manage.iguardfire.com/account/login/?next=/"},
        ),
    )
    # 4. Redirect follow GET /account/login/?next=/
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    # 5. Reauth async_login() GET CSRF
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    # 6. Reauth async_login() POST credentials
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "POST",
        aresponses.Response(
            status=302,
            headers={"Location": "https://manage.iguardfire.com/"},
        ),
    )
    # 7. Login redirect target /
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(text=LOGIN_SUCCESS_HTML, status=200),
    )
    # 8. Retry verification GET returns unlocked device page
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_UNLOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        await client.async_set_lock_state("AABBCCDD1234", target_locked=False)


@pytest.mark.asyncio
async def test_client_http_401_403_raises_invalid_auth(aresponses) -> None:
    """Test that 401 and 403 HTTP status responses raise InvalidAuth."""
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(status=401, text="Unauthorized"),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(InvalidAuth, match="Authentication failure"):
            await client.async_get_devices(retry_login=False)

    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(status=403, text="Forbidden"),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(InvalidAuth, match="Authentication failure"):
            await client.async_get_devices(retry_login=False)


@pytest.mark.asyncio
async def test_client_max_html_size_exceeded_raises_cannot_connect(aresponses) -> None:
    """Test that response exceeding 5MB max HTML size raises CannotConnect."""
    huge_body = b"A" * (5 * 1024 * 1024 + 100)
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(
            status=200, body=huge_body, headers={"Content-Type": "text/html"}
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(CannotConnect, match="exceeds maximum size limit"):
            await client.async_get_devices(retry_login=False)


@pytest.mark.asyncio
async def test_client_http_500_retry_success(aresponses) -> None:
    """Test that HTTP 500 status code retries and succeeds on next attempt."""
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(status=500, text="Server Error"),
    )
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(status=200, text=LOGIN_SUCCESS_HTML),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        devices = await client.async_get_devices(retry_login=False)
        assert len(devices) == 1


@pytest.mark.asyncio
async def test_client_http_500_retry_exhausted(aresponses) -> None:
    """Test that repeated HTTP 500 status code retries and eventually raises CannotConnect."""
    for _ in range(3):
        aresponses.add(
            PORTAL_HOST,
            "/",
            "GET",
            aresponses.Response(status=500, text="Server Error"),
        )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(CannotConnect, match="status 500"):
            await client.async_get_devices(retry_login=False)


@pytest.mark.asyncio
async def test_async_set_lock_state_post_session_expired(aresponses) -> None:
    """Test session expiration during lock POST triggers re-login and retry."""
    # 1. GET device page returns locked page for initial form fetch
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_LOCKED_HTML, status=200),
    )
    # 2. POST lock state returns 401 (InvalidAuth)
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "POST",
        aresponses.Response(status=401, text="Session expired"),
    )
    # 3. async_login GET login page
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    # 4. async_login POST credentials
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "POST",
        aresponses.Response(
            status=302,
            headers={"Location": "https://manage.iguardfire.com/"},
        ),
    )
    # 5. Redirect target /
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(text=LOGIN_SUCCESS_HTML, status=200),
    )
    # 6. Retry GET device page returns locked page for second form fetch
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_LOCKED_HTML, status=200),
    )
    # 7. Retry POST lock state returns unlocked page
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "POST",
        aresponses.Response(text=DEVICE_PAGE_UNLOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        await client.async_set_lock_state("AABBCCDD1234", target_locked=False)


@pytest.mark.asyncio
async def test_client_http_429_502_503_504_status_handling(aresponses) -> None:
    """Test handling of HTTP 429 rate limit and 502/503/504 server gateway errors."""
    for status_code in (429, 502, 503, 504):
        for _ in range(3):
            aresponses.add(
                PORTAL_HOST,
                "/",
                "GET",
                aresponses.Response(status=status_code, text="Service Unavailable"),
            )

        async with aiohttp.ClientSession() as session:
            client = IGuardStoveClient(session, "user@example.com", "secret")
            with pytest.raises(CannotConnect, match="status"):
                await client.async_get_devices(retry_login=False)


@pytest.mark.asyncio
async def test_client_cross_origin_redirect_prevention(aresponses) -> None:
    """Test that cross-origin or insecure redirect locations raise CannotConnect/InvalidAuth."""
    # 1. Login page GET
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    # 2. Login POST returns 302 to external cross-origin URL
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "POST",
        aresponses.Response(
            status=302,
            headers={"Location": "https://evil-phishing.example.com/login"},
        ),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises((CannotConnect, InvalidAuth)):
            await client.async_login()


@pytest.mark.asyncio
async def test_lock_post_not_auto_retried_on_502(aresponses) -> None:
    """Lock POST must not be blindly retried by the transport helper on 502."""
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
        aresponses.Response(status=502, text="Bad Gateway"),
    )
    # Verification GET shows target already applied — no second POST.
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_LOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        await client.async_set_lock_state("AABBCCDD1234", target_locked=True)


@pytest.mark.asyncio
async def test_lock_post_ambiguous_then_controlled_retry(aresponses) -> None:
    """Ambiguous lock POST verifies, refreshes form, then allows one controlled retry."""
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
        aresponses.Response(status=503, text="Unavailable"),
    )
    # Verify still unlocked
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_UNLOCKED_HTML, status=200),
    )
    # Form refresh
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_UNLOCKED_HTML, status=200),
    )
    # Controlled retry POST
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "POST",
        aresponses.Response(text=DEVICE_PAGE_LOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        await client.async_set_lock_state("AABBCCDD1234", target_locked=True)


@pytest.mark.asyncio
async def test_login_post_ambiguous_restarts_csrf_flow(aresponses) -> None:
    """Ambiguous login POST restarts full CSRF GET rather than replaying the POST."""
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "POST",
        aresponses.Response(status=502, text="Bad Gateway"),
    )
    # Restarted CSRF flow
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "GET",
        aresponses.Response(text=LOGIN_PAGE_HTML, status=200),
    )
    aresponses.add(
        PORTAL_HOST,
        LOGIN_PATH_RE,
        "POST",
        aresponses.Response(
            status=302,
            headers={"Location": "https://manage.iguardfire.com/"},
        ),
    )
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(text=LOGIN_SUCCESS_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        assert await client.async_login() is True


@pytest.mark.asyncio
async def test_redirect_methods_and_cross_origin_blocked(aresponses) -> None:
    """Same-origin 303 becomes GET; cross-origin Location is rejected before follow."""
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(
            status=303,
            headers={"Location": "/devices/AABBCCDD1234/"},
        ),
    )
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(text=DEVICE_PAGE_UNLOCKED_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        status, html, url = await client._request(
            "GET", "https://manage.iguardfire.com/"
        )
        assert status == 200
        assert "AABBCCDD1234" in html
        assert "devices" in str(url)

    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(
            status=307,
            headers={"Location": "https://evil.example/steal"},
        ),
    )
    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(CannotConnect, match="origin mismatch"):
            await client._request(
                "GET", "https://manage.iguardfire.com/devices/AABBCCDD1234/"
            )


@pytest.mark.asyncio
async def test_request_too_many_redirects(aresponses) -> None:
    """Cap redirect hops and raise CannotConnect."""
    for _ in range(6):
        aresponses.add(
            PORTAL_HOST,
            "/",
            "GET",
            aresponses.Response(
                status=302,
                headers={"Location": "https://manage.iguardfire.com/"},
            ),
        )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        with pytest.raises(CannotConnect, match="Too many redirects"):
            await client._request("GET", "https://manage.iguardfire.com/")


@pytest.mark.asyncio
async def test_relative_redirect_same_origin(aresponses) -> None:
    """Relative Location headers are resolved and validated against the portal host."""
    aresponses.add(
        PORTAL_HOST,
        "/devices/AABBCCDD1234/",
        "GET",
        aresponses.Response(
            status=301,
            headers={"Location": "/"},
        ),
    )
    aresponses.add(
        PORTAL_HOST,
        "/",
        "GET",
        aresponses.Response(text=DASHBOARD_HTML, status=200),
    )

    async with aiohttp.ClientSession() as session:
        client = IGuardStoveClient(session, "user@example.com", "secret")
        status, html, _ = await client._request(
            "GET", "https://manage.iguardfire.com/devices/AABBCCDD1234/"
        )
        assert status == 200
        assert "AABBCCDD1234" in html
