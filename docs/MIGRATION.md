# Migration from multiscrape

If you previously used a `multiscrape` blueprint for iGuardStove, remove those entries from `configuration.yaml` after installing this integration.

Entity IDs from this integration may differ from your old sensors. Update any automations or dashboards accordingly.

| multiscrape sensor | This integration |
|---|---|
| `sensor.guest_house_stove_status` | `sensor.guest_house_stove_status` |
| `sensor.guest_house_stove_last_check_in` | `sensor.guest_house_stove_last_check_in` |
| _(not available)_ | `sensor.guest_house_stove_temperature` |
| _(not available)_ | `sensor.guest_house_stove_fires_prevented` |
| _(not available)_ | `binary_sensor.guest_house_stove_stove_lockout` |
| _(not available)_ | `lock.guest_house_stove_master_lock` |
| _(not available)_ | `event.guest_house_stove_activity` |

This integration replaces the multiscrape blueprint approach with a first-class Home Assistant integration that auto-discovers all stoves on your account.

## Breaking change: Master Lock vs lockout (config entry version 2)

> [!CAUTION]
> **Breaking entity migration.** Upgrading retires the legacy lock unique ID `{device_id}_stove_lock` and replaces it with separate Master Lock and Stove Lockout entities. Old lock `entity_id`s (including user-renamed ones) stop working. Update automations, dashboards, and voice exposures before or immediately after upgrade.

iGuard separates **Master Lock** (remote form toggle) from **effective lockout** (Night/Scheduled Lock, caregiver lock, etc.).

| Concept | Platform | Unique ID |
|---|---|---|
| Master Lock | `lock` | `{device_id}_master_lock` |
| Stove Lockout | `binary_sensor` | `{device_id}_stove_lockout` |
| Legacy effective lock (retired) | — | `{device_id}_stove_lock` **removed on upgrade** |

### What to replace

| If your old lock entity was used for… | Replace it with… |
|---|---|
| Manual / remote lock control (engage or disengage Master Lock) | **Master lock** (`lock.…_master_lock`) |
| “Can the stove currently operate?” / effective lockout / Night Lock | **Stove lockout** (`binary_sensor.…_stove_lockout`) or **Status** |

Do not keep pointing “is the stove usable?” automations at Master lock. During Night Lock with Master Lock off, Master lock reports `unlocked` while Stove lockout stays `on`.

### What happens on upgrade

1. Config entry migrates from version **1 → 2**.
2. Migration walks **entity-registry entries owned by this config entry** (not the current portal discovery list). Legacy lock rows still migrate even if that stove is offline or missing from `devices` / discovery.
3. Each legacy `lock` registry entry with unique_id `{device_id}_stove_lock` is removed.
4. A new Master Lock registry entry is created at `{device_id}_master_lock` (new `entity_id`).
5. **Stove lockout** (`…_stove_lockout`) is unchanged (or created on first setup if missing).

Preserved from the legacy lock when present: enabled/disabled state (`disabled_by`), custom name, icon, and area.

**Not preserved:** the legacy `entity_id` (including user-renamed IDs). Home Assistant cannot move a registry identity from `lock` to `binary_sensor`, and reusing the old `entity_id` for Master Lock would silently change meaning for automations.

### After upgrade

- Use **Stove lockout** or **Status** for “is the stove prevented from operating?”
- Use **Master lock** only for the remote Master Lock toggle.
- During Night Lock with Master Lock off, Master lock reports `unlocked` while Stove lockout stays `on`. Do not treat Master lock `unlocked` as “stove is usable.”
