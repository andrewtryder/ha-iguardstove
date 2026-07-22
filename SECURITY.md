# Security Policy

## Supported Versions

Only the latest release of `ha-iguardstove` is supported for security updates.

| Version | Supported          |
| ------- | ------------------ |
| v1.x    | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in this Home Assistant integration:

1. **Do NOT open a public GitHub issue.**
2. Report the vulnerability privately to the project maintainers via GitHub Security Advisories or direct maintainer contact.
3. Please include:
   - Description of the vulnerability and potential impact.
   - Steps to reproduce or proof-of-concept.
   - Any suggested remediations.

We will acknowledge receipt within 48 hours and work on a patch promptly.

## Security & Operational Safety Warnings

### 1. Physical Appliance Control Safety
This integration interacts with physical stove safety hardware (iGuardStove / iGuardFire).
- **Lock / Unlock Operations**: Changing the lock state remotely controls physical gas/electric stove cut-off functions.
- **Voice Assistants & Automations**: Automating stove unlock commands via voice assistants (Alexa, Google Assistant, Siri) or automated triggers carries inherent safety risks. The `lock` entity is **disabled by default** in Home Assistant to prevent accidental physical activation. Users must explicitly enable the entity in Home Assistant UI before sending physical commands.

### 2. Authentication & Credential Storage
- The integration authenticates against `manage.iguardfire.com` using HTTP web form login (session cookie & CSRF token).
- Credentials stored in Home Assistant configuration entries are protected by standard Home Assistant file permissions.

### 3. Portal & Web Scraping Dependencies
- Data is retrieved via HTML web scraping of the manufacturer's cloud portal every 60 seconds.
- Changes to the HTML DOM structure of `manage.iguardfire.com` or unexpected portal outages can impair state updates or control actions.
