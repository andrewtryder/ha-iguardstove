<p align="center">
  <img src="custom_components/iguardstove/brand/icon.png" alt="iGuardStove" width="120">
</p>

# ha-iguardstove

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![tests](https://github.com/andrewtryder/ha-iguardstove/actions/workflows/tests.yml/badge.svg?style=for-the-badge)](https://github.com/andrewtryder/ha-iguardstove/actions/workflows/tests.yml)
[![GitHub Release](https://img.shields.io/github/v/release/andrewtryder/ha-iguardstove?style=for-the-badge)](https://github.com/andrewtryder/ha-iguardstove/releases)
[![License](https://img.shields.io/github/license/andrewtryder/ha-iguardstove?style=for-the-badge)](LICENSE)

A Home Assistant custom integration for [iGuardStove / iGuardFire](https://www.iguardstove.com) devices. Replaces the `multiscrape` blueprint approach with a first-class HA integration that auto-discovers all stoves on your account.

![iGuardStove Device Dashboard](images/device_page.png)

---

> [!WARNING]
> ### Important Safety Warning
> This integration provides remote control capabilities over physical stove lockout hardware.
> - **Accidental Remote Activation**: Automating stove lock/unlock operations via voice assistants (Alexa, Google Assistant, Siri) or automated triggers carries inherent safety risks.
> - **Disabled by Default**: To prevent accidental remote physical activation, the write-capable **Stove Lock** entity is **disabled by default** in Home Assistant's Entity Registry. To use remote control, you must explicitly enable the entity in **Settings → Devices & Services → Entities → Stove Lock → Enable**.
> - **Separate Remote-Unlock Permission**: Enabling the entity allows remote locking. For safety, **Remote Unlock** remains disabled by default even when the entity is enabled. Unlocking the stove requires enabling **Allow remote disengagement of stove lockout (Remote Unlock)** in **Settings → Devices & Services → iGuardStove → Configure**.

---

## Features

| Entity | Platform | Description |
|---|---|---|
| **Status** | `sensor` | Human-readable stove status (e.g. "Stove Off", "Night Lock") |
| **Last Check-In** | `sensor` (diagnostic) | Relative time since the device last phoned home (e.g. "24 minutes ago") |
| **Temperature** | `sensor` | Ambient temperature measured by the unit (°F or °C per device settings) |
| **Fires Prevented** | `sensor` (diagnostic) | Total cumulative shutoff events recorded by the stove unit |
| **Stove Lock** | `lock` (disabled by default) | Remote lock/unlock from HA (requires entity opt-in and separate Options Flow permission for unlock) |
| **Activity** | `event` | Portal activity events (e.g. Activity Seen, Night Lock ON/OFF, Stove Turned ON/OFF) detected during each polling cycle |

All stoves registered to your account are discovered automatically at setup time, with dynamic discovery running every 6 hours and state updates polled on a configurable interval (**30–300 seconds**, default **60**).

---

## Activity Events

The integration parses the "Today's Events" table directly from the existing device detail HTML page fetched on each poll (with **no additional HTTP requests**).

### Supported Event Types
- `activity_seen` ("Activity Seen")
- `night_lock_on` ("Night Lock ON")
- `night_lock_off` ("Night Lock OFF")
- `stove_on` ("Stove Turned ON")
- `stove_off` ("Stove Turned OFF")
- `motion_auto_resumed` ("Motion Auto Resumed")
- `auto_shut_off` ("Auto Shut Off" / "Shut Off")
- `emergency_button` ("Emergency Button Pressed")
- `temperature_alert` ("Temperature Alert")
- `lost_communication` ("Lost Communication")
- `bypassed` ("iGuardStove Bypassed")
- `no_activity_grace_period` ("No Activity During Grace Period")
- `unknown` (Unmapped portal event labels, with `raw_label` preserved as an attribute)

### Event Handling & Deduplication
- **No Replaying on Startup**: Existing events present on the portal page at initial integration setup or Home Assistant restart are seeded into deduplication memory and **not** replayed as new events.
- **Timezone Handling**: Displayed portal times (which load `/static/tz.js` on the web interface) are combined with the current Home Assistant local date and interpreted in the Home Assistant local timezone.
- **Oldest-First Emission**: When multiple new events are detected in a single refresh, they are emitted in chronological order (oldest-first) to ensure Home Assistant automations observe proper event ordering.
- **Persistence**: Event fingerprints are persisted to Home Assistant storage using a 48-hour rolling window so reloads and restarts maintain exact deduplication state.

---

## Automation Blueprints

This repository includes project-provided Home Assistant automation blueprints to easily create automations for iGuardStove safety and operational activity events directly in the Home Assistant UI.

### Included Blueprints

1. **iGuardStove - Event Action Runner**: A flexible blueprint to trigger custom actions (mobile/persistent notifications, lights, sirens, TTS, or scripts) whenever selected iGuardStove event types occur.
   [![Import Blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fandrewtryder%2Fha-iguardstove%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Figuardstove%2Fselected_event_actions.yaml)

2. **iGuardStove - Stove Safety Notification**: A guided blueprint configured for mobile app safety alerts with customizable titles and optional critical notification sound overrides (bypassing silent mode on supported devices).
   [![Import Blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fandrewtryder%2Fha-iguardstove%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Figuardstove%2Fsafety_notification.yaml)

### Blueprint Safety Principles

To preserve the safety model of iGuardStove:
- **No Automatic Unlocking**: Blueprints in this repository are strictly notification and action runners. Blueprints will **never** automatically unlock the stove (e.g., via presence, schedules, or voice commands).
- **Manual Lock Entity Opt-in**: The write-capable lock entity remains disabled by default in Home Assistant.

---

## Prerequisites

- An active iGuardFire account.
- At least one iGuardStove visible in the iGuardFire management portal.
- Home Assistant 2026.3.0 or newer.
- Internet access from Home Assistant to `manage.iguardfire.com`.

> [!NOTE]
> This integration depends on an undocumented portal HTML interface (`manage.iguardfire.com`) and does not use an official REST API.

---

## Installation

### Via HACS (recommended)

1. In HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/andrewtryder/ha-iguardstove` as an **Integration**
3. Install **iGuardStove** from HACS
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/iguardstove` folder into your `<config>/custom_components/` directory
2. Restart Home Assistant

---

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **iGuardStove**
3. Enter your **iGuardFire account email and password**
4. All stoves on the account are discovered and set up automatically

No YAML configuration is needed.

---

## Architecture & Limitations

- **Web Scraping Dependency**: The integration authenticates against `manage.iguardfire.com` using a Django CSRF token + session cookie flow and scrapes HTML detail pages using BeautifulSoup. Because there is no official REST API, breaking changes to the portal's DOM layout may require integration updates.
- **Polling Interval**: Device pages are polled on a configurable interval (**30–300 seconds**, default **60**).
- **Dynamic Discovery**: New stoves added to an existing account are discovered automatically during periodic background discovery passes (every **6 hours**).

### Entities per Device

```
sensor.guest_house_stove_status
sensor.guest_house_stove_last_check_in
sensor.guest_house_stove_temperature
sensor.guest_house_stove_fires_prevented
lock.guest_house_stove_stove_lock (disabled by default)
event.guest_house_stove_activity
```

---

## Migration from multiscrape

If you were previously using the `multiscrape` blueprint, remove those entries from your `configuration.yaml` after installing this integration. The entity IDs produced by this integration will differ; update any automations or dashboards accordingly.

| multiscrape sensor | This integration |
|---|---|
| `sensor.guest_house_stove_status` | `sensor.guest_house_stove_status` |
| `sensor.guest_house_stove_last_check_in` | `sensor.guest_house_stove_last_check_in` |
| _(not available)_ | `sensor.guest_house_stove_temperature` |
| _(not available)_ | `sensor.guest_house_stove_fires_prevented` |
| _(not available)_ | `lock.guest_house_stove_stove_lock` |
| _(not available)_ | `event.guest_house_stove_activity` |

---

## Removing the integration

1. Open **Settings → Devices & services**.
2. Select **iGuardStove**.
3. Open the integration menu and select **Delete**.
4. If installed manually, remove `custom_components/iguardstove`.
5. Restart Home Assistant after removing a manual installation.

Removing the integration does not modify the iGuardFire account, portal settings, schedules, or physical stove configuration.

---

## Security

See [SECURITY.md](SECURITY.md) for full security policy, vulnerability reporting, and credential storage security information.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

[MIT](LICENSE)
