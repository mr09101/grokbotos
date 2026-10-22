#!/bin/bash
# Set the screen-lock PIN of the calling kiosk user. Runs as root via
# /etc/sudoers.d/grokbot-lock; the only allowed caller is the session user.
# stdin: line 1 = new PIN. If a PIN is already set: line 1 = current PIN,
# line 2 = new PIN. The PIN is the user's unix password (swaylock uses PAM).
# Never logs or echoes the PIN.
#
# Wrong current PINs are counted in $state_dir/.fail-<user>: after
# MAX_FAIL wrong answers the helper refuses for LOCKOUT seconds, doubling
# each further time (sudo lets the user call this without limit).
set -euo pipefail
state_dir=${GROKBOT_LOCK_STATE_DIR:-/var/lib/grokbot/lock-pin}
MIN_LEN=6
MAX_FAIL=5
LOCKOUT=300
user=${SUDO_USER:-}
if [[ -z $user || $user == "root" ]]; then
    echo "lock-setpin: must be run through sudo by the session user" >&2
    exit 2
fi
if ! id -u "$user" >/dev/null 2>&1; then
    echo "lock-setpin: unknown user" >&2
    exit 2
fi
mkdir -p "$state_dir"
chmod 0755 "$state_dir"
marker="$state_dir/$user"
failfile="$state_dir/.fail-$user"
shadow_hash() { ${GROKBOT_GETSHADOW:-getent shadow} "$user" | cut -d: -f2; }

# Verify with libcrypt itself, so any hash method works (yescrypt "$y$"
# is the Fedora default; openssl passwd cannot compute it).
pin_matches() {
    PIN_STORED=$1 python3 -c '
import ctypes, hmac, os, sys
c = ctypes.CDLL(__import__("ctypes.util").util.find_library("crypt") or "libcrypt.so.2")
c.crypt.restype = ctypes.c_char_p
c.crypt.argtypes = (ctypes.c_char_p, ctypes.c_char_p)
stored = os.environ["PIN_STORED"].encode()
got = c.crypt(sys.stdin.buffer.read(), stored)
sys.exit(0 if got and stored[:1] == b"$" and hmac.compare_digest(got, stored) else 1)'
}

if [[ -f $marker ]]; then
    fails=0 until=0
    if [[ -f $failfile ]]; then
        read -r fails until <"$failfile" || true
        [[ $fails =~ ^[0-9]+$ ]] || fails=0
        [[ $until =~ ^[0-9]+$ ]] || until=0
    fi
    now=$(date +%s)
    if (( until > now )); then
        echo "lock-setpin: too many wrong PINs; try again in $(( until - now )) s" >&2
        exit 5
    fi
    IFS= read -r current || true
    if ! printf '%s' "$current" | pin_matches "$(shadow_hash)"; then
        fails=$(( fails + 1 ))
        until=0
        if (( fails >= MAX_FAIL )); then
            until=$(( now + LOCKOUT * (1 << (fails - MAX_FAIL < 6 ? fails - MAX_FAIL : 6)) ))
        fi
        printf '%s %s\n' "$fails" "$until" >"$failfile"
        chmod 0600 "$failfile"
        [[ -n ${GROKBOT_NO_SLEEP:-} ]] || sleep 2
        echo "lock-setpin: current PIN is wrong" >&2
        exit 3
    fi
    rm -f "$failfile"
fi
IFS= read -r pin || true
if (( ${#pin} < MIN_LEN || ${#pin} > 64 )); then
    echo "lock-setpin: PIN must be $MIN_LEN-64 characters" >&2
    exit 4
fi
if [[ $pin == *:* ]]; then
    echo "lock-setpin: PIN must not contain ':'" >&2
    exit 4
fi
if [[ -n ${GROKBOT_CHPASSWD:-} ]]; then
    printf '%s:%s\n' "$user" "$pin" | $GROKBOT_CHPASSWD
else
    # chpasswd hashes with the system default (yescrypt).
    printf '%s:%s\n' "$user" "$pin" | chpasswd
fi
date -u +%FT%TZ >"$marker"
chmod 0644 "$marker"
${GROKBOT_FAILLOCK:-faillock} --dir /var/lib/grokbot/faillock --user "$user" --reset 2>/dev/null || true
echo "ok"
