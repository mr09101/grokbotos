#!/bin/bash
# Build-time payload installer. No network. Package managers are skipped.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=tests/assert.sh
source "${root}/tests/assert.sh"

script="${root}/build_files/install-grokbot-app.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

core="${tmp}/core"
make_core_path "$core"
export PATH="${core}:/usr/bin:/bin"

run() {
    # shellcheck disable=SC2093
    env \
        GROKBOT_DESTDIR="${DESTDIR}" \
        GROKBOT_APP_SOURCE="${GROKBOT_APP_SOURCE:-}" \
        GROKBOT_APP_SHA256="${GROKBOT_APP_SHA256:-}" \
        GROKBOT_APP_KIND="${GROKBOT_APP_KIND:-auto}" \
        GROKBOT_APP_EXEC="${GROKBOT_APP_EXEC:-}" \
        GROKBOT_FLATPAK_ID="${GROKBOT_FLATPAK_ID:-}" \
        GROKBOT_WEB_URL="${GROKBOT_WEB_URL:-}" \
        GROKBOT_LOCAL_PAYLOAD="${GROKBOT_LOCAL_PAYLOAD:-${tmp}/no-payload}" \
        GROKBOT_SHA256SUMS="${GROKBOT_SHA256SUMS:-${tmp}/no-sums}" \
        GROKBOT_SKIP_PACKAGE_INSTALL="${GROKBOT_SKIP_PACKAGE_INSTALL:-}" \
        GROKBOT_DISABLE_BUNDLED_APP="${GROKBOT_DISABLE_BUNDLED_APP:-1}" \
        GROKBOT_TARGET_ARCH="${GROKBOT_TARGET_ARCH:-}" \
        GROKBOT_DRY_RUN="${GROKBOT_DRY_RUN:-}" \
        bash "$script"
}

reset_env() {
    unset GROKBOT_APP_SOURCE GROKBOT_APP_SHA256 GROKBOT_APP_KIND GROKBOT_APP_EXEC
    unset GROKBOT_FLATPAK_ID GROKBOT_WEB_URL GROKBOT_LOCAL_PAYLOAD GROKBOT_SHA256SUMS
    unset GROKBOT_SKIP_PACKAGE_INSTALL GROKBOT_DISABLE_BUNDLED_APP GROKBOT_TARGET_ARCH
    unset GROKBOT_DRY_RUN
    DESTDIR="${tmp}/root-$$"
}

expect_fail() {
    local code=0
    run >"${tmp}/out" 2>"${tmp}/err" || code=$?
    [[ "$code" -ne 0 ]] || fail "expected failure, got success: $(cat "${tmp}/out" "${tmp}/err")"
}

reset_env
DESTDIR="${tmp}/placeholder"
run >"${tmp}/out"
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_MODE="placeholder"'
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_WEB_URL=""'
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_APP_ID="firefox"'
assert_contains "${tmp}/out" "placeholder"

reset_env
DESTDIR="${tmp}/web"
GROKBOT_WEB_URL="https://example.com/grok"
run >/dev/null
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_WEB_URL="https://example.com/grok"'
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_MODE="placeholder"'

reset_env
DESTDIR="${tmp}/bad-url"
# The dollar sign must stay literal so the installer rejects it.
# shellcheck disable=SC2016
GROKBOT_WEB_URL='https://example.com/$(reboot)'
expect_fail
assert_contains "${tmp}/err" "unsafe characters"

reset_env
DESTDIR="${tmp}/ftp"
GROKBOT_WEB_URL="ftp://example.com/grok"
expect_fail

payload="${tmp}/Grok.AppImage"
printf 'grok-bytes\n' >"$payload"
hash=$(sha256sum "$payload" | awk '{print $1}')

reset_env
DESTDIR="${tmp}/no-sum"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_KIND="appimage"
expect_fail
assert_contains "${tmp}/err" "checksum"

reset_env
DESTDIR="${tmp}/bad-sum"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_SHA256="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
GROKBOT_APP_KIND="appimage"
expect_fail
assert_contains "${tmp}/err" "checksum mismatch"

reset_env
DESTDIR="${tmp}/appimage"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_SHA256="$hash"
run >/dev/null
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_MODE="native"'
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_EXEC="/usr/lib/grokbot/grokbot-native"'
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_APP_ID="grokbot"'
[[ -x "${DESTDIR}/usr/lib/grokbot/grokbot.AppImage" ]]
assert_contains "${DESTDIR}/usr/lib/grokbot/grokbot-native" "APPIMAGE_EXTRACT_AND_RUN"
assert_contains "${DESTDIR}/usr/lib/grokbot/grokbot-native" "/usr/lib/grokbot/grokbot.AppImage"
bash -n "${DESTDIR}/usr/lib/grokbot/grokbot-native"

reset_env
DESTDIR="${tmp}/http"
GROKBOT_APP_SOURCE="http://example.com/grok.AppImage"
GROKBOT_APP_SHA256="$hash"
expect_fail
assert_contains "${tmp}/err" "https://"

