"""Pure HTML parsing functions for iGuardStove portal pages."""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from bs4 import BeautifulSoup, Tag

from .const import (
    SEL_INFO_BLOCK,
    SEL_INFO_TITLE,
    SEL_INFO_VALUE,
    SEL_LOCK_IMG,
    SEL_STATUS_ICON,
    SEL_STOVE_DATE,
    SEL_STOVE_STATUS_TEXT,
    SEL_STOVE_TITLE,
    STATUS_MAP,
)
from .exceptions import (
    DashboardParseError,
    DevicePageParseError,
    EventParseError,
    InvalidAuth,
)
from .models import StoveEvent, StoveEventType
from .types import DeviceData, DeviceSummary

_LOGGER = logging.getLogger(__name__)

DEVICE_URL_RE = re.compile(r"^/devices/([A-F0-9]+)/$")
CHECKIN_PREFIX_RE = re.compile(
    r"^iGuardStove\s+Last\s+Checked\s+In:\s*", flags=re.IGNORECASE
)
TEMP_RE = re.compile(r"([\d.]+)\s*(°[FC]?)?")

_SEEN_UNKNOWN_STATUSES: set[str] = set()
_SEEN_UNKNOWN_EVENT_LABELS: set[str] = set()
_SEEN_EVENT_PARSE_ERRORS: set[str] = set()

