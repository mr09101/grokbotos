#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=tests/assert.sh
source "${root}/tests/assert.sh"

switch="${root}/system_files/usr/local/bin/grokbot-switch"
focus="${root}/system_files/usr/local/bin/grokbot-focus"
open_browser="${root}/system_files/usr/local/bin/grokbot-open-browser"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

export HOME="${tmp}/home"
mkdir -p "$HOME"
core="${tmp}/core"
fake="${tmp}/bin"
make_core_path "$core"
mkdir -p "$fake"
export PATH="${fake}:${core}"

code=0
"$switch" >"${tmp}/no-fuzzel" 2>&1 || code=$?
[[ "$code" -ne 0 ]]
assert_contains "${tmp}/no-fuzzel" "fuzzel is not installed"

export FUZZEL_LOG="${tmp}/fuzzel.log"
cat >"${fake}/fuzzel" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" > "${FUZZEL_LOG:?}"
exit 0
EOF
chmod 755 "${fake}/fuzzel"
"$switch"
assert_contains "$FUZZEL_LOG" "--prompt"
assert_contains "$FUZZEL_LOG" "앱 실행 "

export GROKBOT_CONF="${tmp}/app.conf"
export SWAYMSG_LOG="${tmp}/swaymsg.log"
cat >"$GROKBOT_CONF" <<'EOF'
GROKBOT_MODE="placeholder"
GROKBOT_WEB_URL=""
GROKBOT_APP_ID="firefox"
GROKBOT_EXEC=""
EOF
cat >"${fake}/swaymsg" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" > "${SWAYMSG_LOG:?}"
exit 0
EOF
chmod 755 "${fake}/swaymsg"
"$focus"
assert_contains "$SWAYMSG_LOG" '[app_id="firefox"] focus'

export FAKE_FIREFOX_LOG="${tmp}/browser.log"
cat >"${fake}/firefox" <<'EOF'
#!/bin/bash
printf '%s\n' "$@" > "${FAKE_FIREFOX_LOG:?}"
exit 0
EOF
chmod 755 "${fake}/firefox"
"$open_browser" "https://example.com/login"
assert_contains "$FAKE_FIREFOX_LOG" "--new-window"
assert_contains "$FAKE_FIREFOX_LOG" "--profile"
assert_contains "$FAKE_FIREFOX_LOG" "${HOME}/.local/share/grokbot/external-browser-profile"
assert_contains "$FAKE_FIREFOX_LOG" "https://example.com/login"
if grep -F -q -- "--kiosk" "$FAKE_FIREFOX_LOG"; then
    fail "external browser opened in kiosk mode"
fi
if grep -F -q -- "--no-remote" "$FAKE_FIREFOX_LOG"; then
    fail "external browser used --no-remote and cannot be reused"
fi

echo "PASS test-grokbot-switch.sh"
