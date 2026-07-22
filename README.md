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

All stoves registered to your account are discovered automatically at setup time and updated dynamically during the polling cycle.

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
