"""Tests for pure HTML parser functions."""

import pytest

from custom_components.iguardstove.parser import (
    has_password_input,
    normalize_status,
    parse_dashboard_devices,
    parse_device_page,
    parse_lock_form,
    parse_login_csrf,
    parse_login_errors,
)

LOGIN_PAGE_HTML = """
<!doctype html>
<html>
<body>
  <form method="post">
    <input type="hidden" name="csrfmiddlewaretoken" value="test_csrf_token_val" />
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
  <div class="alert-danger">Invalid credentials provided.</div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!doctype html>
<html>
<body>
  <div class="stove_line">
    <span class="stove_title">Main Kitchen Stove</span>
    <a href="/devices/AABBCCDD1234/">View Details</a>
  </div>
  <div class="stove_line">
    <a href="/devices/EEFF00112233/">View Details</a>
  </div>
</body>
</html>
"""

DEVICE_PAGE_UNLOCKED_HTML = """
<!doctype html>
<html>
<body>
  <span class="stove_title">Main Kitchen Stove</span>
  <span class="stove_status_text">iGuardStove is off</span>
  <span class="stove_date">iGuardStove Last Checked In: 10 minutes ago</span>
  <div class="info_block">
    <span class="info_title">Potential Fires Prevented</span>
    <span class="info_value">5</span>
  </div>
  <div class="info_block">
    <span class="info_title">Temperature</span>
    <span class="info_value">21.5°C</span>
  </div>
  <form id="unlock" action="/devices/AABBCCDD1234/toggle">
    <input type="hidden" name="csrfmiddlewaretoken" value="lock_form_csrf_token" />
    <button type="submit" name="lock" value="AABBCCDD1234">Lock</button>
  </form>
</body>
</html>
"""

DEVICE_PAGE_NO_FORM_HTML = """
<!doctype html>
<html>
<body>
  <span class="stove_title">Main Kitchen Stove</span>
  <span class="stove_status_text">iGuardStove is off</span>
</body>
</html>
"""


def test_parse_login_csrf() -> None:
    """Test extracting CSRF token from login HTML."""
    token = parse_login_csrf(LOGIN_PAGE_HTML)
    assert token == "test_csrf_token_val"
    assert parse_login_csrf("<html></html>") is None


def test_parse_login_errors() -> None:
    """Test parsing login error messages."""
    err = parse_login_errors(LOGIN_ERROR_HTML)
    assert err == "Invalid credentials provided."
    assert parse_login_errors("<html></html>") is None


def test_has_password_input() -> None:
    """Test checking for password input presence."""
    assert has_password_input(LOGIN_PAGE_HTML) is True
    assert has_password_input("<html></html>") is False


def test_parse_dashboard_devices() -> None:
    """Test parsing discovered devices from dashboard HTML."""
    devices = parse_dashboard_devices(DASHBOARD_HTML)
    assert len(devices) == 2
    assert devices[0] == {
        "device_id": "AABBCCDD1234",
        "device_name": "Main Kitchen Stove",
    }
    assert devices[1] == {"device_id": "EEFF00112233", "device_name": "iGuardStove"}


def test_parse_device_page() -> None:
    """Test parsing full device status page."""
    data = parse_device_page("AABBCCDD1234", DEVICE_PAGE_UNLOCKED_HTML)
    assert data["device_id"] == "AABBCCDD1234"
    assert data["device_name"] == "Main Kitchen Stove"
    assert data["status_raw"] == "iGuardStove is off"
    assert data["status"] == "Stove Off"
    assert data["is_locked"] is False
    assert data["last_check_in"] == "10 minutes ago"
    assert data["fires_prevented"] == 5
    assert data["temperature"] == 21.5
    assert data["temperature_unit"] == "°C"


def test_parse_lock_form() -> None:
    """Test parsing lock toggle form parameters."""
    form_data = parse_lock_form(DEVICE_PAGE_UNLOCKED_HTML, "AABBCCDD1234")
    assert form_data.csrf_token == "lock_form_csrf_token"
    assert form_data.button_name == "lock"
    assert form_data.button_value == "AABBCCDD1234"
    assert form_data.action == "/devices/AABBCCDD1234/toggle"
    assert form_data.is_currently_locked is False


def test_parse_lock_form_missing() -> None:
    """Test parse_lock_form raises ValueError when form is absent."""
    with pytest.raises(ValueError, match="Lock toggle form not found"):
        parse_lock_form(DEVICE_PAGE_NO_FORM_HTML, "AABBCCDD1234")


def test_normalize_status_unknown() -> None:
    """Test normalize_status falls back to raw text for unknown status."""
    raw = "unheard of status text"
    res = normalize_status(raw)
    assert res == raw
    assert normalize_status(None) is None
