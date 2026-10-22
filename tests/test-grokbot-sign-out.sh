#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=tests/assert.sh
source "${root}/tests/assert.sh"

signout="${root}/system_files/usr/local/bin/grokbot-sign-out"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

export HOME="${tmp}/home"
mkdir -p "$HOME"
export GROKBOT_LIB="${root}/system_files/usr/lib/grokbot/common.sh"
export GROKBOT_CONF="${tmp}/app.conf"
core="${tmp}/core"
fake="${tmp}/bin"
make_core_path "$core"
mkdir -p "$fake"
export SWAYMSG_LOG="${tmp}/swaymsg.log"
cat >"${fake}/swaymsg" <<'EOF'
#!/bin/bash
printf '%s\n' "$*" > "${SWAYMSG_LOG:?}"
exit 0
EOF
chmod 755 "${fake}/swaymsg"
export PATH="${fake}:${core}"

cat >"$GROKBOT_CONF" <<'EOF'
GROKBOT_MODE="placeholder"
GROKBOT_WEB_URL=""
GROKBOT_APP_ID="firefox"
GROKBOT_EXEC=""
EOF

profile="${HOME}/.local/share/grokbot/firefox-profile"
mkdir -p "${profile}/cookies"
echo secret >"${profile}/cookies/cookie"
keep="${HOME}/.local/share/grokbot/keep"
mkdir -p "$keep"
echo stay >"${keep}/note"

"$signout" >"${tmp}/out"
[[ ! -e "$profile" ]]
assert_file "${keep}/note"
assert_contains "$SWAYMSG_LOG" '[app_id="firefox"] kill'
assert_contains "${tmp}/out" "브라우저 세션을 지웠습니다."

outside="${tmp}/outside"
mkdir -p "$outside"
echo keep-me >"${outside}/secret"
ln -s "$outside" "$profile"
code=0
"$signout" >"${tmp}/symlink-out" 2>&1 || code=$?
[[ "$code" -ne 0 ]]
assert_file "${outside}/secret"
assert_contains "${tmp}/symlink-out" "symlink"

cat >"$GROKBOT_CONF" <<'EOF'
GROKBOT_MODE="native"
GROKBOT_WEB_URL=""
GROKBOT_APP_ID="grokbot"
GROKBOT_EXEC="/usr/lib/grokbot/grokbot-native"
EOF
"$signout" >"${tmp}/native-out" 2>&1
assert_contains "${tmp}/native-out" "로그아웃"

echo "PASS test-grokbot-sign-out.sh"
