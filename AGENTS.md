# AI Agent & Editor Instructions (AGENTS.md)

Welcome! You are working on the `ha-iguardstove` repository, a Home Assistant custom integration for iGuardStove / iGuardFire devices. This file provides strict guidelines, architectural context, and development workflows you **must** follow when analyzing, editing, or testing this codebase.

## 1. Project Overview & Domain Context

*   **Purpose:** This is a first-class Home Assistant custom integration that auto-discovers and integrates iGuardStove devices. It replaces an older `multiscrape` blueprint approach.
*   **Authentication Flow:** The integration authenticates against `manage.iguardfire.com` using a standard session-cookie and Django CSRF token login flow (similar to a web browser).
*   **Data Retrieval:** The integration relies on **web scraping** using `BeautifulSoup` rather than a standard REST API. It scrapes device detail pages.
*   **Polling Interval:** Scraping happens every **60 seconds**.
*   **Lock Mechanism:** The `lock` toggle (`lock` entity) POSTs to the same device page form that the "Lock" button on the website uses. **Critical:** The portal uses a single toggle action (not separate lock/unlock endpoints). Therefore, the integration *must* check the current lock state before acting to avoid double-flips.

## 2. Architecture & Code Organization

*   **`client.py`:** Contains the API interaction logic (`IGuardStoveClient`). This is where all HTTP requests (aiohttp), BeautifulSoup parsing, and CSRF handling live.
*   **`coordinator.py`:** Contains the `IGuardStoveDataUpdateCoordinator` which inherits from Home Assistant's `DataUpdateCoordinator`. This handles the 60-second polling loop and state updates.
*   **`config_flow.py`:** Handles the UI-based setup process. This integration requires **no YAML configuration**.
*   **`sensor.py`, `lock.py`, `event.py`:** Home Assistant entity platform implementations.

## 3. Tooling & Development Workflow

When you are asked to write code, modify files, or run tests, you **must** use the following exact commands to ensure code quality and consistency.

### Environment Setup
You must run tests and linters inside a virtual environment to ensure dependencies (`aiohttp`, `BeautifulSoup`, `pytest`, `pytest-homeassistant-custom-component`, etc.) are resolved correctly.
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements_test.txt
```

### Code Formatting & Linting
This project enforces formatting and linting using `ruff`. You must run these checks after making any code changes:
```bash
ruff check custom_components/ tests/
ruff format custom_components/ tests/
```
Alternatively, you can run the full pre-commit suite:
```bash
pre-commit run --all-files
```

### Testing
Execute the test suite using `pytest`. Ensure the virtual environment is active so local packages are picked up instead of global wrappers (like pipx).
```bash
python -m pytest
```

### Structural Validation (`hassfest`)
To ensure the custom component structure and `manifest.json` are valid according to Home Assistant standards, run:
```bash
docker run --rm -v "$(pwd)/custom_components:/github/workspace/custom_components" ghcr.io/home-assistant/hassfest
```

## 4. Coding Conventions & Home Assistant Rules

*   **Async/Await:** This is an asynchronous integration. All I/O operations (like fetching web pages) *must* be non-blocking and use `aiohttp` via the Home Assistant async utilities. Do not use synchronous `requests`.
*   **Exception Handling:** Handle specific exceptions (e.g., connection errors, auth errors) gracefully and bubble them up to the Coordinator using standard `UpdateFailed` exceptions.
*   **State Updates:** Rely on the `DataUpdateCoordinator` for state. Entities should update their state based on `self.coordinator.data` in their respective `_handle_coordinator_update` methods.
*   **Translations:** Use `strings.json` and the `translations/` directory for localized strings instead of hardcoding strings in the Python files (where applicable).
*   **Release & Version Policy:** Only Release Please changes `manifest.json`, `.release-please-manifest.json`, tags, and `CHANGELOG.md` versions. Feature PRs and edits must use Conventional Commit titles but **never** manually bump version numbers.
*   **Strict Adherence:** Prioritize these instructions unless the user explicitly requests otherwise.
