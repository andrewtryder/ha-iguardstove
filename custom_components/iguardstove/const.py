"""Constants for the iGuardStove integration."""

DOMAIN = "iguardstove"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

BASE_URL = "https://manage.iguardfire.com"
LOGIN_URL = f"{BASE_URL}/account/login/?next=/"
DASHBOARD_URL = f"{BASE_URL}/"

CONF_DEVICE_ID = "device_id"

# Selectors
SEL_STOVE_TITLE = "stove_title"
SEL_STOVE_STATUS_TEXT = "stove_status_text"
SEL_STOVE_DATE = "stove_date"
SEL_INFO_BLOCK = "info_block"
SEL_INFO_TITLE = "info_title"
SEL_INFO_VALUE = "info_value"
SEL_STATUS_ICON = "stove_status_icon"
SEL_LOCK_IMG = "lock"

# ---------------------------------------------------------------------------
# Known stove status patterns
# ---------------------------------------------------------------------------
# Maps a lowercase substring (found in the raw status string) to a clean,
# normalised state value that is used as the sensor's state.
#
# When the portal returns a status string that doesn't match ANY of these
# patterns, the integration will:
#   1. Use the raw text as the state (so HA still has a value).
#   2. Log a WARNING with the full raw string so you can add it here later.
#
# To add a new status, find the raw text in the HA log (look for
# "Unknown iGuardStove status") and add a lowercase substring → label entry.
# ---------------------------------------------------------------------------
STATUS_MAP: dict[str, str] = {
    # Normal operating states
    "stove is off": "Stove Off",
    "stove is on": "Stove On",
    "stove has been shut off": "Stove Shut Off",

    # Lock states
    "locked out for the night": "Night Lock",
    "locked out": "Locked Out",
    "manually locked": "Manually Locked",
    "caregiver locked": "Caregiver Locked",

    # Timer / countdown
    "countdown": "Countdown Active",
    "manual timer": "Manual Timer",

    # Motion / auto shut-off
    "no motion": "No Motion Detected",
    "motion detected": "Motion Detected",
    "shut off due to inactivity": "Auto Shut Off",
    "automatically shut off": "Auto Shut Off",

    # Alert / problem states
    "emergency": "Emergency",
    "temperature alert": "Temperature Alert",
    "lost communication": "Lost Communication",
    "bypassed": "Bypassed",
}
