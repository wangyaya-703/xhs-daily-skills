#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
PRE_COMMIT_HOOK="$ROOT_DIR/.git/hooks/pre-commit"
PRE_PUSH_HOOK="$ROOT_DIR/.git/hooks/pre-push"

cat > "$PRE_COMMIT_HOOK" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel)"
"$repo_root/scripts/check-secrets.sh" --staged
HOOK

cat > "$PRE_PUSH_HOOK" <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel)"

# Equivalent local gate before remote push:
# 1) secret-scan (gitleaks + deterministic rules over repo files)
"$repo_root/scripts/check-secrets.sh"

# 2) secret-leak-scan (custom repo + history checks)
python3 "$repo_root/scripts/security/scan_secrets.py" --mode repo
python3 "$repo_root/scripts/security/scan_secrets.py" --mode history
HOOK

chmod +x "$PRE_COMMIT_HOOK" "$PRE_PUSH_HOOK"
echo "Installed pre-commit hook: $PRE_COMMIT_HOOK"
echo "Installed pre-push hook: $PRE_PUSH_HOOK"
