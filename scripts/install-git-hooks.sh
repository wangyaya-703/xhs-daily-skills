#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
HOOK_PATH="$ROOT_DIR/.git/hooks/pre-commit"

cat > "$HOOK_PATH" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel)"
"$repo_root/scripts/check-secrets.sh" --staged
HOOK

chmod +x "$HOOK_PATH"
echo "Installed pre-commit hook: $HOOK_PATH"
