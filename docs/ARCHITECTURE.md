# Architecture

Technical details for contributors and maintainers. End users should start with the [README](../README.md).

## Overview

This is a Home Assistant custom integration that authenticates against `manage.iguardfire.com` and scrapes device detail pages. There is no official REST API.

| Module | Responsibility |
|---|---|
| `client.py` | HTTP (`aiohttp`), login, CSRF handling, lock POST |
| `parser.py` | BeautifulSoup HTML parsing and DOM invariants |
| `coordinator.py` | Polling loop and dynamic discovery via `DataUpdateCoordinator` |
| `config_flow.py` | UI setup (no YAML required) |
| `sensor.py` / `lock.py` / `event.py` | Entity platforms |

## Authentication & data retrieval

- Login uses a Django CSRF token + session cookie flow (same as a browser).
- Device state is scraped from portal HTML detail pages with BeautifulSoup.
- Because there is no official API, portal DOM changes can break parsing and may require integration updates.
- Outbound portal requests use a stable User-Agent of `HomeAssistant-iGuardStove` (no integration release number) so Release Please version bumps cannot drift the request identity.

## Polling & discovery

- Device pages are polled on a configurable interval (**30–300 seconds**, default **60**).
- New stoves on an existing account are discovered automatically every **6 hours**.

## Lock control

The portal exposes a single lock **toggle** action (not separate lock/unlock endpoints). The integration must read the current lock state before POSTing so it does not double-flip.

For safety:

- The **Stove Lock** entity is **disabled by default**.
- **Remote Unlock** is a separate option and also defaults to off.

## Activity events

Events are parsed from the "Today's Events" table on the same device detail HTML fetched each poll (**no extra HTTP requests**).

### Supported event types

| Event type | Portal label |
|---|---|
| `activity_seen` | Activity Seen |
| `night_lock_on` | Night Lock ON |
| `night_lock_off` | Night Lock OFF |
| `stove_on` | Stove Turned ON |
| `stove_off` | Stove Turned OFF |
| `motion_auto_resumed` | Motion Auto Resumed |
| `auto_shut_off` | Auto Shut Off / Shut Off |
| `emergency_button` | Emergency Button Pressed |
| `temperature_alert` | Temperature Alert |
| `lost_communication` | Lost Communication |
| `bypassed` | iGuardStove Bypassed |
| `no_activity_grace_period` | No Activity During Grace Period |
| `unknown` | Unmapped labels (`raw_label` kept as an attribute) |

### Deduplication & emission

- **No replay on startup**: Events already on the portal page at setup or HA restart are seeded into dedup memory and not emitted as new.
- **Timezone**: Portal display times (from `/static/tz.js`) are combined with the Home Assistant local date and interpreted in the HA local timezone.
- **Oldest-first**: Multiple new events in one refresh are emitted oldest-first so automations see correct order.
- **Persistence**: Fingerprints are stored in Home Assistant storage with a **48-hour** rolling window (and a newest-500 cap) so reloads keep dedup state.

## Related docs

- [Migration from multiscrape](MIGRATION.md)
- [Release & branch protection](release.md)