EVENT_TYPE_MAP: dict[str, StoveEventType] = {
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


@dataclass(frozen=True)
class LockFormData:
    """Extracted lock form parameters."""

    csrf_token: str
    button_name: str
    button_value: str
    action: str | None
    is_currently_locked: bool


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
    return raw


def normalize_event_label(raw_label: str) -> StoveEventType:
    """Normalize raw event string to StoveEventType enum value.

    Uses ' '.join(raw_label.casefold().split()) for normalization.
    """
    normalized_text = " ".join(raw_label.casefold().split())
    if normalized_text in EVENT_TYPE_MAP:
        return EVENT_TYPE_MAP[normalized_text]

    if raw_label not in _SEEN_UNKNOWN_EVENT_LABELS:
        _SEEN_UNKNOWN_EVENT_LABELS.add(raw_label)
        _LOGGER.warning(
            "Unknown iGuardStove event label encountered: %r — "
            "please open an issue to add support for this label",
            raw_label,
        )

    return StoveEventType.UNKNOWN


def parse_login_csrf(html: str) -> str | None:
    """Extract CSRF middleware token from login form HTML."""
    soup = BeautifulSoup(html, "html.parser")
    csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
    if csrf_input and isinstance(csrf_input.get("value"), str):
        return csrf_input["value"]
    return None


def parse_login_errors(html: str) -> str | None:
    """Check login page HTML for error banners or error lists."""
    soup = BeautifulSoup(html, "html.parser")
    err_el = soup.find(class_="errorlist") or soup.find(class_="alert-danger")
    if err_el:
        return err_el.get_text(strip=True)
    return None


def has_password_input(html: str) -> bool:
    """Return True if password input element is present in HTML."""
    soup = BeautifulSoup(html, "html.parser")
    return soup.find("input", {"type": "password"}) is not None


def parse_dashboard_devices(html: str) -> list[DeviceSummary]:
    """Parse device links from account dashboard HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # 1. Reject login / auth pages
    if (
        soup.find("input", {"type": "password"})
        or soup.find("input", {"name": ["login", "username"]})
        or soup.find(class_="errorlist")
        or soup.find(class_="alert-danger")
        or soup.find("form", action=re.compile(r"/account/login/?", re.I))
    ):
        raise InvalidAuth("Auth or login page returned instead of account dashboard")

    devices: list[DeviceSummary] = []
    seen_device_ids: set[str] = set()

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

    if devices:
        return devices

    # 2. Check for explicit valid empty dashboard page invariants
    page_text = soup.get_text().casefold()
    has_dashboard_structure = (
        soup.find("a", href=re.compile(r"/account/logout/?", re.I)) is not None
        or soup.find(class_=["stoves_list", "stove_line", "dashboard"]) is not None
        or "no stoves" in page_text
        or "no devices" in page_text
        or "registered stoves" in page_text
        or "your stoves" in page_text
    )

    if not has_dashboard_structure:
        raise DashboardParseError(
            "Account dashboard HTML missing expected page structure or device list"
        )

    return []


def parse_event_table(
    table: Tag,
    event_date: date,
    tzinfo: tzinfo | None = None,
) -> tuple[StoveEvent, ...]:
    """Parse rows from an iGuardStove event table element.

    This function can be reused for both live device pages and historical daily event pages.
    """
    rows = table.find_all("tr")
    if not rows:
        return ()

    # Check header row
    header_row = rows[0]
    header_cells = header_row.find_all(["th", "td"])
    header_texts = [
        " ".join(cell.get_text().casefold().split()) for cell in header_cells
    ]
    if len(header_texts) < 2 or header_texts[0] != "event" or header_texts[1] != "time":
        raise EventParseError(
            f"Unexpected event table headers: expected ['Event', 'Time'], got {header_texts!r}"
        )

    events: list[StoveEvent] = []
    seen_ordinals: dict[tuple[datetime, str], int] = defaultdict(int)

    for row in rows[1:]:
        tds = row.find_all("td")
        if not tds:
            continue
        if len(tds) != 2:
            raise EventParseError(
                f"Malformed event row: expected exactly 2 td cells, found {len(tds)}"
            )

        raw_label = tds[0].get_text(strip=True)
        raw_time = tds[1].get_text(strip=True).replace("\xa0", " ")

        if not raw_label or not raw_time:
            raise EventParseError("Malformed event row: missing label or time text")

        try:
            time_obj = datetime.strptime(raw_time, "%I:%M %p").time()
        except ValueError as err:
            raise EventParseError(
                f"Invalid time format in event table: {raw_time!r}"
            ) from err

        naive_dt = datetime.combine(event_date, time_obj)
        aware_dt = naive_dt.replace(tzinfo=tzinfo) if tzinfo is not None else naive_dt

        event_type = normalize_event_label(raw_label)
        norm_label = " ".join(raw_label.casefold().split())

        key = (aware_dt, norm_label)
        ordinal = seen_ordinals[key]
        seen_ordinals[key] += 1

        events.append(
            StoveEvent(
                occurred_at=aware_dt,
                event_type=event_type,
                raw_label=raw_label,
                duplicate_ordinal=ordinal,
            )
        )

    return tuple(events)


def parse_today_events(
    soup: BeautifulSoup,
    event_date: date,
    tzinfo: tzinfo | None = None,
) -> tuple[StoveEvent, ...]:
    """Parse 'Today's Events' section from device detail page soup.

    The page loads /static/tz.js, so the displayed portal time is assumed to match
    the Home Assistant-local/account-local timezone until the portal behavior is better understood.
    """
    # 1. Reject login page
    if soup.find("input", {"type": "password"}) or soup.find(class_="errorlist"):
        raise EventParseError("Login page returned instead of device page")

    # 2. Find div.title equal to "Today's Events:"
    title_el = None
    for div in soup.find_all("div", class_="title"):
        norm_text = " ".join(div.get_text().casefold().split())
        if norm_text in ("today's events:", "today's events"):
            title_el = div
            break

    if not title_el:
        raise EventParseError("Today's Events section missing")

    # 3. Find nearest enclosing div.child
    child_div = title_el.find_parent(class_="child")
    if not child_div:
        raise EventParseError("Today's Events container div.child missing")

    # 4. Find table.list within that div.child
    table = child_div.find("table", class_="list") or child_div.find("table")
    if not table:
        child_text = child_div.get_text().casefold()
        if "no events" in child_text or "no activity" in child_text:
            return ()
        raise EventParseError("Event table missing in Today's Events section")

    return parse_event_table(table, event_date, tzinfo)


def validate_device_page_invariants(soup: BeautifulSoup, device_id: str) -> None:
    """Validate core iGuardStove device page structure invariants."""
    # 1. Check for auth/login pages
    if (
        soup.find("input", {"type": "password"})
        or soup.find("input", {"name": ["login", "username"]})
        or soup.find(class_="errorlist")
        or soup.find(class_="alert-danger")
        or soup.find("form", action=re.compile(r"/account/login/?", re.I))
    ):
        raise InvalidAuth(
            f"Auth or login page returned instead of device page for {device_id}"
        )

    # 2. Check for core device detail page invariants
    has_title = soup.find(class_=SEL_STOVE_TITLE) is not None
    has_status = soup.find(class_=SEL_STOVE_STATUS_TEXT) is not None
    has_date = soup.find(class_=SEL_STOVE_DATE) is not None
    has_lock_form = soup.find("form", {"id": ["unlock", "lock"]}) is not None or any(
        f.find("button", {"name": ["lock", "unlock"]}) for f in soup.find_all("form")
    )
    has_status_icon = soup.find(class_=SEL_STATUS_ICON) is not None
    has_info_block = soup.find(class_=SEL_INFO_BLOCK) is not None

    if not has_title or not (
        has_status or has_date or has_lock_form or has_status_icon or has_info_block
    ):
        raise DevicePageParseError(
            f"Missing core device page invariants for device {device_id}"
        )


def _parse_lock_form_state(soup: BeautifulSoup) -> bool | None:
    """Parse lock state from lock/unlock form button if present."""
    form = soup.find("form", {"id": ["unlock", "lock"]})
    if not form:
        for f in soup.find_all("form"):
            if f.find("button", {"name": ["lock", "unlock"]}):
                form = f
                break

    button = form.find("button") if form else None
    if button and button.get("name") in ("lock", "unlock"):
        return button.get("name") == "unlock"
    return None


def _parse_lock_icon_state(soup: BeautifulSoup) -> bool | None:
    """Parse lock state from stove status icon container if present."""
    icon_block = soup.find(class_=SEL_STATUS_ICON)
    if icon_block:
        if icon_block.find("img", class_=SEL_LOCK_IMG):
            return True
        if icon_block.find("img", class_="unlock"):
            return False
    return None


def _parse_lock_text_state(
    soup: BeautifulSoup, status: str | None = None
) -> bool | None:
    """Parse lock state from status text element or status string."""
    status_el = soup.find(class_=SEL_STOVE_STATUS_TEXT)
    raw_status = status_el.get_text(strip=True) if status_el else status
    if not raw_status:
        return None

    lower = raw_status.lower()
    if "locked" in lower:
        return True

    norm = normalize_status(raw_status)
    if norm and norm.lower() != lower and "locked" not in norm.lower():
        return False

    for pattern in STATUS_MAP:
        if pattern in lower:
            return "locked" in pattern

    return None


def parse_lock_state(
    html_or_soup: str | BeautifulSoup, status: str | None = None
) -> bool | None:
    """Parse lock state (True = locked, False = unlocked, None = unknown) from device HTML or soup."""
    soup = (
        html_or_soup
        if isinstance(html_or_soup, BeautifulSoup)
        else BeautifulSoup(html_or_soup, "html.parser")
    )

    state = _parse_lock_form_state(soup)
    if state is not None:
        return state

    state = _parse_lock_icon_state(soup)
    if state is not None:
        return state

    return _parse_lock_text_state(soup, status)


def parse_device_page(
    device_id: str,
    html: str,
    event_date: date | None = None,
    tzinfo: tzinfo | None = None,
) -> DeviceData:
    """Parse the device detail page HTML into a DeviceData dict."""
    soup = BeautifulSoup(html, "html.parser")
    validate_device_page_invariants(soup, device_id)
    data: DeviceData = {"device_id": device_id}

    # Title / name
    title_el = soup.find(class_=SEL_STOVE_TITLE)
    data["device_name"] = title_el.get_text(strip=True) if title_el else "iGuardStove"

    # Status
    status_el = soup.find(class_=SEL_STOVE_STATUS_TEXT)
    raw_status: str | None = status_el.get_text(strip=True) if status_el else None
    data["status_raw"] = raw_status
    data["status"] = normalize_status(raw_status)

    # Lock state
    data["is_locked"] = parse_lock_state(soup, data.get("status"))

    # Last check-in
    checkin_el = soup.find(class_=SEL_STOVE_DATE)
    if checkin_el:
        raw = checkin_el.get_text(strip=True)
        data["last_check_in"] = CHECKIN_PREFIX_RE.sub("", raw)
    else:
        data["last_check_in"] = None

    # Info blocks (fires prevented, temperature)
    data["fires_prevented"] = None
    data["temperature"] = None
    data["temperature_unit"] = "°F"

    _parse_info_blocks(soup, data)

    # Parse today's events with isolated failure domain
    try:
        if event_date is None:
            event_date = date.today()
        data["today_events"] = parse_today_events(soup, event_date, tzinfo)
        data["events_error"] = None
    except EventParseError as err:
        err_key = f"{device_id}:{err}"
        if err_key not in _SEEN_EVENT_PARSE_ERRORS:
            _SEEN_EVENT_PARSE_ERRORS.add(err_key)
            _LOGGER.warning("Event parse error for device %s: %s", device_id, err)
        else:
            _LOGGER.debug("Event parse error for device %s: %s", device_id, err)
        data["today_events"] = ()
        data["events_error"] = str(err)

    return data


def _parse_info_blocks(soup: BeautifulSoup, data: DeviceData) -> None:
    """Helper to populate fires_prevented and temperature from info blocks."""
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


def parse_lock_form(html: str, device_id: str) -> LockFormData:
    """Parse the lock form parameters from device page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", {"id": "unlock"}) or soup.find("form", {"id": "lock"})
    if not form:
        for f in soup.find_all("form"):
            if f.find("button", {"name": ["lock", "unlock"]}):
                form = f
                break

    if not form:
        raise ValueError(f"Lock toggle form not found on device page for {device_id}")

    csrf_input = form.find("input", {"name": "csrfmiddlewaretoken"})
    if (
        not csrf_input
        or not isinstance(csrf_input.get("value"), str)
        or not csrf_input.get("value")
    ):
        raise ValueError("csrfmiddlewaretoken missing or invalid in lock form")

    csrf_token = str(csrf_input["value"])

    button = form.find("button")
    if not button or not button.get("name"):
        raise ValueError("Lock button missing or unnamed in form")

    button_name = str(button.get("name"))
    if button_name not in ("lock", "unlock"):
        raise ValueError(f"Unexpected button name {button_name!r} in lock form")

    is_currently_locked = button_name == "unlock"
    button_value = str(button.get("value", device_id))
    action = form.get("action")
    action_str = str(action) if action else None

    return LockFormData(
        csrf_token=csrf_token,
        button_name=button_name,
        button_value=button_value,
        action=action_str,
        is_currently_locked=is_currently_locked,
    )
