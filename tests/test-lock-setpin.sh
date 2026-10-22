#!/bin/bash
# shellcheck disable=SC2016  # $y$ / $6$ are literal hash prefixes
# lock-setpin.sh (security review #7): 6+ characters, yescrypt and sha512
# hashes verified through libcrypt, wrong-PIN lockout. Fake shadow and
# chpasswd; the real account is never touched.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=tests/assert.sh
source "${root}/tests/assert.sh"
helper="${root}/system_files/usr/lib/grokbot/lock-setpin.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

me=$(id -un)
export SUDO_USER=$me GROKBOT_LOCK_STATE_DIR="$tmp/state" GROKBOT_FAILLOCK=true
export GROKBOT_GETSHADOW="$tmp/getshadow" GROKBOT_CHPASSWD="$tmp/chpasswd"
cat >"$GROKBOT_CHPASSWD" <<SH
#!/bin/bash
IFS=: read -r u p
python3 -c '
import ctypes, sys
c = ctypes.CDLL(__import__("ctypes.util").util.find_library("crypt") or "libcrypt.so.2"); c.crypt.restype = ctypes.c_char_p
c.crypt_gensalt.restype = ctypes.c_char_p
s = c.crypt_gensalt(b"\$y\$", 0, None, 0)
print(sys.argv[1] + ":" + c.crypt(sys.argv[2].encode(), s).decode() + ":")' "\$u" "\$p" >"$tmp/shadow"
SH
printf '#!/bin/bash\ncat "%s/shadow"\n' "$tmp" >"$GROKBOT_GETSHADOW"
chmod +x "$GROKBOT_CHPASSWD" "$GROKBOT_GETSHADOW"

run() { local c=0; bash "$helper" >"$tmp/out" 2>"$tmp/err" <<<"$1" || c=$?; echo "$c"; }

[[ $(run "12345") == 4 ]] || fail "5-character PIN accepted"
[[ $(run "123456") == 0 ]] || fail "first PIN refused: $(cat "$tmp/err")"
grep -q '\$y\$' "$tmp/shadow" || fail "not yescrypt"
[[ -f $GROKBOT_LOCK_STATE_DIR/$me ]] || fail "no marker"
# change with the right current PIN (yescrypt hash)
[[ $(run $'123456\n654321') == 0 ]] || fail "yescrypt current PIN not verified: $(cat "$tmp/err")"
# sha512 hashes from older images still verify
python3 -c '
import ctypes, sys
c = ctypes.CDLL(__import__("ctypes.util").util.find_library("crypt") or "libcrypt.so.2"); c.crypt.restype = ctypes.c_char_p
print(sys.argv[1] + ":" + c.crypt(b"654321", b"$6$abcdefgh").decode() + ":")' "$me" >"$tmp/shadow"
[[ $(run $'654321\n111111') == 0 ]] || fail "sha512 current PIN not verified"
# wrong PINs: 5 strikes, then locked out even with the right one
for _ in 1 2 3 4 5; do
    [[ $(GROKBOT_NO_SLEEP=1 run $'000000\n222222') == 3 ]] || fail "wrong PIN accepted"
done
[[ $(run $'111111\n222222') == 5 ]] || fail "no lockout after 5 wrong PINs"
assert_contains "$tmp/err" "too many wrong PINs"
# lockout expired: the right PIN works and clears the counter
echo "5 1" >"$GROKBOT_LOCK_STATE_DIR/.fail-$me"
[[ $(run $'111111\n222222') == 0 ]] || fail "right PIN refused after lockout ended"
[[ ! -e $GROKBOT_LOCK_STATE_DIR/.fail-$me ]] || fail "counter not cleared"
# an empty/garbage stored hash never matches
echo "$me:!:" >"$tmp/shadow"
[[ $(run $'!\n333333') == 3 ]] || fail "locked hash matched"
grep -q "pam_faillock.so preauth" "${root}/system_files/etc/pam.d/swaylock" || fail "swaylock has no faillock"
echo "PASS test-lock-setpin.sh"
