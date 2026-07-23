"""Tests for pure HTML parser functions."""

from datetime import date, timezone
from zoneinfo import ZoneInfo

import pytest
from bs4 import BeautifulSoup

from custom_components.iguardstove.exceptions import (
    DashboardParseError,
    DevicePageParseError,
    EventParseError,
    InvalidAuth,
)
from custom_components.iguardstove.models import StoveEventType
from custom_components.iguardstove.parser import (
    has_password_input,
    normalize_event_label,
    normalize_status,
    parse_dashboard_devices,
    parse_device_page,
    parse_event_table,
    parse_lock_form,
    parse_lock_state,
    parse_login_csrf,
    parse_login_errors,
    parse_today_events,
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
  <div class="grid whole">
    <div class="child">
      <div class="title">Today's Events:</div>
      <table class="list">
        <tr>
          <th>Event</th>
          <th>Time</th>
        </tr>
        <tr>
          <td>
            <img class="activity" src="/static/gfx/moon_sm.png" />
            Activity Seen
          </td>
          <td>9:47 AM</td>
        </tr>
        <tr>
          <td>
            <img class="lock" src="/static/gfx/unlock_sm.png" />
            Night Lock OFF
          </td>
          <td>7:00 AM</td>
        </tr>
      </table>
    </div>
  </div>
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


def test_parse_dashboard_devices_empty_valid_account() -> None:
    """Test parsing valid empty dashboard page."""
    valid_empty_html = """<html><body><div class="dashboard">No stoves registered to your account.</div><a href="/account/logout/">Logout</a></body></html>"""
    assert parse_dashboard_devices(valid_empty_html) == []


def test_parse_dashboard_devices_malformed_html_raises_error() -> None:
    """Test parsing arbitrary malformed HTML raises DashboardParseError."""
    malformed_html = "<html><body><h1>Maintenance Page</h1></body></html>"
    with pytest.raises(DashboardParseError):
        parse_dashboard_devices(malformed_html)


def test_parse_dashboard_devices_auth_page_raises_error() -> None:
    """Test parsing login/auth page raises InvalidAuth."""
    with pytest.raises(InvalidAuth):
        parse_dashboard_devices(LOGIN_PAGE_HTML)


def test_parse_device_page() -> None:
    """Test parsing full device status page including events."""
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
    assert len(data["today_events"]) == 2
    assert data["events_error"] is None


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


def test_parse_today_events_multiple_valid_rows() -> None:
    """Test parsing multiple valid event rows."""
    soup = BeautifulSoup(DEVICE_PAGE_UNLOCKED_HTML, "html.parser")
    events = parse_today_events(soup, date(2026, 7, 22))
    assert len(events) == 2
    assert events[0].event_type == StoveEventType.ACTIVITY_SEEN
    assert events[0].occurred_at.hour == 9
    assert events[0].occurred_at.minute == 47
    assert events[0].raw_label == "Activity Seen"
    assert events[1].event_type == StoveEventType.NIGHT_LOCK_OFF
    assert events[1].occurred_at.hour == 7
    assert events[1].occurred_at.minute == 0


def test_parse_today_events_all_known_mappings() -> None:
    """Test mapping every known event label."""
    mappings = {
        "activity seen": StoveEventType.ACTIVITY_SEEN,
        "night lock on": StoveEventType.NIGHT_LOCK_ON,
        "night lock off": StoveEventType.NIGHT_LOCK_OFF,
        "stove turned on": StoveEventType.STOVE_ON,
        "stove turned off": StoveEventType.STOVE_OFF,
        "motion auto resumed": StoveEventType.MOTION_AUTO_RESUMED,
        "auto shut off": StoveEventType.AUTO_SHUT_OFF,
        "shut off": StoveEventType.AUTO_SHUT_OFF,
        "emergency button pressed": StoveEventType.EMERGENCY_BUTTON,
        "temperature alert": StoveEventType.TEMPERATURE_ALERT,
        "lost communication": StoveEventType.LOST_COMMUNICATION,
        "iguardstove bypassed": StoveEventType.BYPASSED,
        "no activity during the grace period": StoveEventType.NO_ACTIVITY_GRACE_PERIOD,
    }
    for label, expected in mappings.items():
        assert normalize_event_label(label) == expected
        assert normalize_event_label(label.upper()) == expected


def test_parse_today_events_unknown_label() -> None:
    """Test preserving unknown event labels."""
    html = """
    <div class="child">
      <div class="title">Today's Events:</div>
      <table class="list">
        <tr><th>Event</th><th>Time</th></tr>
        <tr><td>Brand New Event Label</td><td>11:15 AM</td></tr>
      </table>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    events = parse_today_events(soup, date(2026, 7, 22))
    assert len(events) == 1
    assert events[0].event_type == StoveEventType.UNKNOWN
    assert events[0].raw_label == "Brand New Event Label"


def test_parse_today_events_am_pm_and_tz() -> None:
    """Test parsing AM/PM times and producing timezone-aware datetimes."""
    html = """
    <div class="child">
      <div class="title">Today's Events:</div>
      <table class="list">
        <tr><th>Event</th><th>Time</th></tr>
        <tr><td>Activity Seen</td><td>12:05 AM</td></tr>
        <tr><td>Night Lock ON</td><td>12:30 PM</td></tr>
        <tr><td>Stove Turned OFF</td><td>11:59 PM</td></tr>
      </table>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    tz = ZoneInfo("America/New_York")
    events = parse_today_events(soup, date(2026, 7, 22), tzinfo=tz)
    assert len(events) == 3
    assert events[0].occurred_at.hour == 0
    assert events[0].occurred_at.minute == 5
    assert events[0].occurred_at.tzinfo == tz

    assert events[1].occurred_at.hour == 12
    assert events[1].occurred_at.minute == 30

    assert events[2].occurred_at.hour == 23
    assert events[2].occurred_at.minute == 59


def test_parse_today_events_valid_no_event_day() -> None:
    """Test handling valid no-event day HTML fixtures."""
    # Case 1: Header-only table
    html1 = """
    <div class="child">
      <div class="title">Today's Events:</div>
      <table class="list">
        <tr><th>Event</th><th>Time</th></tr>
      </table>
    </div>
    """
    soup1 = BeautifulSoup(html1, "html.parser")
    assert parse_today_events(soup1, date(2026, 7, 22)) == ()

    # Case 2: No table but explicit message
    html2 = """
    <div class="child">
      <div class="title">Today's Events:</div>
      <p>No events recorded today.</p>
    </div>
    """
    soup2 = BeautifulSoup(html2, "html.parser")
    assert parse_today_events(soup2, date(2026, 7, 22)) == ()


def test_parse_today_events_missing_section() -> None:
    """Test rejecting missing Today's Events section."""
    soup = BeautifulSoup("<div><p>Empty page</p></div>", "html.parser")
    with pytest.raises(EventParseError, match="Today's Events section missing"):
        parse_today_events(soup, date(2026, 7, 22))


def test_parse_today_events_unexpected_headers() -> None:
    """Test rejecting unexpected table headers."""
    html = """
    <div class="child">
      <div class="title">Today's Events:</div>
      <table class="list">
        <tr><th>WrongHeader1</th><th>WrongHeader2</th></tr>
      </table>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    with pytest.raises(EventParseError, match="Unexpected event table headers"):
        parse_today_events(soup, date(2026, 7, 22))


def test_parse_today_events_malformed_rows() -> None:
    """Test handling malformed rows."""
    html = """
    <div class="child">
      <div class="title">Today's Events:</div>
      <table class="list">
        <tr><th>Event</th><th>Time</th></tr>
        <tr><td>Activity Seen</td></tr>
      </table>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    with pytest.raises(EventParseError, match="Malformed event row"):
        parse_today_events(soup, date(2026, 7, 22))


def test_parse_today_events_invalid_time_value() -> None:
    """Test rejecting invalid time value strings."""
    html = """
    <div class="child">
      <div class="title">Today's Events:</div>
      <table class="list">
        <tr><th>Event</th><th>Time</th></tr>
        <tr><td>Activity Seen</td><td>INVALID_TIME</td></tr>
      </table>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    with pytest.raises(EventParseError, match="Invalid time format"):
        parse_today_events(soup, date(2026, 7, 22))


def test_parse_today_events_duplicate_ordinals() -> None:
    """Test assigning duplicate ordinals deterministically."""
    html = """
    <div class="child">
      <div class="title">Today's Events:</div>
      <table class="list">
        <tr><th>Event</th><th>Time</th></tr>
        <tr><td>Activity Seen</td><td>9:47 AM</td></tr>
        <tr><td>Activity Seen</td><td>9:47 AM</td></tr>
      </table>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    events = parse_today_events(soup, date(2026, 7, 22))
    assert len(events) == 2
    assert events[0].duplicate_ordinal == 0
    assert events[1].duplicate_ordinal == 1


def test_parse_today_events_ignores_calendar_summary() -> None:
    """Test ignoring calendar summary links."""
    html = """
    <div class="child">
      <div class="title">Calendar:</div>
      <a href="/devices/AABBCCDD1234/events/2026/07/22/">22</a>
    </div>
    <div class="child">
      <div class="title">Today's Events:</div>
      <table class="list">
        <tr><th>Event</th><th>Time</th></tr>
        <tr><td>Activity Seen</td><td>9:47 AM</td></tr>
      </table>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    events = parse_today_events(soup, date(2026, 7, 22))
    assert len(events) == 1
    assert events[0].event_type == StoveEventType.ACTIVITY_SEEN


def test_parse_today_events_rejects_login_page() -> None:
    """Test that login page is rejected as EventParseError."""
    soup = BeautifulSoup(LOGIN_PAGE_HTML, "html.parser")
    with pytest.raises(EventParseError, match="Login page returned"):
        parse_today_events(soup, date(2026, 7, 22))


def test_parse_today_events_preserves_row_order() -> None:
    """Test preserving source table order."""
    html = """
    <div class="child">
      <div class="title">Today's Events:</div>
      <table class="list">
        <tr><th>Event</th><th>Time</th></tr>
        <tr><td>Stove Turned ON</td><td>10:00 AM</td></tr>
        <tr><td>Activity Seen</td><td>9:50 AM</td></tr>
        <tr><td>Night Lock OFF</td><td>7:00 AM</td></tr>
      </table>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    events = parse_today_events(soup, date(2026, 7, 22))
    assert [e.raw_label for e in events] == [
        "Stove Turned ON",
        "Activity Seen",
        "Night Lock OFF",
    ]


def test_parse_event_table_reusability() -> None:
    """Test parse_event_table can be called directly on table element."""
    html = """
    <table class="list">
      <tr><th>Event</th><th>Time</th></tr>
      <tr><td>Stove Turned ON</td><td>10:00 AM</td></tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    assert table is not None
    events = parse_event_table(table, date(2026, 7, 22), tzinfo=timezone.utc)
    assert len(events) == 1
    assert events[0].event_type == StoveEventType.STOVE_ON


def test_parse_lock_form_unnamed_form_fallback() -> None:
    """Test parse_lock_form falls back to scanning forms with lock/unlock button."""
    html = """
    <form action="/devices/DEV1/">
      <input name="csrfmiddlewaretoken" value="csrftoken123">
      <button name="unlock" value="DEV1">Unlock</button>
    </form>
    """
    form_data = parse_lock_form(html, "DEV1")
    assert form_data.csrf_token == "csrftoken123"
    assert form_data.is_currently_locked is True


def test_parse_lock_form_validation_errors() -> None:
    """Test parse_lock_form raises ValueError on invalid HTML structure."""
    html_no_csrf = """
    <form id="lock">
      <button name="lock">Lock</button>
    </form>
    """
    with pytest.raises(ValueError, match="csrfmiddlewaretoken missing"):
        parse_lock_form(html_no_csrf, "DEV1")

    html_unnamed_button = """
    <form id="lock">
      <input name="csrfmiddlewaretoken" value="token">
      <button>Lock</button>
    </form>
    """
    with pytest.raises(ValueError, match="Lock button missing"):
        parse_lock_form(html_unnamed_button, "DEV1")

    html_bad_button = """
    <form id="lock">
      <input name="csrfmiddlewaretoken" value="token">
      <button name="invalid">Lock</button>
    </form>
    """
    with pytest.raises(ValueError, match="Unexpected button name"):
        parse_lock_form(html_bad_button, "DEV1")


def test_parse_device_page_generic_same_origin_200_html() -> None:
    """Test parse_device_page raises DevicePageParseError on generic same-origin 200 HTML."""
    html = "<html><body><h1>Welcome to Portal</h1><p>Dashboard main content</p></body></html>"
    with pytest.raises(
        DevicePageParseError, match="Missing core device page invariants"
    ):
        parse_device_page("DEV123", html)
    assert parse_lock_state(html) is None


def test_parse_device_page_maintenance_page() -> None:
    """Test parse_device_page raises DevicePageParseError on maintenance page HTML."""
    html = """
    <!doctype html>
    <html>
    <body>
      <div class="maintenance">
        <h1>System Maintenance</h1>
        <p>The iGuardFire portal is under scheduled maintenance. Please try again later.</p>
      </div>
    </body>
    </html>
    """
    with pytest.raises(
        DevicePageParseError, match="Missing core device page invariants"
    ):
        parse_device_page("DEV123", html)
    assert parse_lock_state(html) is None


def test_parse_device_page_missing_lock_form_and_icon() -> None:
    """Test lock state returns None when form and icon are missing and status is unrecognized."""
    html_unrecognized = """
    <!doctype html>
    <html>
    <body>
      <span class="stove_title">Main Kitchen Stove</span>
      <span class="stove_status_text">Custom portal status</span>
      <span class="stove_date">iGuardStove Last Checked In: 5 minutes ago</span>
    </body>
    </html>
    """
    assert parse_lock_state(html_unrecognized) is None
    data = parse_device_page("DEV123", html_unrecognized)
    assert data["is_locked"] is None
    assert data["status_raw"] == "Custom portal status"

    html_recognized_unlocked = """
    <!doctype html>
    <html>
    <body>
      <span class="stove_title">Main Kitchen Stove</span>
      <span class="stove_status_text">iGuardStove is off</span>
      <span class="stove_date">iGuardStove Last Checked In: 5 minutes ago</span>
    </body>
    </html>
    """
    assert parse_lock_state(html_recognized_unlocked) is False
    data2 = parse_device_page("DEV123", html_recognized_unlocked)
    assert data2["is_locked"] is False


def test_parse_device_page_changed_status_markup() -> None:
    """Test lock state parsing when status markup structure is changed or unrecognized."""
    html = """
    <!doctype html>
    <html>
    <body>
      <span class="stove_title">Main Kitchen Stove</span>
      <div class="unknown_status_wrapper">Status: Active Operating Mode</div>
      <span class="stove_date">iGuardStove Last Checked In: 1 minute ago</span>
    </body>
    </html>
    """
    assert parse_lock_state(html) is None
    data = parse_device_page("DEV123", html)
    assert data["is_locked"] is None


def test_parse_device_page_auth_page_without_password_element() -> None:
    """Test rejecting auth pages that do not contain exact password input element."""
    username_only_form = """
    <!doctype html>
    <html>
    <body>
      <form action="/account/login/" method="post">
        <label>Username or Email</label>
        <input type="text" name="username" />
        <button type="submit">Next</button>
      </form>
    </body>
    </html>
    """
    with pytest.raises(InvalidAuth, match="Auth or login page returned"):
        parse_device_page("DEV123", username_only_form)

    session_expired_notice = """
    <!doctype html>
    <html>
    <body>
      <div class="session-expired">
        <h2>Session Expired</h2>
        <p>Please <a href="/account/login/">sign in</a> again to continue.</p>
      </div>
    </body>
    </html>
    """
    with pytest.raises((InvalidAuth, DevicePageParseError)):
        parse_device_page("DEV123", session_expired_notice)
