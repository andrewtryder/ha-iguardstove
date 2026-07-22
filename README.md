<p align="center">
  <img src="custom_components/iguardstove/brand/icon.png" alt="iGuardStove" width="120">
</p>

# ha-iguardstove

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![tests](https://github.com/andrewtryder/ha-iguardstove/actions/workflows/tests.yml/badge.svg?style=for-the-badge)](https://github.com/andrewtryder/ha-iguardstove/actions/workflows/tests.yml)
[![GitHub Release](https://img.shields.io/github/v/release/andrewtryder/ha-iguardstove?style=for-the-badge)](https://github.com/andrewtryder/ha-iguardstove/releases)
[![License](https://img.shields.io/github/license/andrewtryder/ha-iguardstove?style=for-the-badge)](LICENSE)

A Home Assistant custom integration for [iGuardStove / iGuardFire](https://www.iguardstove.com) devices. Replaces the `multiscrape` blueprint approach with a first-class HA integration that auto-discovers all stoves on your account.


---

## Features

| Entity | Platform | Description |
|---|---|---|
| **Status** | `sensor` | Human-readable stove status (e.g. "iGuardStove is LOCKED OUT for the night") |
| **Last Check-In** | `sensor` (diagnostic) | Relative time since the device last phoned home (e.g. "24 minutes ago") |
| **Temperature** | `sensor` | Ambient temperature measured by the unit (°F or °C per device settings) |
| **Stove Lock** | `lock` | Lock/unlock the stove from the HA UI, automations, or voice assistants |

All stoves registered to your account are discovered automatically at setup time and updated dynamically.

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

The lock control (`lock` entity) safely and idempotently sets the requested target lockout state by checking fresh device page form state and verifying state postconditions.

### Entities per Device

```
sensor.guest_house_stove_status
sensor.guest_house_stove_last_check_in
sensor.guest_house_stove_temperature
lock.guest_house_stove_stove_lock
```

---

## Migration from multiscrape

If you were previously using the `multiscrape` blueprint, remove those entries from your `configuration.yaml` after installing this integration. The entity IDs produced by this integration will differ; update any automations or dashboards accordingly.

| multiscrape sensor | This integration |
|---|---|
| `sensor.guest_house_stove_status` | `sensor.guest_house_stove_status` |
| `sensor.guest_house_stove_last_check_in` | `sensor.guest_house_stove_last_check_in` |
| _(not available)_ | `sensor.guest_house_stove_temperature` |
| _(not available)_ | `lock.guest_house_stove_stove_lock` |

---

## Security

Credentials are stored in Home Assistant’s protected configuration storage and are not logged by this integration. At-rest protection depends on the security and disk-encryption configuration of the Home Assistant host.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

[MIT](LICENSE)
