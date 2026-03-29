#!/usr/bin/env bash
# 检查 bb-browser XHS 登录态是否健康
set -euo pipefail

export PATH=/opt/homebrew/bin:$HOME/.npm-global/bin:$PATH
COOKIE_FILE="$HOME/.bb-browser/browser/user-data/Default/Cookies"

if [ ! -f "$COOKIE_FILE" ]; then
  echo "WARN: Cookie 文件不存在，bb-browser 可能未初始化。"
  exit 1
fi

COOKIE_AGE_DAYS="$(/usr/bin/python3 - "$COOKIE_FILE" <<'PY'
import os
import sys
import time

mtime = os.path.getmtime(sys.argv[1])
print(int((time.time() - mtime) / 86400))
PY
)"

if [ "$COOKIE_AGE_DAYS" -ge 3 ]; then
  echo "WARN: Cookie 已 ${COOKIE_AGE_DAYS} 天未更新，登录态可能过期。"
  echo "建议手动登录：bb-browser open https://www.xiaohongshu.com 然后扫码登录。"
  exit 1
fi

if ! command -v bb-browser >/dev/null 2>&1; then
  echo "WARN: 未找到 bb-browser 命令，无法完成在线检查。"
  exit 1
fi

bb-browser open https://www.xiaohongshu.com >/dev/null 2>&1 || true
sleep 3
SNAPSHOT="$(bb-browser snapshot 2>&1 | head -n 120 || true)"

if echo "$SNAPSHOT" | grep -Eqi '登录|login|请先登录|立即登录|扫码'; then
  echo "WARN: 检测到登录提示，需要重新登录。"
  echo "请手动执行：bb-browser open https://www.xiaohongshu.com 然后扫码登录。"
  exit 1
fi

echo "OK: bb-browser XHS 登录态正常（Cookie ${COOKIE_AGE_DAYS} 天前更新）"
exit 0
