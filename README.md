# ha-iguardstove

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/andrewtryder/ha-iguardstove)](https://github.com/andrewtryder/ha-iguardstove/releases)
[![License](https://img.shields.io/github/license/andrewtryder/ha-iguardstove)](LICENSE)

A Home Assistant custom integration for [iGuardStove / iGuardFire](https://www.iguardstove.com) devices. Replaces the `multiscrape` blueprint approach with a first-class HA integration that auto-discovers all stoves on your account.

---

## Features

| Entity | Platform | Description |
|---|---|---|
| **Status** | `sensor` | Human-readable stove status (e.g. "iGuardStove is LOCKED OUT for the night") |
| **Last Check-In** | `sensor` (diagnostic) | Relative time since the device last phoned home (e.g. "24 minutes ago") |
| **Temperature** | `sensor` | Ambient temperature measured by the unit (°F or °C per device settings) |
| **Potential Fires Prevented** | `sensor` | Cumulative count of automatic shut-offs |
| **Locked** | `binary_sensor` | `ON` when stove is in lockout, `OFF` when available |
| **Needs Attention** | `binary_sensor` (problem) | `ON` when stove is NOT in the "stove is off" state — mirrors the original multiscrape binary sensor |
| **Stove Lock** | `lock` | Lock/unlock the stove from the HA UI, automations, or voice assistants |

All stoves registered to your account are discovered automatically at setup time.

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

## How It Works

This integration authenticates against `manage.iguardfire.com` using a standard session-cookie + Django CSRF token login flow (the same flow used by your web browser). It scrapes the device detail pages every **60 seconds** using [BeautifulSoup](https://beautiful-soup-4.readthedocs.io/en/latest/) and exposes the data as native Home Assistant entities.

The lock toggle (`lock` entity) POSTs to the same device page form that the **Lock** button on the website uses. Because the portal uses a simple toggle (not separate lock/unlock endpoints), the integration checks the current lock state before acting to avoid double-flips.

### Entities per Device

```
sensor.guest_house_stove_status
sensor.guest_house_stove_last_check_in
sensor.guest_house_stove_temperature
sensor.guest_house_stove_potential_fires_prevented
binary_sensor.guest_house_stove_locked
binary_sensor.guest_house_stove_needs_attention
lock.guest_house_stove_stove_lock
```

---

## Migration from multiscrape

If you were previously using the `multiscrape` blueprint, remove those entries from your `configuration.yaml` after installing this integration. The entity IDs produced by this integration will differ; update any automations or dashboards accordingly.

| multiscrape sensor | This integration |
|---|---|
| `sensor.guest_house_stove_status` | `sensor.guest_house_stove_status` |
| `sensor.guest_house_stove_last_check_in` | `sensor.guest_house_stove_last_check_in` |
| `binary_sensor.guest_house_stove_attention` | `binary_sensor.guest_house_stove_needs_attention` |
| _(not available)_ | `sensor.guest_house_stove_temperature` |
| _(not available)_ | `sensor.guest_house_stove_potential_fires_prevented` |
| _(not available)_ | `lock.guest_house_stove_stove_lock` |

---

## Security

Your credentials are stored in Home Assistant's encrypted config entry storage (`.storage/core.config_entries`). They are never logged.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

[MIT](LICENSE)
