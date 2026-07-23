# Migration from multiscrape

If you previously used a `multiscrape` blueprint for iGuardStove, remove those entries from `configuration.yaml` after installing this integration.

Entity IDs from this integration may differ from your old sensors. Update any automations or dashboards accordingly.

| multiscrape sensor | This integration |
|---|---|
| `sensor.guest_house_stove_status` | `sensor.guest_house_stove_status` |
| `sensor.guest_house_stove_last_check_in` | `sensor.guest_house_stove_last_check_in` |
| _(not available)_ | `sensor.guest_house_stove_temperature` |
| _(not available)_ | `sensor.guest_house_stove_fires_prevented` |
| _(not available)_ | `lock.guest_house_stove_stove_lock` |
| _(not available)_ | `event.guest_house_stove_activity` |

This integration replaces the multiscrape blueprint approach with a first-class Home Assistant integration that auto-discovers all stoves on your account.
