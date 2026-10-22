#!/bin/bash
# grokbot-launch is the single UI entry: placeholder Firefox, or one native executable.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=tests/assert.sh
source "${root}/tests/assert.sh"

launch="${root}/system_files/usr/local/bin/grokbot-launch"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

export HOME="${tmp}/home"
mkdir -p "$HOME"
core="${tmp}/core"
fake="${tmp}/bin"
make_core_path "$core"
mkdir -p "$fake"
export FAKE_FIREFOX_LOG="${tmp}/firefox.log"
cat >"${fake}/firefox" <<'EOF'
#!/bin/bash
printf '%s\n' "$@" > "${FAKE_FIREFOX_LOG:?}"
exit 0
EOF
chmod 755 "${fake}/firefox"
export PATH="${fake}:${core}"
export GROKBOT_CONF="${tmp}/app.conf"

cat >"$GROKBOT_CONF" <<'EOF'
GROKBOT_MODE="placeholder"
GROKBOT_WEB_URL=""
GROKBOT_APP_ID="firefox"
GROKBOT_EXEC=""
EOF
"$launch"
assert_contains "$FAKE_FIREFOX_LOG" "--kiosk"
assert_contains "$FAKE_FIREFOX_LOG" "--no-remote"
assert_contains "$FAKE_FIREFOX_LOG" "--new-instance"
assert_contains "$FAKE_FIREFOX_LOG" "--profile"
assert_contains "$FAKE_FIREFOX_LOG" "${HOME}/.local/share/grokbot/firefox-profile"
assert_contains "$FAKE_FIREFOX_LOG" "file:///usr/share/grokbot/placeholder.html"
[[ -d "${HOME}/.local/share/grokbot/firefox-profile" ]]

cat >"$GROKBOT_CONF" <<'EOF'
GROKBOT_MODE="placeholder"
GROKBOT_WEB_URL="https://example.com/grok"
GROKBOT_APP_ID="firefox"
GROKBOT_EXEC=""
EOF
: >"$FAKE_FIREFOX_LOG"
"$launch"
assert_contains "$FAKE_FIREFOX_LOG" "https://example.com/grok"
if grep -F -q "placeholder.html" "$FAKE_FIREFOX_LOG"; then
    fail "web URL mode still opened the placeholder page"
fi

mark="${tmp}/native-ran"
cat >"${tmp}/native-app" <<EOF
#!/bin/bash
echo ran > "${mark}"
EOF
chmod 755 "${tmp}/native-app"
cat >"$GROKBOT_CONF" <<EOF
GROKBOT_MODE="native"
GROKBOT_WEB_URL=""
GROKBOT_APP_ID="grokbot"
GROKBOT_EXEC="${tmp}/native-app"
EOF
"$launch"
assert_file "$mark"

cat >"$GROKBOT_CONF" <<'EOF'
GROKBOT_MODE="native"
GROKBOT_WEB_URL=""
GROKBOT_APP_ID="grokbot"
GROKBOT_EXEC="relative-bin"
EOF
code=0
"$launch" >"${tmp}/native-err" 2>&1 || code=$?
[[ "$code" -ne 0 ]]

export PATH="${core}"
cat >"$GROKBOT_CONF" <<'EOF'
GROKBOT_MODE="placeholder"
GROKBOT_WEB_URL=""
GROKBOT_APP_ID="firefox"
GROKBOT_EXEC=""
EOF
code=0
"$launch" >"${tmp}/no-firefox" 2>&1 || code=$?
[[ "$code" -ne 0 ]]
assert_contains "${tmp}/no-firefox" "firefox is not installed"

echo "PASS test-grokbot-launch.sh"
