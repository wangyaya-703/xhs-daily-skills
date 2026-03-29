#!/usr/bin/env bash
# 检查是否在 XHS 日报执行时间窗口内（09:00-12:00 Asia/Shanghai）
set -euo pipefail

HOUR="$(TZ=Asia/Shanghai date +%H)"
TODAY="$(TZ=Asia/Shanghai date +%Y-%m-%d)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK_FILE="$(cd "$SCRIPT_DIR/.." && pwd)/.push_lock"

LOCK_DATE=""
if [ -f "$LOCK_FILE" ]; then
  if [ -x /usr/bin/python3 ]; then
    LOCK_DATE="$(/usr/bin/python3 - "$LOCK_FILE" <<'PY' 2>/dev/null || true
import json
import sys

try:
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        print(json.load(f).get("date", ""))
except Exception:
    print("")
PY
)"
  else
    LOCK_DATE="$(grep -Eo '"date"[[:space:]]*:[[:space:]]*"[0-9]{4}-[0-9]{2}-[0-9]{2}"' "$LOCK_FILE" | head -n1 | sed -E 's/.*"([0-9]{4}-[0-9]{2}-[0-9]{2})"/\1/' || true)"
  fi
fi

if [ "$LOCK_DATE" = "$TODAY" ]; then
  echo "SKIP: $TODAY 的 XHS 日报已推送过。"
  exit 0
fi

if [ "$HOUR" -ge 9 ] && [ "$HOUR" -lt 12 ]; then
  echo "PENDING: 当前在执行窗口内（09:00-12:00），继续执行。"
  exit 1
fi

echo "SKIP: 当前不在执行窗口（09:00-12:00），跳过。"
exit 0
