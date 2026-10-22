#!/bin/bash
# grokbot-factory-reset deletes only a fixture home. The real /var is never used.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=tests/assert.sh
source "${root}/tests/assert.sh"

reset="${root}/system_files/usr/local/bin/grokbot-factory-reset"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

export GROKBOT_LIB="${root}/system_files/usr/lib/grokbot/common.sh"
export GROKBOT_RESET_ROOT="${tmp}/sys"

plant() {
    local base="$1"
    mkdir -p \
        "${base}/var/home/grokbot/.config/GrokBot" \
        "${base}/var/home/grokbot/Apps/demo" \
        "${base}/var/home/admin" \
        "${base}/usr/bin" \
        "${base}/etc"
    echo session >"${base}/var/home/grokbot/.config/GrokBot/session"
    echo app >"${base}/var/home/grokbot/Apps/demo/app"
    echo admin-secret >"${base}/var/home/admin/secret"
    echo binary >"${base}/usr/bin/grok-bot"
    echo machine >"${base}/etc/machine-id"
}

assert_untouched() {
    local base="$1"
    assert_file "${base}/var/home/admin/secret"
    assert_file "${base}/usr/bin/grok-bot"
    assert_file "${base}/etc/machine-id"
    assert_file "${base}/var/home/grokbot/.config/GrokBot/session"
}

plant "$GROKBOT_RESET_ROOT"

code=0
"$reset" >"${tmp}/none.out" 2>"${tmp}/none.err" || code=$?
[[ "$code" -eq 2 ]]
assert_contains "${tmp}/none.err" "아무것도 지우지 않았습니다."
assert_untouched "$GROKBOT_RESET_ROOT"

code=0
"$reset" --confirm nope >"${tmp}/bad.out" 2>"${tmp}/bad.err" || code=$?
[[ "$code" -eq 2 ]]
assert_untouched "$GROKBOT_RESET_ROOT"

"$reset" --dry-run >"${tmp}/dry.out"
assert_contains "${tmp}/dry.out" "dry-run"
assert_contains "${tmp}/dry.out" "remove ${GROKBOT_RESET_ROOT}/var/home/grokbot/.config"
assert_contains "${tmp}/dry.out" "remove ${GROKBOT_RESET_ROOT}/var/home/grokbot/Apps"
if grep -F -q "remove ${GROKBOT_RESET_ROOT}/var/home/admin" "${tmp}/dry.out"; then
    fail "dry-run listed another user's home"
fi
if grep -F -q "remove ${GROKBOT_RESET_ROOT}/usr" "${tmp}/dry.out"; then
    fail "dry-run listed /usr"
fi
assert_untouched "$GROKBOT_RESET_ROOT"

"$reset" --confirm RESET --dry-run >"${tmp}/both.out"
assert_contains "${tmp}/both.out" "dry-run"
assert_untouched "$GROKBOT_RESET_ROOT"

"$reset" --help >"${tmp}/help.out"
assert_contains "${tmp}/help.out" "--confirm RESET"
assert_untouched "$GROKBOT_RESET_ROOT"