plain="${tmp}/payload"
printf 'plain-bytes\n' >"$plain"
plain_hash=$(sha256sum "$plain" | awk '{print $1}')
printf '%s  payload\n' "$plain_hash" >"${tmp}/SHA256SUMS"

reset_env
DESTDIR="${tmp}/need-kind"
GROKBOT_LOCAL_PAYLOAD="$plain"
GROKBOT_SHA256SUMS="${tmp}/SHA256SUMS"
expect_fail
assert_contains "${tmp}/err" "GROKBOT_APP_KIND"

reset_env
DESTDIR="${tmp}/binary"
GROKBOT_LOCAL_PAYLOAD="$plain"
GROKBOT_SHA256SUMS="${tmp}/SHA256SUMS"
GROKBOT_APP_KIND="binary"
run >/dev/null
[[ -x "${DESTDIR}/usr/lib/grokbot/grokbot" ]]
assert_contains "${DESTDIR}/usr/lib/grokbot/grokbot-native" "exec /usr/lib/grokbot/grokbot"
bash -n "${DESTDIR}/usr/lib/grokbot/grokbot-native"

reset_env
DESTDIR="${tmp}/rpm-missing-exec"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_SHA256="$hash"
GROKBOT_APP_KIND="rpm"
GROKBOT_SKIP_PACKAGE_INSTALL=1
expect_fail
assert_contains "${tmp}/err" "GROKBOT_APP_EXEC"

reset_env
DESTDIR="${tmp}/rpm"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_SHA256="$hash"
GROKBOT_APP_KIND="rpm"
GROKBOT_APP_EXEC="/usr/bin/grokbot"
GROKBOT_SKIP_PACKAGE_INSTALL=1
run >/dev/null
assert_contains "${DESTDIR}/usr/lib/grokbot/grokbot-native" "exec /usr/bin/grokbot"
assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_MODE="native"'
bash -n "${DESTDIR}/usr/lib/grokbot/grokbot-native"

reset_env
DESTDIR="${tmp}/flatpak"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_SHA256="$hash"
GROKBOT_APP_KIND="flatpak"
GROKBOT_FLATPAK_ID="org.example.GrokBot"
GROKBOT_SKIP_PACKAGE_INSTALL=1
run >/dev/null
assert_contains "${DESTDIR}/usr/lib/grokbot/grokbot-native" "exec /usr/bin/flatpak run org.example.GrokBot"
bash -n "${DESTDIR}/usr/lib/grokbot/grokbot-native"

reset_env
DESTDIR="${tmp}/flatpak-bad"
GROKBOT_APP_SOURCE="$payload"
GROKBOT_APP_SHA256="$hash"
GROKBOT_APP_KIND="flatpak"
GROKBOT_FLATPAK_ID="not-an-id"
GROKBOT_SKIP_PACKAGE_INSTALL=1
expect_fail

AMD64_URL="https://downloads.cursor.com/grokbot/stable/92808c0ad869b2e3725dbc3b8fa2fcc991687502/linux/x64/grok-bot-0.71.2-1.x86_64.rpm"
AMD64_SHA="ba68a9332675238deb3102dfcdab6d6e7978fa2aa281df5bbf11cbb61a19418a"
ARM64_URL="https://downloads.cursor.com/grokbot/stable/92808c0ad869b2e3725dbc3b8fa2fcc991687502/linux/arm64/grok-bot-0.71.2-1.aarch64.rpm"
ARM64_SHA="9ff82fb7468ce08509e9a67945e96bc72fa2fb35283dc6132060e90ddd5da0be"

reset_env
DESTDIR="${tmp}/dry-amd64"
GROKBOT_DISABLE_BUNDLED_APP=0
GROKBOT_TARGET_ARCH=amd64
GROKBOT_DRY_RUN=1
run >"${tmp}/out"
assert_contains "${tmp}/out" "$AMD64_URL"
assert_contains "${tmp}/out" "$AMD64_SHA"
assert_contains "${tmp}/out" "target_arch=amd64"
assert_contains "${tmp}/out" "kind=rpm"

reset_env
DESTDIR="${tmp}/dry-arm64"
GROKBOT_DISABLE_BUNDLED_APP=0
GROKBOT_TARGET_ARCH=aarch64
GROKBOT_DRY_RUN=1
run >"${tmp}/out"
assert_contains "${tmp}/out" "$ARM64_URL"
assert_contains "${tmp}/out" "$ARM64_SHA"
assert_contains "${tmp}/out" "target_arch=arm64"

reset_env
DESTDIR="${tmp}/dry-bad-arch"
GROKBOT_DISABLE_BUNDLED_APP=0
GROKBOT_TARGET_ARCH=ppc64le
GROKBOT_DRY_RUN=1
expect_fail
assert_contains "${tmp}/err" "unsupported architecture"

