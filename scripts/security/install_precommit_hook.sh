#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT_DIR"
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit scripts/security/scan_secrets.py

echo "Installed pre-commit secret scan hook."
echo "Hooks path: $(git config --get core.hooksPath)"
