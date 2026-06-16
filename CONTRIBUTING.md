# Contributing to iGuardStove Custom Integration

Thank you for considering contributing to the **iGuardStove** custom integration! This document outlines local development workflow setup, testing, formatting, and general submission guidelines.

---

## Local Setup

### 1. Initialize Virtual Environment
It is highly recommended to isolate your dependencies using a virtual environment:
```bash
# Create virtual environment
python3 -m venv .venv

# Activate it (on MacOS/Linux)
source .venv/bin/activate

# Install requirements
pip install -r requirements.txt -r requirements_test.txt
```

### 2. Configure Git Hooks (pre-commit)
We use `pre-commit` to verify code layout, trailing whitespace, and formatting automatically during commit preparation:
```bash
pre-commit install
```

---

## Validation & Code Quality

Before pushing code or opening a pull request, run the following automated checks locally:

### 1. Code Formatting and Linting
We enforce standard Python formatting via `ruff`:
```bash
# Check syntax rules
ruff check custom_components/ tests/

# Check formatting compliance
ruff format --check custom_components/ tests/
```

### 2. Execute Tests
Run the test suite using `pytest` to ensure all functionality is preserved:
```bash
python -m pytest
```

To view code coverage details:
```bash
python -m pytest --cov=custom_components/iguardstove --cov-report=term-missing
```

### 3. Structural Validation (`hassfest`)
Validate custom component structure and manifest formatting using the official Home Assistant linter:
```bash
docker run --rm -v "$(pwd)/custom_components:/github/workspace/custom_components" ghcr.io/home-assistant/hassfest
```