# A tiny RPM with the official layout. dnf is not used; DESTDIR extracts
# with rpm2cpio. The host arch is the RPM arch.
case "$(uname -m)" in
    x86_64) host_target=amd64 ;;
    aarch64) host_target=arm64 ;;
    *)
        echo "test-install-grokbot-app.sh: skipping rpm fixture on $(uname -m)" >&2
        host_target=""
        ;;
esac

if [[ -n "$host_target" ]]; then
    command -v rpmbuild >/dev/null
    command -v rpm2cpio >/dev/null
    command -v cpio >/dev/null
    rpm_home="${tmp}/rpmhome"
    mkdir -p "${rpm_home}/rpmbuild/SPECS"
    cat >"${rpm_home}/rpmbuild/SPECS/grok-bot.spec" <<'EOF'
Name: grok-bot
Version: 0.0.1
Release: 1
Summary: fixture
License: MIT

%description
fixture

%install
mkdir -p "%{buildroot}/opt/Grok Bot"
mkdir -p %{buildroot}/usr/share/applications
printf '#!/bin/sh\n' > "%{buildroot}/opt/Grok Bot/grok-bot"
printf 'sandbox\n' > "%{buildroot}/opt/Grok Bot/chrome-sandbox"
chmod 755 "%{buildroot}/opt/Grok Bot/grok-bot"
chmod 755 "%{buildroot}/opt/Grok Bot/chrome-sandbox"
cat > %{buildroot}/usr/share/applications/grok-bot.desktop << 'DESK'
[Desktop Entry]
Name=Grok Bot
Exec=grok-bot %U
StartupWMClass=grok-bot
MimeType=x-scheme-handler/grokbot;x-scheme-handler/sand;
Type=Application
DESK

%files
"/opt/Grok Bot"
/usr/share/applications/grok-bot.desktop
EOF
    if ! HOME="$rpm_home" rpmbuild -bb "${rpm_home}/rpmbuild/SPECS/grok-bot.spec" >"${tmp}/rpmbuild.log" 2>&1; then
        cat "${tmp}/rpmbuild.log" >&2
        fail "rpmbuild failed"
    fi
    fixture=$(find "${rpm_home}/rpmbuild/RPMS" -name '*.rpm' -print -quit)
    [[ -n "$fixture" ]]
    fixture_sha=$(sha256sum "$fixture" | awk '{print $1}')

    reset_env
    DESTDIR="${tmp}/official"
    GROKBOT_DISABLE_BUNDLED_APP=0
    GROKBOT_TARGET_ARCH="$host_target"
    GROKBOT_APP_SOURCE="$fixture"
    GROKBOT_APP_SHA256="$fixture_sha"
    GROKBOT_APP_KIND=rpm
    run >/dev/null
    [[ -x "${DESTDIR}/usr/lib/grokbot/app/grok-bot" ]]
    [[ ! -e "${DESTDIR}/opt/Grok Bot/grok-bot" ]]
    [[ "$(stat -c %a "${DESTDIR}/usr/lib/grokbot/app/chrome-sandbox")" == "4755" ]]
    assert_contains "${DESTDIR}/usr/bin/grok-bot" "--ozone-platform=wayland"
    assert_contains "${DESTDIR}/usr/bin/grok-bot" "--enable-features=UseOzonePlatform"
    assert_contains "${DESTDIR}/usr/bin/grok-bot" "exec /usr/lib/grokbot/app/grok-bot"
    if grep -E '^[[:space:]]*exec ' "${DESTDIR}/usr/bin/grok-bot" | grep -F -q '/opt/Grok Bot'; then
        fail "wrapper exec still points at the spaced /opt path"
    fi
    bash -n "${DESTDIR}/usr/bin/grok-bot"
    assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_MODE="native"'
    assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_APP_ID="grok-bot"'
    assert_contains "${DESTDIR}/etc/grokbot/app.conf" 'GROKBOT_EXEC="/usr/bin/grok-bot"'
    assert_contains "${DESTDIR}/etc/xdg/mimeapps.list" "x-scheme-handler/grokbot=grok-bot.desktop"
    assert_contains "${DESTDIR}/etc/xdg/mimeapps.list" "x-scheme-handler/sand=grok-bot.desktop"
    [[ ! -e "${DESTDIR}/etc/yum.repos.d/grok-bot.repo" ]]
    [[ ! -e "${DESTDIR}/etc/apparmor.d/grok-bot" ]]
    assert_contains "${DESTDIR}/usr/share/applications/grok-bot.desktop" "StartupWMClass=grok-bot"

    case "$host_target" in
        amd64) other=arm64 ;;
        arm64) other=amd64 ;;
    esac
    reset_env
    DESTDIR="${tmp}/official-arch"
    GROKBOT_DISABLE_BUNDLED_APP=0
    GROKBOT_TARGET_ARCH="$other"
    GROKBOT_APP_SOURCE="$fixture"
    GROKBOT_APP_SHA256="$fixture_sha"
    GROKBOT_APP_KIND=rpm
    expect_fail
    assert_contains "${tmp}/err" "does not match target"
fi

echo "PASS test-install-grokbot-app.sh"
