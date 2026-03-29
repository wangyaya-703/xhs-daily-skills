#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT_DIR"

MODE="all"
if [[ "${1:-}" == "--staged" ]]; then
  MODE="staged"
fi

fail() {
  echo "[security] $*" >&2
  exit 1
}

warn() {
  echo "[security] $*" >&2
}

FILES=()
while IFS= read -r line; do
  FILES+=("$line")
done < <(
  if [[ "$MODE" == "staged" ]]; then
    git diff --cached --name-only --diff-filter=ACMRTUXB
  else
    rg --files
  fi
)

if [[ ${#FILES[@]} -eq 0 ]]; then
  exit 0
fi

for f in "${FILES[@]}"; do
  if [[ "$f" == "secrets.env" ]]; then
    fail "Detected tracked secrets file: $f. Keep secrets in local untracked file only."
  fi
done

# Quick deterministic checks for known high-risk literals.
for f in "${FILES[@]}"; do
  [[ -f "$f" ]] || continue
  if rg -n --pcre2 'FEISHU_APP_SECRET\s*=\s*["\x27][^"\x27]{12,}["\x27]' "$f" >/dev/null 2>&1; then
    fail "Hardcoded FEISHU_APP_SECRET found in $f"
  fi
  if rg -n --pcre2 'ARK_API_KEY\s*=\s*["\x27][^"\x27]{12,}["\x27]' "$f" >/dev/null 2>&1; then
    fail "Hardcoded ARK_API_KEY found in $f"
  fi
  if rg -n --pcre2 'app_secret\s*[:=]\s*["\x27][^"\x27]{12,}["\x27]' "$f" >/dev/null 2>&1; then
    fail "Potential hardcoded app_secret found in $f"
  fi
  if rg -n --pcre2 'api[_-]?key\s*[:=]\s*["\x27][A-Za-z0-9_\-]{16,}["\x27]' "$f" >/dev/null 2>&1; then
    fail "Potential hardcoded api key found in $f"
  fi
done

if command -v gitleaks >/dev/null 2>&1; then
  if [[ "$MODE" == "staged" ]]; then
    tmpdir="$(mktemp -d /tmp/xhs-gitleaks-staged.XXXXXX)"
    cleanup() { rm -rf "$tmpdir"; }
    trap cleanup EXIT

    for f in "${FILES[@]}"; do
      [[ -f "$f" ]] || continue
      mkdir -p "$tmpdir/$(dirname "$f")"
      git show ":$f" > "$tmpdir/$f" 2>/dev/null || cp "$f" "$tmpdir/$f"
    done

    gitleaks dir "$tmpdir" --no-banner --redact --config .gitleaks.toml
  else
    gitleaks dir . --no-banner --redact --config .gitleaks.toml
  fi
else
  warn "gitleaks not found. Install it for stronger detection (brew install gitleaks)."
fi

echo "[security] secret scan passed ($MODE)."
