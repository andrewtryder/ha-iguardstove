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
> - **Disabled by Default**: To prevent accidental remote physical activation, the write-capable **Stove Lock** entity is **disabled by default** in Home Assistant's Entity Registry. To use remote locking/unlocking, you must explicitly enable the entity in **Settings → Devices & Services → Entities → Stove Lock → Enable**.

---

## Features

| Entity | Platform | Description |
|---|---|---|
| **Status** | `sensor` | Human-readable stove status (e.g. "Stove Off", "Night Lock") |
| **Last Check-In** | `sensor` (diagnostic) | Relative time since the device last phoned home (e.g. "24 minutes ago") |
| **Temperature** | `sensor` | Ambient temperature measured by the unit (°F or °C per device settings) |
| **Fires Prevented** | `sensor` (diagnostic) | Total cumulative shutoff events recorded by the stove unit |
| **Stove Lock** | `lock` (disabled by default) | Lock/unlock the stove from HA (requires explicit UI opt-in) |
| **Activity** | `event` | Real-time portal activity events (e.g. Activity Seen, Night Lock ON/OFF, Stove Turned ON/OFF) |

All stoves registered to your account are discovered automatically at setup time and updated dynamically during the polling cycle.

---

## Activity Events

The integration parses the "Today's Events" table directly from the existing device detail HTML page fetched every 60 seconds (with **no additional HTTP requests**).

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

## Prerequisites

- An active iGuardFire account.
- At least one iGuardStove visible in the iGuardFire management portal.
- A supported Home Assistant version.
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
- **Polling Interval**: Device pages are polled every **60 seconds**.
- **Discovery Limitations**: New stoves added to an existing account are discovered automatically during the regular polling loop.

### Entities per Device

```
sensor.guest_house_stove_status
sensor.guest_house_stove_last_check_in
sensor.guest_house_stove_temperature
sensor.guest_house_stove_fires_prevented
lock.guest_house_stove_stove_lock (disabled by default)
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

---

## Security

See [SECURITY.md](SECURITY.md) for full security policy, vulnerability reporting, and credential storage security information.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

[MIT](LICENSE)
