#!/usr/bin/env bash
set -euo pipefail

# Portfolio Universal Local Validation Contract
# Repository: ha-iguardstove
# Gate: 95% component statement coverage (offline/mock safety-critical)

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -d "$REPO_ROOT/.venv/bin" ]]; then
    export PATH="$REPO_ROOT/.venv/bin:$PATH"
fi

echo "==> [1/7] Verifying toolchain and interpreter"
python --version

echo "==> [2/7] Running pre-commit hooks on all files"
pre-commit run --all-files

echo "==> [3/7] Compiling Python source files"
python -m compileall -q custom_components tests

echo "==> [4/7] Running Ruff lint and formatting checks"
ruff check .
ruff format --check .

echo "==> [5/7] Running Mypy strict type checks"
mypy custom_components tests

echo "==> [6/7] Running Python test suite with offline safety isolation (>=95% coverage)"
pytest

echo "==> [7/7] Verifying clean git working tree"
git diff --exit-code

echo "==> Local validation passed successfully!"
