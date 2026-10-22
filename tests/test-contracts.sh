#!/bin/bash
# The image build stays wired to the new session, and the old names that
# would break GHCR / kickstart are still the ones the workflows expect.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=tests/assert.sh
source "${root}/tests/assert.sh"
cd "$root"

if grep -n 'COPY orchestrator' Containerfile; then
    fail "Containerfile still copies the orchestrator into the image"
fi
if grep -n 'legacy' Containerfile; then
    fail "Containerfile references legacy/"
fi
# Security review L: the old orchestrator (unauthenticated web shell) is
# gone from the repository, not just from the image.
if [[ -e legacy/orchestrator || -e orchestrator ]]; then
    fail "legacy orchestrator code is back in the repository"
fi
# Security review #8: base image and bootc-image-builder pinned by digest.
grep -qE '^FROM [^ ]+@sha256:[0-9a-f]{64}' Containerfile || fail "Containerfile base is not pinned by digest"
grep -qE '^BIB_IMAGE="[^"]+@sha256:[0-9a-f]{64}"' grokbotos.env || fail "BIB_IMAGE is not pinned by digest"

if grep -RInE '(^|[^[:alnum:]_])aios([^[:alnum:]_]|$)' \
    system_files build_files Containerfile Justfile; then
    fail "aios is still wired into the image build"
fi

assert_contains system_files/etc/sway/config "/usr/local/bin/grokbot-kiosk"
assert_contains system_files/etc/sway/config "Mod4+space"
assert_contains system_files/etc/sway/config "Mod1+space"
assert_contains system_files/etc/sway/config "Mod4+g"
assert_contains system_files/etc/sway/config "Mod1+g"
assert_contains system_files/etc/sway/config "Mod1+Tab"
assert_contains system_files/etc/sway/config "Mod1+F4"
assert_contains system_files/etc/sway/config "mode invisible"
assert_contains system_files/etc/systemd/system/getty@tty1.service.d/autologin.conf "autologin grokbot"
assert_contains system_files/usr/lib/tmpfiles.d/grokbot-home.conf "/var/home/grokbot"
assert_contains build_files/build.sh "install-grokbot-app.sh"
assert_contains build_files/build.sh 'NAME="Grok Bot OS"'
assert_contains build_files/build.sh "grokbot-open-browser"
assert_contains grokbotos.env "IMAGE_NAME=grokbotos"
assert_contains disk_config/iso.toml "ghcr.io/head77x/grokbotos:latest"
assert_contains .github/workflows/build-disk.yml 's#ghcr.io/head77x/grokbotos:latest#'
assert_contains .github/workflows/build.yml "grokbotos-arm64"
assert_contains system_files/usr/local/bin/grokbot-kiosk "while true"
assert_contains build_files/install-grokbot-app.sh "ba68a9332675238deb3102dfcdab6d6e7978fa2aa281df5bbf11cbb61a19418a"
assert_contains build_files/install-grokbot-app.sh "9ff82fb7468ce08509e9a67945e96bc72fa2fb35283dc6132060e90ddd5da0be"
assert_contains build_files/install-grokbot-app.sh "grok-bot-0.71.2-1.x86_64.rpm"
assert_contains build_files/install-grokbot-app.sh "grok-bot-0.71.2-1.aarch64.rpm"
assert_contains build_files/install-grokbot-app.sh "--ozone-platform=wayland"
assert_contains build_files/install-grokbot-app.sh "--enable-features=UseOzonePlatform"
# Korean input reaches Grok Bot (Electron, Wayland) only with the IME flag.
assert_contains build_files/install-grokbot-app.sh "--enable-wayland-ime"
assert_contains system_files/etc/xdg/fcitx5/profile "Name=hangul"
assert_contains build_files/install-grokbot-app.sh "tsflags=noscripts"
assert_contains build_files/install-grokbot-app.sh "x-scheme-handler/grokbot=grok-bot.desktop"
assert_contains build_files/install-grokbot-app.sh "x-scheme-handler/sand=grok-bot.desktop"
assert_contains build_files/build.sh "mesa-libgbm"
assert_contains build_files/build.sh "cups-libs"
assert_contains .github/workflows/build.yml "GROKBOT_TARGET_ARCH"

python3 - <<'PY'
import json, pathlib, sys
try:
    import yaml
except ImportError:
    sys.exit(0)
root = pathlib.Path(".")
for path in root.glob(".github/workflows/*.yml"):
    with path.open() as handle:
        docs = list(yaml.safe_load_all(handle))
    if not docs or not isinstance(docs[0], dict):
        raise SystemExit(f"{path} is not a workflow mapping")
    if "on" not in docs[0] and True not in docs[0]:
        # PyYAML 5.1+ parses bare `on` as True.
        raise SystemExit(f"{path} has no 'on' key: {list(docs[0])}")
print("workflow yaml ok")
PY

# grokbotd (docs/OS_API.md): user service, enabled globally, loopback only.
assert_contains build_files/build.sh "systemctl --global enable grokbotd.service"
assert_contains system_files/usr/lib/systemd/user/grokbotd.service "ExecStart=/usr/local/bin/grokbotd"
assert_contains system_files/usr/lib/grokbot/grokbotd/server.py '("127.0.0.1", paths.http_port())'
if grep -n '"0.0.0.0"' system_files/usr/lib/grokbot/grokbotd/*.py; then
    fail "grokbotd must not bind all interfaces"
fi

# The kiosk password is the short screen-lock PIN: never an SSH login.
assert_contains system_files/etc/ssh/sshd_config.d/10-grokbot-kiosk.conf "DenyUsers grokbot"

echo "PASS test-contracts.sh"