mkdir -p "${GROKBOT_RESET_ROOT}/var/lib/grokbot/lock-pin" "${GROKBOT_RESET_ROOT}/var/lib/grokbot/faillock"
date >"${GROKBOT_RESET_ROOT}/var/lib/grokbot/lock-pin/grokbot"
echo "1 0" >"${GROKBOT_RESET_ROOT}/var/lib/grokbot/lock-pin/.fail-grokbot"
echo tally >"${GROKBOT_RESET_ROOT}/var/lib/grokbot/faillock/grokbot"
"$reset" --dry-run >"${tmp}/pin-dry.out"
assert_contains "${tmp}/pin-dry.out" "clear screen-lock PIN"
assert_file "${GROKBOT_RESET_ROOT}/var/lib/grokbot/lock-pin/grokbot"
"$reset" --confirm RESET >"${tmp}/wipe.out"
# Security review #5: the PIN marker and tallies go too; in test mode the
# real password is never touched.
[[ ! -e "${GROKBOT_RESET_ROOT}/var/lib/grokbot/lock-pin/grokbot" ]] || fail "PIN marker kept"
[[ ! -e "${GROKBOT_RESET_ROOT}/var/lib/grokbot/lock-pin/.fail-grokbot" ]] || fail "fail counter kept"
[[ ! -e "${GROKBOT_RESET_ROOT}/var/lib/grokbot/faillock/grokbot" ]] || fail "faillock tally kept"
assert_contains "${tmp}/wipe.out" "test mode"
grep -q "usermod -p '!' grokbot" "$reset" || fail "real reset does not lock the password"
assert_contains "${tmp}/wipe.out" "재부팅은 하지 않았습니다."
[[ -d "${GROKBOT_RESET_ROOT}/var/home/grokbot" ]]
[[ ! -e "${GROKBOT_RESET_ROOT}/var/home/grokbot/.config" ]]
[[ ! -e "${GROKBOT_RESET_ROOT}/var/home/grokbot/Apps" ]]
assert_file "${GROKBOT_RESET_ROOT}/var/home/admin/secret"
assert_file "${GROKBOT_RESET_ROOT}/usr/bin/grok-bot"
assert_file "${GROKBOT_RESET_ROOT}/etc/machine-id"

"$reset" --dry-run >"${tmp}/empty.out"
assert_contains "${tmp}/empty.out" "지울 항목이 없습니다."

# A second wipe of an empty home still does not touch the neighbors.
"$reset" --confirm RESET >"${tmp}/again.out"
assert_file "${GROKBOT_RESET_ROOT}/var/home/admin/secret"

# Symlink inside the home: remove the link, not the target.
echo outside >"${GROKBOT_RESET_ROOT}/outside"
ln -s "${GROKBOT_RESET_ROOT}/outside" "${GROKBOT_RESET_ROOT}/var/home/grokbot/link"
"$reset" --confirm RESET >"${tmp}/link.out"
[[ ! -e "${GROKBOT_RESET_ROOT}/var/home/grokbot/link" ]]
assert_file "${GROKBOT_RESET_ROOT}/outside"

# The home directory itself must not be a symlink.
rmdir "${GROKBOT_RESET_ROOT}/var/home/grokbot"
ln -s "${GROKBOT_RESET_ROOT}/var/home/admin" "${GROKBOT_RESET_ROOT}/var/home/grokbot"
code=0
"$reset" --confirm RESET >"${tmp}/symlink.out" 2>"${tmp}/symlink.err" || code=$?
[[ "$code" -eq 1 ]]
assert_contains "${tmp}/symlink.err" "symlink"
assert_file "${GROKBOT_RESET_ROOT}/var/home/admin/secret"
code=0
"$reset" --dry-run >"${tmp}/symlink-dry.out" 2>"${tmp}/symlink-dry.err" || code=$?
[[ "$code" -eq 1 ]]
assert_file "${GROKBOT_RESET_ROOT}/var/home/admin/secret"

# A parent symlink is also refused, before anything is deleted.
rm -rf -- "${GROKBOT_RESET_ROOT:?}/var"
mkdir -p "${GROKBOT_RESET_ROOT}/real/home/grokbot"
echo stay >"${GROKBOT_RESET_ROOT}/real/home/grokbot/secret"
ln -s "${GROKBOT_RESET_ROOT}/real" "${GROKBOT_RESET_ROOT}/var"
code=0
"$reset" --confirm RESET >"${tmp}/parent.out" 2>"${tmp}/parent.err" || code=$?
[[ "$code" -eq 1 ]]
assert_file "${GROKBOT_RESET_ROOT}/real/home/grokbot/secret"

unset GROKBOT_RESET_ROOT
code=0
"$reset" --dry-run >"${tmp}/noroot.out" 2>"${tmp}/noroot.err" || code=$?
[[ "$code" -eq 2 ]]
assert_contains "${tmp}/noroot.err" "아무것도 지우지 않았습니다."

if grep -n 'factory-reset' "${root}/system_files/etc/sway/config"; then
    fail "factory reset is bound to a sway key"
fi

echo "PASS test-grokbot-factory-reset.sh"
