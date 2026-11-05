# Activity and automations

Return to the [README](../README.md) for setup and essential safety information.

## Activity events

Build notifications and automations from real stove activity — for example when motion is detected, night lock changes, or the stove shuts off.

Supported events include:

- Motion Detected (Activity Seen)
- Night Lock On / Off
- Stove Turned On / Off
- Motion Auto Resumed
- Auto Shut Off
- Stove Left On Overnight
- Left-On Condition Cleared
- Emergency Button Pressed
- Temperature Alert
- Lost Communication
- iGuardStove Bypassed
- No Activity During Grace Period

<details>
<summary>Technical details (for contributors)</summary>

Event parsing, deduplication, timezone handling, and persistence are documented in [docs/ARCHITECTURE.md](ARCHITECTURE.md).

</details>

---

## Automation blueprints

A **blueprint** is a pre-built automation you can import with one click — no YAML or coding required.

### Included blueprints

1. **iGuardStove - Event Action Runner**: Trigger custom actions (notifications, lights, sirens, TTS, or scripts) when selected iGuardStove events occur.
   [![Import Blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fandrewtryder%2Fha-iguardstove%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Figuardstove%2Fselected_event_actions.yaml)

2. **iGuardStove - Stove Safety Notification**: Guided mobile safety alerts with customizable titles and optional critical notification sounds (can bypass silent mode on supported devices).
   [![Import Blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fandrewtryder%2Fha-iguardstove%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Figuardstove%2Fsafety_notification.yaml)

### Blueprint safety principles

To preserve the safety model of iGuardStove:

- **No automatic unlocking**: These blueprints only run notifications and actions. They will **never** unlock the stove (e.g. via presence, schedules, or voice).
- **Manual lock opt-in**: The Master lock entity remains disabled by default until you enable it.

---
